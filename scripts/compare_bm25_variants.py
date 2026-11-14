#!/usr/bin/env python3
"""Retrieval-only comparison: Plain BM25Plus vs Fixed Strict Term-Presence Match (Phase 12).

Evaluates lexical retrieval performance without LLM generation over gold benchmark items.
Computes Recall@5, Reciprocal Rank (MRR), and nDCG@5 with paired bootstrap 95% CIs.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import settings
from src.evaluation.gold_set import GoldQuestionItem, load_gold_set
from src.evaluation.metrics import (
    bootstrap_ci,
    ndcg_at_k,
    paired_bootstrap_ci,
    recall_at_k,
    reciprocal_rank,
)
from src.ingestion.indexer import BM25Indexer


def run_bm25_comparison(
    gold_path: str = "data/eval/gold_set.jsonl",
    top_k: int = 5,
    out_dir: str = "reports",
) -> dict[str, Any]:
    indexer = BM25Indexer(settings.BM25_INDEX_PATH)
    if not indexer.load():
        raise RuntimeError(f"Failed to load BM25 index from {settings.BM25_INDEX_PATH}. Index corpus first.")

    questions = load_gold_set(gold_path, include_rejected=False)
    human_reviewed = [
        q for q in questions
        if getattr(q, "status", None) == "reviewed" and getattr(q, "reviewed_by", None) == "human"
    ]

    is_human_reviewed_subset = bool(human_reviewed)
    eval_set = human_reviewed if human_reviewed else [q for q in questions if q.expected_behaviour == "answer" and q.gold_chunk_ids]

    print("=" * 86)
    print("BM25 RETRIEVAL-ONLY COMPARISON: PLAIN BM25PLUS vs. STRICT MATCH (Phase 12)")
    print("=" * 86)
    print(f"Human-reviewed count : {len(human_reviewed)}")
    print(f"Evaluation questions : {len(eval_set)} ({'Human-reviewed only' if is_human_reviewed_subset else 'All answerable benchmark items'})")
    print(f"Corpus chunks in index: {len(indexer.chunks)}")
    print("-" * 86)

    plain_recalls: list[float] = []
    strict_recalls: list[float] = []
    plain_mrrs: list[float] = []
    strict_mrrs: list[float] = []
    plain_ndcgs: list[float] = []
    strict_ndcgs: list[float] = []

    per_query_records: list[dict[str, Any]] = []

    for q in eval_set:
        gold_cids = list(q.gold_chunk_ids)
        role = q.role_asking

        # 1. Plain BM25Plus
        res_plain = indexer.search(q.question, top_k=top_k, role=role, strict_match=False)
        plain_cids = [h.get("chunk_id", "") if isinstance(h, dict) else getattr(h, "chunk_id", "") for h in res_plain.hits]
        r_plain = recall_at_k(plain_cids, gold_cids, k=top_k)
        mrr_plain = reciprocal_rank(plain_cids, gold_cids)
        ndcg_plain = ndcg_at_k(plain_cids, gold_cids, k=top_k)

        # 2. Strict Match BM25Plus
        res_strict = indexer.search(q.question, top_k=top_k, role=role, strict_match=True)
        strict_cids = [h.get("chunk_id", "") if isinstance(h, dict) else getattr(h, "chunk_id", "") for h in res_strict.hits]
        r_strict = recall_at_k(strict_cids, gold_cids, k=top_k)
        mrr_strict = reciprocal_rank(strict_cids, gold_cids)
        ndcg_strict = ndcg_at_k(strict_cids, gold_cids, k=top_k)

        plain_recalls.append(r_plain)
        strict_recalls.append(r_strict)
        plain_mrrs.append(mrr_plain)
        strict_mrrs.append(mrr_strict)
        plain_ndcgs.append(ndcg_plain)
        strict_ndcgs.append(ndcg_strict)

        per_query_records.append({
            "id": q.id,
            "role": role,
            "plain_hits": len(plain_cids),
            "strict_hits": len(strict_cids),
            "plain_recall": r_plain,
            "strict_recall": r_strict,
            "plain_mrr": mrr_plain,
            "strict_mrr": mrr_strict,
            "plain_ndcg": ndcg_plain,
            "strict_ndcg": ndcg_strict,
        })

    n = len(eval_set)
    mean_p_rec = sum(plain_recalls) / n if n else 0.0
    mean_s_rec = sum(strict_recalls) / n if n else 0.0
    mean_p_mrr = sum(plain_mrrs) / n if n else 0.0
    mean_s_mrr = sum(strict_mrrs) / n if n else 0.0
    mean_p_ndcg = sum(plain_ndcgs) / n if n else 0.0
    mean_s_ndcg = sum(strict_ndcgs) / n if n else 0.0

    ci_p_rec = bootstrap_ci(plain_recalls)
    ci_s_rec = bootstrap_ci(strict_recalls)
    paired_ci_rec = paired_bootstrap_ci(strict_recalls, plain_recalls)

    ci_p_mrr = bootstrap_ci(plain_mrrs)
    ci_s_mrr = bootstrap_ci(strict_mrrs)
    paired_ci_mrr = paired_bootstrap_ci(strict_mrrs, plain_mrrs)

    ci_p_ndcg = bootstrap_ci(plain_ndcgs)
    ci_s_ndcg = bootstrap_ci(strict_ndcgs)
    paired_ci_ndcg = paired_bootstrap_ci(strict_ndcgs, plain_ndcgs)

    print(f"{'Variant':<25} {'Recall@5 (95% CI)':<24} {'MRR (95% CI)':<22} {'nDCG@5 (95% CI)':<22}")
    print("-" * 86)
    print(
        f"{'Plain BM25Plus (A0)':<25} "
        f"{mean_p_rec:.4f} [{ci_p_rec['ci_low']:.3f}, {ci_p_rec['ci_high']:.3f}]     "
        f"{mean_p_mrr:.4f} [{ci_p_mrr['ci_low']:.3f}, {ci_p_mrr['ci_high']:.3f}]   "
        f"{mean_p_ndcg:.4f} [{ci_p_ndcg['ci_low']:.3f}, {ci_p_ndcg['ci_high']:.3f}]"
    )
    print(
        f"{'Strict BM25 (Fixed)':<25} "
        f"{mean_s_rec:.4f} [{ci_s_rec['ci_low']:.3f}, {ci_s_rec['ci_high']:.3f}]     "
        f"{mean_s_mrr:.4f} [{ci_s_mrr['ci_low']:.3f}, {ci_s_mrr['ci_high']:.3f}]   "
        f"{mean_s_ndcg:.4f} [{ci_s_ndcg['ci_low']:.3f}, {ci_s_ndcg['ci_high']:.3f}]"
    )
    print("-" * 86)
    delta_rec = mean_s_rec - mean_p_rec
    delta_mrr = mean_s_mrr - mean_p_mrr
    delta_ndcg = mean_s_ndcg - mean_p_ndcg
    print(
        f"{'Paired Difference (Δ)':<25} "
        f"{delta_rec:+.4f} [{paired_ci_rec['ci_low']:+.3f}, {paired_ci_rec['ci_high']:+.3f}]   "
        f"{delta_mrr:+.4f} [{paired_ci_mrr['ci_low']:+.3f}, {paired_ci_mrr['ci_high']:+.3f}]  "
        f"{delta_ndcg:+.4f} [{paired_ci_ndcg['ci_low']:+.3f}, {paired_ci_ndcg['ci_high']:+.3f}]"
    )
    print(
        f"{'Statistically Significant?':<25} "
        f"{'YES' if paired_ci_rec.get('is_significant') else 'NO (CI includes 0)':<24} "
        f"{'YES' if paired_ci_mrr.get('is_significant') else 'NO (CI includes 0)':<22} "
        f"{'YES' if paired_ci_ndcg.get('is_significant') else 'NO (CI includes 0)':<22}"
    )
    print("=" * 86)

    out_payload = {
        "evaluation_count": n,
        "is_human_reviewed_subset": is_human_reviewed_subset,
        "human_reviewed_count": len(human_reviewed),
        "plain_bm25": {
            "recall@5": round(mean_p_rec, 4),
            "recall_ci_95": {"low": round(ci_p_rec["ci_low"], 4), "high": round(ci_p_rec["ci_high"], 4)},
            "mrr": round(mean_p_mrr, 4),
            "mrr_ci_95": {"low": round(ci_p_mrr["ci_low"], 4), "high": round(ci_p_mrr["ci_high"], 4)},
            "ndcg@5": round(mean_p_ndcg, 4),
            "ndcg_ci_95": {"low": round(ci_p_ndcg["ci_low"], 4), "high": round(ci_p_ndcg["ci_high"], 4)},
        },
        "strict_bm25": {
            "recall@5": round(mean_s_rec, 4),
            "recall_ci_95": {"low": round(ci_s_rec["ci_low"], 4), "high": round(ci_s_rec["ci_high"], 4)},
            "mrr": round(mean_s_mrr, 4),
            "mrr_ci_95": {"low": round(ci_s_mrr["ci_low"], 4), "high": round(ci_s_mrr["ci_high"], 4)},
            "ndcg@5": round(mean_s_ndcg, 4),
            "ndcg_ci_95": {"low": round(ci_s_ndcg["ci_low"], 4), "high": round(ci_s_ndcg["ci_high"], 4)},
        },
        "paired_difference": {
            "delta_recall@5": round(delta_rec, 4),
            "recall_paired_ci_95": {"low": round(paired_ci_rec["ci_low"], 4), "high": round(paired_ci_rec["ci_high"], 4)},
            "recall_significant": paired_ci_rec.get("is_significant", False),
            "delta_mrr": round(delta_mrr, 4),
            "mrr_paired_ci_95": {"low": round(paired_ci_mrr["ci_low"], 4), "high": round(paired_ci_mrr["ci_high"], 4)},
            "mrr_significant": paired_ci_mrr.get("is_significant", False),
            "delta_ndcg@5": round(delta_ndcg, 4),
            "ndcg_paired_ci_95": {"low": round(paired_ci_ndcg["ci_low"], 4), "high": round(paired_ci_ndcg["ci_high"], 4)},
            "ndcg_significant": paired_ci_ndcg.get("is_significant", False),
        },
        "per_query": per_query_records,
    }

    out_path = Path(out_dir) / "bm25_comparison.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_payload, indent=2), encoding="utf-8")
    print(f"Report saved to: {out_path}")

    return out_payload


if __name__ == "__main__":
    run_bm25_comparison()
