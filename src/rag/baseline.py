"""Baseline standard RAG: hybrid retrieval, RRF, CPU re-ranking, generation."""

import logging
import re
import time
from typing import Any

from pydantic import BaseModel, Field

from src.config import settings
from src.core.llm_client import ResilientLLMClient, llm_client
from src.core.prompts import load_prompt
from src.ingestion.indexer import BM25Indexer, QdrantIndexer

logger = logging.getLogger(__name__)

REFUSAL_TEXT = (
    "I cannot find sufficient authoritative guidance in the current regulatory "
    "corpus for this request."
)


# ==============================================================================
# Pydantic schemas for the baseline API and pipeline
# ==============================================================================
class SourceChunk(BaseModel):
    """One citation returned with a baseline answer."""

    chunk_id: str
    doc_title: str
    section: str
    clause: str | None = None
    page: int | None = None
    score: float
    snippet: str


class RAGTimings(BaseModel):
    retrieval_ms: float = 0.0
    rerank_ms: float = 0.0
    generation_ms: float = 0.0
    total_ms: float = 0.0


class BaselineRAGRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=1000, description="User compliance question")
    session_id: str | None = Field(default=None, description="Optional session identifier")


class BaselineRAGResponse(BaseModel):
    query: str
    answer: str
    sources: list[SourceChunk] = Field(default_factory=list)
    chunk_ids_used: list[str] = Field(default_factory=list)
    timings: RAGTimings = Field(default_factory=RAGTimings)
    cached: bool = False
    llm_profile: str = ""
    llm_model: str = ""


# ==============================================================================
# Local CPU cross-encoder re-ranker
# ==============================================================================
class CrossEncoderReranker:
    """Lazy loader for a SentenceTransformers cross-encoder running on CPU."""

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or settings.RERANKER_MODEL_NAME
        self._model = None

    def _get_model(self):
        if self._model is None:
            logger.info("Loading local cross-encoder '%s' on CPU...", self.model_name)
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:
                raise ImportError(
                    "sentence-transformers is required for cross-encoder re-ranking."
                ) from exc
            self._model = CrossEncoder(self.model_name, device="cpu")
        return self._model

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_n: int = 5,
    ) -> list[dict[str, Any]]:
        """Score (query, passage) pairs and return the top-n descending."""
        if not candidates:
            return []
        if len(candidates) == 1:
            result = dict(candidates[0])
            result.setdefault("score", 0.0)
            return [result][:top_n]

        model = self._get_model()
        pairs = [(query, candidate.get("text_content", "")) for candidate in candidates]
        scores = model.predict(pairs, show_progress_bar=False)

        scored = []
        for candidate, score in zip(candidates, scores):
            item = dict(candidate)
            item["score"] = float(score)
            scored.append(item)
        scored.sort(key=lambda item: (-item["score"], item.get("chunk_id", "")))
        return scored[:top_n]


class MockCrossEncoderReranker:
    """Fast deterministic re-ranker for unit tests that need no downloads."""

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_n: int = 5,
    ) -> list[dict[str, Any]]:
        scored = []
        for index, candidate in enumerate(candidates):
            item = dict(candidate)
            item["score"] = 0.95 - (index * 0.05)
            scored.append(item)
        return scored[:top_n]


# ==============================================================================
# Reciprocal Rank Fusion
# ==============================================================================
def reciprocal_rank_fusion(
    bm25_results: list[dict[str, Any]],
    vector_results: list[dict[str, Any]],
    k: int = 60,
    top_k: int = 20,
) -> list[dict[str, Any]]:
    """Merge sparse and dense rankings with RRF: sum(1 / (k + rank))."""
    if k < 0:
        raise ValueError("RRF k must be non-negative")

    scores: dict[str, float] = {}
    chunk_map: dict[str, dict[str, Any]] = {}

    for results in (bm25_results, vector_results):
        for rank, document in enumerate(results, start=1):
            chunk_id = document.get("chunk_id")
            if not chunk_id:
                continue
            chunk_map.setdefault(chunk_id, document)
            scores[chunk_id] = scores.get(chunk_id, 0.0) + (1.0 / (k + rank))

    ordered = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))
    fused: list[dict[str, Any]] = []
    for chunk_id in ordered[:top_k]:
        item = dict(chunk_map[chunk_id])
        item["rrf_score"] = scores[chunk_id]
        fused.append(item)
    return fused


# ==============================================================================
# Baseline pipeline
# ==============================================================================
class BaselineRAGPipeline:
    """Standard RAG baseline with hybrid retrieval and grounded generation.

    1. BM25 top-k plus dense vector top-k.
    2. Reciprocal Rank Fusion.
    3. CPU cross-encoder re-ranking to top-n.
    4. Versioned answer prompt through the single LLM gateway.
    """

    def __init__(
        self,
        qdrant_indexer: QdrantIndexer | None = None,
        bm25_indexer: BM25Indexer | None = None,
        reranker: CrossEncoderReranker | None = None,
        llm: ResilientLLMClient | None = None,
    ) -> None:
        self.qdrant = qdrant_indexer or QdrantIndexer()
        self.bm25 = bm25_indexer or BM25Indexer()
        self.reranker = reranker or CrossEncoderReranker()
        self.llm = llm or llm_client
        self._prompt_template = load_prompt("answer")

    def retrieve(self, query: str) -> tuple[list[dict[str, Any]], float]:
        """Run BM25 and dense retrieval, then merge with RRF."""
        start = time.perf_counter()
        top_k = settings.RETRIEVAL_TOP_K_HYBRID

        try:
            bm25_hits = self.bm25.search(query, top_k=top_k)
        except Exception as exc:
            logger.warning("BM25 retrieval failed (%s).", type(exc).__name__)
            bm25_hits = []
        try:
            vector_hits = self.qdrant.search(query, top_k=top_k)
        except Exception as exc:
            logger.warning("Vector retrieval failed (%s).", type(exc).__name__)
            vector_hits = []

        fused = reciprocal_rank_fusion(
            bm25_hits,
            vector_hits,
            k=settings.RETRIEVAL_RRF_K,
            top_k=top_k,
        )
        return fused, (time.perf_counter() - start) * 1000.0

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], float]:
        """Re-rank fused candidates with the CPU cross-encoder."""
        start = time.perf_counter()
        reranked = self.reranker.rerank(query, candidates, top_n=settings.RERANKER_TOP_N)
        return reranked, (time.perf_counter() - start) * 1000.0

    def _format_passages(self, passages: list[dict[str, Any]]) -> str:
        blocks: list[str] = []
        for passage in passages:
            blocks.append(
                "<passage "
                f"chunk_id=\"{passage.get('chunk_id', 'UNKNOWN')}\" "
                f"doc=\"{passage.get('doc_title', 'Document')}\" "
                f"section=\"{passage.get('section_label', '')}\">\n"
                f"{passage.get('text_content', '').strip()}\n"
                "</passage>"
            )
        return "\n\n".join(blocks)

    def generate(
        self,
        query: str,
        passages: list[dict[str, Any]],
    ) -> tuple[str, list[str], bool, float]:
        """Generate an answer strictly from the final passages."""
        start = time.perf_counter()
        passage_ids = [passage["chunk_id"] for passage in passages if passage.get("chunk_id")]

        if not passages:
            return REFUSAL_TEXT, [], False, 0.0

        prompt = self._prompt_template.format(
            passages=self._format_passages(passages),
            question=query,
        )
        response = self.llm.complete(prompt=prompt, temperature=0.0, step="answer")
        generation_ms = (time.perf_counter() - start) * 1000.0

        raw_text = response.content.strip()
        cited: list[str] = []
        chunk_line = re.search(
            r"(?im)^\s*supporting chunks?\s*:\s*(.+?)\s*$",
            raw_text,
        )
        if chunk_line:
            candidates = re.split(r"[,;\s]+", chunk_line.group(1))
            for candidate in candidates:
                cleaned = candidate.strip().strip("[]`\"'")
                if cleaned in passage_ids and cleaned not in cited:
                    cited.append(cleaned)

        answer = re.sub(
            r"(?ims)^\s*supporting chunks?\s*:.*$",
            "",
            raw_text,
        ).strip()
        answer = re.sub(r"(?is)^\s*answer\s*:\s*", "", answer).strip()

        if not answer or REFUSAL_TEXT.lower() in raw_text.lower():
            return REFUSAL_TEXT, [], response.cached, generation_ms
        if not cited:
            # The model saw every final passage; if it omitted labels, cite the
            # supplied context rather than silently returning an unsourced answer.
            cited = passage_ids

        return answer, cited, response.cached, generation_ms

    def ask(self, query: str) -> BaselineRAGResponse:
        """Execute the complete baseline RAG request."""
        total_start = time.perf_counter()

        candidates, retrieval_ms = self.retrieve(query)
        final_passages, rerank_ms = self.rerank(query, candidates)
        answer, cited_ids, cached, generation_ms = self.generate(query, final_passages)

        sources: list[SourceChunk] = []
        for passage in final_passages:
            text = passage.get("text_content", "")
            sources.append(
                SourceChunk(
                    chunk_id=passage.get("chunk_id", ""),
                    doc_title=passage.get("doc_title", "Document"),
                    section=passage.get("section_label", ""),
                    clause=passage.get("clause_label"),
                    page=passage.get("page"),
                    score=float(passage.get("score", 0.0)),
                    snippet=text[:200] + ("..." if len(text) > 200 else ""),
                )
            )

        llm = settings.llm
        return BaselineRAGResponse(
            query=query,
            answer=answer,
            sources=sources,
            chunk_ids_used=cited_ids,
            timings=RAGTimings(
                retrieval_ms=round(retrieval_ms, 2),
                rerank_ms=round(rerank_ms, 2),
                generation_ms=round(generation_ms, 2),
                total_ms=round((time.perf_counter() - total_start) * 1000.0, 2),
            ),
            cached=cached,
            llm_profile=llm.profile,
            llm_model=llm.model,
        )

    def close(self) -> None:
        """Release the embedded Qdrant file lock."""
        self.qdrant.close()


# Global pipeline instance used by the API and smoke script.
baseline_pipeline = BaselineRAGPipeline()
