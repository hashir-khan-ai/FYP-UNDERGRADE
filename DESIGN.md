# Design Specification — Enterprise Banking Regulatory Compliance RAG Assistant

> **Status: Historical.** The Streamlit client has been retired in favor of the Next.js client ("Compliance Desk"). For active UI specifications, design tokens, and components, see [docs/WEB_UI_DESIGN_SYSTEM.md](docs/WEB_UI_DESIGN_SYSTEM.md).

**Module:** COM6301 (BSc Final Year Project)  
**Phase:** 8 — Integrity, Citation Redesign, Stretch Panels & UI Polish  
**Status:** Authoritative UI & Accessibility Contract  

---

## 1. Visual Identity & 60 / 30 / 10 Colour System

The interface follows a high-contrast dark institutional compliance aesthetic governed by a strict **60 / 30 / 10** colour distribution:

| Proportion | Role | Name | Hex Code | Usage |
| :--- | :--- | :--- | :--- | :--- |
| **60% (Primary Surface)** | Background & Canvas | **Matte Black** | `#1C1D20` | Main viewport background, primary workspace canvas, primary action button text (`#1C1D20` on `#FF5F00`). |
| **30% (Secondary Structure)** | Panels, Cards & Chrome | **Storm Grey** | `#26292E` / `#5A6068` | Sidebar surface (`#26292E` cards, `#5A6068` hairline borders & secondary chrome), citation cards, session list items, pipeline stepper, reasoning trace container, table headers. |
| **10% (Interactive Accent)** | Primary Actions & Highlights | **Safety Orange** | `#FF5F00` | Primary submit/login buttons (`#1C1D20` label text), active session indicator, citation index badges/jump markers, focus rings, active 3D layer cards, and role badge accents. |
| **Typography** | Primary Foreground Text | **Polar White** | `#F1F3F4` | All body copy, chat messages, headings, input text, and table values (`-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", sans-serif`; no network fonts). |

### Semantic Status Colours & Inline SVG Icons
- **Iconography:** All UI icons use a consistent inline `<svg>` icon helper (`get_svg_icon` in `src/ui/app.py`) — zero OS/browser emoji characters and zero external icon/font CDNs.
- **Refusal / Insufficient Evidence Banner:** `#FF5F00` left accent border on `#26292E` card with explicit compliance refusal SVG icon and uniform non-leaking refusal message.
- **Error Boundary Banner:** `#E5484D` border on `#2A1C1E` surface with sanitized user-friendly message and retry guidance.
- **Profile Badge:**
  - `mock`: Storm Grey pill with Safety Orange border (`#FF5F00`) and warning SVG icon (`OFFLINE MOCK · model`) to conspicuously denote evaluation/synthetic mode.
  - `dev`: Storm Grey pill with Safety Orange border (`#FF5F00`) and warning SVG icon (`DEV PROVIDER · model`) to denote local/development mode.
  - `demo`: Safety Orange solid pill (`#FF5F00`) with Matte Black text (`DEMO LIVE · model`) to denote live paid demonstration mode.
- **Security Invariant:** Never display API keys, authorization headers, or user passwords in profile badges or UI telemetry.

---

## 2. Screens & Information Architecture

### 2.1 Login Screen
- **Purpose:** Authenticate synthetic compliance users (`analyst_user`, `manager_user`, `auditor_user`) via `POST /api/v1/auth/login`.
- **Elements:**
  - Application header with system title, active LLM profile badge (`mock` / `dev` / `demo`), indexed chunk count, and RBAC status pill.
  - Username and Password inputs with explicit visible labels and `#FF5F00` focus outlines.
  - Primary **Sign In** button (`#FF5F00` fill, `#1C1D20` text).
  - **Quick-Fill Synthetic Persona Helper:** Rendered strictly only when `DEMO_MODE=true`.
  - **Leakage Verification Status:** Reads the latest `reports/leakage_*.json` metric and ISO timestamp dynamically (`measured 0.00% leakage (<timestamp>)`), or shows `not yet measured` if no report exists.
- **Security Invariant:** The bearer token is stored exclusively in `st.session_state["access_token"]` in memory; it is never written to URL query parameters, browser local storage, or disk. The active role is always read from the server response (`GET /api/v1/auth/me` / login payload), never from a client-side role selector.

### 2.2 Session List & Settings Sidebar
- **Identity Header:** Displays authenticated user's full name, username, server-verified role badge (`ROLE: ANALYST`, `ROLE: MANAGER`, or `ROLE: AUDITOR`), active LLM profile badge, and **Sign Out** button (`POST /api/v1/auth/logout`).
- **Navigation Mode Switch:**
  - **Compliance Chat** (all roles)
  - **Auditor Summary & RBAC Logs** (rendered only when server-verified role is `auditor`).
- **Session Controls:**
  - **+ New Session** button (`POST /api/v1/sessions`)
  - Ordered list of the user's sessions (`GET /api/v1/sessions`) with one-click open and delete (`×`, `DELETE /api/v1/sessions/{id}`) actions, plus collapsed **2-Min Demo Showcase (Viva)** and role-gated **Ingest Regulatory Document** expanders.
- **Settings & System Profile Panel (`System Profile & Run Budget`):**
  - Read-only telemetry synced with the exact runtime configuration (`GET /api/v1/admin/config` + per-turn `active_layers` overrides):
    - Active Profile, Model, and Prompt Version (`v1`)
    - Exact active architecture layers (`adaptive_router`, `corrective_grader`, `rbac`, `memory`, `xai_output`, `heading_path`, `claim_check`, `calculator`) mirrored in a stacked CSS 3D visual card indicator (`.layer-stack-3d`)
    - Profile-aware Spend Guard status: `offline-mock (unmetered)` labelling token counts as `estimated tokens`, `local-dev (safety ceiling)`, or `live` per-query + session cap with an interactive **Reset budget** action (`POST /api/v1/sessions/{id}/new-run`).

### 2.3 Compliance Chat View
- **Conversation Stream:** Displays prior turns for the active session (`GET /api/v1/sessions/{id}/messages`) and new turns submitted via `POST /api/v1/chat/query`, with dual selectors for **Knowledge Scope** (`Auto`, `Company Docs`, `General Chat`) and **Response Style** (`Strict Compliance`, `Explain & Discuss`).
- **Assistant Response Structure:**
  1. **Answer Card:** Grounded regulatory answer in Polar White `#F1F3F4` with clickable/hoverable inline `[1]`, `[2]` citation markers that expand, scroll to, and pulse the matching citation card; or a visually distinct **Refusal Card** when refused.
  2. **Live 5-Stage Pipeline Stepper:** Pure-CSS animated stage tracker (`Route > Retrieve > Re-rank > Grade > Answer`) displaying active stage latencies (ms) and dimmed `skipped` badges for bypassed or disabled layers.
  3. **Authoritative Citations Panel (`Sources & citations (N)`):** Human-friendly cards ordered cleanly:
     - **Title line:** `[index]` badge + human document title (`doc_title`).
     - **Single Breadcrumb line:** Clean deduplicated `heading_path` without raw markdown `#` markers or backticks.
     - **Source Pill:** `Public · verifiable` with clickable verification links (`Open Source`, `Verify on Google`) for public documents, OR a lock SVG icon + `Internal · visible to <Roles>` read from chunk `allowed_roles` for internal policies (never emitting "no verification link" text or external links).
     - **Verbatim Quote Blockquote:** Escaped clause text with HTML tags/markdown markers stripped and the query-matched sentence highlighted.
     - **Technical Details Expander:** Collapsed `<details>` holding `Doc ID`, `Page`, `Chunk ID`, and a **Copy** action.
     - **Motion:** Cards enter with short staggered `citeCardEnter` motion and subtle CSS 3D hover tilt (`perspective(900px) rotateX(2.5deg) rotateY(-4deg)`).
  4. **XAI Stretch Panels & Trace (`xai_output=true` only):** When `xai_output` is disabled, neither the reasoning trace nor XAI-only panels (`claim_check` per-claim support statuses, deterministic AST `calculator` formula/citations/result) are rendered.

### 2.4 Auditor Summary View (`auditor` Role Only)
- **Purpose:** Inspect system-wide compliance audit summaries (`GET /api/v1/audit/logs`) without exposing private conversation text (`query_text` and `response_text` are omitted by the server).
- **Elements:**
  - Filter controls (`limit`, optional `user_id` filter).
  - KPI Summary Strip: Total audited queries, zero-leakage RBAC status (`0.00%`), total citations verified, total invalid citations dropped, and cache hit ratio.
  - Tabular summary of audit records (`audit_id`, `created_at`, `user_role`, `final_route`, `retrieved_chunk_ids`, `citation_count`, `citations_dropped`, `heading_path_enabled`, `latency_ms`, `llm_profile`).

---

## 3. UI States

1. **Loading State:** Animated typing/shimmer skeleton placeholder (`.typing-skeleton`) inside a polite `aria-live="polite"` status card while verifying permissions, retrieving clauses, and validating citations.
2. **Empty State:** Structured hero banner (`bank` SVG icon), pure inline-SVG compliance flow diagram (`RAG_TOPOLOGY_CANVAS_HTML`, zero `<canvas>` or WebGL), and role-scoped starter question cards with wrapping action buttons.
3. **Refusal State:** Distinct bordered alert card (`#FF5F00` left accent) clearly distinguishing an evidence/scope refusal from a system error, showing the uniform refusal message and `refusal_category` badge (`insufficient_evidence`, `no_permitted_passages`, `out_of_scope`) with zero leaked metadata.
4. **Error State:** Sanitized alert banner (`401` session expired, `403` forbidden, `429` rate/spend limit, `503` provider offline) mapping API error codes to actionable guidance without stack traces or internal file paths.

---

## 4. Layout & Accessibility Rules

1. **Contrast & Readability:**
   - Polar White (`#F1F3F4`) on Matte Black (`#1C1D20`) achieves a contrast ratio $> 14:1$ (exceeding WCAG AAA).
   - Matte Black (`#1C1D20`) text on Safety Orange (`#FF5F00`) primary buttons achieves $> 6.5:1$ contrast (WCAG AA compliant for normal text and AAA for large/bold text).
2. **Keyboard, Motion & Screen-Reader Accessibility:**
   - Every form input has an explicit non-empty label, visible `#FF5F00` focus-visible rings on selects/inputs/buttons, and multi-line wrapping on starter/demo/follow-up buttons (`white-space: normal; word-break: break-word`).
   - All CSS animations (stepper sequence, citation stagger/pulse, typing skeleton shimmer, sidebar transitions) and 3D transforms (`perspective(...) rotateX(...) rotateY(...)`, `.layer-stack-3d`) include `@media (prefers-reduced-motion: reduce)` overrides disabling motion and flattening transforms cleanly.
   - Zero WebGL, zero heavy JS libraries, zero external fonts, and zero external CDNs.
3. **Strict Architectural Boundary:**
   - The UI layer (`src/ui/app.py`) communicates with the backend exclusively through `src/ui/api_client.py` over HTTP (`localhost`). It never imports `src.db`, `src.rag`, `src.core.llm_client`, or Qdrant directly (except reading `settings.DEMO_MODE` / local `reports/leakage_*.json` telemetry on login).

