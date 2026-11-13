# Project Status & Execution Log

**Current Phase:** Phase 8A–8D Complete (Integrity Fixes, Citation Card Redesign, Stretch Tools, UI Polish & Visual Verification)  
**Verification:** 248 tests passing (`pytest -v`) | Leakage rate: strictly 0.00% (45/45 cells via `scripts/leakage_check.py`) | Corpus: 24 docs, 101 chunks | Gold v2: 115 items (`data/gold_v2.jsonl`) | Knowledge Graph: 38 nodes, 35 edges

## Phase Summary
- **Phase 1-6:** Ingestion, Hybrid RAG, RBAC/Memory, Adaptive Router, Corrective Grader, XAI & Base UI (158 tests, 0.00% leak).
- **Phase 7, 7b & 7c (Eval & Integrity):** 24-doc corpus (101 chunks), sidecar audit, student review CLI gate (`review_gold_set.py`), bootstrap 95% CIs on LaTeX tables, harness check banners (16 tests, 0.00% leak).
- **Phase 8 (Frontend Polish & Demo):** Headless AppTest suite (`tests/test_ui_app.py`), 6 demo presets, non-demo warning badges, accessible contrast, DEMO_SCRIPT.md.
- **Conversational UX, Dynamic Ingestion & Smart Intent Routing:** Collapsed citations expander UI, conversational grounded "Explain & Discuss" mode (`response_mode="explain"`), smart intent selector (`auto`, `rag`, `general`), deterministic injection neutralization, safe config disclosure, suggested follow-up chips, on-the-fly role-gated document upload subsystem (`src/ingestion/upload_ingest.py`, `POST /api/v1/documents/upload`), local $0 Ollama OpenAI-compatible dev profile runbook (`docs/RUNBOOK.md`), SQLite Knowledge Graph (`src/retrieval/knowledge_graph.py`, 38 nodes, 35 cross-reference edges) with strict server-side RBAC.
- **Phase 8A–8D Hardening, Citation Redesign, Stretch Tools & Visual Polish:**
  - **8A Integrity (`5c5d0b3`, `bb0d11a`, `500c14c`, `4118ced`):** Stripped chunk HTML/markdown heading markers at ingestion and escaped at render; bypassed SpendGuard cap in `mock`/local profiles with per-query + session live budgets and `"estimated tokens"` labelling; exposed exact runtime layer flags including `xai_output` trace gating; read login leakage metric dynamically from `reports/leakage_*.json` and gated persona quick-fill on `DEMO_MODE=true`.
  - **8B Citations (`5c81add`):** Human-friendly card ordering (title, single breadcrumb, `Public · verifiable` or lock `Internal · visible to <Roles>`, highlighted escaped quote, collapsed `Technical details` with copy), plus clickable/hoverable `[1]`/`[2]` jump & pulse markers.
  - **8C Stretch Tools & Gold v2 (`7531a8b`):** Added config-gated `claim_check` (`src/core/claim_check.py`) and AST-whitelisted `calculator` (`src/core/calculator.py`), both enforcing strict server-side RBAC, SQLite `audit_log` persistence, XAI UI rendering, `data/gold_v2.jsonl` (`100` unchanged + `15` numeric/multi-claim), and `A6_claim_check` / `A7_calculator` ablation profiles (`"MOCK, not evidence"`).
  - **8D UI Polish & Headless Audit:** Enforced `DESIGN.md` 60/30/10 palette (`#1C1D20`, `#26292E`/`#5A6068`, `#FF5F00`, `#F1F3F4`), inline SVG icons replacing all emojis, pure inline-SVG architecture flow diagram, live 5-stage animated pipeline stepper, CSS 3D citation card hover tilt & sidebar layer stack, `@media (prefers-reduced-motion: reduce)` fallbacks, and headless Chrome DevTools verification (`0` console errors, 4 screenshots in `docs/screenshots/phase8/`). Recorded in `docs/PHASE8_NOTES.md`.

## PowerShell Commands (with .venv)
```powershell
$env:HF_HUB_OFFLINE="1"

# Tests, Leakage & AppTest Suite
.\.venv\Scripts\python.exe -m pytest -q -m "not slow" -x
.\.venv\Scripts\python.exe -m pytest tests/test_ui_app.py -v
.\.venv\Scripts\python.exe scripts/leakage_check.py

# Ingestion, Manifest & Evaluation
.\.venv\Scripts\python.exe scripts/corpus_manifest.py
.\.venv\Scripts\python.exe scripts/review_gold_set.py
.\.venv\Scripts\python.exe scripts/eval_retrieval.py
.\.venv\Scripts\python.exe scripts/run_ablation.py --profile mock --include-rbac-off
.\.venv\Scripts\python.exe scripts/make_report_tables.py

# Start Backend & Frontend
.\.venv\Scripts\python.exe -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
.\.venv\Scripts\python.exe -m streamlit run src/ui/app.py --server.port 8501
```

## Required .env Variables (Names Only)
- Core: `APP_ENV`, `API_HOST`, `API_PORT`, `CORS_ORIGINS`, `SECRET_KEY`, `SEED_DEFAULT_PASSWORD`
- Profiles: `LLM_PROFILE`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `DEMO_LLM_BASE_URL`, `DEMO_LLM_API_KEY`, `DEMO_LLM_MODEL`
- Storage: `DATABASE_PATH`, `QDRANT_STORAGE_PATH`, `BM25_INDEX_PATH`
- Flags: `ENABLE_RBAC`, `ENABLE_MEMORY`, `ENABLE_ADAPTIVE_ROUTER`, `ENABLE_CORRECTIVE_GRADER`, `ENABLE_XAI_OUTPUT`, `ENABLE_HEADING_PATH`

## File Map
- Ingestion & Corpus: `src/ingestion/`, `data/raw/`, `data/synthetic/`, `scripts/corpus_manifest.py`, `docs/CORPUS_GUIDE.md`
- Core RAG & Logic: `src/rag/baseline.py`, `src/core/router.py`, `src/core/grader.py`, `src/core/memory.py`, `src/core/xai.py`, `src/core/llm_client.py`
- Evaluation: `src/evaluation/`, `scripts/eval_retrieval.py`, `scripts/run_ablation.py`, `scripts/make_report_tables.py`, `scripts/review_gold_set.py`
- Auth, API & UI: `src/core/auth.py`, `src/api/`, `src/ui/`, `tests/test_ui_app.py`, `docs/DEMO_SCRIPT.md`

## Known Gaps & Unverified Items
- `.env` has an empty `LLM_API_KEY`, so `dev` and `demo` live LLM profiles have NOT been verified against an external live provider.
- Gold set questions are currently `draft` (0/40 student reviewed) pending manual verification via `scripts/review_gold_set.py`.
- Evaluation tables currently represent `mock` harness checks.

## Next Single Step
- Review $\ge 40$ questions via `scripts/review_gold_set.py`, configure live dev key in `.env`, and run `scripts/smoke_demo.py --profile dev`.
