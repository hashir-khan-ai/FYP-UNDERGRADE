# Memory Architecture & Tenant Isolation Specification

**Project:** Enterprise RAG Assistant for Banking Regulatory Compliance  
**Module:** COM6301 (BSc Final Year Project)  
**Author:** Hashir Khan (Lead Architect / Candidate)  
**Status:** Authoritative Architectural Standard & Memory Audit  

---

## 1. Executive Summary & Cognitive Memory Taxonomy

Enterprise regulatory compliance in banking mandates deterministic, point-in-time accuracy, strict role-based access control (RBAC), and immutable auditability. Unlike open-domain conversational agents that accumulate persistent personal user models, an enterprise compliance assistant must enforce rigorous memory boundaries. Uncontrolled memory accumulation across queries or users poses critical data leakage, regulatory non-compliance, and prompt injection vulnerabilities.

This document audits the eight cognitive memory classes for the compliance assistant. For each class, it defines implementation state, exact codebase paths, multi-tenant and role scoping mechanisms, operational cost per call, and the formal regulatory justification for components designated as out of scope.

### Memory Classification Matrix

| Memory Class | Status | Code Path | Role & Tenant Scoping Mechanism | Cost Profile Per Call |
| :--- | :--- | :--- | :--- | :--- |
| **1. Working Memory** | **Active** | `src/rag/baseline.py`<br>`src/core/prompts.py` | Role-filtered pre-retrieval (Qdrant & BM25 payloads); isolated per HTTP request; sandboxed in `<authoritative_documents>` XML | 0 persistent storage cost;<br>~500–2,500 prompt tokens |
| **2. Session Memory** | **Active** | `src/core/memory.py`<br>`src/db/repository.py` | Strict SQLite ownership (`WHERE session_id = ? AND user_id = ?`); per-turn role re-verification; sliding window condensation | 0 tokens under threshold;<br>1 rewrite call (~150–300 tokens) when active |
| **3. Semantic Memory** | **Out of Scope** | *Explicitly Excluded* | N/A (No persistent user knowledge base or cross-session vector index) | $0.00$ (Eliminates vector indexing & drift risk) |
| **4. Episodic Memory** | **Out of Scope** | *Explicitly Excluded* | N/A (No experience replay, past session embedding, or agent reflection) | $0.00$ (Prevents hallucination propagation) |
| **5. Procedural Memory** | **Active** | `prompts/`<br>`src/core/router.py`<br>`src/core/grader.py`<br>`src/core/calculator.py`<br>`DESIGN.md`, `DECISIONS.md` | Versioned prompts (`settings.PROMPT_VERSION`), router/grader Pydantic schemas, AST calculator grammar, and architectural invariants documented in `DESIGN.md` and `DECISIONS.md` | 0 runtime API cost;<br>Pre-compiled static execution |
| **6. Prospective Memory**| **Out of Scope** | *Explicitly Excluded* | N/A (Synchronous request-response only; no asynchronous background tasks) | $0.00$ (Eliminates unmanaged execution risk) |
| **7. Parametric Memory** | **Active** | `src/core/llm_client.py`<br>`src/rag/embeddings.py`<br>`src/rag/reranker.py` | Generator weights per profile (`mock`: deterministic canned; `local`: `sshleifer/tiny-gpt2` smoke test; `dev`: Groq `llama-3.3-70b-versatile`; `demo`: paid). Note: Local CPU embeddings (`bge-small-en-v1.5`) and re-ranker (`ms-marco-MiniLM-L-6-v2`) are separate components from the generator | CPU inference (~20–60ms);<br>Generator tokens governed by spend caps |
| **8. Cache Memory** | **Active** | `src/core/llm_client.py`<br>`data/cache/llm/` | Deterministic SHA-256 key salted with `(role, user_id, prompt_version, model, step)`; zero cross-tenant collision risk | 0 tokens / 0 latency on hit;<br>SQLite lookup ~0.4ms |

---

## 2. In-Depth Audit of Memory Classes

### 2.1 Working Memory (In-Flight Request Context)

* **Definition:** The transient, short-lived context window assembled during a single request turn to synthesize a grounded regulatory response.
* **Code Paths:**
  * `src/rag/baseline.py`: `BaselineRAGPipeline.ask()`, `retrieve_relevant_chunks()`
  * `src/core/prompts.py`: `render_prompt()`, XML encapsulation utilities
  * `src/core/pipeline.py`: Pipeline execution context orchestration
* **Role & User Scoping:**
  * **Server-Side RBAC Filtering:** Role filtering is applied strictly at the database retrieval level before working memory is populated. Vector queries in Qdrant filter on `allowed_roles` via native payload filters; BM25 queries filter candidate postings by role. Chunks outside the user's role are mathematically excluded from candidate lists and never enter LLM context.
  * **XML Security Boundaries:** Retrieved passages are wrapped within untrusted data delimiters (`<authoritative_documents>...</authoritative_documents>`). Prompts explicitly instruct the parametric model to treat passage content strictly as data, neutralizing prompt injection payloads embedded in retrieved texts.
  * **Lifecycle:** Instantiated upon HTTP request ingress, stored in-memory in Python process memory, and destroyed immediately upon response transmission.
* **Cost Profile Per Call:**
  * Persistent storage cost: $0.00$.
  * Upstream LLM token cost: ~500 to 2,500 prompt tokens (proportional to top-$k$ retrieved chunks and passage lengths).

---

### 2.2 Session Memory (Short-Term Conversational History)

* **Definition:** Short-term conversational continuity within a single thread, enabling multi-turn clarification, pronoun resolution, and follow-up question answering.
* **Code Paths:**
  * `src/core/memory.py`: `load_recent_turns()`, `rewrite_follow_up()`, `MAX_HISTORY_MESSAGE_CHARS = 1000`
  * `src/db/repository.py`: `Repository.get_recent_messages()`, `Repository.add_message()`
  * `src/api/routes.py`: Session loading and query execution endpoints
* **Role & User Scoping:**
  * **Strict Database Ownership (Anti-IDOR):** Message retrieval queries enforce compound predicates:
    ```sql
    SELECT * FROM sessions WHERE id = ? AND user_id = ?;
    ```
    If `user_id` does not match the authenticated JWT token, `load_recent_turns()` aborts immediately and returns an empty turn list (`[]`). A user cannot view, probe, or leverage another user's session memory.
  * **Dynamic RBAC Re-Verification:** Session memory does **not** persist retrieved passages—it stores only the sanitized user query and assistant response. When a user submits a follow-up question referencing an earlier turn, the query is rewritten into a standalone question (`rewrite_follow_up`) and submitted to the retrieval engine. The retrieval engine re-filters the corpus using the user's **current, active JWT clearance**. Historical messages mentioning restricted terminology cannot widen retrieval scope.
  * **Sliding Window:** Limited to the last $N$ turns (default 6), truncating individual turns to 1,000 characters to prevent context window overflow or memory-based denial-of-service.
* **Cost Profile Per Call:**
  * In baseline mode (`ENABLE_MEMORY=False`): Exactly 0 additional LLM calls; history is ignored.
  * In conversational mode (`ENABLE_MEMORY=True`): 0 additional calls for the first turn; exactly 1 lightweight rewrite call (~150–300 tokens) for subsequent follow-up turns.

---

### 2.3 Semantic Memory (Long-Term Cross-Session User Knowledge) — OUT OF SCOPE

* **Status:** **Explicitly Excluded / Out of Scope by Architectural Design.**
* **Definition:** The long-term accumulation of facts, preferences, user profiles, or historical compliance positions persisted in vector or graph stores across sessions.
* **Architectural Design Choices & Rationale:**
  1. **Point-in-Time Regulatory Grounding (Anti-Drift):** In banking compliance, regulatory determinations must be based exclusively on statutory rulebooks and approved internal policy documents as of the exact evaluation date. Accumulating semantic user memories risks institutionalizing informal, mistaken, or speculative user discussions as "precedent," creating hallucination feedback loops.
  2. **Data Minimisation Design Choice:** Persisting user conversational history across sessions violates the principle of storing only what is strictly necessary for active compliance workflows. (Regulatory claim under GDPR Article 5 to be checked by the author).
  3. **Leakage Risk Across Roles:** In multi-role institutions (Analyst, Manager, Auditor), persistent semantic memory creates a high-severity exfiltration vector. If an Auditor queries restricted internal audit findings, an embedding store indexing semantic conversational turns could permit an Analyst in a subsequent session to surface those restricted findings via semantic similarity search.
  4. **Audit Trail Determinism:** Financial compliance audits require point-in-time determinism. If an answer generated in October depended on user habits formed in June, the decision is non-reproducible and compromises audit reproducibility. (Regulatory recordkeeping claim to be checked by the author).
* **Architectural Invariant:** No vector indexing, embedding, or semantic clustering of user conversations or user profiles is implemented in the repository.
* **Cost Profile Per Call:** $0.00$.

---

### 2.4 Episodic Memory (Experience Replay / Past Interaction Episodes) — OUT OF SCOPE

* **Status:** **Explicitly Excluded / Out of Scope by Architectural Design.**
* **Definition:** Mechanism allowing the assistant to recall specific past query-answer episodes ("reflection" or "few-shot experience retrieval") to influence present reasoning.
* **Architectural Design Choices & Rationale:**
  1. **Point-in-Time Grounding vs. Temporal Decay:** Banking regulations undergo frequent amendments (e.g., PRA Policy Statements, FCA Handbook updates, Basel revisions). If the assistant recalls past interaction episodes, it risks retrieving and applying superseded regulatory thresholds (e.g., outdated capital buffer ratios or revoked sanctions lists).
  2. **Prevention of Hallucination Propagation:** If a past interaction contained an ungrounded claim that bypassed review, episodic memory would retrieve and amplify that error across future interactions.
  3. **Direct Traceability to Primary Clauses:** Sound compliance practice requires answers to trace directly to primary authoritative clauses, not past conversational episodes ("we answered this way last month"). (Regulatory explanation standard to be checked by the author).
* **Architectural Invariant:** Interactions are logged strictly in append-only audit tables (`audit_logs`) for human audit verification. The assistant's reasoning engine never queries or embeds past audit logs to formulate new answers.
* **Cost Profile Per Call:** $0.00$.

---

### 2.5 Procedural Memory (Pipeline Schemas, Tool Grammars & Prompts)

* **Definition:** Static, pre-compiled institutional knowledge governing how the pipeline operates: prompt templates, intent routing logic, grading heuristics, and mathematical tool execution rules.
* **Code Paths & Architectural Documents:**
  * `prompts/`: Versioned YAML/Jinja prompts (`prompts/prompts.yaml`, version tagged by `settings.PROMPT_VERSION`)
  * `src/core/router.py`: Intent routing schema (`RouteDecision`, `RouteType`)
  * `src/core/grader.py`: Retrieval grader schema (`GradeResult`, `PassageGrade`)
  * `src/core/calculator.py`: Whitelisted Abstract Syntax Tree (AST) grammar for deterministic arithmetic
  * `DESIGN.md` & `DECISIONS.md`: Authoritative engineering contract and architectural invariants governing pipeline behaviour
* **Role & User Scoping:**
  * **Immutable & System-Wide:** Procedural rules are baked into the application codebase and verified by automated unit tests. They cannot be altered by user queries or runtime prompts.
  * **Strict Pydantic Validation:** All structured LLM responses (routing and grading) are strictly validated against Pydantic schemas. If output violates procedural schemas, exactly one repair retry is attempted, followed by deterministic fallback (router falls back to `SINGLE_SEARCH`; grader falls back to retaining passages).
  * **Safe Arithmetic Tooling:** The calculator tool executes arithmetic strictly via Python's `ast` module against an allowlist of operators (`Add`, `Sub`, `Mult`, `Div`). No `eval()` or arbitrary execution is permitted.
* **Cost Profile Per Call:**
  * Static execution cost: $0.00$.
  * Grammar parsing latency: $< 0.1$ms.

---

### 2.6 Prospective Memory (Deferred Tasks & Asynchronous Reminders) — OUT OF SCOPE

* **Status:** **Explicitly Excluded / Out of Scope by Architectural Design.**
* **Definition:** The capacity to schedule future actions, monitor external conditions, or execute delayed background workflows (e.g., "Alert me when PRA publishes new guidance on Pillar 2A").
* **Architectural Design Choices & Rationale:**
  1. **Unbounded Agentic Risk:** Autonomous background execution without human-in-the-loop oversight presents unacceptable operational risk in financial institutions.
  2. **Permissions Invalidation Race Conditions:** In an asynchronous model, a task scheduled under valid user permissions might execute after the user's role has been downgraded or revoked, violating security policies.
  3. **System Boundary Discipline:** The assistant is explicitly engineered as a synchronous, deterministic decision support tool, strictly separated from background event loops or cron daemons.
* **Architectural Invariant:** The system exposes only synchronous HTTP request-response endpoints (`POST /api/v1/chat/query`). No job queues (Celery, Redis) or scheduling daemons exist.
* **Cost Profile Per Call:** $0.00$.

---

### 2.7 Parametric Memory (Model Weights & Local Embeddings/Rerankers)

* **Definition:** The internal, frozen knowledge encoded in the neural network weights of the generator LLM, embedding model, and cross-encoder re-ranker.
* **Code Paths & Model Identification:**
  * `src/core/llm_client.py`: Gateway interface to the generator model. Models used per profile:
    * `mock`: Deterministic offline heuristics returning canned compliance answers (`mock-compliance-v1`).
    * `local`: Small local CPU transformer `sshleifer/tiny-gpt2` (used strictly for smoke testing pipeline mechanics; cannot follow complex instructions).
    * `dev`: Free-tier Groq Cloud API with `llama-3.3-70b-versatile` (or unconfigured fallback).
    * `demo`: Paid provider model configured via `DEMO_LLM_*` environment variables.
  * `src/rag/embeddings.py`: Local CPU dense embedding generator (`BAAI/bge-small-en-v1.5`, 384 dimensions, ~130MB RAM).
  * `src/rag/reranker.py`: Local CPU cross-encoder re-ranker (`cross-encoder/ms-marco-MiniLM-L-6-v2`, ~170MB RAM).
  * **Component Separation:** Note that the local dense embedding model and the cross-encoder re-ranker are separate, self-contained local components independent of the generation LLM.
* **Role & User Scoping:**
  * **Parametric Knowledge Subordination:** Parametric knowledge is explicitly subordinated to retrieved authoritative documents. System prompts strictly mandate:
    > "You are an enterprise compliance assistant. Rely solely on the provided <authoritative_documents>. If the documents do not contain sufficient evidence to answer the question, you must refuse."
  * **Deterministic Sampling:** All compliance queries execute at `temperature = 0.0`, minimizing stochastic drift and hallucinatory output.
  * **Local CPU Execution:** Embeddings and re-ranking execute locally on CPU (~300MB RAM combined), operating in read-only inference mode with zero external network transmission.
* **Cost Profile Per Call:**
  * Local models: ~20–60ms CPU latency; 0 API cost.
  * Generator: Governed by spend guard limits (configurable RPM/TPM and token budgets).

---

### 2.8 Cache Memory (Deterministic Response Cache)

* **Definition:** On-disk deterministic response cache preventing redundant LLM calls, eliminating unnecessary API spend, and enabling deterministic re-execution of benchmark evaluations.
* **Code Paths:**
  * `src/core/llm_client.py`: `_compute_cache_key()`, `_read_cache()`, `_write_cache()`
  * `src/db/connection.py`: SQLite table `llm_cache`
* **Role & User Scoping:**
  * **Cryptographic Multi-Tenant Salt:** Cache keys are deterministic SHA-256 digests computed over all operational variables, including user identity and role:
    $$\text{CacheKey} = \text{SHA-256}\Big(\text{profile} \parallel \text{model} \parallel \text{prompt\_version} \parallel \text{step} \parallel \text{system\_prompt} \parallel \text{prompt} \parallel \text{temperature} \parallel \text{max\_tokens} \parallel \mathbf{role} \parallel \mathbf{user\_id}\Big)$$
  * **Impossibility of Cross-Role Collision:** If an `auditor` and an `analyst` execute an identical query, their cache keys differ due to the `role` and `user_id` salt. An analyst can never retrieve an answer cached by an auditor.
  * **Cache Poisoning Prevention:** Malformed JSON responses or outputs failing Pydantic validation are never written to `llm_cache` (`test_complete_json_prevents_cache_poisoning`).
* **Cost Profile Per Call:**
  * Cache Hit: Exactly 0 tokens, 0 upstream cost, ~0.4ms retrieval time from local SQLite.
  * Cache Miss: Standard upstream generation cost, followed by single SQLite write.

---

## 3. Empirical Verification & Test Evidence

The memory boundaries and multi-tenant isolation rules specified above are verified by automated tests in the continuous integration suite.

### Verified Test Suite

```
tests/test_memory.py::test_memory_is_off_by_default_for_baseline PASSED
tests/test_memory.py::test_rewrite_follow_up_uses_history PASSED
tests/test_memory.py::test_rewrite_falls_back_to_original_question_on_failure PASSED
tests/test_memory.py::test_no_history_means_no_llm_call PASSED
tests/test_memory.py::test_mock_profile_rewrite_returns_valid_json_and_is_safe PASSED
tests/test_memory.py::test_history_loading_is_scoped_to_the_owner PASSED
tests/test_memory.py::test_restricted_history_cannot_widen_retrieval PASSED
tests/test_memory.py::test_chat_runs_memory_only_when_enabled PASSED
tests/test_memory.py::test_chat_without_memory_does_not_pay_for_a_rewrite PASSED
tests/test_memory.py::test_cache_key_isolation_across_roles_and_users PASSED
tests/test_memory.py::test_session_turns_and_titles_isolated_across_users PASSED
tests/test_sessions.py::test_create_and_list_only_own_sessions PASSED
tests/test_sessions.py::test_idor_cannot_read_or_delete_another_users_session PASSED
tests/test_session_title.py::test_no_passage_text_in_the_title PASSED
```

### Key Verification Highlights

1. **Cross-Role Cache Key Isolation (`test_cache_key_isolation_across_roles_and_users`):** Proves that identical prompts evaluated under `analyst`, `manager`, and `auditor` produce strictly distinct SHA-256 cache keys.
2. **Cross-User Session History Partitioning (`test_session_turns_and_titles_isolated_across_users`):** Proves that even with knowledge of a valid `session_id`, a user cannot load recent turns or view session titles belonging to another user.
3. **Privilege Widening Prevention (`test_restricted_history_cannot_widen_retrieval`):** Proves that when an analyst's session history references auditor-only restricted text (e.g. through adversarial prompt injection or transcript manipulation), subsequent retrieval queries remain strictly bounded by analyst clearance (target leakage: $0.00\%$).
4. **Session Title Exfiltration Guard (`test_no_passage_text_in_the_title`):** Proves that session titling functions never accept document passages, citations, or context as arguments, eliminating passage exfiltration via sidebar titles.

---

## 4. Architectural Summary

By maintaining strict boundaries across the eight memory classes, the architecture guarantees:
* **Zero Cross-Tenant Leakage:** Neither cache keys, session transcripts, nor query rewrites can bridge roles or users.
* **Deterministic Grounding:** The exclusion of semantic and episodic memory prevents regulatory drift and preserves point-in-time statutory accuracy.
* **Budget & Quota Predictability:** Cache memory provides zero-cost replay, while procedural memory runs locally at zero marginal cost.

