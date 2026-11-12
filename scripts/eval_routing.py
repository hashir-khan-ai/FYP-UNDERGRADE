"""Routing evaluation harness for the Phase 4 adaptive router.

Runs the router over the labelled question set and reports accuracy, a confusion
matrix, the fallback rate, and average latency/tokens per predicted route. Every
call goes through the single LLM gateway, so the on-disk response cache makes a
rerun of the same profile cost nothing.

The label file in ``data/eval/`` is a DRAFT pending student review; the output
records that status alongside the profile and model that produced the numbers.

Usage:
    python scripts/eval_routing.py --profile mock
    python scripts/eval_routing.py --profile dev
"""

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import settings  # noqa: E402
from src.core.llm_client import llm_client  # noqa: E402
from src.core.router import classify_question  # noqa: E402
from src.core.spend_guard import SpendGuardExceededError  # noqa: E402
from src.db.connection import get_db_connection  # noqa: E402
from src.db.migrations import init_db  # noqa: E402
from src.db.repository import Repository  # noqa: E402

ROUTE_ORDER = ("direct", "single_search", "split")
DEFAULT_LABELS = PROJECT_ROOT / "data" / "eval" / "routing_labels.jsonl"


def load_labels(path: Path) -> tuple[list[dict], dict]:
    """Load JSONL labels, returning (rows, meta). Lines with ``_meta`` are metadata."""
    rows: list[dict] = []
    meta: dict = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                item = json.loads(text)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"Invalid JSON on line {line_number} of {path}: {exc}") from exc
            if "_meta" in item:
                meta = dict(item["_meta"])
                continue
            if item.get("expected_route") not in ROUTE_ORDER:
                raise SystemExit(
                    f"Line {line_number}: expected_route must be one of {ROUTE_ORDER}."
                )
            rows.append(item)
    if not rows:
        raise SystemExit(f"No labelled questions found in {path}.")
    return rows, meta


def _write_results(payload: dict, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = output_dir / f"routing_eval_{payload['profile']}_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _cache_counters(after_id: int) -> dict[str, int]:
    with get_db_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS calls,
                   COALESCE(SUM(cached), 0) AS cache_hits
            FROM llm_calls
            WHERE id > ?;
            """,
            (after_id,),
        ).fetchone()
    return {
        "calls": int(row["calls"] or 0) if row else 0,
        "cache_hits": int(row["cache_hits"] or 0) if row else 0,
    }


def run(profile: str | None, labels_path: Path, output_dir: Path) -> int:
    """Execute the routing evaluation and return a process exit code."""
    if profile:
        os.environ["LLM_PROFILE"] = profile
        settings.LLM_PROFILE = profile

    try:
        active = settings.llm
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: cannot resolve LLM profile '{settings.LLM_PROFILE}': {exc}")
        return 2

    init_db()
    labels, meta = load_labels(labels_path)

    with get_db_connection() as conn:
        call_floor = Repository(conn).get_max_llm_call_id()

    print("=" * 80)
    print(f"ROUTING EVALUATION (profile={active.profile}, model={active.model})")
    print(f"Prompt version: {settings.PROMPT_VERSION} | Labels: {labels_path.name} ({len(labels)} items)")
    print(f"Label status: {meta.get('status', 'unlabelled')} (student review pending)")
    print("=" * 80)

    rows: list[dict] = []
    status = "completed"
    for item in labels:
        start = time.perf_counter()
        try:
            decision = classify_question(llm_client, str(item["query"]), session_id=None)
        except SpendGuardExceededError as exc:
            status = "aborted_spend_limit"
            print(f"\nSTOPPED: {exc}")
            break
        except Exception as exc:  # sanitized: never echo prompts or keys
            rows.append(
                {
                    "id": item["id"],
                    "category": item.get("category"),
                    "query": item["query"],
                    "expected_route": item["expected_route"],
                    "predicted_route": "error",
                    "confidence": None,
                    "fallback_used": False,
                    "fallback_reason": None,
                    "latency_ms": round((time.perf_counter() - start) * 1000.0, 2),
                    "tokens_used": 0,
                    "error": type(exc).__name__,
                }
            )
            continue

        rows.append(
            {
                "id": item["id"],
                "category": item.get("category"),
                "query": item["query"],
                "expected_route": item["expected_route"],
                "predicted_route": decision.route,
                "confidence": decision.confidence,
                "fallback_used": decision.fallback_used,
                "fallback_reason": decision.fallback_reason,
                "direct_category": decision.direct_category,
                "latency_ms": round((time.perf_counter() - start) * 1000.0, 2),
                "tokens_used": decision.tokens_used,
            }
        )

    scored = [row for row in rows if row["predicted_route"] in ROUTE_ORDER]
    correct = sum(1 for row in scored if row["predicted_route"] == row["expected_route"])
    total = len(scored)
    accuracy = (correct / total) if total else 0.0

    confusion: dict[str, dict[str, int]] = {
        expected: {predicted: 0 for predicted in ROUTE_ORDER} for expected in ROUTE_ORDER
    }
    for row in scored:
        confusion[row["expected_route"]][row["predicted_route"]] += 1

    fallbacks = sum(1 for row in scored if row["fallback_used"])
    fallback_rate = (fallbacks / total) if total else 0.0

    per_route: dict[str, dict[str, float | int]] = {}
    for route in ROUTE_ORDER:
        group = [row for row in scored if row["predicted_route"] == route]
        if not group:
            per_route[route] = {"count": 0, "avg_latency_ms": 0.0, "avg_tokens": 0.0, "avg_confidence": 0.0}
            continue
        confidences = [row["confidence"] for row in group if row["confidence"] is not None]
        per_route[route] = {
            "count": len(group),
            "avg_latency_ms": round(sum(row["latency_ms"] for row in group) / len(group), 2),
            "avg_tokens": round(sum(row["tokens_used"] for row in group) / len(group), 2),
            "avg_confidence": (
                round(sum(confidences) / len(confidences), 3) if confidences else 0.0
            ),
        }

    counters = _cache_counters(call_floor)
    payload = {
        "run_id": f"routing_eval_{active.profile}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "profile": active.profile,
        "model": active.model,
        "prompt_version": settings.PROMPT_VERSION,
        "heading_path_enabled": settings.ENABLE_HEADING_PATH,
        "temperature": settings.LLM_TEMPERATURE,
        "labels_file": str(labels_path),
        "labels_status": meta.get("status", "unlabelled"),
        "label_count": len(labels),
        "accuracy": round(accuracy, 4),
        "correct": correct,
        "scored": total,
        "fallback_rate": round(fallback_rate, 4),
        "confusion_matrix": confusion,
        "per_route": per_route,
        "llm_calls": counters["calls"],
        "cache_hits": counters["cache_hits"],
        "rows": rows,
    }
    output_path = _write_results(payload, output_dir)

    print(f"\nAccuracy      : {accuracy:.1%} ({correct}/{total})")
    print(f"Fallback rate : {fallback_rate:.1%} ({fallbacks}/{total})")
    print(f"LLM calls     : {counters['calls']} (cache hits {counters['cache_hits']})")
    print("\nConfusion matrix (rows = expected, columns = predicted)")
    header = f"{'expected':<16}" + "".join(f"{route:<16}" for route in ROUTE_ORDER)
    print(header)
    print("-" * len(header))
    for expected in ROUTE_ORDER:
        cells = "".join(f"{confusion[expected][predicted]:<16}" for predicted in ROUTE_ORDER)
        print(f"{expected:<16}{cells}")
    print("\nPer predicted route")
    print(f"{'route':<16}{'n':<6}{'avg latency ms':<18}{'avg tokens':<14}{'avg confidence':<15}")
    print("-" * 69)
    for route in ROUTE_ORDER:
        stats = per_route[route]
        print(
            f"{route:<16}{stats['count']:<6}{stats['avg_latency_ms']:<18}"
            f"{stats['avg_tokens']:<14}{stats['avg_confidence']:<15}"
        )
    if status != "completed":
        print(f"\nStatus: {status} (partial results written)")
    print(f"\nResults written to: {output_path}")
    print("=" * 80)
    return 0 if status == "completed" else 3


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate adaptive router accuracy on labelled questions.")
    parser.add_argument(
        "--profile",
        default=None,
        choices=["mock", "dev", "demo"],
        help="Override the LLM profile for this run only",
    )
    parser.add_argument(
        "--labels",
        default=str(DEFAULT_LABELS),
        help="Path to the JSONL label file",
    )
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "evaluation" / "results"),
        help="Directory for the result artifact",
    )
    args = parser.parse_args()
    raise SystemExit(
        run(
            profile=args.profile,
            labels_path=Path(args.labels),
            output_dir=Path(args.output_dir),
        )
    )


if __name__ == "__main__":
    main()
