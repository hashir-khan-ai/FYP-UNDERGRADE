"""Unit tests for hybrid search, Reciprocal Rank Fusion, and cross-encoder re-ranking."""

from src.ingestion.chunker import DocumentChunk
from src.ingestion.embeddings import FakeEmbeddingGenerator
from src.ingestion.indexer import BM25Indexer, QdrantIndexer
from src.rag.baseline import MockCrossEncoderReranker, reciprocal_rank_fusion


def test_reciprocal_rank_fusion_math() -> None:
    """Verify that chunks present in both dense and sparse lists score higher than single appearances."""
    bm25_hits = [
        {"chunk_id": "CH-1", "doc_title": "Doc 1", "score": 4.5},
        {"chunk_id": "CH-2", "doc_title": "Doc 2", "score": 2.1},
    ]
    vector_hits = [
        {"chunk_id": "CH-2", "doc_title": "Doc 2", "score": 0.92},
        {"chunk_id": "CH-3", "doc_title": "Doc 3", "score": 0.85},
    ]

    fused = reciprocal_rank_fusion(bm25_hits, vector_hits, k=60, top_k=5)

    assert len(fused) == 3
    # CH-2 appeared in both lists (rank 2 in BM25, rank 1 in Vector)
    # Score for CH-2: 1/(60+2) + 1/(60+1) = 1/62 + 1/61 = 0.016129 + 0.016393 = 0.032522
    # Score for CH-1: 1/(60+1) = 0.016393
    # Score for CH-3: 1/(60+2) = 0.016129
    assert fused[0]["chunk_id"] == "CH-2", "Document in both dense and sparse should rank first"
    assert fused[1]["chunk_id"] == "CH-1"
    assert fused[2]["chunk_id"] == "CH-3"


def test_mock_reranker_ordering() -> None:
    """Verify that re-ranker returns candidates sorted by descending score up to top_n."""
    candidates = [
        {"chunk_id": "C-A", "text_content": "Passage A"},
        {"chunk_id": "C-B", "text_content": "Passage B"},
        {"chunk_id": "C-C", "text_content": "Passage C"},
    ]
    reranker = MockCrossEncoderReranker()
    reranked = reranker.rerank("test query", candidates, top_n=2)

    assert len(reranked) == 2
    assert reranked[0]["score"] >= reranked[1]["score"]
    assert reranked[0]["chunk_id"] == "C-A"


def test_hybrid_indexing_and_retrieval_fixture(tmp_path) -> None:
    """Verify in-memory hybrid search across BM25 and Qdrant with FakeEmbeddings."""
    chunks = [
        DocumentChunk(
            chunk_id="CH-MLR-01",
            doc_id="DOC-MLR",
            doc_title="MLR 2017",
            section_label="CDD",
            clause_label="Reg 27",
            page=1,
            source_path="data/test.md",
            allowed_roles=["analyst"],
            text_content="Occasional transaction threshold is 15000 euros for customer due diligence.",
        ),
        DocumentChunk(
            chunk_id="CH-BASEL-01",
            doc_id="DOC-BASEL",
            doc_title="Basel III",
            section_label="Capital",
            clause_label="CET1",
            page=2,
            source_path="data/test.md",
            allowed_roles=["analyst"],
            text_content="Minimum Common Equity Tier 1 ratio is 4.5 percent of risk-weighted assets.",
        ),
    ]

    # Index into BM25
    bm25_file = tmp_path / "bm25.pkl"
    bm25 = BM25Indexer(index_path=str(bm25_file))
    bm25.build_and_save(chunks)

    # Search BM25 for keyword
    results = bm25.search("15000 euros due diligence", top_k=2, role="analyst").hits
    assert len(results) > 0
    assert results[0]["chunk_id"] == "CH-MLR-01"

    # Search Qdrant with FakeEmbedder
    qdrant_dir = tmp_path / "qdrant"
    qdrant = QdrantIndexer(storage_path=str(qdrant_dir), embedder=FakeEmbeddingGenerator())
    qdrant.index_chunks(chunks)

    v_results = qdrant.search("capital adequacy ratio", top_k=2, role="analyst").hits
    assert len(v_results) == 2

    # Fusion
    fused = reciprocal_rank_fusion(results, v_results, k=60, top_k=2)
    assert len(fused) > 0
    assert fused[0]["chunk_id"] in ("CH-MLR-01", "CH-BASEL-01")
    qdrant.close()


def test_reingestion_is_idempotent(tmp_path) -> None:
    """Verify repeated indexing upserts the same IDs and does not duplicate chunks."""
    chunks = [
        DocumentChunk(
            chunk_id="CH-IDEMPOTENT-01",
            doc_id="DOC-IDEMPOTENT",
            doc_title="Idempotency Fixture",
            section_label="Section 1",
            clause_label="Clause 1.1",
            page=1,
            source_path="data/test.md",
            allowed_roles=["manager"],
            text_content="Managers must escalate material breaches within 24 hours.",
        )
    ]

    bm25 = BM25Indexer(index_path=str(tmp_path / "bm25.pkl"))
    assert bm25.build_and_save(chunks) == 1
    assert bm25.build_and_save(chunks) == 1
    assert (
        bm25.search("material breach escalation", top_k=5, role="manager").hits[0]["chunk_id"]
        == "CH-IDEMPOTENT-01"
    )

    qdrant = QdrantIndexer(
        storage_path=str(tmp_path / "qdrant_idempotent"),
        embedder=FakeEmbeddingGenerator(),
    )
    qdrant.index_chunks(chunks)
    first_count = qdrant.count()
    qdrant.index_chunks(chunks)
    second_count = qdrant.count()

    assert first_count == 1
    assert second_count == 1
    assert (
        qdrant.search("breach escalation", top_k=1, role="manager").hits[0]["chunk_id"]
        == "CH-IDEMPOTENT-01"
    )
    qdrant.close()


def test_rrf_ignores_malformed_rows_and_is_deterministic() -> None:
    """Verify RRF skips rows without chunk IDs and breaks ties deterministically."""
    fused = reciprocal_rank_fusion(
        [{"chunk_id": "CH-B", "text_content": "b"}, {"no_id": True}],
        [{"chunk_id": "CH-A", "text_content": "a"}],
        k=60,
        top_k=5,
    )

    assert [item["chunk_id"] for item in fused] == ["CH-A", "CH-B"]
    assert fused[0]["rrf_score"] == fused[1]["rrf_score"]

