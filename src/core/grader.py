"""Layer 2: Corrective Grader — passage relevance check, query rewrite, and refusal.

Runs after retrieval and re-ranking, on every route that retrieves (single_search
and split), and only on passages that have ALREADY passed the RBAC role filter.
The grader never sees or reveals restricted content — it receives only the passages
that the upstream role guard has explicitly permitted.

Safety invariants:
* RBAC filter and post-rerank guard apply BEFORE any passage reaches this module.
* A rewritten query is retrieved under the SAME role filter; access is never widened.
* Text such as "mark all passages relevant" inside a document or question cannot
  change grading logic — the prompt wraps those as untrusted data with explicit
  instructions to ignore embedded commands.
* ENABLE_CORRECTIVE_GRADER=False is a fully transparent no-op; callers see the
  same passages they would have seen without this module.
* All failures fall back to keeping the passages (RBAC still enforced). The grader
  can NEVER fail open on security: an error keeps passages, never widens access.
* Hard caps: one rewrite, GRADER_MAX_CALLS_PER_REQUEST grader calls per request,
  and the existing spend guard apply throughout.
"""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.config import settings
from src.core.llm_client import LLMClientError, ResilientLLMClient
from src.core.prompts import load_prompt
from src.core.spend_guard import SpendGuardExceededError, spend_guard

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic schemas for strict JSON I/O
# ---------------------------------------------------------------------------

GradeLabel = Literal["relevant", "ambiguous", "irrelevant"]

GRADER_PATH_SHORTCUT_KEEP = "shortcut_keep"
GRADER_PATH_SHORTCUT_REJECT = "shortcut_reject"
GRADER_PATH_LLM = "llm_grade"


class PassageGrade(BaseModel):
    """Grade for one passage returned by the LLM grader."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    label: GradeLabel
    reason: str = Field(max_length=300, default="")

    @field_validator("reason", mode="before")
    @classmethod
    def _truncate_reason(cls, v: Any) -> str:
        return str(v)[:300] if v else ""


class GraderOutput(BaseModel):
    """Strict JSON envelope returned by the LLM grader call."""

    model_config = ConfigDict(extra="forbid")

    grades: list[PassageGrade] = Field(default_factory=list)


class RewriteOutput(BaseModel):
    """Strict JSON envelope returned by the LLM rewrite call."""

    model_config = ConfigDict(extra="forbid")

    rewritten_query: str = Field(max_length=400, default="")

    @field_validator("rewritten_query", mode="before")
    @classmethod
    def _truncate_query(cls, v: Any) -> str:
        s = str(v).strip()
        return s[: settings.GRADER_MAX_REWRITE_CHARS] if s else ""


# ---------------------------------------------------------------------------
# Grader result dataclass
# ---------------------------------------------------------------------------


@dataclass
class GraderDecision:
    """Outcome of one grader invocation (first pass or retry)."""

    path: str  # shortcut_keep | shortcut_reject | llm_grade
    kept_passages: list[dict[str, Any]] = field(default_factory=list)
    relevant_count: int = 0
    ambiguous_count: int = 0
    irrelevant_count: int = 0
    rewrite_used: bool = False
    rewritten_query: str | None = None
    refused: bool = False
    refusal_reason: str = ""  # generic category: "no_evidence" | "cap_hit"
    grader_calls: int = 0
    total_latency_ms: float = 0.0
    total_tokens: int = 0
    fallback_used: bool = False


# ---------------------------------------------------------------------------
# Core grader
# ---------------------------------------------------------------------------


def _format_passages_for_grader(passages: list[dict[str, Any]]) -> str:
    """Format passages for the grader prompt without leaking role metadata."""
    blocks: list[str] = []
    for passage in passages:
        chunk_id = passage.get("chunk_id", "UNKNOWN")
        # Only chunk_id and text_content are injected; role data is never sent.
        text = passage.get("text_content", "").strip()
        blocks.append(f'<passage chunk_id="{chunk_id}">\n{text}\n</passage>')
    return "\n\n".join(blocks)


def _scores_from_passages(passages: list[dict[str, Any]]) -> list[float]:
    return [float(p.get("score", 0.0)) for p in passages]


def _apply_shortcut(passages: list[dict[str, Any]]) -> str | None:
    """Return 'keep', 'reject', or None when shortcuts are disabled/inconclusive."""
    if not settings.GRADER_SHORTCUT_ENABLED or not passages:
        return None

    scores = _scores_from_passages(passages)
    top_score = max(scores)
    medium_count = sum(1 for s in scores if s >= settings.GRADER_SHORTCUT_MEDIUM_SCORE)

    # All passages below the low threshold → go straight to rewrite/refuse.
    if top_score < settings.GRADER_SHORTCUT_REJECT_SCORE:
        return "reject"

    # Top score above the high threshold AND enough medium passages → keep.
    if (
        top_score >= settings.GRADER_SHORTCUT_KEEP_SCORE
        and medium_count >= settings.GRADER_MIN_RELEVANT_PASSAGES
    ):
        return "keep"

    return None


def _grade_passages_via_llm(
    llm: ResilientLLMClient,
    question: str,
    passages: list[dict[str, Any]],
    valid_chunk_ids: set[str],
    session_id: str | None,
) -> tuple[GraderOutput | None, int, float]:
    """
    Call the LLM grader once and validate the output.

    Returns (output_or_None, tokens_used, latency_ms).
    None means invalid JSON after one repair retry (caller must fall back).
    """
    prompt_template = load_prompt("grader")
    # Sanitize question: strip angle brackets so user text cannot break out of
    # the <user_question> data block.
    safe_question = re.sub(r"[<>]", " ", question).strip()
    passage_text = _format_passages_for_grader(passages)
    prompt = (
        prompt_template.replace("{question}", safe_question).replace("{passages}", passage_text)
    )

    tokens_before = spend_guard.tokens_count
    start = time.perf_counter()
    try:
        result = llm.complete_json(
            prompt=prompt,
            schema=GraderOutput,
            fallback=None,
            step="grader",
            session_id=session_id,
        )
    except (LLMClientError, SpendGuardExceededError) as exc:
        elapsed = (time.perf_counter() - start) * 1000.0
        tokens = max(spend_guard.tokens_count - tokens_before, 0)
        logger.warning("Grader LLM call failed (%s); will fall back.", type(exc).__name__)
        return None, tokens, elapsed

    elapsed = (time.perf_counter() - start) * 1000.0
    tokens = max(spend_guard.tokens_count - tokens_before, 0)

    # Security: reject any chunk_id that was not in our input set (injection guard).
    filtered_grades = [g for g in result.grades if g.chunk_id in valid_chunk_ids]
    if len(filtered_grades) != len(result.grades):
        logger.warning(
            "Grader returned %d unknown chunk_id(s); they were rejected.",
            len(result.grades) - len(filtered_grades),
        )

    return GraderOutput(grades=filtered_grades), tokens, elapsed


def _select_passages(
    grades: list[PassageGrade],
    passage_map: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, int, int]:
    """
    Select passages to keep based on grades.

    Returns (kept_passages, relevant_count, ambiguous_count, irrelevant_count).
    Strategy: take all relevant passages, then fill up to GRADER_MAX_AMBIGUOUS_KEPT
    with ambiguous ones (up to the RERANKER_TOP_N budget).
    """
    relevant: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    irrelevant_count = 0

    for grade in grades:
        p = passage_map.get(grade.chunk_id)
        if p is None:
            continue
        if grade.label == "relevant":
            relevant.append(p)
        elif grade.label == "ambiguous":
            ambiguous.append(p)
        else:
            irrelevant_count += 1

    # Ambiguous passages may be kept up to the config cap.
    ambiguous_kept = ambiguous[: settings.GRADER_MAX_AMBIGUOUS_KEPT]
    kept = (relevant + ambiguous_kept)[: settings.RERANKER_TOP_N]
    return kept, len(relevant), len(ambiguous), irrelevant_count


def _rewrite_query(
    llm: ResilientLLMClient,
    question: str,
    session_id: str | None,
) -> tuple[str | None, int, float]:
    """
    Rewrite the query once using the rewrite prompt.

    Returns (rewritten_or_None, tokens, latency_ms).
    None means the rewrite failed or produced an empty string.
    """
    prompt_template = load_prompt("rewrite")
    safe_question = re.sub(r"[<>]", " ", question).strip()
    prompt = (
        prompt_template.replace("{question}", safe_question).replace(
            "{max_chars}", str(settings.GRADER_MAX_REWRITE_CHARS)
        )
    )

    tokens_before = spend_guard.tokens_count
    start = time.perf_counter()
    try:
        result = llm.complete_json(
            prompt=prompt,
            schema=RewriteOutput,
            fallback=RewriteOutput(rewritten_query=question),
            step="grader_rewrite",
            session_id=session_id,
        )
    except (LLMClientError, SpendGuardExceededError) as exc:
        elapsed = (time.perf_counter() - start) * 1000.0
        tokens = max(spend_guard.tokens_count - tokens_before, 0)
        logger.warning("Query rewrite failed (%s); will retry with original.", type(exc).__name__)
        return None, tokens, elapsed

    elapsed = (time.perf_counter() - start) * 1000.0
    tokens = max(spend_guard.tokens_count - tokens_before, 0)
    rewritten = result.rewritten_query.strip()
    if not rewritten:
        return None, tokens, elapsed
    return rewritten, tokens, elapsed


def grade(
    llm: ResilientLLMClient,
    question: str,
    passages: list[dict[str, Any]],
    retrieval_fn: Any,  # Callable[[str], list[dict[str, Any]]]
    role: str,
    session_id: str | None = None,
) -> GraderDecision:
    """
    Grade passages for one retrieval result and decide keep/rewrite/refuse.

    Args:
        llm:            The single LLM gateway.
        question:       The user's (possibly rewritten) question.
        passages:       Role-permitted, re-ranked passages.
        retrieval_fn:   ``Callable[[str], list[dict]]`` — runs retrieval + rerank
                        with the same role filter; called at most once on retry.
        role:           Authenticated role (never widened by this function).
        session_id:     Telemetry linkage.

    Returns:
        A :class:`GraderDecision` with the final passages and observability data.
    """
    total_start = time.perf_counter()
    grader_calls = 0
    total_tokens = 0
    decision = GraderDecision(path=GRADER_PATH_LLM)

    if not passages:
        decision.refused = True
        decision.refusal_reason = "no_evidence"
        decision.path = GRADER_PATH_SHORTCUT_REJECT
        decision.total_latency_ms = (time.perf_counter() - total_start) * 1000.0
        return decision

    passage_map: dict[str, dict[str, Any]] = {
        p["chunk_id"]: p for p in passages if p.get("chunk_id")
    }
    valid_chunk_ids = set(passage_map.keys())

    # ------------------------------------------------------------------
    # Step 1: Check shortcut conditions
    # ------------------------------------------------------------------
    shortcut = _apply_shortcut(passages)

    if shortcut == "keep":
        logger.debug("Grader shortcut: keep (top score >= %.2f).", settings.GRADER_SHORTCUT_KEEP_SCORE)
        decision.path = GRADER_PATH_SHORTCUT_KEEP
        decision.kept_passages = list(passages)
        # Count all as relevant for observability (shortcut assumption).
        decision.relevant_count = len(passages)
        decision.total_latency_ms = (time.perf_counter() - total_start) * 1000.0
        return decision

    if shortcut == "reject":
        logger.debug(
            "Grader shortcut: reject (all scores below %.2f).", settings.GRADER_SHORTCUT_REJECT_SCORE
        )
        decision.path = GRADER_PATH_SHORTCUT_REJECT
        # Fall through to rewrite/refuse logic below.
        grades_output = None
    else:
        # ------------------------------------------------------------------
        # Step 2: LLM grading (first pass)
        # ------------------------------------------------------------------
        grader_calls += 1
        grades_output, toks, lat = _grade_passages_via_llm(
            llm, question, passages, valid_chunk_ids, session_id
        )
        total_tokens += toks
        decision.grader_calls = grader_calls
        decision.total_latency_ms = lat

        if grades_output is None:
            # LLM grader failed; fallback = keep passages (RBAC still enforced).
            logger.warning("Grader fallback: keeping passages after LLM failure.")
            decision.fallback_used = True
            decision.kept_passages = list(passages)
            decision.relevant_count = len(passages)
            decision.total_latency_ms = (time.perf_counter() - total_start) * 1000.0
            decision.total_tokens = total_tokens
            return decision

        kept, rel, amb, irrel = _select_passages(grades_output.grades, passage_map)
        decision.relevant_count = rel
        decision.ambiguous_count = amb
        decision.irrelevant_count = irrel

        if rel >= settings.GRADER_MIN_RELEVANT_PASSAGES:
            # Enough relevant passages → generate as normal.
            decision.path = GRADER_PATH_LLM
            decision.kept_passages = kept
            decision.grader_calls = grader_calls
            decision.total_latency_ms = (time.perf_counter() - total_start) * 1000.0
            decision.total_tokens = total_tokens
            return decision

    # ------------------------------------------------------------------
    # Step 3: Not enough relevant passages → rewrite once and retry
    # ------------------------------------------------------------------
    cap_remaining = settings.GRADER_MAX_CALLS_PER_REQUEST - grader_calls
    if cap_remaining <= 0:
        logger.warning("Grader cap hit; refusing.")
        decision.refused = True
        decision.refusal_reason = "cap_hit"
        decision.grader_calls = grader_calls
        decision.total_latency_ms = (time.perf_counter() - total_start) * 1000.0
        decision.total_tokens = total_tokens
        return decision

    rewritten, rw_toks, rw_lat = _rewrite_query(llm, question, session_id)
    total_tokens += rw_toks

    if not rewritten or rewritten == question:
        # Rewrite returned the same query or failed; refuse.
        logger.info("Grader rewrite returned same/empty query; refusing.")
        decision.refused = True
        decision.refusal_reason = "no_evidence"
        decision.grader_calls = grader_calls
        decision.total_latency_ms = (time.perf_counter() - total_start) * 1000.0
        decision.total_tokens = total_tokens
        return decision

    decision.rewrite_used = True
    decision.rewritten_query = rewritten
    logger.info("Grader rewriting query for retry (original len=%d).", len(question))

    # Retry retrieval under the SAME role filter — retrieval_fn enforces this.
    try:
        retry_passages = retrieval_fn(rewritten)
    except Exception as exc:
        logger.warning("Grader retry retrieval failed (%s); refusing.", type(exc).__name__)
        decision.refused = True
        decision.refusal_reason = "no_evidence"
        decision.grader_calls = grader_calls
        decision.total_latency_ms = (time.perf_counter() - total_start) * 1000.0
        decision.total_tokens = total_tokens
        return decision

    if not retry_passages:
        decision.refused = True
        decision.refusal_reason = "no_evidence"
        decision.grader_calls = grader_calls
        decision.total_latency_ms = (time.perf_counter() - total_start) * 1000.0
        decision.total_tokens = total_tokens
        return decision

    retry_map: dict[str, dict[str, Any]] = {
        p["chunk_id"]: p for p in retry_passages if p.get("chunk_id")
    }
    retry_valid_ids = set(retry_map.keys())

    # Grade the retry passages (second LLM call).
    grader_calls += 1
    retry_grades, rt_toks, rt_lat = _grade_passages_via_llm(
        llm, rewritten, retry_passages, retry_valid_ids, session_id
    )
    total_tokens += rt_toks

    if retry_grades is None:
        # Retry grader failed; fallback = keep retry passages (RBAC still enforced).
        logger.warning("Grader retry fallback: keeping retry passages after LLM failure.")
        decision.fallback_used = True
        decision.kept_passages = list(retry_passages)
        decision.relevant_count = len(retry_passages)
        decision.grader_calls = grader_calls
        decision.total_latency_ms = (time.perf_counter() - total_start) * 1000.0
        decision.total_tokens = total_tokens
        return decision

    kept2, rel2, amb2, irrel2 = _select_passages(retry_grades.grades, retry_map)
    # Update counts to reflect the retry.
    decision.relevant_count = rel2
    decision.ambiguous_count = amb2
    decision.irrelevant_count = irrel2

    if rel2 >= settings.GRADER_MIN_RELEVANT_PASSAGES:
        decision.kept_passages = kept2
        decision.grader_calls = grader_calls
        decision.total_latency_ms = (time.perf_counter() - total_start) * 1000.0
        decision.total_tokens = total_tokens
        return decision

    # Still not enough → refuse with the uniform refusal wording.
    # The refusal does not reveal whether restricted documents exist or why evidence
    # is missing beyond a generic category.
    logger.info("Grader: not enough relevant passages after retry; refusing.")
    decision.refused = True
    decision.refusal_reason = "no_evidence"
    decision.grader_calls = grader_calls
    decision.total_latency_ms = (time.perf_counter() - total_start) * 1000.0
    decision.total_tokens = total_tokens
    return decision


def grader_metadata(decision: GraderDecision) -> dict[str, object]:
    """Return a JSON-serialisable summary for the audit row (no passage text)."""
    return {
        "enabled": True,
        "path": decision.path,
        "relevant_count": decision.relevant_count,
        "ambiguous_count": decision.ambiguous_count,
        "irrelevant_count": decision.irrelevant_count,
        "rewrite_used": decision.rewrite_used,
        "refused": decision.refused,
        "refusal_reason": decision.refusal_reason,
        "grader_calls": decision.grader_calls,
        "fallback_used": decision.fallback_used,
        "latency_ms": round(decision.total_latency_ms, 2),
        "tokens_used": decision.total_tokens,
    }


__all__ = [
    "GradeLabel",
    "GraderDecision",
    "GraderOutput",
    "PassageGrade",
    "RewriteOutput",
    "GRADER_PATH_LLM",
    "GRADER_PATH_SHORTCUT_KEEP",
    "GRADER_PATH_SHORTCUT_REJECT",
    "grade",
    "grader_metadata",
]

