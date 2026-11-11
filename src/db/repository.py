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

    def upsert_user(
        self,
        username: str,
        password_hash: str,
        role_id: int,
        full_name: str,
        email: str,
    ) -> int:
        """Create or update a synthetic user without changing its identifier."""
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO users (username, password_hash, role_id, full_name, email)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                password_hash = excluded.password_hash,
                role_id = excluded.role_id,
                full_name = excluded.full_name,
                email = excluded.email,
                is_active = 1;
            """,
            (username, password_hash, role_id, full_name, email),
        )
        cur.execute("SELECT id FROM users WHERE username = ?;", (username,))
        row = cur.fetchone()
        return int(row["id"]) if row else int(cur.lastrowid)


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

    def get_session_for_user(self, session_id: str, user_id: int) -> sqlite3.Row | None:
        """Return a session only when it belongs to ``user_id`` (IDOR guard)."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM sessions WHERE id = ? AND user_id = ?;",
            (session_id, user_id),
        )
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

    def delete_session_for_user(self, session_id: str, user_id: int) -> bool:
        """Delete a session only when it belongs to ``user_id``."""
        cur = self.conn.cursor()
        cur.execute(
            "DELETE FROM sessions WHERE id = ? AND user_id = ?;",
            (session_id, user_id),
        )
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
        user_role: str | None = None,
    ) -> int:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO messages (session_id, sender, content, route_used, user_role, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?);
            """,
            (session_id, sender, content, route_used, user_role, metadata_json),
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

    def get_recent_messages(self, session_id: str, limit: int = 10) -> list[sqlite3.Row]:
        """Return the newest ``limit`` messages, oldest first.

        Callers must resolve the session owner first; this method intentionally
        takes only ``session_id`` because ownership is enforced by
        :meth:`get_session_for_user` before it is reached.
        """
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT * FROM (
                SELECT * FROM messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
            )
            ORDER BY id ASC;
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
        llm_profile: str = "mock",
        llm_calls: int = 0,
        cached_calls: int = 0,
        spend_guard_hit: bool = False,
        prompt_version: str = "v1",
        llm_model: str | None = None,
        candidates_retrieved: int = 0,
        candidates_filtered: int = 0,
        router_confidence: float | None = None,
        router_fallback_reason: str | None = None,
        sub_questions: list[str] | str | None = None,
        step_timings: list[dict[str, Any]] | str | None = None,
        # Phase 5 grader observability (all nullable)
        grader_path: str | None = None,
        grader_relevant_count: int | None = None,
        grader_ambiguous_count: int | None = None,
        grader_irrelevant_count: int | None = None,
        grader_rewrite_used: bool | None = None,
        grader_rewritten_query: str | None = None,
        grader_refused: bool | None = None,
        grader_refusal_reason: str | None = None,
        grader_calls: int | None = None,
        grader_tokens: int | None = None,
        grader_latency_ms: float | None = None,
    ) -> int:
        # Normalize collections to JSON strings
        chunks_str = json.dumps(retrieved_chunk_ids) if isinstance(retrieved_chunk_ids, list) else retrieved_chunk_ids
        scores_str = json.dumps(relevance_scores) if isinstance(relevance_scores, list) else relevance_scores
        trace_str = json.dumps(reasoning_trace) if isinstance(reasoning_trace, list) else reasoning_trace
        cites_str = json.dumps(citations_json) if isinstance(citations_json, list) else citations_json
        subs_str = json.dumps(sub_questions) if isinstance(sub_questions, list) else sub_questions
        timings_str = json.dumps(step_timings) if isinstance(step_timings, list) else step_timings

        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO audit_log (
                session_id, user_id, user_role, query_text, final_route,
                retrieved_chunk_ids, relevance_scores, retry_count, rewritten_query,
                response_text, reasoning_trace, citations_json, latency_ms,
                tokens_prompt, tokens_completion, llm_profile, llm_calls,
                cached_calls, spend_guard_hit, prompt_version, llm_model,
                candidates_retrieved, candidates_filtered, router_confidence,
                router_fallback_reason, sub_questions, step_timings_json,
                grader_path, grader_relevant_count, grader_ambiguous_count,
                grader_irrelevant_count, grader_rewrite_used, grader_rewritten_query,
                grader_refused, grader_refusal_reason, grader_calls, grader_tokens,
                grader_latency_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
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
                llm_profile,
                llm_calls,
                cached_calls,
                1 if spend_guard_hit else 0,
                prompt_version,
                llm_model,
                candidates_retrieved,
                candidates_filtered,
                router_confidence,
                router_fallback_reason,
                subs_str,
                timings_str,
                grader_path,
                grader_relevant_count,
                grader_ambiguous_count,
                grader_irrelevant_count,
                1 if grader_rewrite_used else (0 if grader_rewrite_used is not None else None),
                grader_rewritten_query,
                1 if grader_refused else (0 if grader_refused is not None else None),
                grader_refusal_reason,
                grader_calls,
                grader_tokens,
                grader_latency_ms,
            ),
        )
        return cur.lastrowid

    def list_audit_logs(
        self,
        limit: int = 50,
        user_id: int | None = None,
        start_date: str | None = None,
    ) -> list[sqlite3.Row]:
        """Return newest-first audit rows, optionally filtered.

        A single static, fully parameterized statement is used so no user value
        is ever interpolated into SQL.
        """
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT * FROM audit_log
            WHERE (? IS NULL OR user_id = ?)
              AND (? IS NULL OR created_at >= ?)
            ORDER BY created_at DESC
            LIMIT ?;
            """,
            (user_id, user_id, start_date, start_date, limit),
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
    # On-Disk LLM Cache & Telemetry
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

    def log_llm_call(
        self,
        profile: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        cache_hit: bool,
        call_status: str = "success",
        error_message: str | None = None,
        step: str = "answer",
        prompt_version: str = "v1",
        audit_id: int | None = None,
        session_id: str | None = None,
        json_repair_attempted: bool = False,
        fallback_used: bool = False,
    ) -> int:
        """Persist one LLM call for token, latency, cache and spend telemetry."""
        cur = self.conn.cursor()
        total_tokens = prompt_tokens + completion_tokens
        cur.execute(
            """
            INSERT INTO llm_calls (
                profile, llm_profile, model, step, prompt_version,
                prompt_tokens, completion_tokens, total_tokens, latency_ms,
                cache_hit, cached, call_status, error_message, audit_id,
                session_id, json_repair_attempted, fallback_used
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                profile,
                profile,
                model,
                step,
                prompt_version,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                latency_ms,
                1 if cache_hit else 0,
                1 if cache_hit else 0,
                call_status,
                error_message,
                audit_id,
                session_id,
                1 if json_repair_attempted else 0,
                1 if fallback_used else 0,
            ),
        )
        return cur.lastrowid

    def get_max_llm_call_id(self) -> int:
        """Return the highest telemetry row id, or 0 when the table is empty."""
        cur = self.conn.cursor()
        cur.execute("SELECT COALESCE(MAX(id), 0) AS max_id FROM llm_calls;")
        row = cur.fetchone()
        return int(row["max_id"]) if row else 0

    def get_llm_usage_since(self, after_id: int, session_id: str) -> dict[str, int]:
        """Aggregate telemetry for one request without storing prompt content."""
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT
                COUNT(*) AS calls,
                COALESCE(SUM(cached), 0) AS cached_calls,
                COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) AS completion_tokens
            FROM llm_calls
            WHERE id > ? AND session_id = ?;
            """,
            (after_id, session_id),
        )
        row = cur.fetchone()
        if row is None:
            return {"calls": 0, "cached_calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
        return {
            "calls": int(row["calls"] or 0),
            "cached_calls": int(row["cached_calls"] or 0),
            "prompt_tokens": int(row["prompt_tokens"] or 0),
            "completion_tokens": int(row["completion_tokens"] or 0),
        }

    def get_spend_totals(self) -> dict[str, int]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT 
                COUNT(*) as total_calls,
                COALESCE(SUM(total_tokens), 0) as total_tokens,
                COALESCE(SUM(CASE WHEN cache_hit = 1 THEN 1 ELSE 0 END), 0) as cache_hits
            FROM llm_calls;
            """
        )
        row = cur.fetchone()
        if row:
            return {
                "total_calls": row["total_calls"],
                "total_tokens": row["total_tokens"],
                "cache_hits": row["cache_hits"],
            }
        return {"total_calls": 0, "total_tokens": 0, "cache_hits": 0}

