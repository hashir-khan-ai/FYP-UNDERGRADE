"""Post-generation claim-level grounding verification (Phase 8C stretch feature).

Splits an assistant answer into atomic factual claims and scores each claim
strictly against role-permitted passages using lexical/numeric checks plus the
existing local CPU embedder and cross-encoder re-ranker when available.

Security invariant:
    Passages are filtered with :func:`src.core.security.enforce_role_visibility`
    before any scoring occurs so restricted content can never validate a claim.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.core.security import enforce_role_visibility, normalize_role

logger = logging.getLogger(__name__)

ClaimStatus = Literal["supported", "weak", "unsupported"]

_STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "been", "being", "by", "can",
        "could", "did", "do", "does", "for", "from", "had", "has", "have", "in",
        "into", "is", "it", "its", "may", "might", "must", "not", "of", "on",
        "or", "shall", "should", "such", "that", "the", "their", "them", "there",
        "these", "this", "those", "to", "under", "was", "were", "what", "when",
        "where", "which", "who", "will", "with", "would",
    }
)

_ABBREVIATIONS_RE = re.compile(
    r"\b(?:e\.g|i\.e|vs|etc|Art|Reg|Sec|No|Ch|Para|p|pp)\.",
    re.IGNORECASE,
)


class ClaimResult(BaseModel):
    """Support evaluation for a single atomic claim."""

    claim: str
    status: ClaimStatus
    score: float
    supporting_chunk_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class ClaimVerificationResult(BaseModel):
    """Aggregate claim-verification report and sanitized answer."""

    claims: list[ClaimResult] = Field(default_factory=list)
    supported_count: int = 0
    weak_count: int = 0
    unsupported_count: int = 0
    unsupported_claim_rate: float = 0.0
    revised_answer: str = ""
    removed_claims: list[str] = Field(default_factory=list)
    rbac_dropped_passages: int = 0


def _strip_inline_citations(text: str) -> str:
    """Remove bracketed numeric or chunk citation markers for proposition scoring."""
    cleaned = re.sub(r"\[(?:\d+(?:\s*,\s*\d+)*|DOC-[^\]]+|CH-[^\]]+|EVAL-[^\]]+|POL-[^\]]+)\]", "", text)
    cleaned = re.sub(r"\((?:DOC-|CH-|EVAL-|POL-)[^)]+\)", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _extract_content_tokens(text: str) -> set[str]:
    """Extract normalized alphanumeric domain tokens excluding common stopwords."""
    cleaned = _strip_inline_citations(text).lower()
    return {
        tok
        for tok in re.findall(r"[a-z0-9]+", cleaned)
        if len(tok) > 2 and tok not in _STOPWORDS
    }


def _extract_numeric_tokens(text: str) -> set[str]:
    """Extract normalized percentages, currency amounts, and policy thresholds."""
    cleaned = _strip_inline_citations(text)
    tokens: set[str] = set()
    for match in re.finditer(r"(?<![A-Za-z0-9-])([£$€]?\d+(?:,\d{3})*(?:\.\d+)?%?)", cleaned):
        raw = match.group(1)
        # Skip trailing regulation section indices like 4.1.2R captured partially
        end_idx = match.end()
        if end_idx < len(cleaned) and cleaned[end_idx] in (".", "R", "r"):
            continue
        norm = raw.lstrip("£$€").replace(",", "")
        if norm.endswith("%"):
            tokens.add(norm)
            tokens.add(norm[:-1])
        else:
            tokens.add(norm)
    return tokens


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute bounded cosine similarity between two equal-length float vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


def _protect_non_boundary_periods(text: str) -> str:
    """Temporarily replace periods inside decimals, rule numbers, and abbreviations."""
    placeholder = "\u2024"
    protected = re.sub(r"(?<=\d)\.(?=\d)", placeholder, text)
    protected = _ABBREVIATIONS_RE.sub(lambda m: m.group(0).replace(".", placeholder), protected)
    return protected


def split_atomic_claims(answer: str) -> list[str]:
    """Split an answer into distinct, deduplicated atomic factual claims.

    Ignores trailing metadata lines such as ``Supporting Chunks: ...`` or
    ``Verified calculation: ...`` and preserves decimal numbers and clause IDs.
    """
    if not answer or not answer.strip():
        return []

    kept_lines: list[str] = []
    for raw_line in answer.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.lower().startswith(("supporting chunks:", "verified calculation:")):
            continue
        # Strip leading markdown list bullet or numbered prefix
        stripped = re.sub(r"^(?:[-*•]+|\d+[.)])\s+", "", stripped)
        if stripped:
            kept_lines.append(stripped)

    if not kept_lines:
        return []

    claims: list[str] = []
    seen: set[str] = set()
    for line in kept_lines:
        protected = _protect_non_boundary_periods(line)
        segments = re.split(r"(?<=[.!?])\s+|\s*;\s+", protected)
        for seg in segments:
            candidate = seg.replace("\u2024", ".").strip()
            if not candidate:
                continue
            words = re.findall(r"[A-Za-z0-9£$€%]+", _strip_inline_citations(candidate))
            if len(words) < 3 and not re.search(r"\d+%", candidate):
                continue
            norm_key = candidate.lower()
            if norm_key not in seen:
                seen.add(norm_key)
                claims.append(candidate)
    return claims


def _best_embed_similarity(
    claim_text: str,
    passage_texts: list[str],
    embedder: Any,
) -> dict[int, float]:
    """Score cosine similarity per passage using the local embedder if real weights exist."""
    if embedder is None or not passage_texts:
        return {}
    if type(embedder).__name__.startswith(("Fake", "Mock")):
        return {}
    try:
        claim_vec = embedder.embed_query(claim_text)
        doc_vecs = embedder.embed_texts(passage_texts)
        return {
            idx: _cosine_similarity(claim_vec, doc_vec)
            for idx, doc_vec in enumerate(doc_vecs)
        }
    except Exception as exc:
        logger.debug("Claim check embedder unavailable (%s); using lexical/numeric scoring.", type(exc).__name__)
        return {}


def _best_rerank_scores(
    claim_text: str,
    permitted_passages: list[dict[str, Any]],
    reranker: Any,
) -> dict[str, float]:
    """Score claim-passage pairs using the local CPU cross-encoder when weights exist."""
    if reranker is None or not permitted_passages:
        return {}
    if type(reranker).__name__.startswith(("Mock", "Fake")):
        return {}
    try:
        ranked = reranker.rerank(claim_text, permitted_passages, top_n=len(permitted_passages))
        scores: dict[str, float] = {}
        for item in ranked:
            cid = str(item.get("chunk_id") or "")
            raw = float(item.get("score", 0.0))
            prob = 1.0 / (1.0 + math.exp(-max(-10.0, min(10.0, raw))))
            if cid:
                scores[cid] = prob
        return scores
    except Exception as exc:
        logger.debug("Claim check reranker unavailable (%s); using lexical/numeric scoring.", type(exc).__name__)
        return {}


def score_claim_support(
    claim: str,
    permitted_passages: list[dict[str, Any]],
    *,
    embedder: Any = None,
    reranker: Any = None,
    _embed_cache: dict[int, float] | None = None,
    _rerank_cache: dict[str, float] | None = None,
) -> ClaimResult:
    """Evaluate support for one atomic claim against already role-filtered passages."""
    if not permitted_passages:
        return ClaimResult(
            claim=claim,
            status="unsupported",
            score=0.0,
            supporting_chunk_ids=[],
            reason="No role-permitted passages available.",
        )

    clean_claim = _strip_inline_citations(claim)
    claim_tokens = _extract_content_tokens(clean_claim)
    claim_numbers = _extract_numeric_tokens(clean_claim)

    passage_texts = [
        f"{p.get('heading_path', '')} {p.get('text_content', '')}".strip()
        for p in permitted_passages
    ]
    embed_scores = (
        _embed_cache
        if _embed_cache is not None
        else _best_embed_similarity(clean_claim, passage_texts, embedder)
    )
    rerank_scores = (
        _rerank_cache
        if _rerank_cache is not None
        else _best_rerank_scores(clean_claim, permitted_passages, reranker)
    )

    best_score = -1.0
    best_cids: list[str] = []
    best_num_ok = True
    best_overlap = 0.0

    for idx, passage in enumerate(permitted_passages):
        cid = str(passage.get("chunk_id") or f"passage-{idx}")
        p_text = passage_texts[idx]
        p_tokens = _extract_content_tokens(p_text)
        p_numbers = _extract_numeric_tokens(p_text)

        overlap_ratio = (
            len(claim_tokens & p_tokens) / float(max(len(claim_tokens), 1))
            if claim_tokens
            else 0.0
        )

        num_match_ratio = 1.0
        has_all_nums = True
        if claim_numbers:
            matched_nums = claim_numbers & p_numbers
            num_match_ratio = len(matched_nums) / float(len(claim_numbers))
            has_all_nums = len(matched_nums) == len(claim_numbers)

        signals = [overlap_ratio]
        weights = [0.65 if (embed_scores or rerank_scores) else 1.0]
        if idx in embed_scores:
            signals.append(embed_scores[idx])
            weights.append(0.20)
        if cid in rerank_scores:
            signals.append(rerank_scores[cid])
            weights.append(0.25)

        total_w = sum(weights) or 1.0
        combined = sum(s * w for s, w in zip(signals, weights)) / total_w

        if claim_numbers:
            if not has_all_nums and num_match_ratio == 0.0:
                combined = min(combined, 0.15)
            elif not has_all_nums:
                combined = min(combined, 0.42)
            else:
                combined = min(1.0, combined * 0.8 + 0.2)

        if combined > best_score:
            best_score = combined
            best_cids = [cid]
            best_num_ok = has_all_nums
            best_overlap = overlap_ratio
        elif abs(combined - best_score) < 1e-6 and cid not in best_cids:
            best_cids.append(cid)

    final_score = round(max(0.0, min(1.0, best_score)), 4)

    if claim_numbers and not best_num_ok:
        if final_score >= 0.30 and len(claim_numbers) > 1:
            status: ClaimStatus = "weak"
            reason = "Partial numeric match; verify exact figures."
        else:
            status = "unsupported"
            reason = "Numeric figures in claim do not match role-permitted passages."
    elif best_overlap == 0.0 and final_score < 0.45:
        status = "unsupported"
        reason = "No lexical or entity support in permitted passages."
    elif final_score >= 0.50:
        status = "supported"
        reason = "Grounded in role-permitted passage evidence."
    elif final_score >= 0.25:
        status = "weak"
        reason = "Partial overlap with role-permitted passages."
    else:
        status = "unsupported"
        reason = "Insufficient grounding in role-permitted passages."

    return ClaimResult(
        claim=claim,
        status=status,
        score=final_score,
        supporting_chunk_ids=best_cids if status != "unsupported" else [],
        reason=reason,
    )


def verify_answer_claims(
    answer: str,
    passages: list[dict[str, Any]],
    role: str,
    *,
    rbac_enabled: bool = True,
    embedder: Any = None,
    reranker: Any = None,
    remove_unsupported: bool = True,
) -> ClaimVerificationResult:
    """Verify every atomic claim in ``answer`` against RBAC-permitted ``passages``.

    Unsupported claims are either stripped from ``revised_answer`` (default)
    or annotated inline when ``remove_unsupported=False``.
    """
    if rbac_enabled:
        permitted_passages, dropped_count = enforce_role_visibility(
            passages, normalize_role(role)
        )
    else:
        permitted_passages = list(passages)
        dropped_count = 0

    if not answer or not answer.strip():
        return ClaimVerificationResult(
            revised_answer=answer or "",
            rbac_dropped_passages=dropped_count,
        )

    lowered = answer.lower()
    if "can't find that in the documents available to your role" in lowered:
        return ClaimVerificationResult(
            revised_answer=answer,
            rbac_dropped_passages=dropped_count,
        )

    atomic_claims = split_atomic_claims(answer)
    if not atomic_claims:
        return ClaimVerificationResult(
            revised_answer=answer,
            rbac_dropped_passages=dropped_count,
        )

    results = [
        score_claim_support(
            claim,
            permitted_passages,
            embedder=embedder,
            reranker=reranker,
        )
        for claim in atomic_claims
    ]

    supported_count = sum(1 for item in results if item.status == "supported")
    weak_count = sum(1 for item in results if item.status == "weak")
    unsupported_claims = [item.claim for item in results if item.status == "unsupported"]
    unsupported_count = len(unsupported_claims)
    rate = round(unsupported_count / float(len(results)), 4)

    # Preserve non-claim metadata footer lines if present (Supporting Chunks / Verified calculation)
    footer_lines = [
        line.strip()
        for line in answer.splitlines()
        if line.strip().lower().startswith(("supporting chunks:", "verified calculation:"))
    ]

    if unsupported_count == 0:
        revised = answer
    elif remove_unsupported:
        kept_claims = [item.claim for item in results if item.status != "unsupported"]
        if kept_claims:
            revised = " ".join(kept_claims)
            if footer_lines:
                revised = f"{revised}\n" + "\n".join(footer_lines)
        else:
            revised = "I can't find verified support for those claims in the documents available to your role."
    else:
        annotated = [
            f"[UNSUPPORTED] {item.claim}" if item.status == "unsupported" else item.claim
            for item in results
        ]
        revised = " ".join(annotated)
        if footer_lines:
            revised = f"{revised}\n" + "\n".join(footer_lines)

    return ClaimVerificationResult(
        claims=results,
        supported_count=supported_count,
        weak_count=weak_count,
        unsupported_count=unsupported_count,
        unsupported_claim_rate=rate,
        revised_answer=revised,
        removed_claims=unsupported_claims if remove_unsupported else [],
        rbac_dropped_passages=dropped_count,
    )


__all__ = [
    "ClaimResult",
    "ClaimStatus",
    "ClaimVerificationResult",
    "score_claim_support",
    "split_atomic_claims",
    "verify_answer_claims",
]
