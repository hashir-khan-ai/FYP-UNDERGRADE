"""Dynamic on-the-fly document ingestion service for uploaded compliance documents.

Handles saving to user-scoped upload directories, validation, metadata sidecar creation,
loading, clause-aware chunking, dense vector indexing in Qdrant, atomic BM25 merging,
and database registration.

RBAC ENFORCEMENT CONTRACT:
Every uploaded document receives an explicit `allowed_roles` specification.
Chunks are tagged with these roles and stored inside Qdrant payloads and BM25 metadata.
Server-side payload filtering prevents unpermitted roles from retrieving any passage
from the uploaded document. Target leakage: strictly 0.00%.
"""

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any

from src.config import settings
from src.core.security import normalize_role
from src.db.connection import get_db_connection
from src.db.repository import Repository
from src.ingestion.chunker import ClauseAwareChunker, DocumentChunk
from src.ingestion.indexer import BM25Indexer, QdrantIndexer
from src.ingestion.loaders import DocumentLoader

logger = logging.getLogger(__name__)


class UploadValidationError(ValueError):
    """Raised when an uploaded document fails format, size, or role validation."""


def sanitize_filename(filename: str) -> str:
    """Strip directory traversal, path characters, and invalid symbols from filename."""
    base_name = Path(filename).name
    # Remove any characters other than alphanumeric, hyphens, underscores, and dots
    clean_name = re.sub(r"[^A-Za-z0-9.\-_]", "_", base_name)
    if not clean_name or clean_name.startswith("."):
        clean_name = f"document_{uuid.uuid4().hex[:8]}{Path(filename).suffix or '.txt'}"
    return clean_name[:120]


def validate_upload_request(
    filename: str,
    file_size: int,
    user_role: str,
    allowed_roles: list[str] | None,
) -> tuple[str, list[str]]:
    """Validate user permissions, file extension, size limit, and role targets."""
    normalized_user_role = normalize_role(user_role)
    if normalized_user_role not in settings.UPLOAD_ALLOWED_ROLES:
        raise UploadValidationError(
            f"Role '{user_role}' is not authorized to upload documents. "
            f"Authorized roles: {settings.UPLOAD_ALLOWED_ROLES}"
        )

    safe_name = sanitize_filename(filename)
    ext = Path(safe_name).suffix.lstrip(".").lower()
    if ext not in settings.UPLOAD_ALLOWED_EXTENSIONS:
        raise UploadValidationError(
            f"Unsupported file extension '.{ext}'. "
            f"Permitted extensions: {settings.UPLOAD_ALLOWED_EXTENSIONS}"
        )

    max_bytes = settings.UPLOAD_MAX_FILE_SIZE_MB * 1024 * 1024
    if file_size > max_bytes:
        raise UploadValidationError(
            f"File size ({file_size / (1024 * 1024):.2f} MB) exceeds maximum allowed limit "
            f"({settings.UPLOAD_MAX_FILE_SIZE_MB} MB)."
        )

    if file_size == 0:
        raise UploadValidationError("Uploaded file cannot be empty.")

    # Target allowed_roles validation
    target_roles: list[str] = []
    if allowed_roles:
        for r in allowed_roles:
            norm = normalize_role(r)
            if norm not in target_roles:
                target_roles.append(norm)
    if not target_roles:
        # Default: user's role + higher tiers
        if normalized_user_role == "analyst":
            target_roles = ["analyst", "manager", "auditor"]
        elif normalized_user_role == "manager":
            target_roles = ["manager", "auditor"]
        else:
            target_roles = ["auditor"]

    return safe_name, target_roles


def ingest_uploaded_document(
    file_bytes: bytes,
    filename: str,
    user_id: int,
    user_role: str,
    allowed_roles: list[str] | None = None,
    doc_id: str | None = None,
    title: str | None = None,
    doc_type: str | None = None,
    jurisdiction: str | None = None,
    version: str | None = None,
    qdrant_indexer: QdrantIndexer | None = None,
    bm25_indexer: BM25Indexer | None = None,
) -> dict[str, Any]:
    """Ingest, chunk, and index an uploaded document on-the-fly.

    Args:
        file_bytes: Raw binary content of the uploaded file.
        filename: Original file name.
        user_id: Authenticated user identifier.
        user_role: Authenticated user role.
        allowed_roles: Target roles permitted to access this document.
        doc_id: Optional custom document ID (auto-generated if omitted).
        title: Optional document title.
        doc_type: Optional document classification string.
        jurisdiction: Regulatory jurisdiction (e.g. UK_FCA).
        version: Document version string.
        qdrant_indexer: Optional QdrantIndexer instance.
        bm25_indexer: Optional BM25Indexer instance.

    Returns:
        Summary dict containing doc_id, filename, chunks_indexed, and paths.
    """
    safe_name, target_roles = validate_upload_request(
        filename=filename,
        file_size=len(file_bytes),
        user_role=user_role,
        allowed_roles=allowed_roles,
    )

    upload_uuid = uuid.uuid4().hex
    upload_dir = Path(settings.UPLOAD_DIR) / f"user_{user_id}" / upload_uuid
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / safe_name

    # Save raw file
    file_path.write_bytes(file_bytes)

    # Document ID and title resolution
    final_doc_id = (
        doc_id.strip()
        if (doc_id and isinstance(doc_id, str) and doc_id.strip())
        else f"DOC-UP-{Path(safe_name).stem.upper()[:24]}-{upload_uuid[:6]}"
    )
    final_title = (
        title.strip()
        if (title and isinstance(title, str) and title.strip())
        else Path(safe_name).stem.replace("-", " ").replace("_", " ").title()
    )
    final_doc_type = (
        doc_type.strip()
        if (doc_type and isinstance(doc_type, str) and doc_type.strip())
        else "USER_UPLOADED_POLICY"
    )
    final_jurisdiction = (
        jurisdiction.strip()
        if (jurisdiction and isinstance(jurisdiction, str) and jurisdiction.strip())
        else "INTERNAL_BANK"
    )
    final_version = (
        version.strip()
        if (version and isinstance(version, str) and version.strip())
        else "1.0"
    )

    # Write per-document metadata sidecar
    sidecar_data = {
        "document_id": final_doc_id,
        "title": final_title,
        "allowed_roles": target_roles,
        "doc_type": final_doc_type,
        "jurisdiction": final_jurisdiction,
        "version": final_version,
        "content_origin": "user_upload",
        "uploaded_by_user_id": user_id,
        "upload_uuid": upload_uuid,
    }
    sidecar_path = upload_dir / f"{safe_name}.meta.json"
    sidecar_path.write_text(json.dumps(sidecar_data, indent=2), encoding="utf-8")

    # Load document
    doc = DocumentLoader.load(file_path)
    doc.doc_id = final_doc_id
    doc.title = final_title
    doc.allowed_roles = target_roles
    doc.doc_type = final_doc_type
    doc.jurisdiction = final_jurisdiction
    doc.version = final_version

    # Chunk document
    chunker = ClauseAwareChunker()
    chunks = chunker.chunk_document(doc)
    if not chunks:
        # Fallback: create at least one chunk from raw text if structural splitter found no clauses
        full_text = "\n\n".join(p.content for p in doc.pages if p.content.strip())
        if full_text.strip():
            chunks = [
                DocumentChunk(
                    chunk_id=f"{final_doc_id}_C01",
                    doc_id=final_doc_id,
                    doc_title=final_title,
                    section_label="General Section",
                    clause_label="General Clause",
                    page=1,
                    source_path=str(file_path),
                    allowed_roles=target_roles,
                    text_content=full_text.strip()[:1500],
                    token_count=len(full_text.split()),
                    heading_path=f"{final_title} > General Section",
                )
            ]
        else:
            raise UploadValidationError("Document contains no indexable text content.")

    # Enforce allowed_roles on every chunk
    for c in chunks:
        c.allowed_roles = list(target_roles)
        c.doc_id = final_doc_id
        c.doc_title = final_title

    # 1. Dense Vector Indexing (Qdrant)
    if qdrant_indexer is not None:
        qdrant = qdrant_indexer
    else:
        try:
            from src.rag.baseline import baseline_pipeline
            qdrant = baseline_pipeline.qdrant
        except Exception:
            qdrant = QdrantIndexer()

    qdrant.index_chunks(chunks)

    # 2. Lexical Indexing (BM25 atomic merge)
    if bm25_indexer is not None:
        bm25 = bm25_indexer
    else:
        try:
            from src.rag.baseline import baseline_pipeline
            bm25 = baseline_pipeline.bm25
        except Exception:
            bm25 = BM25Indexer()

    bm25.merge_and_save(chunks)

    # 3. Database Catalog Registration (SQLite)
    with get_db_connection() as conn:
        repo = Repository(conn)
        repo.register_document(
            doc_id=final_doc_id,
            filename=safe_name,
            source_jurisdiction=final_jurisdiction,
            doc_type=final_doc_type,
            version=final_version,
            allowed_roles=target_roles,
            file_path=str(file_path),
            total_chunks=len(chunks),
        )

    logger.info(
        "Successfully ingested uploaded document '%s' (doc_id=%s): %d chunks indexed into Qdrant & BM25.",
        safe_name,
        final_doc_id,
        len(chunks),
    )

    return {
        "doc_id": final_doc_id,
        "filename": safe_name,
        "title": final_title,
        "chunks_indexed": len(chunks),
        "allowed_roles": target_roles,
        "doc_type": final_doc_type,
        "file_path": str(file_path),
        "message": f"Successfully ingested {len(chunks)} chunks into vector and lexical search.",
    }
