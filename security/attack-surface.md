# Attack Surface Analysis

**System:** Enterprise RAG Assistant for Banking Regulatory Compliance  
**Module:** COM6301 (BSc Final Year Project)  
**Evaluation Target:** Current Codebase (Phase 5 Closeout)  
**Scope:** Network Ingress, API Endpoints, Authorization Gates, Data Stores, Third-Party Interfaces  

---

## 1. Public & Internal Endpoints

All HTTP endpoints are defined in `src/api/routes.py` and `src/api/main.py`:

| Endpoint | HTTP Method | Auth Required | Intended Access | Description |
|---|---|---|---|---|
| `/health` | `GET` | **No** | Public | Returns service status, LLM profile name, and layer flags. |
| `/api/v1/auth/login` | `POST` | **No** | Public | Authenticates username/password; returns JWT bearer token. |
| `/api/v1/auth/users` | `GET` | **No (Dev/Test)** | Public (Dev/Test only) | Returns synthetic users directory for local switcher UI. |
| `/api/v1/auth/me` | `GET` | **Yes (Bearer)** | Authenticated User | Returns caller's user profile and verified server-side role. |
| `/api/v1/auth/logout` | `POST` | **Yes (Bearer)** | Authenticated User | Revokes token `jti` in database until expiration. |
| `/api/v1/sessions` | `POST` | **Yes (Bearer)** | Authenticated User | Creates a new chat session owned by caller `user_id`. |
| `/api/v1/sessions` | `GET` | **Yes (Bearer)** | Authenticated User | Lists chat sessions strictly owned by caller `user_id`. |
| `/api/v1/sessions/{id}` | `GET` | **Yes (Bearer)** | Authenticated User | Returns session metadata and historical turns for owner. |
| `/api/v1/sessions/{id}` | `DELETE`| **Yes (Bearer)** | Authenticated User | Deletes session and associated messages owned by caller. |
| `/api/v1/chat/query` | `POST` | **Yes (Bearer)** | Authenticated User | Submits user query; runs router, retrieval, grader, RAG. |
| `/api/v1/audit/logs` | `GET` | **Yes (`auditor`)** | Auditor Role Only | Queries compliance audit records; returns 403 for non-auditors. |
| `/api/v1/admin/health` | `GET` | **Yes (Bearer)** | Authenticated User | Extended system diagnostic health information. |
| `/ask` | `POST` | **Yes (Bearer)** | Authenticated User | Legacy Phase 2 baseline retrieval/answer endpoint. |

---

## 2. Authentication & Authorization Attack Surfaces

1. **JWT Header Verification Surface:**  
   - Handled by `get_current_user` in `src/api/deps.py`.
   - Parses `Authorization: Bearer <token>`.
   - Verifies HS256 signature using `settings.SECRET_KEY`.
   - Validates `exp` timestamp claim.
   - Queries `revoked_tokens` table to reject logged-out `jti`s.
   - Enforces database user existence and active status.
2. **Role Authorization & RBAC Enforcement Surface:**  
   - Handled by `src/core/security.py` and `src/rag/baseline.py`.
   - User role is extracted *strictly* from the validated database/JWT identity (`user.role`).
   - The query endpoint completely ignores any client-supplied role parameter.
   - Role permissions:
     - `analyst`: Can retrieve `public` and `analyst` chunks.
     - `manager`: Can retrieve `public`, `analyst`, and `manager` chunks.
     - `auditor`: Can retrieve `public`, `analyst`, `manager`, and `auditor` chunks.
   - Filtering is enforced at the database layer (Qdrant payload filter) and re-verified post-rerank.
3. **Session Ownership & IDOR Protection:**  
   - Handled in `src/api/routes.py`.
   - Every session query (`GET`, `DELETE`, `chat/query`) asserts `int(session["user_id"]) == user.id`.
   - If user ID does not match, the API raises `ApiError(404, "SESSION_NOT_FOUND", ...)` to prevent user enumeration.

---

## 3. User Inputs & Serialization Surfaces

1. **Chat Query Input (`/api/v1/chat/query`):**  
   - Input field: `query: str` (Pydantic validated: `min_length=1`, `max_length=1000`).
   - Injection risk: Adversarial prompts attempting to override system instructions or leak restricted chunks.
   - Mitigation: Context passages are enclosed in XML tags (`<authoritative_documents>`) and passed to generation with instructions treating documents as passive untrusted data.
2. **Session Creation (`/api/v1/sessions`):**  
   - Input field: `title: str | None` (Pydantic validated: `max_length=120`).
   - Stripped and sanitized before database insertion.
3. **Authentication Credentials (`/api/v1/auth/login`):**  
   - Input fields: `username: str`, `password: str`.
   - Rate-limited per username to prevent automated brute-force attacks.

---

## 4. File Uploads & Document Ingestion Surfaces

- **No Public File Upload Endpoints:**  
  There are zero public or client-facing file upload endpoints exposed by FastAPI.
- **Offline / Internal Ingestion Only:**  
  Document ingestion occurs strictly offline via `scripts/run_ingestion.py` reading trusted local directories:
  - Public regulations: `./data/raw/` (Markdown files)
  - Synthetic internal policies: `./data/synthetic/` (Markdown files)
  - Documents are parsed using standard library file operations and markdown loaders (`src/ingestion/loader.py`).

---

## 5. Database & Storage Access Surfaces

1. **SQLite Database (`./data/sqlite/app.db`):**  
   - Tables: `roles`, `users`, `sessions`, `messages`, `audit_log`, `llm_calls`, `llm_cache`, `revoked_tokens`.
   - All database queries across `src/db/repository.py` use parameterized SQL statements (`?` placeholders).
   - Zero raw string formatting (`f"..."`) or dynamic SQL execution exists in the entire repository.
   - Foreign key constraints are strictly enforced via `PRAGMA foreign_keys = ON;`.
2. **Embedded Qdrant Vector DB (`./data/qdrant`):**  
   - Vector collection: `regulatory_chunks` (384-dimensional cosine similarity vectors).
   - Local embedded storage using file-level `storage.lock`.
   - Query filters use native Qdrant `Filter` and `FieldCondition` structs. No dynamic query strings.

---

## 6. Third-Party Integrations & External Reachability

1. **Upstream LLM Provider API:**  
   - Endpoints: Configured via `LLM_BASE_URL` (Groq/OpenAI/OpenRouter compatible).
   - Interface: Handled strictly via `src/core/llm_client.py` using `requests.Session` with strict timeouts (`15s`), retry backoff, and jitter.
   - Response validation: All router and grader JSON outputs are validated using Pydantic models with schema repair and deterministic fallbacks.
2. **HuggingFace Hub / Local Models:**  
   - Models: `BAAI/bge-small-en-v1.5` (embeddings) and `cross-encoder/ms-marco-MiniLM-L-6-v2` (re-ranker).
   - Executed locally on CPU. No data leaves the machine during embedding or re-ranking.
   - Offline mode: Setting `HF_HUB_OFFLINE=1` disables all remote metadata queries.

---

## 7. Categorized Findings & Vulnerability Assessment

### A. Confirmed Vulnerability

*None identified.* The application enforces strict parameterization, schema validation, server-side RBAC, and ownership boundaries.

---

### B. Security Weakness

#### 1. Permissive CORS Headers Configuration in Development
- **Severity:** Medium
- **Evidence:** `src/api/main.py:46-52`:
  ```python
  app.add_middleware(
      CORSMiddleware,
      allow_origins=settings.cors_origins_list,
      allow_credentials=True,
      allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
      allow_headers=["*"],
  )
  ```
  `allow_headers=["*"]` allows arbitrary HTTP headers from permitted origins.
- **Risk:** Permissive header specifications can expose the API to custom header manipulation if a permitted origin (`localhost:3000`) suffers from XSS.
- **Affected Location:** `src/api/main.py:50`
- **Why It Matters:** Defense-in-depth requires explicit whitelisting of accepted headers (`Authorization`, `Content-Type`).
- **Recommended Fix:** Explicitly whitelist permitted request headers (`["Authorization", "Content-Type", "Accept"]`) rather than wildcard `["*"]`.

#### 2. User Directory Disclosure via `GET /api/v1/auth/users`
- **Severity:** Low
- **Evidence:** `src/api/routes.py:133-149` returns all usernames, full names, and roles when `APP_ENV != "production"`.
- **Risk:** Discloses valid account names and roles, facilitating targeted password spraying against the login endpoint.
- **Affected Location:** `src/api/routes.py:133-149`
- **Why It Matters:** Reduces attacker effort during reconnaissance.
- **Recommended Fix:** Restrict the endpoint strictly to authenticated `auditor` or admin users, or disable entirely outside local UI testing.

---

### C. Missing Control

#### 1. Global API Rate Limiter
- **Severity:** Medium
- **Evidence:** While `POST /api/v1/auth/login` has a dedicated in-memory throttle (`InMemoryLoginThrottle`), authenticated endpoints (`/api/v1/chat/query`, `/api/v1/sessions`) do not have per-IP or per-user rate limiters.
- **Risk:** An authenticated user can submit thousands of concurrent chat queries, depleting the per-run token budget in `SpendGuard` or overwhelming the local CPU models.
- **Affected Location:** `src/api/routes.py:chat_query`
- **Why It Matters:** Protects backend CPU and upstream LLM quota from denial-of-service abuse.
- **Recommended Fix:** Implement a token-bucket rate limiter middleware across all authenticated API endpoints (e.g., 30 requests per minute per user).

#### 2. Security Headers Middleware (HSTS, CSP, X-Frame-Options)
- **Severity:** Low
- **Evidence:** `src/api/main.py` does not register standard HTTP security response headers (`Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Strict-Transport-Security`).
- **Risk:** Increased susceptibility to clickjacking or MIME-sniffing when responses are embedded in external web frames.
- **Affected Location:** `src/api/main.py`
- **Why It Matters:** Industry-standard defense-in-depth for financial and regulatory compliance services.
- **Recommended Fix:** Add middleware injecting standard security headers on all HTTP responses.

---

### D. Potential Risk Requiring Verification

#### 1. SQLite File System Permissions
- **Severity:** Low
- **Evidence:** `./data/sqlite/app.db` is created with default OS filesystem permissions.
- **Risk:** On shared multi-user server environments, other local OS users might have read access to the SQLite database file containing password hashes and audit records.
- **Affected Location:** `src/db/connection.py:10-15`
- **Why It Matters:** Database files must be readable solely by the application process owner.
- **Recommended Fix:** Set explicit filesystem file permissions (`chmod 600` on POSIX, or restricted ACLs on Windows) when creating database files in production.

---

### E. Recommendations

1. **Deploy Behind Reverse Proxy:** Always terminate TLS (HTTPS) and enforce rate limiting via Nginx or Cloudflare in production deployments.
2. **Explicit HTTP Method Restrictions:** Ensure web application firewall (WAF) blocks non-standard HTTP verbs at the perimeter.
3. **Structured Ingress Payload Sizing:** Enforce a maximum HTTP request body size (e.g. 1MB) at the web server layer to reject oversized denial-of-service payloads.

