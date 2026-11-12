# Comprehensive Project Security Checklist

**System:** Enterprise RAG Assistant for Banking Regulatory Compliance  
**Module:** COM6301 (BSc Final Year Project)  
**Evaluation Target:** Current Codebase (Phase 5 Closeout)  
**Standard:** OWASP Top 10 / LLM Applications Security Top 10 Compliance  

---

## 1. Security Domains Checklist

| # | Domain | Status | Core Implementation & Controls |
|---|---|:---:|---|
| 1 | **Authentication** | Pass | PBKDF2-HMAC-SHA256 password hashing (100k rounds, 16-byte random salt). Zero plaintext passwords. |
| 2 | **Authorization & RBAC** | Pass | Server-side role resolution in Qdrant (`allowed_roles`) and BM25. 0.00% leakage across all roles. |
| 3 | **Session / Token Security** | Pass | Stateless HS256 JWT with `jti`, expiration timestamps, and database revocation table (`revoked_tokens`). |
| 4 | **Input Validation** | Pass | Pydantic v2 schemas (`ChatQueryRequest`, `SessionCreateRequest`), length bounds, `extra="forbid"`. |
| 5 | **Injection (SQL & Prompts)** | Pass | Parameterized SQL queries exclusively. Prompt injection safety with `<authoritative_documents>` boundaries. |
| 6 | **XSS & CSRF** | Pass | JSON-only API contracts; CORS origin restriction limited strictly to localhost Streamlit origins. |
| 7 | **API Security** | Pass | Bearer token authentication required for all business endpoints. Uniform refusal and 404 responses. |
| 8 | **Rate Limiting & Abuse** | Partial | Dedicated login throttle per username; global authenticated route rate limiter recommended. |
| 9 | **File Uploads** | Pass | No public or client file upload endpoints exist. Ingestion is offline and strictly file-system local. |
| 10| **Database Security** | Pass | SQLite WAL mode, foreign key integrity enforced, zero dynamic query interpolation. |
| 11| **Secrets Management** | Pass | Credentials resolved strictly through `src/config.py` from `.env`; clean `.env.example`; no hardcoded keys. |
| 12| **Encryption & Hashing** | Pass | PBKDF2 password derivation, SHA-256 LLM response cache hashing, SHA-256 JWT signature verification. |
| 13| **CORS Configuration** | Pass | Restricts allowed origins strictly to `http://localhost:8501` and `http://127.0.0.1:8501`. |
| 14| **Dependency Security** | Pass | Pinned versions in `requirements.txt` with justification comments; no unnecessary third-party packages. |
| 15| **Logging & Monitoring** | Pass | Comprehensive telemetry in `audit_log` and `llm_calls`; prompts and credentials excluded from logs. |
| 16| **Admin Security** | Pass | `/api/v1/audit/logs` endpoint restricted exclusively to authenticated users with `auditor` role. |
| 17| **Deployment & Infrastructure**| Pass | Local CPU execution for embeddings and re-ranking (BAAI/bge-small and MiniLM-L-6-v2); no GPU required. |
| 18| **Data Privacy (PII)** | Pass | Verified zero real personal or confidential banking customer data in `/data/synthetic/`. |
| 19| **Error Handling** | Pass | Standardized exception handlers returning sanitized JSON errors without leaking stack traces or paths. |
| 20| **Backup & Recovery** | Partial | File-backed SQLite database easily snapshotable; automated point-in-time recovery to be configured in production. |

---

## 2. Detailed Findings & Categorized Vulnerability Matrix

### A. Confirmed Vulnerability

*None identified.* The application enforces strict server-side validation, database parameterization, and zero-leakage role filtering.

---

### B. Security Weakness

#### 1. In-Memory Login Throttle Resets on Worker Recycle
- **Severity:** Medium
- **Evidence:** `src/core/auth.py:30-75`: `InMemoryLoginThrottle` tracks failed attempts using an in-memory dictionary.
- **Risk:** Process restarts or running multiple Uvicorn workers clears the rate-limit history, enabling distributed brute-force attacks against user credentials.
- **Affected Location:** `src/core/auth.py` (`InMemoryLoginThrottle`)
- **Why It Matters:** Brute-force protection must persist reliably across process recycles in production.
- **Recommended Fix:** Persist failed login attempts in the SQLite database or an external key-value store (e.g. Redis).

#### 2. Permissive Wildcard Ingress Headers in CORS
- **Severity:** Medium
- **Evidence:** `src/api/main.py:50`: `allow_headers=["*"]`.
- **Risk:** Accepts unvetted client headers from permitted origins, broadening request surface if frontend origin is compromised.
- **Affected Location:** `src/api/main.py:46-52`
- **Why It Matters:** Principle of least privilege requires explicit header whitelisting.
- **Recommended Fix:** Replace `allow_headers=["*"]` with an explicit list: `["Authorization", "Content-Type", "Accept"]`.

#### 3. Default `SECRET_KEY` in Configuration Fallback
- **Severity:** Medium
- **Evidence:** `src/config.py:42`: `SECRET_KEY: str = Field(default="dev-secret-key-change-in-production-32-chars-min")`.
- **Risk:** Deploying without specifying `SECRET_KEY` in `.env` allows attackers to sign valid arbitrary JWT tokens.
- **Affected Location:** `src/config.py:41-45`
- **Why It Matters:** Token authenticity depends entirely on the private entropy of `SECRET_KEY`.
- **Recommended Fix:** Enforce a startup validation failure if `APP_ENV not in ("test", "local", "development")` and `SECRET_KEY` matches the default value.

---

### C. Missing Control

#### 1. Global Rate Limiting on Authenticated Query Endpoints
- **Severity:** Medium
- **Evidence:** `src/api/routes.py:chat_query` does not throttle authenticated requests.
- **Risk:** Malicious or runaway authenticated clients could exhaust upstream LLM spend caps or overload CPU re-ranking models.
- **Affected Location:** `src/api/routes.py:280-570`
- **Why It Matters:** Upstream API quota exhaustion denies service to all compliance users.
- **Recommended Fix:** Add a per-user token-bucket rate limiter middleware enforcing a cap (e.g. 30 requests/minute per user).

#### 2. Standard HTTP Security Headers Middleware
- **Severity:** Low
- **Evidence:** `src/api/main.py` lacks security response headers (`X-Frame-Options`, `X-Content-Type-Options`, `Content-Security-Policy`).
- **Risk:** Leaves web clients open to clickjacking and MIME-type sniffing if accessed via browsers.
- **Affected Location:** `src/api/main.py`
- **Why It Matters:** Basic web defense-in-depth required for enterprise compliance applications.
- **Recommended Fix:** Add a Starlette middleware that injects `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, and a strict CSP header.

#### 3. Unauthenticated User Listing in Non-Production Mode
- **Severity:** Low
- **Evidence:** `src/api/routes.py:133-149`: `GET /api/v1/auth/users` returns all synthetic accounts without credentials when `APP_ENV != "production"`.
- **Risk:** Enumeration of valid usernames and roles aiding targeted credential testing.
- **Affected Location:** `src/api/routes.py:133-149`
- **Why It Matters:** Information exposure aids attacker reconnaissance.
- **Recommended Fix:** Protect `GET /api/v1/auth/users` with auditor authentication or restrict it exclusively to local UI testing.

---

### D. Potential Risk Requiring Verification

#### 1. Embedded Qdrant Concurrent Process Access
- **Severity:** Low
- **Evidence:** `src/ingestion/indexer.py` instantiates `QdrantClient(path=storage_path)`.
- **Risk:** Multiple OS processes trying to open the same embedded directory lock can lead to locking conflicts on Windows.
- **Affected Location:** `src/ingestion/indexer.py:165-175`
- **Why It Matters:** Concurrency errors cause unexpected service downtime.
- **Recommended Fix:** Verify that the application runs as a single Uvicorn worker when using embedded storage mode.

#### 2. Local Model File Download Probes in Strict Offline Environments
- **Severity:** Low
- **Evidence:** HuggingFace Hub client attempts network socket checks for model commits unless `$env:HF_HUB_OFFLINE="1"` is set.
- **Risk:** Unintended socket connection attempts in air-gapped banking network setups.
- **Affected Location:** `src/ingestion/embeddings.py`, `src/rag/baseline.py`
- **Why It Matters:** Air-gapped environments forbid unvetted outbound connections.
- **Recommended Fix:** Explicitly set `local_files_only=True` in HuggingFace model loaders.

---

### E. Recommendations

1. **Periodic Revoked Token Table Cleanup:** Implement a scheduled cleanup script to delete expired tokens from `revoked_tokens` to prevent table bloat.
2. **Audit Trail Cryptographic Integrity:** Implement SHA-256 HMAC chaining on audit log records so auditors can verify that compliance records have not been altered or deleted.
3. **Database Backup Strategy:** Automate daily SQLite backups using SQLite's online backup API (`sqlite3_backup`) to prevent database corruption during backups.

