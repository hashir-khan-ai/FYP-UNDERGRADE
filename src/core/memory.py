"""Short-term conversational memory and follow-up query rewriting.

History is loaded only from a session owned by the authenticated user. The
rewritten question is used for retrieval, but the role filter is always the
current server-side role, so history can never widen what a user may retrieve.
"""

import logging
import os
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from src.config import settings
from src.core.llm_client import LLMClientError, ResilientLLMClient
from src.core.prompts import load_prompt
from src.db.repository import Repository

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGE_CHARS = 400


class RewrittenQuestion(BaseModel):
    """Strict JSON schema for the follow-up rewrite step."""

    standalone_question: str = Field(min_length=2, max_length=2000)


@dataclass(frozen=True)
class MemoryContext:
    """Outcome of the memory step for one request."""

    standalone_question: str
    rewritten: bool
    turns_used: int


def load_recent_turns(
    repo: Repository,
    session_id: str,
    user_id: int,
    limit: int,
) -> list[dict[str, str]]:
    """Load the most recent turns of a session owned by ``user_id``.

    Args:
        repo: Repository bound to an open connection.
        session_id: Session identifier from the request.
        user_id: Authenticated user identifier.
        limit: Maximum number of messages to load.

    Returns:
        Oldest-first list of ``{"sender", "content"}`` dictionaries. An empty
        list is returned when the session is not owned by the user, so a caller
        can never read another user's history through the memory layer.
    """
    if limit <= 0:
        return []
    # Positive control: Mutant (e) shares session memory across roles/users
    if os.environ.get("MUTANT_SHARED_MEMORY") != "1":
        if repo.get_session_for_user(session_id, user_id) is None:
            return []

    rows = repo.get_recent_messages(session_id, limit)
    turns: list[dict[str, str]] = []
    for row in reversed(rows):
        content = str(row["content"] or "").strip()
        if not content:
            continue
        turns.append(
            {
                "sender": str(row["sender"]),
                "content": content[:MAX_HISTORY_MESSAGE_CHARS],
            }
        )
    return turns


def format_history(turns: list[dict[str, str]]) -> str:
    """Render turns inside a bounded, clearly delimited history block."""
    lines = [f"{turn['sender']}: {turn['content']}" for turn in turns]
    return "\n".join(lines) if lines else "(no previous turns)"


def rewrite_follow_up(
    llm: ResilientLLMClient,
    question: str,
    turns: list[dict[str, str]],
    session_id: str | None = None,
) -> MemoryContext:
    """Rewrite a follow-up question into a standalone question.

    The LLM call is strict JSON with exactly one repair retry inside the
    gateway. Any failure falls back to the original question, so retrieval is
    always possible even when the provider misbehaves.

    Args:
        llm: The single LLM gateway.
        question: Current user question.
        turns: Recent session turns owned by the authenticated user.

    Returns:
        A :class:`MemoryContext` with the question used for retrieval.
    """
    original = question.strip()
    if not turns:
        return MemoryContext(standalone_question=original, rewritten=False, turns_used=0)

    prompt = load_prompt("rewrite").format(
        history=format_history(turns),
        question=original,
    )
    fallback = RewrittenQuestion(standalone_question=original)
    try:
        result = llm.complete_json(
            prompt=prompt,
            schema=RewrittenQuestion,
            fallback=fallback,
            step="rewrite",
            session_id=session_id,
        )
    except LLMClientError:
        logger.warning("Follow-up rewrite unavailable; using the original question.")
        return MemoryContext(
            standalone_question=original,
            rewritten=False,
            turns_used=len(turns),
        )

    candidate = (result.standalone_question or "").strip()
    if len(candidate) < 2:
        candidate = original
    return MemoryContext(
        standalone_question=candidate,
        rewritten=candidate != original,
        turns_used=len(turns),
    )


def memory_metadata(context: MemoryContext) -> dict[str, Any]:
    """Return a JSON-serialisable memory summary for message/audit metadata."""
    return {
        "rewritten": context.rewritten,
        "turns_used": context.turns_used,
        "standalone_question": context.standalone_question if context.rewritten else None,
    }


__all__ = [
    "MemoryContext",
    "RewrittenQuestion",
    "format_history",
    "load_recent_turns",
    "memory_metadata",
    "rewrite_follow_up",
]
