"""Unit tests for ResilientLLMClient, caching, retries, spend guard and JSON repair."""

import logging
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel, Field

from src.core.llm_client import (
    LLMClientError,
    LLMUnavailableError,
    ResilientLLMClient,
)
from src.core.spend_guard import SpendGuard, SpendGuardExceededError
from src.db.connection import get_db_connection


class SampleSchema(BaseModel):
    category: str = Field(..., description="Classification category")
    confidence: float = Field(..., description="Score between 0 and 1")


def test_cache_hit_and_miss() -> None:
    """Verify that repeated prompts with the same settings return cached responses."""
    client = ResilientLLMClient()
    prompt = "Unique compliance question for cache verification 12345"

    resp1 = client.complete(prompt=prompt, temperature=0.0, force_cache_refresh=True)
    assert resp1.cached is False
    assert len(resp1.content) > 0

    # Second call should be a cache hit and cost zero quota.
    resp2 = client.complete(prompt=prompt, temperature=0.0)
    assert resp2.cached is True
    assert resp2.content == resp1.content
    assert resp2.latency_ms == 0.0

    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT response_text FROM llm_cache WHERE cache_key IS NOT NULL LIMIT 1;"
        ).fetchall()
        assert rows
        telemetry = conn.execute(
            "SELECT cache_hit, cached, call_status FROM llm_calls ORDER BY id DESC LIMIT 1;"
        ).fetchone()
        assert telemetry["cache_hit"] == 1
        assert telemetry["cached"] == 1
        assert telemetry["call_status"] == "success"


def test_retry_backoff_on_safe_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify 5xx responses are retried with backoff and then succeed."""
    calls: list[httpx.Request] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "recovered"}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 2},
            },
        )

    monkeypatch.setattr("src.core.llm_client.time.sleep", lambda seconds: sleeps.append(seconds))
    client = ResilientLLMClient(transport=httpx.MockTransport(handler))
    resolved = SimpleNamespace(
        base_url="https://provider.invalid/v1",
        api_key="secret-key",
        model="test-model",
        max_retries=3,
        timeout_seconds=5.0,
        profile="dev",
    )

    content, prompt_tokens, completion_tokens = client._execute_with_retry(
        resolved_llm=resolved,
        prompt="hello",
        system_prompt=None,
        temperature=0.0,
        max_tokens=16,
    )

    assert content == "recovered"
    assert (prompt_tokens, completion_tokens) == (7, 2)
    assert len(calls) == 3
    assert len(sleeps) == 2
    assert sleeps[0] > 0 and sleeps[1] > sleeps[0]


def test_retry_stops_after_safe_error_budget() -> None:
    """Verify repeated 5xx responses end in a sanitized unavailable error."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "down"})

    client = ResilientLLMClient(transport=httpx.MockTransport(handler))
    resolved = SimpleNamespace(
        base_url="https://provider.invalid/v1",
        api_key="secret-key",
        model="test-model",
        max_retries=1,
        timeout_seconds=5.0,
        profile="dev",
    )

    with pytest.raises(LLMUnavailableError, match="unavailable"):
        client._execute_with_retry(
            resolved_llm=resolved,
            prompt="hello",
            system_prompt=None,
            temperature=0.0,
            max_tokens=16,
        )


def test_non_retryable_status_is_not_retried() -> None:
    """Verify a 400 response fails immediately without retry."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(400, json={"error": "bad request"})

    client = ResilientLLMClient(transport=httpx.MockTransport(handler))
    resolved = SimpleNamespace(
        base_url="https://provider.invalid/v1",
        api_key="secret-key",
        model="test-model",
        max_retries=3,
        timeout_seconds=5.0,
        profile="dev",
    )

    with pytest.raises(LLMUnavailableError, match="HTTP 400"):
        client._execute_with_retry(
            resolved_llm=resolved,
            prompt="hello",
            system_prompt=None,
            temperature=0.0,
            max_tokens=16,
        )
    assert len(calls) == 1


def test_spend_guard_cap_enforcement() -> None:
    """Verify that SpendGuard halts execution when call budget is exhausted."""
    guard = SpendGuard(max_calls=2, max_tokens=1000)

    guard.check_call_allowed()
    guard.record_usage(10, 20)
    assert guard.calls_count == 1

    guard.check_call_allowed()
    guard.record_usage(10, 20)
    assert guard.calls_count == 2

    # Third call should raise SpendGuardExceededError
    with pytest.raises(SpendGuardExceededError, match="Spend guard cap exceeded"):
        guard.check_call_allowed()


def test_spend_guard_token_cap_enforcement() -> None:
    """Verify that SpendGuard halts execution when token budget is exhausted."""
    guard = SpendGuard(max_calls=10, max_tokens=100)

    guard.check_call_allowed()
    guard.record_usage(50, 40)
    assert guard.tokens_count == 90

    # Adding 20 tokens exceeds 100 limit
    with pytest.raises(SpendGuardExceededError, match="token cap exceeded"):
        guard.record_usage(10, 15)


def test_complete_json_repair_and_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify that complete_json applies caller fallback when raw output is invalid JSON."""
    client = ResilientLLMClient()

    # Mock response returning non-JSON text
    monkeypatch.setattr(client, "_generate_mock_response", lambda prompt: "This is definitely not valid JSON.")

    fallback_obj = SampleSchema(category="SAFE_FALLBACK", confidence=0.0)
    result = client.complete_json(
        prompt="Classify this request",
        schema=SampleSchema,
        fallback=fallback_obj,
    )

    assert result.category == "SAFE_FALLBACK"
    assert result.confidence == 0.0


def test_complete_json_repairs_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify exactly one repair retry can recover a malformed first response."""
    client = ResilientLLMClient()
    responses = iter(
        [
            "not json at all",
            '{"category": "REPAIRED", "confidence": 0.75}',
        ]
    )
    monkeypatch.setattr(client, "_generate_mock_response", lambda prompt: next(responses))

    result = client.complete_json(prompt="Classify this repair case", schema=SampleSchema)
    assert result.category == "REPAIRED"
    assert result.confidence == 0.75


def test_complete_json_raises_without_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify invalid JSON without a fallback raises a sanitized client error."""
    client = ResilientLLMClient()
    monkeypatch.setattr(client, "_generate_mock_response", lambda prompt: "still not json")

    with pytest.raises(LLMClientError, match="one repair retry"):
        client.complete_json(prompt="Classify this failing case", schema=SampleSchema)


def test_client_spend_guard_stops_before_second_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the wrapper refuses calls once the per-run call budget is exhausted."""
    import src.core.llm_client as llm_module

    guard = SpendGuard(max_calls=1, max_tokens=10_000)
    monkeypatch.setattr(llm_module, "spend_guard", guard)
    client = ResilientLLMClient()

    first = client.complete(prompt="spend guard first prompt", force_cache_refresh=True)
    assert first.content

    with pytest.raises(SpendGuardExceededError, match="Spend guard cap exceeded"):
        client.complete(prompt="spend guard second prompt", force_cache_refresh=True)


def test_no_api_keys_leaked_in_logs(caplog: pytest.LogCaptureFixture) -> None:
    """Verify that API keys or auth headers are never logged."""
    client = ResilientLLMClient()
    secret_key = "gsk_super_secret_test_key_xyz987"

    with caplog.at_level(logging.DEBUG):
        client.complete("Check regulatory compliance requirement")

    for record in caplog.records:
        assert secret_key not in record.getMessage()
        assert "Bearer" not in record.getMessage()
        assert "gsk_" not in record.getMessage()

