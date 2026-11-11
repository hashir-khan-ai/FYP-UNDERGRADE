# Engineering Decisions & Deviations Log

**Project:** Enterprise RAG Assistant for Banking Regulatory Compliance  
**Module:** COM6301 (BSc Final Year Project)  
**Purpose:** Records every deviation from the frozen docs, and every judgement call
made where the specification was silent. Newest phase first within each section.

---

## Part A — Phase 2 Closeout

### A1. Embedded Qdrant lifecycle (shutdown warning fix)
**Decision:** `QdrantIndexer` is a context manager with an explicit `close()`, the
FastAPI `lifespan` closes the shared pipeline on shutdown, ingestion/smoke/leakage
scripts close in `finally`, and every client creation registers an `atexit` safety
net that swallows teardown exceptions.

**Why:** On Windows the embedded client holds a `portalocker` file lock. If the
interpreter tears down the process before the client closes, `portalocker` prints a
`Traceback ... AttributeError` during module finalisation. Explicit, ordered close
removes the race instead of hiding it.

**Verification:** explicit-close script and full smoke run both produce no
`portalocker`/`Traceback` output on stderr. `close()` is idempotent (sets the
client reference to `None` before closing).

### A2. `BM25Plus` instead of `BM25Okapi` (PLAN.md deviation)
**Decision:** Use `rank_bm25.BM25Plus`.

**Why:** `BM25Okapi` computes an IDF term that becomes zero or negative when a term
appears in at least half of a tiny corpus (the six-document baseline). That silently
zeroes otherwise valid keyword matches and makes the hybrid retrieval behave
unpredictably on small synthetic corpora. `BM25Plus` uses a positive floor on IDF,
so a rare-but-present term still scores.

**Trade-off:** slightly higher scores overall; RRF uses ranks, not raw scores, so
fusion behaviour is unaffected. Documented rather than tuned.

### A3. Retrieval lives in `src/ingestion/` + `src/rag/` (PLAN.md deviation)
**Decision:** `QdrantIndexer` and `BM25Indexer` stay in `src/ingestion/indexer.py`;
fusion, re-ranking, and generation stay in `src/rag/baseline.py`. No `src/retrieval/`
package was created.

**Why:** The implementation already existed and was tested. Splitting it into the
PLAN.md paths would be a pure file move with zero behavioural value and would risk
breaking the passing Phase 2 suite. AGENTS.md prioritises small, atomic diffs and
explicitly forbids unsolicited refactoring.

### A4. Deferred chat/session response shape
**Decision:** Phase 2 shipped only `/ask` plus a minimal `/health`. The full chat and
session contracts in API.md were deferred and are now implemented in Phase 3.

**Why:** Phase 2 had no session store or identity to scope them to; shipping the
endpoints without ownership checks would have created an IDOR surface. Phase 3 adds
the sessions/messages tables and authentication, so the endpoints were built there
with ownership enforcement from the start.

### A5. Live `dev` smoke run skipped
**Decision:** The live `scripts/smoke_demo.py --profile dev` run was **skipped**.

**Why:** `.env` does not exist in this workspace and `LLM_API_KEY` is unset, so the
`dev` profile correctly refuses to resolve
(`LLM profile 'dev' requires LLM_API_KEY`). The smoke suite was instead executed on
the deterministic `mock` profile and reported separately. No live API call was
made, and nothing is claimed about live-provider latency.

---

## Phase 3 — Access Control & Conversational Memory

### 1. Password hashing: Argon2id via `argon2-cffi`
**Decision:** Add `argon2-cffi==25.1.0` (pulls `argon2-cffi-bindings`, `cffi`,
`pycparser`) to `requirements.txt` with a justification comment.

**Why:** Argon2id is the current OWASP-recommended password hashing function, and
`argon2-cffi` is the maintained reference binding with prebuilt Windows wheels.
`bcrypt` would also have been acceptable; Argon2id was chosen for its memory-hard
parameters. Passwords are never stored or logged in plaintext. This is the **only**
package added in Phase 3.

### 2. Tokens: stdlib HMAC-SHA256 signed bearer tokens (no JWT library)
**Decision:** Access tokens are `<base64url(payload)>.<base64url(HMAC-SHA256)>`,
signed with `SECRET_KEY`, carrying `sub`, `username`, `role`, `jti`, `iat`, `exp`.

**Why:** ARCHITECTURE.md names "Session Auth" and API.md says
`Bearer <jwt_or_user_token>`, but no JWT library is pinned and adding one for a
local single-user demo would be an unjustified dependency. A signed, expiring,
revocable token provides the same guarantees required here (integrity, expiry,
logout) with the standard library only. Recorded as an explicit choice.

**Limitations (recorded, not hidden):** revocation and login-throttle state are
in-process, which is correct for the single-instance local demo and would move to
shared storage in a distributed deployment.

### 3. Role is always reloaded from SQLite, never trusted from the token or body
**Decision:** `get_current_user` validates the token, then loads the user row and
derives `role` from the `roles` table. The `role` claim is used only for diagnostics.
Any client-supplied `role`/`user_id` field is ignored because the request models do
not read it.

**Why:** Makes role changes take effect immediately and removes privilege-escalation
via a forged claim. A test proves a token that claims `auditor` for an `analyst`
user still resolves to `analyst`.

### 4. `ENABLE_RBAC` is authoritative, with a guarded off-switch
**Decision:** `ENABLE_RBAC` defaults to `true`. `settings.rbac_enabled` raises
`RuntimeError` unless `APP_ENV=test` or `BASELINE_ABLATION=true`. The value is
written into every result (`BaselineRAGResponse.rbac_enabled`, the API response, and
the audit row indirectly via the role and filter counters).

**Why:** An accidental `ENABLE_RBAC=false` in `.env` must fail loudly rather than
silently expose restricted documents. `ENABLE_RBAC_MEMORY` is retained as a derived
compatibility flag for the frozen API/health shape.

### 5. Filtering order and counter semantics
**Decision:** The role filter is applied inside both indexes *before* RRF fusion:
Qdrant via a native `allowed_roles` payload filter, BM25 against candidate metadata.
After re-ranking, `enforce_role_visibility` drops and counts any passage that does
not permit the role. `chunk_visible_to_role` denies by default when `allowed_roles`
is missing or empty.

**Why:** Defence in depth plus a fail-closed default: an ingestion bug cannot widen
access.

**Counter semantics:** Qdrant reports `filtered=0` because native filtering excludes
points before scoring, so nothing is dropped *after* the query. The audit
`candidates_filtered` value therefore combines the BM25 pre-filter drops and the
post-rerank drops, which is the only honest count available. `candidates_retrieved`
is the number of hits BM25 plus Qdrant actually returned.

### 6. Uniform refusal text and prompt boundary
**Decision:** When no permitted passage survives, the pipeline returns
`"I can't find that in the documents available to your role."` and makes **no** LLM
call. The answer prompt places passages inside `<authoritative_documents>` and
instructs the model to treat them as untrusted data, ignoring embedded instructions.

**Why:** The refusal must not reveal whether restricted documents exist, and paying
for an LLM call on empty context adds cost and hallucination risk. The XML boundary
plus the explicit instruction is the prompt-injection control; a fixture document
containing "ignore previous instructions" is proven to remain data and to keep role
filtering intact.

### 7. Cache safety across roles
**Decision:** No extra namespace was added to the LLM cache key; safety comes from
the fact that only role-permitted passages are ever rendered into a prompt, so the
same question asked by two roles produces different prompt text (different chunk
IDs/passages) and therefore different cache keys. A dedicated test asserts the two
roles' cache rows are disjoint and that no restricted marker appears in the lower
role's cached answer.

**Why:** Adding role to the cache key would be redundant *and* would mask a
regression where restricted text leaked into the prompt. Keeping the key
content-derived means the existing isolation test actually tests the pipeline.

### 8. Memory scope and defaults
**Decision:** `ENABLE_MEMORY` defaults to `false` in `src/config.py` (baseline
experiments and all automated tests) and is set to `true` in `.env.example` for the
running application. History is loaded only after an ownership check
(`get_session_for_user`), capped by `MEMORY_MAX_TURNS`, and passed through the single
LLM gateway as strict JSON with one repair retry and a fallback to the original
question. Each stored message records the role used at the time.

**Why:** Matches the requirement ("false for baseline, true for the app") without
making tests pay for a rewrite call. Retrieval is always filtered by the *current*
role, so history can never widen access — proven by a test where a transcript
mentions auditor-only text and an analyst still retrieves nothing restricted.

### 9. `config_overrides` is accepted but cannot disable security layers
**Decision:** API.md's `config_overrides` object is modelled for contract
compatibility, but `enable_rbac_memory`, `enable_adaptive_router`, etc. are ignored
server-side. RBAC and memory are controlled only by server configuration.

**Why:** Letting a client turn off RBAC is a direct data-leak primitive. The field
exists so the frozen API shape validates; it has no effect.

### 10. Audit records identifiers and counters, never content
**Decision:** Each chat request writes `audit_log` with user id, role, session id,
timestamp, query text, route, cited chunk **IDs**, relevance scores, latency, token
counts, profile, model, prompt version, LLM call/cache counts, spend-guard hit, and
role-filter counters. Reasoning traces contain only counts and step labels. No passage
text, prompt body, token, key, or password hash is written to audit or logs.

**Note:** `query_text` and the final answer are stored because DATABASE.md's schema
requires them for the audit/XAI foundation; they are the user's own turn, not
restricted corpus content.

### 11. Seeded credentials
**Decision:** `scripts/seed_data.py` hashes one synthetic password
(`SEED_DEFAULT_PASSWORD`, default `password123`) with Argon2id for all three demo
users, using an upsert that preserves user IDs and therefore existing audit/session
references.

**Why:** The three synthetic roles need working logins for the demo. The default is
documented in `.env.example`, overridable locally, and is not a real credential. The
upsert avoids the data loss that a delete-and-reinsert would cause on the existing
`audit_log.user_id` foreign key.

### 12. Endpoint protection changes in Phase 3
**Decision:** `POST /ask` and `GET /api/v1/admin/health` now require a bearer token.
`GET /health` stays public (liveness probe, exposes no corpus content).
`GET /api/v1/auth/users` lists synthetic users only when `APP_ENV` is `development`
or `test`; otherwise it returns 403.

**Why:** `/ask` performs retrieval, so it must never run without an authenticated
role. `/health` must remain usable by a local probe before login.

### 13. Session IDOR handling
**Decision:** A session that exists but belongs to another user returns **404**
`SESSION_NOT_FOUND`, identical to a non-existent session.

**Why:** 403 would confirm that the ID exists, leaking metadata. 404 makes the two
cases indistinguishable. The same check guards read, delete, and chat.

### 14. Phase 3 scope kept clean
**Decision:** No adaptive router, no corrective grader, no XAI output rendering, and
no Streamlit UI were added. `route_taken` is the constant `SINGLE_SEARCH`,
`retry_count` is 0, and `reasoning_trace` is a minimal factual step list.

**Why:** Phase 4 and Phase 5 are not authorised. The response fields exist only
because API.md's frozen shape requires them.
