# Design Specification — Enterprise Banking Regulatory Compliance RAG Assistant

**Module:** COM6301 (BSc Final Year Project)  
**Phase:** 6B — Streamlit Explainable User Interface  
**Status:** Authoritative UI & Accessibility Contract  

---

## 1. Visual Identity & 60 / 30 / 10 Colour System

The interface follows a high-contrast dark institutional compliance aesthetic governed by a strict **60 / 30 / 10** colour distribution:

| Proportion | Role | Name | Hex Code | Usage |
| :--- | :--- | :--- | :--- | :--- |
| **60% (Primary Surface)** | Background & Canvas | **Matte Black** | `#1C1D20` | Main viewport background, primary workspace canvas, primary action button text (`#1C1D20` on `#FF5F00`). |
| **30% (Secondary Structure)** | Panels, Cards & Chrome | **Storm Grey** | `#5A6068` | Sidebar surface (`#26292E` / `#5A6068` borders & surfaces), citation cards, session list items, reasoning trace container, table headers, muted metadata dividers. |
| **10% (Interactive Accent)** | Primary Actions & Highlights | **Safety Orange** | `#FF5F00` | Primary submit/login buttons (with Matte Black `#1C1D20` label text), active session indicator, citation badge pills, focus rings, and role badge accents. |
| **Typography** | Primary Foreground Text | **Polar White** | `#F1F3F4` | All body copy, chat messages, headings, input text, and table values. |

### Semantic Status Colours
- **Refusal / Insufficient Evidence Banner:** `#FF5F00` border on `#26292E` card with explicit compliance refusal icon and uniform message.
- **Error Boundary Banner:** `#E5484D` border on `#2A1C1E` surface with sanitized user-friendly message and retry guidance.
- **Profile Badge:**
  - `mock`: Storm Grey pill (`#5A6068`) with Polar White text (`OFFLINE MOCK`)
  - `dev`: Safety Orange outline pill (`#FF5F00`) (`DEV PROVIDER`)
  - `demo`: Safety Orange solid pill (`#FF5F00`) with Matte Black text (`DEMO LIVE`)

---

## 2. Screens & Information Architecture

### 2.1 Login Screen
- **Purpose:** Authenticate synthetic compliance users (`analyst_user`, `manager_user`, `auditor_user`) via `POST /api/v1/auth/login`.
- **Elements:**
  - Application header with system title, active LLM profile badge (`mock` / `dev` / `demo`), and local dev user quick-fill helper (enabled only when `GET /api/v1/auth/users` is permitted in development/test).
  - Username and Password inputs with explicit visible labels.
  - Primary **Sign In** button (`#FF5F00` fill, `#1C1D20` text).
- **Security Invariant:** The bearer token is stored exclusively in `st.session_state["access_token"]` in memory; it is never written to URL query parameters, browser local storage, or disk. The active role is always read from the server response (`GET /api/v1/auth/me` / login payload), never from a client-side role selector.

### 2.2 Session List & Settings Sidebar
- **Identity Header:** Displays authenticated user's full name, username, and a prominent server-verified role badge (`ANALYST`, `MANAGER`, or `AUDITOR`), plus **Sign Out** button (`POST /api/v1/auth/logout`).
- **Navigation Mode Switch:**
  - **Compliance Chat** (all roles)
  - **Auditor Summary & RBAC Verification** (rendered only when server-verified role is `auditor`).
- **Session Controls:**
  - **New Session** button (`POST /api/v1/sessions`)
  - Ordered list of the user's sessions (`GET /api/v1/sessions`) with one-click **Open** and **Delete** (`DELETE /api/v1/sessions/{id}`) actions.
- **Settings & System Status Panel:**
  - Read-only telemetry fetched from `GET /api/v1/admin/config` and `GET /api/v1/admin/health`:
    - Active Profile badge (`mock` / `dev` / `demo`) & Model name
    - Prompt Version (`v1`)
    - Active Architecture Layers (`RBAC`, `Memory`, `Adaptive Router`, `Corrective Grader`, `XAI Output`, `Heading Path`)
    - Spend Guard usage & caps (`calls_limit`, `tokens_limit`).

### 2.3 Compliance Chat View
- **Conversation Stream:** Displays prior turns for the active session (`GET /api/v1/sessions/{id}/messages`) and new turns submitted via `POST /api/v1/chat/query`.
- **Assistant Response Structure:**
  1. **Answer Card:** Grounded regulatory answer rendered in Polar White `#F1F3F4`, or a visually distinct **Refusal Card** when the query is refused (`refusal_category` is set or uniform refusal wording is returned).
  2. **Route & Grader Metadata Bar:** Compact pill bar showing `route`, `grader_path`, `latency_ms`, and `citations_dropped` (if any).
  3. **Authoritative Citations Panel:** Structured cards for each verified citation displaying:
     - Document Title (`doc_title`) & Clause (`clause`)
     - Structure-aware Heading Path (`heading_path`, e.g., `Part 4 > 4.2 > 4.2.3`) and Page number (`page`)
     - Verbatim Quote Snippet (`quote_snippet`, $\le 200$ chars) inside a monospace/bordered block.
  4. **Expandable Safe Reasoning Trace:** Collapsible `st.expander("Reasoning Trace & Verification Steps")` listing the ordered 6-step server trace without prompts, dropped passage text, or restricted document counts.

### 2.4 Auditor Summary View (`auditor` Role Only)
- **Purpose:** Inspect system-wide compliance audit summaries (`GET /api/v1/audit/logs`) without exposing private conversation text (`query_text` and `response_text` are omitted by the server).
- **Elements:**
  - Filter controls (`limit`, optional `user_id` filter).
  - KPI Summary Strip: Total audited queries, zero-leakage RBAC status (`0.00%`), total citations verified, total invalid citations dropped, and cache hit ratio.
  - Tabular summary of audit records (`audit_id`, `created_at`, `user_role`, `final_route`, `retrieved_chunk_ids`, `citation_count`, `citations_dropped`, `heading_path_enabled`, `latency_ms`, `llm_profile`).

---

## 3. UI States

1. **Loading State:** Explicit spinner (`st.spinner("Verifying role permissions, retrieving clauses, and validating citations...")`) during API calls so the user has clear visual feedback.
2. **Empty State:** When a session has no messages yet, displays a structured onboarding card explaining role-scoped regulatory search and offering three clickable example compliance questions appropriate for the user's role.
3. **Refusal State:** Distinct bordered alert card (`#FF5F00` left accent) clearly distinguishing an evidence/scope refusal from a system error, showing the uniform refusal message and `refusal_category` badge (`insufficient_evidence`, `no_permitted_passages`, `out_of_scope`) with zero leaked metadata.
4. **Error State:** Sanitized alert banner (`401` session expired, `403` forbidden, `429` rate/spend limit, `503` provider offline) mapping API error codes to actionable guidance without stack traces or internal file paths.

---

## 4. Layout & Accessibility Rules

1. **Contrast & Readability:**
   - Polar White (`#F1F3F4`) on Matte Black (`#1C1D20`) achieves a contrast ratio $> 14:1$ (exceeding WCAG AAA).
   - Matte Black (`#1C1D20`) text on Safety Orange (`#FF5F00`) primary buttons achieves $> 6.5:1$ contrast (WCAG AA compliant for normal text and AAA for large/bold text).
2. **Keyboard & Screen-Reader Accessibility:**
   - Every form input (`username`, `password`, `session title`, `chat query`, `audit filters`) has an explicit non-empty label.
   - Status states (Refusal, Error, Role Badge, Profile Badge) use both text labels and iconography rather than colour alone.
3. **Strict Architectural Boundary:**
   - The UI layer (`src/ui/app.py`) communicates with the backend exclusively through `src/ui/api_client.py` over HTTP (`localhost`). It never imports `src.db`, `src.rag`, `src.core.llm_client`, or Qdrant directly.

