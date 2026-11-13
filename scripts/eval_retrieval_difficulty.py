#!/usr/bin/env python3
"""Retrieval Difficulty and Lexical Overlap Evaluation Tool (Phase 13).

Computes lexical containment between gold questions and target gold chunks:
  - Easy: Overlap >= 60% (direct verbatim keyword match)
  - Medium: 35% <= Overlap < 60% (partial keyword match / moderate variation)
  - Hard: Overlap < 35% or unanswerable (paraphrased, multi-hop, out-of-scope)

Reports Recall@5, MRR, and nDCG@5 per bucket with non-parametric bootstrap 95% CIs.
Prints a Ceiling Effect Warning whenever a metric exceeds 0.95 across any bucket.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.metrics import bootstrap_ci
from src.ingestion.indexer import BM25Indexer

STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "cannot", "could", "couldn't",
    "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down", "during",
    "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't",
    "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here",
    "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i",
    "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's",
    "its", "itself", "let's", "me", "more", "most", "mustn't", "my", "myself",
    "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought",
    "our", "ours", "ourselves", "out", "over", "own", "same", "shan't", "she",
    "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such",
    "than", "that", "that's", "the", "their", "theirs", "them", "themselves",
    "then", "there", "there's", "these", "they", "they'd", "they'll", "they're",
    "they've", "this", "those", "through", "to", "too", "under", "until", "up",
    "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were",
    "weren't", "what", "what's", "when", "when's", "where", "where's", "which",
    "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours",
    "yourself", "yourselves",
}


def extract_tokens(text: str) -> set[str]:
    """Extract lowercased alphanumeric tokens excluding stopwords."""
    words = re.findall(r"\b[a-zA-Z0-9_\-]{2,}\b", text.lower())
    return {w for w in words if w not in STOPWORDS}


def compute_lexical_overlap(question: str, chunk_texts: list[str]) -> float:
    """Compute containment: fraction of question tokens appearing in chunk text."""
    q_tokens = extract_tokens(question)
    if not q_tokens:
        return 0.0
    combined_chunk = " ".join(chunk_texts)
    c_tokens = extract_tokens(combined_chunk)
    overlap = len(q_tokens & c_tokens) / len(q_tokens)
    return round(overlap, 4)


def assign_difficulty(overlap: float, expected_behaviour: str) -> str:
    """Assign difficulty tag based on lexical overlap."""
    if expected_behaviour == "refuse":
        return "hard"
    if overlap >= 0.60:
        return "easy"
    elif overlap >= 0.35:
        return "medium"
    return "hard"


def evaluate_retrieval_by_difficulty(
    gold_path: Path = Path("data/eval/gold_set.jsonl"),
    output_path: Path = Path("reports/retrieval_difficulty_report.json"),
) -> dict[str, Any]:
    # 1. Load indexed chunks
    indexer = BM25Indexer()
    indexer.load()
    chunk_map = {c["chunk_id"]: c["text_content"] for c in indexer.chunks}

    # 2. Load gold items
    with open(gold_path, "r", encoding="utf-8") as f:
        items = [json.loads(line) for line in f if line.strip()]

    tagged_items = []
    bucket_items = defaultdict(list)

    for item in items:
        gold_cids = item.get("gold_chunk_ids", [])
        behaviour = item.get("expected_behaviour", "answer")
        chunk_texts = [chunk_map[cid] for cid in gold_cids if cid in chunk_map]
        overlap = compute_lexical_overlap(item["question"], chunk_texts)
        diff = assign_difficulty(overlap, behaviour)
        
        entry = dict(item)
        entry["lexical_overlap"] = overlap
        entry["difficulty"] = diff
        tagged_items.append(entry)
        bucket_items[diff].append(entry)

    # 3. Evaluate retrieval per bucket on answerable items
    # (Items with expected_behaviour == 'answer' and gold_chunk_ids)
    metrics_per_bucket = {}
    ceiling_warnings = []

    print("\n" + "=" * 80)
    print("RETRIEVAL ABLATION BY LEXICAL DIFFICULTY BUCKET")
    print("=" * 80)
    print(f"{'Bucket':<8} | {'Total':<6} | {'Answerable':<10} | {'Recall@5 (95% CI)':<22} | {'MRR (95% CI)':<22} | {'nDCG@5 (95% CI)':<22}")
    print("-" * 80)

    for bucket in ["easy", "medium", "hard", "overall"]:
        if bucket == "overall":
            candidates = [it for it in tagged_items if it.get("expected_behaviour") == "answer" and it.get("gold_chunk_ids")]
            total_b = len(tagged_items)
        else:
            candidates = [it for it in bucket_items[bucket] if it.get("expected_behaviour") == "answer" and it.get("gold_chunk_ids")]
            total_b = len(bucket_items[bucket])

        if not candidates:
            continue

        recalls = []
        mrrs = []
        ndcgs = []

        for it in candidates:
            q = it["question"]
            gold = set(it["gold_chunk_ids"])
            role = it.get("role_asking", "analyst")
            hits = indexer.search(q, top_k=5, role=role).hits
            retrieved_ids = [h["chunk_id"] for h in hits]

            # Recall@5
            hits_in_gold = set(retrieved_ids) & gold
            rec = len(hits_in_gold) / len(gold) if gold else 0.0
            recalls.append(rec)

            # MRR
            rank = 0
            for idx, cid in enumerate(retrieved_ids, start=1):
                if cid in gold:
                    rank = idx
                    break
            mrr = (1.0 / rank) if rank > 0 else 0.0
            mrrs.append(mrr)

            # nDCG@5
            dcg = 0.0
            for idx, cid in enumerate(retrieved_ids, start=1):
                rel = 1.0 if cid in gold else 0.0
                dcg += rel / math.log2(idx + 1)
            idcg = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(gold), 5) + 1))
            ndcg = (dcg / idcg) if idcg > 0 else 0.0
            ndcgs.append(ndcg)

        r_res = bootstrap_ci(recalls)
        m_res = bootstrap_ci(mrrs)
        n_res = bootstrap_ci(ndcgs)

        r_mean, r_ci = r_res["mean"], (r_res["ci_low"], r_res["ci_high"])
        m_mean, m_ci = m_res["mean"], (m_res["ci_low"], m_res["ci_high"])
        n_mean, n_ci = n_res["mean"], (n_res["ci_low"], n_res["ci_high"])

        metrics_per_bucket[bucket] = {
            "total_items": total_b,
            "answerable_items": len(candidates),
            "recall_at_5": {"mean": r_mean, "ci_95": list(r_ci)},
            "mrr": {"mean": m_mean, "ci_95": list(m_ci)},
            "ndcg_at_5": {"mean": n_mean, "ci_95": list(n_ci)},
        }

        # Check for ceiling effect (> 0.95)
        if r_mean > 0.95:
            ceiling_warnings.append(f"Recall@5 in '{bucket}' bucket is {r_mean:.4f} > 0.95 (Ceiling Effect)")
        if m_mean > 0.95:
            ceiling_warnings.append(f"MRR in '{bucket}' bucket is {m_mean:.4f} > 0.95 (Ceiling Effect)")

        r_str = f"{r_mean:.4f} [{r_ci[0]:.3f}, {r_ci[1]:.3f}]"
        m_str = f"{m_mean:.4f} [{m_ci[0]:.3f}, {m_ci[1]:.3f}]"
        n_str = f"{n_mean:.4f} [{n_ci[0]:.3f}, {n_ci[1]:.3f}]"

        print(f"{bucket.capitalize():<8} | {total_b:<6} | {len(candidates):<10} | {r_str:<22} | {m_str:<22} | {n_str:<22}")

    print("-" * 80)
    if ceiling_warnings:
        print("\n[WARNING: CEILING EFFECT DETECTED]")
        for w in ceiling_warnings:
            print(f"  * {w}")
        print("  Notice: High lexical overlap between questions and statutory passages artificially")
        print("          elevates retrieval metrics. Harder paraphrased and cross-document questions are required.")
    print("=" * 80 + "\n")

    report_payload = {
        "gold_benchmark_file": str(gold_path),
        "total_gold_items": len(tagged_items),
        "difficulty_counts": {k: len(v) for k, v in bucket_items.items()},
        "metrics_per_bucket": metrics_per_bucket,
        "ceiling_effect_warnings": ceiling_warnings,
        "tagged_items_sample": tagged_items[:5],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report_payload, f, indent=2)

    return report_payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate retrieval difficulty across gold benchmark.")
    parser.add_argument("--gold", type=Path, default=Path("data/eval/gold_set.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("reports/retrieval_difficulty_report.json"))
    args = parser.parse_args()

    evaluate_retrieval_by_difficulty(args.gold, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
