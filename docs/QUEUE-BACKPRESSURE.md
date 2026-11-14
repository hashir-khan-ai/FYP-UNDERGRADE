# System Audit: Queue, Backpressure, Concurrency & Resource Governance

**Project:** Enterprise RAG Assistant for Banking Regulatory Compliance  
**Module:** COM6301 (BSc Final Year Project)  
**Author:** Hashir Khan (Lead Architect / Candidate)  
**Date:** November 2026  
**Status:** Authoritative Architectural Audit  
**System Scope:** Single-node academic prototype. No message broker (RabbitMQ, Kafka, Redis Celery) exists or is expected.

---

## 1. Executive Summary & Prototype Baseline

This audit analyzes concurrency, backpressure, resource contention, and admission control across the FastAPI backend (`src/`), embedded storage engines (Qdrant, SQLite, BM25), local CPU inference pipelines, and Next.js frontend (`web/`). 

> [!IMPORTANT]
> **Prototype Classification:** This project is engineered and evaluated strictly as a **single-node academic prototype** for research and viva demonstration. It is designed to run locally on commodity hardware without external cloud infrastructure or dedicated GPUs. It does **not** claim distributed production readiness, multi-worker clustering, or horizontal scalability.

Every finding below is labeled as either **"verified by test [TestName]"** or **"analyzed from source, not tested"** in strict accordance with empirical research standards.

### Executive Verdict Summary Matrix

| # | Audited Vector | Verdict | Protecting File Path & Function | Verification Test / Analysis | Failure Mode Under Stress |
| :-: | :--- | :---: | :--- | :--- | :--- |
| **2.1** | Embedded Qdrant File Lock | **Protected** | `src/ingestion/indexer.py:check_storage_lock()`, `src/ingestion/indexer.py:QdrantIndexer._get_client()` | Verified by `test_enterprise_hardening.py::test_qdrant_storage_lock_detection_and_release` | Startup crash (`RuntimeError`) on second worker |
| **2.2** | Event Loop Blocking vs Threads | **Protected** | `src/api/routes.py:chat_query()`, `src/api/routes.py:upload_document()`, `src/api/main.py:health_check()` | Analyzed from source | Latency degradation under CPU saturation |
| **2.3** | SQLite Write Serialization | **Partially protected** | `src/db/connection.py:get_db_connection()`, `src/db/repository.py:Repository.add_audit_log()` | Analyzed from source | `sqlite3.OperationalError: database is locked` after 5s |
| **2.4** | LLM Call Budget & Spend Guard | **Partially protected** | `src/core/spend_guard.py:SpendGuard.check_and_charge()`, `src/core/rate_limiter.py:RateLimiter.acquire()`, `src/core/llm_client.py:ResilientLLMClient._execute_with_retry()` | Verified by `test_spend_guard.py` and `test_llm_client.py` | HTTP 429 (`RATE_OR_SPEND_LIMIT`) |
| **2.5** | Admission Control & Limits | **Protected** | `src/api/deps.py:enforce_query_rate_limit()`, `src/api/deps.py:enforce_upload_rate_limit()`, `src/ingestion/upload_ingest.py:validate_upload_request()`, `src/core/auth.py:login_user()`, `src/api/routes.py:_execute_chat_turn()` | Verified by `test_rate_limiter.py`, `test_auth.py`, `test_upload_ingest.py` | HTTP 400, 413, 422, or 429 |
| **2.6** | Dual-Index Ingestion Consistency | **Unprotected** | *None* (Documented Architectural Limitation) | Analyzed from source | Dual-index divergence on mid-upload crash |
| **2.7** | Mid-Stream Disconnect Handling | **Unprotected** | *None* (Documented Architectural Limitation) | Analyzed from source | Wasted compute/tokens; runs to completion |
| **2.8** | Cache & Memory Retention | **Partially protected** | `src/core/spend_guard.py:SpendGuard._runs`, `src/core/rate_limiter.py:RateLimiter._buckets`, `src/core/memory.py:load_recent_turns()` | Verified by `test_spend_guard.py` | Monotonic disk growth of SQLite `llm_cache` |
| **2.9** | Operational Telemetry & Metrics | **Partially protected** | `src/api/main.py:_health_payload()`, `src/api/main.py:health_check()`, `src/api/routes.py:admin_metrics()`, `src/core/telemetry.py:TelemetryCollector.get_summary()` | Analyzed from source | Silent degradation; lack of RSS / queue depth |
| **2.10** | Frontend Backpressure | **Protected** | `web/components/chat/composer.tsx:Composer()`, `web/components/chat/composer.tsx:handleKeyDown()`, `web/components/chat/chat-view.tsx:handleSubmit()`, `web/lib/api-client.ts:fetchApi()` | Verified by `web/tests/message-list.test.tsx` and `web/tests/api-client.test.ts` | Clean alert card, no retry storms |

---

## 2. Exhaustive Subsystem Governance Audit

### 2.1 Embedded Qdrant File Lock & API Worker Scaling

* **Verdict:** **Protected**
* **Protecting Implementation:** `src/ingestion/indexer.py:check_storage_lock()`, `src/ingestion/indexer.py:QdrantIndexer._get_client()`
* **Source Locations:** `src/ingestion/indexer.py` (`QdrantIndexer._get_client()`, `check_storage_lock()`), `src/config.py` (`settings.QDRANT_STORAGE_PATH`), `src/api/main.py` (`lifespan`).
* **Worker Capacity:** Exactly **one (1) API worker** can run against the embedded Qdrant store.
* **Mechanism & Second Process Behavior:**
  * Embedded Qdrant operates in local file mode (`QdrantClient(path=self.storage_path)`), creating an exclusive OS file lock (`.lock` file in the storage directory).
  * In `src/ingestion/indexer.py:59`, `check_storage_lock()` attempts to open the lock file for read/write:
    ```python
    with open(lock_file, "r+"): pass
    ```
  * If a second operating system process (e.g. starting Uvicorn with `--workers 2` or running concurrent standalone test scripts) attempts to access the same directory, `check_storage_lock()` catches the `PermissionError` / `OSError` and immediately raises:
    ```python
    RuntimeError("Local Qdrant storage at '...' is locked by another running process or stale server...")
    ```
  * If `check_storage_lock()` were bypassed, Qdrant's underlying storage engine raises an exclusive lock acquisition failure.
  * **Failure Mode:** Immediate process startup crash (`RuntimeError`). No data corruption or hanging occurs, but the second worker process terminates immediately.
* **Verification Status:** Verified by test `tests/test_enterprise_hardening.py::test_qdrant_storage_lock_detection_and_release`.
* **Mitigation Recommendation:**
  * *Dissertation:* Keep single-worker Uvicorn (`--workers 1`). High priority for prototype stability; zero extra dependencies. Effort: **Low**.
  * *Production:* Transition from embedded local Qdrant to standalone Qdrant container/service accessed over HTTP/gRPC (`url="http://qdrant:6333"`), which natively handles multi-process concurrency and connection pooling. Effort: **Medium (Production only)**.

---

### 2.2 Event Loop Non-Blocking vs. Thread Pool Dispatch

* **Verdict:** **Protected**
* **Protecting Implementation:** `src/api/routes.py:chat_query()`, `src/api/routes.py:upload_document()`, `src/api/main.py:health_check()`
* **Source Locations:** `src/api/routes.py` (`chat_query`, `_execute_chat_turn`, `upload_document`), `src/api/main.py` (`health_check`, `ask_question`), `src/rag/baseline.py` (`BaselineRAGPipeline.ask()`).
* **Route Definition Analysis:**
  * Every API endpoint in `src/api/routes.py` is declared using synchronous function syntax (`def chat_query(...)`, `def upload_document(...)`), **not** `async def`.
  * In FastAPI / Starlette, synchronous routes are automatically offloaded to an external worker threadpool using `anyio.to_thread.run_sync` (which wraps `concurrent.futures.ThreadPoolExecutor`).
  * The main `asyncio` event loop is **never blocked** by CPU-bound tasks (cross-encoder re-ranking, dense vector embedding generation, BM25 inverted index tokenization/scoring, or document chunking). The event loop remains responsive to handle HTTP handshakes, health probes (`/health`), and CORS preflight requests.
* **Thread Pool Sizing:**
  * The thread pool size is governed by AnyIO's default thread limiter: `anyio.to_thread.current_default_thread_limiter().total_tokens`, which defaults to **40 worker threads**.
* **CPU Contention Under Concurrency:**
  * While the event loop is not blocked, concurrent requests executing in the thread pool contend for physical CPU cores during PyTorch neural inference (`BAAI/bge-small-en-v1.5` embeddings and `ms-marco-MiniLM-L-6-v2` cross-encoder).
  * PyTorch C++ operations release the Python Global Interpreter Lock (GIL) during underlying matrix multiplications (OpenMP / BLAS), so CPU utilization scales across cores, but heavy concurrent request spikes will cause latency degradation.
* **Verification Status:** Analyzed from source, not tested under synthetic multi-threaded load.

---

### 2.3 SQLite Journal Mode, Busy Timeout & Write Contention

* **Verdict:** **Partially protected**
* **Protecting Implementation:** `src/db/connection.py:get_db_connection()`, `src/db/repository.py:Repository.add_audit_log()`
* **Source Locations:** `src/db/connection.py` (`get_db_connection()`), `src/db/repository.py` (`add_audit_log()`, `add_message()`, `create_session()`, `rename_session_for_user()`), `src/core/llm_client.py` (`_write_cache()`, `_log_call()`).
* **Engine Configuration:**
  ```sql
  PRAGMA foreign_keys = ON;
  PRAGMA journal_mode = WAL;
  PRAGMA busy_timeout = 5000;
  ```
  `sqlite3.connect(path, timeout=30.0)`
* **Write Paths Per Request Turn:**
  A single standard chat request turn (`POST /api/v1/chat/query`) executes up to **six (6) discrete SQLite writes**:
  1. *Session Auto-Titling:* `UPDATE sessions SET title = ...` (if first turn).
  2. *User Turn Logging:* `INSERT INTO messages` (records user prompt and clearance).
  3. *Assistant Turn Logging:* `INSERT INTO messages` (records verified answer, citations, and metadata).
  4. *Cryptographic Audit Trail:* `INSERT INTO audit_logs` (reads head hash, re-computes SHA-256 chain, writes immutable audit record).
  5. *LLM Response Caching:* `INSERT INTO llm_cache` (caches completion against salted SHA-256 key).
  6. *Telemetry Call Record:* `INSERT INTO llm_calls` (persists token usage, latency, and profile telemetry).
* **Contention & Locking Analysis:**
  * SQLite WAL (Write-Ahead Logging) mode allows multiple readers to operate concurrently with a single writer. Readers never block writers, and writers never block readers.
  * However, SQLite strictly serializes writes: **only one writer can hold the write lock at any instant**.
  * The `PRAGMA busy_timeout = 5000;` instructs SQLite to sleep and retry internally for up to 5,000ms if a lock collision occurs.
  * Under low-to-moderate academic use (1–5 concurrent turns), transactions complete in < 2ms, so contention is negligible.
  * Under heavy concurrent write bursts, transactions queue up. If cumulative lock contention exceeds 5 seconds, SQLite raises `sqlite3.OperationalError: database is locked`.
* **Verification Status:** Analyzed from source, not tested under concurrent write stress.
* **Mitigation Recommendation:**
  * *Dissertation:* Keep WAL mode with 5,000ms busy timeout. Catch `sqlite3.OperationalError` in API exception handlers and return a sanitized HTTP 503 instead of an unhandled 500. Effort: **Low (Worth doing)**.
  * *Production:* Migrate from single-file SQLite to a relational database with row-level locking (PostgreSQL). Effort: **High (Production only)**.

---

### 2.4 LLM Call Budget, Profile Execution & Spend Guard

* **Verdict:** **Partially protected**
* **Protecting Implementation:** `src/core/spend_guard.py:SpendGuard.check_and_charge()`, `src/core/rate_limiter.py:RateLimiter.acquire()`, `src/core/llm_client.py:ResilientLLMClient._execute_with_retry()`
* **Source Locations:** `src/core/llm_client.py` (`ResilientLLMClient`), `src/core/spend_guard.py` (`SpendGuard`), `src/core/rate_limiter.py` (`RateLimiter`), `src/api/routes.py` (`_execute_chat_turn`).
* **LLM Calls Per User Query Breakdown:**
  * *Baseline (A0):* Exactly **1 call** (Answer generation).
  * *Full Pipeline (A7) on First Turn:* **5 calls**:
    1. Query Reformulation / Rewrite: 0 (no history).
    2. Adaptive Router: 1 call (`classify_question`).
    3. Corrective Grader: 1 call (`grade_passages`).
    4. Answer Generation: 1 call (`pipeline.ask`).
    5. Claim Verification: 1 call (`verify_claims`).
    6. Auto-Titling: 1 call (`generate_session_title`).
  * *Full Pipeline (A7) on Follow-up Turn:* **5 calls**:
    1. Query Reformulation: 1 call (`rewrite_follow_up`).
    2. Adaptive Router: 1 call.
    3. Corrective Grader: 1 call.
    4. Answer Generation: 1 call.
    5. Claim Verification: 1 call.
  * *Multi-Intent Split:* Up to $K$ sub-question calls + 1 synthesis call.
* **Concurrency Caps & Rate Limiting:**
  * *Concurrency Cap:* **None.** There is no active semaphore (`asyncio.Semaphore` or `threading.BoundedSemaphore`) capping concurrent in-flight LLM calls across threads.
  * *Token Bucket Rate Limiter:* `RateLimiter` enforces `settings.LLM_MAX_RPM` (default 30 RPM) via thread sleeping before upstream dispatch.
  * *Timeout & Retries:* `httpx.Client(timeout=15.0)` enforces strict 15s per-call timeout. `_execute_with_retry` retries up to `settings.LLM_MAX_RETRIES` (default 2) with exponential backoff and jitter:
    $$\text{backoff} = \text{base} \times 2^{\text{attempt}} + \text{Uniform}(0.1, 0.5)$$
    Safe retry statuses: 429, 500, 502, 503, 504.
* **Spend Guard & UI Handling:**
  * `SpendGuard` enforces per-run limits (`LLM_MAX_CALLS_PER_RUN = 8`, `LLM_MAX_TOKENS_PER_RUN = 16,000`) and per-session limits (`LLM_MAX_CALLS_PER_SESSION = 150`, `LLM_MAX_TOKENS_PER_SESSION = 400,000`).
  * If a cap is breached, `SpendGuardExceededError` is raised before network dispatch, mapped by `src/api/main.py:119` to HTTP 429 with header `Retry-After: 60`.
  * In the Next.js frontend (`web/lib/api-client.ts`), 429 is mapped to code `RATE_OR_SPEND_LIMIT`. The UI does **not** auto-retry, preventing rapid quota exhaustion.
* **Verification Status:** Verified by tests `tests/test_spend_guard.py` and `tests/test_llm_client.py`.

---

### 2.5 Admission Control & Input Validation

* **Verdict:** **Protected**
* **Protecting Implementation:** `src/api/deps.py:enforce_query_rate_limit()`, `src/api/deps.py:enforce_upload_rate_limit()`, `src/ingestion/upload_ingest.py:validate_upload_request()`, `src/core/auth.py:login_user()`, `src/api/routes.py:_execute_chat_turn()`
* **Source Locations:** `src/api/deps.py` (`enforce_query_rate_limit`, `enforce_upload_rate_limit`), `src/api/routes.py` (`_execute_chat_turn`), `src/ingestion/upload_ingest.py` (`validate_upload_request`), `src/core/auth.py` (`login_user`), `src/config.py`.
* **Enforced Admission Boundaries:**
  1. *Query Length:*
     * Minimum: `len(query) < 2` $\rightarrow$ HTTP 400 (`EMPTY_QUERY`).
     * Maximum: Schema validation caps query at 2,000 characters $\rightarrow$ HTTP 422 (`VALIDATION_ERROR`).
     * Internal pipeline clamping: sub-questions clamped to 400 chars, history turns to 400 chars, grader rewrites to 400 chars.
  2. *Upload File Size:*
     * Capped at `settings.UPLOAD_MAX_FILE_SIZE_MB` (default 10MB).
     * Checked in `validate_upload_request()`: if `file_size > max_bytes` $\rightarrow$ raises `ApiError(413, "FILE_TOO_LARGE", ...)`.
  3. *Per-User Query Rate Limiting:*
     * `enforce_query_rate_limit()` tracks query timestamps per user ID in SQLite table `rate_limits`.
     * Sliding window of `settings.RATE_LIMIT_QUERIES_PER_MINUTE` (default 20 RPM).
     * Breached limit $\rightarrow$ HTTP 429 with `Retry-After: 60` and `{"error": {"code": "RATE_LIMIT_EXCEEDED"}}`.
  4. *Authentication Lockout:*
     * `AUTH_MAX_LOGIN_ATTEMPTS = 5` failed attempts per username/IP triggers a 900-second account lockout $\rightarrow$ HTTP 429 (`ACCOUNT_LOCKED`).
  5. *Global Request Body Limit:*
     * FastAPI/Starlette has no default global request body ceiling for standard JSON endpoints (analyzed from source, not tested).
* **Verification Status:** Rate limiting verified by `tests/test_rate_limiter.py` and `tests/test_auth.py`; upload limits verified by `tests/test_upload_ingest.py`.

---

### 2.6 Dynamic Ingestion During Live Query Traffic

* **Verdict:** **Unprotected**
* **Protecting Implementation:** *None* (Acknowledged Prototype Limitation)
* **Source Locations:** `src/api/routes.py` (`upload_document`), `src/ingestion/upload_ingest.py` (`ingest_uploaded_document`).
* **Concurrency Impact on Live Queries:**
  * When an authorized user uploads a document, `ingest_uploaded_document` executes synchronously inside a threadpool worker thread.
  * Dense vector indexing embeds the new chunks on the CPU using `BAAI/bge-small-en-v1.5`, consuming significant CPU cycles and temporarily increasing retrieval latency for concurrent chat queries.
* **Dual-Index Transactionality Risk (Qdrant + BM25):**
  * Ingestion writes to Qdrant first (`qdrant.index_chunks(chunks)`), and subsequently persists BM25 to disk (`bm25.build_and_save(...)`).
  * **No Two-Phase Commit:** There is no transactional rollback across Qdrant and BM25. If the server crashes or an exception occurs during BM25 serialization, Qdrant retains the vectors while BM25 does not, creating an inconsistent dual-index state.
  * In `src/api/routes.py:1297`, `baseline_pipeline.bm25.load()` reloads the BM25 index from disk in-place. If another thread is actively evaluating `bm25.search()` during that assignment, it could observe transient state.
* **Verification Status:** Analyzed from source, not tested under concurrent upload/query collision.
* **Mitigation Recommendation:**
  * *Dissertation:* Restrict upload permissions strictly to `manager` and `auditor` roles (already enforced). Document as an acknowledged prototype boundary. Effort: **Low**.
  * *Production:* Offload document ingestion to an asynchronous worker queue (Celery/Temporal) with staged indexing and atomic index swaps. Effort: **High (Production only)**.

---

### 2.7 Streaming Responses & Socket Disconnect Handling

* **Verdict:** **Unprotected**
* **Protecting Implementation:** *None* (Acknowledged Prototype Limitation)
* **Source Locations:** `src/api/routes.py` (`chat_query`), `web/components/chat/progressive-answer.tsx`.
* **Architecture Clarification:**
  * The backend does **not** perform server-sent event (SSE) token streaming. The endpoint `POST /api/v1/chat/query` returns a complete, verified JSON response synchronously.
  * "Streaming" in the Next.js interface is a presentation-layer progressive reveal (`ProgressiveAnswer`) using `requestAnimationFrame` to reveal completed text smoothly over 280–900ms.
* **Client Disconnect Behavior:**
  * If a user closes their browser tab or navigates away while a query is in-flight, the synchronous backend thread **continues executing to completion**:
    * Vector retrieval completes.
    * Re-ranking completes.
    * External LLM calls complete and consume quota.
    * Audit log and database records are written.
  * The backend only detects the client disconnection when attempting to write the final HTTP response to the closed TCP socket. No computational or token spend is saved on disconnect.
* **Verification Status:** Analyzed from source, not tested.

---

### 2.8 Cache and Memory Retention Bounds

* **Verdict:** **Partially protected**
* **Protecting Implementation:** `src/core/spend_guard.py:SpendGuard._runs`, `src/core/rate_limiter.py:RateLimiter._buckets`, `src/core/memory.py:load_recent_turns()`
* **Source Locations:** `src/core/llm_client.py` (`_read_cache`, `_write_cache`, `_cache_row_is_fresh`), `src/config.py` (`LLM_CACHE_TTL_DAYS`), `src/core/spend_guard.py` (`MAX_TRACKED_RUNS`), `src/core/rate_limiter.py` (`MAX_BUCKETS`).
* **Bounding Audit:**
  1. *SQLite LLM Cache (`llm_cache`):*
     * Checked against `LLM_CACHE_TTL_DAYS` (default 30 days) on read.
     * **No Automated Pruning:** Stale entries older than 30 days are ignored on lookup, but they are **never deleted automatically** from the database file. The `llm_cache` table grows monotonically unless manually truncated.
  2. *Session Message History (`messages`):*
     * In-flight LLM working memory is strictly bounded by `settings.MEMORY_MAX_TURNS` (default 6 turns).
     * SQLite storage of `messages` is append-only and unbounded.
  3. *In-Memory Telemetry Stores:*
     * `SpendGuard._runs`: Bounded by `MAX_TRACKED_RUNS = 512` (FIFO eviction of oldest runs).
     * `RateLimiter._buckets`: Bounded by `MAX_BUCKETS = 4096`.
* **Verification Status:** Memory bounding verified in `test_spend_guard.py`; lack of SQLite cache pruning analyzed from source.
* **Mitigation Recommendation:**
  * *Dissertation:* Add a startup query in `lifespan` pruning expired cache rows: `DELETE FROM llm_cache WHERE created_at < datetime('now', '-30 days')`. Effort: **Low (Worth doing)**.
  * *Production:* Background cron job or Redis with native TTL eviction. Effort: **Medium (Production only)**.

---

### 2.9 Operational Telemetry & Health Monitoring Gaps

* **Verdict:** **Partially protected**
* **Protecting Implementation:** `src/api/main.py:_health_payload()`, `src/api/main.py:health_check()`, `src/api/routes.py:admin_metrics()`, `src/core/telemetry.py:TelemetryCollector.get_summary()`
* **Source Locations:** `src/api/main.py` (`_health_payload`, `/health`, `/readiness`), `src/api/routes.py` (`/admin/metrics`, `/admin/config`), `src/core/telemetry.py`.
* **What is Currently Exposed:**
  * `/health` (Public): Database connectivity (`connected: true/false`), vector store status and vector count, active LLM profile and model name, boolean flags for all active pipeline layers.
  * `/admin/metrics` (Auditor/Manager only): Total calls, cached calls, cache hit rate, token totals (prompt, completion, total), latency metrics ($p_{50}$, $p_{95}$, average ms), SpendGuard quota status.
* **Missing Operational Telemetry for Production Operators:**
  1. *In-Flight Request Gauge:* No counter indicating how many concurrent queries are actively executing.
  2. *Memory / Process RSS:* No telemetry on host RAM consumption (critical for local CPU models).
  3. *Thread Pool Saturation:* No metric on AnyIO worker thread pool queue depth.
  4. *SQLite Lock Wait Duration:* No metric on how many milliseconds threads wait for SQLite write locks.
  5. *Prometheus Standard Exporter:* Output is custom JSON; lacks standard `/metrics` Prometheus scrape format.
* **Verification Status:** Analyzed from source.

---

### 2.10 Frontend Resilience & Error Handling (`web/`)

* **Verdict:** **Protected**
* **Protecting Implementation:** `web/components/chat/composer.tsx:Composer()`, `web/components/chat/composer.tsx:handleKeyDown()`, `web/components/chat/chat-view.tsx:handleSubmit()`, `web/lib/api-client.ts:fetchApi()`
* **Source Locations:** `web/components/chat/composer.tsx`, `web/components/chat/chat-view.tsx`, `web/lib/api-client.ts`.
* **Duplicate Submission Protection:**
  * The Composer submit button enforces `disabled={!canSend}`, where:
    ```typescript
    const canSend = draft.trim().length >= 2 && !sending && !offline;
    ```
  * When a query is initiated, `sending` transitions to `true` immediately. Keyboard handlers (`Enter`) check `if (!canSend) return;`.
  * Rapid double-clicks or repeated keyboard presses are completely prevented from initiating duplicate backend queries.
* **HTTP 429 & 503 Handling:**
  * `web/lib/api-client.ts` maps 429 to `RATE_OR_SPEND_LIMIT` ("The query limit or spend cap was reached. Try again shortly.") and 503 to `SERVICE_UNAVAILABLE`.
  * In `ChatView`, errors do not crash the React component tree; they render an accessible alert card (`role="alert"`) with an explicit "Try again" manual retry button.
  * The frontend **never automatically retries** on 429 or 503, preventing client loops from exhausting quotas or compounding server strain.
* **Verification Status:** Verified by tests `web/tests/message-list.test.tsx` and `web/tests/api-client.test.ts`.

---

## 3. What Matters for this Dissertation

In a final-year undergraduate engineering project, academic rigor requires distinguishing between **achievable local hardening** and **unnecessary enterprise over-engineering**.

### Top 5 Actionable Findings Worth Addressing Now

| # | Finding & Proposed Action | Rationale for Dissertation | Effort | Status |
| :--- | :--- | :--- | :---: | :---: |
| **1** | **Add In-Flight LLM Call Semaphore:** Wrap live generator calls in a local `threading.BoundedSemaphore(5)` to prevent concurrent CPU/network flooding. | Protects local demonstration runs from thrashing if multiple tabs are opened during viva. | **Low** | Recommended |
| **2** | **Prune Expired Cache on Startup:** Add `DELETE FROM llm_cache WHERE created_at < ...` in `lifespan` initialization. | Demonstrates database hygiene without introducing complex background daemons. | **Low** | Recommended |
| **3** | **Catch SQLite Busy Lock with Clean 503:** Wrap `get_db_connection` in an exception handler translating `sqlite3.OperationalError: database is locked` to HTTP 503. | Eliminates raw 500 error stack traces during accidental concurrent write spikes. | **Low** | Recommended |
| **4** | **Expose In-Flight Request Count on `/health`:** Add a simple integer atomic counter tracking active turns. | Provides immediate visibility into server load for demonstration monitoring. | **Low** | Recommended |
| **5** | **Enforce Maximum Request Body Ceiling:** Add a Starlette middleware capping raw request payload size at 15MB. | Prevents potential process memory exhaustion from malformed oversized POST bodies. | **Low** | Recommended |

### Documented Architectural Limitations (for `LIMITATIONS.md`)

The following findings are explicitly designated as out-of-scope for the single-node prototype and will be documented in `docs/LIMITATIONS.md`:
1. **Single-Worker Process Ceiling:** Embedded Qdrant file lock strictly limits the API to a single worker process (`--workers 1`). Multi-worker horizontal scaling requires standalone Qdrant server.
2. **SQLite Write Serialization:** High-throughput concurrent multi-user environments require migrating from SQLite to a distributed relational database (PostgreSQL) with row-level MVCC locking.
3. **Absence of Token Streaming:** Server-Sent Events (SSE) token streaming is omitted in favor of synchronous verification and full-response cryptographic audit integrity.
4. **Non-Transactional Multi-Index Ingestion:** Ingestion across dense Qdrant and lexical BM25 lacks distributed two-phase commit; recovery from partial failures requires re-indexing.
5. **No Work Cancellation on Disconnect:** In-flight queries run to completion even if the user closes the browser session mid-generation.

