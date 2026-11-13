"""Hash-chained audit log canonical hashing and verification helpers."""

from __future__ import annotations

import hashlib
from typing import Any

GENESIS_PREV_HASH = "GENESIS"

AUDIT_HASH_COLUMNS: tuple[str, ...] = (
    "session_id",
    "user_id",
    "user_role",
    "query_text",
    "final_route",
    "retrieved_chunk_ids",
    "relevance_scores",
    "retry_count",
    "rewritten_query",
    "response_text",
    "reasoning_trace",
    "citations_json",
    "latency_ms",
    "tokens_prompt",
    "tokens_completion",
    "llm_profile",
    "llm_calls",
    "cached_calls",
    "spend_guard_hit",
    "prompt_version",
    "llm_model",
    "candidates_retrieved",
    "candidates_filtered",
    "router_confidence",
    "router_fallback_reason",
    "sub_questions",
    "step_timings_json",
    "grader_path",
    "grader_relevant_count",
    "grader_ambiguous_count",
    "grader_irrelevant_count",
    "grader_rewrite_used",
    "grader_rewritten_query",
    "grader_refused",
    "grader_refusal_reason",
    "grader_calls",
    "grader_tokens",
    "grader_latency_ms",
    "citation_count",
    "citations_dropped",
    "heading_path_enabled",
    "claim_check_json",
    "calculator_json",
)


def compute_audit_hash(prev_hash: str, values: tuple[Any, ...]) -> str:
    """Compute the deterministic SHA-256 hash for an audit log entry in the chain."""
    serialized: list[str] = []
    for val in values:
        if val is None:
            serialized.append("")
        elif isinstance(val, float):
            serialized.append(f"{val:.2f}")
        elif isinstance(val, bool):
            serialized.append("1" if val else "0")
        else:
            serialized.append(str(val))
    raw = (prev_hash or GENESIS_PREV_HASH) + "|" + "|".join(serialized)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

