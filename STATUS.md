# Project Status & Execution Log

**Current Phase:** Phase 12 (Independent Verification & Real-LLM Security Run) Complete  
**Verification:** Full pytest suite passing (270 passed, 0 failed, 1 deselected slow) | Leakage rate: strictly 0.00% (141/141 cells across 3 roles on real index + 32 adversarial probes) | Red team evaluation: 45/45 passed on toy local model (`sshleifer/tiny-gpt2`, smoke test only, cannot follow instructions) and mock | Canary guard: 0 leaks across 7 operational surfaces | Audit anchor: exported & verified (`reports/audit_anchor_latest.json`) | Corpus: 24 docs, 101 chunks | Gold v2: 115 items (0 human-reviewed, 115 unreviewed draft) | Knowledge Graph: 38 nodes, 35 edges

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
  - **Next.js UX Pass:** Hardened error taxonomy, global offline provider, composer guards, per-message status, truthful reasoning panel, skeletons, optimistic mutations, keyboard shortcuts, accessible WCAG contrast, and unified Sonner toasts.

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
