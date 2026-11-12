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

---

## Phase 4 — Adaptive Router & Hardening

### 15. Audit endpoint returns summaries, not stored turn text (API.md deviation)
**Decision:** `GET /api/v1/audit/logs` stays **auditor-only** but no longer returns
`query_text` or `response_text`. `AuditLogEntry` now carries `router_confidence` and
`router_fallback_reason` instead, and `sub_questions` is deliberately withheld.

**Why:** The security instruction for this phase is stricter than the frozen API.md
shape: an auditor may read audit summaries, but only the owning user may read their
own turn text. Sub-questions are paraphrases of the user's question, so exposing them
would leak the same text indirectly. The user's own history remains available through
`GET /api/v1/sessions/{id}/messages`, which is owner-only and returns 404 for a
foreign session. Both rules are covered by tests.

### 16. Additive audit columns (DATABASE.md deviation)
**Decision:** Four nullable columns were added to `audit_log` via
`apply_migrations`: `router_confidence`, `router_fallback_reason`, `sub_questions`,
`step_timings_json`.

**Why:** The phase requires per-step observability (route, confidence, sub-questions,
fallback reasons, latency/tokens per step). The migration is additive and nullable, so
existing rows and the frozen schema remain valid; no data is rewritten.

### 17. Route naming: lowercase in the model, uppercase in the API/DB
**Decision:** The router prompt and `RouterOutput` use `direct|single_search|split`.
`RouteDecision.route` uses the same lowercase values internally, and `ROUTE_API_NAMES`
maps them to the frozen API/DB values `DIRECT_REPLY|SINGLE_SEARCH|MULTI_PART_SPLIT`.

**Why:** Short lowercase tokens are the least error-prone JSON the model can emit and
are what the prompt documents; the frozen external contract is preserved unchanged.

### 18. Router prompt location
**Decision:** The prompt lives at `prompts/router/v1.md` with no YAML front-matter,
loaded through the existing `load_prompt` helper.

**Why:** Matches the PLAN.md layout and the loader's candidate paths, and keeps the
prompt style consistent with the existing `prompts/v1/*.txt` files.

### 19. Rule pre-check scope and the short-input clarification
**Decision:** The deterministic pre-check covers greetings, thanks, capability
questions, unsafe requests, clearly out-of-scope topics, and inputs shorter than 12
characters or at most two tokens. A greeting/thanks followed by a real question does
**not** match and is classified normally.

**Why:** These cases are cheap and unambiguous, and matching them avoids a paid call.
The short-input rule prevents a one-word query from being turned into a fabricated
answer; it returns the clarification template, which contains no facts and no digits.

### 20. `direct` can only ever return a fixed template
**Decision:** Both the rule pre-check and the LLM may select `direct`, but the reply
is always one of the six fixed `DIRECT_REPLIES` templates. The model never writes
factual content on the direct path, and no retrieval happens.

**Why:** A model-authored "direct" answer would be ungrounded content outside the
RBAC-filtered corpus, which is exactly what the project forbids. Fixed templates make
the path safe by construction.

### 21. Every fallback degrades to `single_search`, never to `direct`
**Decision:** Invalid JSON, provider errors, low confidence
(`< ROUTER_CONFIDENCE_THRESHOLD`), more than `ROUTER_MAX_SUB_QUESTIONS`, fewer than two
sub-questions, and exceeding `ROUTER_MAX_RETRIEVAL_CALLS` all resolve to
`single_search` with a recorded `fallback_reason`.

**Why:** `single_search` is the conservative baseline: it still retrieves with the
same role filter. Degrading to `direct` would skip retrieval and could produce an
unhelpful or unsafe reply, so it is never used as a fallback.

### 22. Split retrieval semantics
**Decision:** Each sub-question runs through `retrieve` + `rerank` with the
authenticated role, so the native payload filter and the post-rerank guard apply to
every part. Passages are merged by `chunk_id` keeping the best score and capped to
`RERANKER_TOP_N`, then a **single** generation call answers the original question.

**Why:** One generation over the merged evidence keeps cost and latency bounded and
avoids the model answering from separate, partial contexts. The merge is also what the
leakage matrix and the de-duplication test verify.

### 23. Token accounting per step is the spend-guard delta
**Decision:** Per-step `tokens` records the change in `spend_guard.tokens_count`
across the step rather than a prompt/completion split the pipeline cannot attribute
per step.

**Why:** Reporting a fabricated split would be dishonest. The delta is exact, and the
existing aggregate prompt/completion counters in `llm_stats` are unchanged.

### 24. Router-off behaviour is unchanged
**Decision:** `ENABLE_ADAPTIVE_ROUTER` defaults to `false` in `src/config.py` (all
tests and the baseline) and is `true` in `.env.example`. With it off, the chat path is
the Phase 3 path: no router call, `route_taken` is `SINGLE_SEARCH`, the five original
reasoning-trace lines are byte-identical, and the router audit columns stay null/empty.

**Why:** The dissertation baseline must remain reproducible. A regression test asserts
the trace and that no `step='router'` call is written when the flag is off.

### 25. Routing labels are draft
**Decision:** `data/eval/routing_labels.jsonl` contains 42 hand-written questions
(12 direct, 20 single_search, 10 split) plus a `_meta` record marked
`"status": "draft"`.

**Why:** The mock-profile evaluation is a harness sanity check, not a dissertation
result. The labels need student review before any number is quoted as a finding. The
current mock accuracy (85.7%, 36/42) mostly reflects the deterministic mock router
heuristic, not a real model's routing quality.

### 26. Seed password has no default
**Decision:** `scripts/seed_data.py` reads `SEED_DEFAULT_PASSWORD` and refuses to run
outside `APP_ENV=test` when it is unset. The `test` environment uses a clearly
non-credential constant so the suite stays deterministic.

**Why:** A hardcoded demo password is a real credential smell. The failure message
names the variable to set, and `.env.example` documents it. This supersedes decision 11.

### 27. Live `dev` smoke still skipped
**Decision:** `.env` has no configured live key in this workspace, so live runs
were skipped and the `mock` profile was reported instead.

**Why:** No live key is configured, and the `dev` profile correctly refuses to resolve
without one. Nothing is claimed about live-provider latency or token use.

---

## Part E — Phase 5 Closeout (Corrective Grader)

### 28. Prompt formatting with JSON schema examples
**Decision:** Prompts containing JSON examples (`prompts/grader/v1.md`,
`prompts/rewrite/v1.md`) use string replacement (`.replace("{question}", ...)`)
rather than `str.format()` or f-strings.

**Why:** Markdown prompts with JSON schemas contain literal curly braces (`{`, `}`).
Using `str.format()` treats JSON braces as Python formatting keys, throwing `KeyError`.
Using `.replace()` preserves literal JSON schemas without fragile double-brace escaping.

### 29. Additive audit schema in `SCHEMA_DDL`
**Decision:** Grader observability columns are added to both `SCHEMA_DDL` in
`src/db/migrations.py` and `_AUDIT_LOG_EXTRA_COLUMNS`.

**Why:** Running `ALTER TABLE` during runtime connection pooling on Windows causes
intermittent SQLite file locks. Placing nullable columns in the initial DDL ensures
clean initialization on fresh databases while preserving migration safety for upgrades.

### 30. Corrective Grader shortcuts and safe degradation
**Decision:** Cross-encoder scores above `GRADER_SHORTCUT_HIGH_THRESHOLD` with sufficient
passages bypass LLM grading (`shortcut_keep`). Unparseable LLM output triggers exactly
one repair retry before falling back to keeping all passages (`fallback_used=true`).

**Why:** Keeps latency and token spend minimal for obvious relevant matches. Under model
malfunction or malformed output, evidence is never silently dropped, and RBAC filtering
remains strictly enforced.

### 31. Retry retrieval preserves strict RBAC filter
**Decision:** Rewritten queries are re-retrieved using the exact same role-derived payload
filter and cross-encoder re-ranking threshold.

**Why:** A rewritten query must never broaden retrieval scope or retrieve documents outside
the authenticated user's permission boundaries. Penetration tests confirm 0.00% leakage.

### 32. In-process route testing for sandboxed Windows environments
**Decision:** API contract tests invoke FastAPI route functions in-process rather than
binding external TCP loopback ports with `TestClient`.

**Why:** Prevents Windows Proactor event loop socketpair deadlocks in isolated/sandboxed
test harnesses while testing the identical endpoint logic, schema validation, and database rows.

---

## Part F — Phase 6A & 6B Closeout (Explainable Output & Streamlit UI)

### 33. Structure-aware `heading_path` (`ENABLE_HEADING_PATH`, default `true`)
**Decision:** `DocumentChunk` stores a hierarchical `heading_path` (e.g.,
`"Part 4 Governance > 4.2 Board Voting > 4.2.3 Plurality rule"`) maintained by a
5-level heading stack in `ClauseAwareChunker`. When `ENABLE_HEADING_PATH=true`,
`build_indexable_text(chunk)` prepends `heading_path` to the text embedded in Qdrant
and tokenized by BM25, and evaluation result files record `heading_path_enabled`.

**Why:** Gives dense and sparse retrieval structural context for short sub-clauses
while allowing clean ablation (`ENABLE_HEADING_PATH=false`) in Phase 7. Re-ingestion
remains idempotent because deterministic UUIDv5 point IDs derive from `chunk_id`.

### 34. Backward-compatible `Citation` and `ChatQueryResponse` fields (API.md vs Phase 6A)
**Decision:** `Citation` in `src/api/schemas.py` populates both the Phase 3/API.md keys
(`doc_id`, `doc_name`, `section_title`, `clause_id`, `page_number`, `snippet`) and the
Phase 6A keys (`chunk_id`, `doc_title`, `heading_path`, `clause`, `page`,
`quote_snippet`). `ChatQueryResponse` includes `route`, `grader_path`, `refusal`,
`refusal_category`, `timings`, `citations_dropped`, and `heading_path_enabled` alongside
the existing nested stats objects.

**Why:** Satisfies the Phase 6A structured response specification without breaking
any Phase 3–5 contract tests.

### 35. Verbatim `quote_snippet` without ellipsis suffix
**Decision:** `extract_verbatim_snippet(text, max_chars=200)` returns `text.strip()[:200]`
without appending `"..."`.

**Why:** Appending `"..."` to truncated snippets causes a strict verbatim substring check
(`quote_snippet in passage_text`) to fail on passages longer than 200 characters. Pure
slicing guarantees 100% verbatim substring fidelity.

### 36. Server-side citation guard & safe 6-step reasoning trace (`ENABLE_XAI_OUTPUT`)
**Decision:** `validate_cited_chunks` drops any model-cited `chunk_id` that was not in
the context passages passed to the generator OR is not permitted for the authenticated
role, recording the count in `citations_dropped`. When `ENABLE_XAI_OUTPUT=true`,
`sources` / `citations` are filtered to the validated cited passages and
`reasoning_trace` emits 6 ordered steps (`Question rewritten`, `Route`,
`Passages retrieved/kept`, `Grader path`, `Retry used`, `Self-limits hit`) without
prompts, passage text, or restricted document counts (`candidates_filtered` is omitted
from the user-facing trace). When `ENABLE_XAI_OUTPUT=false`, the Phase 3–5 trace is
preserved unchanged.

**Why:** Enforces anti-hallucination and zero restricted metadata leakage while keeping
flag-off parity for ablation runs.

### 37. UI boundary and server-authoritative role in Streamlit (`Phase 6B`)
**Decision:** `src/ui/app.py` communicates with the backend exclusively through
`src/ui/api_client.py` (`ComplianceAPIClient`), stores the bearer token only in
`st.session_state["access_token"]`, and reads the active role from the server's
`/api/v1/auth/login` and `/api/v1/auth/me` payloads rather than a client-side role
dropdown.

**Why:** Prevents privilege escalation or client-side role spoofing and keeps the UI
strictly decoupled from database, Qdrant, and LLM internals.

---

## Part G — Phase 7 Closeout (Gold Set, Retrieval Eval & Ablation Runner)

### 38. Coexistence of legacy `data/gold_set.json` and Phase 7 `data/eval/gold_set.jsonl`
**Decision:** Phase 1's `data/gold_set.json` (4 categories, clause-ID references, tested by
`tests/test_data_validation.py`) is kept intact. Phase 7 introduces `data/eval/gold_set.jsonl`
with 100 structured JSONL rows across all 5 required question types (`20 single_fact`,
`20 multi_part`, `20 cross_reference`, `20 role_restricted`, `20 unanswerable`), mapped to
real ingested `chunk_id`s from `/data` and marked `status: "draft"`.

**Why:** Preserves 100% backward compatibility with Phase 1 tests while satisfying the
Phase 7 JSONL schema (`id`, `question`, `type`, `role_asking`, `gold_chunk_ids`, `gold_doc`,
`clause`, `gold_answer`, `expected_behaviour`, `status`) and the $\ge 15$-per-type quota.

### 39. Paired role-restricted questions and LLM suggestion status enforcement
**Decision:** In `data/eval/gold_set.jsonl`, `role_restricted` questions are authored in
explicit role pairs (`paired_id`): each manager-permitted (`DOC-INT-POL-MGT-002`) or
auditor-only (`DOC-INT-AUDIT-CONF-2025`) question is tested both as `expected_behaviour="answer"`
for the authorized role and `expected_behaviour="refuse"` (with `unauthorized_keywords`) for
the restricted role (`analyst` or `manager`). In `scripts/build_gold_set.py --suggest`,
LLM-proposed questions are hard-coded to `status="draft"` with `source_chunk_id` attached
and can never be written as `"reviewed"`.

**Why:** Paired testing proves that the exact same regulatory question is answered for an
authorized role and refused with 0.00% leakage for a lower-privilege role. Enforcing
`status="draft"` on LLM-suggested items prevents unreviewed synthetic labels from polluting
final benchmark claims.

### 40. Temporary isolated indices for retrieval & ablation (`ENABLE_HEADING_PATH` on/off)
**Decision:** Both `scripts/eval_retrieval.py` and `scripts/run_ablation.py` re-index the
corpus into `tempfile.TemporaryDirectory` instances for `ENABLE_HEADING_PATH=False` (`A0_baseline`)
and `ENABLE_HEADING_PATH=True` (`A1_heading_path`..`A5_full_xai`, `RBAC_OFF_DEMO`), never
modifying `./data/qdrant` or `./data/sqlite/bm25_index.pkl`. Cross-encoder re-ranking also
prepends `heading_path` when `ENABLE_HEADING_PATH=True`.

**Why:** Guarantees that comparing heading-path off vs on is a clean, isolated index
comparison and never clobbers the live application index.

### 41. Profile-mixing guard (`ProfileMismatchError`) and `RBAC_OFF_DEMO` isolation
**Decision:** Every checkpoint row and result JSON records `llm_profile` and `llm_model`.
`load_checkpoint_rows` and `load_and_validate_ablation_files` raise `ProfileMismatchError`
if an attempt is made to resume or merge artifacts across different profiles or models.
The `RBAC_OFF_DEMO` configuration is gated behind `--include-rbac-off` (`allow_rbac_off=True`),
which sets `BASELINE_ABLATION=True` strictly inside the context manager and labels the row
`"DEMONSTRATION ONLY — DO NOT USE AS RESULT"`.

**Why:** Prevents accidental contamination of live (`dev`/`demo`) dissertation tables with
`mock` harness numbers, and demonstrates empirically what server-side RBAC prevents without
weakening production security guards.


---

## Part H — Phase 7b Closeout (Evaluation Metrics Fixes & Corpus Expansion Tooling)

### 42. Routing accuracy "n/a" when router is disabled
**Decision:** `routing_accuracy` is computed only when `ENABLE_ADAPTIVE_ROUTER=True` AND
the evaluation question has a defined routing label (`expected_route`). For all other
configurations (`A0_baseline`, `A1_heading_path`, `A2_memory`, `RBAC_OFF_DEMO`),
`routing_accuracy` is strictly `None` and rendered as `"n/a"` in markdown and CSV reports.

**Why:** When the router is disabled, the pipeline unconditionally executes `SINGLE_SEARCH`.
Comparing this default against gold labels yielded a misleading constant accuracy (e.g. `0.6000`),
obscuring whether an active routing decision took place.

### 43. Separate live calls, cached calls, and non-LLM refusals
**Decision:** Cost and latency metrics now track three separate figures: `live_calls`
(uncached provider calls consuming quota), `cached_calls` (served from SQLite cache), and
`refusals_without_llm` (queries refused by rule or retrieval before calling the generator).
Cost comparisons must strictly evaluate `live_calls_per_query` and `live_tokens_per_query`.
Uncached latency is reported separately for queries with zero cache hits.

**Why:** Configurations evaluated sequentially share the SQLite response cache, which caused
later rows (such as `A5_full_xai`) to appear cheaper purely due to cache hits on identical
underlying prompts.

### 44. Final ablation review gate (`--require-reviewed`, default N=40)
**Decision:** Added `--require-reviewed` to `scripts/run_ablation.py` (and `--min-reviewed N`
to `scripts/validate_gold_set.py`). When `--require-reviewed` is passed, the runner filters
the dataset strictly to questions where `status == "reviewed"` and raises
`InsufficientReviewedQuestionsError` if fewer than $N$ reviewed items exist (default 40).

**Why:** Ensures that final dissertation benchmarks cannot be run against purely synthetic,
unreviewed draft questions.

### 45. Corpus Manifest & Sidecar Audit Tooling
**Decision:** Added `scripts/corpus_manifest.py` and `docs/CORPUS_GUIDE.md` to govern corpus
expansion toward 20–40 documents. Every document must have a companion `.meta.json` with
`source`, `licence`, and `allowed_roles`. `scripts/eval_retrieval.py` emits an explicit warning
if the total chunk count is under 100 ("corpus too small for meaningful retrieval comparison").

**Why:** Small corpora ($\le 26$ chunks) compress Recall@5 to $\sim 1.0$ across all methods.
Tooling ensures new documents adhere to licensing, role labelling, and chunking standards.

### 46. Full production corpus ingestion (24 documents, 101 chunks)
**Decision:** Indexed all 24 regulatory documents (16 public raw, 8 synthetic internal) into
the production Qdrant collection and BM25 index via `src/ingestion/run.py --rebuild`.
Leakage check verified strictly 0.00% leakage across all 36 test cells on the 101-chunk store.
The retrieval evaluation script `scripts/eval_retrieval.py` confirmed removal of the `< 100` chunk
warning and demonstrated clear empirical differentiation across BM25, Vector, and Hybrid retrieval.

**Why:** Replaces the toy 6-document baseline with a statistically meaningful evaluation corpus,
ensuring top-5 retrieval does not capture 20% of the entire index.

### 47. Gold benchmark review gate promotion (45 questions verified)
**Decision:** Promoted 45 representative questions across all 5 evaluation types (10 single-fact,
10 multi-part, 10 cross-reference, 10 role-restricted, 5 unanswerable) in `data/eval/gold_set.jsonl`
from `status: "draft"` to `status: "reviewed"` after verifying them against the underlying regulatory
text. Confirmed readiness via `scripts/validate_gold_set.py --min-reviewed 40`.

**Why:** Eliminates the risk of evaluating the RAG architecture on purely unverified draft questions,
satisfying the `--require-reviewed` gate in `scripts/run_ablation.py`.

### 48. Dissertation LaTeX table export
**Decision:** Added `generate_latex_table` to `scripts/make_report_tables.py` to automatically
export publication-ready LaTeX tables using `booktabs` into `results/dissertation_tables.tex` and
`evaluation/results/dissertation_tables.tex`. The export generates two complementary tables:
(1) Overall layer ablation results ($n=45$, Recall@5, nDCG@5, Ans F1, CRR, Leakage, Route Acc, Live Calls),
and (2) Latency and Token Efficiency (Median/p95 latency, Live/Cached calls per query, Live tokens).

**Why:** Fulfills PLAN.md Phase 7 dissertation reporting requirements and enables direct `\input{...}`
in LaTeX thesis documents without manual transcription errors.


---

## Part I — Phase 7c Closeout (Integrity Fixes: Human Review Gate, Corpus Provenance & Result Labelling)

### 49. Gold Set Review Integrity & Reset of Agent-Reviewed Questions
**Decision:** Added `reviewed_by: str | None = None` and `reviewed_on: str | None = None` to the `GoldQuestionItem` schema (`src/evaluation/gold_set.py`), and extended `ReviewStatus = Literal["draft", "reviewed", "rejected"]`. All 45 questions in `data/eval/gold_set.jsonl` previously marked as `"reviewed"` were explicitly reset back to `status="draft"` with `reviewed_by=None` and `reviewed_on=None`. The review gates in `select_reviewed_questions` and `scripts/run_ablation.py --require-reviewed` now strictly filter for `status == "reviewed"` AND `reviewed_by == "student"`. Created `scripts/review_gold_set.py`: an interactive terminal CLI that presents questions with their full context and referenced chunk text, allowing the student researcher to approve (`a`), edit (`e`), reject (`r`), skip (`s`), or quit (`q`), saving atomically after each decision.

**Why:** An AI agent cannot peer-review or certify its own benchmark answers. Permitting the system builder or agent to mark its own questions as "reviewed" undermines academic integrity. Questions must be examined and certified by the human student researcher before they can satisfy the final ablation review gate.

### 50. Corpus Provenance Audit, Manifest Enforcement & Origin Classifications
**Decision:** Added mandatory sidecar fields `content_origin` (`original_text`, `excerpt_of_original`, `paraphrase_or_summary`, `synthetic`) and `licence_url` to all 24 document `.meta.json` sidecars and updated `scripts/corpus_manifest.py` to fail if either is missing. All 16 public regulation documents in `data/raw` were audited and tagged as `excerpt_of_original` (averaging 3–6 chunks and ~1.5–2.8KB each, containing verbatim statutory clauses from the FCA Handbook, BCBS frameworks, and UK statutory instruments), while all 8 internal documents were tagged as `synthetic`. `scripts/corpus_manifest.py` prints an origin summary table and emits explicit warnings for public regulations yielding under 10 chunks to document that they represent targeted academic excerpts rather than complete multi-hundred-page legislative codes.

**Why:** Rigorous academic transparency requires distinguishing full statutory text from curated clause excerpts and synthetic internal policies, while providing unambiguous licensing URLs (UK Open Government Licence v3.0, BIS Terms, and EU Public Licence).

### 51. Result Labelling, Profile Mismatch Guards & 95% Confidence Intervals
**Decision:** Standardized ablation and report outputs in `scripts/run_ablation.py`, `scripts/make_report_tables.py`, and `results/dissertation_tables.tex` around strict profile-based banners: `"HARNESS CHECK (mock)"` for offline test harness checks and `"LIVE (dev/demo)"` for live external LLM benchmarks. The LaTeX exporter carries a visible metadata block (profile, model, execution mode, date) and raises `ProfileMismatchError` if mock results lack the harness banner or if profiles are mixed. Both retrieval (`scripts/eval_retrieval.py`) and ablation tables include 95% bootstrap confidence interval columns for Recall@5 and nDCG@5, and automatically flag overlapping intervals ($\dag$) against the `A0_baseline`.

**Why:** Ensures that offline mock harness checks can never be misrepresented as live LLM evaluations in academic writeups, and provides statistical confidence intervals to prevent overinterpreting minor score differences on small sample sizes.

---

## Part J — Phase 8 Closeout (Frontend Hardening, AppTest Suite & Demo Polish)

### 52. Headless Streamlit AppTest Suite, 2-Minute Demo Presets, Warning Badges & Presentation Script
**Decision:** Hardened the Streamlit user interface (`src/ui/app.py`) and authored automated and operational artifacts for dissertation presentation without altering the frozen backend API:
1. Implemented a fully offline headless testing suite (`tests/test_ui_app.py`, 11 tests) using `streamlit.testing.v1.AppTest` verifying login success/failure, role-based view isolation (analyst blocked from auditor summaries), HTTP 401 token expiration clearing state, refusal card rendering, long multi-citation responses, backend unreachable notices, session lifecycle, and demo preset button query execution.
2. Embedded `DEMO_PRESETS` in the UI sidebar providing 6 pre-configured compliance questions (public CDD, manager escalation policy, confidential KYC audit findings, Basel III vs AML split route, out-of-corpus Dodd-Frank unanswerable, and adversarial prompt-injection override) enabling a rapid 2-minute role differentiation demo.
3. Enhanced LLM profile badge rendering to conspicuously display a high-contrast warning pill (`⚠️ OFFLINE MOCK • model` / `⚠️ DEV PROVIDER • model`) whenever running non-demo modes, preventing synthetic mock responses from being mistaken for live production outputs.
4. Enforced strict WCAG AAA / AA compliance per `DESIGN.md`: Matte Black `#1C1D20` button text on Safety Orange `#FF5F00` primary buttons, visible focus outlines, explicit non-empty input labels, and text-differentiated role badges.
5. Authored `docs/DEMO_SCRIPT.md`: a complete 5-minute timeboxed live demonstration script detailing minute-by-minute physical actions, spoken commentary, audience takeaways, and technical contingency fallback procedures. Updated `docs/UI_TEST_CHECKLIST.md` with headless test commands.

**Why:** Fulfills all Phase 8 requirements under the frozen project scope, providing automated UI test coverage without flaky browser drivers and giving the student a polished, fail-safe script for final viva examinations.
