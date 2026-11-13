"""Verifiable source metadata: public links only, never for internal documents."""

import json
import uuid

from src.api.deps import CurrentUser
from src.api.routes import list_documents
from src.db.connection import get_db_connection
from src.db.repository import Repository
from src.rag.baseline import build_verification_metadata


def _metadata(doc_id: str, **overrides: str) -> dict:
    payload = {
        "doc_id": doc_id,
        "doc_title": "Regulatory source",
        "jurisdiction": "PUBLIC",
        "doc_type": "PUBLIC_REGULATION",
    }
    payload.update(overrides)
    return build_verification_metadata(payload)


def test_public_regulation_gets_official_url_and_verification_link() -> None:
    meta = _metadata("DOC-BASEL-III-2023", jurisdiction="BASEL_BCBS")

    assert meta["is_internal"] is False
    assert meta["source_url"] == "https://www.bis.org/bcbs/basel3.htm"
    assert meta["verification_url"].startswith("https://www.google.com/search?q=")
    assert meta["source_name"] == "Basel Committee (BIS)"


def test_internal_policy_never_gets_an_external_link() -> None:
    meta = _metadata(
        "DOC-INT-POL-MGT-002",
        jurisdiction="INTERNAL_SYNTHETIC",
        doc_type="INTERNAL_MANAGEMENT_POLICY",
    )

    assert meta["is_internal"] is True
    assert meta["source_url"] is None
    assert meta["verification_url"] is None
    assert meta["source_name"] == "Internal Bank Policy"


def test_document_catalog_exposes_trust_metadata_without_guessing_urls() -> None:
    suffix = uuid.uuid4().hex[:8]
    public_id = f"DOC-BASEL-III-2023-{suffix}"
    internal_id = f"POL-CATALOG-{suffix}"

    with get_db_connection() as conn:
        repo = Repository(conn)
        repo.register_document(
            doc_id=internal_id,
            filename="POLICY-CATALOG.md",
            source_jurisdiction="INTERNAL_SYNTHETIC",
            doc_type="INTERNAL_MANAGEMENT_POLICY",
            version="1.0",
            allowed_roles=["manager", "auditor"],
            file_path="data/synthetic/POLICY-CATALOG.md",
            total_chunks=3,
        )
        repo.register_document(
            doc_id=public_id,
            filename="BASEL-III-CATALOG.md",
            source_jurisdiction="BASEL_BCBS",
            doc_type="PUBLIC_REGULATION",
            version="2023.1",
            allowed_roles=["manager", "auditor"],
            file_path="data/raw/BASEL-III-CATALOG.md",
            total_chunks=4,
        )

    user = CurrentUser(
        id=2,
        username="manager_user",
        full_name="Bob Manager",
        role="manager",
        jti="test_jti_manager",
        expires_at=9999999999,
    )
    response = list_documents(user=user)
    by_id = {document.id: document for document in response.documents}

    internal = by_id[internal_id]
    assert internal.is_internal is True
    assert internal.source_url is None

    public = by_id[public_id]
    assert public.source_url is None or public.source_url.startswith("https://")
    if public.source_url:
        assert public.source_name

    with get_db_connection() as conn:
        conn.execute(
            "DELETE FROM documents WHERE id IN (?, ?);",
            (internal_id, public_id),
        )


def test_catalog_payload_contains_no_local_paths_in_trust_fields() -> None:
    """The trust metadata block never falls back to a filesystem path as a URL."""
    meta = _metadata("POL-FILESYSTEM-FALLBACK")
    serialized = json.dumps(meta)

    assert "C:\\" not in serialized
    assert "file://" not in serialized
    assert meta["verification_url"] is None
