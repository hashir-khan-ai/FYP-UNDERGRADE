"""Pure retrieval, answer-quality, and bootstrap-CI evaluation metrics.

All functions in this module are deterministic, require zero network calls,
and operate on plain Python data structures so they can be unit-tested on
small hand-computed fixtures.
"""

from __future__ import annotations

import math
import random
import re
from collections import Counter
from typing import Any

_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "this",
        "to",
        "under",
        "was",
        "were",
        "which",
        "with",
    }
)


def recall_at_k(retrieved_ids: list[str], gold_ids: list[str], k: int) -> float:
    """Compute Recall@k over unique gold chunk identifiers.

    Args:
        retrieved_ids: Ordered list of retrieved chunk IDs (rank 1 first).
        gold_ids: Ground-truth relevant chunk IDs for the question.
        k: Cutoff rank (must be >= 1).

    Returns:
        Fraction of unique ``gold_ids`` found within the top ``k`` retrieved
        items, in ``[0.0, 1.0]``. Returns ``0.0`` when ``gold_ids`` is empty.
    """
    if k <= 0:
        raise ValueError("k must be a positive integer.")
    gold_set = {cid for cid in gold_ids if cid}
    if not gold_set:
        return 0.0
    top_k_set = {cid for cid in retrieved_ids[:k] if cid}
    return len(gold_set & top_k_set) / float(len(gold_set))


def reciprocal_rank(retrieved_ids: list[str], gold_ids: list[str]) -> float:
    """Compute Reciprocal Rank (RR) of the first relevant chunk.

    Args:
        retrieved_ids: Ordered list of retrieved chunk IDs (rank 1 first).
        gold_ids: Ground-truth relevant chunk IDs for the question.

    Returns:
        ``1.0 / rank`` of the highest-ranked relevant chunk, or ``0.0`` if
        no relevant chunk is retrieved.
    """
    gold_set = {cid for cid in gold_ids if cid}
    if not gold_set:
        return 0.0
    for index, cid in enumerate(retrieved_ids, start=1):
        if cid in gold_set:
            return 1.0 / float(index)
    return 0.0


def ndcg_at_k(retrieved_ids: list[str], gold_ids: list[str], k: int) -> float:
    """Compute binary Normalized Discounted Cumulative Gain at cutoff ``k``.

    Duplicate chunk IDs in ``retrieved_ids`` are only credited at their first
    appearance so repeated items cannot inflate DCG above 1.0.

    Args:
        retrieved_ids: Ordered list of retrieved chunk IDs (rank 1 first).
        gold_ids: Ground-truth relevant chunk IDs for the question.
        k: Cutoff rank (must be >= 1).

    Returns:
        nDCG@k in ``[0.0, 1.0]``. Returns ``0.0`` when ``gold_ids`` is empty.
    """
    if k <= 0:
        raise ValueError("k must be a positive integer.")
    gold_set = {cid for cid in gold_ids if cid}
    if not gold_set:
        return 0.0

    dcg = 0.0
    seen: set[str] = set()
    for index, cid in enumerate(retrieved_ids[:k], start=1):
        if cid in seen:
            continue
        seen.add(cid)
        if cid in gold_set:
            dcg += 1.0 / math.log2(index + 1)

    ideal_hits = min(k, len(gold_set))
    idcg = sum(1.0 / math.log2(index + 1) for index in range(1, ideal_hits + 1))
    if idcg <= 0.0:
        return 0.0
    return dcg / idcg


def _content_tokens(text: str) -> list[str]:
    """Extract lowercase alphanumeric content tokens excluding stopwords."""
    raw = re.findall(r"[a-z0-9]+(?:\.[a-z0-9]+)*%?", (text or "").lower())
    return [tok for tok in raw if tok and tok not in _STOPWORDS]


def answer_correctness_score(prediction: str, gold_answer: str) -> float:
    """Compute deterministic content-token F1 + recall score against ``gold_answer``.

    In compliance QA, a verbose grounded answer that includes all key facts
    from a short ``gold_answer`` should score well even if it is longer than
    the reference summary. We therefore blend token-level F1 (weight 0.5) and
    gold-token coverage/recall (weight 0.5).

    Args:
        prediction: Model-generated answer text.
        gold_answer: Concise ground-truth reference answer.

    Returns:
        Score in ``[0.0, 1.0]``.
    """
    pred_tokens = _content_tokens(prediction)
    gold_tokens = _content_tokens(gold_answer)
    if not gold_tokens or not pred_tokens:
        return 0.0

    pred_counts = Counter(pred_tokens)
    gold_counts = Counter(gold_tokens)
    common = sum((pred_counts & gold_counts).values())
    if common == 0:
        return 0.0

    precision = common / float(len(pred_tokens))
    recall = common / float(len(gold_tokens))
    f1 = (2.0 * precision * recall) / (precision + recall)
    return round(0.5 * f1 + 0.5 * recall, 4)


def bootstrap_ci(
    values: list[float],
    n_boot: int = 1000,
    confidence: float = 0.95,
    seed: int = 42,
) -> dict[str, Any]:
    """Compute sample mean and non-parametric percentile bootstrap CI.

    Args:
        values: Per-question metric values.
        n_boot: Number of bootstrap resamples (default 1000).
        confidence: Confidence level in ``(0.0, 1.0)`` (default 0.95).
        seed: Fixed PRNG seed for deterministic reproducibility.

    Returns:
        Dictionary with ``n``, ``mean``, ``ci_low``, and ``ci_high``.
    """
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": 0.0, "ci_low": 0.0, "ci_high": 0.0}
    mean_val = sum(values) / float(n)
    if n == 1 or n_boot <= 0:
        rounded = round(mean_val, 4)
        return {"n": n, "mean": rounded, "ci_low": rounded, "ci_high": rounded}

    rng = random.Random(seed)
    boot_means: list[float] = []
    for _ in range(n_boot):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        boot_means.append(sum(sample) / float(n))
    boot_means.sort()

    alpha = 1.0 - confidence
    low_idx = max(0, min(n_boot - 1, int(math.floor((alpha / 2.0) * n_boot))))
    high_idx = max(0, min(n_boot - 1, int(math.ceil((1.0 - alpha / 2.0) * n_boot)) - 1))
    return {
        "n": n,
        "mean": round(mean_val, 4),
        "ci_low": round(boot_means[low_idx], 4),
        "ci_high": round(boot_means[high_idx], 4),
    }


def intervals_overlap(
    ci_a: tuple[float, float] | dict[str, Any],
    ci_b: tuple[float, float] | dict[str, Any],
) -> bool:
    """Return True if two confidence intervals overlap.

    When two configurations' 95% confidence intervals overlap, the ablation
    runner must not claim a statistically significant difference.
    """
    low_a = float(ci_a["ci_low"] if isinstance(ci_a, dict) else ci_a[0])
    high_a = float(ci_a["ci_high"] if isinstance(ci_a, dict) else ci_a[1])
    low_b = float(ci_b["ci_low"] if isinstance(ci_b, dict) else ci_b[0])
    high_b = float(ci_b["ci_high"] if isinstance(ci_b, dict) else ci_b[1])
    return max(low_a, low_b) <= min(high_a, high_b)

