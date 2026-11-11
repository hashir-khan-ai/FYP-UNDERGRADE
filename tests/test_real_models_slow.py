"""Integration test marked slow that exercises real CPU embedding and re-ranker models on a fixture."""

import pytest
from src.ingestion.embeddings import LocalCPUEmbeddings
from src.rag.baseline import CrossEncoderReranker


@pytest.mark.slow
def test_real_cpu_models_on_fixture() -> None:
    """
    Validates that real local CPU models (BGE-small embeddings and MiniLM re-ranker)
    execute correctly on a small fixture without errors.
    """
    # 1. Test real local CPU embeddings
    embedder = LocalCPUEmbeddings(model_name="BAAI/bge-small-en-v1.5")
    texts = [
        "The minimum Common Equity Tier 1 (CET1) capital ratio is 4.5 percent.",
        "Customer due diligence measures must be applied for occasional transactions of 15000 euros.",
    ]
    vectors = embedder.embed_texts(texts)
    assert len(vectors) == 2
    assert len(vectors[0]) == 384, "bge-small-en-v1.5 must produce 384-dimensional vectors"

    query_vec = embedder.embed_query("What is the CET1 capital ratio?")
    assert len(query_vec) == 384

    # 2. Test real local CPU Cross-Encoder re-ranker
    reranker = CrossEncoderReranker(model_name="cross-encoder/ms-marco-MiniLM-L-6-v2")
    candidates = [
        {"chunk_id": "C-MLR", "text_content": texts[1]},
        {"chunk_id": "C-CET1", "text_content": texts[0]},
    ]

    reranked = reranker.rerank("What is the CET1 capital ratio?", candidates, top_n=2)
    assert len(reranked) == 2
    # The CET1 chunk must score higher than the KYC/MLR chunk for a CET1 question
    assert reranked[0]["chunk_id"] == "C-CET1", "CET1 passage should be re-ranked above MLR passage"
    assert reranked[0]["score"] > reranked[1]["score"]

