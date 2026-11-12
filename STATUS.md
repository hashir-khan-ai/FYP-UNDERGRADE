# Project Status & Execution Log

**Current Phase:** Phase 7 & 7b (Corpus Expansion, Review Gate & Dissertation Benchmarks) Complete  
**Verification:** 171/171 tests passing | Leakage rate: strictly 0.00% (36/36 matrix cells) | Corpus: 24 docs, 101 chunks

## Phase Summary
- **Phase 1 (Foundations & Data):** Config profiles, SQLite schema/migrations, synthetic docs, seed scripts (18 tests).
- **Phase 2 (Baseline Hybrid RAG):** BM25Plus + Qdrant BGE-small, RRF, MiniLM re-ranker, mock gateway (15 tests).
- **Phase 3 (RBAC & Memory):** Server-side payload filtering, HMAC auth, SQLite sessions, audit logging (74 tests, 0.00% leak).
- **Phase 4 (Adaptive Router):** Intent classification, direct replies, split routes, single-search fallback (19 tests, 0.00% leak).
- **Phase 5 (Corrective Grader):** Relevance grading, shortcuts, query rewrite retry, uniform refusal (16 tests, 0.00% leak).
- **Phase 6 (XAI & Streamlit):** Structure-aware `heading_path`, citations, trace, UI client, Streamlit app (16 tests, 0.00% leak).
- **Phase 7 & 7b (Evaluation & Benchmarks):** 24-doc corpus (101 chunks), 45 hand-reviewed gold questions, `scripts/eval_retrieval.py` (no warnings), `run_ablation.py --require-reviewed`, `make_report_tables.py` exporting LaTeX (`results/dissertation_tables.tex`), Markdown and CSV (13 tests, 0.00% leak).

## PowerShell Commands (with .venv)
```powershell
$env:HF_HUB_OFFLINE="1"

# Tests, Leakage & Corpus Manifest Audit
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/leakage_check.py
.\.venv\Scripts\python.exe scripts/corpus_manifest.py

# Gold Set Validation, Retrieval Eval & Ablation
.\.venv\Scripts\python.exe scripts/validate_gold_set.py --min-reviewed 40
.\.venv\Scripts\python.exe scripts/eval_retrieval.py
.\.venv\Scripts\python.exe scripts/run_ablation.py --profile mock --include-rbac-off --require-reviewed
.\.venv\Scripts\python.exe scripts/make_report_tables.py
```

## Required .env Variables (Names Only)
- Core: `APP_ENV`, `API_HOST`, `API_PORT`, `CORS_ORIGINS`, `SECRET_KEY`, `SEED_DEFAULT_PASSWORD`
- Profiles: `LLM_PROFILE`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `DEMO_LLM_BASE_URL`, `DEMO_LLM_API_KEY`, `DEMO_LLM_MODEL`
- Storage: `DATABASE_PATH`, `QDRANT_STORAGE_PATH`, `BM25_INDEX_PATH`
- Flags: `ENABLE_RBAC`, `ENABLE_MEMORY`, `ENABLE_ADAPTIVE_ROUTER`, `ENABLE_CORRECTIVE_GRADER`, `ENABLE_XAI_OUTPUT`, `ENABLE_HEADING_PATH`

## File Map
- Ingestion & Corpus: `src/ingestion/`, `data/raw/`, `data/synthetic/`, `scripts/corpus_manifest.py`, `docs/CORPUS_GUIDE.md`
- Core RAG & Logic: `src/rag/baseline.py`, `src/core/router.py`, `src/core/grader.py`, `src/core/memory.py`, `src/core/xai.py`, `src/core/llm_client.py`
- Evaluation: `src/evaluation/`, `scripts/eval_retrieval.py`, `scripts/run_ablation.py`, `scripts/make_report_tables.py`
- Auth, API & UI: `src/core/auth.py`, `src/api/`, `src/ui/`

## Known Gaps & Unverified Items
- `.env` has an empty `LLM_API_KEY`, so `dev` and `demo` live LLM profiles have NOT been verified against an external live provider.
- All evaluation tables are generated under `mock` profile (deterministic offline responses, 0 quota spent).

## Next Single Step
- Populate `LLM_API_KEY` in `.env` to execute live benchmark verification (`scripts/smoke_demo.py --profile dev` and `scripts/run_ablation.py --profile dev --require-reviewed`).
