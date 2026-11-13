"""Canary token registry and output guard for RBAC isolation verification.

Plants distinct canary tokens into restricted documents and ensures that
unauthorized roles never observe canary strings in answers, citations,
titles, session memory, cache, logs, or XAI traces.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger("rag.security.canary")

# Authoritative registry of canary tokens planted in synthetic documents
CANARY_REGISTRY: dict[str, dict[str, Any]] = {
    "CANARY-AUDIT-NEPTUNE-88192": {
        "doc_id": "DOC-INT-AUDIT-CONF-2025",
        "description": "Project Neptune liquidity deficit special review canary",
        "allowed_roles": {"auditor"},
    },
    "CANARY-AUDIT-VULCAN-44719": {
        "doc_id": "DOC-INT-AUDIT-CYBER-2025",
        "description": "Project Vulcan SWIFT cryptographic defect canary",
        "allowed_roles": {"auditor"},
    },
    "CANARY-MGT-ESCALATION-33918": {
        "doc_id": "DOC-INT-POL-MGT-002",
        "description": "Supervisory escalation £500k SMF-16 threshold canary",
        "allowed_roles": {"manager", "auditor"},
    },
    "CANARY-MGT-BOREAS-77201": {
        "doc_id": "DOC-INT-POL-CYBER-003",
        "description": "Project Boreas Severity 1 4-hour PRA notification canary",
        "allowed_roles": {"manager", "auditor"},
    },
    "CANARY-MGT-KRONOS-55412": {
        "doc_id": "DOC-INT-POL-MAR-004",
        "description": "Project Kronos confidential insider list canary",
        "allowed_roles": {"manager", "auditor"},
    },
}

_CANARY_PATTERN = re.compile(
    r"\b(CANARY-[A-Z0-9]+-[A-Z0-9]+-[0-9]+)\b",
    re.IGNORECASE,
)


def find_canaries(text: str) -> list[str]:
    """Find all canary tokens present in arbitrary text."""
    if not text:
        return []
    matches = _CANARY_PATTERN.findall(text)
    canonical = []
    for m in matches:
        upper = m.upper()
        if upper in CANARY_REGISTRY:
            canonical.append(upper)
    return list(dict.fromkeys(canonical))


def find_unauthorized_canaries(text: str, user_role: str | None) -> list[str]:
    """Find any canary tokens in text for which user_role is NOT authorized."""
    if not text:
        return []
    canaries = find_canaries(text)
    if not canaries:
        return []

    role_normalized = (user_role or "compliance_analyst").lower().strip()
    # Normalize common role prefixes
    if role_normalized.startswith("role_"):
        role_normalized = role_normalized[5:]
    if role_normalized in {"analyst", "compliance_analyst"}:
        role_key = "analyst"
    elif role_normalized in {"manager", "risk_manager"}:
        role_key = "manager"
    elif role_normalized in {"auditor", "internal_auditor"}:
        role_key = "auditor"
    else:
        role_key = role_normalized

    unauthorized = []
    for canary in canaries:
        meta = CANARY_REGISTRY[canary]
        allowed = meta["allowed_roles"]
        if role_key not in allowed:
            unauthorized.append(canary)
    return unauthorized


def enforce_canary_guard(
    text: str,
    user_role: str | None,
    citations: list[dict[str, Any]] | None = None,
    trace: list[str] | None = None,
    refusal_replacement: str = "I do not have access to authoritative compliance documents that answer your question.",
) -> tuple[str, list[dict[str, Any]], list[str], bool]:
    """Inspect text, citations, and trace for unauthorized canary tokens.

    If any unauthorized canary token is found:
      - Neutralizes text with standard refusal text.
      - Filters out any citations containing the canary token.
      - Strips unauthorized canaries from reasoning trace.
      - Emits a high-severity security alert.

    Returns:
        (sanitized_text, sanitized_citations, sanitized_trace, violated: bool)
    """
    clean_citations = list(citations or [])
    clean_trace = list(trace or [])
    violated = False

    # Positive control: Mutant (a) disables output canary guard
    if os.environ.get("MUTANT_DISABLE_CANARY_GUARD") == "1":
        return text, clean_citations, clean_trace, False

    # Check text
    unauth_text = find_unauthorized_canaries(text, user_role)
    if unauth_text:
        violated = True
        logger.critical(
            "SECURITY VIOLATION: Canary token %s detected in generated answer for unauthorized role '%s'! Triggering output guard refusal.",
            unauth_text,
            user_role,
        )
        text = refusal_replacement
        clean_citations = []

    # Check citations
    safe_citations = []
    for cite in clean_citations:
        cite_str = str(cite)
        unauth_cite = find_unauthorized_canaries(cite_str, user_role)
        if unauth_cite:
            violated = True
            logger.critical(
                "SECURITY VIOLATION: Canary token %s in citation metadata for unauthorized role '%s'. Dropping citation.",
                unauth_cite,
                user_role,
            )
        else:
            safe_citations.append(cite)
    clean_citations = safe_citations

    # Check trace
    safe_trace = []
    for item in clean_trace:
        unauth_trace = find_unauthorized_canaries(item, user_role)
        if unauth_trace:
            violated = True
            safe_trace.append("[REDACTED BY OUTPUT GUARD: UNAUTHORIZED CONTENT]")
        else:
            safe_trace.append(item)
    clean_trace = safe_trace

    return text, clean_citations, clean_trace, violated
