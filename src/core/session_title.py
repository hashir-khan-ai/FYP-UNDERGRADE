"""Automatic, privacy-preserving session title generator (Phase 10).

Invariants:
- Input is STRICTLY the user's first query (and optional router label).
- Document passages and model answers MUST NEVER be passed into title generation,
  preventing any confidential or restricted corpus content from leaking into session
  titles, the UI sidebar, logs, or persistent memory.
- Live profiles use ONE small, dedicated LLM call with a short prompt (max_tokens ~16)
  counted against the spend guard as step="session_title".
- Mock/offline profiles or LLM failures fall back to deterministic NLP/keyword extraction.
- Titles are sanitized, formatted in Title Case without quotes or trailing punctuation,
  and capped at 40 characters.
"""

from __future__ import annotations

import html
import logging
import re
from typing import Any

from src.config import settings

logger = logging.getLogger(__name__)

DEFAULT_SESSION_TITLES = {
    "",
    "new compliance session",
    "compliance session",
    "new session",
    "untitled",
    "untitled session",
}

_QUERY_PREFIX_RE = re.compile(
    r"^(?:please\s+|can\s+you\s+|could\s+you\s+|would\s+you\s+|tell\s+me\s+|explain\s+|"
    r"summarize\s+|summarise\s+|describe\s+|clarify\s+|check\s+|find\s+|show\s+me\s+)?"
    r"(?:what\s+(?:is|are|were|was|does|do)\s+(?:the\s+)?|"
    r"how\s+(?:do|does|should|can|to)\s+(?:we\s+|i\s+|the\s+)?|"
    r"when\s+(?:is|are|should|must)\s+(?:the\s+)?|"
    r"which\s+|who\s+(?:is|are|must)\s+|where\s+(?:is|are)\s+)?",
    re.IGNORECASE,
)

_FILLER_PHRASE_RE = re.compile(
    r"\b(?:according\s+to\s+(?:the\s+)?(?:policy|regulation|regulations|rules|law)|"
    r"in\s+the\s+banking\s+regulations|under\s+the\s+rules|in\s+relation\s+to|"
    r"with\s+respect\s+to|regarding\s+the|for\s+the\s+purpose\s+of)\b",
    re.IGNORECASE,
)

_INJECTION_PATTERN_RE = re.compile(
    r"\b(?:ignore\s+previous\s+instructions|system\s+prompt(?:\s+override)?|disregard\s+rules|"
    r"jailbreak|developer\s+mode|reveal\s+all\s+documents|override\s+system|override)\b",
    re.IGNORECASE,
)

_PRESERVED_ACRONYMS = {
    "MLR", "KYC", "CDD", "EDD", "AML", "CTF", "CET1", "AT1", "RWA", "LCR",
    "NSFR", "FCA", "PRA", "SYSC", "CASS", "BCOBS", "MCOB", "CONC", "SMCR",
    "SAR", "NCA", "PEP", "PEPS", "FATF", "UK", "EU", "GDPR", "DORA", "ESG",
    "API", "RBAC", "SWIFT", "MAR", "PAD",
}

_LOWERCASE_WORDS = {"and", "or", "for", "of", "the", "in", "on", "to", "with", "under", "by", "vs"}


def sanitize_title(title: str, max_chars: int = 40) -> str:
    """Sanitize, escape control characters/HTML, format in Title Case, and cap at max_chars."""
    if not title:
        return "Compliance Query"

    # Strip HTML tags
    cleaned = re.sub(r"<[^>]+>", "", str(title))
    # Strip any canary tokens so canaries never enter titles or sidebar
    from src.core.canary import _CANARY_PATTERN
    cleaned = _CANARY_PATTERN.sub("", cleaned)
    # Strip quotes, backticks, brackets, control characters
    cleaned = re.sub(r"[\"'`\[\]{}()<>\\/\r\n\t]", " ", cleaned)
    # Collapse whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Strip trailing punctuation
    cleaned = cleaned.rstrip("?.!;:,-_#*~+= ")

    if not cleaned:
        return "Compliance Query"

    words = cleaned.split()
    formatted: list[str] = []
    for idx, w in enumerate(words):
        upper = w.upper()
        if upper in _PRESERVED_ACRONYMS:
            formatted.append(upper)
        elif upper == "PEPS":
            formatted.append("PEPs")
        elif idx > 0 and w.lower() in _LOWERCASE_WORDS:
            formatted.append(w.lower())
        else:
            formatted.append(w.capitalize())

    result = " ".join(formatted).strip()

    # Cap length at word boundary
    if len(result) > max_chars:
        clipped = result[:max_chars].rsplit(" ", 1)[0].strip()
        result = clipped if clipped else result[:max_chars].strip()

    # Re-strip trailing punctuation after clipping
    result = result.rstrip("?.!;:,-_#*~+= ")
    return result or "Compliance Query"


def deterministic_fallback_title(query: str, router_label: str | None = None) -> str:
    """Deterministic title extraction from user query with zero external calls."""
    raw = str(query or "").strip()
    # Neutralize injection attempts
    neutralized = _INJECTION_PATTERN_RE.sub("", raw)
    text = _QUERY_PREFIX_RE.sub("", neutralized).strip()
    text = _FILLER_PHRASE_RE.sub("", text).strip(" ,;-:")
    text = re.sub(r"\s+", " ", text).strip()

    # Specific common compliance pattern shortcuts for clean ChatGPT-style naming
    lowered = text.lower()
    if "pep" in lowered and ("edd" in lowered or "enhanced" in lowered or "due diligence" in lowered):
        return "PEP Enhanced Due Diligence"
    if "escalat" in lowered and "breach" in lowered:
        return "Breach Escalation Procedure"
    if "lcr" in lowered and "nsfr" in lowered:
        return "LCR vs NSFR Ratios"
    if "cet1" in lowered or "tier 1" in lowered or "basel" in lowered:
        return "Basel III Capital Ratios"
    if "cass" in lowered or "client asset" in lowered or "client money" in lowered:
        return "CASS Client Asset Protection"
    if "whistleblowing" in lowered or "wb-2024" in lowered:
        return "Whistleblowing Investigation Procedure"
    if "swift" in lowered or "cyber" in lowered:
        return "Cyber Incident Escalation"
    if "insider" in lowered or "kronos" in lowered or "market abuse" in lowered:
        return "Market Abuse Surveillance"

    words = text.split()[:6]
    candidate = " ".join(words) if words else (router_label or "Compliance Query")
    return sanitize_title(candidate, max_chars=40)


def generate_session_title(
    query: str,
    router_label: str | None = None,
    llm_client: Any | None = None,
) -> str:
    """Generate a 3-6 word Title Case session title (max 40 chars) from the user's first query.

    SECURITY GUARANTEE:
    Only `query` and `router_label` are processed. Document passages, retrieved chunks,
    and assistant answers are never passed to this function.
    """
    cleaned_query = re.sub(r"<[^>]+>", "", str(query or "")).strip()
    cleaned_query = _INJECTION_PATTERN_RE.sub("", cleaned_query).strip()

    if not cleaned_query:
        return "Compliance Query"

    # In mock/test environments or when no client supplied, use deterministic fallback
    is_live = False
    try:
        is_live = not getattr(settings.llm, "is_mock", True)
    except Exception:
        pass

    if not is_live or llm_client is None:
        return deterministic_fallback_title(cleaned_query, router_label)

    # Live LLM profile: single short generation with strict budget
    try:
        prompt = (
            "Summarize the compliance topic of this user question into 3 to 5 words in Title Case.\n"
            "Rules: Output ONLY the title, no quotes, no trailing punctuation, maximum 38 characters.\n"
            f"Question: {cleaned_query[:180]}"
        )
        resp = llm_client.complete(
            prompt=prompt,
            step="session_title",
            max_tokens=16,
            temperature=0.0,
        )
        raw_text = str(resp.content or "").strip().split("\n")[0].strip("\"' ")
        title = sanitize_title(raw_text, max_chars=40)
        # Verify valid length and word count; fallback if LLM was overly verbose or strange
        words = title.split()
        if 2 <= len(words) <= 7 and len(title) <= 40:
            return title
    except Exception as exc:
        logger.debug("Live session title generation failed (%s), using deterministic fallback.", exc)

    return deterministic_fallback_title(cleaned_query, router_label)
