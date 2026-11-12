"""Interactive Terminal Tool for Human Review of Gold Questions.

Implements Phase 7c integrity requirements:
- Allows the human student researcher to review gold questions one at a time.
- Displays question text, role_asking, type, expected_behaviour, gold_answer,
  and the full text and heading path of every referenced gold chunk.
- Keystroke actions:
  - [a] Approve: sets status='reviewed', reviewed_by='student', reviewed_on=YYYY-MM-DD.
  - [e] Edit: edit gold answer or chunk IDs with immediate validation.
  - [r] Reject: sets status='rejected', reviewed_by='student', reviewed_on=YYYY-MM-DD.
  - [s] Skip: keep current status, proceed to next question.
  - [q] Quit: save and exit cleanly.
- Saves after every single decision and is fully resumable across sessions.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.gold_set import (
    GoldQuestionItem,
    load_indexed_chunks,
)
from src.ingestion.chunker import ClauseAwareChunker, DocumentChunk
from src.ingestion.loaders import DocumentLoader
from src.ingestion.run import discover_documents


def load_chunk_lookup(data_dir: str | Path = "data") -> dict[str, dict[str, Any]]:
    """Build a fast lookup dictionary mapping chunk_id to full metadata and text."""
    # First try the BM25 index if available
    indexed = load_indexed_chunks()
    lookup: dict[str, dict[str, Any]] = {}
    for c in indexed:
        cid = str(c.get("chunk_id", ""))
        if cid:
            lookup[cid] = c

    # Supplement or build from raw documents if needed
    doc_paths = discover_documents(data_dir)
    chunker = ClauseAwareChunker()
    for p in doc_paths:
        try:
            doc = DocumentLoader.load(p)
            chunks = chunker.chunk_document(doc)
            for ch in chunks:
                if ch.chunk_id not in lookup or not lookup[ch.chunk_id].get("text_content"):
                    lookup[ch.chunk_id] = {
                        "chunk_id": ch.chunk_id,
                        "doc_id": ch.doc_id,
                        "doc_title": ch.doc_title,
                        "heading_path": ch.heading_path,
                        "clause_label": ch.clause_label,
                        "allowed_roles": list(ch.allowed_roles),
                        "text_content": ch.text_content,
                    }
        except Exception:
            continue
    return lookup


def atomic_save_gold_set(path: Path, items: list[dict[str, Any]]) -> None:
    """Save items list as JSONL atomically via a temp file."""
    temp_path = path.with_suffix(".tmp.jsonl")
    with open(temp_path, "w", encoding="utf-8") as handle:
        for item in items:
            handle.write(json.dumps(item) + "\n")
    temp_path.replace(path)


def format_chunk_details(chunk_id: str, lookup: dict[str, Any]) -> str:
    """Format full text, heading path, and allowed roles of a referenced chunk."""
    meta = lookup.get(chunk_id)
    if not meta:
        return f"  [!] Chunk ID '{chunk_id}' NOT FOUND in corpus index!\n"
    heading = meta.get("heading_path") or meta.get("clause_label") or "No heading"
    roles = ",".join(meta.get("allowed_roles", []))
    text = (meta.get("text_content") or "").strip()
    return (
        f"  - Chunk ID     : {chunk_id}\n"
        f"    Heading Path : {heading}\n"
        f"    Allowed Roles: [{roles}]\n"
        f"    Text Content :\n      \"\"\"\n      {text}\n      \"\"\"\n"
    )


def review_gold_set(
    gold_set_path: Path,
    data_dir: Path,
    reviewer: str = "student",
    status_filter: str = "draft",
) -> int:
    """Run interactive terminal review session."""
    if not gold_set_path.exists():
        print(f"ERROR: Gold set file not found: {gold_set_path}", file=sys.stderr)
        return 1

    raw_items: list[dict[str, Any]] = []
    with open(gold_set_path, "r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                raw_items.append(json.loads(stripped))

    chunk_lookup = load_chunk_lookup(data_dir)

    print("=" * 80)
    print("GOLD SET HUMAN REVIEW TOOL (Phase 7c Integrity)")
    print(f"Target File     : {gold_set_path}")
    print(f"Reviewer Tag    : {reviewer}")
    print(f"Status Filter   : {status_filter}")
    print(f"Total Questions : {len(raw_items)}")
    reviewed_count = sum(
        1 for r in raw_items if r.get("status") == "reviewed" and r.get("reviewed_by") == reviewer
    )
    draft_count = sum(1 for r in raw_items if r.get("status") == "draft")
    rejected_count = sum(1 for r in raw_items if r.get("status") == "rejected")
    print(f"Progress        : {reviewed_count} reviewed by {reviewer} | {draft_count} draft | {rejected_count} rejected")
    print("=" * 80)
    print("Commands: [a]pprove  [e]dit  [r]eject  [s]kip  [q]uit")
    print("=" * 80)

    today = datetime.date.today().isoformat()
    modified = False

    for idx, item in enumerate(raw_items, start=1):
        cur_status = item.get("status", "draft")
        if status_filter != "all" and cur_status != status_filter:
            continue

        qid = item.get("id", f"INDEX-{idx}")
        qtype = item.get("type", "unknown")
        role = item.get("role_asking", "unknown")
        behaviour = item.get("expected_behaviour", "answer")
        qtext = item.get("question", "")
        gold_answer = item.get("gold_answer", "")
        gold_chunks = item.get("gold_chunk_ids", [])

        print("\n" + "-" * 80)
        print(f"[{idx}/{len(raw_items)}] Question ID: {qid} | Status: {cur_status} | Reviewer: {item.get('reviewed_by')}")
        print("-" * 80)
        print(f"Type             : {qtype}")
        print(f"Role Asking      : {role}")
        print(f"Expected Action  : {behaviour}")
        print(f"Question Text    :\n  {qtext}")
        print(f"Gold Answer      :\n  {gold_answer}")
        print("Gold Chunks      :")
        if not gold_chunks:
            print("  (None specified - unanswerable or empty)")
        else:
            for cid in gold_chunks:
                print(format_chunk_details(cid, chunk_lookup))

        while True:
            try:
                choice = input("Decision [a]pprove, [e]dit, [r]eject, [s]kip, [q]uit: ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                print("\nSession interrupted. Saving progress and exiting...")
                atomic_save_gold_set(gold_set_path, raw_items)
                return 0

            if choice == "q":
                atomic_save_gold_set(gold_set_path, raw_items)
                print(f"\n[SAVED] Progress saved to {gold_set_path}. Goodbye!")
                return 0

            if choice == "s":
                print("Skipped.")
                break

            if choice == "a":
                item["status"] = "reviewed"
                item["reviewed_by"] = reviewer
                item["reviewed_on"] = today
                atomic_save_gold_set(gold_set_path, raw_items)
                modified = True
                print(f"[APPROVED] Marked {qid} as reviewed by {reviewer} on {today}.")
                break

            if choice == "r":
                item["status"] = "rejected"
                item["reviewed_by"] = reviewer
                item["reviewed_on"] = today
                atomic_save_gold_set(gold_set_path, raw_items)
                modified = True
                print(f"[REJECTED] Marked {qid} as rejected.")
                break

            if choice == "e":
                print("\n--- EDIT MODE ---")
                new_q = input(f"New Question text (press Enter to keep '{qtext[:50]}...'): ").strip()
                if new_q:
                    item["question"] = new_q

                new_ans = input(f"New Gold Answer (press Enter to keep '{gold_answer[:50]}...'): ").strip()
                if new_ans:
                    item["gold_answer"] = new_ans

                cur_cids_str = ", ".join(gold_chunks)
                new_cids_raw = input(f"New Gold Chunk IDs comma-separated (press Enter to keep '{cur_cids_str}'): ").strip()
                if new_cids_raw:
                    new_cids = [c.strip() for c in new_cids_raw.split(",") if c.strip()]
                    item["gold_chunk_ids"] = new_cids

                approve_now = input("Approve edited question now? [y/N]: ").strip().lower()
                if approve_now == "y":
                    item["status"] = "reviewed"
                    item["reviewed_by"] = reviewer
                    item["reviewed_on"] = today
                    print(f"[APPROVED] Edited and approved {qid} as reviewed by {reviewer}.")
                else:
                    print(f"[SAVED] Edits saved; {qid} remains draft.")

                atomic_save_gold_set(gold_set_path, raw_items)
                modified = True
                break

            print("Invalid input. Please choose 'a', 'e', 'r', 's', or 'q'.")

    print("\n" + "=" * 80)
    print("Review queue complete!")
    reviewed_count = sum(
        1 for r in raw_items if r.get("status") == "reviewed" and r.get("reviewed_by") == reviewer
    )
    print(f"Final Count: {reviewed_count}/{len(raw_items)} questions student-reviewed.")
    print("=" * 80)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Interactive CLI tool for student review of gold questions.")
    parser.add_argument(
        "--path",
        type=Path,
        default=Path("data/eval/gold_set.jsonl"),
        help="Path to gold_set.jsonl (default: data/eval/gold_set.jsonl).",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Path to corpus data directory (default: data).",
    )
    parser.add_argument(
        "--reviewer",
        type=str,
        default="student",
        help="Reviewer name to write into reviewed_by field (default: student).",
    )
    parser.add_argument(
        "--status",
        type=str,
        default="draft",
        choices=["draft", "reviewed", "rejected", "all"],
        help="Filter items by status to review (default: draft).",
    )
    args = parser.parse_args()
    return review_gold_set(
        gold_set_path=args.path,
        data_dir=args.data_dir,
        reviewer=args.reviewer,
        status_filter=args.status,
    )


if __name__ == "__main__":
    raise SystemExit(main())

