"""Regression tests for independent per-user/per-IP API rate limiting."""

import time
import uuid

from fastapi.testclient import TestClient

from src.api.main import app
from src.config import settings
from src.core.rate_limiter import SlidingWindowRateLimiter, api_rate_limiter
from src.core.spend_guard import spend_guard


def test_sliding_window_isolates_buckets_and_recovers_after_window() -> None:
    now = [100.0]
    limiter = SlidingWindowRateLimiter(clock=lambda: now[0])

    assert limiter.check_and_record("query:user:1:127.0.0.1", limit=2, window_seconds=60.0) == 1
    assert limiter.check_and_record("query:user:1:127.0.0.1", limit=2, window_seconds=60.0) == 0

    try:
        limiter.check_and_record("query:user:1:127.0.0.1", limit=2, window_seconds=60.0)
        raise AssertionError("Expected RateLimitExceededError")
    except Exception as exc:
        assert getattr(exc, "http_status", None) == 429
        assert getattr(exc, "error_code", None) == "RATE_LIMIT_EXCEEDED"
        assert getattr(exc, "retry_after", 0) >= 1

    # Different user/IP bucket must stay unaffected.
    assert limiter.check_and_record("query:user:2:127.0.0.1", limit=2, window_seconds=60.0) == 1

    # Advancing clock past 60s window opens the bucket again.
    now[0] += 61.0
    assert limiter.check_and_record("query:user:1:127.0.0.1", limit=2, window_seconds=60.0) == 1


def test_api_rate_limiter_triggers_429_independently_of_spend_guard(
    auth_headers,
    monkeypatch,
) -> None:
    api_rate_limiter.clear()
    spend_guard.reset_all()
    monkeypatch.setattr(settings, "API_RATE_LIMIT_PER_MINUTE", 2)

    client = TestClient(app)
    headers = auth_headers("analyst")
    sess_resp = client.post("/api/v1/sessions", json={"title": "Rate limit test"}, headers=headers)
    assert sess_resp.status_code == 201
    session_id = sess_resp.json()["id"]

    for _ in range(2):
        ok = client.post(
            "/api/v1/chat/query",
            json={"session_id": session_id, "query": "Hello"},
            headers=headers,
        )
        assert ok.status_code == 200

    blocked = client.post(
        "/api/v1/chat/query",
        json={"session_id": session_id, "query": "Hello again"},
        headers=headers,
    )
    assert blocked.status_code == 429
    assert blocked.headers.get("Retry-After") is not None
    err = blocked.json()["error"]
    assert err["code"] == "RATE_LIMIT_EXCEEDED"
    assert "LLM_MAX" not in err["message"]
    assert spend_guard.exhausted is False

    # A second role/user retains an independent quota bucket.
    mgr_headers = auth_headers("manager")
    mgr_sess = client.post("/api/v1/sessions", json={"title": "Mgr rate limit"}, headers=mgr_headers).json()["id"]
    mgr_ok = client.post(
        "/api/v1/chat/query",
        json={"session_id": mgr_sess, "query": "Hello"},
        headers=mgr_headers,
    )
    assert mgr_ok.status_code == 200
    api_rate_limiter.clear()
