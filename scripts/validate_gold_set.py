"""Validate ``data/eval/gold_set.jsonl`` schema, chunk IDs, and type quotas."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.gold_set import DEFAULT_MIN_REVIEWED, validate_gold_set_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Phase 7 gold evaluation dataset.")
    parser.add_argument(
        "--path",
        type=str,
        default="data/eval/gold_set.jsonl",
        help="Path to the gold set JSONL file (default: data/eval/gold_set.jsonl).",
    )
    parser.add_argument(
        "--min-per-type",
        type=int,
        default=15,
        help="Minimum questions required per question type (default: 15).",
    )
    parser.add_argument(
        "--min-reviewed",
        type=int,
        default=0,
        help=(
            "Fail unless at least N questions are status 'reviewed' (default: 0 = report only). "
            f"The final ablation gate in run_ablation.py uses {DEFAULT_MIN_REVIEWED}."
        ),
    )
    args = parser.parse_args()

    report = validate_gold_set_file(
        gold_set_path=args.path,
        min_per_type=args.min_per_type,
    )
    reviewed_n = report.counts_by_status.get("reviewed", 0)
    draft_n = report.counts_by_status.get("draft", 0)
    gate_n = args.min_reviewed if args.min_reviewed > 0 else DEFAULT_MIN_REVIEWED

    print("==============================================================================")
    print(f"GOLD SET VALIDATION REPORT ({args.path})")
    print("==============================================================================")
    print(f"Total questions   : {report.total_count}")
    print(f"Reviewed          : {reviewed_n}")
    print(f"Draft             : {draft_n}")
    print(
        f"Final ablation    : {'READY' if reviewed_n >= gate_n else 'NOT READY'} "
        f"({reviewed_n}/{gate_n} reviewed required for run_ablation.py --require-reviewed)"
    )
    print(f"Counts by role    : {report.counts_by_role}")
    print(f"Counts by action  : {report.counts_by_behaviour}")
    print("------------------------------------------------------------------------------")
    print("Counts by question type (target >= 15 each):")
    for qtype, count in report.counts_by_type.items():
        status_mark = "OK" if count >= args.min_per_type else "FAIL"
        print(f"  - {qtype:<18}: {count:>3}  [{status_mark}]")
    print("------------------------------------------------------------------------------")

    if report.schema_errors:
        print(f"Schema errors ({len(report.schema_errors)}):")
        for err in report.schema_errors:
            print(f"  [SCHEMA] {err}")

    if report.missing_chunk_errors:
        print(f"Missing chunk errors ({len(report.missing_chunk_errors)}):")
        for err in report.missing_chunk_errors:
            print(f"  [CHUNK]  {err}")

    if report.type_quota_errors:
        print(f"Type quota errors ({len(report.type_quota_errors)}):")
        for err in report.type_quota_errors:
            print(f"  [QUOTA]  {err}")

    reviewed_gate_failed = args.min_reviewed > 0 and reviewed_n < args.min_reviewed
    if reviewed_gate_failed:
        print(f"  [REVIEW] Only {reviewed_n} reviewed question(s); --min-reviewed requires {args.min_reviewed}.")

    overall_ok = report.valid and not reviewed_gate_failed
    print(f"Overall status    : {'PASSED' if overall_ok else 'FAILED'}")
    print("==============================================================================")

    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

