# Phase 6B Manual UI Verification Checklist

**Project:** Enterprise RAG Assistant for Banking Regulatory Compliance (COM6301)  
**Target UI:** `src/ui/app.py` (Streamlit) + `src/api/main.py` (FastAPI)  

---

## 1. Startup Commands (Windows PowerShell)

1. **Terminal 1 — Start FastAPI Backend (Mock Profile Default):**
   ```powershell
   $env:HF_HUB_OFFLINE="1"; .\.venv\Scripts\python.exe -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
   ```
2. **Terminal 2 — Start Streamlit UI:**
   ```powershell
   .\.venv\Scripts\python.exe -m streamlit run src/ui/app.py --server.port 8501
   ```
3. Open `http://127.0.0.1:8501` in your browser.

---

## 2. Verification Steps

- [ ] **1. Theme & 60/30/10 Colour System:**
  - Verify primary background is Matte Black (`#1C1D20`), cards/sidebar use Storm Grey (`#26292E` / `#5A6068` borders), primary buttons use Safety Orange (`#FF5F00`) with Matte Black (`#1C1D20`) text, and body text is Polar White (`#F1F3F4`).
- [ ] **2. Login & Token Security:**
  - Sign in as `analyst_user`. Verify the URL bar contains **no** token or role query parameters.
  - Verify the sidebar displays `ROLE: ANALYST` and the active profile badge (`OFFLINE MOCK` / `DEV PROVIDER` / `DEMO LIVE`).
- [ ] **3. Session Lifecycle:**
  - Click **+ New Session**, enter a title, and verify it appears in the sidebar.
  - Switch between sessions and click `✕` to delete a session.
- [ ] **4. Grounded Answer, Citations Panel & Verbatim Snippets:**
  - Ask a permitted regulatory question (or click a starter question).
  - Verify the Citations Panel renders `chunk_id`, `doc_title`, `heading_path` (e.g., `Part 1 > ...`), `clause`, `page`, and a verbatim `quote_snippet` ($\le 200$ chars).
- [ ] **5. Expandable Safe Reasoning Trace:**
  - Expand **Reasoning Trace & Verification Steps** and verify it shows the 6 ordered steps without prompt text, dropped passage text, or restricted document counts.
- [ ] **6. Distinct Refusal State & RBAC Enforcement:**
  - As `analyst_user`, ask an auditor-only question (`"What did the internal audit conclude about control gaps in the KYC remediation plan?"`).
  - Verify the UI displays the bordered **COMPLIANCE REFUSAL** card with uniform refusal wording and zero restricted citations.
- [ ] **7. Auditor-Only Summary View:**
  - Sign out and sign in as `auditor_user`.
  - Switch **Workspace View** in the sidebar to **Auditor Summary & RBAC Logs**.
  - Verify KPI cards (`0.00%` RBAC Leakage Rate, Verified Citations, Dropped Invalid Citations) and the summary table load without exposing any user's `query_text` or `response_text`.

