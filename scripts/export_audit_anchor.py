#!/usr/bin/env python3
"""Audit anchor export tool.

Exports the current head hash and chain height of the SQLite audit_log table
into a timestamped anchor file in reports/ (and reports/audit_anchor_latest.json).

An external audit anchor provides tamper-evidence against an attacker with direct
SQL database write access who might otherwise recompute the entire hash chain.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.verify_audit import verify_audit_chain
from src.core.audit_chain import GENESIS_PREV_HASH


def export_audit_anchor(
    db_path: Path = Path("data/sqlite/app.db"),
    output_dir: Path = Path("reports"),
) -> tuple[Path, dict]:
    """Export the head hash and height of the audit chain to an anchor file.

    Returns:
        (anchor_path, anchor_payload)
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database file not found: {db_path}")

    # 1. Verify internal chain integrity before anchoring
    valid, msg, details = verify_audit_chain(db_path)
    if not valid:
        raise ValueError(f"Cannot export anchor: audit chain is invalid! {msg}")

    # 2. Extract head metadata
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) as cnt FROM audit_log;")
        row_count = cur.fetchone()["cnt"]

        if row_count == 0:
            head_id = None
            head_hash = GENESIS_PREV_HASH
            prev_hash = GENESIS_PREV_HASH
            timestamp_val = None
        else:
            cur.execute("SELECT id, created_at, prev_hash, entry_hash FROM audit_log ORDER BY id DESC LIMIT 1;")
            head_row = cur.fetchone()
            head_id = head_row["id"]
            head_hash = head_row["entry_hash"]
            prev_hash = head_row["prev_hash"]
            timestamp_val = head_row["created_at"]
    finally:
        conn.close()

    now_utc = datetime.now(timezone.utc)
    ts_str = now_utc.strftime("%Y%m%d_%H%M%S")

    anchor_payload = {
        "schema_version": "1.0",
        "exported_at": now_utc.isoformat(),
        "database_file": str(db_path),
        "total_entries": row_count,
        "head_id": head_id,
        "head_hash": head_hash,
        "prev_hash": prev_hash,
        "last_entry_timestamp": timestamp_val,
        "genesis_hash": GENESIS_PREV_HASH,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamped_file = output_dir / f"audit_anchor_{ts_str}.json"
    latest_file = output_dir / "audit_anchor_latest.json"

    with open(timestamped_file, "w", encoding="utf-8") as f:
        json.dump(anchor_payload, f, indent=2)

    with open(latest_file, "w", encoding="utf-8") as f:
        json.dump(anchor_payload, f, indent=2)

    return timestamped_file, anchor_payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Export head hash anchor of audit log chain.")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/sqlite/app.db"),
        help="Path to SQLite database (default: data/sqlite/app.db)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("reports"),
        help="Directory to save anchor JSON files (default: reports)",
    )
    args = parser.parse_args()

    try:
        path, payload = export_audit_anchor(args.db, args.output_dir)
        print(f"[OK] Audit anchor exported successfully:")
        print(f"     Path:         {path}")
        print(f"     Latest link:  {args.output_dir / 'audit_anchor_latest.json'}")
        print(f"     Head ID:      {payload['head_id']}")
        print(f"     Total Rows:   {payload['total_entries']}")
        print(f"     Head Hash:    {payload['head_hash']}")
        return 0
    except Exception as e:
        print(f"[FAIL] Error exporting audit anchor: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
