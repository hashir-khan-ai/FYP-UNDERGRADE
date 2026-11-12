"""Phase 6A: Explainable Output (XAI) — citation validation and safe reasoning traces.

Enforces two strict server-side invariants:
1. Anti-hallucination & RBAC citation guard: any cited ``chunk_id`` that was not in
   the passages passed to the generator OR is not permitted for the authenticated
   user's role is dropped, and ``citations_dropped`` increments by count only.
2. Safe user-facing reasoning trace: reports ordered execution steps (question
   rewritten, route, passages retrieved/kept, grader path, retry, self-limits hit)
   without exposing prompts, passage text, other users' data, or counts of
   restricted documents.
"""

import re
from typing import Any

from src.config import settings
from src.core.security import chunk_visible_to_role, normalize_role

MAX_QUOTE_SNIPPET_CHARS = 200

_IGNORE_TOKENS = {"none", "n/a", "null", "nil", "-"}


def extract_verbatim_snippet(text: str, max_chars: int = MAX_QUOTE_SNIPPET_CHARS) -> str:
    """Return up to ``max_chars`` characters taken verbatim from ``text``."""
    if not text:
        return ""
    stripped = text.strip()
    return stripped[:max_chars]


def build_heading_path(passage: dict[str, Any]) -> str:
    """Resolve the hierarchical heading path for a passage dictionary."""
    explicit = str(passage.get("heading_path") or "").strip()
    if explicit:
        return explicit
    section = str(passage.get("section_label") or passage.get("section") or "").strip()
    clause = str(passage.get("clause_label") or passage.get("clause") or "").strip()
    if section and clause and clause != section:
        return f"{section} > {clause}"
    return section or clause or str(passage.get("doc_title") or "Document")


def extract_candidate_chunk_ids(raw_text: str) -> list[str]:
    """Parse candidate chunk IDs from the generator's ``Supporting Chunks:`` line."""
    chunk_line = re.search(
        r"(?im)^\s*supporting chunks?\s*:\s*(.+?)\s*$",
        raw_text,
    )
    if not chunk_line:
        return []

    raw_candidates = re.split(r"[,;\s]+", chunk_line.group(1))
    candidates: list[str] = []
    for token in raw_candidates:
        cleaned = token.strip().strip("[]`\"'().")
        if not cleaned or cleaned.lower() in _IGNORE_TOKENS:
            continue
        if cleaned not in candidates:
            candidates.append(cleaned)
    return candidates


def validate_cited_chunks(
    candidate_ids: list[str],
    context_passages: list[dict[str, Any]],
    role: str | None = None,
) -> tuple[list[str], int]:
    """Validate candidate cited chunk IDs against context passages and role permissions.

    Drops any ``chunk_id`` that:
    - was not present in ``context_passages`` given to the generator, OR
    - is not permitted for ``role`` under server-side RBAC.

    Args:
        candidate_ids: Chunk IDs emitted by the model.
        context_passages: Final kept passages supplied to the model.
        role: Authenticated user role (optional only when RBAC is disabled in tests).

    Returns:
        Tuple of ``(valid_chunk_ids, citations_dropped_count)``.
    """
    rbac_on = settings.rbac_enabled
    normalized_role = normalize_role(role) if (role is not None and rbac_on) else None

    permitted_ids: set[str] = set()
    for passage in context_passages:
        cid = str(passage.get("chunk_id") or "").strip()
        if not cid:
            continue
        if normalized_role is not None and not chunk_visible_to_role(passage, normalized_role):
            continue
        permitted_ids.add(cid)

    valid: list[str] = []
    dropped = 0
    for cid in candidate_ids:
        if cid in permitted_ids:
            if cid not in valid:
                valid.append(cid)
        else:
            dropped += 1

    return valid, dropped


def filter_passages_for_citations(
    context_passages: list[dict[str, Any]],
    valid_chunk_ids: list[str],
    role: str | None = None,
) -> list[dict[str, Any]]:
    """Return the subset of ``context_passages`` matching ``valid_chunk_ids`` in order.

    Enforces a final RBAC check so a restricted passage can never appear in any
    citation field.
    """
    rbac_on = settings.rbac_enabled
    normalized_role = normalize_role(role) if (role is not None and rbac_on) else None

    by_id: dict[str, dict[str, Any]] = {}
    for passage in context_passages:
        cid = str(passage.get("chunk_id") or "").strip()
        if not cid:
            continue
        if normalized_role is not None and not chunk_visible_to_role(passage, normalized_role):
            continue
        by_id[cid] = passage

    return [by_id[cid] for cid in valid_chunk_ids if cid in by_id]


def build_safe_reasoning_trace(
    *,
    question_rewritten: bool,
    route: str,
    passages_retrieved: int,
    passages_kept: int,
    grader_path: str | None,
    retry_used: bool,
    limits_hit: bool,
) -> list[str]:
    """Build the user-facing 6-step XAI reasoning trace.

    Safety invariants:
    - Never includes prompt text.
    - Never includes passage text of kept or dropped passages.
    - Never includes other users' data.
    - Never includes counts of restricted or role-excluded documents.
    """
    grader_label = grader_path if grader_path else "disabled"
    return [
        f"Step 1: Question rewritten: {'yes' if question_rewritten else 'no'}.",
        f"Step 2: Route: {route}.",
        f"Step 3: Passages retrieved: {int(passages_retrieved)}; kept: {int(passages_kept)}.",
        f"Step 4: Grader path: {grader_label}.",
        f"Step 5: Retry used: {'yes' if retry_used else 'no'}.",
        f"Step 6: Self-limits hit: {'yes' if limits_hit else 'no'}.",
    ]

