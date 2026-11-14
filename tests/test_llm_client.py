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
    """Verify the wrapper refuses paid-profile calls once the per-run call budget is exhausted."""
    import httpx
    import src.core.llm_client as llm_module
    from src.config import ResolvedLLM

    guard = SpendGuard(max_calls=1, max_tokens=10_000)
    monkeypatch.setattr(llm_module, "spend_guard", guard)
    paid_resolved = ResolvedLLM(
        profile="demo",
        model="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        api_key="sk-test-demo",
        is_mock=False,
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "Paid response 1."}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 6},
            },
        )
    )
    client = ResilientLLMClient(transport=transport, resolved_override=paid_resolved)

    first = client.complete(prompt="spend guard first prompt", force_cache_refresh=True)
    assert first.content == "Paid response 1."

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


def test_rate_limiter_is_thread_safe() -> None:
    """Concurrent threads acquiring slots must not race or corrupt deque state."""
    import concurrent.futures
    from src.core.llm_client import RateLimiter

    limiter = RateLimiter(max_rpm=200)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(limiter.acquire) for _ in range(32)]
        for fut in futures:
            fut.result()
    assert len(limiter.timestamps) == 32


def test_complete_json_prevents_cache_poisoning(monkeypatch: pytest.MonkeyPatch) -> None:
    """Malformed JSON outputs must never remain persisted in llm_cache."""
    client = ResilientLLMClient()
    prompt = "Prevent cache poisoning prompt 987654"
    monkeypatch.setattr(client, "_generate_mock_response", lambda p: "invalid json output")

    with pytest.raises(LLMClientError):
        client.complete_json(prompt=prompt, schema=SampleSchema, step="router")

    resolved = SimpleNamespace(
        profile="mock",
        model="mock-deterministic",
    )
    key = client._compute_cache_key(
        resolved.profile,
        resolved.model,
        prompt
        + '\n\nOUTPUT INSTRUCTION: Respond ONLY with a valid JSON object matching this schema:\n```json\n'
        + __import__("json").dumps(SampleSchema.model_json_schema(), indent=2)
        + "\n```\nDo not include explanation or text outside the JSON object.",
        None,
        0.0,
        1024,
        "router",
    )
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM llm_cache WHERE cache_key = ?;", (key,)).fetchone()
    assert row is None


def test_cache_hit_records_saved_tokens_without_paid_spend() -> None:
    """Cache hits increment per-run cache savings without consuming paid quota."""
    guard = SpendGuard(max_calls=1, max_tokens=5000)
    client = ResilientLLMClient(spend_guard_instance=guard)
    with guard.run_scope("cache-savings-run", profile="mock", has_paid_quota=False, is_local=True):
        first = client.complete(prompt="Unique savings prompt 112233", force_cache_refresh=True)
        second = client.complete(prompt="Unique savings prompt 112233")
        snap = guard.status(profile="mock", has_paid_quota=False, is_local=True)
    assert first.cached is False
    assert second.cached is True
    assert snap.cached_calls == 1
    assert snap.saved_tokens == second.total_tokens
    assert snap.paid_calls == 0


def test_offline_missing_weights_raise_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing offline HF model weights fail at load time with an actionable message."""
    import sentence_transformers
    from src.ingestion.embeddings import LocalCPUEmbeddings, ModelWeightsMissingError
    from src.rag.baseline import CrossEncoderReranker

    def boom(*args, **kwargs):
        raise OSError("LocalEntryNotFoundError: not in local cache")

    monkeypatch.setattr(sentence_transformers, "SentenceTransformer", boom)
    monkeypatch.setattr(sentence_transformers, "CrossEncoder", boom)

    embedder = LocalCPUEmbeddings(model_name="nonexistent/offline-model")
    with pytest.raises(ModelWeightsMissingError, match="offline mode"):
        embedder.embed_query("test")

    reranker = CrossEncoderReranker(model_name="nonexistent/offline-reranker")
    with pytest.raises(ModelWeightsMissingError, match="offline mode"):
        reranker.rerank("q", [{"chunk_id": "1", "text_content": "a"}, {"chunk_id": "2", "text_content": "b"}])


def test_revoke_role_on_document_invalidates_cached_answer() -> None:
    """(a) Revoking a role on a document alters the ACL version, making previous cached answers unreachable."""
    from src.core.acl_version import compute_index_acl_version
    from src.db.repository import Repository

    client = ResilientLLMClient()
    prompt = "Unique prompt for permission revocation test 998877"

    with get_db_connection() as conn:
        from src.db.repository import Repository
        repo = Repository(conn)
        # Register test document with auditor + manager roles
        repo.register_document(
            doc_id="DOC-REVOKE-TEST",
            filename="confidential_audit.md",
            source_jurisdiction="INTERNAL_UK",
            doc_type="AUDIT_REPORT",
            version="1.0",
            allowed_roles=["manager", "auditor"],
            file_path="data/synthetic/confidential_audit.md",
            total_chunks=5,
        )
        conn.commit()

        v1 = compute_index_acl_version(conn)
        key_before = client._compute_cache_key(
            profile="mock",
            model="mock-v1",
            prompt=prompt,
            system_prompt="sys",
            temperature=0.0,
            max_tokens=100,
            step="answer",
            role="manager",
            index_acl_version=v1,
        )

        # Populate cache with answer
        repo.set_cached_llm(key_before, "prompt_hash", "mock-v1", "Cached manager answer for doc", 10, 20)
        conn.commit()

        # Manager gets cached hit
        cached_row = repo.get_cached_llm(key_before)
        assert cached_row is not None
        assert cached_row["response_text"] == "Cached manager answer for doc"

        # REVOCATION: Revoke manager role, leaving only auditor
        repo.register_document(
            doc_id="DOC-REVOKE-TEST",
            filename="confidential_audit.md",
            source_jurisdiction="INTERNAL_UK",
            doc_type="AUDIT_REPORT",
            version="1.0",
            allowed_roles=["auditor"],  # Manager role revoked!
            file_path="data/synthetic/confidential_audit.md",
            total_chunks=5,
        )
        conn.commit()

        v2 = compute_index_acl_version(conn)
        assert v1 != v2, "ACL index version must change when roles are revoked"

        key_after = client._compute_cache_key(
            profile="mock",
            model="mock-v1",
            prompt=prompt,
            system_prompt="sys",
            temperature=0.0,
            max_tokens=100,
            step="answer",
            role="manager",
            index_acl_version=v2,
        )
        assert key_before != key_after

        # Previously cached answer is NOT served for the revoked role
        cached_after = repo.get_cached_llm(key_after)
        assert cached_after is None, "Cached answer must be unreachable after permission revocation!"


def test_cache_entries_expire_after_ttl_and_purged() -> None:
    """(b) Cache entries older than TTL expire and are removed by purge_expired_cache routine."""
    from src.config import settings
    from src.core.llm_client import purge_expired_cache
    from src.db.repository import Repository

    client = ResilientLLMClient()
    prompt = "Unique prompt for TTL expiration test 334455"
    key = client._compute_cache_key("mock", "mock-v1", prompt, None, 0.0, 100, "answer", role="analyst")

    with get_db_connection() as conn:
        from src.db.repository import Repository
        repo = Repository(conn)
        repo.set_cached_llm(key, "hash_ttl", "mock-v1", "Expiring answer", 10, 20)
        conn.commit()

        # Simulate backdating row created_at to 48 hours ago
        conn.execute(
            "UPDATE llm_cache SET created_at = datetime('now', '-48 hours') WHERE cache_key = ?;",
            (key,),
        )
        conn.commit()

        # 1. Freshness check: row is stale against 24h TTL
        stale_row = conn.execute("SELECT created_at FROM llm_cache WHERE cache_key = ?;", (key,)).fetchone()
        assert client._cache_row_is_fresh(stale_row["created_at"]) is False

        # 2. Startup purge routine purges entries older than TTL
        purged_count = purge_expired_cache(conn=conn, ttl_hours=24)
        assert purged_count >= 1

        # 3. Entry is completely deleted from database
        assert repo.get_cached_llm(key) is None


def test_cache_never_returns_answer_across_roles() -> None:
    """(c) The cache strictly partitions entries by role; an answer cached for auditor is never served to analyst."""
    client = ResilientLLMClient()
    prompt = "Explain confidential capital liquidity requirements."

    key_analyst = client._compute_cache_key("mock", "mock-v1", prompt, None, 0.0, 100, "answer", role="analyst")
    key_manager = client._compute_cache_key("mock", "mock-v1", prompt, None, 0.0, 100, "answer", role="manager")
    key_auditor = client._compute_cache_key("mock", "mock-v1", prompt, None, 0.0, 100, "answer", role="auditor")

    assert key_analyst != key_manager != key_auditor

    with get_db_connection() as conn:
        from src.db.repository import Repository
        repo = Repository(conn)
        repo.set_cached_llm(key_auditor, "hash_audit", "mock-v1", "Auditor-only confidential answer", 15, 30)
        conn.commit()

        # Auditor hit
        assert repo.get_cached_llm(key_auditor)["response_text"] == "Auditor-only confidential answer"

        # Analyst miss
        assert repo.get_cached_llm(key_analyst) is None

        # Manager miss
        assert repo.get_cached_llm(key_manager) is None



