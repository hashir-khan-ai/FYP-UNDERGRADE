"""Session ownership (IDOR) and chat/session API contract tests."""

import json
import uuid

from fastapi.testclient import TestClient

from src.api.main import app
from src.db.connection import get_db_connection

client = TestClient(app)


def _create_session(headers: dict[str, str], title: str = "Compliance session") -> str:
    response = client.post("/api/v1/sessions", json={"title": title}, headers=headers)
    assert response.status_code == 201
    return response.json()["id"]


def test_session_endpoints_require_authentication() -> None:
    assert client.get("/api/v1/sessions").status_code == 401
    assert client.post("/api/v1/sessions", json={}).status_code == 401
    assert client.get(f"/api/v1/sessions/{uuid.uuid4()}/messages").status_code == 401
    assert client.delete(f"/api/v1/sessions/{uuid.uuid4()}").status_code == 401
    assert client.patch(
        f"/api/v1/sessions/{uuid.uuid4()}", json={"title": "Renamed"}
    ).status_code == 401


def test_create_and_list_only_own_sessions(auth_headers) -> None:
    analyst = auth_headers("analyst")
    manager = auth_headers("manager")

    first = _create_session(analyst, "Analyst KYC")
    second = _create_session(analyst, "Analyst AML")

    listing = client.get("/api/v1/sessions", headers=analyst)
    assert listing.status_code == 200
    ids = {item["id"] for item in listing.json()["sessions"]}
    assert {first, second} <= ids

    manager_listing = client.get("/api/v1/sessions", headers=manager)
    manager_ids = {item["id"] for item in manager_listing.json()["sessions"]}
    assert first not in manager_ids
    assert second not in manager_ids


def test_chat_persists_turns_with_role_and_metadata(auth_headers) -> None:
    headers = auth_headers("analyst")
    session_id = _create_session(headers)

    response = client.post(
        "/api/v1/chat/query",
        json={
            "session_id": session_id,
            "query": "What are the KYC verification requirements for high-risk clients?",
        },
        headers=headers,
    )
    assert response.status_code == 200

    body = response.json()
    assert body["session_id"] == session_id
    assert body["route_taken"] == "SINGLE_SEARCH"
    assert "answer" in body and body["answer"]
    assert body["role"] == "analyst"
    assert body["rbac_enabled"] is True
    assert body["retrieval_stats"]["retry_count"] == 0
    assert body["retrieval_stats"]["rewritten_query"] is None
    assert body["llm_stats"]["profile"] == "mock"
    assert body["spend"]["calls_limit"] > 0
    assert body["audit_id"] > 0
    for citation in body["citations"]:
        assert {"doc_id", "doc_name", "section_title", "clause_id", "snippet"} <= set(citation)

    history = client.get(f"/api/v1/sessions/{session_id}/messages", headers=headers)
    assert history.status_code == 200
    messages = history.json()["messages"]
    assert len(messages) == 2
    assert messages[0]["sender"] == "user"
    assert messages[0]["user_role"] == "analyst"
    assert messages[1]["sender"] == "assistant"
    assert messages[1]["route_used"] == "SINGLE_SEARCH"
    assert isinstance(messages[1]["metadata"]["chunk_ids"], list)
    assert messages[1]["metadata"]["cached"] is not None
    # Reload parity: the owner can re-render citations, grounding and trace
    # without calling the audit endpoint.
    assert messages[1]["metadata"]["citations"] == body["citations"]
    assert messages[1]["metadata"]["reasoning_trace"] == body["reasoning_trace"]
    assert messages[1]["metadata"]["grounded"] == body["grounded"]
    assert messages[1]["metadata"]["response_type"] == body["response_type"]
    assert messages[1]["metadata"]["refusal_category"] == body["refusal_category"]
    assert (
        messages[1]["metadata"]["suggested_follow_ups"]
        == body["suggested_follow_ups"]
    )
    assert "system_prompt" not in json.dumps(messages[1]["metadata"]).lower()


def test_idor_cannot_read_or_delete_another_users_session(auth_headers) -> None:
    owner = auth_headers("auditor")
    attacker = auth_headers("analyst")
    session_id = _create_session(owner, "Auditor confidential review")

    read = client.get(f"/api/v1/sessions/{session_id}/messages", headers=attacker)
    assert read.status_code == 404
    assert read.json()["error"]["code"] == "SESSION_NOT_FOUND"

    delete = client.delete(f"/api/v1/sessions/{session_id}", headers=attacker)
    assert delete.status_code == 404

    chat = client.post(
        "/api/v1/chat/query",
        json={"session_id": session_id, "query": "Summarise the audit findings"},
        headers=attacker,
    )
    assert chat.status_code == 404

    # The owner still has full access.
    assert client.get(f"/api/v1/sessions/{session_id}/messages", headers=owner).status_code == 200


def test_unknown_session_returns_404(auth_headers) -> None:
    headers = auth_headers("manager")
    missing = str(uuid.uuid4())
    assert client.get(f"/api/v1/sessions/{missing}/messages", headers=headers).status_code == 404
    assert client.delete(f"/api/v1/sessions/{missing}", headers=headers).status_code == 404


def test_invalid_session_uuid_is_rejected(auth_headers) -> None:
    response = client.post(
        "/api/v1/chat/query",
        json={"session_id": "not-a-uuid", "query": "What are the CDD rules?"},
        headers=auth_headers("analyst"),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_delete_own_session_cascades_messages(auth_headers) -> None:
    headers = auth_headers("analyst")
    session_id = _create_session(headers, "Temporary session")
    assert client.post(
        "/api/v1/chat/query",
        json={"session_id": session_id, "query": "What are the CDD rules?"},
        headers=headers,
    ).status_code == 200

    deleted = client.delete(f"/api/v1/sessions/{session_id}", headers=headers)
    assert deleted.status_code == 200

    with get_db_connection() as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) AS total FROM messages WHERE session_id = ?;",
            (session_id,),
        ).fetchone()["total"]
    assert remaining == 0
    assert client.get(f"/api/v1/sessions/{session_id}/messages", headers=headers).status_code == 404


def test_chat_rejects_blank_query(auth_headers) -> None:
    headers = auth_headers("analyst")
    session_id = _create_session(headers)
    response = client.post(
        "/api/v1/chat/query",
        json={"session_id": session_id, "query": "   "},
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "EMPTY_QUERY"


def test_rename_session_is_owner_scoped(auth_headers) -> None:
    owner = auth_headers("manager")
    other = auth_headers("auditor")
    session_id = _create_session(owner, "Draft escalation review")

    renamed = client.patch(
        f"/api/v1/sessions/{session_id}",
        json={"title": "  Escalation runbook  "},
        headers=owner,
    )
    assert renamed.status_code == 200
    assert renamed.json()["id"] == session_id
    assert renamed.json()["title"] == "Escalation runbook"

    foreign = client.patch(
        f"/api/v1/sessions/{session_id}",
        json={"title": "Hijacked"},
        headers=other,
    )
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "SESSION_NOT_FOUND"

    # The original owner's title is unchanged by the failed foreign attempt.
    listing = client.get("/api/v1/sessions", headers=owner).json()["sessions"]
    assert next(item for item in listing if item["id"] == session_id)["title"] == (
        "Escalation runbook"
    )


def test_rename_session_rejects_blank_and_overlong_titles(auth_headers) -> None:
    headers = auth_headers("analyst")
    session_id = _create_session(headers)

    blank = client.patch(
        f"/api/v1/sessions/{session_id}",
        json={"title": "   "},
        headers=headers,
    )
    assert blank.status_code == 400
    assert blank.json()["error"]["code"] == "EMPTY_TITLE"

    too_long = client.patch(
        f"/api/v1/sessions/{session_id}",
        json={"title": "x" * 121},
        headers=headers,
    )
    assert too_long.status_code == 422
    assert too_long.json()["error"]["code"] == "VALIDATION_ERROR"
