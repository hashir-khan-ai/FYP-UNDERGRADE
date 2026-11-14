"""Apply exported human review decisions to the gold dataset and review sheet.

Reads ``data/gold_review_decisions.json`` (exported by ``reports/gold_review.html``)
and updates **only** items with an explicit actionable human decision
(``approved``, ``needs_fix``, ``rejected``, or ``unanswerable_correct``).

- Undecided and ``skipped`` items are left completely untouched.
- Sets ``reviewed_by="human"``, ``reviewed_at``, and ``human_notes``.
- For ``needs_fix`` items, preserves both original values
  (``original_gold_answer``, ``original_clause``, ``original_gold_chunk_ids``)
  and the corrected values.
- For ``rejected`` items, marks ``status="rejected"`` and ``review_status="rejected"``
  so evaluation helpers and ablation scripts exclude them from metrics.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ACTIONABLE_DECISIONS = frozenset(
    {"approved", "needs_fix", "rejected", "unanswerable_correct"}
)
CHUNK_ID_TOKEN_RE = re.compile(r"^DOC-[A-Za-z0-9-]+_[A-Za-z0-9._-]+$")
DEFAULT_CSV_COLUMNS = [
    "id",
    "question",
    "expected answer",
    "source clause",
    "role",
    "review_status",
    "reviewed_by",
    "reviewed_at",
    "answerable_from_cited_clause",
    "expected_answer_correct",
    "role_correct",
    "difficulty",
    "human_notes",
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_decisions(decisions_path: str | Path) -> dict[str, dict[str, Any]]:
    """Parse ``gold_review_decisions.json`` and return only actionable decisions."""
    path = Path(decisions_path)
    if not path.exists():
        raise FileNotFoundError(f"Decisions file not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))

    raw_map: dict[str, dict[str, Any]] = {}
    if isinstance(payload, dict) and isinstance(payload.get("decisions"), dict):
        raw_map = {str(k): v for k, v in payload["decisions"].items() if isinstance(v, dict)}
    elif isinstance(payload, dict):
        raw_map = {str(k): v for k, v in payload.items() if isinstance(v, dict)}
    elif isinstance(payload, list):
        for entry in payload:
            if isinstance(entry, dict) and entry.get("id"):
                raw_map[str(entry["id"])] = entry
    else:
        raise ValueError("Unsupported decisions JSON structure.")

    actionable: dict[str, dict[str, Any]] = {}
    for qid, entry in raw_map.items():
        verdict = str(entry.get("decision") or "").strip().lower()
        if verdict not in ACTIONABLE_DECISIONS:
            continue
        item_id = str(entry.get("id") or qid).strip()
        if item_id:
            normalized = dict(entry)
            normalized["id"] = item_id
            normalized["decision"] = verdict
            actionable[item_id] = normalized
    return actionable


def _parse_chunk_id_list(raw_clause: str) -> list[str] | None:
    """If ``raw_clause`` is strictly comma/whitespace-separated DOC chunk IDs, parse them."""
    tokens = [tok.strip() for tok in re.split(r"[\s,;]+", raw_clause.strip()) if tok.strip()]
    if tokens and all(CHUNK_ID_TOKEN_RE.match(tok) for tok in tokens):
        return tokens
    return None


def _apply_decision_to_json_record(
    row: dict[str, Any],
    decision: dict[str, Any],
    fallback_timestamp: str,
) -> dict[str, Any]:
    """Return updated copy of a gold JSON record, preserving original fields on fix."""
    updated = dict(row)
    verdict = decision["decision"]
    decided_at = str(decision.get("decided_at") or fallback_timestamp).strip()
    reviewed_on = decided_at[:10]
    notes = str(decision.get("human_notes") or "").strip()

    updated["reviewed_by"] = "human"
    updated["reviewed_at"] = decided_at
    updated["reviewed_on"] = reviewed_on
    updated["review_status"] = verdict
    if verdict == "rejected":
        updated["status"] = "rejected"
    else:
        updated["status"] = "reviewed"

    if notes:
        updated["human_notes"] = notes

    if verdict == "needs_fix":
        orig_answer = updated.get("original_gold_answer") or row.get("gold_answer", "")
        updated["original_gold_answer"] = orig_answer
        corrected_answer = str(decision.get("corrected_answer") or "").strip()
        if corrected_answer:
            updated["gold_answer"] = corrected_answer

        orig_clause = updated.get("original_clause")
        if orig_clause is None:
            orig_clause = row.get("clause", "")
        updated["original_clause"] = orig_clause

        corrected_clause = str(decision.get("corrected_clause") or "").strip()
        explicit_chunks = decision.get("corrected_chunk_ids")
        if isinstance(explicit_chunks, list) and explicit_chunks:
            if updated.get("original_gold_chunk_ids") is None:
                updated["original_gold_chunk_ids"] = list(row.get("gold_chunk_ids", []))
            updated["gold_chunk_ids"] = [str(c).strip() for c in explicit_chunks if str(c).strip()]
        elif corrected_clause:
            parsed_ids = _parse_chunk_id_list(corrected_clause)
            if parsed_ids:
                if updated.get("original_gold_chunk_ids") is None:
                    updated["original_gold_chunk_ids"] = list(row.get("gold_chunk_ids", []))
                updated["gold_chunk_ids"] = parsed_ids
            updated["clause"] = corrected_clause

    return updated


def _update_jsonl_file(
    path: Path,
    decisions: dict[str, dict[str, Any]],
    fallback_timestamp: str,
) -> tuple[int, dict[str, dict[str, Any]]]:
    """Update matching lines in a JSONL file in place; leave undecided lines untouched."""
    if not path.exists():
        return 0, {}

    raw_lines = path.read_text(encoding="utf-8").splitlines()
    out_lines: list[str] = []
    updated_map: dict[str, dict[str, Any]] = {}
    updated_count = 0

    for raw_line in raw_lines:
        stripped = raw_line.strip()
        if not stripped:
            continue
        parsed = json.loads(stripped)
        qid = str(parsed.get("id") or "").strip()
        if qid in decisions:
            new_row = _apply_decision_to_json_record(parsed, decisions[qid], fallback_timestamp)
            updated_map[qid] = new_row
            out_lines.append(json.dumps(new_row, ensure_ascii=False))
            updated_count += 1
        else:
            out_lines.append(stripped)

    if updated_count > 0:
        path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return updated_count, updated_map


def _update_json_array_file(
    path: Path,
    decisions: dict[str, dict[str, Any]],
    fallback_timestamp: str,
) -> int:
    """Update matching items in a JSON array file (e.g. ``data/gold_v2.json``)."""
    if not path.exists():
        return 0
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        return 0

    updated_count = 0
    out_rows: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict) and str(row.get("id") or "").strip() in decisions:
            qid = str(row["id"]).strip()
            out_rows.append(_apply_decision_to_json_record(row, decisions[qid], fallback_timestamp))
            updated_count += 1
        else:
            out_rows.append(row)

    if updated_count > 0:
        path.write_text(json.dumps(out_rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return updated_count


def _format_csv_notes(existing_notes: str, new_notes: str, original_snapshot: str) -> str:
    """Combine human review notes and original pre-fix text cleanly without duplicating."""
    parts: list[str] = []
    base = new_notes.strip() or existing_notes.strip()
    if base:
        parts.append(base)
    if original_snapshot and original_snapshot not in base:
        parts.append(original_snapshot)
    return " | ".join(parts)


def _apply_decision_to_csv_row(
    row: dict[str, str],
    decision: dict[str, Any],
    json_record: dict[str, Any] | None,
    fallback_timestamp: str,
) -> dict[str, str]:
    """Update a CSV review sheet row for an actionable human decision."""
    updated = dict(row)
    verdict = decision["decision"]
    decided_at = str(decision.get("decided_at") or fallback_timestamp).strip()

    updated["review_status"] = verdict
    updated["reviewed_by"] = "human"
    updated["reviewed_at"] = decided_at

    if verdict == "approved":
        updated["answerable_from_cited_clause"] = updated.get("answerable_from_cited_clause") or "yes"
        updated["expected_answer_correct"] = "yes"
        updated["role_correct"] = updated.get("role_correct") or "yes"
    elif verdict == "unanswerable_correct":
        updated["answerable_from_cited_clause"] = "no (unanswerable/restricted)"
        updated["expected_answer_correct"] = "yes"
        updated["role_correct"] = updated.get("role_correct") or "yes"
    elif verdict == "rejected":
        updated["expected_answer_correct"] = "no"
    elif verdict == "needs_fix":
        updated["expected_answer_correct"] = "fixed"

    notes = str(decision.get("human_notes") or "").strip()
    orig_snapshot_parts: list[str] = []

    if verdict == "needs_fix":
        prev_answer = row.get("expected answer", "")
        corrected_answer = str(decision.get("corrected_answer") or "").strip()
        if corrected_answer:
            if prev_answer and corrected_answer != prev_answer:
                orig_snapshot_parts.append(f"original_answer={prev_answer}")
            updated["expected answer"] = corrected_answer

        prev_clause = row.get("source clause", "")
        corrected_clause = str(decision.get("corrected_clause") or "").strip()
        if corrected_clause:
            if prev_clause and corrected_clause != prev_clause:
                orig_snapshot_parts.append(f"original_clause={prev_clause}")
            updated["source clause"] = corrected_clause

    updated["human_notes"] = _format_csv_notes(
        row.get("human_notes", ""),
        notes,
        "; ".join(orig_snapshot_parts),
    )

    if json_record and not updated.get("difficulty"):
        qtype = str(json_record.get("type") or "")
        updated["difficulty"] = "hard" if qtype in ("cross_reference", "multi_part") else "medium"
    return updated


def _update_csv_sheet(
    csv_path: Path,
    decisions: dict[str, dict[str, Any]],
    json_records_by_id: dict[str, dict[str, Any]],
    fallback_timestamp: str,
) -> int:
    """Update only decided rows in ``data/gold_review_sheet.csv`` (append newly decided IDs if missing)."""
    if csv_path.exists():
        with open(csv_path, "r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = list(reader.fieldnames or DEFAULT_CSV_COLUMNS)
            rows = list(reader)
    else:
        fieldnames = list(DEFAULT_CSV_COLUMNS)
        rows = []

    existing_ids: set[str] = set()
    updated_rows: list[dict[str, str]] = []
    updated_count = 0

    for row in rows:
        qid = (row.get("id") or "").strip()
        if qid:
            existing_ids.add(qid)
        if qid in decisions:
            new_row = _apply_decision_to_csv_row(
                row,
                decisions[qid],
                json_records_by_id.get(qid),
                fallback_timestamp,
            )
            updated_rows.append(new_row)
            updated_count += 1
        else:
            updated_rows.append(row)

    # Append newly human-reviewed items (e.g. HARD-Q-*) only if the human decided them
    for qid, decision in decisions.items():
        if qid in existing_ids:
            continue
        jrec = json_records_by_id.get(qid)
        if not jrec:
            continue
        base_row: dict[str, str] = {col: "" for col in fieldnames}
        base_row["id"] = qid
        base_row["question"] = str(jrec.get("question", ""))
        orig_ans = str(jrec.get("original_gold_answer") or jrec.get("gold_answer", ""))
        orig_cls = str(jrec.get("original_clause") or jrec.get("clause", ""))
        base_row["expected answer"] = orig_ans
        base_row["source clause"] = orig_cls
        base_row["role"] = str(jrec.get("role_asking", ""))
        new_row = _apply_decision_to_csv_row(base_row, decision, jrec, fallback_timestamp)
        updated_rows.append(new_row)
        updated_count += 1

    if updated_count > 0:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(csv_path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(updated_rows)

    return updated_count


def apply_review(
    decisions_path: str | Path = PROJECT_ROOT / "data" / "gold_review_decisions.json",
    gold_jsonl_path: str | Path = PROJECT_ROOT / "data" / "eval" / "gold_set.jsonl",
    sheet_csv_path: str | Path = PROJECT_ROOT / "data" / "gold_review_sheet.csv",
    sync_paths: list[str | Path] | None = None,
) -> dict[str, Any]:
    """Apply exported human review decisions without modifying undecided or skipped items."""
    decisions = load_decisions(decisions_path)
    fallback_timestamp = _utc_now_iso()

    primary_jsonl = Path(gold_jsonl_path)
    primary_count, updated_json_records = _update_jsonl_file(
        primary_jsonl,
        decisions,
        fallback_timestamp,
    )

    if sync_paths is None:
        sync_candidates = [
            PROJECT_ROOT / "data" / "gold_v2.jsonl",
            PROJECT_ROOT / "data" / "eval" / "gold_v2.jsonl",
            PROJECT_ROOT / "data" / "gold_v2.json",
        ]
    else:
        sync_candidates = [Path(p) for p in sync_paths]

    synced_counts: dict[str, int] = {}
    for candidate in sync_candidates:
        if not candidate.exists() or candidate.resolve() == primary_jsonl.resolve():
            continue
        if candidate.suffix.lower() == ".json":
            cnt = _update_json_array_file(candidate, decisions, fallback_timestamp)
        else:
            cnt, _ = _update_jsonl_file(candidate, decisions, fallback_timestamp)
        synced_counts[str(candidate)] = cnt

    csv_count = _update_csv_sheet(
        Path(sheet_csv_path),
        decisions,
        updated_json_records,
        fallback_timestamp,
    )

    verdict_counts: dict[str, int] = {}
    for entry in decisions.values():
        v = entry["decision"]
        verdict_counts[v] = verdict_counts.get(v, 0) + 1

    return {
        "actionable_decisions": len(decisions),
        "verdict_counts": verdict_counts,
        "updated_gold_jsonl": primary_count,
        "updated_csv_rows": csv_count,
        "synced_files": synced_counts,
    }


def main() -> int:
    """CLI entry point to apply human review decisions."""
    parser = argparse.ArgumentParser(description="Apply exported human review decisions to gold files.")
    parser.add_argument("--decisions", default=str(PROJECT_ROOT / "data" / "gold_review_decisions.json"))
    parser.add_argument("--gold-path", default=str(PROJECT_ROOT / "data" / "eval" / "gold_set.jsonl"))
    parser.add_argument("--sheet-path", default=str(PROJECT_ROOT / "data" / "gold_review_sheet.csv"))
    args = parser.parse_args()

    summary = apply_review(
        decisions_path=args.decisions,
        gold_jsonl_path=args.gold_path,
        sheet_csv_path=args.sheet_path,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

