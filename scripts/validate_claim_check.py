"""Validate post-generation claim_check precision and recall against human labels (Phase 9D).

Evaluates `verify_answer_claims` from `src.core.claim_check` against `data/claim_labels.csv`.
Computes:
- True Positives (TP), False Positives (FP)
- True Negatives (TN), False Negatives (FN)
- Precision, Recall, F1 Score, Accuracy
Does NOT use `unsupported_claim_rate` from claim_check itself as the headline metric.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.claim_check import verify_answer_claims


def run_claim_validation(csv_path: str = "data/claim_labels_blind.csv") -> dict[str, Any] | None:
    path = Path(csv_path)
    if "agent_draft" in str(path).lower():
        print(f"[REFUSED] Agent draft labels in '{path}' are excluded from evaluation metrics.", file=sys.stderr)
        print("Please provide human-filled blind labels via data/claim_labels_blind.csv.", file=sys.stderr)
        return None

    if not path.exists():
        raise FileNotFoundError(f"Missing {csv_path}. Provide human-labeled blind CSV.")

    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print(f"[REFUSED] '{path}' is empty.", file=sys.stderr)
        return None

    # Check for blank / unlabelled rows
    blank_indices = [
        idx + 1 for idx, row in enumerate(rows)
        if not (row.get("human_label") or "").strip()
    ]
    if blank_indices:
        print(
            f"[REFUSED] Found {len(blank_indices)} unlabelled/blank row(s) in '{path}' "
            f"(e.g., rows: {blank_indices[:5]}...). Human evaluation must fill every label before running.",
            file=sys.stderr,
        )
        return None

    tp = 0  # Human supported, Model predicted supported
    fp = 0  # Human unsupported, Model predicted supported
    tn = 0  # Human unsupported, Model predicted unsupported/weak
    fn = 0  # Human supported, Model predicted unsupported/weak

    detailed_results: list[dict[str, Any]] = []

    for row in rows:
        claim_id = row["claim_id"]
        claim_text = row["claim_text"]
        ref_context = row["reference_context"]
        human_label = row["human_label"].strip().lower()

        # Build passage structure for verify_answer_claims
        mock_passage = {
            "chunk_id": f"REF-{claim_id}",
            "doc_id": "DOC-REF",
            "doc_title": "Regulatory Reference Document",
            "section": "Section 1",
            "clause": "1.0",
            "heading_path": "Regulatory Reference > Compliance Rules",
            "snippet": ref_context,
            "text": ref_context,
            "text_content": ref_context,
            "allowed_roles": ["analyst", "manager", "auditor"],
            "score": 0.95,
        }

        # Evaluate claim using core claim check engine
        res = verify_answer_claims(
            answer=claim_text,
            passages=[mock_passage],
            role="analyst",
            rbac_enabled=True,
            remove_unsupported=False,
        )

        pred_status = "unsupported"
        pred_score = 0.0
        if res.claims:
            pred_status = res.claims[0].status
            pred_score = res.claims[0].score

        is_pred_supported = (pred_status == "supported")
        is_human_supported = (human_label == "supported")

        if is_human_supported and is_pred_supported:
            tp += 1
            classification = "TP"
        elif not is_human_supported and is_pred_supported:
            fp += 1
            classification = "FP"
        elif not is_human_supported and not is_pred_supported:
            tn += 1
            classification = "TN"
        else:
            fn += 1
            classification = "FN"

        detailed_results.append({
            "claim_id": claim_id,
            "claim_text": claim_text[:60] + "...",
            "human_label": human_label,
            "pred_status": pred_status,
            "score": round(pred_score, 3),
            "class": classification,
        })

    total = len(rows)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    accuracy = (tp + tn) / total if total > 0 else 0.0

    metrics = {
        "total_claims": total,
        "true_positives": tp,
        "false_positives": fp,
        "true_negatives": tn,
        "false_negatives": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1_score": round(f1, 4),
        "accuracy": round(accuracy, 4),
    }

    print("==========================================================================")
    print("CLAIM-CHECK HUMAN-VALIDATION METRIC REPORT (Phase 9D)")
    print("==========================================================================")
    print(f"Total Sampled Claims : {total}")
    print(f"Human Distribution   : {tp + fn} Supported | {fp + tn} Unsupported")
    print("--------------------------------------------------------------------------")
    print(f"Confusion Matrix     : TP={tp} | FP={fp} | TN={tn} | FN={fn}")
    print(f"Precision (Supported): {precision:.4f} ({precision * 100:.1f}%)")
    print(f"Recall (Supported)   : {recall:.4f} ({recall * 100:.1f}%)")
    print(f"F1-Score             : {f1:.4f}")
    print(f"Overall Accuracy     : {accuracy:.4f} ({accuracy * 100:.1f}%)")
    print("==========================================================================")
    print("NOTE: Evaluated against external human ground-truth labels in data/claim_labels.csv")
    print("      Does NOT use unsupported_claim_rate from claim_check itself as headline.")
    print("==========================================================================")

    return metrics


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Validate claim_check against human labels.")
    parser.add_argument(
        "--labels",
        type=str,
        default="data/claim_labels_blind.csv",
        help="Path to CSV containing human-labeled claims (default: data/claim_labels_blind.csv)",
    )
    args = parser.parse_args()
    res = run_claim_validation(args.labels)
    if res is None:
        sys.exit(2)
