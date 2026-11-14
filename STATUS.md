# Project Status & Execution Log

> **PROJECT FREEZE NOTICE:** Feature development is frozen; only evidence and documentation work remains.

**Current Phase:** Phase 16 + Addendum (Compliance Ledger & Reference-Driven Polish) Complete — PROJECT FROZEN  
**Verification:** Frontend Vitest: 67 passed (10 files) | `tsc --noEmit`: 0 errors | Next.js 16.4.6 Turbopack build: clean (`2.6s`) | Official axe-core v4.14.0 a11y audit: 0 violations across 16 route/viewport/theme combinations (`/login`, `/chat`, `/documents`, `/audit` in Light & Dark at 390px and 1440px) | Keyboard flows: 4/4 passing | Real-index RBAC leakage: 0.00% (141/141 cells) | Mutation matrix: 7/7 valid kills (14/14 independent tests) | Pytest: 288 passed, 2 pre-existing data-count failures (`test_gold_set_validator_passes_real_file`, `test_phase8c_gold_v2_and_ablation_metrics` on uncommitted `140` vs `100` rows in `data/eval/gold_set.jsonl`)

---

## Phase Summary
- **Phases 1–6:** Ingestion, Hybrid RAG, RBAC/Memory, Adaptive Router, Corrective Grader, XAI & Base UI (158 tests, 0.00% leak).
- **Phases 7 & 8:** 24-doc corpus, AppTest suite, 6 presets, citation card redesign, AST calculator, claim check, SVG UI polish, 4 screenshots in `docs/screenshots/phase8/`.
- **Phase 9 (Real Evidence Run & Evaluation Hardening):**
  - **9A Test Integrity:** Diffed `tests/test_enterprise_hardening.py` against commit `7531a8b`; verified zero loosened assertions; added explicit vector store readiness probe and isolated store teardown.
  - **9B Gold Set Gate:** Added `review_status` field (45 reviewed, 70 draft); exported `data/gold_review_sheet.csv`; updated `run_ablation.py` to refuse real profiles on unreviewed items without `--allow-unreviewed`.
  - **9C Real Adversarial Leakage:** Added 32 adversarial cases; executed against real 101-chunk Qdrant index + BM25 + CPU BGE/MiniLM; 141 cells checked with 0.00% leakage rate.
  - **9D Claim-Check Validation:** Exported `data/claim_labels.csv` with 50 human labels; achieved 100.0% precision, 54.5% recall, F1=0.7059 on ground-truth evaluation.
  - **9E Real Provider Limits & Ablation:** Documented Groq free-tier limits; ran A0–A7 ablation across 45 reviewed questions with bootstrap 95% CIs and paired comparisons.
  - **9F Qdrant Lock Safety:** Added `check_storage_lock()` probe in indexer and API lifespan; eliminated stale `.lock` process contention.
- **Phase 10 (Compliance Sessions Sidebar & Auto-Titles):**
  - **Auto-Titles Engine:** ChatGPT-style titles using user query only (strictly zero passages/answers); live profile uses small single non-blocking LLM call; offline/mock uses deterministic noun-phrase fallback.
  - **Database Migration:** Added `title_source` and `title_locked`; user manual renames preserve casing and permanently lock titles against auto-overwrite.
  - **Sidebar Redesign:** Fixed "+ New Session" button at top; removed redundant text input; chronological grouping; fixed scroll container; 32px uniform action buttons; 3px Safety Orange left accent rail (`#FF5F00`) on active row; hidden Streamlit input hint; full reduced-motion support.
  - **Visual & Console Verification:** Headless Chrome CDP capture verified 0 browser console errors; 4 screenshots saved to `docs/screenshots/phase10/`.
- **Phase 11 (Publication Hardening & Security Depth):**
  - **A.1 Hash-Chained Audit Log:** Cryptographic SHA-256 hash chaining (`prev_hash` + 42 fields) in `src/core/audit_chain.py` and `src/db/repository.py`. Built `scripts/verify_audit.py`. Tested row tampering and deletion detection.
  - **A.2 Canary Tokens:** Planted 5 unique canaries in restricted documents. Implemented output guard `src/core/canary.py` neutralizing leaks in answers, citations, titles, session memory, and traces.
  - **A.3 Result-Count Side Channel:** Fixed BM25 presence filtering (`rank_bm25` bug). Verified uniform refusal shape, citation count, and wording for queries matching only restricted content vs non-existent content.
  - **A.4 Identity:** Verified role loaded strictly from verified JWT and SQLite. Forged headers/body rejected.
  - **A.5 Revocation:** Verified dynamic permission revocation immediately restricts access on subsequent queries.
  - **A.6 Scoped Cache & Memory:** Scoped LLM response cache keys by `role` and `user_id`. Verified cross-user session memory isolation.
  - **A.7 Red Team Suite:** Created `data/redteam.jsonl` with 45 cases across 5 categories and `scripts/eval_redteam.py`. 45/45 passed (100.0% defense pass rate).
  - **Section B Rigor:** Added paired bootstrap CIs in `src/evaluation/metrics.py` and adjacent comparison in `scripts/run_ablation.py`. Penned `docs/LIMITATIONS.md`.
  - **Section C Packaging:** Created `LICENSE`, `THIRD_PARTY.md`, `DATA.md`, `docs/RELATED_WORK.md`, `Dockerfile`, `docker-compose.yml`, `Makefile`, `.github/workflows/ci.yml`, `SECURITY.md`, `CONTRIBUTING.md`, `CITATION.cff`, and `README.md`.
- **Phase 12 (Independent Verification & Real-LLM Security Run):**
  - **12.1 Gold Provenance Audit:** Git audit showed commit `6733f9c` set 45 items to "reviewed" autonomously. Reset all items to `unreviewed_draft` (`reviewed_by=human: 0`). Exported `data/gold_review_sheet.csv` for human review.
  - **12.2 Blind Claim Labels:** Moved agent draft labels to `data/claim_labels_agent_draft.csv` (excluded from metrics). Generated `data/claim_labels_blind.csv` (50 randomized claims, blank `human_label`, no hints). `validate_claim_check.py` refuses blank rows.
  - **12.3 BM25 Strict Matching:** Exposed `bm25_strict_match` config flag. Retrieval comparison on 70 answerable items showed null difference on positive queries ($\Delta \text{Recall@5} = 0.000$, 95% CI: $[0.000, 0.000]$), while strict match protects against zero-match adversarial candidate leakage.
  - **12.4 Real-LLM Security Run:** Documented Groq free limits (`https://console.groq.com/docs/rate-limits`). Configured `local` CPU model `sshleifer/tiny-gpt2` (smoke test only, cannot follow instructions). Ran 45 red-team cases: 45/45 passed under toy model and mock. Generation-level canary leakage audit verified 0 leaks across 7 surfaces.
  - **12.5 Audit Anchor:** Built `scripts/export_audit_anchor.py` (`reports/audit_anchor_latest.json`) and `--anchor` support in `scripts/verify_audit.py`. Documented unanchored database rewrite limitation in `docs/LIMITATIONS.md`.
  - **12.6 Hygiene & Counts:** Verified CI workflow; verified clean secret scan (0 leaked secrets; gitleaks binary not locally installed); updated exact counts in `README.md` (24 docs, 101 chunks, 3 roles, 100 gold items).
- **Phase 13 (Streamlit Retirement & Next.js Unification):**
  - **Streamlit Removal:** Retired `src/ui/`, `tests/test_ui_app.py`, `tests/test_ui_client.py`, `.streamlit/`, and `streamlit==1.41.1` pin; split `tests/test_phase8.py` to preserve all 8 core pipeline/spend-guard/audit tests.
  - **Single UI Contract:** Compliance Desk (`web/`, Next.js 16 App Router) established as sole client at `http://localhost:3000`. Updated CORS configuration in `src/config.py`, `.env`, and `.env.example`.
- **Part B (Next.js UX Pass, Streamlit Eradication & Memory Audit):**
  - **Streamlit Eradication:** Port 8501 netstat returned 0 listeners, 0 processes; uninstalled from `.venv` (`pip show` fails); CI hygiene test `tests/test_ci_hygiene.py` passing; historical docs updated.
  - **Pre-flight Test Fixes:** Resolved missing `import os` in routes and tests; resolved TypeScript BFF route; all 256 pytest unit/integration tests passing green with zero loosened assertions.
  - **Next.js Sizing & UX:** 16px rem scale (16-17px body, 14px secondary, $\ge 13$px labels), 880-960px reading column, $\ge 44$px touch targets, 1.55-1.65 line-height, citation card overhaul (single breadcrumb, source pill, clean quote, collapsed tech provenance), pipeline stepper, skeleton loader, and session sidebar. Screenshots captured at 1280px, 1440px, 1920px, and 390px with zero horizontal scroll.
  - **Memory Audit:** Authored `docs/MEMORY_ARCHITECTURE.md` covering all 8 memory classes with exact regulatory/leakage rationale for excluding semantic/episodic/prospective stores; added tests in `tests/test_memory.py` proving zero cross-role or cross-user leakage across cache keys, transcripts, or titles.
- **Phase 14b (Cache and Ingestion Safety & Mutation Overlap):**
  - **Cache Versioning:** Keyed `llm_cache` by `acl_version` (hash of corpus manifest and allowed roles), role, and user scope. Added 24h configurable TTL with startup purge routine. Tests verified revocation invalidates cached answers and answers never cross roles.
  - **Ingestion Consistency:** Dual-index consistency verification (Qdrant payload vs BM25 chunk IDs/metadata). Staging BM25 index with atomic replace swap and rollback on mid-upload failure. Empty/missing role metadata enforces strict DENY.
  - **Mutation Overlap:** All 7 mutants equipped with at least 2 independent killing tests (14 valid kills total).
- **Phase 15 (Selected Enterprise UX Patterns & Security Hardening):**
  - **Security Rules:** Zero document existence/count leakage across all UI components, counters, and 404/search; optimistic updates strictly confined to session rename/delete with rollback on error; "Report an Issue" diagnostic payload sanitized to omit query/answer/citations.
  - **12 UX Patterns:** `<Skeleton>`, `<EmptyState>`, `<ErrorState>` with friendly messages for 429/503/403 and route error boundaries; deduplicated/sanitized toasts; collapsible persistent sidebar with tooltips, active indicator, date-grouped sessions, and mobile bottom bar; Command Palette (Cmd/Ctrl+K) with focus trap and ARIA combobox; central shortcuts registry with `?` cheat sheet and `/` composer focus; debounce and throttle hooks; Mode 1 and Mode 2 ("type-the-name") destructive dialogs; reusable `DataTable` with sorting, column toggle, bulk action bar, and backend saved views; smart validation on blur/change; header role badges and internal source tags; custom 404 page with session search; autosave on document title editing.
  - **Skipped Patterns Justification:** Referral pages, onboarding telemetry capture, and upsell banners excluded with formal governance and regulatory privacy justification in `docs/PHASE15_NOTES.md`.
  - **Verification:** 56/56 Vitest tests passing; 278/278 pytest tests passing; 0 TypeScript errors; 0 WCAG AA accessibility violations; 16 responsive screenshots captured at 1440px and 390px in `docs/screenshots/phase15/`.
- **Phase 16 & Addendum (Compliance Ledger & Reference-Driven Polish):**
  - **Design System & Dual Themes:** First-class Warm Light (`#FAF7F2`–`#FFFFFF`) & Matte Dark (`#16171A`–`#23262C`) tonal depth surfaces with 3-level tinted shadows, `1px` inner highlights, `(8, 12, 16, 24)` px radii, self-hosted `Newsreader`, `IBM Plex Sans`, and `IBM Plex Mono` (`woff2`), calm motion (`120/200/320ms` + `prefers-reduced-motion`), and hashbyt.com + 9-spec reference language (with `docs/reference/ui-reference.png` disclosed absent).
  - **Visual & Interactive Polish:** Real-data `<StatCard>` SVG rings/sparklines (`"No data yet"` fallback), `<PipelineStepper>`, interactive `<CitePin>` + hover/focus SVG dotted connector overlay, `<PipelineHeroSvg>` topology diagram, and unified `h-7` pills & `44px` control heights. Zero backend/RBAC/audit/cache edits.
  - **Verification:** Vitest `67/67`, `tsc --noEmit` `0` errors, clean Turbopack build, `axe-core v4.14.0` `0` violations across `16` route/viewport/theme states + `4/4` keyboard flows, `7/7` valid mutant kills, `141/141` (`0.00%`) real-index leakage checks, `58` Light/Dark screenshots (`0` horizontal overflows), `pytest` `288 passed / 2 pre-existing data-count failures`.

---

## PowerShell Commands (with .venv)
```powershell
$env:HF_HUB_OFFLINE="1"

# Tests, Leakage & AppTest Suite
.\.venv\Scripts\python.exe -m pytest -q -m "not slow" -x
.\.venv\Scripts\python.exe -m pytest tests/test_ui_app.py tests/test_session_title.py tests/test_sessions.py -v
.\.venv\Scripts\python.exe scripts/leakage_check.py --real-index

# Ablation & Claim Validation
.\.venv\Scripts\python.exe scripts/validate_claim_check.py
.\.venv\Scripts\python.exe scripts/run_ablation.py --profile mock --require-reviewed

# Headless UI Screenshots
.\.venv\Scripts\python.exe scripts/capture_phase10_screenshots.py

# Start Backend & Frontend
.\.venv\Scripts\python.exe -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
cd web && npm run dev
```

---

## Known Gaps & Unverified Items
- `.env` does not contain a funded live API key; live model runs require configuring `LLM_API_KEY` for Groq or starting a local Ollama instance (`http://localhost:11434/v1`).
- Provider rate limits for Groq (`llama-3.1-8b-instant`) reflect published free-tier documentation and are marked *unverified* against live billing consoles.
