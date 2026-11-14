"""Parameterized data access repository for SQLite database."""

import json
import sqlite3
from typing import Any

from src.core.audit_chain import GENESIS_PREV_HASH, compute_audit_hash


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
    def create_session(
        self,
        session_id: str,
        user_id: int,
        title: str = "New Compliance Session",
        title_source: str = "default",
        title_locked: int = 0,
    ) -> str:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO sessions (id, user_id, title, title_source, title_locked)
            VALUES (?, ?, ?, ?, ?);
            """,
            (session_id, user_id, title, title_source, title_locked),
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

    def rename_session_for_user(
        self,
        session_id: str,
        user_id: int,
        title: str,
        title_source: str = "user",
        title_locked: int = 1,
        force: bool = False,
    ) -> sqlite3.Row | None:
        """Rename a session owned by ``user_id``; return the updated row or None."""
        cur = self.conn.cursor()
        existing = self.get_session_for_user(session_id, user_id)
        if not existing:
            return None
        existing_locked = bool(existing["title_locked"] if "title_locked" in existing.keys() else 0)
        if existing_locked and not force and title_source == "auto":
            return existing

        cur.execute(
            """
            UPDATE sessions
            SET title = ?, title_source = ?, title_locked = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND user_id = ?;
            """,
            (title, title_source, title_locked, session_id, user_id),
        )
        if cur.rowcount == 0:
            return None
        return self.get_session_for_user(session_id, user_id)


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
        # Phase 6A XAI observability (all nullable)
        citation_count: int | None = None,
        citations_dropped: int | None = None,
        heading_path_enabled: bool | None = None,
        # Phase 8C stretch feature observability (all nullable)
        claim_check_json: dict[str, Any] | str | None = None,
        calculator_json: dict[str, Any] | str | None = None,
    ) -> int:
        # Normalize collections to JSON strings
        chunks_str = json.dumps(retrieved_chunk_ids) if isinstance(retrieved_chunk_ids, list) else retrieved_chunk_ids
        scores_str = json.dumps(relevance_scores) if isinstance(relevance_scores, list) else relevance_scores
        trace_str = json.dumps(reasoning_trace) if isinstance(reasoning_trace, list) else reasoning_trace
        cites_str = json.dumps(citations_json) if isinstance(citations_json, list) else citations_json
        subs_str = json.dumps(sub_questions) if isinstance(sub_questions, list) else sub_questions
        timings_str = json.dumps(step_timings) if isinstance(step_timings, list) else step_timings
        claim_str = json.dumps(claim_check_json) if isinstance(claim_check_json, dict) else claim_check_json
        calc_str = json.dumps(calculator_json) if isinstance(calculator_json, dict) else calculator_json

        cur = self.conn.cursor()
        cur.execute("SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1;")
        prev_row = cur.fetchone()
        prev_hash = str(prev_row[0]) if prev_row and prev_row[0] else GENESIS_PREV_HASH

        entry_values = (
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
            spend_guard_hit,
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
            grader_rewrite_used,
            grader_rewritten_query,
            grader_refused,
            grader_refusal_reason,
            grader_calls,
            grader_tokens,
            grader_latency_ms,
            citation_count,
            citations_dropped,
            heading_path_enabled,
            claim_str,
            calc_str,
        )
        entry_hash = compute_audit_hash(prev_hash, entry_values)

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
                grader_latency_ms, citation_count, citations_dropped, heading_path_enabled,
                claim_check_json, calculator_json, prev_hash, entry_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
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
                citation_count,
                citations_dropped,
                1 if heading_path_enabled else (0 if heading_path_enabled is not None else None),
                claim_str,
                calc_str,
                prev_hash,
                entry_hash,
            ),
        )
        return cur.lastrowid

    def list_audit_logs(
        self,
        limit: int = 50,
        user_id: int | None = None,
        start_date: str | None = None,
        route: str | None = None,
        user_role: str | None = None,
        offset: int = 0,
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
              AND (? IS NULL OR final_route = ?)
              AND (? IS NULL OR user_role = ?)
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?;
            """,
            (
                user_id,
                user_id,
                start_date,
                start_date,
                route,
                route,
                user_role,
                user_role,
                limit,
                max(int(offset), 0),
            ),
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

    def get_document(self, doc_id: str) -> sqlite3.Row | None:
        """Fetch a single document from the catalog by its ID."""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM documents WHERE id = ?;", (doc_id,))
        return cur.fetchone()

    def update_document_metadata(
        self,
        doc_id: str,
        title: str | None = None,
        allowed_roles: list[str] | None = None,
    ) -> bool:
        """Update a document's title or allowed roles."""
        cur = self.conn.cursor()
        updates = []
        params = []
        if title is not None:
            updates.append("filename = ?")
            params.append(title)
        if allowed_roles is not None:
            updates.append("allowed_roles = ?")
            params.append(json.dumps(allowed_roles))
        if not updates:
            return False
        params.append(doc_id)
        cur.execute(f"UPDATE documents SET {', '.join(updates)} WHERE id = ?;", tuple(params))
        return cur.rowcount > 0

    def delete_document(self, doc_id: str) -> bool:
        """Delete a document from the catalog."""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM documents WHERE id = ?;", (doc_id,))
        return cur.rowcount > 0

    # --------------------------------------------------------------------------
    # Saved Views (Scoped strictly by user ID)
    # --------------------------------------------------------------------------
    def save_user_view(
        self,
        user_id: int,
        view_name: str,
        page: str,
        filters_json: str,
        view_id: str | None = None,
    ) -> str:
        """Save or update a named filter view scoped strictly to user_id."""
        import uuid
        cur = self.conn.cursor()
        if view_id:
            cur.execute("SELECT user_id FROM saved_views WHERE id = ?;", (view_id,))
            row = cur.fetchone()
            if row and int(row[0]) != int(user_id):
                raise PermissionError("Cannot overwrite a saved view owned by another user.")
            final_id = view_id
        else:
            final_id = f"view_{uuid.uuid4().hex[:12]}"

        cur.execute(
            """
            INSERT OR REPLACE INTO saved_views (id, user_id, view_name, page, filters_json)
            VALUES (?, ?, ?, ?, ?);
            """,
            (final_id, user_id, view_name.strip()[:100], page.strip()[:50], filters_json),
        )
        return final_id

    def get_user_view(self, user_id: int, view_id: str) -> sqlite3.Row | None:
        """Fetch a single saved view strictly verifying ownership by user_id."""
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM saved_views WHERE id = ? AND user_id = ?;", (view_id, user_id))
        return cur.fetchone()

    def update_user_view(
        self,
        user_id: int,
        view_id: str,
        view_name: str | None = None,
        filters_json: str | None = None,
    ) -> bool:
        """Update a saved view strictly verifying ownership by user_id."""
        cur = self.conn.cursor()
        updates = []
        params = []
        if view_name is not None:
            updates.append("view_name = ?")
            params.append(view_name.strip()[:100])
        if filters_json is not None:
            updates.append("filters_json = ?")
            params.append(filters_json)
        if not updates:
            return False
        params.extend([view_id, user_id])
        cur.execute(
            f"UPDATE saved_views SET {', '.join(updates)} WHERE id = ? AND user_id = ?;",
            tuple(params),
        )
        return cur.rowcount > 0

    def list_user_views(self, user_id: int, page: str | None = None) -> list[sqlite3.Row]:
        """List saved filter views scoped strictly to user_id."""
        cur = self.conn.cursor()
        if page:
            cur.execute(
                "SELECT * FROM saved_views WHERE user_id = ? AND page = ? ORDER BY created_at DESC;",
                (user_id, page),
            )
        else:
            cur.execute(
                "SELECT * FROM saved_views WHERE user_id = ? ORDER BY created_at DESC;",
                (user_id,),
            )
        return cur.fetchall()

    def delete_user_view(self, user_id: int, view_id: str) -> bool:
        """Delete a saved view verifying ownership by user_id."""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM saved_views WHERE id = ? AND user_id = ?;", (view_id, user_id))
        return cur.rowcount > 0

    # --------------------------------------------------------------------------
    # On-Disk LLM Cache & Telemetry
    # --------------------------------------------------------------------------
    def get_cached_llm(self, cache_key: str) -> sqlite3.Row | None:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM llm_cache WHERE cache_key = ?;", (cache_key,))
        return cur.fetchone()

    def delete_cached_llm(self, cache_key: str) -> None:
        """Delete one invalidated or malformed cache entry."""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM llm_cache WHERE cache_key = ?;", (cache_key,))

    def clear_all_llm_cache(self) -> int:
        """Purge all cached LLM answers across all models and roles."""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM llm_cache;")
        return cur.rowcount

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

    def get_llm_usage_after(self, after_id: int) -> dict[str, int]:
        """Aggregate live vs cached LLM usage logged after ``after_id``.

        Used by the evaluation harness to count cache hits separately from
        live (uncached) provider calls. Reads only counters, never prompt text.
        """
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN cache_hit = 0 THEN 1 ELSE 0 END), 0) AS live_calls,
                COALESCE(SUM(CASE WHEN cache_hit = 1 THEN 1 ELSE 0 END), 0) AS cached_calls,
                COALESCE(SUM(CASE WHEN cache_hit = 0
                    THEN COALESCE(prompt_tokens, 0) + COALESCE(completion_tokens, 0)
                    ELSE 0 END), 0) AS live_tokens,
                COALESCE(SUM(CASE WHEN cache_hit = 1
                    THEN COALESCE(prompt_tokens, 0) + COALESCE(completion_tokens, 0)
                    ELSE 0 END), 0) AS cached_tokens
            FROM llm_calls
            WHERE id > ?;
            """,
            (after_id,),
        )
        row = cur.fetchone()
        if row is None:
            return {"live_calls": 0, "cached_calls": 0, "live_tokens": 0, "cached_tokens": 0}
        return {
            "live_calls": int(row["live_calls"] or 0),
            "cached_calls": int(row["cached_calls"] or 0),
            "live_tokens": int(row["live_tokens"] or 0),
            "cached_tokens": int(row["cached_tokens"] or 0),
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

    def get_system_metrics(self) -> dict[str, Any]:
        """Return aggregated non-sensitive operational metrics and recent latency samples."""
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT
                COUNT(*) AS total_calls,
                COALESCE(SUM(CASE WHEN cache_hit = 1 THEN 1 ELSE 0 END), 0) AS cached_calls,
                COALESCE(SUM(CASE WHEN call_status = 'error' THEN 1 ELSE 0 END), 0) AS error_calls,
                COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                COALESCE(SUM(total_tokens), 0) AS total_tokens
            FROM llm_calls;
            """
        )
        llm_row = cur.fetchone()

        cur.execute(
            """
            SELECT
                COUNT(*) AS total_turns,
                COALESCE(SUM(candidates_filtered), 0) AS total_role_filtered,
                COALESCE(SUM(citations_dropped), 0) AS total_citations_dropped
            FROM audit_log;
            """
        )
        audit_row = cur.fetchone()

        cur.execute(
            """
            SELECT latency_ms
            FROM audit_log
            WHERE latency_ms IS NOT NULL
            ORDER BY id DESC
            LIMIT 1000;
            """
        )
        latencies = [float(r["latency_ms"]) for r in cur.fetchall() if r["latency_ms"] is not None]

        return {
            "total_calls": int(llm_row["total_calls"] or 0) if llm_row else 0,
            "cached_calls": int(llm_row["cached_calls"] or 0) if llm_row else 0,
            "error_calls": int(llm_row["error_calls"] or 0) if llm_row else 0,
            "prompt_tokens": int(llm_row["prompt_tokens"] or 0) if llm_row else 0,
            "completion_tokens": int(llm_row["completion_tokens"] or 0) if llm_row else 0,
            "total_tokens": int(llm_row["total_tokens"] or 0) if llm_row else 0,
            "total_turns": int(audit_row["total_turns"] or 0) if audit_row else 0,
            "total_role_filtered": int(audit_row["total_role_filtered"] or 0) if audit_row else 0,
            "total_citations_dropped": int(audit_row["total_citations_dropped"] or 0) if audit_row else 0,
            "latencies": latencies,
        }

