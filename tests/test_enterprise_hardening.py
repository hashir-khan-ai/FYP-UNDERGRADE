"""Enterprise hardening tests: correlation IDs, /ready, /admin/metrics, audit filters, offline fallback."""

from __future__ import annotations

import logging
from fastapi.testclient import TestClient

from src.api.main import app
from src.config import ResolvedLLM, settings
from src.core.telemetry import CorrelationLogFilter
from src.ingestion.embeddings import FakeEmbeddingGenerator
from src.ingestion.indexer import QdrantIndexer, SearchResult
from src.rag.baseline import baseline_pipeline
from tests.conftest import TEST_AUTH_PASSWORD


def _login_headers(client: TestClient, username: str) -> dict[str, str]:
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": TEST_AUTH_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_request_correlation_headers_and_sanitized_logs(
    seeded_auth_users,
    caplog,
) -> None:
    """Every API response includes X-Request-ID and structured logs link request_id & audit_id without secrets."""
    api_logger = logging.getLogger("api")
    filt = CorrelationLogFilter()
    api_logger.addFilter(filt)
    caplog.set_level(logging.INFO, logger="api")

    try:
        with TestClient(app) as client:
            r_auto = client.get("/health")
            assert r_auto.status_code == 200
            assert "X-Request-ID" in r_auto.headers
            assert len(r_auto.headers["X-Request-ID"]) == 16

            r_echo = client.get("/health", headers={"X-Request-ID": "trace-req-007"})
            assert r_echo.status_code == 200
            assert r_echo.headers["X-Request-ID"] == "trace-req-007"

            # Malformed / injection headers must be replaced by a safe generated ID.
            r_bad = client.get("/health", headers={"X-Request-ID": "bad id; drop table"})
            assert r_bad.status_code == 200
            assert r_bad.headers["X-Request-ID"] != "bad id; drop table"
            assert len(r_bad.headers["X-Request-ID"]) == 16

            headers = _login_headers(client, "analyst_user")
            sess = client.post("/api/v1/sessions", headers=headers, json={"title": "Corr check"})
            assert sess.status_code == 201
            session_id = sess.json()["id"]

            secret_query = "What are KYC customer identification requirements?"
            turn = client.post(
                "/api/v1/chat/query",
                headers={**headers, "X-Request-ID": "corr-turn-42"},
                json={"session_id": session_id, "query": secret_query},
            )
            assert turn.status_code == 200, turn.text
            assert turn.headers["X-Request-ID"] == "corr-turn-42"
            audit_id = str(turn.json()["audit_id"])

        completed_logs = [
            rec.getMessage()
            for rec in caplog.records
            if "request_completed" in rec.getMessage() and "corr-turn-42" in rec.getMessage()
        ]
        assert completed_logs, "Expected structured request_completed log entry for corr-turn-42"
        msg = completed_logs[0]
        assert f"audit_id={audit_id}" in msg
        assert "path=/api/v1/chat/query" in msg
        # Strict non-leakage in logs
        assert secret_query not in msg
        assert settings.SECRET_KEY not in msg
        assert headers["Authorization"] not in msg
    finally:
        api_logger.removeFilter(filt)


def test_readiness_probe_healthy_and_degraded(monkeypatch, tmp_path) -> None:
    """GET /ready returns 200 when dependencies pass and 503 if LLM configuration fails."""
    isolated_qdrant = QdrantIndexer(
        storage_path=str(tmp_path / "qdrant"),
        embedder=FakeEmbeddingGenerator(),
    )
    isolated_qdrant.ensure_collection(vector_dim=384)
    monkeypatch.setattr(baseline_pipeline, "qdrant", isolated_qdrant)

    try:
        with TestClient(app) as client:
            ok = client.get("/ready")
            assert ok.status_code == 200
            body = ok.json()
            assert body["status"] == "ready"
            assert body["checks"]["database"] is True
            assert body["checks"]["llm_config"] is True
            assert body["checks"]["vector_store"] is True

            def _broken_ready() -> ResolvedLLM:
                raise ValueError("Simulated missing provider API key")

            monkeypatch.setattr(type(settings), "ensure_llm_ready", lambda self: _broken_ready())
            fail = client.get("/ready")
            assert fail.status_code == 503
            fail_body = fail.json()
            assert fail_body["status"] == "not_ready"
            assert fail_body["checks"]["llm_config"] is False
            assert "Simulated missing provider API key" not in fail.text
    finally:
        isolated_qdrant.close()


def test_fallback_offline_preserves_response_contract_and_audit(
    seeded_auth_users,
    monkeypatch,
    tmp_path,
) -> None:
    """Explicit fallback_offline=True executes under offline mock profile with identical contract."""
    isolated_qdrant = QdrantIndexer(
        storage_path=str(tmp_path / "qdrant"),
        embedder=FakeEmbeddingGenerator(),
    )
    isolated_qdrant.ensure_collection(vector_dim=384)
    monkeypatch.setattr(baseline_pipeline, "qdrant", isolated_qdrant)
    monkeypatch.setattr(
        baseline_pipeline.bm25,
        "search",
        lambda query, top_k=20, role=None: SearchResult(
            hits=[
                {
                    "chunk_id": "CH-OFFLINE-001",
                    "doc_id": "DOC-OFFLINE",
                    "doc_title": "AML Offline Compliance Standard",
                    "section_title": "Section 4.1",
                    "heading_path": "AML Policy > Customer Due Diligence",
                    "clause_id": "4.1",
                    "page_number": 3,
                    "snippet": "Enhanced due diligence applies to high-risk accounts.",
                    "text": "Enhanced due diligence applies to high-risk accounts.",
                    "allowed_roles": ["analyst", "manager", "auditor"],
                    "score": 0.91,
                }
            ],
            considered=1,
            filtered=0,
        ),
    )

    try:
        with TestClient(app) as client:
            headers = _login_headers(client, "analyst_user")
            sess = client.post("/api/v1/sessions", headers=headers, json={"title": "Offline parity"})
            assert sess.status_code == 201
            session_id = sess.json()["id"]

            resp = client.post(
                "/api/v1/chat/query",
                headers=headers,
                json={
                    "session_id": session_id,
                    "query": "When is enhanced due diligence required under AML policy?",
                    "fallback_offline": True,
                },
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["llm_stats"]["profile"] == "mock"
            assert data["llm_stats"]["model"] == "mock-offline-fallback"
            assert data["spend"]["scope"] == "offline"
            assert data["spend"]["is_paid"] is False
            assert data["audit_id"] > 0
            assert isinstance(data["answer"], str) and len(data["answer"]) > 0
            assert isinstance(data["citations"], list) and len(data["citations"]) >= 1
            assert data["citations"][0]["doc_id"] == "DOC-OFFLINE"
    finally:
        isolated_qdrant.close()


def test_admin_metrics_and_queryable_audit_filters(seeded_auth_users) -> None:
    """GET /api/v1/admin/metrics and filtered GET /api/v1/audit/logs return telemetry safely."""
    with TestClient(app) as client:
        analyst_headers = _login_headers(client, "analyst_user")
        auditor_headers = _login_headers(client, "auditor_user")

        sess = client.post(
            "/api/v1/sessions",
            headers=analyst_headers,
            json={"title": "Metrics Turn"},
        )
        assert sess.status_code == 201
        session_id = sess.json()["id"]

        turn = client.post(
            "/api/v1/chat/query",
            headers=analyst_headers,
            json={"session_id": session_id, "query": "What LLM model is active?"},
        )
        assert turn.status_code == 200, turn.text
        assert turn.json()["route"] == "DIRECT_REPLY"

        metrics_resp = client.get(
            f"/api/v1/admin/metrics?session_id={session_id}",
            headers=analyst_headers,
        )
        assert metrics_resp.status_code == 200, metrics_resp.text
        metrics = metrics_resp.json()
        assert metrics["profile"] == "mock"
        assert "latency" in metrics
        assert metrics["latency"]["sample_count"] >= 1
        assert metrics["latency"]["p50_ms"] >= 0.0
        assert metrics["latency"]["p95_ms"] >= metrics["latency"]["p50_ms"]
        assert "guard_status" in metrics
        assert metrics["guard_status"]["scope"] == "offline"
        assert "LLM_API_KEY" not in metrics_resp.text

        filtered_logs = client.get(
            "/api/v1/audit/logs?limit=20&user_role=analyst&route=DIRECT_REPLY",
            headers=auditor_headers,
        )
        assert filtered_logs.status_code == 200, filtered_logs.text
        rows = filtered_logs.json()
        assert len(rows) >= 1
        assert all(r["user_role"] == "analyst" and r["final_route"] == "DIRECT_REPLY" for r in rows)

        # Injection attempt in filter value returns empty results cleanly via parameterized SQL.
        sqli = client.get(
            "/api/v1/audit/logs?route=%27%20OR%201%3D1%20--",
            headers=auditor_headers,
        )
        assert sqli.status_code == 200
        assert sqli.json() == []
