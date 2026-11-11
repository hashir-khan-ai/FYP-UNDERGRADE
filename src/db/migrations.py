"""Database schema migrations and initialization for SQLite."""

import sqlite3
from src.db.connection import get_db_connection

SCHEMA_DDL = """
-- 1. Roles Table
CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,              -- 'analyst', 'manager', 'auditor'
    description TEXT NOT NULL,
    hierarchy_level INTEGER NOT NULL,      -- 10 = analyst, 20 = manager, 30 = auditor
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Users Table
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,          -- 'analyst_user', 'manager_user', 'auditor_user'
    password_hash TEXT NOT NULL,
    role_id INTEGER NOT NULL,
    full_name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (role_id) REFERENCES roles (id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_role_id ON users(role_id);

-- 3. Sessions Table
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

-- 4. Messages Table
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    sender TEXT NOT NULL CHECK(sender IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    route_used TEXT,
    metadata_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at);

-- 5. Audit Log Table
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    user_id INTEGER NOT NULL,
    user_role TEXT NOT NULL,
    query_text TEXT NOT NULL,
    final_route TEXT NOT NULL,
    retrieved_chunk_ids TEXT,
    relevance_scores TEXT,
    retry_count INTEGER DEFAULT 0,
    rewritten_query TEXT,
    response_text TEXT NOT NULL,
    reasoning_trace TEXT,
    citations_json TEXT,
    latency_ms REAL NOT NULL,
    tokens_prompt INTEGER DEFAULT 0,
    tokens_completion INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE SET NULL,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_audit_user_id ON audit_log(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_session_id ON audit_log(session_id);
CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_log(created_at);

-- 6. Document Catalog Table
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    source_jurisdiction TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    version TEXT NOT NULL,
    allowed_roles TEXT NOT NULL,           -- JSON array string
    file_path TEXT NOT NULL,
    total_chunks INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 7. LLM Response Memoization Cache
CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key TEXT PRIMARY KEY,            -- SHA256(model + prompt + temp + schema)
    prompt_hash TEXT NOT NULL,
    model_name TEXT NOT NULL,
    response_text TEXT NOT NULL,
    prompt_tokens INTEGER DEFAULT 0,
    completion_tokens INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_cache_prompt_hash ON llm_cache(prompt_hash);
"""


def init_db(db_path: str | None = None) -> None:
    """Initialize database schema."""
    with get_db_connection(db_path) as conn:
        conn.executescript(SCHEMA_DDL)


if __name__ == "__main__":
    init_db()
    print("Database schema successfully initialized.")
