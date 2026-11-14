"""Corpus manifest and index/ACL version computation for cache partitioning.

CRITICAL SECURITY CONTRACT:
Cached LLM answers must be strictly invalidated whenever the corpus, document
permissions, or access control lists (ACLs) change. If an administrator or auditor
revokes a role from a document, or re-indexes the corpus, previously cached answers
must immediately become unreachable to prevent unauthorized information disclosure.

The index/ACL version is a deterministic SHA-256 hash computed over:
1. All registered document IDs and their permitted roles (sorted deterministically).
2. Document catalog version and total chunk counts.
3. Physical BM25 index state / timestamp.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from src.config import settings

logger = logging.getLogger(__name__)


def compute_index_acl_version(conn: sqlite3.Connection | None = None) -> str:
    """Compute the deterministic SHA-256 hash of the current corpus ACL manifest.

    Args:
        conn: Optional SQLite connection to use. If omitted, opens a read-only connection
              if the database file exists, or falls back to synthetic sidecars.

    Returns:
        Hexadecimal SHA-256 digest representing the active index/ACL version.
    """
    manifest_items: list[dict[str, Any]] = []

    # 1. Inspect registered documents in SQLite database
    db_path = Path(getattr(settings, "DATABASE_PATH", getattr(settings, "DB_PATH", "./data/sqlite/app.db")))
    if db_path.exists() or conn is not None:
        try:
            should_close = False
            if conn is None:
                db_conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
                should_close = True
            else:
                db_conn = conn

            try:
                cur = db_conn.cursor()
                cur.execute(
                    "SELECT id, filename, allowed_roles, version, total_chunks "
                    "FROM documents ORDER BY id ASC;"
                )
                rows = cur.fetchall()
                for row in rows:
                    roles = row[2]
                    if isinstance(roles, str):
                        try:
                            roles = json.loads(roles)
                        except Exception:
                            roles = [r.strip() for r in roles.split(",") if r.strip()]
                    sorted_roles = sorted(roles) if isinstance(roles, list) else []
                    manifest_items.append(
                        {
                            "id": str(row[0]),
                            "filename": str(row[1]),
                            "allowed_roles": sorted_roles,
                            "version": str(row[3]),
                            "chunks": int(row[4] or 0),
                        }
                    )
            finally:
                if should_close:
                    db_conn.close()
        except Exception as exc:
            logger.debug("Database read during ACL version calculation skipped (%s).", exc)

    # 2. If database had no documents, inspect synthetic/upload sidecars on disk
    if not manifest_items:
        synthetic_dir = Path("./data/synthetic")
        if synthetic_dir.exists():
            for meta_path in sorted(synthetic_dir.glob("*.meta.json")):
                try:
                    data = json.loads(meta_path.read_text(encoding="utf-8"))
                    roles = data.get("allowed_roles") or []
                    manifest_items.append(
                        {
                            "id": data.get("document_id", meta_path.stem),
                            "filename": meta_path.name,
                            "allowed_roles": sorted(roles),
                            "version": data.get("version", "1.0"),
                            "chunks": 0,
                        }
                    )
                except Exception:
                    continue

    # 3. Include BM25 index file state if present
    bm25_state = ""
    bm25_path = Path(settings.BM25_INDEX_PATH)
    if bm25_path.exists():
        try:
            stat = bm25_path.stat()
            bm25_state = f"{stat.st_size}_{int(stat.st_mtime)}"
        except OSError:
            pass

    # 4. Deterministic serialization and hashing
    canonical_payload = {
        "manifest": manifest_items,
        "bm25_state": bm25_state,
        "role_model_version": "v1.0",
    }
    raw_bytes = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw_bytes).hexdigest()[:32]
