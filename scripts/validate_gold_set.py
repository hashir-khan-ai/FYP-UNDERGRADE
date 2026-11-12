"""Validate ``data/eval/gold_set.jsonl`` schema, chunk IDs, and type quotas."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.gold_set import validate_gold_set_file


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
    args = parser.parse_args()

    report = validate_gold_set_file(
        gold_set_path=args.path,
        min_per_type=args.min_per_type,
    )

    print("==============================================================================")
    print(f"GOLD SET VALIDATION REPORT ({args.path})")
    print("==============================================================================")
    print(f"Total questions   : {report.total_count}")
    print(f"Counts by status  : {report.counts_by_status}")
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

    print(f"Overall status    : {'PASSED' if report.valid else 'FAILED'}")
    print("==============================================================================")

    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())

