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
from src.core.claim_check import verify_answer_claims
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
from src.db.connection import get_db_connection
from src.db.repository import Repository
from src.evaluation.gold_set import GoldQuestionItem
from src.evaluation.metrics import (
    answer_correctness_score,
    bootstrap_ci,
    intervals_overlap,
    ndcg_at_k,
    numeric_exact_match,
    paired_bootstrap_ci,
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
    enable_claim_check: bool = False
    enable_calculator: bool = False
    bm25_strict_match: bool = False
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
    "A6_claim_check": AblationConfigSpec(
        name="A6_claim_check",
        description="A5 + post-generation atomic claim-level grounding check",
        enable_heading_path=True,
        enable_rbac=True,
        enable_memory=True,
        enable_adaptive_router=True,
        enable_corrective_grader=True,
        enable_xai_output=True,
        enable_claim_check=True,
        enable_calculator=False,
    ),
    "A7_calculator": AblationConfigSpec(
        name="A7_calculator",
        description="A6 + deterministic AST-whitelist compliance calculator",
        enable_heading_path=True,
        enable_rbac=True,
        enable_memory=True,
        enable_adaptive_router=True,
        enable_corrective_grader=True,
        enable_xai_output=True,
        enable_claim_check=True,
        enable_calculator=True,
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
        "ENABLE_CLAIM_CHECK": settings.ENABLE_CLAIM_CHECK,
        "ENABLE_CALCULATOR": settings.ENABLE_CALCULATOR,
        "BM25_STRICT_MATCH": settings.BM25_STRICT_MATCH,
    }
    try:
        settings.ENABLE_HEADING_PATH = spec.enable_heading_path
        settings.ENABLE_RBAC = spec.enable_rbac
        settings.BASELINE_ABLATION = not spec.enable_rbac
        settings.ENABLE_MEMORY = spec.enable_memory
        settings.ENABLE_ADAPTIVE_ROUTER = spec.enable_adaptive_router
        settings.ENABLE_CORRECTIVE_GRADER = spec.enable_corrective_grader
        settings.ENABLE_XAI_OUTPUT = spec.enable_xai_output
        settings.ENABLE_CLAIM_CHECK = spec.enable_claim_check
        settings.ENABLE_CALCULATOR = spec.enable_calculator
        settings.BM25_STRICT_MATCH = spec.bm25_strict_match
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
    telemetry_floor = _telemetry_floor()

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
    # Phase 7b: LLM usage is read from the llm_calls telemetry window, which
    # records one row per gateway call with an explicit cache_hit flag. Live
    # (uncached) and cached calls are therefore counted separately and
    # consistently across configurations. The judge (if any) runs after this
    # window so it never inflates pipeline cost.
    usage = _read_usage_window(telemetry_floor)
    live_calls = int(usage["live_calls"])
    cached_calls = int(usage["cached_calls"])
    live_tokens = int(usage["live_tokens"])
    cached_tokens = int(usage["cached_tokens"])
    if live_calls == 0 and cached_calls == 0:
        # Telemetry write failures are swallowed by the gateway; fall back to
        # the spend guard, which only counts uncached calls.
        live_calls = max(0, spend_guard.calls_count - calls_before)
        live_tokens = max(0, spend_guard.tokens_count - tokens_before)

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

    # 7. Routing accuracy: only defined when the router actually ran AND the
    # question carries a routing label. Otherwise it is None ("n/a"), never a
    # misleading constant produced by comparing a fixed default route.
    actual_route_norm = _normalize_route_label(route_used)
    if settings.ENABLE_ADAPTIVE_ROUTER and item.expected_route:
        expected_route_norm: str | None = _normalize_route_label(item.expected_route)
        route_correct: float | None = 1.0 if actual_route_norm == expected_route_norm else 0.0
    else:
        expected_route_norm = _normalize_route_label(item.expected_route) if item.expected_route else None
        route_correct = None

    refused_without_llm = bool(is_refusal and live_calls == 0 and cached_calls == 0)

    unsupported_claim_rate: float | None = None
    numeric_em: float | None = None
    if item.expected_behaviour == "answer":
        if is_refusal:
            if numeric_exact_match("", item.gold_answer) is not None:
                numeric_em = 0.0
        else:
            passages_for_check = [
                chunk_lookup[s.chunk_id]
                if s.chunk_id in chunk_lookup
                else {
                    "chunk_id": s.chunk_id,
                    "text_content": s.snippet,
                    "allowed_roles": [role],
                }
                for s in sources
            ]
            claim_audit = verify_answer_claims(
                answer,
                passages_for_check,
                role,
                rbac_enabled=settings.rbac_enabled,
            )
            unsupported_claim_rate = claim_audit.unsupported_claim_rate
            numeric_em = numeric_exact_match(
                answer,
                item.gold_answer,
                result.calculator if result is not None else None,
            )

    resolved_llm = settings.llm
    return {
        "id": item.id,
        "type": item.type,
        "role_asking": role,
        "expected_behaviour": item.expected_behaviour,
        "llm_profile": resolved_llm.profile,
        "llm_model": resolved_llm.model,
        "evidence_status": "MOCK, not evidence" if resolved_llm.is_mock else f"LIVE ({resolved_llm.profile})",
        "router_enabled": bool(settings.ENABLE_ADAPTIVE_ROUTER),
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
        "unsupported_claim_rate": unsupported_claim_rate,
        "numeric_exact_match": numeric_em,
        "latency_ms": elapsed_ms,
        "live_calls": live_calls,
        "cached_calls": cached_calls,
        "live_tokens": live_tokens,
        "cached_tokens": cached_tokens,
        "refused_without_llm": refused_without_llm,
    }


def _telemetry_floor() -> int:
    """Return the current max ``llm_calls.id`` (0 if telemetry is unavailable)."""
    try:
        with get_db_connection() as conn:
            return Repository(conn).get_max_llm_call_id()
    except Exception:
        return 0


def _read_usage_window(after_id: int) -> dict[str, int]:
    """Read live/cached LLM usage logged after ``after_id`` (zeros on failure)."""
    try:
        with get_db_connection() as conn:
            return Repository(conn).get_llm_usage_after(after_id)
    except Exception:
        return {"live_calls": 0, "cached_calls": 0, "live_tokens": 0, "cached_tokens": 0}


def aggregate_ablation_rows(
    spec: AblationConfigSpec,
    rows: list[dict[str, Any]],
    baseline_ci: dict[str, dict[str, Any]] | None = None,
    previous_rows: list[dict[str, Any]] | None = None,
    previous_spec: AblationConfigSpec | None = None,
) -> dict[str, Any]:
    """Aggregate per-question ablation rows into configuration summary metrics + 95% CIs.

    Cost figures are reported as three separate quantities: live (uncached)
    calls, cached calls, and refusals that made no LLM call. Token cost is
    computed from live calls only. Routing accuracy is ``None`` (rendered
    "n/a") when the router was off or no row carries a routing label.
    """
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

    route_vals = [
        float(r["route_correct"])
        for r in rows
        if r.get("route_correct") is not None and r.get("router_enabled", spec.enable_adaptive_router)
    ]
    route_ci: dict[str, Any] | None = bootstrap_ci(route_vals) if route_vals else None
    routing_accuracy = route_ci["mean"] if route_ci is not None else None

    faith_vals = [float(r["faithfulness"]) for r in answerable_rows if r.get("faithfulness") is not None]
    ctx_prec_vals = [
        float(r["context_precision"]) for r in answerable_rows if r.get("context_precision") is not None
    ]
    unsup_vals = [
        float(r["unsupported_claim_rate"])
        for r in answerable_rows
        if r.get("unsupported_claim_rate") is not None
    ]
    num_em_vals = [
        float(r["numeric_exact_match"])
        for r in answerable_rows
        if r.get("numeric_exact_match") is not None
    ]
    faith_mean = round(sum(faith_vals) / len(faith_vals), 4) if faith_vals else None
    ctx_prec_mean = round(sum(ctx_prec_vals) / len(ctx_prec_vals), 4) if ctx_prec_vals else None
    unsup_mean = round(sum(unsup_vals) / len(unsup_vals), 4) if unsup_vals else None
    num_em_mean = round(sum(num_em_vals) / len(num_em_vals), 4) if num_em_vals else None
    evidence_status = (
        "MOCK, not evidence"
        if any(str(r.get("llm_profile", "")) == "mock" for r in rows)
        else "LIVE"
    )

    n_rows = max(len(rows), 1)
    latencies = sorted(float(r["latency_ms"]) for r in rows)
    uncached_latencies = sorted(
        float(r["latency_ms"])
        for r in rows
        if int(r.get("cached_calls", 0)) == 0 and int(r.get("live_calls", 0)) > 0
    )
    live_calls_pq = round(sum(int(r.get("live_calls", 0)) for r in rows) / n_rows, 2)
    cached_calls_pq = round(sum(int(r.get("cached_calls", 0)) for r in rows) / n_rows, 2)
    live_tokens_pq = round(sum(int(r.get("live_tokens", 0)) for r in rows) / n_rows, 1)
    cached_tokens_pq = round(sum(int(r.get("cached_tokens", 0)) for r in rows) / n_rows, 1)
    refusals_without_llm = sum(1 for r in rows if r.get("refused_without_llm"))

    ci_map: dict[str, dict[str, Any]] = {
        "recall@5": rec5_ci,
        "ndcg@5": ndcg5_ci,
        "answer_correctness": ans_ci,
        "correct_refusal_rate": crr_ci,
        "leakage_rate": leak_ci,
    }
    if route_ci is not None:
        ci_map["routing_accuracy"] = route_ci

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

    # Paired bootstrap CI vs adjacent preceding configuration (Ak vs Ak-1)
    vs_adjacent_prev: dict[str, Any] | None = None
    if previous_rows and previous_spec:
        prev_by_id = {r["id"]: r for r in previous_rows if "id" in r}
        cur_by_id = {r["id"]: r for r in rows if "id" in r}
        common_ids = [qid for qid in cur_by_id if qid in prev_by_id]
        common_ans_ids = [qid for qid in common_ids if cur_by_id[qid]["expected_behaviour"] == "answer"]

        r5_cur = [float(cur_by_id[qid]["recall@5"]) for qid in common_ans_ids]
        r5_prev = [float(prev_by_id[qid]["recall@5"]) for qid in common_ans_ids]

        ndcg_cur = [float(cur_by_id[qid]["ndcg@5"]) for qid in common_ans_ids]
        ndcg_prev = [float(prev_by_id[qid]["ndcg@5"]) for qid in common_ans_ids]

        ans_cur = [float(cur_by_id[qid]["answer_correctness"]) for qid in common_ans_ids]
        ans_prev = [float(prev_by_id[qid]["answer_correctness"]) for qid in common_ans_ids]

        cit_cur = [float(cur_by_id[qid]["citation_validity"]) for qid in common_ans_ids]
        cit_prev = [float(prev_by_id[qid]["citation_validity"]) for qid in common_ans_ids]

        lat_cur = [float(cur_by_id[qid]["latency_ms"]) for qid in common_ids]
        lat_prev = [float(prev_by_id[qid]["latency_ms"]) for qid in common_ids]

        vs_adjacent_prev = {
            "previous_config_name": previous_spec.name,
            "metrics": {
                "recall@5": paired_bootstrap_ci(r5_cur, r5_prev),
                "ndcg@5": paired_bootstrap_ci(ndcg_cur, ndcg_prev),
                "answer_correctness": paired_bootstrap_ci(ans_cur, ans_prev),
                "citation_validity": paired_bootstrap_ci(cit_cur, cit_prev),
                "latency_ms": paired_bootstrap_ci(lat_cur, lat_prev),
            },
        }

    retrieval_metrics = {
        "recall@1": rec1_ci["mean"],
        "recall@3": rec3_ci["mean"],
        "recall@5": rec5_ci["mean"],
        "mrr": mrr_ci["mean"],
        "ndcg@5": ndcg5_ci["mean"],
        "context_precision": ctx_prec_mean,
    }

    answer_metrics = {
        "answer_correctness": ans_ci["mean"],
        "faithfulness": faith_mean,
        "citation_validity_rate": cit_val_ci["mean"],
        "citation_support_rate": cit_sup_ci["mean"],
        "unsupported_claim_rate": unsup_mean,
        "numeric_exact_match": num_em_mean,
        "correct_refusal_rate": crr_ci["mean"],
        "false_refusal_rate": frr_ci["mean"],
        "leakage_rate": leak_ci["mean"],
        "routing_accuracy": routing_accuracy,
    }

    layer_costs_and_latencies = {
        "latency_median_ms": _percentile(latencies, 50.0),
        "latency_p95_ms": _percentile(latencies, 95.0),
        "latency_uncached_median_ms": (
            _percentile(uncached_latencies, 50.0) if uncached_latencies else None
        ),
        "latency_uncached_p95_ms": (
            _percentile(uncached_latencies, 95.0) if uncached_latencies else None
        ),
        "live_calls_per_query": live_calls_pq,
        "cached_calls_per_query": cached_calls_pq,
        "refusals_without_llm": refusals_without_llm,
        "live_tokens_per_query": live_tokens_pq,
        "cached_tokens_per_query": cached_tokens_pq,
    }

    flat_metrics = {**retrieval_metrics, **answer_metrics, **layer_costs_and_latencies}

    return {
        "config_name": spec.name,
        "description": spec.description,
        "evidence_status": evidence_status,
        "is_demonstration_only": spec.is_demonstration_only,
        "warning_banner": spec.warning_banner,
        "flags": asdict(spec),
        "n_total": len(rows),
        "n_answerable": len(answerable_rows),
        "n_refusal": len(refusal_rows),
        "n_route_labelled": len(route_vals),
        "n_uncached_latency": len(uncached_latencies),
        "retrieval_metrics": retrieval_metrics,
        "answer_metrics": answer_metrics,
        "layer_costs_and_latencies": layer_costs_and_latencies,
        "metrics": flat_metrics,
        "ci_95": ci_map,
        "vs_baseline_A0": overlap_flags,
        "vs_adjacent_prev": vs_adjacent_prev,
    }
