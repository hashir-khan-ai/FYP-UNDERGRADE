"""Integration tests for the baseline FastAPI endpoints (now auth-protected)."""

import pytest
from fastapi.testclient import TestClient
from src.config import settings
from src.api.main import app

client = TestClient(app)


def test_health_check_endpoint() -> None:
    """Verify that GET /health returns 200 and reports mock profile under test."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("healthy", "degraded")
    assert data["llm"]["profile"] == "mock"
    assert data["llm"]["is_mock"] is True
    assert data["layers"]["adaptive_router"] == settings.ENABLE_ADAPTIVE_ROUTER
    assert data["layers"]["corrective_grader"] == settings.ENABLE_CORRECTIVE_GRADER
    assert data["layers"]["xai_output"] is False
    assert data["layers"]["rbac"] is True
    assert "vector_store" in data


def test_admin_health_requires_auth(auth_headers) -> None:
    """Verify the API.md health endpoint is authenticated."""
    assert client.get("/api/v1/admin/health").status_code == 401
    response = client.get("/api/v1/admin/health", headers=auth_headers("analyst"))
    assert response.status_code == 200
    assert response.json()["llm"]["profile"] == "mock"


def test_ask_requires_auth() -> None:
    """Verify unauthenticated retrieval is refused (no role can be assumed)."""
    response = client.post("/ask", json={"query": "What are the KYC requirements?"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_ask_endpoint_valid_query(auth_headers) -> None:
    """Verify that POST /ask returns a structured, role-scoped RAG response."""
    payload = {"query": "What are the KYC verification requirements?"}
    response = client.post("/ask", json=payload, headers=auth_headers("analyst"))
    assert response.status_code == 200

    data = response.json()
    assert "answer" in data
    assert len(data["answer"]) > 0
    assert "sources" in data
    assert "timings" in data
    assert "total_ms" in data["timings"]
    assert data["llm_profile"] == "mock"
    assert data["llm_model"] == "mock"
    assert data["role"] == "analyst"
    assert data["rbac_enabled"] is True
    for source in data["sources"]:
        assert {"chunk_id", "doc_title", "section", "page", "score"} <= set(source)
        assert "allowed_roles" not in source


def test_ask_empty_retrieval_returns_refusal(auth_headers, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify a corpus miss returns 200 with a refusal and no fabricated sources."""
    from src.rag.baseline import REFUSAL_TEXT

    monkeypatch.setattr(
        "src.api.main.baseline_pipeline.retrieve",
        lambda query, role: (
            [],
            0.0,
            {"candidates_retrieved": 0, "candidates_filtered_by_role": 0},
        ),
    )
    monkeypatch.setattr(
        "src.api.main.baseline_pipeline.rerank",
        lambda query, candidates, role: ([], 0.0, 0),
    )

    response = client.post(
        "/ask",
        json={"query": "Japanese FSA mortgage rules"},
        headers=auth_headers("analyst"),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == REFUSAL_TEXT
    assert data["sources"] == []
    assert data["chunk_ids_used"] == []


def test_ask_endpoint_empty_query_validation(auth_headers) -> None:
    """Verify that an empty or whitespace query is rejected with an error envelope."""
    response = client.post("/ask", json={"query": "   "}, headers=auth_headers("analyst"))
    assert response.status_code in (400, 422)
    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == "EMPTY_QUERY"


def test_ask_endpoint_missing_payload_validation(auth_headers) -> None:
    """Verify that an invalid payload triggers a 422 validation error envelope."""
    response = client.post("/ask", json={}, headers=auth_headers("analyst"))
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_localhost_cors_headers() -> None:
    """Verify that CORS headers allow localhost origin."""
    response = client.options(
        "/ask",
        headers={
            "Origin": "http://localhost:8501",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:8501"


def test_non_localhost_origin_is_rejected() -> None:
    """Verify disallowed origins receive no CORS allow-origin header."""
    response = client.options(
        "/ask",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.headers.get("access-control-allow-origin") not in (
        "*",
        "https://evil.example",
    )
