# Secrets Management & Hygiene Assessment

**System:** Enterprise RAG Assistant for Banking Regulatory Compliance  
**Module:** COM6301 (BSc Final Year Project)  
**Evaluation Target:** Current Codebase (Phase 5 Closeout)  
**Policy:** Zero Hardcoded Credentials, Mandatory Parameterization, Clean Environment Boundaries  

---

## 1. Secrets Inventory & Expected Locations

The system requires and interacts with the following classes of sensitive credentials:

| Secret Identifier | Category | Purpose | Ingestion / Storage Path | Sensitivity |
|---|---|---|---|---|
| `SECRET_KEY` | Symmetric Key | Signing & verifying JWT user session tokens (HS256) | Environment variable (`.env` -> `src/config.py`) | **High** |
| `LLM_API_KEY` | Provider API Token | Upstream inference authentication for `dev` profile | Environment variable (`.env` -> `src/config.py`) | **High** |
| `DEMO_LLM_API_KEY` | Provider API Token | Upstream inference authentication for `demo` profile | Environment variable (`.env` -> `src/config.py`) | **Critical** |
| `FALLBACK_LLM_API_KEY` | Provider API Token | Upstream inference authentication for failover profile | Environment variable (`.env` -> `src/config.py`) | **High** |
| `SEED_DEFAULT_PASSWORD` | Initial Password | Password seed for synthetic users (`scripts/seed_data.py`) | Environment variable (`.env` -> `scripts/seed_data.py`) | **Medium** |
| User Password Hashes | Storage Credential | Authenticating users at `/api/v1/auth/login` | SQLite `users` table (`password_hash`) | **High** |
| Active JWT Tokens | Bearer Token | Authenticating REST requests in `Authorization` header | Transient client storage & memory | **High** |

---

## 2. Environment & Configuration Handling

- **Single Gateway Configuration:** Credentials resolve exclusively via `src/config.py` using Pydantic `BaseSettings`. No module outside `src/config.py` directly parses `.env` or reads raw environment variables.
- **Fail-Fast Profile Guard:** If a profile requiring live credentials (`dev` or `demo`) is selected without the corresponding API key, `src/config.py:ensure_llm_ready()` raises an explicit `ValueError` identifying the missing variable by name without logging any key fragments.
- **Credential Separation Between Profiles:** The `demo` profile resolves exclusively from `DEMO_LLM_API_KEY` and never borrows or falls back to `LLM_API_KEY`, preventing accidental cross-provider credential bleed.
- **Test Isolation:** In automated tests (`APP_ENV=test`), `tests/conftest.py` strictly forces `LLM_PROFILE=mock` before settings resolution. Any test attempting to resolve a live profile fails fast with `RuntimeError`.

---

## 3. Git & Repository Hygiene

- **`.gitignore` Enforcement:**  
  Evidence: `.gitignore` contains explicit patterns ignoring `.env`, `data/sqlite/*.db`, `data/qdrant/`, `data/cache/`, `.venv/`, `__pycache__/`, and `.pytest_cache/`.
- **`.env.example` Hygiene:**  
  Evidence: `.env.example` provides complete template blocks for all profiles with clear dummy strings (`gsk_dev_dummy_key_not_real`, `sk-demo-dummy-key-not-real`). No live or real API keys exist in the repository template.
- **Synthetic Data Verification:**  
  Evidence: All files in `data/synthetic/` (`SOP-KYC-001.md`, `POLICY-SUPERVISORY-002.md`, `AUDIT-LIQUIDITY-2025.md`) contain only fictitious procedural rules, synthetic customer thresholds, and fabricated organizational markers. Zero real bank data, customer PII, or internal credentials exist in the corpus.

---

## 4. Logging, Error & Storage Hygiene

- **No Credential Logging in Telemetry:**  
  Evidence: `src/core/llm_client.py` and `src/db/repository.py` record latency, prompt tokens, completion tokens, profile name, and model name into `llm_calls` and `audit_log`. The `Authorization` header, client API keys, and prompt inputs are excluded from audit log columns.
- **Sanitized API Errors:**  
  Evidence: `src/api/main.py` registers global exception handlers for `ApiError`, `RequestValidationError`, `LLMAuthError`, `LLMUnavailableError`, and general `Exception`. Stack traces, file system paths, and internal error payloads are replaced with sanitized JSON responses (e.g. `{"error": {"code": "SERVICE_UNAVAILABLE", "message": "Upstream LLM provider is currently unavailable."}}`).
- **Cryptographic Storage of Passwords:**  
  Evidence: `src/core/auth.py` hashes passwords using `hashlib.pbkdf2_hmac("sha256", password, salt, 100_000)` with a 16-byte cryptographically secure random salt (`os.urandom(16)`). Plaintext passwords are never persisted to disk.

---

## 5. Secret Rotation & Lifecycle Requirements

1. **`SECRET_KEY` Rotation:**  
   - Rotating `SECRET_KEY` invalidates all existing user JWT tokens.
   - Recommended lifecycle: 90-day rotation in production, supported by a transition period where tokens signed with the previous key are accepted until expiration.
2. **LLM Provider API Keys:**  
   - Rotation requires updating `.env` and triggering an application restart. Because `src/config.py` instantiates settings on startup, key changes take effect immediately upon worker recycle without database modifications.
3. **Revoked Token Housekeeping:**  
   - SQLite `revoked_tokens` table stores `jti` and `expires_at`. Tokens remain blocked until natural expiration. Expired `revoked_tokens` rows should be purged periodically.

---

## 6. Categorized Findings & Vulnerability Assessment

### A. Confirmed Vulnerability

*None identified.* All credential handling adheres to environment isolation and parameterization standards.

---

### B. Security Weakness

#### 1. Insecure Default Value for `SECRET_KEY` in Configuration Schema
- **Severity:** Medium
- **Evidence:** `src/config.py:42`:  
  `SECRET_KEY: str = Field(default="dev-secret-key-change-in-production-32-chars-min", ...)`
- **Risk:** If an administrator starts the service in a production or publicly accessible staging environment without configuring `SECRET_KEY` in `.env`, the system defaults to this well-known static string. An attacker could forge valid JWT tokens for any role.
- **Affected Location:** `src/config.py:41-45`
- **Why It Matters:** JWT signature validity relies entirely on the confidentiality of `SECRET_KEY`.
- **Recommended Fix:** Enforce a startup check in `validate_security_flags()` that raises an exception if `APP_ENV == "production"` and `SECRET_KEY` matches the default value or has less than 256 bits of entropy.

#### 2. Deterministic Fallback Password in `seed_data.py` for Non-Test Environments
- **Severity:** Low
- **Evidence:** `scripts/seed_data.py:32-38`:  
  Checks `SEED_DEFAULT_PASSWORD` and raises an error if unset, but allows `"password123"` when `APP_ENV == "test"`.
- **Risk:** If a developer seeds a non-test database while setting `APP_ENV=test` temporarily, accounts are provisioned with trivial default passwords (`password123`).
- **Affected Location:** `scripts/seed_data.py:32-38`
- **Why It Matters:** Default seed credentials are a frequent entry point for unauthorized access during deployment staging.
- **Recommended Fix:** Print a prominent security warning to stderr whenever `scripts/seed_data.py` is invoked with test defaults.

---

### C. Missing Control

#### 1. Automated Secret Rotation Hook for JWT Signing Key
- **Severity:** Low
- **Evidence:** `src/core/auth.py` supports only a single static `settings.SECRET_KEY`.
- **Risk:** Immediate revocation of all user sessions during emergency secret rotation, causing disruption to active users.
- **Affected Location:** `src/core/auth.py:80-115`
- **Why It Matters:** Graceful key rotation (dual-key verification) enables zero-downtime credential refresh.
- **Recommended Fix:** Implement key ID (`kid`) support in JWT headers allowing verification against both a primary and secondary key during rotation windows.

---

### D. Potential Risk Requiring Verification

#### 1. Accidental Inclusion of `.env` in Unverified Working Tree Backups
- **Severity:** Medium
- **Evidence:** `.env` is present in local development workspace for runtime execution.
- **Risk:** Manual copy commands (e.g. creating zip archives of the workspace) could accidentally capture `.env` if `.gitignore` is not respected by archive tools.
- **Affected Location:** Repository root `.env`
- **Why It Matters:** Leaked `.env` exposes provider API keys and JWT signing secrets.
- **Recommended Fix:** Ensure release packaging and build scripts explicitly exclude `.env` and verify via automated pre-commit scanning (`detect-secrets` or `trufflehog`).

---

### E. Recommendations

1. **Automated Entropy Checking on Startup:** Validate that all loaded API keys and secret strings meet minimum length and randomness requirements.
2. **Environment Variable Injection via Vault / Cloud Secrets:** When deploying to production cloud infrastructure (AWS/GCP/Azure), inject secrets directly via environment secret managers rather than file-backed `.env` files.

