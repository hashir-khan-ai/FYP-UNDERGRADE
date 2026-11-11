"""Pytest configuration and zero-quota mock fixtures."""

import os
import sqlite3
from collections.abc import Generator
from pathlib import Path
from typing import Any
import pytest

from src.db.migrations import SCHEMA_DDL
from src.db.repository import Repository

# Force test environment variables
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_PATH"] = ":memory:"
os.environ["LLM_API_KEY"] = "mock-test-key-no-external-spend"
os.environ["FALLBACK_LLM_API_KEY"] = "mock-fallback-key"


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
