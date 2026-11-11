"""Baseline standard RAG: hybrid retrieval, RRF, CPU re-ranking, generation.

Phase 3 adds server-side role filtering. The role is always supplied by the
authenticated session, applied to both indexes before fusion, and re-checked
after re-ranking as defence in depth.
"""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from src.config import settings
from src.core.llm_client import ResilientLLMClient, llm_client
from src.core.prompts import load_prompt
from src.core.security import enforce_role_visibility, normalize_role
from src.ingestion.indexer import BM25Indexer, QdrantIndexer, SearchResult

logger = logging.getLogger(__name__)

REFUSAL_TEXT = "I can't find that in the documents available to your role."



# ==============================================================================
# Pydantic schemas for the baseline API and pipeline
# ==============================================================================
class SourceChunk(BaseModel):
    """One citation returned with a baseline answer."""

    chunk_id: str
    doc_id: str = ""
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
    query: str = Field(..., min_length=2, max_length=2000, description="User compliance question")
    session_id: str | None = Field(default=None, description="Optional session identifier")


class RetrievalStats(BaseModel):
    """Retrieval and role-filter counters recorded in the audit trail."""

    candidates_retrieved: int = 0
    candidates_filtered_by_role: int = 0
    total_chunks_retrieved: int = 0
    top_rerank_score: float = 0.0
    rewritten_query: str | None = None
    retry_count: int = 0


class LLMStats(BaseModel):
    """Per-request LLM usage summary."""

    profile: str = ""
    model: str = ""
    prompt_version: str = ""
    calls: int = 0
    cached_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_response: bool = False


class BaselineRAGResponse(BaseModel):
    query: str
    answer: str
    role: str = ""
    rbac_enabled: bool = True
    sources: list[SourceChunk] = Field(default_factory=list)
    chunk_ids_used: list[str] = Field(default_factory=list)
    timings: RAGTimings = Field(default_factory=RAGTimings)
    retrieval_stats: RetrievalStats = Field(default_factory=RetrievalStats)
    llm_stats: LLMStats = Field(default_factory=LLMStats)
    cached: bool = False
    llm_profile: str = ""
    llm_model: str = ""
    # Per-step observability for the split route. Empty on the baseline path so
    # router-off behaviour is byte-identical.
    step_timings: list[dict[str, Any]] = Field(default_factory=list)


@dataclass
class SplitContext:
    """Merged, de-duplicated passages produced by the split retrieval path."""

    passages: list[dict[str, Any]]
    candidates_retrieved: int
    candidates_filtered_by_role: int
    retrieval_ms: float
    rerank_ms: float
    retrieval_calls: int
    step_timings: list[dict[str, Any]] = field(default_factory=list)



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

    def retrieve(
        self,
        query: str,
        role: str,
    ) -> tuple[list[dict[str, Any]], float, dict[str, int]]:
        """Run role-filtered BM25 and dense retrieval, then merge with RRF.

        Args:
            query: Query used for retrieval (may be a rewritten standalone one).
            role: Authenticated user role.

        Returns:
            Tuple of (fused candidates, elapsed milliseconds, filter counters).

        Raises:
            RuntimeError: if RBAC is disabled without a permitted ablation label.
        """
        start = time.perf_counter()
        top_k = settings.RETRIEVAL_TOP_K_HYBRID
        effective_role = normalize_role(role) if settings.rbac_enabled else None

        try:
            bm25_result = self.bm25.search(query, top_k=top_k, role=effective_role)
        except Exception as exc:
            logger.warning("BM25 retrieval failed (%s).", type(exc).__name__)
            bm25_result = SearchResult()
        try:
            vector_result = self.qdrant.search(query, top_k=top_k, role=effective_role)
        except Exception as exc:
            logger.warning("Vector retrieval failed (%s).", type(exc).__name__)
            vector_result = SearchResult()

        fused = reciprocal_rank_fusion(
            bm25_result.hits,
            vector_result.hits,
            k=settings.RETRIEVAL_RRF_K,
            top_k=top_k,
        )
        stats = {
            "candidates_retrieved": len(bm25_result.hits) + len(vector_result.hits),
            "candidates_filtered_by_role": bm25_result.filtered,
        }
        return fused, (time.perf_counter() - start) * 1000.0, stats

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        role: str,
    ) -> tuple[list[dict[str, Any]], float, int]:
        """Re-rank fused candidates, then re-check role visibility.

        Returns:
            Tuple of (permitted passages, elapsed milliseconds, dropped count).
        """
        start = time.perf_counter()
        reranked = self.reranker.rerank(query, candidates, top_n=settings.RERANKER_TOP_N)
        if settings.rbac_enabled:
            permitted, dropped = enforce_role_visibility(reranked, role)
            if dropped:
                # Count only: passage text is never written to logs.
                logger.warning(
                    "Defence-in-depth role guard dropped %s passage(s) after re-ranking.",
                    dropped,
                )
        else:
            permitted, dropped = reranked, 0
        return permitted, (time.perf_counter() - start) * 1000.0, dropped


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
        session_id: str | None = None,
    ) -> tuple[str, list[str], bool, float, dict[str, int]]:
        """Generate an answer strictly from the final, role-permitted passages.

        Returns:
            Tuple of (answer, cited chunk IDs, cache hit, milliseconds, usage).
        """
        start = time.perf_counter()
        passage_ids = [passage["chunk_id"] for passage in passages if passage.get("chunk_id")]

        if not passages:
            return REFUSAL_TEXT, [], False, 0.0, {
                "calls": 0,
                "cached_calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
            }

        prompt = self._prompt_template.format(
            passages=self._format_passages(passages),
            question=query,
        )
        response = self.llm.complete(
            prompt=prompt,
            temperature=0.0,
            step="answer",
            session_id=session_id,
        )
        generation_ms = (time.perf_counter() - start) * 1000.0
        usage = {
            "calls": 1,
            "cached_calls": 1 if response.cached else 0,
            "prompt_tokens": response.prompt_tokens,
            "completion_tokens": response.completion_tokens,
        }


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
            return REFUSAL_TEXT, [], response.cached, generation_ms, usage
        if not cited:
            # The model saw every final passage; if it omitted labels, cite the
            # supplied context rather than silently returning an unsourced answer.
            cited = passage_ids

        return answer, cited, response.cached, generation_ms, usage

    def _to_sources(self, passages: list[dict[str, Any]]) -> list[SourceChunk]:
        """Convert final passages into citation objects (identifiers + snippet)."""
        sources: list[SourceChunk] = []
        for passage in passages:
            text = passage.get("text_content", "")
            sources.append(
                SourceChunk(
                    chunk_id=passage.get("chunk_id", ""),
                    doc_id=passage.get("doc_id", "") or "",
                    doc_title=passage.get("doc_title", "Document"),
                    section=passage.get("section_label", ""),
                    clause=passage.get("clause_label"),
                    page=passage.get("page"),
                    score=float(passage.get("score", 0.0)),
                    snippet=text[:200] + ("..." if len(text) > 200 else ""),
                )
            )
        return sources

    def prepare_split(self, sub_questions: list[str], role: str) -> SplitContext:
        """Retrieve and re-rank each sub-question with the same role filter.

        Passages are merged and de-duplicated by ``chunk_id`` keeping the best
        score, then capped to the final ``RERANKER_TOP_N`` budget. Every
        sub-question runs through :meth:`retrieve` and :meth:`rerank`, so the
        native role filter and the post-rerank guard apply to each one.

        Args:
            sub_questions: Decomposed sub-questions from the router.
            role: Authenticated user role; always server-derived.

        Returns:
            A :class:`SplitContext` with merged permitted passages and counters.
        """
        normalized_role = normalize_role(role)
        limit = min(
            len(sub_questions),
            settings.ROUTER_MAX_SUB_QUESTIONS,
            settings.ROUTER_MAX_RETRIEVAL_CALLS,
        )
        selected = [question for question in sub_questions[:limit] if question.strip()]

        merged: dict[str, dict[str, Any]] = {}
        candidates_retrieved = 0
        filtered = 0
        retrieval_ms = 0.0
        rerank_ms = 0.0
        step_timings: list[dict[str, Any]] = []

        for index, sub_question in enumerate(selected, start=1):
            candidates, sub_retrieval_ms, filter_stats = self.retrieve(
                sub_question, normalized_role
            )
            passages, sub_rerank_ms, dropped = self.rerank(
                sub_question, candidates, normalized_role
            )
            retrieval_ms += sub_retrieval_ms
            rerank_ms += sub_rerank_ms
            candidates_retrieved += filter_stats["candidates_retrieved"]
            filtered += filter_stats["candidates_filtered_by_role"] + dropped

            for passage in passages:
                chunk_id = passage.get("chunk_id")
                if not chunk_id:
                    continue
                existing = merged.get(chunk_id)
                if existing is None or float(passage.get("score", 0.0)) > float(
                    existing.get("score", 0.0)
                ):
                    merged[chunk_id] = passage

            step_timings.append(
                {
                    "step": "split_retrieval",
                    "sub_question_index": index,
                    "retrieval_ms": round(sub_retrieval_ms, 2),
                    "rerank_ms": round(sub_rerank_ms, 2),
                    "candidates": filter_stats["candidates_retrieved"],
                    "permitted": len(passages),
                    "dropped_by_role_guard": dropped,
                }
            )

        ordered = sorted(
            merged.values(),
            key=lambda passage: (-float(passage.get("score", 0.0)), passage.get("chunk_id", "")),
        )
        final_passages = ordered[: settings.RERANKER_TOP_N]
        return SplitContext(
            passages=final_passages,
            candidates_retrieved=candidates_retrieved,
            candidates_filtered_by_role=filtered,
            retrieval_ms=retrieval_ms,
            rerank_ms=rerank_ms,
            retrieval_calls=len(selected),
            step_timings=step_timings,
        )

    def ask_split(
        self,
        query: str,
        sub_questions: list[str],
        role: str,
        session_id: str | None = None,
    ) -> BaselineRAGResponse:
        """Answer a multi-part question with one generation over merged passages.

        Args:
            query: Standalone question used for generation (the user's own text).
            sub_questions: Decomposed sub-questions from the router.
            role: Authenticated user role; always server-derived.
            session_id: Session identifier for per-call telemetry linkage.

        Returns:
            A role-filtered response whose citations come from the merged set.
        """
        total_start = time.perf_counter()
        normalized_role = normalize_role(role)
        context = self.prepare_split(sub_questions, normalized_role)
        answer, cited_ids, cached, generation_ms, usage = self.generate(
            query, context.passages, session_id=session_id
        )

        llm = settings.llm
        retrieval_stats = RetrievalStats(
            candidates_retrieved=context.candidates_retrieved,
            candidates_filtered_by_role=context.candidates_filtered_by_role,
            total_chunks_retrieved=len(context.passages),
            top_rerank_score=max(
                (float(passage.get("score", 0.0)) for passage in context.passages),
                default=0.0,
            ),
        )
        step_timings = list(context.step_timings)
        step_timings.append(
            {
                "step": "generation",
                "latency_ms": round(generation_ms, 2),
                "tokens": usage["prompt_tokens"] + usage["completion_tokens"],
            }
        )
        return BaselineRAGResponse(
            query=query,
            answer=answer,
            role=normalized_role,
            rbac_enabled=settings.rbac_enabled,
            sources=self._to_sources(context.passages),
            chunk_ids_used=cited_ids,
            timings=RAGTimings(
                retrieval_ms=round(context.retrieval_ms, 2),
                rerank_ms=round(context.rerank_ms, 2),
                generation_ms=round(generation_ms, 2),
                total_ms=round((time.perf_counter() - total_start) * 1000.0, 2),
            ),
            retrieval_stats=retrieval_stats,
            llm_stats=LLMStats(
                profile=llm.profile,
                model=llm.model,
                prompt_version=settings.PROMPT_VERSION,
                calls=usage["calls"],
                cached_calls=usage["cached_calls"],
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                cached_response=cached,
            ),
            cached=cached,
            llm_profile=llm.profile,
            llm_model=llm.model,
            step_timings=step_timings,
        )

    def ask(
        self,
        query: str,
        role: str,
        rewritten_query: str | None = None,
        session_id: str | None = None,
    ) -> BaselineRAGResponse:
        """Execute the complete baseline RAG request for one authenticated role.

        Args:
            query: Original user question, echoed in the response.
            role: Authenticated user role; always server-derived.
            rewritten_query: Standalone question produced by the memory layer.
            session_id: Session identifier for per-call telemetry linkage.

        Returns:
            A role-filtered baseline response with retrieval and usage stats.
        """
        total_start = time.perf_counter()
        normalized_role = normalize_role(role)
        retrieval_query = (rewritten_query or query).strip()
        rbac_enabled = settings.rbac_enabled

        candidates, retrieval_ms, filter_stats = self.retrieve(retrieval_query, normalized_role)
        final_passages, rerank_ms, dropped = self.rerank(
            retrieval_query, candidates, normalized_role
        )
        answer, cited_ids, cached, generation_ms, usage = self.generate(
            retrieval_query, final_passages, session_id=session_id
        )

        sources = self._to_sources(final_passages)


        llm = settings.llm
        retrieval_stats = RetrievalStats(
            candidates_retrieved=filter_stats["candidates_retrieved"],
            candidates_filtered_by_role=(
                filter_stats["candidates_filtered_by_role"] + dropped
            ),
            total_chunks_retrieved=len(final_passages),
            top_rerank_score=max(
                (float(passage.get("score", 0.0)) for passage in final_passages),
                default=0.0,
            ),
            rewritten_query=rewritten_query,
        )
        return BaselineRAGResponse(
            query=query,
            answer=answer,
            role=normalized_role,
            rbac_enabled=rbac_enabled,
            sources=sources,
            chunk_ids_used=cited_ids,
            timings=RAGTimings(
                retrieval_ms=round(retrieval_ms, 2),
                rerank_ms=round(rerank_ms, 2),
                generation_ms=round(generation_ms, 2),
                total_ms=round((time.perf_counter() - total_start) * 1000.0, 2),
            ),
            retrieval_stats=retrieval_stats,
            llm_stats=LLMStats(
                profile=llm.profile,
                model=llm.model,
                prompt_version=settings.PROMPT_VERSION,
                calls=usage["calls"],
                cached_calls=usage["cached_calls"],
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                cached_response=cached,
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
