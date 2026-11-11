"""Unit tests for SQLite database layer, migrations, and repository."""

import sqlite3
import pytest
from src.db.repository import Repository


def test_schema_initialization(test_db: sqlite3.Connection) -> None:
    """Verify that all core tables exist in the schema."""
    cur = test_db.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row[0] for row in cur.fetchall()}
    expected = {"roles", "users", "sessions", "messages", "audit_log", "documents", "llm_cache"}
    assert expected.issubset(tables)


def test_roles_and_hierarchy(repo: Repository) -> None:
    """Verify role insertion and retrieval."""
    repo.insert_role("analyst", "Front-line staff", 10)
    repo.insert_role("manager", "Manager staff", 20)
    repo.insert_role("auditor", "Audit officer", 30)

    roles = repo.list_roles()
    assert len(roles) == 3
    assert roles[0]["name"] == "analyst"
    assert roles[0]["hierarchy_level"] == 10
    assert roles[2]["name"] == "auditor"
    assert roles[2]["hierarchy_level"] == 30


def test_user_foreign_key_enforcement(repo: Repository, test_db: sqlite3.Connection) -> None:
    """Verify that creating a user with a non-existent role_id fails."""
    with pytest.raises(sqlite3.IntegrityError):
        repo.create_user("ghost_user", "hash", 9999, "Ghost User", "ghost@bank.local")


def test_user_creation_and_retrieval(repo: Repository) -> None:
    """Verify user creation with valid role."""
    repo.insert_role("analyst", "Front-line staff", 10)
    role = repo.get_role_by_name("analyst")
    assert role is not None

    user_id = repo.create_user("alice", "hash123", role["id"], "Alice Analyst", "alice@bank.local")
    assert user_id > 0

    user = repo.get_user_by_username("alice")
    assert user is not None
    assert user["full_name"] == "Alice Analyst"
    assert user["role_name"] == "analyst"
    assert user["hierarchy_level"] == 10


def test_session_and_message_lifecycle(repo: Repository) -> None:
    """Verify session creation and message turn tracking for conversation memory."""
    repo.insert_role("analyst", "Front-line staff", 10)
    role = repo.get_role_by_name("analyst")
    user_id = repo.create_user("alice", "hash123", role["id"], "Alice Analyst", "alice@bank.local")

    session_id = "test-session-uuid-001"
    repo.create_session(session_id, user_id, "KYC Consultation")

    session = repo.get_session(session_id)
    assert session is not None
    assert session["title"] == "KYC Consultation"

    # Add messages
    repo.add_message(session_id, "user", "What is the KYC threshold?")
    repo.add_message(session_id, "assistant", "15,000 euros under MLR 2017.", route_used="SINGLE_SEARCH")

    messages = repo.get_session_messages(session_id)
    assert len(messages) == 2
    assert messages[0]["sender"] == "user"
    assert messages[1]["route_used"] == "SINGLE_SEARCH"


def test_audit_log_recording(repo: Repository) -> None:
    """Verify audit log creation with structured JSON fields."""
    repo.insert_role("manager", "Manager", 20)
    role = repo.get_role_by_name("manager")
    user_id = repo.create_user("bob", "hash123", role["id"], "Bob Manager", "bob@bank.local")

    audit_id = repo.create_audit_log(
        session_id=None,
        user_id=user_id,
        user_role="manager",
        query_text="What are notification deadlines for breaches?",
        final_route="SINGLE_SEARCH",
        retrieved_chunk_ids=["CH-POL-MGT-001"],
        relevance_scores=[0.92],
        response_text="Notification must be made within 24 hours.",
        latency_ms=1240.5,
        retry_count=0,
        reasoning_trace=["Step 1: Router classified query", "Step 2: Graded relevance 0.92"],
        citations_json=[{"clause": "POL-MGT-1.1", "doc": "POLICY-002"}],
        tokens_prompt=210,
        tokens_completion=45,
    )
    assert audit_id > 0

    logs = repo.list_audit_logs(limit=10)
    assert len(logs) == 1
    assert logs[0]["user_role"] == "manager"
    assert logs[0]["latency_ms"] == 1240.5
    assert logs[0]["tokens_prompt"] == 210


def test_llm_response_cache(repo: Repository) -> None:
    """Verify on-disk LLM response caching and retrieval."""
    cache_key = "test_sha256_hash_abc"
    repo.set_cached_llm(
        cache_key=cache_key,
        prompt_hash="prompt_123",
        model_name="llama-3.1-8b-instant",
        response_text='{"route": "SINGLE_SEARCH"}',
        prompt_tokens=50,
        completion_tokens=10,
    )

    cached = repo.get_cached_llm(cache_key)
    assert cached is not None
    assert cached["model_name"] == "llama-3.1-8b-instant"
    assert cached["response_text"] == '{"route": "SINGLE_SEARCH"}'
    assert cached["prompt_tokens"] == 50


def test_llm_call_telemetry_schema_and_insert(repo: Repository, test_db: sqlite3.Connection) -> None:
    """Verify the documented telemetry columns exist and are populated."""
    cur = test_db.cursor()
    cur.execute("PRAGMA table_info(llm_calls);")
    columns = {row[1] for row in cur.fetchall()}
    assert {
        "audit_id",
        "session_id",
        "step",
        "llm_profile",
        "prompt_version",
        "cached",
        "json_repair_attempted",
        "fallback_used",
    } <= columns

    repo.log_llm_call(
        profile="mock",
        model="mock",
        prompt_tokens=12,
        completion_tokens=4,
        latency_ms=1.5,
        cache_hit=True,
        step="answer",
        prompt_version="v1",
    )
    row = test_db.execute("SELECT * FROM llm_calls ORDER BY id DESC LIMIT 1;").fetchone()
    assert row["step"] == "answer"
    assert row["llm_profile"] == "mock"
    assert row["prompt_version"] == "v1"
    assert row["cached"] == 1
    assert row["total_tokens"] == 16


def test_apply_migrations_upgrades_phase1_llm_calls_table() -> None:
    """Verify an old Phase 1 llm_calls table gains the documented columns."""
    from src.db.migrations import apply_migrations

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE llm_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profile TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            latency_ms REAL NOT NULL,
            cache_hit INTEGER DEFAULT 0,
            call_status TEXT NOT NULL DEFAULT 'success',
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    apply_migrations(conn)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(llm_calls);").fetchall()}
    assert {"step", "llm_profile", "prompt_version", "cached", "fallback_used"} <= columns
    conn.close()


def test_parameterized_query_sql_injection_safety(repo: Repository) -> None:
    """Verify that malicious SQL payloads in inputs do not execute or compromise data."""
    repo.insert_role("analyst", "Analyst", 10)
    role = repo.get_role_by_name("analyst")

    malicious_username = "alice'; DROP TABLE roles; --"
    user_id = repo.create_user(
        malicious_username, "hash", role["id"], "Alice Injected", "alice_inj@bank.local"
    )
    assert user_id > 0

    # Verify roles table is intact
    roles = repo.list_roles()
    assert len(roles) == 1

    # Verify user can be fetched safely with exact string
    user = repo.get_user_by_username(malicious_username)
    assert user is not None
    assert user["username"] == malicious_username

