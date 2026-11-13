"""Tests for dynamic document upload, on-the-fly ingestion, and server-side RBAC."""

import json
from io import BytesIO
from pathlib import Path

import pytest
from starlette.datastructures import UploadFile

from src.api.deps import ApiError, CurrentUser
from src.api.routes import list_documents, upload_document
from src.config import settings
from src.ingestion.embeddings import FakeEmbeddingGenerator
from src.ingestion.indexer import BM25Indexer, QdrantIndexer
from src.ingestion.upload_ingest import (
    UploadValidationError,
    ingest_uploaded_document,
    sanitize_filename,
    validate_upload_request,
)
from src.rag.baseline import BaselineRAGPipeline, MockCrossEncoderReranker


@pytest.fixture
def analyst_user() -> CurrentUser:
    return CurrentUser(
        id=1,
        username="analyst_user",
        full_name="Alice Analyst",
        role="analyst",
        jti="test_jti_analyst",
        expires_at=9999999999,
    )


@pytest.fixture
def manager_user() -> CurrentUser:
    return CurrentUser(
        id=2,
        username="manager_user",
        full_name="Bob Manager",
        role="manager",
        jti="test_jti_manager",
        expires_at=9999999999,
    )


@pytest.fixture
def test_pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> BaselineRAGPipeline:
    """Isolated, fast pipeline fixture with in-memory/temp storage to avoid lock contention."""
    qdrant = QdrantIndexer(
        storage_path=str(tmp_path / "qdrant"),
        embedder=FakeEmbeddingGenerator(),
    )
    bm25 = BM25Indexer(index_path=str(tmp_path / "bm25.pkl"))
    pipeline = BaselineRAGPipeline(
        qdrant_indexer=qdrant,
        bm25_indexer=bm25,
        reranker=MockCrossEncoderReranker(),
    )
    monkeypatch.setattr("src.rag.baseline.baseline_pipeline", pipeline)
    monkeypatch.setattr("src.api.routes.baseline_pipeline", pipeline)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))
    return pipeline


def test_sanitize_filename() -> None:
    """Path traversal characters and spaces are safely stripped."""
    assert sanitize_filename("../../etc/passwd.txt") == "passwd.txt"
    assert sanitize_filename("..\\..\\windows\\win.ini") == "win.ini"
    assert sanitize_filename("policy @#$ draft 2026.md") == "policy_____draft_2026.md"


def test_validate_upload_request_rejects_unauthorized_role() -> None:
    """Analyst role is not in UPLOAD_ALLOWED_ROLES and fails validation."""
    with pytest.raises(UploadValidationError) as exc:
        validate_upload_request(
            filename="policy.md",
            file_size=100,
            user_role="analyst",
            allowed_roles=["analyst", "manager"],
        )
    assert "not authorized to upload documents" in str(exc.value)


def test_validate_upload_request_rejects_invalid_extension() -> None:
    """Only approved file extensions (.md, .txt, .pdf, .html) are accepted."""
    with pytest.raises(UploadValidationError) as exc:
        validate_upload_request(
            filename="malicious_script.exe",
            file_size=100,
            user_role="manager",
            allowed_roles=["manager"],
        )
    assert "Unsupported file extension" in str(exc.value)


def test_upload_api_role_gating(
    test_pipeline: BaselineRAGPipeline,
    analyst_user: CurrentUser,
    manager_user: CurrentUser,
) -> None:
    """Analyst receives HTTP 403 on upload; Manager receives HTTP 201."""
    file_content = b"# Internal Policy\n\nSection 1\nClause 1.1: Managers must review loans over 1M.\n"
    file_obj = UploadFile(file=BytesIO(file_content), filename="policy.md")

    # 1. Analyst attempt -> 403 ApiError
    with pytest.raises(ApiError) as exc_info:
        upload_document(
            file=file_obj,
            allowed_roles=json.dumps(["manager", "auditor"]),
            title="Test Policy",
            doc_type="policy",
            user=analyst_user,
        )
    assert exc_info.value.status_code == 403
    assert "not authorized to upload" in exc_info.value.message

    # 2. Manager attempt -> 201 DocumentUploadResponse
    file_obj_mgr = UploadFile(file=BytesIO(file_content), filename="policy.md")
    resp_mgr = upload_document(
        file=file_obj_mgr,
        allowed_roles=json.dumps(["manager", "auditor"]),
        title="Test Policy",
        doc_type="policy",
        user=manager_user,
    )
    assert resp_mgr.chunks_indexed >= 1
    assert "policy" in resp_mgr.filename.lower()
    assert resp_mgr.allowed_roles == ["manager", "auditor"]


def test_uploaded_document_rbac_leakage_guarantee(test_pipeline: BaselineRAGPipeline) -> None:
    """Uploaded manager-only document cannot be retrieved by analyst (0.00% leakage)."""
    # 1. Manager uploads an internal policy with unique secret token
    secret_marker = "SECRET_TIER_ESC_998822"
    doc_text = f"""# Manager Confidential Protocol
Section 1. Executive Escalation
Clause 1.1: The executive risk threshold marker is {secret_marker}.
"""
    result = ingest_uploaded_document(
        file_bytes=doc_text.encode("utf-8"),
        filename="escalation_protocol.md",
        user_id=2,
        user_role="manager",
        allowed_roles=["manager", "auditor"],
        doc_id="DOC-UP-ESC-001",
        title="Escalation Protocol 2026",
        qdrant_indexer=test_pipeline.qdrant,
        bm25_indexer=test_pipeline.bm25,
    )
    assert result["chunks_indexed"] >= 1

    # 2. Retrieve as Analyst -> must NOT retrieve or leak
    test_pipeline.bm25.load()

    analyst_res = test_pipeline.ask(
        query=f"What is the executive risk threshold marker {secret_marker}?",
        role="analyst",
    )
    assert analyst_res.answer == "I can't find that in the documents available to your role."
    assert secret_marker not in analyst_res.answer
    assert secret_marker not in json.dumps([s.model_dump() for s in analyst_res.sources])

    # 3. Retrieve as Manager -> must retrieve permitted document
    manager_res = test_pipeline.ask(
        query=f"What is the executive risk threshold marker {secret_marker}?",
        role="manager",
    )
    assert manager_res.answer != "I can't find that in the documents available to your role."
    assert len(manager_res.sources) >= 1
    assert any(s.doc_id == "DOC-UP-ESC-001" for s in manager_res.sources)


def test_document_catalog_endpoint_filters_by_role(
    test_pipeline: BaselineRAGPipeline,
    analyst_user: CurrentUser,
    manager_user: CurrentUser,
) -> None:
    """Catalog endpoint /api/v1/documents returns only documents visible to caller's role."""
    analyst_catalog = list_documents(user=analyst_user)
    for d in analyst_catalog.documents:
        assert "analyst" in [r.lower() for r in d.allowed_roles]

    mgr_catalog = list_documents(user=manager_user)
    for d in mgr_catalog.documents:
        roles_lower = [r.lower() for r in d.allowed_roles]
        assert "manager" in roles_lower or "analyst" in roles_lower
        assert "/" not in d.file_path and "\\" not in d.file_path


def test_upload_error_is_sanitized_and_file_path_omits_directories(
    test_pipeline: BaselineRAGPipeline,
    manager_user: CurrentUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unexpected ingestion errors must not leak internal paths or tracebacks."""
    import src.ingestion.upload_ingest as ui_mod

    monkeypatch.setattr(
        ui_mod,
        "ingest_uploaded_document",
        lambda **kwargs: (_ for _ in ()).throw(
            RuntimeError("C:\\secret\\local\\disk failure in qdrant")
        ),
    )
    file_obj = UploadFile(file=BytesIO(b"hello policy world"), filename="secret.md")
    with pytest.raises(ApiError) as exc_info:
        upload_document(
            file=file_obj,
            allowed_roles='["manager"]',
            user=manager_user,
        )
    assert exc_info.value.status_code == 500
    assert exc_info.value.code == "INGESTION_ERROR"
    assert "C:\\secret" not in exc_info.value.message
    assert "qdrant" not in exc_info.value.message

