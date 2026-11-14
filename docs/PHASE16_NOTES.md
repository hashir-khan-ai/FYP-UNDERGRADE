# Phase 16 — Premium Frontend Redesign Notes ("The Compliance Ledger")

**Scope:** Visual, typographic, layout, SVG craft, and motion redesign only. Zero modifications to FastAPI endpoints, RBAC filtering (`allowed_roles`), SQLite audit/session schemas, caching keys, or data flows.

---

## Step 1 — Baseline Metrics & Honest Critique

### Baseline Build & Asset Measurements (Pre-Redesign)
- **Static JS total (`web/.next/static/**/*.js`):** `30` files — `1,164.8 KB` raw (`364.7 KB` gzipped)
- **Static CSS total (`web/.next/static/**/*.css`):** `1` file — `59.1 KB` raw (`11.3 KB` gzipped)
- **Pre-Phase-16 Build Blocker Found & Unblocked:** Running `npm --prefix web run build` uncovered two missing optional props in `CommandPaletteProps` (`onSelectAction`) and `DataTableProps` (`selectable`) referenced by `web/tests/phase15-keyboard.test.tsx`. Added backward-compatible optional prop signatures without altering any test file.
- **Icon Family Measurement (`draw-svg/scripts/measure.mjs` on `http://localhost:3000/login`):**
  - Library detected: Lucide (`24x24` grid, line strokes)
  - Stroke weight: `2` (`1.75` optical), `round` caps and joins, corner radius `2`, padding `1`, shown at `14`, `16`, `20` px.
- **Baseline Lighthouse (`/login`, mobile preset):**
  - Performance: **93** (`FCP = 779ms`, `LCP = 779ms`, `TBT = 336ms`, `CLS = 0`)
  - Accessibility: **98** (deduction: `landmark-one-main` — `/login` lacked a `<main>` landmark)
  - Best Practices: **100**
- **Baseline Lighthouse (`/chat`, session with citations, mobile preset):**
  - Performance: **90** (`FCP = 935ms`, `LCP = 3,407ms`, `TBT = 139ms`, `CLS = 0`)
  - Accessibility: **98** (deduction: `heading-order` — headings skipped levels in rendered markdown answers)
  - Best Practices: **100**

### Baseline Screenshots Critique (`docs/screenshots/phase16/before/`)

Inspected all 20 baseline screenshots across `390px` and `1440px`:

1. **Palette Drift & Generic SaaS Look (`tokens.css` vs `DESIGN.md`):**
   - `tokens.css` drifted completely from the mandated 60/30/10 palette (`#1C1D20` Matte Black / `#26292E` + `#5A6068` Storm Grey / `#FF5F00` Safety Orange / `#F1F3F4` Polar White) into a cliché dark-navy + glowing-blue `#070b11` / `#78a9ff` / `#54d6c4` SaaS template with radial neon blurs and grid masks (`.app-atmosphere`).
2. **Broken CSS Variable References in `ErrorState` & `EmptyState`:**
   - `web/components/ui/error-state.tsx` and `web/components/ui/empty-state.tsx` reference undefined CSS variables (`--status-danger-subtle`, `--status-danger-border`, `--text-primary`, `--text-secondary`, `--text-muted`, `--surface-primary`, `--accent-primary`), causing degraded fallback styling when rendered.
   - `ChatView` renders a hand-rolled inline danger div on 429/503 instead of using the shared `<ErrorState>` component (`05_error_429_1440px.png`).
3. **Typography & Accessible Floor Violations:**
   - All text uses system UI sans (`-apple-system`) with no typographic hierarchy differentiating institutional headings, regulatory verbatim clauses, and UI controls.
   - Multiple labels violate the `>= 13px` minimum floor: `MobileBottomBar` uses `text-[10px]`, `TrustCell` restricted pill and `NotFound` header use `text-[11px]`, `.kbd` uses `0.625rem` (`10px`), and `.command-palette` ESC key uses `text-[11px]`.
4. **Login Collision (`01_login_1440px.png`):**
   - Top-left brand subtitle `REGULATORY INTELLIGENCE` physically touches the `"Local-first regulatory intelligence"` pill border.
   - Missing `<main>` landmark causes Lighthouse Accessibility `98` instead of `100`.
5. **Mobile First-Fold Crushed on `/chat` (`02_empty_chat_390px.png`):**
   - Tall hero spacing + 3 full-height starter cards + dual-row composer controls + fixed bottom tab bar push the greeting heading and first two starter cards completely above the scroll fold on `390px` viewports; users land seeing only card #3 and the input box.
6. **Nested "Box Soup" & Static Citations (`03_answer_citations_1440px.png`):**
   - Citation panel stacks four nested bordered rounded boxes (outer citation box → rounded pill → rounded blockquote box → nested rounded `<details>` box).
   - Inline citation numbers `[1]`, `[2]`, `[3]` in answer prose are passive unstyled text with no hover highlight, marginalia linkage, or scroll-and-pulse behavior.
   - On wide `1440px` viewports, right-hand space beside the `60–72ch` column is wasted instead of showing clean footnote marginalia.
7. **Broken Pill Wrapping & Horizontal Table Clipping (`06_documents_1440px.png`, `06_documents_390px.png`, `07_audit_1440px.png`):**
   - In `/documents`, long hyphenated filenames truncate awkwardly mid-word inside bordered pills (`BASEL-III-Capital-Ad`), and the internal `"Restricted to Manager, Auditor"` rounded-full pill collapses into a stacked orange circle (`06_documents_1440px.png`).
   - Both `/documents` and `/audit` clip right-most columns (`TRUST`, actions, `Latency`) horizontally at `1440px` inside `.overflow-x-auto`.
   - On `/audit` (`07_audit_390px.png`), the `User ID...` filter input height mismatches adjacent `<select>` controls.
8. **Command Palette Footer Cramping (`09_command_palette_390px.png`) & Minimal 404 (`08_not_found_1440px.png`):**
   - At `390px`, the command palette footer hints collide cleanly across two tightly wrapped blocks with no tap-friendly close button (`ESC` is non-interactive `<kbd>`).
   - The `404` page is a stark generic box with no bespoke illustration.

---

## Step 2 — Architecture Plan: "The Compliance Ledger"

1. **Strict 60/30/10 Palette + Optional Light Mode:**
   - Dark default (`#1C1D20` canvas 60%, `#26292E` / `#5A6068` Storm Grey structures & hairlines 30%, `#FF5F00` Safety Orange interactive accents 10%, `#F1F3F4` Polar White ink).
   - `[data-theme="light"]` token block (`#F7F5F0` archival ledger paper, `#EAE6DD` Storm parchment secondary, `#5A6068` muted rules, `#C94600` WCAG-AA darkened Safety Orange for text/buttons, `#1C1D20` Matte Black ink) toggled cleanly via user preference without breaking existing routes.
2. **Self-Hosted Editorial Typography (`next/font/local`, `.woff2` Latin Subsets, SIL OFL 1.1):**
   - **Serif (`Newsreader` variable weight 400–700 + italic):** Display headings, page headers, and verbatim regulatory blockquotes.
   - **UI Sans (`IBM Plex Sans` 400, 500, 600):** Interface controls, tables, memos, navigation.
   - **Mono (`IBM Plex Mono` 400, 500):** Clause IDs (`CASS-7.13.1R`), audit hashes, route tags, latencies, keyboard badges (`.tabular` tabular-nums everywhere).
   - Strict `clamp()` fluid scale (`16–17px` body, `1.6` line-height, `60–72ch` answer measure, zero text below `13px`).
3. **Interactive Memo & Marginalia Citations:**
   - Interactive `[1]`, `[2]`, `[3]` footnote markers inside markdown prose + sticky/aligned desktop right-margin marginalia ledger notes (`xl:grid-cols-[minmax(0,68ch)_280px]`) + collapsible full citations drawer (`Sources & citations (N)` default collapsed cleanly preserved, hover/focus highlights matching citation, click opens/scrolls & pulses with Safety Orange rail).
4. **Centralized Motion Tokens (`web/lib/motion.ts` & `web/styles/motion.css`):**
   - `120ms` / `200ms` / `320ms` durations, standard & emphasized cubic-beziers, Framer Motion springs for sidebar collapse and palette, `startViewTransition` helper + fallback, staggered entrances, soft streaming caret, synchronized shimmer skeletons, animated KPI counters, <= 4deg CSS perspective tilt on starter cards only, full `@media (prefers-reduced-motion: reduce)` parity.
5. **Bespoke `draw-svg` Assets:**
   - Brand lockup & uniform inline stroke SVG icons (`24x24`, `strokeWidth=2`, `round` caps/joins).
   - Live horizontal SVG RAG topology & 5-stage pipeline stepper (`Route -> Retrieve -> Re-rank -> Grade -> Answer`).
   - Spot editorial SVG illustrations for 404, 429/503 Error, and Empty states.


---

## Step 3 & Addendum — Reference-Driven Polish ("The Compliance Ledger")

### Reference Asset Disclosure
- `docs/reference/ui-reference.png` does **not** exist in the repository (`docs/reference/` is absent).
- Per instructions, the enterprise UI design language was extracted from `https://hashbyt.com/blog/enterprise-ui-design` combined with the 9 Phase 16 Addendum specifications (tonal depth surfaces, whisper-soft tinted shadows, restrained Safety Orange accents, SVG progress/sparkline telemetry from real data only, calm motion, and crisp control geometry). No third-party copy, photos, layouts, or branding were copied.

### Architecture & Design Tokens (`web/styles/tokens.css`, `web/app/globals.css`, `web/styles/motion.css`)
- **Shape Radius Scale (`8, 12, 16, 24` px):** `--r-sm: 0.5rem` (`8px`), `--r-md: 0.75rem` (`12px`), `--r-lg: 1rem` (`16px`), `--r-xl: 1.5rem` (`24px`), plus `--r-pill: 9999px` for status tags & segmented pills.
- **3-Level Tinted Depth Scale & Inner Highlights (borderless elevation):**
  - Warm Light (`[data-theme="light"]`, warm walnut-tinted shadows `rgba(56, 42, 24, ...)`): `--canvas: #FAF7F2`, `--canvas-raised: #F3EFE7`, `--surface: #FFFFFF`, `--surface-2: #EFEAE1`, `--surface-3: #E6DFD4`, `--surface-inset: #F6F3EC`, `--inner-highlight: inset 0 1px 0 rgba(255, 255, 255, 0.94), inset 0 0 0 1px rgba(46, 38, 28, 0.055)`.
  - Matte Dark (`:root` / `[data-theme="dark"]`, obsidian-tinted shadows): `--canvas: #16171A`, `--canvas-raised: #1D1F24`, `--surface: #23262C`, `--surface-2: #2B2F36`, `--surface-3: #343942`, `--surface-inset: #191B1F`, `--inner-highlight: inset 0 1px 0 rgba(255, 255, 255, 0.075), inset 0 0 0 1px rgba(255, 255, 255, 0.035)`.
- **Theme Persistence (`web/components/providers/theme-provider.tsx`):** Follows OS `prefers-color-scheme` (`window.matchMedia`) until explicitly toggled, persists explicit choice in `localStorage`, and supports quick `Auto` reset in the sidebar footer.

### Verified WCAG AA Contrast Matrix (`web/styles/tokens.css`)
All token foregrounds tested mathematically across all 5 theme surfaces (`canvas`, `canvas-raised`, `surface`, `surface-2`, `surface-inset`) and blended soft badge fills:
- **Warm Light Theme:**
  - `--ink` (`#191A1D`): **14.52:1 – 17.40:1**
  - `--ink-soft` (`#26292E`): **12.18:1 – 14.59:1**
  - `--muted` (`#494D54`): **7.09:1 – 8.49:1**
  - `--faint` (`#575C64`): **5.62:1 – 6.73:1**
  - `--accent-link` (`#9B3400`): **6.08:1 – 7.28:1** (`5.37:1` inside `--accent-soft` badge)
  - Primary CTA (`#16171A` on `#FF5F00`): **5.88:1**
  - Semantic statuses (`--teal` `#0B5E50`, `--success` `#0C5C36`, `--warning` `#7A4600`, `--danger` `#A31D14`, `--info` `#124E9E`, `--non-grounded` `#5B2CA0`): **6.39:1 – 9.08:1** on surfaces, **5.43:1 – 5.68:1** inside blended soft pills.
- **Matte Dark Theme:**
  - `--ink` (`#F1F3F4`): **12.07:1 – 16.10:1**
  - `--ink-soft` (`#DCE0E5`): **10.13:1 – 13.52:1**
  - `--muted` (`#B6BCC4`): **7.03:1 – 9.37:1**
  - `--faint` (`#98A0AA`): **5.08:1 – 6.78:1**
  - `--accent-link` (`#FF8A47`): **5.75:1 – 7.66:1** (`5.44:1` inside `--accent-soft` badge)
  - Primary CTA (`#16171A` on `#FF5F00`): **5.88:1**
  - Semantic statuses (`--teal` `#58D6B8`, `--success` `#5EE09E`, `--warning` `#F5B841`, `--danger` `#FF8585`, `--info` `#8DCBFF`, `--non-grounded` `#D1B8FF`): **5.72:1 – 10.78:1** on surfaces, **5.08:1 – 6.64:1** inside blended soft pills.

### Component Consistency & Interactive Upgrades
- **Stat Cards (`web/components/ui/stat-card.tsx`, used in `audit-view.tsx` and `documents-view.tsx`):** Tabular-figure KPI numerals with delta pills, rounded icon badges, inline SVG progress rings & real-data bar/line sparklines, and explicit `"No data yet"` states when telemetry is empty or unindexed.
- **Pipeline Stepper (`web/components/chat/pipeline-stepper.tsx`):** 5-stage horizontal compliance pipeline (`Route -> Retrieve -> Re-rank -> Grade -> Answer`) with SVG dashed connectors, radial focus halo on active nodes, and subdued skipped stages without faking progress.
- **Citations & Marginalia Connector (`markdown.tsx`, `message-list.tsx`, `citations-panel.tsx`):** Refactored `[n]` citation pins to `CiteContext` + `<CitePin>` so hover/focus updates styles in place without remounting Markdown DOM nodes. Added desktop `CitationConnectorOverlay` rendering an animated orange dotted SVG cubic Bezier curve strictly on active hover/focus to matching marginalia/cards, alongside serif quote insets (`bg-inset`), large monospace clause IDs, and unified `h-7` source pills.
- **Hero Visual & Spot Illustrations (`PipelineHeroSvg` in `trust-map.tsx`, `illustrations.tsx`):** Bespoke SVG topology connecting query -> RBAC server gate -> clause grader -> cited memo, plus empty/error/404 editorial graphics.
- **Restrained Motion (`web/lib/motion.ts`):** Timing tokens fixed at `120ms` / `200ms` / `320ms`, Framer Motion springs for sidebar/palette, `withViewTransition` helper, and full `@media (prefers-reduced-motion: reduce)` fallbacks (`1ms` CSS variables).

### Visual Look-and-Fix Summary (Rounds 1–2) & Honest Remaining Minor Imperfections
- **Fixed in Look-and-Fix Rounds:** Replaced undefined `--elev-floating`/`--elev-xs` classes; moved `StatCard` sparkline cleanly opposite the numeral row so bottom captions never truncate; fixed `<select>` custom chevrons and `44px` button/input height parity; constrained `/documents` column widths + borderless-at-rest inline filename input so `Added` and `Actions` fit cleanly within `1440px` and `JURISDICTION` separates cleanly from `TYPE`; aborted `/api/backend/chat*` via Playwright/CDP Fetch interception in screenshot capture so loading spinner captures cleanly in both themes.
- **Remaining Minor Visual Observations (Honest Critique):**
  1. On `/login`, the `Auditor` quick-fill persona chip displays `AA` initials rather than `CA` (`Carol Auditor`), matching its generic `"Auditor"` label.
  2. On `/documents` at `1440px`, dense 8-column layout truncates long hyphenated document filenames around ~22 characters (`BASEL-III-Capital-Adeq...`), while 3-role `READ ACCESS` badges wrap across two lines.
  3. On `/audit` at `1440px`, the `AUDIT ID` column header wraps across two lines and `PROFILE` cells wrap across 2–3 lines (`mock / 1.3K tok · 4 / calls`).

### Final Post-Edit Verification Results
- **Frontend Unit & Component Tests (`npm --prefix web test`, Vitest `v5.1.0`):** `10` files, **`67` passed, `0` failed** (`tsc --noEmit`: `0` errors).
- **Frontend Production Build (`npm --prefix web run build`, Next.js `16.4.6` Turbopack):** Clean compile in `2.6s` (`27` JS chunks = `1,377.6 KB` raw, `1` CSS stylesheet = `67.7 KB` raw).
- **Accessibility & Keyboard Flows (`scripts/run_axe_audit.py`, `axe-core v4.14.0`):** **`0` violations across all `16` route/viewport/theme combinations** (`8` Light + `8` Dark across `/login`, `/chat`, `/documents`, `/audit` at `390px` & `1440px`); **`4/4` keyboard flows PASS**.
- **Responsive Screenshots (`scripts/capture_phase16b_screenshots.py`):** `58` screenshots in `docs/screenshots/phase16b/after/{light,dark}/` (`390, 768, 1440, 1920` px), **`0` horizontal overflows**.
- **Mutation Matrix (`scripts/run_mutant_matrix.py`):** **`7/7` (`100.0%`) valid `AssertionError` kills** (`14/14` independent killing tests, `0` baseline failures).
- **Real-Index RBAC Leakage (`scripts/leakage_check.py --real-index`):** **`141` cells checked, `0` leaked (`0.00%`)** against the 101-chunk Qdrant + BM25 index.
- **Python Backend Suite (`.venv\Scripts\python.exe -m pytest -q`):** **`288 passed, 2 failed`** in `58.03s` — the only 2 failures are pre-existing data-count checks (`tests/test_phase7_eval.py::test_gold_set_validator_passes_real_file` and `tests/test_phase8.py::test_phase8c_gold_v2_and_ablation_metrics`) asserting `100` rows against `140` lines currently present in `data/eval/gold_set.jsonl` (40 uncommitted `HARD-Q` rows written prior to Phase 16, preserved untouched under visual-only constraints).

---

## Addendum: Runtime Fixes & Offline Gold Review Tool (`2026-11-15`)

### 1. Document Catalogue (`/documents`) Mouse-Wheel Scroll Fix
- **Root Cause:** `web/app/globals.css` combined `html { overflow-x: hidden; }` with `body { overflow-x: hidden; overscroll-behavior-y: none; }`. Paired `overflow-x: hidden` causes Chromium to turn `body` into a scroll container while `overscroll-behavior-y: none` blocks wheel scroll chaining up to `html` on document-scrolled pages (`/documents`, `/audit`).
- **Fix:** Switched `html` to `overflow-x: clip;` and removed `overflow-x: hidden;` and `overscroll-behavior-y: none;` from `body` in `web/app/globals.css`, followed by a fresh Next.js production build.
- **Verification:** Headless Chrome (`1440×760`, authenticated as `auditor` on `/documents` with `scrollHeight=1570`) dispatched `Input.dispatchMouseEvent(mouseWheel, deltaY=500)` and verified `window.scrollY` advanced from `0` to `500` (`WHEEL_SCROLL_PASS`).

### 2. `LLM_AUTH_ERROR` / False "Compliance Service Offline" Diagnosis & Fix
- **Root Cause:** The running Uvicorn worker held a stale `Settings()` singleton prior to `.env` updates, while `.env` itself contained a placeholder `DEMO_LLM_MODEL` string alongside `LLM_PROFILE=mock`. In addition, `src/core/router.py` caught `LLMAuthError` inside its generic `except LLMClientError:` block (falling back while later synthesis raised HTTP `503 LLM_AUTH_ERROR`), and `web/components/ui/error-state.tsx` + `web/components/chat/chat-view.tsx` treated any HTTP `503` as a dead backend offline state (`"Compliance Service Offline"`).
- **Fix:** Re-raised `LLMAuthError` explicitly in `src/core/router.py`, ordered `LLM_AUTH_ERROR` / `LLM_UNAVAILABLE` / `MODEL_WEIGHTS_MISSING` ahead of `statusCode === 503` in `web/components/ui/error-state.tsx`, and excluded `LLM_*` / `MODEL_WEIGHTS_MISSING` errors from triggering the offline server banner in `web/components/chat/chat-view.tsx`.

### 3. Offline Gold Review Tool (`scripts/review_gold.py` & `scripts/apply_review.py`)
- **Generator (`scripts/review_gold.py`):** Generates standalone zero-dependency HTML (`reports/gold_review.html`, zero external CSS/JS/network calls, works directly over `file://`). Shows one item at a time (question, role, difficulty, expected answer) beside the full verbatim cited corpus clause(s) (`heading_path` and `text_content`, zero model outputs). Supports `A`/`F`/`R`/`U`/`S` verdict buttons/keys, `←`/`→` navigation, Fix editor panel, subset/difficulty/status filters, 60-item stratified remaining tracker (`30 original_100 + 20 agent_extra_40 + 10 unanswerable_role_boundary`), `localStorage` persistence, and export to `data/gold_review_decisions.json`.
- **Applier (`scripts/apply_review.py`):** Applies only actionable human decisions (`approved`, `needs_fix`, `rejected`, `unanswerable_correct`) to `data/eval/gold_set.jsonl`, `data/gold_review_sheet.csv`, and matching `gold_v2` rows, stamping `reviewed_by="human"`, `reviewed_at`, and `human_notes`. Leaves undecided and `skipped` items untouched, retains original pre-fix values alongside fixes (`original_gold_answer`, `original_clause`, `original_gold_chunk_ids`), and excludes `rejected` items from `load_gold_set(..., include_rejected=False)`, `select_reviewed_questions()`, and evaluation/ablation scripts. Real repository gold files remain untouched by the agent (`human_reviewed_count=0`).

### 4. Pipeline Stepper Card Alignment & Timing Key Mapping Fix
- **Root Cause:** In `web/components/chat/pipeline-stepper.tsx`, latency pills lacked `whitespace-nowrap` and the stage list used `sm:items-center` instead of `sm:items-stretch`, causing multi-digit durations (such as `664 ms`) to wrap across two lines inside narrow containers and stretch the `Re-rank` card above sibling stage cards while crowding `Answer`. In addition, `buildPipelineStages` checked `"retrieve_ms"` / `"generate"` instead of FastAPI's `"retrieval_ms"`, `"generation_ms"`, and `router.latency_ms`.
- **Fix:** Updated `PipelineStepper` (`sm:items-stretch`, `self-center` dotted connectors, `sm:min-w-[88px]`, `overflow-x-auto`, `whitespace-nowrap` on stage labels and badges) and mapped `retrieval_ms`, `generation_ms`, and `router.latency_ms` in `pipeline-stepper.tsx` and `advanced-details.tsx`. Verified visually in headless Chrome (`780x900`: all 5 stage cards equal `57px` height, `top: 352`, single-line `18px` pills, `STEPPER_LAYOUT_PASS`).

### 5. Final Post-Edit Verification Results
- **Frontend (`npm --prefix web run typecheck`, `npm --prefix web test`, `npm --prefix web run build`):** `tsc --noEmit` `0` errors; Vitest `10` files, **`68` passed, `0` failed**; Next.js `16.4.6` compiled cleanly in `2.9s`.
- **Python Suite (`.venv\Scripts\python.exe -m pytest -q`):** **`291` passed, `2` failed** in `69.68s` (all 3 new `tests/test_gold_review_tool.py` cases pass; the 2 failures remain the pre-existing `140 == 100` count checks on `data/eval/gold_set.jsonl`).
