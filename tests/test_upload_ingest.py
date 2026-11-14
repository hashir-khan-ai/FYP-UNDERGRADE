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


def test_empty_or_missing_roles_means_deny_by_default() -> None:
    """Missing or empty allowed_roles metadata on a chunk MUST mean DENY (excluded for every role)."""
    from src.core.security import chunk_visible_to_role, enforce_role_visibility

    # Chunk with empty roles
    empty_roles_chunk = {"chunk_id": "DENY-01", "allowed_roles": [], "text_content": "Secret text"}
    for role in ("analyst", "manager", "auditor"):
        assert chunk_visible_to_role(empty_roles_chunk, role) is False, (
            f"Chunk with empty roles must be denied for role '{role}'"
        )

    # Chunk with None roles
    none_roles_chunk = {"chunk_id": "DENY-02", "allowed_roles": None, "text_content": "Secret text"}
    for role in ("analyst", "manager", "auditor"):
        assert chunk_visible_to_role(none_roles_chunk, role) is False, (
            f"Chunk with None roles must be denied for role '{role}'"
        )

    # Re-ranking drop verification
    permitted, dropped = enforce_role_visibility([empty_roles_chunk, none_roles_chunk], "auditor")
    assert len(permitted) == 0
    assert dropped == 2


def test_dual_index_consistency_verification_catches_divergence() -> None:
    """Dual-index verification raises IngestionConsistencyError if chunk IDs or role metadata mismatch."""
    from src.ingestion.chunker import DocumentChunk
    from src.ingestion.upload_ingest import IngestionConsistencyError, verify_dual_index_consistency

    chunk = DocumentChunk(
        chunk_id="CHK-001",
        doc_id="D-1",
        doc_title="Policy",
        section_label="S1",
        clause_label="C1",
        page=1,
        source_path="data/test.md",
        allowed_roles=["manager", "auditor"],
        text_content="Policy body",
    )

    # 1. Chunk ID missing in BM25 staged list -> raises IngestionConsistencyError
    with pytest.raises(IngestionConsistencyError, match="missing from staged BM25 index"):
        verify_dual_index_consistency([chunk], [])

    # 2. Role metadata mismatch -> raises IngestionConsistencyError
    mismatched_bm25_chunk = {
        "chunk_id": "CHK-001",
        "allowed_roles": ["analyst"],  # Diverged roles!
    }
    with pytest.raises(IngestionConsistencyError, match="Role metadata mismatch"):
        verify_dual_index_consistency([chunk], [mismatched_bm25_chunk])

    # 3. Exact match -> passes cleanly
    matched_bm25_chunk = {
        "chunk_id": "CHK-001",
        "allowed_roles": ["manager", "auditor"],
    }
    verify_dual_index_consistency([chunk], [matched_bm25_chunk])


def test_simulated_ingestion_failure_rolls_back_and_leaves_index_intact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure mid-upload rolls back staging, unlinks temp files, and leaves previous live index intact."""
    from src.ingestion.chunker import DocumentChunk
    from src.ingestion.upload_ingest import IngestionConsistencyError, ingest_uploaded_document

    # 1. Create an initial live index with 1 chunk
    bm25_path = tmp_path / "live_bm25.pkl"
    bm25 = BM25Indexer(index_path=str(bm25_path))
    initial_chunk = DocumentChunk(
        chunk_id="ORIG-001",
        doc_id="DOC-ORIG",
        doc_title="Original Policy",
        section_label="S1",
        clause_label="C1",
        page=1,
        source_path="data/orig.md",
        allowed_roles=["analyst", "manager", "auditor"],
        text_content="Original established policy content.",
    )
    bm25.build_and_save([initial_chunk])
    assert len(bm25.chunks) == 1
    assert bm25_path.exists()

    qdrant = QdrantIndexer(
        storage_path=str(tmp_path / "qdrant_test"),
        embedder=FakeEmbeddingGenerator(),
    )
    qdrant.index_chunks([initial_chunk])

    # 2. Attempt ingestion with SIMULATE_INGESTION_FAILURE=True
    monkeypatch.setattr(settings, "SIMULATE_INGESTION_FAILURE", True)
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path / "uploads"))

    new_content = b"# New Policy\n\nSection 1\n\nThis is new policy content to ingest."
    with pytest.raises(IngestionConsistencyError, match="SIMULATED_INGESTION_CRASH_BEFORE_SWAP"):
        ingest_uploaded_document(
            file_bytes=new_content,
            filename="new_policy.md",
            user_id=2,
            user_role="manager",
            allowed_roles=["manager", "auditor"],
            bm25_indexer=bm25,
            qdrant_indexer=qdrant,
        )

    # 3. Verify rollback: Live BM25 file was not overwritten; staging temp files were unlinked
    bm25.load()
    assert len(bm25.chunks) == 1
    assert bm25.chunks[0]["chunk_id"] == "ORIG-001"

    # Verify no dangling .tmp or .staging files remain
    staging_files = list(tmp_path.glob("*.tmp*"))
    assert len(staging_files) == 0, f"Found dangling staging files: {staging_files}"


