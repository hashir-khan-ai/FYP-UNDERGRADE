"""Integration tests for the ingestion CLI and idempotent re-indexing."""

from pathlib import Path

import pytest

from src.config import settings
from src.db.connection import get_db_connection
from src.ingestion.embeddings import FakeEmbeddingGenerator
from src.ingestion.indexer import BM25Indexer, QdrantIndexer
from src.ingestion.run import run_ingestion


def test_ingestion_is_idempotent(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run ingestion twice over a fixture corpus and assert stable counts/IDs."""
    data_dir = tmp_path / "data"
    raw_dir = data_dir / "raw"
    synthetic_dir = data_dir / "synthetic"
    raw_dir.mkdir(parents=True)
    synthetic_dir.mkdir(parents=True)

    (raw_dir / "public.md").write_text(
        "# Public Rule\n"
        "**Document ID:** DOC-INGEST-PUBLIC\n"
        "**Permitted Roles:** [\"analyst\", \"manager\", \"auditor\"]\n\n"
        "## Section 1: Capital\n"
        "### Clause CAP-1.1 (Minimum Ratio)\n"
        "Institutions must maintain a CET1 ratio of at least 4.5 percent.\n",
        encoding="utf-8",
    )
    (synthetic_dir / "audit.md").write_text(
        "# Confidential Audit\n"
        "**Document ID:** DOC-INGEST-AUDIT\n\n"
        "## Section 2: Findings\n"
        "### Clause AUD-2.1 (Liquidity)\n"
        "The audit found a temporary liquidity shortfall.\n",
        encoding="utf-8",
    )
    (synthetic_dir / "audit.meta.json").write_text(
        '{"doc_id": "DOC-INGEST-AUDIT", "allowed_roles": ["auditor"]}',
        encoding="utf-8",
    )

    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "app.db"))
    monkeypatch.setattr(settings, "QDRANT_STORAGE_PATH", str(tmp_path / "qdrant"))
    monkeypatch.setattr(settings, "BM25_INDEX_PATH", str(tmp_path / "bm25.pkl"))
    monkeypatch.setattr("src.ingestion.indexer.embeddings", FakeEmbeddingGenerator())

    first = run_ingestion(data_dir=str(data_dir), rebuild=True)
    second = run_ingestion(data_dir=str(data_dir), rebuild=False)

    assert first["documents"] == 2
    assert first["failures"] == 0
    assert first["chunks"] == second["chunks"]
    assert first["qdrant_points"] == second["qdrant_points"] == first["chunks"]
    assert first["bm25_records"] == second["bm25_records"] == first["chunks"]

    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, allowed_roles, total_chunks FROM documents ORDER BY id;"
        ).fetchall()
        assert [row["id"] for row in rows] == ["DOC-INGEST-AUDIT", "DOC-INGEST-PUBLIC"]
        roles = {row["id"]: row["allowed_roles"] for row in rows}
        assert "auditor" in roles["DOC-INGEST-AUDIT"]
        assert "analyst" not in roles["DOC-INGEST-AUDIT"]

    qdrant = QdrantIndexer(
        storage_path=str(tmp_path / "qdrant"),
        embedder=FakeEmbeddingGenerator(),
    )
    try:
        assert qdrant.count() == first["chunks"]
    finally:
        qdrant.close()

    bm25 = BM25Indexer(index_path=str(tmp_path / "bm25.pkl"))
    hits = bm25.search("CET1 ratio", top_k=3, role="analyst").hits
    assert hits
    assert hits[0]["doc_id"] == "DOC-INGEST-PUBLIC"


def test_ingestion_handles_missing_source_directory(tmp_path) -> None:
    """Verify an empty corpus returns zero counts instead of raising."""
    summary = run_ingestion(data_dir=str(tmp_path / "does-not-exist"), rebuild=False)
    assert summary == {"documents": 0, "chunks": 0, "failures": 0}


def test_ingestion_continues_after_a_bad_document(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify one invalid file is counted as a failure while good files index."""
    raw_dir = tmp_path / "data" / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "good.md").write_text(
        "# Good\n## Section 1: A\n### Clause GOOD-1.1\nUseful regulatory text.\n",
        encoding="utf-8",
    )
    (raw_dir / "bad.md").write_text("# Bad\n", encoding="utf-8")

    monkeypatch.setattr(settings, "DATABASE_PATH", str(tmp_path / "app.db"))
    monkeypatch.setattr(settings, "QDRANT_STORAGE_PATH", str(tmp_path / "qdrant"))
    monkeypatch.setattr(settings, "BM25_INDEX_PATH", str(tmp_path / "bm25.pkl"))
    monkeypatch.setattr("src.ingestion.indexer.embeddings", FakeEmbeddingGenerator())

    summary = run_ingestion(data_dir=str(tmp_path / "data"), rebuild=True)
    assert summary["documents"] == 1
    assert summary["failures"] == 1
    assert summary["chunks"] > 0
