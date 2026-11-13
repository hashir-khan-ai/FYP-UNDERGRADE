# Database Schema & Metadata Specification

**Project:** Enterprise RAG Assistant for Banking Regulatory Compliance  
**Module:** COM6301 (BSc Final Year Project)  
**Database Engine:** SQLite 3 (WAL mode) + Embedded Vector Store (Qdrant Payload)  
**Status:** Frozen Scope Baseline (Step 1 Architecture)  

---

## 1. Overview & Storage Strategy
The system uses a hybrid persistence strategy designed for local, zero-maintenance execution:
1. **SQLite (`./data/sqlite/app.db`):** Relational store for users, roles, chat sessions, message history, audit logs, per-call LLM metrics, and document catalog metadata.
2. **Embedded Vector Database (`./data/qdrant/`):** Dense vector index and chunk payload store, with server-side payload filtering matching the SQLite role specifications.
3. **LLM Response Cache (`llm_cache` table in `app.db`):** Deterministic LLM responses keyed by a SHA-256 hash of model + prompt + parameters (including profile and prompt version). Disposable at any time.

---

## 2. SQLite Relational Schema (DDL)

```sql
-- Enable foreign key enforcement and Write-Ahead Logging for concurrent reads
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ============================================================================
-- 1. ROLES TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,              -- 'analyst', 'manager', 'auditor'
    description TEXT NOT NULL,
    hierarchy_level INTEGER NOT NULL,      -- 10 = analyst, 20 = manager, 30 = auditor
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- 2. USERS TABLE (Synthetic Staff Directory)
-- ============================================================================
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,          -- 'analyst_user', 'manager_user', 'auditor_user'
    password_hash TEXT NOT NULL,           -- bcrypt / argon2 hash (local auth)
    role_id INTEGER NOT NULL,
    full_name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    is_active INTEGER DEFAULT 1,           -- 1 = true, 0 = false
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (role_id) REFERENCES roles (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_role_id ON users(role_id);

-- ============================================================================
-- 3. SESSIONS TABLE (Conversational Context Containers)
-- ============================================================================
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,                   -- UUIDv4 string
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT 'New Compliance Session',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_updated_at ON sessions(updated_at);

-- ============================================================================
-- 4. MESSAGES TABLE (Chat History for Memory Layer)
-- ============================================================================
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    sender TEXT NOT NULL CHECK(sender IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    route_used TEXT,                       -- 'DIRECT_REPLY', 'SINGLE_SEARCH', 'MULTI_PART_SPLIT'
    metadata_json TEXT,                    -- JSON object with latency, token counts, citations
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);

-- ============================================================================
-- 5. AUDIT_LOG TABLE (Immutable Compliance Audit Trail)
-- ============================================================================
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    user_role TEXT NOT NULL,               -- Snapshot of role at execution time
    query_text TEXT NOT NULL,
    final_route TEXT NOT NULL,             -- 'DIRECT_REPLY', 'SINGLE_SEARCH', 'MULTI_PART_SPLIT'
    retrieved_chunk_ids TEXT,              -- Comma-separated or JSON array of chunk IDs
    relevance_scores TEXT,                 -- JSON array of grader scores
    retry_count INTEGER DEFAULT 0,         -- 0 = first pass, 1 = corrective retry
    rewritten_query TEXT,                  -- Null if no retry
    response_text TEXT NOT NULL,
    reasoning_trace TEXT,                  -- Human-readable trace of decisions
    citations_json TEXT,                   -- JSON array of structured clause references
    latency_ms REAL NOT NULL,
    tokens_prompt INTEGER,
    tokens_completion INTEGER,
    llm_profile TEXT NOT NULL DEFAULT 'mock',  -- 'mock' | 'dev' | 'demo' at execution time
    llm_calls INTEGER NOT NULL DEFAULT 0,      -- total wrapper calls for this request
    cached_calls INTEGER NOT NULL DEFAULT 0,   -- calls served from the on-disk cache
    spend_guard_hit INTEGER NOT NULL DEFAULT 0,-- 1 = run stopped by the call/token cap
    prompt_version TEXT,                       -- e.g. 'v1'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE SET NULL,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_audit_user_id ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_session_id ON audit_log(session_id);
CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_log(created_at);

-- ============================================================================
-- 6. LLM_CALLS TABLE (Per-Call Token, Profile & Cache Metrics)
-- ============================================================================
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id INTEGER,                       -- NULL for pre-audit calls (e.g. evaluation judge)
    session_id TEXT,
    step TEXT NOT NULL CHECK(step IN ('router', 'grader', 'rewrite', 'answer', 'judge')),
    llm_profile TEXT NOT NULL CHECK(llm_profile IN ('mock', 'dev', 'demo')),
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    cached INTEGER NOT NULL DEFAULT 0,      -- 1 = served from on-disk cache, 0 quota
    latency_ms REAL NOT NULL,
    json_repair_attempted INTEGER NOT NULL DEFAULT 0,
    fallback_used INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (audit_id) REFERENCES audit_log (id) ON DELETE SET NULL,
    FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_llm_calls_audit_id ON llm_calls(audit_id);
CREATE INDEX IF NOT EXISTS idx_llm_calls_step ON llm_calls(step);
CREATE INDEX IF NOT EXISTS idx_llm_calls_profile ON llm_calls(llm_profile);
CREATE INDEX IF NOT EXISTS idx_llm_calls_created_at ON llm_calls(created_at);

-- ============================================================================
-- 7. LLM RESPONSE MEMOIZATION CACHE
-- ============================================================================
CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key TEXT PRIMARY KEY,            -- SHA256(profile + model + prompt version + prompt + params)
    prompt_hash TEXT NOT NULL,
    model_name TEXT NOT NULL,
    response_text TEXT NOT NULL,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_cache_prompt_hash ON llm_cache(prompt_hash);

-- ============================================================================
-- 8. DOCUMENTS CATALOG TABLE (Ingested Source Registry)
-- ============================================================================
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,                   -- E.g., 'DOC-FCA-MLR-2017'
    filename TEXT NOT NULL,
    source_jurisdiction TEXT NOT NULL,     -- 'UK_FCA', 'BASEL_III', 'INTERNAL_SYNTHETIC'
    doc_type TEXT NOT NULL,                -- 'PUBLIC_REGULATION', 'INTERNAL_SOP', 'AUDIT_POLICY'
    version TEXT NOT NULL,
    allowed_roles TEXT NOT NULL,           -- JSON array: '["analyst", "manager", "auditor"]'
    file_path TEXT NOT NULL,
    total_chunks INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 3. Vector Database Payload Schema (Qdrant)

Each chunk indexed into Qdrant contains the embedding vector plus a structured JSON payload:

```json
{
  "chunk_id": "FCA-MLR-2017_SEC4_CL12",
  "doc_id": "DOC-FCA-MLR-2017",
  "doc_name": "Money Laundering Regulations 2017",
  "section_title": "Section 4: Customer Due Diligence Measures",
  "clause_id": "Regulation 12(3)(a)",
  "page_number": 14,
  "allowed_roles": ["analyst", "manager", "auditor"],
  "text_content": "A relevant person must apply customer due diligence measures where the relevant person carries out an occasional transaction that amounts to 15,000 euros or more...",
  "token_count": 148,
  "created_at": "2026-11-11T12:00:00Z"
}
```

### 3.1 Role Hierarchy & Tagging Resolution

| Document Classification | Sample Content | Tagged `allowed_roles` in Payload | Accessible By |
| :--- | :--- | :--- | :--- |
| **Public Regulation** | FCA Handbook, Basel III Capital Requirements | `["analyst", "manager", "auditor"]` | Analyst, Manager, Auditor |
| **Internal General SOP** | Standard Account Opening SOP, KYC Checklist | `["analyst", "manager", "auditor"]` | Analyst, Manager, Auditor |
| **Internal Management Policy** | Supervisory Escalation Framework, Remediation Plans | `["manager", "auditor"]` | Manager, Auditor |
| **Confidential Audit / Risk** | Internal Audit Findings, Whistleblowing Reports | `["auditor"]` | Auditor only |

### 3.2 Server-Side Qdrant Filter Definition
When an authenticated user executes a search, the filter condition is generated deterministically by backend security service:

```python
from qdrant_client.http import models

def get_role_filter(user_role: str) -> models.Filter:
    """
    Enforces server-side RBAC. Chunks missing the user's role are
    mathematically excluded from vector distance calculations.
    """
    return models.Filter(
        must=[
            models.FieldCondition(
                key="allowed_roles",
                match=models.MatchValue(value=user_role)
            )
        ]
    )
```

---

## 4. Parameterized SQL Patterns

In accordance with Engineering Rules, raw SQL interpolation (`f"SELECT ... {user_input}"`) is strictly prohibited. Standard parameterized access patterns via Python `sqlite3`:

```python
import sqlite3
from typing import Any

def execute_query(conn: sqlite3.Connection, query: str, params: tuple[Any, ...]) -> list[sqlite3.Row]:
    cursor = conn.cursor()
    cursor.execute(query, params)
    return cursor.fetchall()

# Example: Fetching recent conversation history for memory injection
def get_session_history(conn: sqlite3.Connection, session_id: str, limit: int = 6) -> list[sqlite3.Row]:
    query = """
        SELECT sender, content, route_used, created_at
        FROM messages
        WHERE session_id = ?
        ORDER BY created_at ASC
        LIMIT ?;
    """
    return execute_query(conn, query, (session_id, limit))

# Example: Inserting immutable audit log entry
def insert_audit_log(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    query = """
        INSERT INTO audit_log (
            session_id, user_id, user_role, query_text, final_route,
            retrieved_chunk_ids, relevance_scores, retry_count, rewritten_query,
            response_text, reasoning_trace, citations_json, latency_ms,
            tokens_prompt, tokens_completion, llm_profile, llm_calls,
            cached_calls, spend_guard_hit, prompt_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """
    cursor = conn.cursor()
    cursor.execute(query, (
        data["session_id"], data["user_id"], data["user_role"], data["query_text"],
        data["final_route"], data["retrieved_chunk_ids"], data["relevance_scores"],
        data["retry_count"], data.get("rewritten_query"), data["response_text"],
        data["reasoning_trace"], data["citations_json"], data["latency_ms"],
        data.get("tokens_prompt", 0), data.get("tokens_completion", 0),
        data["llm_profile"], data.get("llm_calls", 0), data.get("cached_calls", 0),
        data.get("spend_guard_hit", 0), data.get("prompt_version", "v1")
    ))
    conn.commit()
    return cursor.lastrowid

# Example: Recording one LLM call (called by the gateway wrapper, never by routes)
def insert_llm_call(conn: sqlite3.Connection, call: dict[str, Any]) -> int:
    query = """
        INSERT INTO llm_calls (
            audit_id, session_id, step, llm_profile, model, prompt_version,
            prompt_tokens, completion_tokens, cached, latency_ms,
            json_repair_attempted, fallback_used
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """
    cursor = conn.cursor()
    cursor.execute(query, (
        call.get("audit_id"), call.get("session_id"), call["step"],
        call["llm_profile"], call["model"], call["prompt_version"],
        call.get("prompt_tokens", 0), call.get("completion_tokens", 0),
        int(call.get("cached", False)), call["latency_ms"],
        int(call.get("json_repair_attempted", False)),
        int(call.get("fallback_used", False)),
    ))
    conn.commit()
    return cursor.lastrowid
```

---

## 5. Seed Data & Synthetic User Registry

The system is seeded with three synthetic users matching the permissions model:

```sql
-- Seed Roles
INSERT OR IGNORE INTO roles (id, name, description, hierarchy_level) VALUES
(1, 'analyst', 'Front-line compliance and operations staff', 10),
(2, 'manager', 'Compliance manager and supervisory lead', 20),
(3, 'auditor', 'Internal/external auditor and executive risk officer', 30);

-- Seed Synthetic Users (Default password hash for local development: 'password123')
INSERT OR IGNORE INTO users (id, username, password_hash, role_id, full_name, email) VALUES
(1, 'analyst_user', '$2b$12$eD4v3mU0...hash...', 1, 'Alice Analyst', 'alice.analyst@bank.local'),
(2, 'manager_user', '$2b$12$eD4v3mU0...hash...', 2, 'Bob Manager', 'bob.manager@bank.local'),
(3, 'auditor_user', '$2b$12$eD4v3mU0...hash...', 3, 'Carol Auditor', 'carol.auditor@bank.local');
```

---

## 6. Assumptions & Open Decisions

### Assumptions Made
- Single-instance local SQLite is sufficient for the scale of this project; concurrent reads are handled smoothly by WAL mode.
- User authentication can be simulated locally via user token/header selection in the Web UI, calling the backend with validated user credentials.
- Document and chunk identifiers (`DOC-XXX`, `CH-XXX`) follow a deterministic numbering scheme generated at ingestion.

### Open Decisions Flagged for User
1. **Password Hashing:** Use standard PBKDF2 or bcrypt for local password storage vs mock deterministic hashes for synthetic users.
2. **Audit Log Retention:** Keep all audit records indefinitely for research evaluation vs adding a cleanup CLI script.

