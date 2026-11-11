"""Pytest configuration and zero-quota mock fixtures."""

import os
import sqlite3
from collections.abc import Generator
from pathlib import Path
from typing import Any
import pytest

# Force the zero-quota test environment BEFORE importing application settings.
os.environ["APP_ENV"] = "test"
os.environ["LLM_PROFILE"] = "mock"
os.environ["DATABASE_PATH"] = ":memory:"

from src.db.migrations import SCHEMA_DDL  # noqa: E402
from src.db.repository import Repository  # noqa: E402
from src.config import settings  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _force_mock_llm_profile() -> None:
    """Fail the session immediately if tests could reach a live LLM."""
    assert settings.LLM_PROFILE == "mock"
    assert settings.llm.is_mock is True


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
