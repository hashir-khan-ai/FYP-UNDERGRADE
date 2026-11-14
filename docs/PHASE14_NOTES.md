# Phase 14 Engineering Notes: Mutation Re-Run & Guard Hardening

**Project:** Enterprise RAG Assistant for Banking Regulatory Compliance  
**Module:** COM6301 (BSc Final Year Project)  
**Date:** November 2026  
**Status:** Verification Complete & Guard Invariant Hardened  

---

## 1. Guard Design Redesign: Eliminating Reachable Switches in Production

### 1.1 Previous Vulnerability Analysis
Previously, `src/core/mutants.py` contained:
```python
def is_running_under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules

def is_mutant_active(flag_name: str) -> bool:
    if not is_running_under_pytest():
        return False
    return os.environ.get(flag_name) == "1"
```
And application files across `src/` (`src/core/canary.py`, `src/rag/baseline.py`, `src/ingestion/indexer.py`, `src/core/llm_client.py`, `src/core/memory.py`, `src/api/routes.py`) branched on `if is_mutant_active(...)`.

**Security Flaw:** If an adversary set `PYTEST_CURRENT_TEST=1` or imported `pytest` in an external script or container environment, the check returned `True`, and environment variables like `MUTANT_ROLE_FROM_BODY=1` or `MUTANT_DISABLE_CANARY_GUARD=1` weakened application defenses.

### 1.2 Redesigned Architecture (Zero Reachable Switches)
1. **Zero Switches in `src/`:** All mutant branches were completely removed from `src/`. No production function reads an environment flag to disable security.
2. **Monkeypatching Only:** Positive controls (mutation tests) in `tests/mutants/` apply mutations strictly via `pytest.MonkeyPatch` on specific target functions in test fixtures.
3. **Inert Compatibility Helper:** `is_mutant_active(flag)` unconditionally returns `False`.
4. **Startup Check Invariant:** `check_no_mutant_flags_on_startup()` unconditionally scans `os.environ` for any legacy `MUTANT_*` variable. If present, it raises `RuntimeError` and refuses startup immediately, **regardless of whether `PYTEST_CURRENT_TEST` is spoofed or `pytest` is imported**.
5. **Subprocess Anti-Spoofing Verification:**
   - `tests/test_mutant_guards.py::test_subprocess_spoofing_pytest_marker_still_refused_at_startup` (PASSED): Confirms startup crashes if legacy mutant flags exist, even with spoofed pytest marker.
   - `tests/test_mutant_guards.py::test_subprocess_spoofing_cannot_bypass_canary_guard` (PASSED): Confirms that even if startup validation is skipped, `enforce_canary_guard` ignores `MUTANT_DISABLE_CANARY_GUARD=1` and intercepts canaries.
   - `tests/test_mutant_guards.py::test_subprocess_spoofing_cannot_bypass_role_resolution` (PASSED): Confirms that `_resolve_effective_role` ignores `MUTANT_ROLE_FROM_BODY=1` and rejects body role forgery.

---

## 2. Mutation Re-Run Matrix (7 Positive Controls)

* **Baseline Execution (No Mutants):** Confirmed **0 failures** across all 7 security checks.
* **Mutant Execution:** Applied via monkeypatching in `tests/mutants/test_mutations.py` and `scripts/run_mutant_matrix.py`.

### Positive Control Kill Results

| Mutant ID | Mutant Name | Valid Kill | Killing Test Name | Failure Type | Specific Assertion Message |
| :-: | :--- | :-: | :--- | :-: | :--- |
| **(a)** | output_canary_guard_off | **YES** | `test_canary_output_guard_blocks_canaries` | `AssertionError` | Output canary guard failed to intercept leaked canary token! |
| **(b)** | post_rerank_rbac_filter_off | **YES** | `test_post_rerank_rbac_defense_in_depth` | `AssertionError` | Post-rerank defense-in-depth permitted 1 restricted chunks! |
| **(c)** | pre_fusion_rbac_filter_off | **YES** | `test_zero_leakage_pre_fusion_vector_and_bm25` | `AssertionError` | Pre-fusion retrieval leaked 1 restricted chunks to analyst! |
| **(d)** | cache_key_without_role | **YES** | `test_cache_keys_strictly_partitioned_by_role` | `AssertionError` | Cache key collision: distinct roles produced identical cache keys! |
| **(e)** | memory_shared_across_roles | **YES** | `test_session_memory_isolation_across_users` | `AssertionError` | Memory isolation failure: user read 2 turns from other user! |
| **(f)** | distinct_restricted_refusal | **YES** | `test_uniform_refusal_indistinguishable_from_empty` | `AssertionError` | Uniform refusal broken: returned 'ACCESS RESTRICTED' differing from standard refusal |
| **(g)** | role_from_request_body | **YES** | `test_role_from_request_body_ignored` | `AssertionError` | Role forgery detected: escalated from 'analyst' to 'auditor'! |

* **Total Mutants Tested:** 7
* **Valid Kills (`AssertionError`):** 7 / 7 (100.0%)
* **Invalid Kills (Crashes/Exceptions):** 0
* **Surviving Mutants:** 0

### 2.1 Mutant Overlap & Multi-Test Coverage (Phase 14b)
Per Phase 14b requirements, each of the 7 mutants is verified by at least TWO independent killing tests:
1. **Mutant (a) [Canary Output Guard Off]:**
   - Kill 1: `test_mutant_a_canary_guard_disabled` (`enforce_canary_guard` unit test)
   - Kill 2: `test_mutant_a_independent_canary_pipeline_kill` (`BaselineRAGPipeline.generate` canary exfiltration)
2. **Mutant (b) [Post-Rerank RBAC Guard Off]:**
   - Kill 1: `test_mutant_b_post_rerank_rbac_disabled` (`pipeline.rerank` unit test)
   - Kill 2: `test_mutant_b_independent_pipeline_ask_kill` (`pipeline.rerank` drop assertion)
3. **Mutant (c) [Pre-Fusion RBAC Filter Off]:**
   - Kill 1: `test_mutant_c_pre_fusion_rbac_disabled` (`BM25Indexer.search` visibility test)
   - Kill 2: `test_mutant_c_independent_qdrant_filter_kill` (`get_role_filter` non-null assertion)
4. **Mutant (d) [Cache Key Without Role]:**
   - Kill 1: `test_mutant_d_cache_key_without_role` (direct cache key comparison)
   - Kill 2: `test_mutant_d_independent_cache_read_pollution_kill` (cross-role cache pollution detection)
5. **Mutant (e) [Shared Memory Across Roles]:**
   - Kill 1: `test_mutant_e_shared_memory_across_roles` (`load_recent_turns` unit test)
   - Kill 2: `test_mutant_e_independent_history_injection_kill` (dialogue context IDOR assertion)
6. **Mutant (f) [Distinct Restricted Refusal]:**
   - Kill 1: `test_mutant_f_distinct_refusal_message` (uniform refusal divergence test)
   - Kill 2: `test_mutant_f_independent_side_channel_probe_kill` (side-channel probe assertion)
7. **Mutant (g) [Role From Request Body]:**
   - Kill 1: `test_mutant_g_role_taken_from_request_body` (`_resolve_effective_role` unit test)
   - Kill 2: `test_mutant_g_independent_chat_payload_forgery_kill` (body payload privilege escalation check)

Total independent killing tests: **14** (2 per mutant). Every mutant is caught by at least two independent assertions.

---

## 2.2 Cache Versioning & Ingestion Consistency (Phase 14b)

### 1. Cache Versioning & Invalidation
- **Module:** `src/core/acl_version.py` (`compute_index_acl_version()`).
- **Cache Key Invariant:** `_compute_cache_key` incorporates `acl_version = compute_index_acl_version()`.
- **Invalidation Guarantee:** Any re-index or document permission change alters the manifest hash, rendering all previously cached responses unreachable.
- **TTL & Startup Purge:** Configured via `settings.LLM_CACHE_TTL_HOURS = 24`. Startup routine `purge_expired_cache()` in `src/api/main.py:lifespan` automatically cleans rows older than 24h.
- **Tests Verified:**
  - `test_revoke_role_on_document_invalidates_cached_answer` (PASSED)
  - `test_cache_entries_expire_after_ttl_and_purged` (PASSED)
  - `test_cache_never_returns_answer_across_roles` (PASSED)

### 2. Ingestion Consistency & Atomic Swap
- **Module:** `src/ingestion/upload_ingest.py` (`ingest_uploaded_document()`, `verify_dual_index_consistency()`).
- **Staging Pipeline:** Uploads build a temporary staging BM25 index (`*.staging.tmp`).
- **Dual-Index Consistency Check:** `verify_dual_index_consistency()` verifies exact parity of chunk IDs and `allowed_roles` between Qdrant and staged BM25.
- **Atomic Swap:** Live BM25 file replaced via `os.replace()` only after successful verification.
- **Rollback Guarantee:** Any exception mid-upload unlinks staging files and preserves previous live indexes untouched.
- **Deny-by-Default:** Chunks with empty or missing `allowed_roles` evaluate strictly to `False` across all project roles.
- **Tests Verified:**
  - `test_empty_or_missing_roles_means_deny_by_default` (PASSED)
  - `test_dual_index_consistency_verification_catches_divergence` (PASSED)
  - `test_simulated_ingestion_failure_rolls_back_and_leaves_index_intact` (PASSED)

---

## 3. Labeling Model Evidence & Real Instruction-Following LLM Status

### 3.1 Relabeling Red-Team Results
* The previously reported 45/45 red-team test pass rate was executed against `sshleifer/tiny-gpt2` / `mock` generator stub.
* **Official Evaluation Label:** **"Smoke test only, cannot follow instructions - not security evidence."**
* The tiny-gpt2 model produces ungrounded synthetic text sequences and does not possess instruction-following or jailbreak capabilities. While it empirically verifies pipeline mechanics and deterministic canary guards, it does **not** constitute empirical resistance against instruction-following jailbreaks.

### 3.2 Real Instruction-Following Run Audit
* **Environment Check:**
  - `ollama`: Not installed / not running on host daemon (`Get-Command ollama` returned not found).
  - Free API Key (`LLM_API_KEY` for `dev` profile): None configured in local `.env` (`DEV_KEY_EXISTS: False`).
  - Paid API Key (`DEMO_LLM_API_KEY`): Present, but engineering contract prohibits spending paid quota during automated verification runs.
* **Status:** Step stopped per instruction without inventing mock results.
* **Ready-to-Run Instruction-Following Commands:**
  To execute the 45-case red-team suite against a local instruction-following model once Ollama is installed:
  ```powershell
  # 1. Install and start Ollama with Llama-3 or Mistral
  ollama pull llama3:8b
  ollama serve

  # 2. Run red-team suite with local instruction-following LLM (temp 0.0)
  python scripts/eval_redteam.py --profile local --model llama3:8b --temperature 0.0
  ```
  Or using a free provider (Groq / OpenRouter / Gemini free tier):
  ```powershell
  $env:LLM_PROFILE="dev"
  $env:LLM_API_KEY="<your-free-tier-key>"
  $env:LLM_MODEL="llama-3.1-8b-instant"
  python scripts/eval_redteam.py --profile dev --temperature 0.0
  ```

---

## 4. Spot Check Summary for `docs/QUEUE-BACKPRESSURE.md`

All 10 audited vectors in `docs/QUEUE-BACKPRESSURE.md` have been updated with explicit verdicts and verified implementation locations:
1. **2.1 Embedded Qdrant File Lock:** **Protected** (`src/ingestion/indexer.py:check_storage_lock()`, `src/ingestion/indexer.py:QdrantIndexer._get_client()`).
2. **2.2 Event Loop Non-Blocking:** **Protected** (`src/api/routes.py:chat_query()`, `src/api/routes.py:upload_document()`, `src/api/main.py:health_check()`).
3. **2.3 SQLite Write Contention:** **Partially protected** (`src/db/connection.py:get_db_connection()`, `src/db/repository.py:Repository.add_audit_log()`).
4. **2.4 LLM Call Budget & Spend Guard:** **Partially protected** (`src/core/spend_guard.py:SpendGuard.check_and_charge()`, `src/core/rate_limiter.py:RateLimiter.acquire()`, `src/core/llm_client.py:ResilientLLMClient._execute_with_retry()`).
5. **2.5 Admission Control & Input Validation:** **Protected** (`src/api/deps.py:enforce_query_rate_limit()`, `src/api/deps.py:enforce_upload_rate_limit()`, `src/ingestion/upload_ingest.py:validate_upload_request()`, `src/core/auth.py:login_user()`, `src/api/routes.py:_execute_chat_turn()`).
6. **2.6 Ingestion Dual-Index Transactionality:** **Unprotected** (None - Documented Prototype Limitation).
7. **2.7 Streaming Disconnect Cancellation:** **Unprotected** (None - Documented Prototype Limitation).
8. **2.8 Cache & Memory Retention Bounds:** **Partially protected** (`src/core/spend_guard.py:SpendGuard._runs`, `src/core/rate_limiter.py:RateLimiter._buckets`, `src/core/memory.py:load_recent_turns()`).
9. **2.9 Operational Telemetry Gaps:** **Partially protected** (`src/api/main.py:_health_payload()`, `src/api/main.py:health_check()`, `src/api/routes.py:admin_metrics()`, `src/core/telemetry.py:TelemetryCollector.get_summary()`).
10. **2.10 Frontend Backpressure:** **Protected** (`web/components/chat/composer.tsx:Composer()`, `web/components/chat/composer.tsx:handleKeyDown()`, `web/components/chat/chat-view.tsx:handleSubmit()`, `web/lib/api-client.ts:fetchApi()`).

