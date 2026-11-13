"""Regression tests for profile-aware, run-scoped SpendGuard and LLM gateway quotas."""

from __future__ import annotations

import threading
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.config import ResolvedLLM, settings
from src.core.llm_client import ResilientLLMClient
from src.core.spend_guard import SpendGuard, SpendGuardExceededError, spend_guard


def test_resolved_profile_exposes_local_and_paid_quota_flags() -> None:
    """Profile quota semantics live on ResolvedLLM in src.config, never ad-hoc in llm_client."""
    mock_cfg = ResolvedLLM(profile="mock", model="mock", is_mock=True)
    assert mock_cfg.is_local is True
    assert mock_cfg.has_paid_quota is False

    local_dev = ResolvedLLM(
        profile="dev",
        model="qwen2.5:7b-instruct",
        base_url="http://localhost:11434/v1",
        api_key="ollama",
        is_mock=False,
    )
    assert local_dev.is_local is True
    assert local_dev.has_paid_quota is False

    paid_demo = ResolvedLLM(
        profile="demo",
        model="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        api_key="sk-test-demo",
        is_mock=False,
    )
    assert paid_demo.is_local is False
    assert paid_demo.has_paid_quota is True


def test_mock_profile_bypasses_paid_quota_over_25_multiturn_session(
    auth_headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 26-turn offline session under mock profile completes with zero spend-limit errors."""
    monkeypatch.setattr(spend_guard, "max_calls", 5)
    monkeypatch.setattr(spend_guard, "max_tokens", 100)
    spend_guard.reset()

    client = TestClient(app)
    headers = auth_headers("analyst")
    sess_resp = client.post("/api/v1/sessions", json={"title": "Offline 26-turn soak"}, headers=headers)
    assert sess_resp.status_code == 201
    session_id = sess_resp.json()["id"]

    questions = [
        "What are the KYC verification rules for high-risk clients?",
        "What capital conservation buffer applies under Basel III?",
        "How long must CDD records be retained?",
        "Explain enhanced due diligence triggers for PEPs.",
        "Can we override sanctions screening on urgent wires?",
    ]
    for turn in range(26):
        q = f"{questions[turn % len(questions)]} (turn {turn + 1})"
        resp = client.post(
            "/api/v1/chat/query",
            json={"session_id": session_id, "query": q, "intent_mode": "rag"},
            headers=headers,
        )
        assert resp.status_code == 200, f"Turn {turn + 1} failed with {resp.status_code}: {resp.text}"
        body = resp.json()
        assert body["spend"]["exhausted"] is False
        assert body["spend"]["is_paid"] is False
        assert body["spend"]["profile"] == "mock"
        assert body["spend"]["scope"] == "offline"


def test_local_dev_ollama_bypasses_paid_cap_but_tracks_local_telemetry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local Ollama dev runs never abort with paid-quota errors; only high safety ceiling applies."""
    guard = SpendGuard(max_calls=2, max_tokens=200, safety_max_calls=50, safety_max_tokens=50_000)

    local_resolved = ResolvedLLM(
        profile="dev",
        model="qwen2.5:7b-instruct",
        base_url="http://127.0.0.1:11434/v1",
        api_key="ollama",
        is_mock=False,
    )

    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "Local regulatory summary."}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8},
            },
        )
    )
    llm_client = ResilientLLMClient(
        resolved_override=local_resolved,
        transport=transport,
        spend_guard_instance=guard,
    )

    # Exceeds paid cap (2 calls / 200 tokens) cleanly without error
    for i in range(6):
        res = llm_client.complete(
            f"Local dev question {i} {uuid.uuid4()}",
            step="answer",
            force_cache_refresh=True,
        )
        assert "Local regulatory summary" in res.content

    snap = guard.status(profile="dev", has_paid_quota=local_resolved.has_paid_quota, is_local=local_resolved.is_local)
    assert snap.exhausted is False
    assert snap.scope == "local"
    assert snap.is_paid is False
    assert snap.paid_calls == 0
    assert snap.paid_tokens == 0
    assert snap.local_calls == 6
    assert snap.local_tokens == 120


def test_paid_live_profile_still_hard_stops_at_cap() -> None:
    """A live/paid profile must still enforce max_calls cleanly before overshoot."""
    guard = SpendGuard(max_calls=2, max_tokens=10_000)
    paid_resolved = ResolvedLLM(
        profile="demo",
        model="gpt-4o-mini",
        base_url="https://api.openai.com/v1",
        api_key="sk-test-only",
        is_mock=False,
    )

    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": f"Paid response {call_count}"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    llm_client = ResilientLLMClient(
        resolved_override=paid_resolved,
        transport=httpx.MockTransport(_handler),
        spend_guard_instance=guard,
    )

    assert llm_client.complete("Q1", step="answer", force_cache_refresh=True).content == "Paid response 1"
    assert llm_client.complete("Q2", step="answer", force_cache_refresh=True).content == "Paid response 2"

    with pytest.raises(SpendGuardExceededError) as exc_info:
        llm_client.complete("Q3", step="answer", force_cache_refresh=True)

    # Never called upstream API on the blocked 3rd attempt
    assert call_count == 2
    assert guard.paid_calls_count == 2
    snap = guard.status(profile="demo", has_paid_quota=True, is_local=False)
    assert snap.exhausted is True
    assert snap.is_paid is True
    assert snap.scope == "paid"

    msg = str(exc_info.value)
    assert "LLM_MAX" not in msg
    assert "DEMO_" not in msg
    assert "\\" not in msg
    assert "session" in msg.lower() or "budget" in msg.lower()


def test_atomic_check_then_act_has_no_overshoot_under_concurrency() -> None:
    """Concurrent callers sharing a paid run_id never overshoot max_calls."""
    guard = SpendGuard(max_calls=3, max_tokens=50_000)
    successes = 0
    blocked = 0
    lock = threading.Lock()

    def _worker() -> None:
        nonlocal successes, blocked
        try:
            guard.reserve_call(profile="demo", has_paid_quota=True, is_local=False, run_id="concurrent-run")
            guard.commit_usage(10, 10, profile="demo", has_paid_quota=True, is_local=False, run_id="concurrent-run")
            with lock:
                successes += 1
        except SpendGuardExceededError:
            with lock:
                blocked += 1

    threads = [threading.Thread(target=_worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert successes == 3
    assert blocked == 7
    snap = guard.status(profile="demo", has_paid_quota=True, is_local=False, run_id="concurrent-run")
    assert snap.paid_calls == 3
    assert snap.exhausted is True


def test_per_session_run_isolation_and_reset() -> None:
    """Exhausting paid budget in session A must not exhaust session B or persist after reset."""
    guard = SpendGuard(max_calls=1, max_tokens=5_000)

    guard.reserve_call(profile="demo", has_paid_quota=True, is_local=False, run_id="session-a")
    guard.commit_usage(10, 10, profile="demo", has_paid_quota=True, is_local=False, run_id="session-a")

    snap_a = guard.status(profile="demo", has_paid_quota=True, is_local=False, run_id="session-a")
    assert snap_a.exhausted is True

    # Session B is untouched
    snap_b = guard.status(profile="demo", has_paid_quota=True, is_local=False, run_id="session-b")
    assert snap_b.exhausted is False
    assert snap_b.paid_calls == 0

    guard.reserve_call(profile="demo", has_paid_quota=True, is_local=False, run_id="session-b")
    guard.commit_usage(5, 5, profile="demo", has_paid_quota=True, is_local=False, run_id="session-b")

    # Explicit reset clears only the targeted run
    guard.reset(run_id="session-a")
    snap_a_reset = guard.status(profile="demo", has_paid_quota=True, is_local=False, run_id="session-a")
    assert snap_a_reset.exhausted is False
    assert snap_a_reset.paid_calls == 0


def test_local_safety_ceiling_never_returns_paid_429() -> None:
    """Runaway local-dev loop hits LocalSafetyLimitError (HTTP 503 LOCAL_SAFETY_LIMIT, not 429)."""
    from src.core.spend_guard import LocalSafetyLimitError

    guard = SpendGuard(max_calls=1, max_tokens=50, safety_max_calls=2, safety_max_tokens=5000)
    local_resolved = ResolvedLLM(
        profile="dev",
        model="qwen2.5:7b-instruct",
        base_url="http://localhost:11434/v1",
        api_key="ollama",
        is_mock=False,
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Local output"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 5}},
        )
    )
    llm_client = ResilientLLMClient(resolved_override=local_resolved, transport=transport, spend_guard_instance=guard)

    llm_client.complete("L1", force_cache_refresh=True)
    llm_client.complete("L2", force_cache_refresh=True)
    with pytest.raises(LocalSafetyLimitError) as exc_info:
        llm_client.complete("L3", force_cache_refresh=True)

    err = exc_info.value
    assert err.http_status == 503
    assert err.error_code == "LOCAL_SAFETY_LIMIT"
    assert "LLM_MAX" not in err.user_message
    assert "LOCAL_SAFETY" not in err.user_message


def test_api_session_budget_exhausted_and_cleared_by_new_run_or_new_session(
    auth_headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Paid cap returns sanitized 429; another session or POST /new-run works immediately."""
    from src.core.spend_guard import CallCapExceededError

    monkeypatch.setattr(spend_guard, "max_calls", 1)
    spend_guard.reset_all()

    client = TestClient(app)
    headers = auth_headers("analyst")
    sess_a = client.post("/api/v1/sessions", json={"title": "Paid Session A"}, headers=headers).json()["id"]
    sess_b = client.post("/api/v1/sessions", json={"title": "Paid Session B"}, headers=headers).json()["id"]

    # Simulate exhausted paid budget on session A via direct guard call
    spend_guard.reserve_call(profile="demo", has_paid_quota=True, is_local=False, run_id=f"session:{sess_a}")
    spend_guard.commit_usage(10, 10, profile="demo", has_paid_quota=True, is_local=False, run_id=f"session:{sess_a}")

    with spend_guard.run_scope(f"session:{sess_a}", profile="demo", has_paid_quota=True, is_local=False):
        with pytest.raises(CallCapExceededError) as exc_info:
            spend_guard.check_call_allowed()
        assert exc_info.value.http_status == 429
        assert exc_info.value.error_code == "LLM_SPEND_LIMIT"
        assert "LLM_MAX" not in exc_info.value.user_message

    # Session B remains unaffected in isolation
    assert spend_guard.status(profile="demo", has_paid_quota=True, is_local=False, run_id=f"session:{sess_b}").exhausted is False

    # Reset via API endpoint restores session A budget cleanly
    reset_resp = client.post(f"/api/v1/sessions/{sess_a}/new-run", headers=headers)
    assert reset_resp.status_code == 200
    assert reset_resp.json()["exhausted"] is False
    assert spend_guard.status(profile="demo", has_paid_quota=True, is_local=False, run_id=f"session:{sess_a}").paid_calls == 0

