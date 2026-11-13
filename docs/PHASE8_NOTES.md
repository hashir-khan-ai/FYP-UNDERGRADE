# Phase 8 Engineering Notes, Interpretations & Verification Record

**Project:** Enterprise RAG Assistant for Banking Regulatory Compliance (COM6301)  
**Scope:** Phase 8A (Integrity Fixes), Phase 8B (Citation Card Redesign), Phase 8C (RBAC-Safe Stretch Tools & Gold v2 Ablations), Phase 8D (UI Polish & Visual Verification)  

---

## 1. Autonomous Interpretations & Design Decisions

Where specifications allowed multiple reasonable interpretations, the following choices were taken and locked in tests:

### Phase 8A — Integrity Fixes
- **8A.1 Raw HTML Leak (`5c5d0b3`):** Stripped HTML tags and markdown `#` heading prefixes inside `ClauseAwareChunker` at ingestion time *and* HTML-escaped all chunk/heading text (`html.escape`) at render time so internal badges or user-supplied markup can never inject into verbatim blockquotes.
- **8A.2 Spend Guard Lifecycle (`bb0d11a`):**
  - `mock` and local `dev` profiles never count against or fail on `LLM_MAX_CALLS_PER_RUN`; `mock` is completely unmetered with separate telemetry counters (`offline_calls`, `offline_tokens`) labelled `"estimated tokens"` in UI telemetry. Local `dev` retains only a high runaway safety ceiling (`LLM_LOCAL_SAFETY_CALLS`, `LLM_LOCAL_SAFETY_TOKENS`) mapped to HTTP `503`.
  - Live paid profiles enforce **two orthogonal budgets**: an atomic per-query budget (reset at each user query boundary) and a separate per-session call cap (`session_calls` / `session_calls_limit`). Replaced raw configuration strings in client responses with a sanitized human notice and an explicit `"Reset budget"` control in the sidebar.
- **8A.3 Profile Truth (`500c14c`):** Exposed the exact runtime layer flags (including `claim_check` and `calculator`) via `GET /api/v1/admin/config` and per-turn metadata (`active_layers`). When `xai_output` is `OFF`, both the reasoning trace expander and XAI-only stretch tool panels are suppressed cleanly.
- **8A.4 Login Leakage Metric & Demo Helper (`4118ced`):** Replaced hardcoded `0.00%` text on the login screen with `get_latest_leakage_status()`, reading the most recent `reports/leakage_*.json` report and ISO timestamp (falling back to `"not yet measured"` when absent). Quick-fill synthetic persona buttons render only when `DEMO_MODE=true`.

### Phase 8B — Human-Friendly Citation Cards (`5c81add`)
- Rebuilt `render_citation_card_html()` in the strict top-to-bottom order: `[idx] Document Title` -> single deduplicated `heading_path` breadcrumb (no duplicate `Clause:`/`Heading Path:` lines or backticks) -> source authority pill (`Public · verifiable` with links OR lock icon + `Internal · visible to <Roles>` read from `allowed_roles`, omitting any `"no verification link"` text) -> escaped verbatim blockquote with matched-sentence highlight -> collapsed `Technical details` `<details>` holding `Doc ID`, `Page`, `Chunk ID`, and a **Copy** button.
- Added clickable/hoverable `[1]`, `[2]` inline citation markers in rendered answers wired through a delegated same-origin pointer handler to expand, scroll to, and pulse the corresponding card.

### Phase 8C — Stretch Tools Behind Config Flags (`7531a8b`)
- **Strict Default OFF & Scope:** `ENABLE_CLAIM_CHECK=false` and `ENABLE_CALCULATOR=false` by default; activated exclusively per config or in `A6_claim_check` / `A7_calculator` ablation profiles (`mock` tested).
- **`claim_check` (`src/core/claim_check.py`):** Splits generated answers into atomic sentence claims, filters input chunks through `enforce_role_visibility()` *before* scoring, scores lexical/numeric overlap plus optional local CPU embedder/reranker similarity (`scoring_mode` degrades cleanly to heuristic lexical+numeric when `mock_reranker` is active or models are unloaded), marks each claim `supported` / `weak` / `unsupported`, removes unsupported sentences in strict compliance mode, logs results into SQLite `audit_log.claim_check_json`, and renders compact status badges inside the XAI panel.
- **`calculator` (`src/core/calculator.py`):** Pure `ast.parse(..., mode="eval")` AST whitelist evaluator supporting numeric literals, `+ - * / **`, unary `+/-`, parentheses, and safe named functions (`abs`, `round`, `min`, `max`, `sum`). `eval()` and `exec()` are never used; attribute access, subscripts, lambdas, and non-whitelisted calls (e.g., `__import__('os')`) are rejected immediately. Operands are extracted solely from `enforce_role_visibility()`-filtered passages with `chunk_id` attribution; missing operands cause a clean refusal rather than guessing.
- **Gold Benchmark Extension (`data/gold_v2.jsonl`):** Preserved the first 100 items (`GS-001..GS-100`) byte-identical to `data/eval/gold_set.jsonl` and appended 15 synthetic numeric/multi-claim draft items (`GS-101..GS-115`), keeping `status="draft"` per validator schema rules. Added `A6_claim_check`, `A7_calculator`, `unsupported_claim_rate`, and `numeric_exact_match`.

### Phase 8D — Visual Polish & Headless Verification
- Enforced `DESIGN.md` 60/30/10 palette (`#1C1D20`, `#26292E`/`#5A6068`, `#FF5F00`, `#F1F3F4`) using pure CSS + inline `<svg>` icons (`get_svg_icon()`), removing all UI emoji codepoints, `<canvas>` tags, external CDNs, and network fonts.
- Replaced `<canvas>` topology diagram with pure inline SVG (`RAG_TOPOLOGY_CANVAS_HTML`), resolving a CommonMark blank-line indentation issue so zero HTML/code-block parsing warnings occur in Streamlit.
- Implemented live animated 5-stage pipeline stepper (`Route > Retrieve > Re-rank > Grade > Answer` with skipped markers and stage latencies), staggered citation entrance (`citeCardEnter`), subtle 3D citation hover tilt (`perspective(900px) rotateX(2.5deg) rotateY(-4deg)`), stacked CSS 3D sidebar layer cards (`.layer-stack-3d`), typing skeleton shimmer, wrapping buttons, `#FF5F00` focus outlines, and `@media (prefers-reduced-motion: reduce)` fallbacks disabling all animations and 3D transforms.

---

## 2. Environment Observations (Qdrant `.lock`)

- `./data/qdrant/.lock` was held by an external host process outside agent-controlled shells during Phase 8 work.
- Ingestion sanitization tests and BM25 corpus index verification (`data/sqlite/bm25_index.pkl`) were executed directly against sanitized chunks, and headless UI + evaluation tests operated safely on isolated temporary copies of `./data/qdrant` (excluding `.lock` files). On a clean restart with no external server process holding `./data/qdrant/.lock`, `scripts/run_ingestion.py` can refresh Qdrant payloads in-place without lock contention.

---

## 3. Package & Model License / Benchmark Audit

Only licenses directly inspected in `.venv` distribution metadata or local HuggingFace cache files are listed as verified; everything else is explicitly recorded as **`unverified`**.

| Artifact / Package | Version (`.venv`) | Verified License / Status | Source Inspected |
| :--- | :--- | :--- | :--- |
| `fastapi` | `0.162.4` | `MIT` | `.venv` package metadata |
| `uvicorn` | `0.54.0` | `BSD-3-Clause` | `.venv` package metadata |
| `pydantic` | `2.14.3` | `MIT` | `.venv` package metadata |
| `pydantic-settings` | `2.16.2` | `MIT` | `.venv` package metadata |
| `streamlit` | `1.41.1` | `Apache License 2.0` | `.venv` package metadata |
| `qdrant-client` | `1.20.0` | `Apache-2.0` | `.venv` package metadata |
| `rank-bm25` | `0.2.2` | `Apache2.0` | `.venv` package metadata |
| `sentence-transformers` | `6.2.0` | `Apache-2.0` | `.venv` package metadata |
| `torch` | `2.15.0` | `Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSD-2-Clause AND BSD-3-Clause` | `.venv` package metadata |
| `transformers` | `5.22.2` | `Apache 2.0 License` | `.venv` package metadata |
| `httpx` | `0.28.1` | `BSD-3-Clause` | `.venv` package metadata |
| `pypdf` | `7.0.1` | `BSD-3-Clause` | `.venv` package metadata |
| `beautifulsoup4` | `4.15.0` | `MIT License` | `.venv` package metadata |
| `argon2-cffi` | `25.1.0` | `MIT` | `.venv` package metadata |
| `python-multipart` | `0.0.20` | `Apache-2.0` | `.venv` package metadata |
| `pytest` | `9.2.0` | `MIT` | `.venv` package metadata |
| `BAAI/bge-small-en-v1.5` (model) | local HF cache | `MIT License` (`FlagEmbedding`) | Local HF snapshot `README.md` |
| `cross-encoder/ms-marco-MiniLM-L-6-v2` (model) | local HF cache | `unverified` (no `README.md` cached locally) | Local HF cache check |
| External LLM model benchmarks / MTEB metrics | n/a | `unverified` (no live external benchmark suite run) | Policy: mock runs excluded from evidence |

---

## 4. Headless UI Boot & Visual Verification

Verified live UI boot in headless Chrome (via DevTools Protocol against isolated local FastAPI + Streamlit under `LLM_PROFILE=mock` and `DEMO_MODE=true`):
- **Console Errors:** `0` across login, Manager authentication, compliance chat query, citation expansion, and sidebar telemetry inspection.
- **Page Exceptions:** `0`.
- **Captured Screenshots (`docs/screenshots/phase8/`):**
  - `docs/screenshots/phase8/login.png` — Login form, `OFFLINE MOCK · mock` pill, dynamic `measured 0.00% leakage` timestamp badge, `DEMO_MODE`-gated quick-fill persona buttons.
  - `docs/screenshots/phase8/chat.png` — Authenticated Manager workspace, `[1]..[5]` inline jump markers, animated 5-stage pipeline stepper (`Route`, `Retrieve`, `Re-rank`, `Grade skipped`, `Answer`), wrapping Suggested Inquiries buttons.
  - `docs/screenshots/phase8/citations.png` — Redesigned human-friendly citation card (`[5] Bank Internal Management Policy...`), single breadcrumb line, lock icon + `Internal · visible to Manager, Auditor`, highlighted verbatim quote, collapsed `Technical details`.
  - `docs/screenshots/phase8/sidebar.png` — `System Profile & Run Budget` showing runtime layer flags, CSS 3D `.layer-stack-3d` indicator, and `offline-mock (unmetered)` estimated token counters.

---

## 5. Mock Ablation Notice (`MOCK, not evidence`)

All ablation runs executed in Phase 8C/8D use `--profile mock --mock-reranker` on `data/gold_v2.jsonl` (`A0_baseline`..`A7_calculator`). Every emitted artifact and console banner is explicitly marked **`MOCK, not evidence`**. Mock metrics verify pipeline instrumentation, `unsupported_claim_rate`, `numeric_exact_match`, and RBAC isolation only, and **must not** be written into dissertation prose as empirical model evaluation evidence.

