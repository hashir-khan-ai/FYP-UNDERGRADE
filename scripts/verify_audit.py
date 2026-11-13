#!/usr/bin/env python3
"""Audit log hash-chain verification tool.

Verifies the cryptographic integrity of the SQLite audit_log table.
Detects row modification (tampering), deletion, or out-of-order insertion.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.audit_chain import AUDIT_HASH_COLUMNS, GENESIS_PREV_HASH, compute_audit_hash


def verify_audit_chain(
    db_source: str | Path | sqlite3.Connection,
    anchor: str | Path | dict[str, Any] | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """Verify the hash chain of the audit_log table, optionally against an external anchor.

    Args:
        db_source: Path to SQLite DB or active sqlite3.Connection
        anchor: Optional path to anchor JSON file or anchor dict

    Returns:
        (is_valid, message, details)
    """
    should_close = False
    if isinstance(db_source, (str, Path)):
        db_path = Path(db_source)
        if not db_path.exists():
            return False, f"Database file not found: {db_path}", {"total": 0}
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        should_close = True
    else:
        conn = db_source
        if conn.row_factory is None:
            conn.row_factory = sqlite3.Row

    try:
        cur = conn.cursor()
        # Check if audit_log table exists
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_log';"
        )
        if not cur.fetchone():
            return True, "No audit_log table found (clean/empty database).", {"total": 0}

        # Check required columns
        cur.execute("PRAGMA table_info(audit_log);")
        columns = {row["name"] for row in cur.fetchall()}
        if "prev_hash" not in columns or "entry_hash" not in columns:
            return False, "Missing prev_hash or entry_hash columns in audit_log.", {"total": 0}

        cur.execute("SELECT * FROM audit_log ORDER BY id ASC;")
        rows = cur.fetchall()
        total_rows = len(rows)

        if total_rows == 0:
            if anchor:
                anchor_dict = _load_anchor(anchor)
                if anchor_dict and anchor_dict.get("total_entries", 0) > 0:
                    return (
                        False,
                        f"Anchor mismatch: database is empty (0 entries) but anchor specifies {anchor_dict.get('total_entries')} entries.",
                        {"total": 0, "anchor_expected": anchor_dict.get("total_entries")},
                    )
            return True, "Audit log is empty (0 entries). Chain is trivially valid.", {"total": 0}

        expected_prev_hash = GENESIS_PREV_HASH

        for idx, row in enumerate(rows):
            row_id = row["id"]
            actual_prev = row["prev_hash"]
            actual_entry = row["entry_hash"]

            # 1. Verify prev_hash matches prior entry's entry_hash
            if actual_prev != expected_prev_hash:
                return (
                    False,
                    f"Chain broken at row id={row_id} (index {idx}): "
                    f"expected prev_hash '{expected_prev_hash}', got '{actual_prev}'. "
                    f"(Indicates row deletion, insertion, or reordering)",
                    {"broken_at_id": row_id, "broken_index": idx, "total": total_rows},
                )

            # 2. Recompute hash from row values
            values = tuple(row[col] for col in AUDIT_HASH_COLUMNS)
            recomputed = compute_audit_hash(actual_prev, values)

            if recomputed != actual_entry:
                return (
                    False,
                    f"Hash mismatch at row id={row_id} (index {idx}): "
                    f"recorded entry_hash '{actual_entry}', recomputed '{recomputed}'. "
                    f"(Indicates row data modification / tampering)",
                    {"tampered_id": row_id, "tampered_index": idx, "total": total_rows},
                )

            expected_prev_hash = actual_entry

        details: dict[str, Any] = {"total": total_rows, "latest_hash": expected_prev_hash}

        # 3. Verify against external anchor if provided
        if anchor:
            anchor_dict = _load_anchor(anchor)
            if not anchor_dict:
                return False, f"Failed to parse or load anchor from {anchor}", details

            anchored_total = anchor_dict.get("total_entries", 0)
            anchored_head_id = anchor_dict.get("head_id")
            anchored_head_hash = anchor_dict.get("head_hash")

            if total_rows < anchored_total:
                return (
                    False,
                    f"Anchor check failed: current DB has {total_rows} entries, fewer than anchored height {anchored_total} (indicates rollback or truncation).",
                    details,
                )

            if anchored_head_id is not None:
                cur.execute("SELECT entry_hash FROM audit_log WHERE id = ?;", (anchored_head_id,))
                found = cur.fetchone()
                if not found:
                    return (
                        False,
                        f"Anchor check failed: anchored row id={anchored_head_id} not found in database.",
                        details,
                    )
                if found["entry_hash"] != anchored_head_hash:
                    return (
                        False,
                        f"Anchor mismatch at row id={anchored_head_id}: database entry_hash is '{found['entry_hash']}', expected '{anchored_head_hash}'. (Indicates chain recomputation / history rewrite)",
                        details,
                    )
            elif anchored_head_hash != GENESIS_PREV_HASH:
                return (
                    False,
                    f"Anchor check failed: anchor specifies head_hash '{anchored_head_hash}' with no head_id.",
                    details,
                )

            details["anchor_verified"] = True
            details["anchored_head_hash"] = anchored_head_hash
            details["anchored_head_id"] = anchored_head_id

            return (
                True,
                f"Audit chain intact and verified against external anchor: {total_rows} entries verified. "
                f"Anchor (id={anchored_head_id}, hash={anchored_head_hash[:12]}...) matched. "
                f"Latest head: {expected_prev_hash[:12]}...",
                details,
            )

        return (
            True,
            f"Audit chain intact: {total_rows} entries verified. "
            f"Genesis -> Latest: {expected_prev_hash[:12]}...",
            details,
        )
    finally:
        if should_close:
            conn.close()


def _load_anchor(anchor_source: str | Path | dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(anchor_source, dict):
        return anchor_source
    anchor_path = Path(anchor_source)
    if not anchor_path.exists():
        return None
    try:
        with open(anchor_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify SQLite audit log hash chain integrity.")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/sqlite/app.db"),
        help="Path to SQLite database file (default: data/sqlite/app.db)",
    )
    parser.add_argument(
        "--anchor",
        type=Path,
        default=None,
        help="Optional path to external anchor JSON file (e.g. reports/audit_anchor_latest.json)",
    )
    args = parser.parse_args()

    valid, message, details = verify_audit_chain(args.db, anchor=args.anchor)
    if valid:
        print(f"[OK] {message}")
        return 0
    else:
        print(f"[FAIL] {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
