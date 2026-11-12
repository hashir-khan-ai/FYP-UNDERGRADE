# Project Status & Execution Log

**Current Phase:** Phase 7 (Gold Set, Retrieval Evaluation & Ablation Runner) Complete  
**Verification:** 168/168 tests passing | Leakage rate: strictly 0.00% (36/36 matrix cells across single, split, grader-retry & XAI surfaces)

## Phase Summary
- **Phase 1 (Foundations & Data):** Config profiles, SQLite schema/migrations, synthetic docs, seed scripts (18 tests).
- **Phase 2 (Baseline Hybrid RAG):** BM25Plus + Qdrant BGE-small, RRF, MiniLM re-ranker, mock gateway (15 tests).
- **Phase 3 (RBAC & Memory):** Server-side payload filtering, HMAC auth, SQLite sessions, audit logging (74 tests, 0.00% leak).
- **Phase 4 (Adaptive Router):** Intent classification, direct replies, split routes, single-search fallback (19 tests, 0.00% leak).
- **Phase 5 (Corrective Grader):** Relevance grading, shortcuts, query rewrite retry, uniform refusal (16 tests, 0.00% leak).
- **Phase 6A (Explainable Output):** Structure-aware `heading_path` (`ENABLE_HEADING_PATH`), citation validator, verbatim `quote_snippet` ($\le 200$ chars), safe 6-step reasoning trace, `scripts/eval_citations.py` (10 tests, 0.00% leak).
- **Phase 6B (Streamlit UI):** `DESIGN.md` (60/30/10 palette), `.streamlit/config.toml`, `src/ui/api_client.py`, `src/ui/app.py`, `docs/UI_TEST_CHECKLIST.md` (6 tests).
- **Phase 7 (Evaluation & Ablation):** 100-question `data/eval/gold_set.jsonl` (20 per type), `scripts/build_gold_set.py`, `scripts/validate_gold_set.py`, `scripts/eval_retrieval.py`, `scripts/run_ablation.py` (`A0`..`A5` + `RBAC_OFF_DEMO`), `scripts/make_report_tables.py` (10 tests, 0.00% leak on `A0`..`A5`).

## PowerShell Commands (with .venv)
```powershell
$env:HF_HUB_OFFLINE="1"

# Start Backend API & Streamlit UI
.\.venv\Scripts\python.exe -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
.\.venv\Scripts\python.exe -m streamlit run src/ui/app.py --server.port 8501

# Tests & Security Leakage Check
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/leakage_check.py

# Gold Set, Retrieval Eval & Ablation (mock profile)
.\.venv\Scripts\python.exe scripts/build_gold_set.py
.\.venv\Scripts\python.exe scripts/validate_gold_set.py
.\.venv\Scripts\python.exe scripts/eval_retrieval.py
.\.venv\Scripts\python.exe scripts/run_ablation.py --profile mock --include-rbac-off
.\.venv\Scripts\python.exe scripts/make_report_tables.py
```

## Required .env Variables (Names Only)
- Core: `APP_ENV`, `API_HOST`, `API_PORT`, `CORS_ORIGINS`, `SECRET_KEY`, `SEED_DEFAULT_PASSWORD`
- Profiles: `LLM_PROFILE`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `DEMO_LLM_BASE_URL`, `DEMO_LLM_API_KEY`, `DEMO_LLM_MODEL`
- Storage: `DATABASE_PATH`, `QDRANT_STORAGE_PATH`, `BM25_INDEX_PATH`
- Flags: `ENABLE_RBAC`, `ENABLE_MEMORY`, `ENABLE_ADAPTIVE_ROUTER`, `ENABLE_CORRECTIVE_GRADER`, `ENABLE_XAI_OUTPUT`, `ENABLE_HEADING_PATH`

## File Map
- Ingestion & Retrieval: `src/ingestion/loaders.py`, `src/ingestion/chunker.py`, `src/ingestion/indexer.py`, `src/rag/baseline.py`
- Core Logic & XAI: `src/core/router.py`, `src/core/grader.py`, `src/core/memory.py`, `src/core/xai.py`, `src/core/llm_client.py`
- Evaluation: `src/evaluation/metrics.py`, `src/evaluation/gold_set.py`, `src/evaluation/ablation.py`, `scripts/eval_retrieval.py`, `scripts/run_ablation.py`, `scripts/make_report_tables.py`
- Auth, API & UI: `src/core/auth.py`, `src/api/main.py`, `src/api/routes.py`, `src/api/schemas.py`, `src/ui/api_client.py`, `src/ui/app.py`

## Known Gaps & Unverified Items
- `.env` has an empty `LLM_API_KEY`, so `dev` and `demo` live LLM profiles have NOT been verified against a live provider.
- All 100 rows in `data/eval/gold_set.jsonl` (plus `grader_labels.jsonl`, `unanswerable.jsonl`, and `routing_labels.jsonl`) are marked `status: "draft"`; reported ablation numbers are deterministic `mock`-profile harness checks (`HARNESS CHECK ONLY`).

## Next Single Step
- Student manual review of `data/eval/gold_set.jsonl` (`status: "draft"` -> `"reviewed"`), setting `LLM_API_KEY` in `.env`, and running live `--profile dev` / `--profile demo` ablation benchmarks.
