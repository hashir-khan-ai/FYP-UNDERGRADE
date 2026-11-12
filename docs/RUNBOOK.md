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

### 2.2 Frontend UI (Streamlit)
```bash
# In active virtual environment:
.\.venv\Scripts\streamlit.exe run src/ui/app.py --server.port 8501
```
- Web Application: `http://localhost:8501`

---

## 3. UI Navigation & Response Modes

### 3.1 Synthetic Persona Quick-Fill
On the login screen, click one of the 1-click synthetic accounts:
- **Analyst Tier** (`analyst_user`): Permitted only to public statutory regulations (Basel III, FCA Handbook, PRA Rulebook, UK GDPR). Cannot retrieve internal policies or audit findings.
- **Manager Tier** (`manager_user`): Permitted to public regulations PLUS internal policies (e.g. `POL-042`).
- **Auditor Tier** (`auditor_user`): Complete access including confidential audit findings (`AUD-2025-01`), plus exclusive access to the **Auditor Compliance & RBAC Summary View**.

### 3.2 Response Modes
- **🛡️ Strict Compliance:** Generates concise, formal compliance answers with strict statutory grounding and clause citations.
- **💬 Explain & Discuss:** Conversational AI overview style designed for policy comprehension. Translates dense clauses into plain language, explains rationale, and supports conversational follow-up questions while strictly preserving grounding and server-side RBAC filters.

### 3.3 Collapsed Citations & Reasoning Trace
Citations are grouped cleanly beneath each assistant response under:
`Sources & citations (N)` (collapsed by default).
Clicking the expander reveals full heading paths, clause identifiers, page numbers, and verbatim source snippets.

---

## 4. Verification Commands

Run the test suite and security audit:
```powershell
# 1. Leakage verification (strictly 0.00% across all 36 test cells):
$env:HF_HUB_OFFLINE="1"
.\.venv\Scripts\python.exe scripts/leakage_check.py

# 2. Automated test suite:
.\.venv\Scripts\python.exe -m pytest -q -m "not slow" -x

# 3. Streamlit UI automated test suite:
.\.venv\Scripts\python.exe -m pytest tests/test_ui_app.py -v
```
