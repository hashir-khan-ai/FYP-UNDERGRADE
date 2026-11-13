# Operational Runbook: Enterprise Banking Regulatory Compliance Assistant

**Target Audience:** Operators, Evaluators, Examiners, Final-Year Project Mentors  
**Status:** Feature Complete & Production Hardened  

---

## 1. Quick Start ($0 Local Execution Mode)

The system supports a 100% free, local-first stack with **zero external API calls**:
- **Embeddings:** `BAAI/bge-small-en-v1.5` on local CPU (~130MB RAM).
- **Cross-Encoder Re-ranking:** `cross-encoder/ms-marco-MiniLM-L-6-v2` on local CPU (~80MB RAM).
- **Vector Database:** Local embedded Qdrant (`./data/qdrant`).
- **Relational DB:** Local SQLite (`./data/compliance.db`).
- **Generation LLM:** Local Ollama (`llama3.1:8b` or `qwen2.5:7b-instruct`).

### 1.1 Running with Local Ollama ($0 Cost)
1. Install Ollama from [https://ollama.ai](https://ollama.ai).
2. Start the local model in terminal:
   ```bash
   ollama run llama3.1:8b
   ```
   *(Alternatively: `ollama run qwen2.5:7b-instruct`)*
3. In `.env`, configure:
   ```ini
   LLM_PROFILE=dev
   LLM_BASE_URL=http://localhost:11434/v1
   LLM_API_KEY=ollama
   LLM_MODEL=llama3.1:8b
   ```

### 1.2 Running Fully Offline with Mock Profile (Testing Mode)
For automated testing and zero-quota deterministic evaluation:
```ini
LLM_PROFILE=mock
```

---

## 2. Starting the Services

### 2.1 Backend API (FastAPI)
```bash
# In active virtual environment:
.\.venv\Scripts\uvicorn.exe src.main:app --host 127.0.0.1 --port 8000
```
- Health Check: `http://127.0.0.1:8000/health`
- OpenAPI Docs: `http://127.0.0.1:8000/docs`

### 2.2 Frontend Web Client (Compliance Desk)
```bash
cd web
npm run dev
```
- Web Application: `http://localhost:3000`

---

## 3. UI Navigation & Response Modes

### 3.1 Synthetic Persona Quick-Fill
On the login screen, click one of the 1-click synthetic accounts:
- **Analyst Tier** (`analyst_user`): Permitted only to public statutory regulations (Basel III, FCA Handbook, PRA Rulebook, UK GDPR). Cannot retrieve internal policies or audit findings.
- **Manager Tier** (`manager_user`): Permitted to public regulations PLUS internal policies (e.g. `POL-042`).
- **Auditor Tier** (`auditor_user`): Complete access including confidential audit findings (`AUD-2025-01`), plus exclusive access to the **Auditor Compliance & RBAC Summary View**.

### 3.2 Knowledge Scope & Intent Routing
- **⚡ Auto (Smart Intent):** Automatically detects whether an inquiry relates to banking regulations, system configuration, or general open knowledge. Neutralizes adversarial prompt injections deterministically with zero retrieval.
- **🏛️ Company Docs (RAG):** Strictly forces hybrid retrieval (Qdrant vector + BM25 keyword + Knowledge Graph cross-references) across authorized compliance documents under server-side RBAC filters with clause citations.
- **🌐 General Chat:** Direct conversational LLM response for open-domain concepts (machine learning, coding, business definitions, weather). Displayed with a clear visual notice: *(Note: Answered from general AI knowledge, not grounded in company documents.)* and zero citation clutter.

### 3.3 Response Styles
- **🛡️ Strict Compliance:** Generates concise, formal compliance answers with strict statutory grounding and clause citations.
- **💬 Explain & Discuss:** Conversational AI overview style designed for policy comprehension. Translates dense clauses into plain language, explains rationale, and supports conversational follow-up questions while strictly preserving grounding and server-side RBAC filters.

### 3.4 Collapsed Citations & Reasoning Trace
Citations are grouped cleanly beneath each assistant response under:
`Sources & citations (N)` (collapsed by default).
Clicking the expander reveals full heading paths, clause identifiers, page numbers, and verbatim source snippets. For non-grounded general chat and system info responses, source expanders and traces are completely hidden.

### 3.5 Dynamic Document Ingestion (Role-Gated)
Authenticated users in authorized roles (Manager & Auditor) can dynamically upload regulatory documents (`.md`, `.txt`, `.pdf`, `.html`) from the web client Documents view or API (`POST /api/v1/documents/upload`):
- Automatically parsed with `DocumentLoader` and chunked with `ClauseAwareChunker`.
- Indexed into Qdrant embedded vector store and BM25 index with assigned `allowed_roles` payload.
- Registered in SQLite metadata table.
- Immediately available for retrieval in the active or new sessions without server restart.

---

## 4. Verification Commands

Run the test suite and security audit:
```powershell
# 1. Leakage verification (strictly 0.00% across all 36 test cells):
$env:HF_HUB_OFFLINE="1"
.\.venv\Scripts\python.exe scripts/leakage_check.py

# 2. Automated test suite:
.\.venv\Scripts\python.exe -m pytest -q -m "not slow" -x
```

