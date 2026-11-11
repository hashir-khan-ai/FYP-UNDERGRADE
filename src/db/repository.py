"""Parameterized data access repository for SQLite database."""

import json
import sqlite3
from typing import Any


class Repository:
    """Encapsulates parameterized CRUD operations over the SQLite schema."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # --------------------------------------------------------------------------
    # Roles
    # --------------------------------------------------------------------------
    def get_role_by_id(self, role_id: int) -> sqlite3.Row | None:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM roles WHERE id = ?;", (role_id,))
        return cur.fetchone()

    def get_role_by_name(self, name: str) -> sqlite3.Row | None:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM roles WHERE name = ?;", (name,))
        return cur.fetchone()

    def list_roles(self) -> list[sqlite3.Row]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM roles ORDER BY hierarchy_level ASC;")
        return cur.fetchall()

    def insert_role(self, name: str, description: str, hierarchy_level: int) -> int:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT OR IGNORE INTO roles (name, description, hierarchy_level)
            VALUES (?, ?, ?);
            """,
            (name, description, hierarchy_level),
        )
        return cur.lastrowid

    # --------------------------------------------------------------------------
    # Users
    # --------------------------------------------------------------------------
    def create_user(
        self,
        username: str,
        password_hash: str,
        role_id: int,
        full_name: str,
        email: str,
    ) -> int:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO users (username, password_hash, role_id, full_name, email)
            VALUES (?, ?, ?, ?, ?);
            """,
            (username, password_hash, role_id, full_name, email),
        )
        return cur.lastrowid

    def get_user_by_username(self, username: str) -> sqlite3.Row | None:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT u.*, r.name as role_name, r.hierarchy_level
            FROM users u
            JOIN roles r ON u.role_id = r.id
            WHERE u.username = ?;
            """,
            (username,),
        )
        return cur.fetchone()

    def get_user_by_id(self, user_id: int) -> sqlite3.Row | None:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT u.*, r.name as role_name, r.hierarchy_level
            FROM users u
            JOIN roles r ON u.role_id = r.id
            WHERE u.id = ?;
            """,
            (user_id,),
        )
        return cur.fetchone()

    def list_users(self) -> list[sqlite3.Row]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT u.id, u.username, u.full_name, u.email, u.is_active, r.name as role_name
            FROM users u
            JOIN roles r ON u.role_id = r.id
            ORDER BY u.id ASC;
            """
        )
        return cur.fetchall()

    # --------------------------------------------------------------------------
    # Sessions
    # --------------------------------------------------------------------------
    def create_session(self, session_id: str, user_id: int, title: str = "New Compliance Session") -> str:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO sessions (id, user_id, title)
            VALUES (?, ?, ?);
            """,
            (session_id, user_id, title),
        )
        return session_id

    def get_session(self, session_id: str) -> sqlite3.Row | None:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM sessions WHERE id = ?;", (session_id,))
        return cur.fetchone()

    def list_sessions_by_user(self, user_id: int) -> list[sqlite3.Row]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT * FROM sessions
            WHERE user_id = ?
            ORDER BY updated_at DESC;
            """,
            (user_id,),
        )
        return cur.fetchall()

    def delete_session(self, session_id: str) -> bool:
        cur = self.conn.cursor()
        cur.execute("DELETE FROM sessions WHERE id = ?;", (session_id,))
        return cur.rowcount > 0

    # --------------------------------------------------------------------------
    # Messages (Memory Layer)
    # --------------------------------------------------------------------------
    def add_message(
        self,
        session_id: str,
        sender: str,
        content: str,
        route_used: str | None = None,
        metadata_json: str | None = None,
    ) -> int:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO messages (session_id, sender, content, route_used, metadata_json)
            VALUES (?, ?, ?, ?, ?);
            """,
            (session_id, sender, content, route_used, metadata_json),
        )
        # Touch session updated_at
        cur.execute(
            "UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?;",
            (session_id,),
        )
        return cur.lastrowid

    def get_session_messages(self, session_id: str, limit: int = 10) -> list[sqlite3.Row]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT * FROM messages
            WHERE session_id = ?
            ORDER BY created_at ASC
            LIMIT ?;
            """,
            (session_id, limit),
        )
        return cur.fetchall()

    # --------------------------------------------------------------------------
    # Audit Log (XAI Layer)
    # --------------------------------------------------------------------------
    def create_audit_log(
        self,
        session_id: str | None,
        user_id: int,
        user_role: str,
        query_text: str,
        final_route: str,
        retrieved_chunk_ids: list[str] | str,
        relevance_scores: list[float] | str,
        response_text: str,
        latency_ms: float,
        retry_count: int = 0,
        rewritten_query: str | None = None,
        reasoning_trace: list[str] | str | None = None,
        citations_json: list[dict[str, Any]] | str | None = None,
        tokens_prompt: int = 0,
        tokens_completion: int = 0,
    ) -> int:
        # Normalize collections to JSON strings
        chunks_str = json.dumps(retrieved_chunk_ids) if isinstance(retrieved_chunk_ids, list) else retrieved_chunk_ids
        scores_str = json.dumps(relevance_scores) if isinstance(relevance_scores, list) else relevance_scores
        trace_str = json.dumps(reasoning_trace) if isinstance(reasoning_trace, list) else reasoning_trace
        cites_str = json.dumps(citations_json) if isinstance(citations_json, list) else citations_json

        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO audit_log (
                session_id, user_id, user_role, query_text, final_route,
                retrieved_chunk_ids, relevance_scores, retry_count, rewritten_query,
                response_text, reasoning_trace, citations_json, latency_ms,
                tokens_prompt, tokens_completion
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                session_id,
                user_id,
                user_role,
                query_text,
                final_route,
                chunks_str,
                scores_str,
                retry_count,
                rewritten_query,
                response_text,
                trace_str,
                cites_str,
                latency_ms,
                tokens_prompt,
                tokens_completion,
            ),
        )
        return cur.lastrowid

    def list_audit_logs(self, limit: int = 50, user_id: int | None = None) -> list[sqlite3.Row]:
        cur = self.conn.cursor()
        if user_id is not None:
            cur.execute(
                """
                SELECT * FROM audit_log
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?;
                """,
                (user_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT * FROM audit_log
                ORDER BY created_at DESC
                LIMIT ?;
                """,
                (limit,),
            )
        return cur.fetchall()

    # --------------------------------------------------------------------------
    # Document Catalog
    # --------------------------------------------------------------------------
    def register_document(
        self,
        doc_id: str,
        filename: str,
        source_jurisdiction: str,
        doc_type: str,
        version: str,
        allowed_roles: list[str] | str,
        file_path: str,
        total_chunks: int = 0,
    ) -> None:
        roles_str = json.dumps(allowed_roles) if isinstance(allowed_roles, list) else allowed_roles
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO documents (
                id, filename, source_jurisdiction, doc_type, version,
                allowed_roles, file_path, total_chunks
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                doc_id,
                filename,
                source_jurisdiction,
                doc_type,
                version,
                roles_str,
                file_path,
                total_chunks,
            ),
        )

    def list_documents(self) -> list[sqlite3.Row]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM documents ORDER BY id ASC;")
        return cur.fetchall()

    # --------------------------------------------------------------------------
    # On-Disk LLM Cache
    # --------------------------------------------------------------------------
    def get_cached_llm(self, cache_key: str) -> sqlite3.Row | None:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM llm_cache WHERE cache_key = ?;", (cache_key,))
        return cur.fetchone()

    def set_cached_llm(
        self,
        cache_key: str,
        prompt_hash: str,
        model_name: str,
        response_text: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO llm_cache (
                cache_key, prompt_hash, model_name, response_text,
                prompt_tokens, completion_tokens
            ) VALUES (?, ?, ?, ?, ?, ?);
            """,
            (
                cache_key,
                prompt_hash,
                model_name,
                response_text,
                prompt_tokens,
                completion_tokens,
            ),
        )
