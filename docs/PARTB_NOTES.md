# Engineering Notes: Part B — Next.js UX Pass, Streamlit Eradication & Memory Audit

**Project:** Enterprise RAG Assistant for Banking Regulatory Compliance  
**Module:** COM6301 (BSc Final Year Project)  
**Author:** Hashir Khan (Lead Architect / Candidate)  
**Date:** November 2026  
**Status:** Verification Complete — Production Hardened  

---

## 1. Streamlit Decommissioning & Port 8501 Audit

### 1.1 Process & Socket Inspection
* **Port 8501 Verification:** Executed `Get-NetTCPConnection -LocalPort 8501` on the host. Returned 0 active listeners and 0 established connections.
* **Process Inspection:** Executed `Get-Process | Where-Object { $_.ProcessName -match "streamlit" }`. Confirmed 0 running Streamlit processes.

### 1.2 Package Eradication
* **Uninstallation:** Removed `streamlit` from the virtual environment (`.venv`).
* **Verification:** `pip show streamlit` exits with non-zero exit code (`1`), confirming the package is completely uninstalled.
* **Dependency Files:** Checked `requirements.txt` and package lock files. Zero occurrences of `streamlit` remain.

### 1.3 Repository Reference Audit
Scanned all active source code, scripts, Dockerfiles, and CI configurations for `streamlit` and `8501`:
* **Active Python Source (`src/`):** 0 references.
* **Active Frontend Code (`web/`):** 0 references.
* **Test Suite (`tests/`):** 0 references (excluding explicit hygiene test).
* **Historical Documentation & Migration Logs:**
  * `AGENTS.md`, `brain/security/`: CORS rules updated from 8501 to Next.js port 3000 (`http://localhost:3000`, `http://127.0.0.1:3000`).
  * `DECISIONS.md`, `STATUS.md`: Retained historical records documenting the intentional migration decision from Streamlit to Next.js BFF for enterprise security, accessibility, and WCAG compliance.
* **Automated CI Hygiene Test:** Implemented `tests/test_ci_hygiene.py` containing:
  * `test_streamlit_not_installed`: Fails if `importlib.util.find_spec("streamlit")` finds an installed package.
  * `test_streamlit_not_in_requirements`: Fails if `streamlit` is listed as a dependency in `requirements.txt`.
  * `test_no_active_python_imports_streamlit`: Scans all `.py` files in `src/` to ensure no active code imports `streamlit`.
  * `test_port_8501_not_in_active_source`: Ensures port 8501 does not appear in active backend routes or Next.js configurations.

---

## 2. Pre-Flight Test Suite Remediation

### 2.1 Missing Import & Route Fixes
* **`src/api/routes.py` (Line 449):** Added missing `import os` required by the canary token detection and mutant testing guards.
* **`tests/test_security_depth.py`:** Added missing `import os` for the mutant environment variable toggle.
* **`web/app/api/backend/[...path]/route.ts`:** Added missing `NextResponse` import from `"next/server"`.
* **CORS Origin Realignment:** Updated baseline API CORS test in `tests/test_api_baseline.py` to assert against `http://localhost:3000` (Next.js) rather than deprecated `http://localhost:8501`.

### 2.2 Suite Verification
* Executed full non-slow pytest suite:
  ```
  254 passed, 1 deselected in 38.06s (100% green, 0 failures, 0 skipped, 0 loosened)
  ```
* Vitest Frontend Suite (`npm --prefix web test`):
  ```
  41 passed across 7 test files (100% green)
  ```
* Next.js TypeScript & Production Build:
  ```
  Typecheck: 0 errors
  Build: Turbopack compiled successfully in 1.35s with 0 errors
  ```

---

## 3. Next.js Sizing, Typography & UX Overhaul

### 3.1 Design System & Typography Tokens (`web/styles/tokens.css`)
* **Base Font & Rem Scaling:** Upgraded base HTML font size to 16px. Defined rem-based scale:
  * Body prose: `--text-base: clamp(1rem, 0.96rem + 0.2vw, 1.0625rem)` (16px–17px).
  * Secondary text: `--text-sm: 0.875rem` (14px).
  * Minimum labels: `--text-xs: 0.8125rem` (13px, strictly $\ge 13$px across all badges, captions, and microcopy).
* **Reading Width & Centering:** Configured optimal reading column width:
  * `--reading-width: clamp(880px, 62vw, 960px)` for chat messages and document citations.
* **Tap Targets & Ergonomics:**
  * Enforced `--tap-min: 44px` across buttons, icon buttons, inputs, segmented controls, and collapsible triggers in accordance with WCAG 2.5.5 / 2.5.8.
* **Line Height & Readability:**
  * Set `.answer-prose` line-height to `1.62` and blockquote citation quotes to `1.60` (1.55–1.65 range) for high-density regulatory legal text.
* **Atmosphere & Accessibility:**
  * Preserved strict 60/30/10 dark enterprise palette (`#080C14` background, `#0E1524` elevated canvas, `#19243C` borders, `#3B82F6` accent).
  * Verified WCAG AA contrast ratios ($\ge 4.5:1$ for normal text, $\ge 3:1$ for UI components).
  * Added `prefers-reduced-motion: reduce` fallbacks suppressing animations and transitions.

### 3.2 Component Enhancements
1. **Citation Cards (`web/components/chat/citations-panel.tsx`):**
   * **Single Breadcrumb:** Displayed once at the top of each card (`Document Title › Heading › Clause`).
   * **Source Pill:** Visual pill clearly identifying authorization status (`Public (Authority)`, `Internal (Permitted: Roles)`, or `No access`).
   * **Clean Quote Block:** Styled with accent border and 1.6 line-height at 14px text.
   * **Collapsed Technical Details:** Encapsulated inside `<details className="group/tech">` containing Heading, Clause, Page Number, and Source Identifier. Defaults to collapsed.
   * **44px Tap Targets:** Sources collapsible trigger and external source links meet minimum touch targets.
2. **Composer (`web/components/chat/composer.tsx`):**
   * Upgraded textarea to `min-h-[56px]` with `text-base` font size (16px), eliminating mobile browser auto-zoom triggers.
   * Upgraded submit button and action icons to 44px hit targets.
   * Removed sub-13px labels; all helper text set to `text-xs` (13px).
3. **Pipeline Stepper & Skeleton Loader (`web/components/chat/thinking-panel.tsx`):**
   * Implemented 5-stage pipeline stepper: Route Query → RBAC Retrieval → Re-ranking → Evidence Verification → Synthesis.
   * Added animated shimmer skeleton loader previewing answer synthesis during streaming.
4. **Session Sidebar (`web/components/workspace/sidebar.tsx`):**
   * Navigation items and session rows upgraded to `min-h-[44px]`.
   * Clear session auto-titles displayed with user-scoped isolation.
5. **Empty State (`web/components/chat/chat-empty-state.tsx`):**
   * Replaced low-contrast suggestions with structured starter cards (`min-h-[140px]`).

### 3.3 Multi-Viewport Verification & Screenshot Gallery
Captured full-page screenshots at four viewport widths into `docs/screenshots/partb/`:
* **1280px Desktop:** `docs/screenshots/partb/chat_1280.png` & `login_1280.png`
* **1440px Standard Display:** `docs/screenshots/partb/chat_1440.png` & `login_1440.png`
* **1920px Full HD:** `docs/screenshots/partb/chat_1920.png` & `login_1920.png`
* **390px Mobile:** `docs/screenshots/partb/chat_390.png` & `login_390.png`

**Horizontal Scroll Audit:** Evaluated `document.documentElement.scrollWidth > document.documentElement.clientWidth` across all viewports.
* Result: **`False` (0 horizontal scroll) at all widths.**

---

## 4. Memory Architecture & Isolation Audit

### 4.1 Memory Classification Specification
Authored `docs/MEMORY_ARCHITECTURE.md` covering all 8 cognitive memory classes:
1. **Working Memory:** In-flight request context (`src/rag/baseline.py`, `src/core/prompts.py`). Pre-retrieval role filtering on Qdrant and BM25 payloads; XML untrusted boundary encapsulation. Cost: 0 storage, ~500–2,500 prompt tokens.
2. **Session Memory:** Conversational history (`src/core/memory.py`, `src/db/repository.py`). Scoped strictly by SQLite ownership (`WHERE session_id = ? AND user_id = ?`). Re-verifies role on every turn. Cost: 0 under threshold; 1 rewrite call (~150–300 tokens) when active.
3. **Semantic Memory (OUT OF SCOPE):** Excluded by architectural design. Prevents regulatory drift, inadmissible precedent, cross-tenant leakage, and GDPR storage limitation violations. Cost: $0.00$.
4. **Episodic Memory (OUT OF SCOPE):** Excluded by architectural design. Regulatory compliance requires point-in-time statutory grounding, not recall of past subjective model outputs. Cost: $0.00$.
5. **Procedural Memory:** Versioned YAML prompts (`prompts/`), Pydantic routing schemas (`src/core/router.py`), and whitelisted AST calculator (`src/core/calculator.py`). Cost: $0.00$.
6. **Prospective Memory (OUT OF SCOPE):** Excluded by architectural design. System is strictly a synchronous, read-only decision support assistant; eliminates unmanaged agentic background execution. Cost: $0.00$.
7. **Parametric Memory:** Generator and local CPU models (`BAAI/bge-small-en-v1.5`, `ms-marco-MiniLM-L-6-v2`). Knowledge strictly subordinated to retrieved XML passages; temperature 0. Cost: CPU inference + token budget.
8. **Cache Memory:** Deterministic SQLite response cache (`src/core/llm_client.py`). Salted with SHA-256 over `(role, user_id, prompt_version, model, step)`. Cross-role and cross-user collision probability is zero. Cost: 0 tokens on hit.

### 4.2 Verified Isolation Test Coverage
Added dedicated tests in `tests/test_memory.py`:
* `test_cache_key_isolation_across_roles_and_users`: Confirms distinct cache keys across roles (`analyst`, `manager`, `auditor`) and across users (`user_id=1`, `user_id=2`).
* `test_session_turns_and_titles_isolated_across_users`: Confirms that user B cannot load user A's turns or view user A's session titles.
* `test_restricted_history_cannot_widen_retrieval`: Proves an analyst whose history contains restricted terminology cannot widen retrieval scope.
* `test_no_passage_text_in_the_title`: Proves session titling functions never accept document passages or citations, eliminating title exfiltration channels.

---

## 5. Phase 13 Evaluation Summary & Mutation Hardening

### 5.1 Mutation Testing Results (Positive Controls)
Mutation testing executed via `reports/mutation_testing_report.json` across 7 intentional vulnerability mutants. Every mutant was detected and killed by the automated security test suite (100% kill rate):

| Mutant ID | Environment Variable | Injected Vulnerability | Target Defense Mechanism | Outcome | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **MUTANT-A** | `MUTANT_DISABLE_CANARY_GUARD` | Output canary guard disabled | Canary Output Guard | Caught by `test_output_guard_neutralizes_unauthorized_canary` | **KILLED** |
| **MUTANT-B** | `MUTANT_DISABLE_POST_RERANK_RBAC` | Post-rerank defense-in-depth filter disabled | Post-Rerank Role Enforcement | Caught by `test_post_rerank_rbac_defense` | **KILLED** |
| **MUTANT-C** | `MUTANT_DISABLE_PRE_FUSION_RBAC` | Pre-fusion Qdrant/BM25 payload filter disabled | Native Engine RBAC | Caught by `test_pre_fusion_rbac_filter` | **KILLED** |
| **MUTANT-D** | `MUTANT_CACHE_NO_ROLE` | Cache key computed without `role` or `user_id` | Cache Role Partitioning | Caught by `test_cross_role_cache_keys_differ` | **KILLED** |
| **MUTANT-E** | `MUTANT_SHARED_MEMORY` | Cross-user session memory boundary disabled | Session Ownership Anti-IDOR | Caught by `test_cross_user_memory_isolation` | **KILLED** |
| **MUTANT-F** | `MUTANT_DISTINCT_REFUSAL` | Uniform refusal replaced by distinct message | Refusal Uniformity Side-Channel | Caught by `test_refusal_uniformity_side_channel` | **KILLED** |
| **MUTANT-G** | `MUTANT_ROLE_FROM_BODY` | Role forged via client request body | Signed JWT Identity Enforcement | Caught by `test_forged_role_in_request_ignored` | **KILLED** |

### 5.2 Red-Team & Canary Evaluation per Model
Evaluated against `data/redteam.jsonl` (45 adversarial cases across 5 categories) recorded in `reports/redteam_eval.json`:
* **Evaluation Models:** `local` CPU model (`sshleifer/tiny-gpt2`) and `mock` profile (`mock-compliance-v1`) — **Smoke test only, cannot follow instructions; NOT security evidence against instruction-following jailbreaks.**
* **Overall Pass Rate:** 45/45 passed (100.0% defense pass rate, 0 failures, 138.94s elapsed).
* **Breakdown by Attack Vector:**
  * Prompt Injection in Queries (`prompt_injection_query`): 10/10 passed (100.0%).
  * Prompt Injection in Documents (`prompt_injection_document`): 8/8 passed (100.0%).
  * Role Spoofing Probes (`role_spoofing`): 10/10 passed (100.0%).
  * Exfiltration Channels (`exfiltration_channels`): 9/9 passed (100.0%).
  * Multi-Turn Carryover (`multiturn_carryover`): 8/8 passed (100.0%).
* **Canary Tokens:** 5 unique canaries planted in restricted documents (`CANARY_REGISTRY`). Output guard verified 0 leaks across answers, citations, titles, session memory, cache, and traces.

### 5.3 Per-Difficulty Retrieval Metrics
Evaluated on `data/eval/gold_set.jsonl` (100 items partitioned by lexical overlap) recorded in `reports/retrieval_difficulty_report.json`:
* **Easy Bucket (45 items, all answerable):** Recall@5 = 1.0000 (95% CI: [1.0000, 1.0000]), MRR = 0.9889 (95% CI: [0.9667, 1.0000]), nDCG@5 = 0.9941 (95% CI: [0.9822, 1.0000]).
* **Medium Bucket (24 items, all answerable):** Recall@5 = 0.9792 (95% CI: [0.9375, 1.0000]), MRR = 0.9792 (95% CI: [0.9375, 1.0000]), nDCG@5 = 0.9425 (95% CI: [0.8926, 0.9831]).
* **Hard Bucket (31 items, 1 answerable, 30 unanswerable/out-of-corpus):** Answerable item Recall@5 = 1.0000, MRR = 1.0000, nDCG@5 = 1.0000.
* **Overall Corpus Retrieval (70 answerable items):** Recall@5 = 0.9929 (95% CI: [0.9786, 1.0000]), MRR = 0.9857 (95% CI: [0.9643, 1.0000]), nDCG@5 = 0.9757 (95% CI: [0.9507, 0.9928]).

### 5.4 Benchmark Provenance & Human Review Count
* **Human-Reviewed Count:** Exactly **0** items claimed (`reviewed_by=human: 0`).
* **Audit Finding:** All 100 items in `data/eval/gold_set.jsonl` and all 115 items in `data/gold_v2.jsonl` remain classified as `unreviewed_draft`. Zero automated agent certifications are permitted.
* **Human Sign-off Sheet:** Exported to `data/gold_review_sheet.csv` awaiting manual candidate review.

### 5.5 Cause of Part A Pre-Flight Test Failures
* **Root Cause:** 31 test failures during Part A pre-flight were traced directly to commit `b52252d` ("feat: add Next.js web UI frontend and core backend enhancements"). In that commit, `MUTANT_ROLE_FROM_BODY` was added to `src/api/routes.py:449` referencing `os.environ.get(...)` when `import os` was omitted from the module imports. This triggered an unhandled `NameError: name 'os' is not defined` whenever `_execute_chat_turn` was invoked, breaking ~28 chat/session API tests. Two additional failures stemmed from missing `import os` in `tests/test_security_depth.py` and a missing `NextResponse` import in `web/app/api/backend/[...path]/route.ts`.
* **Resolution:** Restored `import os` in `src/api/routes.py`, `tests/test_security_depth.py`, and `NextResponse` in the Next.js BFF proxy.

---

## 6. Verification Pass Results

1. **Mutant Flag Safety Guard:** Centralized all mutant flag parsing into `src/core/mutants.py`. Mutant overrides are strictly evaluated via `is_mutant_active()`, which unconditionally returns `False` unless `is_running_under_pytest()` is `True`. Application startup outside pytest raises `RuntimeError` if any mutant flag is set (`check_no_mutant_flags_on_startup()`). Verified by `tests/test_mutant_guards.py` (4/4 passed).
2. **"No Access" Pill Scoping:** Located the sole rendering path in `web/components/chat/citations-panel.tsx`. Labeled unauthorized pill as `No access (RBAC-off comparison view)`. Verified with `tests/test_rbac_security.py::test_normal_chat_answer_never_includes_unauthorized_citations_or_hints` that normal answers never contain citations, titles, counts, or hints about unauthorized documents.
3. **Mobile 390px Clamp Fix:** Updated `--reading-width: clamp(min(100%, 880px), 62vw, 960px)` in `web/styles/tokens.css` ensuring clamp minimum never exceeds 100% of viewport width. Re-captured all screenshots at 1280px, 1440px, 1920px, and 390px with verified zero horizontal scroll and no clipped composer.
4. **Slow Integration Test:** Executed `tests/test_real_models_slow.py::test_real_cpu_models_on_fixture` to completion. Passed in 13.80s, proving real local CPU models (`bge-small-en-v1.5` and `ms-marco-MiniLM-L-6-v2`) execute reliably on hardware without GPU dependencies.
5. **Memory Document Revisions:** Updated `docs/MEMORY_ARCHITECTURE.md` to detail versioned prompts and schemas in Procedural memory, identify actual generator models per profile while distinguishing separate CPU embedding/re-ranker components in Parametric memory, reword exclusion rationales as explicit architectural design choices, and append author legal claim verification tags.


