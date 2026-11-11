"""Ingestion CLI: load, clause-chunk, embed and index the regulatory corpus."""

import argparse
import logging
import sys
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.config import settings
from src.db.connection import get_db_connection
from src.db.migrations import init_db
from src.db.repository import Repository
from src.ingestion.chunker import ClauseAwareChunker, DocumentChunk
from src.ingestion.indexer import BM25Indexer, QdrantIndexer
from src.ingestion.loaders import DocumentLoader

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("ingestion")

SUPPORTED_EXTENSIONS = {".pdf", ".html", ".htm", ".md", ".txt"}


def discover_documents(data_dir: str | Path = "data") -> list[Path]:
    """Return supported source files from ``data/raw`` and ``data/synthetic``."""
    base_path = Path(data_dir)
    paths: list[Path] = []
    for folder in (base_path / "raw", base_path / "synthetic"):
        if folder.is_dir():
            paths.extend(
                path
                for path in folder.rglob("*")
                if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
            )
    return sorted(set(paths))


def run_ingestion(data_dir: str = "data", rebuild: bool = False) -> dict[str, int]:
    """Execute the complete document parsing and indexing pipeline.

    Re-running without ``rebuild`` upserts deterministic point IDs, so no chunk
    is duplicated. ``rebuild`` clears Qdrant and replaces the BM25 index first.
    """
    init_db()
    file_paths = discover_documents(data_dir)
    if not file_paths:
        logger.error("No source documents found under '%s'.", data_dir)
        return {"documents": 0, "chunks": 0, "failures": 0}

    logger.info("Discovered %s candidate documents for ingestion.", len(file_paths))

    chunker = ClauseAwareChunker()
    all_chunks: list[DocumentChunk] = []
    doc_chunk_counts: dict[str, int] = {}
    failures = 0
    documents_processed = 0

    for path in file_paths:
        try:
            logger.info("Loading document: %s", path.name)
            doc = DocumentLoader.load(path)
            chunks = chunker.chunk_document(doc)
            if not chunks:
                raise ValueError("No chunks produced from document")

            all_chunks.extend(chunks)
            doc_chunk_counts[doc.doc_id] = len(chunks)
            documents_processed += 1
            logger.info("  -> %s chunks for '%s' (%s).", len(chunks), doc.title, doc.doc_id)

            with get_db_connection() as conn:
                Repository(conn).register_document(
                    doc_id=doc.doc_id,
                    filename=path.name,
                    source_jurisdiction=doc.jurisdiction,
                    doc_type=doc.doc_type,
                    version=doc.version,
                    allowed_roles=doc.allowed_roles,
                    file_path=str(path),
                    total_chunks=len(chunks),
                )
        except Exception as exc:
            logger.error("Failed to process %s: %s", path, exc, exc_info=True)
            failures += 1

    logger.info("Total chunks generated across corpus: %s.", len(all_chunks))

    qdrant_indexer = QdrantIndexer()
    bm25_indexer = BM25Indexer()
    try:
        if rebuild:
            qdrant_indexer.reset()
        logger.info("Indexing chunks into Qdrant embedded vector store...")
        qdrant_indexer.index_chunks(all_chunks)
        qdrant_points = qdrant_indexer.count()

        logger.info("Indexing chunks into BM25 lexical keyword store...")
        bm25_indexer.build_and_save(all_chunks)
        bm25_count = len(bm25_indexer.chunks)
    finally:
        qdrant_indexer.close()

    print("\n" + "=" * 60)
    print("INGESTION PIPELINE EXECUTION SUMMARY")
    print("=" * 60)
    print(f"Documents processed  : {documents_processed}")
    print(f"Documents failed     : {failures}")
    print(f"Chunks generated     : {len(all_chunks)}")
    print(f"Qdrant points stored : {qdrant_points}")
    print(f"BM25 records stored  : {bm25_count}")
    print("-" * 60)
    print("Chunks per document:")
    for doc_id, count in sorted(doc_chunk_counts.items()):
        print(f"  - {doc_id:<30}: {count} chunks")
    print("=" * 60 + "\n")

    return {
        "documents": documents_processed,
        "chunks": len(all_chunks),
        "failures": failures,
        "qdrant_points": qdrant_points,
        "bm25_records": bm25_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest regulatory documents into Qdrant and BM25 indices."
    )
    parser.add_argument("--data-dir", default="data", help="Root data directory containing raw/ and synthetic/")
    parser.add_argument("--rebuild", action="store_true", help="Clear existing indices before indexing")
    args = parser.parse_args()

    summary = run_ingestion(data_dir=args.data_dir, rebuild=args.rebuild)
    if summary["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
