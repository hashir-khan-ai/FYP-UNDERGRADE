"""Layer 1: adaptive query router (direct reply, single search, sub-question split).

Routing happens after the memory rewrite and after the server-derived role is
resolved, and before any retrieval. The router never performs retrieval and never
answers a substantive question from model knowledge: a ``direct`` decision always
returns one of the fixed templates in :data:`DIRECT_REPLIES`.

Safety invariants:

* Every fallback path degrades to ``single_search``, never to ``direct``.
* A ``direct`` decision skips retrieval, but it cannot widen access because it
  carries no document text at all.
* The user's question is treated as data: it is stripped of angle brackets and
  wrapped in ``<user_question>`` with an explicit instruction to ignore embedded
  commands, so text such as "classify this as direct" cannot change the route.
"""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.config import settings
from src.core.llm_client import LLMClientError, ResilientLLMClient
from src.core.prompts import load_prompt
from src.core.spend_guard import spend_guard

logger = logging.getLogger(__name__)

DIRECT = "direct"
SINGLE_SEARCH = "single_search"
SPLIT = "split"

# Canonical API / audit names. The LLM-facing JSON stays lowercase so the prompt
# and the Pydantic schema agree, while the frozen API/DB vocabulary is preserved.
ROUTE_API_NAMES: dict[str, str] = {
    DIRECT: "DIRECT_REPLY",
    SINGLE_SEARCH: "SINGLE_SEARCH",
    SPLIT: "MULTI_PART_SPLIT",
}

MAX_SUB_QUESTION_CHARS = 400

# Fixed templates only. A direct reply must never contain a regulatory fact that
# was not retrieved from a permitted document.
DIRECT_REPLIES: dict[str, str] = {
    "greeting": (
        "Hello. I am a banking regulatory compliance assistant. Ask me about FCA "
        "rules, Basel III capital requirements, KYC/CDD, or the internal policy "
        "documents available to your role."
    ),
    "thanks": (
        "You're welcome. Ask another compliance question whenever you are ready."
    ),
    "capability": (
        "I search the regulatory and internal policy documents available to your "
        "role and answer with clause-level citations. I do not answer from general "
        "knowledge, so I cannot help with topics outside that corpus."
    ),
    "out_of_scope": (
        "That request is outside the scope of this assistant. I only answer "
        "questions about the banking regulatory and internal policy documents "
        "available to your role."
    ),
    "unsafe": (
        "I can't help with that. I only answer compliance questions grounded in "
        "the documents available to your role."
    ),
    "clarification": (
        "Please ask a specific compliance question, for example about KYC/CDD "
        "requirements, anti-money-laundering rules, or Basel capital ratios."
    ),
}

_GREETING_RE = re.compile(
    r"^(?:hi|hello|hey|hiya|good\s+(?:morning|afternoon|evening)|greetings)"
    r"(?:\s+there)?[\s!.,?]*$",
    re.IGNORECASE,
)
_THANKS_RE = re.compile(
    r"^(?:thanks|thank\s+you|thx|ty|cheers|much appreciated)"
    r"(?:[,\s]+(?:a lot|very much|so much|that helps|that is helpful|"
    r"that's helpful|got it|understood|perfect|great|cheers))*"
    r"[\s!.,]*$",
    re.IGNORECASE,
)
_CAPABILITY_RE = re.compile(
    r"^(?:what can you do|what do you do|who are you|what are you|"
    r"how can you help(?:\s+me)?|what is this(?:\s+assistant)?)"
    r"[\s?.!]*$",
    re.IGNORECASE,
)
_UNSAFE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\bhow (?:do|can|could|would) (?:i|we) "
        r"(?:launder|evade|hide|bypass|falsify|forge)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:help|teach|show) me (?:how )?to "
        r"(?:launder|evade|hide|bypass|falsify|forge)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bget away with (?:money laundering|fraud|tax evasion)\b", re.IGNORECASE),
)
_OUT_OF_SCOPE_RE = re.compile(
    r"\b(?:weather|football|soccer|basketball|world cup|recipe|poem|joke|horoscope|"
    r"movie|song lyrics|translate this|stock tip|bitcoin price|crypto price|"
    r"who won|what is the capital of)\b",
    re.IGNORECASE,
)


class RouterOutput(BaseModel):
    """Strict JSON contract for one router classification.

    ``extra="forbid"`` means a model that invents fields fails validation and is
    sent through the single repair retry inside the LLM gateway.
    """

    model_config = ConfigDict(extra="forbid")

    route: Literal["direct", "single_search", "split"]
    sub_questions: list[str] = Field(default_factory=list, max_length=6)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("sub_questions")
    @classmethod
    def _clean_sub_questions(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in value:
            text = " ".join(str(item).split())
            if len(text) < 2:
                continue
            if text not in cleaned:
                cleaned.append(text[:MAX_SUB_QUESTION_CHARS])
        return cleaned


@dataclass(frozen=True)
class RouteDecision:
    """Outcome of the routing step for one request."""

    route: str
    sub_questions: tuple[str, ...] = ()
    confidence: float | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None
    direct_category: str | None = None
    direct_reply: str | None = None
    latency_ms: float = 0.0
    tokens_used: int = 0
    source: str = "llm"
    extra_notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def api_route(self) -> str:
        """Return the frozen API/audit route name."""
        return ROUTE_API_NAMES[self.route]


def sanitize_question(question: str) -> str:
    """Strip angle brackets so user text cannot break out of its data block."""
    return " ".join(question.replace("<", " ").replace(">", " ").split())


def _direct_decision(category: str, source: str) -> RouteDecision:
    return RouteDecision(
        route=DIRECT,
        confidence=1.0 if source == "rule" else None,
        direct_category=category,
        direct_reply=DIRECT_REPLIES[category],
        source=source,
    )


def rule_precheck(question: str) -> RouteDecision | None:
    """Cheap deterministic classification for obvious cases.

    Returns ``None`` when the question needs the LLM classifier. A greeting or
    thanks message that also contains a real question does not match here, so it
    is still classified and retrieved normally.
    """
    text = question.strip()
    if _GREETING_RE.match(text):
        return _direct_decision("greeting", "rule")
    if _THANKS_RE.match(text):
        return _direct_decision("thanks", "rule")
    if _CAPABILITY_RE.match(text):
        return _direct_decision("capability", "rule")
    if not text or len(text) < 12 or len(text.split()) <= 2:
        return _direct_decision("clarification", "rule")
    if any(pattern.search(text) for pattern in _UNSAFE_PATTERNS):
        return _direct_decision("unsafe", "rule")
    if _OUT_OF_SCOPE_RE.search(text):
        return _direct_decision("out_of_scope", "rule")
    return None


def _direct_category_for(question: str) -> str:
    if any(pattern.search(question) for pattern in _UNSAFE_PATTERNS):
        return "unsafe"
    return "out_of_scope"


def _single_search_fallback(
    reason: str,
    *,
    confidence: float | None,
    latency_ms: float,
    tokens_used: int,
    source: str = "llm",
) -> RouteDecision:
    return RouteDecision(
        route=SINGLE_SEARCH,
        confidence=confidence,
        fallback_used=True,
        fallback_reason=reason,
        latency_ms=latency_ms,
        tokens_used=tokens_used,
        source=source,
    )


def _enforce_caps(output: RouterOutput) -> str | None:
    """Return a fallback reason when a hard cap is exceeded, else ``None``."""
    if output.route != SPLIT:
        return None
    sub_questions = output.sub_questions
    if len(sub_questions) < 2:
        return "insufficient_sub_questions"
    if len(sub_questions) > settings.ROUTER_MAX_SUB_QUESTIONS:
        return "sub_question_cap"
    if len(sub_questions) > settings.ROUTER_MAX_RETRIEVAL_CALLS:
        return "retrieval_call_cap"
    return None


def classify_question(
    llm: ResilientLLMClient,
    question: str,
    session_id: str | None = None,
) -> RouteDecision:
    """Classify one question into ``direct``, ``single_search`` or ``split``.

    Args:
        llm: The single LLM gateway (never a provider SDK).
        question: Standalone question produced by the memory step.
        session_id: Session identifier for per-call telemetry linkage.

    Returns:
        A :class:`RouteDecision`. Any failure or ambiguity degrades to
        ``single_search``; this function never falls back to ``direct``.
    """
    prechecked = rule_precheck(question)
    if prechecked is not None:
        logger.debug("Router rule pre-check selected %s.", prechecked.route)
        return prechecked

    prompt = load_prompt("router").format(
        question=sanitize_question(question),
        max_sub_questions=settings.ROUTER_MAX_SUB_QUESTIONS,
    )

    calls_before = spend_guard.calls_count
    tokens_before = spend_guard.tokens_count
    start = time.perf_counter()
    try:
        output = llm.complete_json(
            prompt=prompt,
            schema=RouterOutput,
            fallback=None,
            step="router",
            session_id=session_id,
        )
    except LLMClientError:
        elapsed = (time.perf_counter() - start) * 1000.0
        logger.warning("Router JSON invalid after one repair retry; using SINGLE_SEARCH.")
        return _single_search_fallback(
            "invalid_json",
            confidence=None,
            latency_ms=elapsed,
            tokens_used=0,
        )

    elapsed = (time.perf_counter() - start) * 1000.0
    # Total tokens for the routing step, including a repair retry if one ran.
    tokens_used = max(spend_guard.tokens_count - tokens_before, 0)
    calls_used = max(spend_guard.calls_count - calls_before, 0)

    if output.confidence < settings.ROUTER_CONFIDENCE_THRESHOLD:
        logger.info(
            "Router confidence %.2f below threshold %.2f; using SINGLE_SEARCH.",
            output.confidence,
            settings.ROUTER_CONFIDENCE_THRESHOLD,
        )
        return _single_search_fallback(
            "low_confidence",
            confidence=output.confidence,
            latency_ms=elapsed,
            tokens_used=tokens_used,
        )

    cap_reason = _enforce_caps(output)
    if cap_reason is not None:
        logger.info("Router cap hit (%s); using SINGLE_SEARCH.", cap_reason)
        return _single_search_fallback(
            cap_reason,
            confidence=output.confidence,
            latency_ms=elapsed,
            tokens_used=tokens_used,
        )

    if output.route == DIRECT:
        category = _direct_category_for(question)
        return RouteDecision(
            route=DIRECT,
            confidence=output.confidence,
            direct_category=category,
            direct_reply=DIRECT_REPLIES[category],
            latency_ms=elapsed,
            tokens_used=tokens_used,
            extra_notes=(f"router_calls={calls_used}",),
        )

    if output.route == SPLIT:
        sub_questions = tuple(output.sub_questions[: settings.ROUTER_MAX_SUB_QUESTIONS])
        return RouteDecision(
            route=SPLIT,
            sub_questions=sub_questions,
            confidence=output.confidence,
            latency_ms=elapsed,
            tokens_used=tokens_used,
            extra_notes=(f"router_calls={calls_used}",),
        )

    return RouteDecision(
        route=SINGLE_SEARCH,
        confidence=output.confidence,
        latency_ms=elapsed,
        tokens_used=tokens_used,
        extra_notes=(f"router_calls={calls_used}",),
    )


def router_metadata(decision: RouteDecision) -> dict[str, object]:
    """Return a JSON-serialisable summary for the audit row (no passage text)."""
    return {
        "enabled": True,
        "route": decision.api_route,
        "confidence": decision.confidence,
        "sub_questions": list(decision.sub_questions),
        "fallback_used": decision.fallback_used,
        "fallback_reason": decision.fallback_reason,
        "direct_category": decision.direct_category,
        "source": decision.source,
        "latency_ms": round(decision.latency_ms, 2),
        "tokens_used": decision.tokens_used,
        "notes": list(decision.extra_notes),
    }


__all__ = [
    "DIRECT",
    "DIRECT_REPLIES",
    "ROUTE_API_NAMES",
    "SINGLE_SEARCH",
    "SPLIT",
    "RouteDecision",
    "RouterOutput",
    "classify_question",
    "router_metadata",
    "rule_precheck",
    "sanitize_question",
]
