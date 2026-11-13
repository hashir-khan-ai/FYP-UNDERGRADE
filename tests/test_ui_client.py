"""Phase 6B unit tests for the Streamlit UI API client and UI helpers.

Runs 100% offline using ``httpx.MockTransport`` under ``LLM_PROFILE=mock``.
"""

import json
from pathlib import Path

import httpx
import pytest

from src.ui.api_client import (
    ComplianceAPIClient,
    UIApiError,
    is_refusal_response,
    profile_badge_meta,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_login_me_and_logout_flow() -> None:
    """Client sends credentials, attaches bearer token on /me, and revokes on /logout."""
    seen_headers: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(dict(request.headers))
        if request.url.path == "/api/v1/auth/login":
            body = json.loads(request.content.decode("utf-8"))
            assert body == {"username": "analyst_user", "password": "secret-password"}
            return httpx.Response(
                200,
                json={
                    "access_token": "tok-123",
                    "token_type": "bearer",
                    "user": {
                        "id": 1,
                        "username": "analyst_user",
                        "full_name": "Alex Analyst",
                        "role": "analyst",
                    },
                },
            )
        if request.url.path == "/api/v1/auth/me":
            assert request.headers.get("authorization") == "Bearer tok-123"
            return httpx.Response(
                200,
                json={
                    "id": 1,
                    "username": "analyst_user",
                    "full_name": "Alex Analyst",
                    "role": "analyst",
                },
            )
        if request.url.path == "/api/v1/auth/logout":
            assert request.headers.get("authorization") == "Bearer tok-123"
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(404)

    client = ComplianceAPIClient(transport=httpx.MockTransport(handler))
    login_res = client.login("  analyst_user ", "secret-password")
    assert login_res["access_token"] == "tok-123"
    assert login_res["user"]["role"] == "analyst"

    me_res = client.get_me("tok-123")
    assert me_res["role"] == "analyst"

    logout_res = client.logout("tok-123")
    assert logout_res["status"] == "ok"


def test_session_lifecycle_and_chat_query_never_sends_client_role() -> None:
    """Chat query payload sends only session_id and query; role comes from server token."""
    captured_chat_body: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/sessions" and request.method == "POST":
            return httpx.Response(
                201,
                json={"id": "sess-001", "title": "Basel Session"},
            )
        if request.url.path == "/api/v1/sessions" and request.method == "GET":
            return httpx.Response(
                200,
                json={"sessions": [{"id": "sess-001", "title": "Basel Session"}]},
            )
        if request.url.path == "/api/v1/chat/query" and request.method == "POST":
            captured_chat_body.update(json.loads(request.content.decode("utf-8")))
            return httpx.Response(
                200,
                json={
                    "session_id": "sess-001",
                    "answer": "Minimum CET1 ratio is 4.5%.",
                    "route_taken": "SINGLE_SEARCH",
                    "route": "SINGLE_SEARCH",
                    "citations": [
                        {
                            "chunk_id": "CH-001",
                            "doc_id": "DOC-BASEL",
                            "doc_name": "Basel III",
                            "doc_title": "Basel III",
                            "section_title": "Part 1",
                            "heading_path": "Part 1 > 1.1 CET1",
                            "clause_id": "1.1",
                            "clause": "1.1",
                            "page_number": 1,
                            "page": 1,
                            "snippet": "Minimum CET1 ratio is 4.5%.",
                            "quote_snippet": "Minimum CET1 ratio is 4.5%.",
                        }
                    ],
                    "reasoning_trace": [
                        "Step 1: Question rewritten: no.",
                        "Step 2: Route: SINGLE_SEARCH.",
                    ],
                    "citations_dropped": 0,
                    "latency_ms": 12.5,
                    "role": "analyst",
                },
            )
        if request.url.path == "/api/v1/sessions/sess-001" and request.method == "DELETE":
            return httpx.Response(200, json={"status": "deleted", "session_id": "sess-001"})
        return httpx.Response(404)

    client = ComplianceAPIClient(transport=httpx.MockTransport(handler))
    created = client.create_session("tok-123", "Basel Session")
    assert created["id"] == "sess-001"

    sessions = client.list_sessions("tok-123")
    assert len(sessions) == 1

    chat_res = client.ask_chat_query("tok-123", "sess-001", "What is CET1?")
    assert captured_chat_body == {"session_id": "sess-001", "query": "What is CET1?"}
    assert "role" not in captured_chat_body
    assert chat_res["citations"][0]["heading_path"] == "Part 1 > 1.1 CET1"

    deleted = client.delete_session("tok-123", "sess-001")
    assert deleted["status"] == "deleted"


def test_error_responses_are_sanitized() -> None:
    """HTTP 401, 403, 429, and network errors raise sanitized UIApiError instances."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/audit/logs":
            return httpx.Response(
                403,
                json={"error": {"code": "FORBIDDEN", "message": "Role 'analyst' is not permitted."}},
            )
        if request.url.path == "/api/v1/chat/query":
            return httpx.Response(
                429,
                json={"error": {"code": "LLM_SPEND_LIMIT", "message": "Spend guard cap exceeded."}},
            )
        return httpx.Response(401, text="Unauthorized")

    client = ComplianceAPIClient(transport=httpx.MockTransport(handler))

    with pytest.raises(UIApiError) as exc_403:
        client.get_audit_logs("tok-analyst")
    assert exc_403.value.status_code == 403
    assert exc_403.value.code == "FORBIDDEN"

    with pytest.raises(UIApiError) as exc_429:
        client.ask_chat_query("tok-analyst", "sess-1", "Question?")
    assert exc_429.value.status_code == 429
    assert exc_429.value.code == "LLM_SPEND_LIMIT"


def test_refusal_and_profile_badge_helpers() -> None:
    """is_refusal_response detects refusal states and profile_badge_meta enforces palette tokens."""
    assert is_refusal_response({"answer": "I can't find that in the documents available to your role."})
    assert is_refusal_response({"answer": "Refused", "refusal_category": "insufficient_evidence"})
    assert is_refusal_response({"answer": "Refused", "grader": {"refused": True}})
    assert not is_refusal_response({"answer": "The minimum CET1 ratio is 4.5%.", "refusal_category": None})

    demo_badge = profile_badge_meta("demo")
    assert demo_badge["bg"] == "#FF5F00"
    assert demo_badge["fg"] == "#1C1D20"

    mock_badge = profile_badge_meta("mock")
    assert mock_badge["bg"] == "#5A6068"
    assert mock_badge["fg"] == "#F1F3F4"


def test_design_md_and_streamlit_theme_contract() -> None:
    """DESIGN.md and .streamlit/config.toml exist and specify the 60/30/10 colour tokens."""
    design_text = (REPO_ROOT / "DESIGN.md").read_text(encoding="utf-8")
    for token in ("#1C1D20", "#5A6068", "#FF5F00", "#F1F3F4"):
        assert token in design_text

    config_text = (REPO_ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    assert 'primaryColor = "#FF5F00"' in config_text
    assert 'backgroundColor = "#1C1D20"' in config_text
    assert 'textColor = "#F1F3F4"' in config_text


def test_ui_client_upload_document_serializes_roles() -> None:
    """upload_document serializes allowed_roles via json.dumps without NameError."""
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = request.read().decode("utf-8", errors="ignore")
        return httpx.Response(
            201,
            json={
                "doc_id": "DOC-UI-1",
                "filename": "policy.md",
                "title": "Policy",
                "chunks_indexed": 2,
                "allowed_roles": ["manager", "auditor"],
                "doc_type": "policy",
                "file_path": "policy.md",
                "message": "ok",
            },
        )

    client = ComplianceAPIClient(transport=httpx.MockTransport(handler))
    res = client.upload_document(
        token="tok-mgr",
        file_bytes=b"# Policy\nClause 1: Rule.",
        filename="policy.md",
        allowed_roles=["manager", "auditor"],
        title="Policy",
    )
    assert res["doc_id"] == "DOC-UI-1"
    assert captured["path"] == "/api/v1/documents/upload"
    assert '["manager", "auditor"]' in captured["body"]


