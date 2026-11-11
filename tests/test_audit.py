"""Audit trail tests: recorded fields, auditor-only access and no passage text."""

import json

from fastapi.testclient import TestClient

from src.api.main import app
from src.db.connection import get_db_connection

client = TestClient(app)


def _run_chat(headers: dict[str, str]) -> tuple[str, dict]:
    created = client.post("/api/v1/sessions", json={"title": "Audit session"}, headers=headers)
    assert created.status_code == 201
    session_id = created.json()["id"]

    response = client.post(
        "/api/v1/chat/query",
        json={"session_id": session_id, "query": "What CDD measures apply to corporate clients?"},
        headers=headers,
    )
    assert response.status_code == 200
    return session_id, response.json()


def test_chat_writes_complete_audit_row(auth_headers) -> None:
    session_id, body = _run_chat(auth_headers("manager"))

    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM audit_log WHERE id = ?;",
            (body["audit_id"],),
        ).fetchone()

    assert row is not None
    assert row["session_id"] == session_id
    assert row["user_role"] == "manager"
    assert row["final_route"] == "SINGLE_SEARCH"
    assert row["llm_profile"] == "mock"
    assert row["llm_model"] == "mock"
    assert row["latency_ms"] > 0
    assert row["candidates_retrieved"] >= 0
    assert row["candidates_filtered"] >= 0
    assert row["llm_calls"] >= 1
    assert row["prompt_version"] == "v1"

    chunk_ids = json.loads(row["retrieved_chunk_ids"])
    assert isinstance(chunk_ids, list)
    assert all(isinstance(chunk_id, str) and " " not in chunk_id for chunk_id in chunk_ids)

    # Passages are recorded as identifiers only; the trace holds no passage text.
    trace = " ".join(json.loads(row["reasoning_trace"]))
    assert "Section" not in trace
    assert row["query_text"] == "What CDD measures apply to corporate clients?"


def test_audit_logs_are_auditor_only(auth_headers) -> None:
    _run_chat(auth_headers("analyst"))

    assert client.get("/api/v1/audit/logs").status_code == 401

    for role in ("analyst", "manager"):
        response = client.get("/api/v1/audit/logs", headers=auth_headers(role))
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"

    auditor = client.get("/api/v1/audit/logs", headers=auth_headers("auditor"))
    assert auditor.status_code == 200
    logs = auditor.json()
    assert logs
    assert {"audit_id", "user_role", "retrieved_chunk_ids", "latency_ms"} <= set(logs[0])


def test_audit_endpoint_never_returns_secrets(auth_headers) -> None:
    _run_chat(auth_headers("manager"))
    response = client.get("/api/v1/audit/logs?limit=10", headers=auth_headers("auditor"))
    assert response.status_code == 200
    assert "argon2" not in response.text.lower()
    assert "authorization" not in response.text.lower()
    assert "access_token" not in response.text.lower()


def test_audit_log_filtering_by_user(auth_headers, seeded_auth_users) -> None:
    _run_chat(auth_headers("manager"))
    manager_id = seeded_auth_users["manager"]["id"]

    response = client.get(
        f"/api/v1/audit/logs?user_id={manager_id}&limit=5",
        headers=auth_headers("auditor"),
    )
    assert response.status_code == 200
    logs = response.json()
    assert logs
    assert all(log["user_id"] == manager_id for log in logs)


def test_audit_limit_is_bounded(auth_headers) -> None:
    headers = auth_headers("auditor")
    assert client.get("/api/v1/audit/logs?limit=0", headers=headers).status_code == 422
    assert client.get("/api/v1/audit/logs?limit=1000", headers=headers).status_code == 422


def test_admin_config_exposes_flags_without_secrets(auth_headers) -> None:
    response = client.get("/api/v1/admin/config", headers=auth_headers("analyst"))
    assert response.status_code == 200
    body = response.json()
    assert body["rbac_enabled"] is True
    assert body["layers"]["rbac"] is True
    assert body["spend_caps"]["calls_limit"] > 0
    assert "api_key" not in response.text.lower()
    assert "secret" not in response.text.lower()
