"""Ablation configuration matrix, checkpointing, and metric aggregation.

Implements Phase 7 Part D requirements:
- Named configuration matrix: ``A0_baseline``, ``A1_heading_path``, ``A2_memory``,
  ``A3_router``, ``A4_grader``, ``A5_full_xai``, plus ``RBAC_OFF_DEMO`` (allowed
  only under ``BASELINE_ABLATION=True`` and labelled
  ``DEMONSTRATION ONLY — DO NOT USE AS RESULT``).
- Strict config isolation via ``apply_ablation_config`` context manager.
- Per-question JSONL checkpointing with ``--resume`` support.
- Profile-mixing guard (``ProfileMismatchError``) refusing to combine or resume
  runs across different ``llm_profile`` or ``llm_model`` values.
- Bootstrap 95% confidence intervals and interval-overlap flags.
"""

from __future__ import annotations

import json
import math
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator

from pydantic import BaseModel, Field

from src.config import settings
from src.core.memory import MemoryContext, rewrite_follow_up
from src.core.router import (
    DIRECT,
    DIRECT_REPLIES,
    SINGLE_SEARCH,
    SPLIT,
    RouteDecision,
    classify_question,
)
from src.core.security import chunk_visible_to_role, normalize_role
from src.core.spend_guard import spend_guard
from src.core.xai import validate_cited_chunks
from src.evaluation.gold_set import GoldQuestionItem
from src.evaluation.metrics import (
    answer_correctness_score,
    bootstrap_ci,
    intervals_overlap,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)
from src.rag.baseline import REFUSAL_TEXT, BaselineRAGPipeline, BaselineRAGResponse

DEMO_ONLY_BANNER = "DEMONSTRATION ONLY — DO NOT USE AS RESULT"


class ProfileMismatchError(ValueError):
    """Raised when an ablation run or table attempts to mix LLM profiles or models."""


@dataclass(frozen=True)
class AblationConfigSpec:
    """One named row in the Phase 7 ablation configuration matrix."""

    name: str
    description: str
    enable_heading_path: bool
    enable_rbac: bool
    enable_memory: bool
    enable_adaptive_router: bool
    enable_corrective_grader: bool
    enable_xai_output: bool
    is_demonstration_only: bool = False
    warning_banner: str = ""


ABLATION_MATRIX: dict[str, AblationConfigSpec] = {
    "A0_baseline": AblationConfigSpec(
        name="A0_baseline",
        description="Baseline RAG (heading path off, RBAC on, memory/router/grader/XAI off)",
        enable_heading_path=False,
        enable_rbac=True,
        enable_memory=False,
        enable_adaptive_router=False,
        enable_corrective_grader=False,
        enable_xai_output=False,
    ),
    "A1_heading_path": AblationConfigSpec(
        name="A1_heading_path",
        description="A0 + hierarchical heading_path in chunks and retrieval",
        enable_heading_path=True,
        enable_rbac=True,
        enable_memory=False,
        enable_adaptive_router=False,
        enable_corrective_grader=False,
        enable_xai_output=False,
    ),
    "A2_memory": AblationConfigSpec(
        name="A2_memory",
        description="A1 + multi-turn conversation memory rewriter",
        enable_heading_path=True,
        enable_rbac=True,
        enable_memory=True,
        enable_adaptive_router=False,
        enable_corrective_grader=False,
        enable_xai_output=False,
    ),
    "A3_router": AblationConfigSpec(
        name="A3_router",
        description="A2 + adaptive query router (SINGLE_SEARCH / SPLIT / DIRECT)",
        enable_heading_path=True,
        enable_rbac=True,
        enable_memory=True,
        enable_adaptive_router=True,
        enable_corrective_grader=False,
        enable_xai_output=False,
    ),
    "A4_grader": AblationConfigSpec(
        name="A4_grader",
        description="A3 + corrective passage relevance grader and single query rewrite",
        enable_heading_path=True,
        enable_rbac=True,
        enable_memory=True,
        enable_adaptive_router=True,
        enable_corrective_grader=True,
        enable_xai_output=False,
    ),
    "A5_full_xai": AblationConfigSpec(
        name="A5_full_xai",
        description="A4 + explainable output (strict citation validation & reasoning trace)",
        enable_heading_path=True,
        enable_rbac=True,
        enable_memory=True,
        enable_adaptive_router=True,
        enable_corrective_grader=True,
        enable_xai_output=True,
    ),
    "RBAC_OFF_DEMO": AblationConfigSpec(
        name="RBAC_OFF_DEMO",
        description="Unfiltered retrieval demonstration (RBAC disabled under BASELINE_ABLATION=True)",
        enable_heading_path=True,
        enable_rbac=False,
        enable_memory=False,
        enable_adaptive_router=False,
        enable_corrective_grader=False,
        enable_xai_output=False,
        is_demonstration_only=True,
        warning_banner=DEMO_ONLY_BANNER,
    ),
}


class JudgeOutput(BaseModel):
    """Schema for optional RAGAS-style LLM judge (--judge mode only)."""

    faithfulness: float = Field(default=1.0, ge=0.0, le=1.0)
    context_precision: float = Field(default=1.0, ge=0.0, le=1.0)
    answer_correctness: float = Field(default=1.0, ge=0.0, le=1.0)


@contextmanager
def apply_ablation_config(
    spec: AblationConfigSpec,
    allow_rbac_off: bool = False,
) -> Iterator[AblationConfigSpec]:
    """Apply ``spec`` flags to ``settings`` and restore original state on exit.

    Raises:
        RuntimeError: if ``spec.enable_rbac`` is False and ``allow_rbac_off``
            is False.
    """
    if not spec.enable_rbac and not allow_rbac_off:
        raise RuntimeError(
            "RBAC_OFF_DEMO requires explicit baseline ablation authorization (allow_rbac_off=True)."
        )

    snapshot = {
        "ENABLE_HEADING_PATH": settings.ENABLE_HEADING_PATH,
        "ENABLE_RBAC": settings.ENABLE_RBAC,
        "BASELINE_ABLATION": settings.BASELINE_ABLATION,
        "ENABLE_MEMORY": settings.ENABLE_MEMORY,
        "ENABLE_ADAPTIVE_ROUTER": settings.ENABLE_ADAPTIVE_ROUTER,
        "ENABLE_CORRECTIVE_GRADER": settings.ENABLE_CORRECTIVE_GRADER,
        "ENABLE_XAI_OUTPUT": settings.ENABLE_XAI_OUTPUT,
    }
    try:
        settings.ENABLE_HEADING_PATH = spec.enable_heading_path
        settings.ENABLE_RBAC = spec.enable_rbac
        settings.BASELINE_ABLATION = not spec.enable_rbac
        settings.ENABLE_MEMORY = spec.enable_memory
        settings.ENABLE_ADAPTIVE_ROUTER = spec.enable_adaptive_router
        settings.ENABLE_CORRECTIVE_GRADER = spec.enable_corrective_grader
        settings.ENABLE_XAI_OUTPUT = spec.enable_xai_output
        yield spec
    finally:
        for key, val in snapshot.items():
            setattr(settings, key, val)


def ensure_same_profile(
    records: list[dict[str, Any]],
    expected_profile: str,
    expected_model: str | None = None,
) -> None:
    """Raise ``ProfileMismatchError`` if any record came from a different profile/model."""
    for rec in records:
        rec_profile = str(rec.get("llm_profile", ""))
        rec_model = str(rec.get("llm_model", ""))
        if rec_profile and rec_profile != expected_profile:
            raise ProfileMismatchError(
                f"Refusing to mix LLM profiles in one run/table: "
                f"found '{rec_profile}', expected '{expected_profile}'."
            )
        if expected_model and rec_model and rec_model != expected_model:
            raise ProfileMismatchError(
                f"Refusing to mix LLM models in one run/table: "
                f"found '{rec_model}', expected '{expected_model}'."
            )


def load_checkpoint_rows(
    checkpoint_path: Path,
    expected_profile: str,
    expected_model: str,
) -> dict[str, dict[str, Any]]:
    """Load per-question checkpoint rows keyed by question ``id``."""
    if not checkpoint_path.exists():
        return {}
    rows: list[dict[str, Any]] = []
    with open(checkpoint_path, "r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                rows.append(json.loads(stripped))
    ensure_same_profile(rows, expected_profile, expected_model)
    return {str(r["id"]): r for r in rows if "id" in r}


def append_checkpoint_row(checkpoint_path: Path, row: dict[str, Any]) -> None:
    """Append a single completed question evaluation record to disk."""
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    with open(checkpoint_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Compute linear-interpolated percentile on a pre-sorted list."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return round(sorted_vals[0], 2)
    pos = (len(sorted_vals) - 1) * (pct / 100.0)
    lower = int(math.floor(pos))
    upper = int(math.ceil(pos))
    if lower == upper:
        return round(sorted_vals[lower], 2)
    weight = pos - lower
    return round(sorted_vals[lower] * (1.0 - weight) + sorted_vals[upper] * weight, 2)


def _normalize_route_label(route_str: str) -> str:
    """Normalize internal and API route strings for routing accuracy comparison."""
    upper = (route_str or "").strip().upper()
    if upper in ("SINGLE_SEARCH", "SINGLE"):
        return "SINGLE_SEARCH"
    if upper in ("SPLIT", "MULTI_PART"):
        return "SPLIT"
    if upper in ("REFUSE", "DIRECT"):
        return "REFUSE"
    return "SINGLE_SEARCH"


def evaluate_single_question(
    item: GoldQuestionItem,
    pipeline: BaselineRAGPipeline,
    chunk_lookup: dict[str, dict[str, Any]],
    run_judge: bool = False,
) -> dict[str, Any]:
    """Run one gold question under the currently active ``settings`` flags."""
    t0 = time.perf_counter()
    calls_before = spend_guard.calls_count
    tokens_before = spend_guard.tokens_count

    role = normalize_role(item.role_asking)
    query = item.question

    if settings.ENABLE_MEMORY:
        memory = rewrite_follow_up(pipeline.llm, query, turns=[])
    else:
        memory = MemoryContext(standalone_question=query, rewritten=False, turns_used=0)

    decision: RouteDecision | None = None
    route_used = SINGLE_SEARCH
    if settings.ENABLE_ADAPTIVE_ROUTER:
        decision = classify_question(pipeline.llm, memory.standalone_question)
        route_used = decision.api_route

    result: BaselineRAGResponse | None = None
    if decision is not None and decision.route == DIRECT:
        answer = decision.direct_reply or DIRECT_REPLIES["out_of_scope"]
        sources = []
        chunk_ids_used: list[str] = []
    elif decision is not None and decision.route == SPLIT:
        result = pipeline.ask_split(
            memory.standalone_question,
            list(decision.sub_questions),
            role=role,
        )
        answer = result.answer
        sources = result.sources
        chunk_ids_used = list(result.chunk_ids_used)
    else:
        result = pipeline.ask(
            query,
            role=role,
            rewritten_query=memory.standalone_question if memory.rewritten else None,
        )
        answer = result.answer
        sources = result.sources
        chunk_ids_used = list(result.chunk_ids_used)

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    router_calls = 1 if (decision is not None and decision.tokens_used > 0) else 0
    router_tokens = int(decision.tokens_used) if decision is not None else 0
    res_calls = (int(result.llm_stats.calls) + int(result.grader_calls)) if result is not None else 0
    res_tokens = (
        int(result.llm_stats.prompt_tokens)
        + int(result.llm_stats.completion_tokens)
        + int(result.grader_tokens)
        if result is not None
        else 0
    )
    llm_calls = max(0, spend_guard.calls_count - calls_before, router_calls + res_calls)
    llm_tokens = max(0, spend_guard.tokens_count - tokens_before, router_tokens + res_tokens)

    retrieved_ids = [s.chunk_id for s in sources if s.chunk_id]
    gold_ids = item.gold_chunk_ids

    # 1. Retrieval metrics (meaningful on answerable questions with gold chunks)
    if item.expected_behaviour == "answer" and gold_ids:
        rec1 = recall_at_k(retrieved_ids, gold_ids, 1)
        rec3 = recall_at_k(retrieved_ids, gold_ids, 3)
        rec5 = recall_at_k(retrieved_ids, gold_ids, 5)
        mrr_val = reciprocal_rank(retrieved_ids, gold_ids)
        ndcg5 = ndcg_at_k(retrieved_ids, gold_ids, 5)
    else:
        rec1 = rec3 = rec5 = mrr_val = ndcg5 = 0.0

    # 2. Refusal detection
    is_refusal = (
        REFUSAL_TEXT.lower() in answer.lower()
        or (decision is not None and decision.route == DIRECT)
        or (result is not None and result.grader_refused)
    )
    if item.expected_behaviour == "refuse":
        correct_refusal = 1.0 if is_refusal else 0.0
        false_refusal = 0.0
    else:
        correct_refusal = 0.0
        false_refusal = 1.0 if is_refusal else 0.0

    # 3. Leakage check (forbidden role chunk in sources/chunk_ids_used OR unauthorized keyword)
    leaked = False
    for cid in set(retrieved_ids) | set(chunk_ids_used):
        meta = chunk_lookup.get(cid)
        if meta is not None and not chunk_visible_to_role(meta, role):
            leaked = True
            break
    if not leaked and item.unauthorized_keywords:
        combined_surface = answer.lower() + " " + " ".join(
            (s.snippet or "").lower() for s in sources
        )
        for kw in item.unauthorized_keywords:
            if kw.lower() in combined_surface:
                leaked = True
                break

    # 4. Citation validity & support
    if not is_refusal:
        if sources:
            valid_citations = 0
            for src in sources:
                meta = chunk_lookup.get(src.chunk_id)
                if meta is not None and chunk_visible_to_role(meta, role):
                    valid_citations += 1
            citation_validity = valid_citations / float(len(sources))
            has_verbatim_support = any(
                bool(src.quote_snippet or src.snippet)
                and src.chunk_id in chunk_lookup
                and chunk_visible_to_role(chunk_lookup[src.chunk_id], role)
                for src in sources
            )
            citation_support = 1.0 if has_verbatim_support else 0.0
        else:
            citation_validity = 0.0
            citation_support = 0.0
    else:
        citation_validity = 1.0
        citation_support = 1.0

    # 5. Answer correctness (deterministic token F1/recall; plus retrieved snippet coverage in mock mode)
    if item.expected_behaviour == "answer":
        if is_refusal:
            ans_score = 0.0
        else:
            direct_score = answer_correctness_score(answer, item.gold_answer)
            # In mock mode, answer text is a canned template citing chunk IDs;
            # blend with citation-grounded snippet overlap so retrieval gains are visible.
            if settings.llm.is_mock and sources:
                grounded_text = answer + " " + " ".join(s.snippet for s in sources)
                ans_score = max(direct_score, answer_correctness_score(grounded_text, item.gold_answer))
            else:
                ans_score = direct_score
    else:
        ans_score = 1.0 if is_refusal else 0.0

    # 6. Optional LLM judge (--judge)
    faithfulness_val: float | None = None
    context_precision_val: float | None = None
    if run_judge and item.expected_behaviour == "answer" and not is_refusal:
        judge_prompt = (
            "Evaluate the compliance assistant response against the retrieved passages and gold answer.\n"
            "Return JSON with keys faithfulness (0..1), context_precision (0..1), answer_correctness (0..1).\n"
            f"Question: {query}\nGold Answer: {item.gold_answer}\nAssistant Answer: {answer}\n"
        )
        judge_out = pipeline.llm.complete_json(
            prompt=judge_prompt,
            schema=JudgeOutput,
            fallback=JudgeOutput(
                faithfulness=citation_support,
                context_precision=rec5,
                answer_correctness=ans_score,
            ),
            step="ablation_judge",
        )
        faithfulness_val = round(float(judge_out.faithfulness), 4)
        context_precision_val = round(float(judge_out.context_precision), 4)

    # 7. Routing accuracy
    expected_route_norm = _normalize_route_label(item.expected_route or "SINGLE_SEARCH")
    actual_route_norm = _normalize_route_label(route_used)
    route_correct = 1.0 if actual_route_norm == expected_route_norm else 0.0

    resolved_llm = settings.llm
    return {
        "id": item.id,
        "type": item.type,
        "role_asking": role,
        "expected_behaviour": item.expected_behaviour,
        "llm_profile": resolved_llm.profile,
        "llm_model": resolved_llm.model,
        "route_used": actual_route_norm,
        "expected_route": expected_route_norm,
        "route_correct": route_correct,
        "is_refusal": is_refusal,
        "correct_refusal": correct_refusal,
        "false_refusal": false_refusal,
        "leaked": 1.0 if leaked else 0.0,
        "recall@1": rec1,
        "recall@3": rec3,
        "recall@5": rec5,
        "mrr": mrr_val,
        "ndcg@5": ndcg5,
        "answer_correctness": ans_score,
        "citation_validity": citation_validity,
        "citation_support": citation_support,
        "faithfulness": faithfulness_val,
        "context_precision": context_precision_val,
        "latency_ms": elapsed_ms,
        "llm_calls": llm_calls,
        "llm_tokens": llm_tokens,
    }


def aggregate_ablation_rows(
    spec: AblationConfigSpec,
    rows: list[dict[str, Any]],
    baseline_ci: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Aggregate per-question ablation rows into configuration summary metrics + 95% CIs."""
    answerable_rows = [r for r in rows if r["expected_behaviour"] == "answer"]
    refusal_rows = [r for r in rows if r["expected_behaviour"] == "refuse"]
    restricted_rows = [
        r for r in rows if r["type"] == "role_restricted" or r["expected_behaviour"] == "refuse"
    ]

    rec1_ci = bootstrap_ci([float(r["recall@1"]) for r in answerable_rows])
    rec3_ci = bootstrap_ci([float(r["recall@3"]) for r in answerable_rows])
    rec5_ci = bootstrap_ci([float(r["recall@5"]) for r in answerable_rows])
    mrr_ci = bootstrap_ci([float(r["mrr"]) for r in answerable_rows])
    ndcg5_ci = bootstrap_ci([float(r["ndcg@5"]) for r in answerable_rows])
    ans_ci = bootstrap_ci([float(r["answer_correctness"]) for r in answerable_rows])
    cit_val_ci = bootstrap_ci([float(r["citation_validity"]) for r in answerable_rows])
    cit_sup_ci = bootstrap_ci([float(r["citation_support"]) for r in answerable_rows])
    crr_ci = bootstrap_ci([float(r["correct_refusal"]) for r in refusal_rows])
    frr_ci = bootstrap_ci([float(r["false_refusal"]) for r in answerable_rows])
    leak_ci = bootstrap_ci([float(r["leaked"]) for r in restricted_rows])
    route_ci = bootstrap_ci([float(r["route_correct"]) for r in rows])

    faith_vals = [float(r["faithfulness"]) for r in answerable_rows if r.get("faithfulness") is not None]
    ctx_prec_vals = [
        float(r["context_precision"]) for r in answerable_rows if r.get("context_precision") is not None
    ]
    faith_mean = round(sum(faith_vals) / len(faith_vals), 4) if faith_vals else None
    ctx_prec_mean = round(sum(ctx_prec_vals) / len(ctx_prec_vals), 4) if ctx_prec_vals else None

    latencies = sorted(float(r["latency_ms"]) for r in rows)
    median_ms = _percentile(latencies, 50.0)
    p95_ms = _percentile(latencies, 95.0)
    avg_calls = round(sum(int(r["llm_calls"]) for r in rows) / max(len(rows), 1), 2)
    avg_tokens = round(sum(int(r["llm_tokens"]) for r in rows) / max(len(rows), 1), 1)

    ci_map = {
        "recall@5": rec5_ci,
        "ndcg@5": ndcg5_ci,
        "answer_correctness": ans_ci,
        "correct_refusal_rate": crr_ci,
        "routing_accuracy": route_ci,
        "leakage_rate": leak_ci,
    }

    overlap_flags: dict[str, dict[str, Any]] = {}
    if baseline_ci:
        for metric_key, cur_ci in ci_map.items():
            base_m = baseline_ci.get(metric_key)
            if base_m is not None:
                overlaps = intervals_overlap(cur_ci, base_m)
                overlap_flags[metric_key] = {
                    "ci_overlaps_baseline": overlaps,
                    "statistically_significant_diff": not overlaps,
                }

    return {
        "config_name": spec.name,
        "description": spec.description,
        "is_demonstration_only": spec.is_demonstration_only,
        "warning_banner": spec.warning_banner,
        "flags": asdict(spec),
        "n_total": len(rows),
        "n_answerable": len(answerable_rows),
        "n_refusal": len(refusal_rows),
        "metrics": {
            "recall@1": rec1_ci["mean"],
            "recall@3": rec3_ci["mean"],
            "recall@5": rec5_ci["mean"],
            "mrr": mrr_ci["mean"],
            "ndcg@5": ndcg5_ci["mean"],
            "answer_correctness": ans_ci["mean"],
            "faithfulness": faith_mean,
            "context_precision": ctx_prec_mean,
            "citation_validity_rate": cit_val_ci["mean"],
            "citation_support_rate": cit_sup_ci["mean"],
            "correct_refusal_rate": crr_ci["mean"],
            "false_refusal_rate": frr_ci["mean"],
            "leakage_rate": leak_ci["mean"],
            "routing_accuracy": route_ci["mean"],
            "latency_median_ms": median_ms,
            "latency_p95_ms": p95_ms,
            "llm_calls_per_query": avg_calls,
            "tokens_per_query": avg_tokens,
        },
        "ci_95": ci_map,
        "vs_baseline_A0": overlap_flags,
    }
