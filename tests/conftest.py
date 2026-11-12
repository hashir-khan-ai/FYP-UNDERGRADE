"""Pytest configuration and zero-quota mock fixtures."""

import os
import sqlite3
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

# Force the zero-quota test environment BEFORE importing application settings.
# A file-backed database is used because every SQLite ``:memory:`` connection is
# a separate database, which would make the LLM cache tests meaningless.
_TEST_DB_PATH = Path(tempfile.gettempdir()) / "enterprise_rag_pytest.db"
for _suffix in ("", "-wal", "-shm"):
    try:
        Path(str(_TEST_DB_PATH) + _suffix).unlink()
    except FileNotFoundError:
        pass

os.environ["APP_ENV"] = "test"
os.environ["LLM_PROFILE"] = "mock"
os.environ["DATABASE_PATH"] = str(_TEST_DB_PATH)
os.environ["LLM_MAX_RPM"] = "1000"
os.environ["ENABLE_MEMORY"] = "false"
os.environ["ENABLE_ADAPTIVE_ROUTER"] = "false"
os.environ["ENABLE_CORRECTIVE_GRADER"] = "false"
os.environ["ENABLE_XAI_OUTPUT"] = "false"
os.environ["ENABLE_HEADING_PATH"] = "true"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

from src.db.migrations import SCHEMA_DDL, init_db  # noqa: E402
from src.db.repository import Repository  # noqa: E402
from src.config import settings  # noqa: E402
from src.core.spend_guard import spend_guard  # noqa: E402
from src.ingestion.embeddings import FakeEmbeddingGenerator  # noqa: E402
from src.rag.baseline import baseline_pipeline, MockCrossEncoderReranker  # noqa: E402

init_db()


@pytest.fixture(scope="session", autouse=True)
def _force_mock_llm_profile() -> None:
    """Fail the session immediately if tests could reach a live LLM."""
    assert settings.LLM_PROFILE == "mock"
    assert settings.llm.is_mock is True


@pytest.fixture(autouse=True)
def _configure_test_pipeline() -> Generator[None, None, None]:
    """Configure fast mock embeddings and reranker for zero-download testing."""
    from src.core.auth import login_throttle

    spend_guard.reset()
    login_throttle.reset()
    orig_embedder = baseline_pipeline.qdrant.embedder
    orig_reranker = baseline_pipeline.reranker

    baseline_pipeline.qdrant.embedder = FakeEmbeddingGenerator()
    baseline_pipeline.reranker = MockCrossEncoderReranker()

    yield

    baseline_pipeline.qdrant.embedder = orig_embedder
    baseline_pipeline.reranker = orig_reranker
    login_throttle.reset()
    spend_guard.reset()


TEST_AUTH_PASSWORD = "password123"

_TEST_USER_SPECS = (
    ("analyst_user", "Alice Analyst", "analyst", "alice.analyst@bank.local", 10),
    ("manager_user", "Bob Manager", "manager", "bob.manager@bank.local", 20),
    ("auditor_user", "Carol Auditor", "auditor", "carol.auditor@bank.local", 30),
)


@pytest.fixture(scope="session")
def seeded_auth_users() -> dict[str, dict[str, Any]]:
    """Seed the three synthetic users into the file-backed test database once."""
    from src.core.auth import hash_password
    from src.db.connection import get_db_connection

    password_hash = hash_password(TEST_AUTH_PASSWORD)
    with get_db_connection() as conn:
        repo = Repository(conn)
        for username, full_name, role, email, level in _TEST_USER_SPECS:
            repo.insert_role(role, f"{role} role", level)
        roles = {row["name"]: int(row["id"]) for row in repo.list_roles()}

        users: dict[str, dict[str, Any]] = {}
        for username, full_name, role, email, _ in _TEST_USER_SPECS:
            repo.upsert_user(username, password_hash, roles[role], full_name, email)
            row = repo.get_user_by_username(username)
            users[role] = {
                "id": int(row["id"]),
                "username": username,
                "full_name": full_name,
                "email": email,
                "password": TEST_AUTH_PASSWORD,
            }
    return users


@pytest.fixture
def auth_headers(seeded_auth_users: dict[str, dict[str, Any]]):
    """Return a factory producing a valid bearer header for one role."""
    from src.core.auth import create_access_token

    def _headers(role: str) -> dict[str, str]:
        info = seeded_auth_users[role]
        token = create_access_token(info["id"], info["username"], role)
        return {"Authorization": f"Bearer {token}"}

    return _headers



class MockLLMResponse:
    """Simulated OpenAI-compatible API response object."""

    def __init__(self, content: str, prompt_tokens: int = 15, completion_tokens: int = 25) -> None:
        self.content = content
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class MockLLMClient:
    """
    Mock LLM Client strictly ensuring ZERO external API calls or quota consumption during tests.
    """

    def __init__(self) -> None:
        self.call_history: list[dict[str, Any]] = []

    def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        response_schema: dict[str, Any] | None = None,
    ) -> MockLLMResponse:
        self.call_history.append({
            "prompt": prompt,
            "system_prompt": system_prompt,
            "temperature": temperature,
            "response_schema": response_schema,
        })

        # Return mock JSON if a schema is requested
        if response_schema:
            return MockLLMResponse('{"route": "SINGLE_SEARCH", "relevance_score": 0.95, "is_relevant": true}')
        return MockLLMResponse("Mock compliance response strictly generated offline.")


@pytest.fixture
def mock_llm() -> MockLLMClient:
    """Fixture providing an offline Mock LLM client."""
    return MockLLMClient()


@pytest.fixture
def test_db() -> Generator[sqlite3.Connection, None, None]:
    """In-memory SQLite connection with full schema initialized."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(SCHEMA_DDL)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def repo(test_db: sqlite3.Connection) -> Repository:
    """Repository instance bound to the in-memory test database."""
    return Repository(test_db)
