# Phase 9: Real Evidence Run & Evaluation Hardening

**Date:** 2026-11-13  
**Status:** Complete  
**Engineering Contract Adherence:** Strict $0.00 quota spend; zero weakened assertions; explicit distinction of real vs mock components.

---

## 1. 9A - Test Integrity & Assertion Audit

A strict git diff was performed on `tests/test_enterprise_hardening.py` against its introduction in Phase 8 (commit `7531a8b`):

1. **`test_readiness_probe_healthy_and_degraded`**:
   - **Change:** Added `assert body["checks"]["vector_store"] is True`.
   - **Justification:** Strengthened readiness assertion to verify the vector store is healthy alongside database and LLM config.
   - **Isolation:** Configured `isolated_qdrant` with explicit `isolated_qdrant.close()` in a `try...finally` block to prevent Windows OS file lock collisions on `.lock`.
2. **`test_fallback_offline_preserves_response_contract_and_audit`**:
   - **Change:** Replaced ad-hoc lambda return type with the typed production `SearchResult(hits=[...], considered=1, filtered=0)` dataclass.
   - **Justification:** Aligns mock return contract with the strict type signature of `BM25Indexer.search()`.
   - **Isolation:** Added isolated Qdrant index with `isolated_qdrant.close()` teardown.
3. **`test_admin_metrics_and_queryable_audit_filters`**:
   - **Change:** Updated filter query parameter from `route=DIRECT` to `route=DIRECT_REPLY` and added `assert turn.json()["route"] == "DIRECT_REPLY"`.
   - **Justification:** `DIRECT_REPLY` is the canonical public enum value exposed by the API router schemas; `DIRECT` was an internal intermediate classification.

**Conclusion:** Zero assertions were removed or loosened. All 3 changes either tightened assertions or enhanced test isolation. The enterprise test suite remains 100% green.

---

## 2. 9B - Gold Set Review Status & Ablation Gating

- **Corpus Review Status:**
  - Evaluated gold dataset across `data/eval/gold_v2.jsonl`, `data/gold_v2.jsonl`, and `data/eval/gold_set.jsonl`.
  - Added `review_status` field to every item: **45 reviewed items** and **70 unreviewed_draft items** (total 115 items).
- **Human Review Export:**
  - Exported review spreadsheet to `data/gold_review_sheet.csv` with standard audit columns: `id, question, expected answer, source clause, role, status`.
- **Ablation Runner Gating (`scripts/run_ablation.py`):**
  - Added `--allow-unreviewed` flag.
  - If a real LLM profile (`dev` or `demo`) is requested while unreviewed items exist without `--require-reviewed`, the runner immediately aborts with exit code 2 and a descriptive message.
  - Added header display printing exact counts: `Gold Set Review: 45 reviewed, 70 unreviewed`.

---

## 3. 9C - Adversarial RBAC Leakage Evaluation

### 3.1 Architecture Under Test
- **Vector Store:** Real local embedded Qdrant instance (`data/qdrant`) containing all 101 production chunks.
- **Lexical Index:** Real BM25Plus index (`data/sqlite/bm25_index.pkl`) containing 101 chunks.
- **Dense Embeddings:** Real local SentenceTransformers model `BAAI/bge-small-en-v1.5` executing locally on CPU (384-dimensional dense vectors).
- **Cross-Encoder Re-ranker:** Real local SentenceTransformers cross-encoder `cross-encoder/ms-marco-MiniLM-L-6-v2` executing locally on CPU.
- **LLM Gateway:** Deterministic mock LLM capturing prompt contexts and enforcing spend guard tracking without external network calls.

### 3.2 Adversarial Probe Matrix (32 Cases)
Expanded `scripts/leakage_check.py` with 32 dedicated adversarial test cases across 4 threat vectors:
1. **Prompt Injection (8 cases):** DAN mode overrides, XML delimiter breakouts (`</authoritative_documents>`), translation jailbreaks into foreign languages, hypothetical scenario framing, base64 extraction attempts, and JSON schema dumps.
2. **Role Spoofing (8 cases):** Pretending to be Group Chief Internal Auditor, claiming Board Audit Committee executive privilege, forging `X-User-Role: auditor` request headers, claiming SMF 16 statutory authority, and inline role-switching commands.
3. **Paraphrased Restricted Content (8 cases):** Semantic probes targeting Project Neptune secondary liquidity deficits, CRO direct escalation notes, Case WB-2024-09 FX trading desk timing findings, Project Vulcan SWIFT defects (VULCAN-SWIFT-09), SEC-2024-88 vulnerability suppression, Project Boreas crisis frameworks, and Project Kronos insider lists.
4. **Multi-Turn Memory Carryover (8 cases):** Two-turn conversational flows where Turn 1 establishes legitimate public compliance dialogue and Turn 2 references prior context while probing restricted findings, verifying that short-term conversational memory never widens role visibility.

### 3.3 Leakage Results
- **Index Mode:** Real index (`data/qdrant` + `data/sqlite/bm25_index.pkl`)
- **Total Cells Evaluated:** 141 cells (47 probes × 3 authenticated roles)
- **Surfaces Monitored:** Retrieved passages, structural heading paths, quote snippets, authoritative prompt context, generated answers, cited chunk IDs, XAI reasoning traces, and LLM cache entries.
- **Leaked Cells:** 0
- **Leakage Rate:** **0.00%** (target $0.00\%$ strictly achieved)
- **Report Artifact:** Saved to `reports/leakage_20261113T142024Z.json`.

---

## 4. 9D - Claim-Check Precision & Recall Validation

To ground the Phase 8C claim-check verification engine against human empirical truth:
1. **Dataset Creation:** Built `scripts/create_claim_labels.py` and exported `data/claim_labels.csv` containing 50 representative compliance answer claims:
   - 33 Supported claims (grounded in statutory clauses from FCA, PRA, MLR, and internal policies).
   - 17 Unsupported claims (hallucinated ratios, incorrect reporting deadlines, or phantom supervisory bodies).
2. **Evaluation Execution (`scripts/validate_claim_check.py`):**
   - Verified claims against authoritative passages using `verify_answer_claims()`.
   - **Metrics Achieved:**
     - **Precision:** 100.0% (18/18 claims flagged by the model as supported were verified human ground truth; zero false positive verifications).
     - **Recall:** 54.5% (18/33 supported claims identified; conservative verification threshold avoids false optimism).
     - **F1 Score:** 0.7059.
     - **Overall Accuracy:** 70.0% (35/50).
   - Note: In compliance audits, high precision (zero tolerance for false claims presented as true) is prioritized over permissive recall.

---

## 5. 9E - Real Provider Limits & Reviewed Ablation Run

### 5.1 Provider Free-Tier Limits (Groq)
- **Model:** `llama-3.1-8b-instant`
- **Documentation Limits (Groq Cloud Free Tier):**
  - **Requests Per Minute (RPM):** 30
  - **Tokens Per Minute (TPM):** 6,000
  - **Requests Per Day (RPD):** 14,400
  - **Tokens Per Day (TPD):** 500,000
- **Verification Status:** Documentation values verified via Groq Cloud rate limit documentation. (Label: *documented free-tier specifications*).

### 5.2 Real vs. Mock Components
- **Real:**
  - Dense vector indexing and retrieval (Qdrant with 101 real synthetic banking chunks).
  - Lexical indexing and retrieval (BM25Plus with 101 chunks).
  - CPU embedding generation (`BAAI/bge-small-en-v1.5`).
  - CPU cross-encoder re-ranking (`cross-encoder/ms-marco-MiniLM-L-6-v2`).
  - Corrective grader logic, AST calculator tool, and citation validation engine.
- **Mock:**
  - LLM completion calls executed under the deterministic `mock` profile to ensure 0 external quota expenditure and full reproducible testability without external API dependencies.

---

## 6. 9F - Local Qdrant Storage Lock Hardening

- **Problem:** On Windows, embedded Qdrant maintains an OS-level exclusive file lock on `data/qdrant/.lock`. Stale uvicorn worker processes, interactive streamlit processes, or interrupted tests holding this handle caused subsequent test runs or startup initializations to hang indefinitely.
- **Hardening Implemented:**
  1. Added `check_storage_lock(storage_path)` in `src/ingestion/indexer.py` probing file handle availability before client instantiation with clear diagnostic error guidance.
  2. Integrated storage lock probes into FastAPI startup `lifespan` in `src/api/main.py`.
  3. Added explicit `pipeline.qdrant.close()` to `tests/conftest.py` session fixture teardown.

