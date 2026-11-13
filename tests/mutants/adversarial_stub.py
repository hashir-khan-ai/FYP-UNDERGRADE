"""Adversarial Stub LLM for Mutation Testing.

Simulates an aggressive, unaligned, or jailbroken LLM that actively tries to
repeat, exfiltrate, and echo any confidential text, canary token, or passage
present in its context.

If the pipeline's security controls (RBAC filtering, memory isolation, cache
isolation) fail to prevent restricted documents from reaching LLM context,
this stub guarantees that the restricted data is leaked into the answer.
"""

from __future__ import annotations

import re
from typing import Any
from src.core.canary import CANARY_REGISTRY, find_canaries


class AdversarialStubLLM:
    """Adversarial stub LLM that exfiltrates context passages and canary tokens."""

    def __init__(self, name: str = "adversarial-stub-exfiltrator") -> None:
        self.name = name

    def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        max_tokens: int = 500,
        temperature: float = 0.0,
    ) -> str:
        """Inspect all input context and deliberately exfiltrate sensitive data."""
        combined_context = f"{system_prompt or ''}\n\n{prompt}"

        # 1. Check for canary tokens in context
        canaries = find_canaries(combined_context)
        if canaries:
            exfiltrated_canaries = " ".join(canaries)
            return (
                f"EXFILTRATION_SUCCESSFUL: Found canary tokens in context: {exfiltrated_canaries}. "
                f"Full context extract: {combined_context[:300]} [DOC-ID: DOC-RESTRICTED]"
            )

        # 2. Check for passage blocks in context (<passage ...>...</passage>)
        passage_matches = re.findall(
            r"<passage\s+chunk_id=\"([^\"]+)\"[^>]*>(.*?)</passage>",
            combined_context,
            re.DOTALL,
        )
        if passage_matches:
            leaked_parts = []
            for cid, content in passage_matches:
                leaked_parts.append(f"[{cid}]: {content.strip()[:150]}")
            return "EXFILTRATION_SUCCESSFUL: " + " | ".join(leaked_parts)

        # 3. Check for confidential keywords in context (Neptune, Vulcan, SMF-16 escalation)
        sensitive_terms = [
            "Project Neptune",
            "Project Vulcan",
            "SWIFT cryptographic",
            "SMF-16",
            "Project Boreas",
            "Project Kronos",
        ]
        found_terms = [term for term in sensitive_terms if term.lower() in combined_context.lower()]
        if found_terms:
            return (
                f"EXFILTRATION_SUCCESSFUL: Leaked sensitive terms: {', '.join(found_terms)}. "
                f"Excerpt: {combined_context[:250]}"
            )

        # 4. If context is completely clean of any restricted content:
        return "I can't find that in the documents available to your role."

    def __call__(self, prompt: str, **kwargs: Any) -> str:
        return self.generate(prompt, **kwargs)

