"""Corpus Manifest & Sidecar Validator CLI.

Scans ``data/raw`` and ``data/synthetic``, computes chunk counts, validates sidecar
metadata completeness (source URL, licence, allowed roles), and prints a formatted
table. Fails (exit code 1) if any document lacks required metadata.

Supports ``--add-template`` to generate boilerplate ``.meta.json`` sidecars for new files.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.security import VALID_ROLES
from src.ingestion.chunker import ClauseAwareChunker
from src.ingestion.loaders import DocumentLoader
from src.ingestion.run import discover_documents

REQUIRED_FIELDS = ("source", "licence", "allowed_roles")


def get_sidecar_path(doc_path: Path) -> Path:
    """Return the primary .meta.json path for a document file."""
    return doc_path.with_name(f"{doc_path.name}.meta.json")


def inspect_document(
    doc_path: Path,
    chunker: ClauseAwareChunker,
) -> dict[str, Any]:
    """Inspect one document file, chunk it, and validate its sidecar metadata."""
    sidecar_path = get_sidecar_path(doc_path)
    stem_sidecar = doc_path.with_suffix(".meta.json")
    sidecar_exists = sidecar_path.is_file() or stem_sidecar.is_file()
    active_sidecar = sidecar_path if sidecar_path.is_file() else (stem_sidecar if stem_sidecar.is_file() else sidecar_path)

    sidecar_data: dict[str, Any] = {}
    sidecar_error = None
    if sidecar_exists:
        try:
            sidecar_data = json.loads(active_sidecar.read_text(encoding="utf-8"))
        except Exception as exc:
            sidecar_error = f"Invalid JSON: {exc}"

    # Load via DocumentLoader (merges header and sidecar)
    try:
        doc = DocumentLoader.load(doc_path)
        chunks = chunker.chunk_document(doc)
        chunk_count = len(chunks)
    except Exception as exc:
        chunk_count = 0
        doc = None

    # Check required fields
    source = sidecar_data.get("source") or sidecar_data.get("source_url") or ""
    licence = sidecar_data.get("licence") or sidecar_data.get("license") or ""
    allowed_roles = sidecar_data.get("allowed_roles")

    missing = []
    if not source:
        missing.append("source")
    if not licence:
        missing.append("licence")
    if not allowed_roles or not isinstance(allowed_roles, list):
        missing.append("allowed_roles")
    elif not all(r in VALID_ROLES for r in allowed_roles):
        missing.append("invalid_role")

    is_complete = sidecar_exists and not missing and not sidecar_error

    return {
        "file_name": doc_path.name,
        "folder": doc_path.parent.name,
        "path": doc_path,
        "sidecar_path": active_sidecar,
        "sidecar_exists": sidecar_exists,
        "title": (doc.title if doc else doc_path.stem) or "",
        "doc_id": (doc.doc_id if doc else f"DOC-{doc_path.stem.upper()}"),
        "source": source,
        "licence": licence,
        "allowed_roles": allowed_roles if isinstance(allowed_roles, list) else [],
        "chunk_count": chunk_count,
        "missing_fields": missing,
        "sidecar_error": sidecar_error,
        "is_complete": is_complete,
    }


def add_template_sidecar(doc_path: Path) -> Path:
    """Write a template .meta.json for a document lacking one."""
    sidecar_path = get_sidecar_path(doc_path)
    if sidecar_path.is_file():
        return sidecar_path

    is_synthetic = "synthetic" in doc_path.parent.name.lower()
    template = {
        "doc_id": f"DOC-{doc_path.stem.upper()}",
        "title": doc_path.stem.replace("-", " ").title(),
        "allowed_roles": ["analyst", "manager", "auditor"] if not is_synthetic else ["manager", "auditor"],
        "doc_type": "INTERNAL_POLICY" if is_synthetic else "PUBLIC_REGULATION",
        "jurisdiction": "INTERNAL_SYNTHETIC" if is_synthetic else "UK_FCA",
        "version": "1.0",
        "source": "SYNTHETIC_DATASET (Describe origin)" if is_synthetic else "https://example.com/regulatory/source",
        "licence": "Educational / Academic Final Year Project (BSc COM6301)" if is_synthetic else "Open Government Licence v3.0 (UK OGL)",
    }
    sidecar_path.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
    return sidecar_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit corpus manifest, metadata sidecars, and chunk counts.")
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Root data directory containing raw/ and synthetic/ (default: data).",
    )
    parser.add_argument(
        "--add-template",
        action="store_true",
        help="Write boilerplate .meta.json next to any document file lacking one.",
    )
    args = parser.parse_args()

    doc_paths = discover_documents(args.data_dir)
    if not doc_paths:
        print(f"ERROR: No documents found in '{args.data_dir}'.")
        return 1

    if args.add_template:
        created_count = 0
        for p in doc_paths:
            s_path = get_sidecar_path(p)
            stem_s = p.with_suffix(".meta.json")
            if not s_path.is_file() and not stem_s.is_file():
                add_template_sidecar(p)
                created_count += 1
                print(f"[TEMPLATE CREATED] {s_path}")
        if created_count == 0:
            print("[TEMPLATE] All documents already have sidecars.")

    chunker = ClauseAwareChunker()
    records = [inspect_document(p, chunker) for p in doc_paths]

    total_docs = len(records)
    total_chunks = sum(r["chunk_count"] for r in records)
    invalid_docs = [r for r in records if not r["is_complete"]]

    print("=" * 110)
    print("CORPUS MANIFEST & SIDECAR AUDIT")
    print(f"Total Documents: {total_docs} | Total Chunks: {total_chunks}")
    print("=" * 110)
    fmt = "{:<32} {:<10} {:<24} {:<20} {:<20} {:>6} {:<12}"
    print(fmt.format("Document File", "Folder", "Licence", "Roles", "Source (truncated)", "Chunks", "Sidecar Status"))
    print("-" * 110)

    for r in records:
        roles_str = ",".join(r["allowed_roles"]) if r["allowed_roles"] else "NONE"
        status_str = "OK" if r["is_complete"] else f"MISSING:{','.join(r['missing_fields'])}"
        src_trunc = (r["source"][:18] + "..") if len(r["source"]) > 20 else r["source"]
        lic_trunc = (r["licence"][:22] + "..") if len(r["licence"]) > 24 else r["licence"]
        print(fmt.format(
            r["file_name"][:30],
            r["folder"],
            lic_trunc,
            roles_str[:18],
            src_trunc,
            r["chunk_count"],
            status_str,
        ))

    print("=" * 110)
    if invalid_docs:
        print(f"\n[FAIL] {len(invalid_docs)} document(s) have incomplete or missing sidecars:")
        for inv in invalid_docs:
            print(f"  - {inv['file_name']} in {inv['folder']}: missing {inv['missing_fields']}")
            if inv["sidecar_error"]:
                print(f"    Sidecar error: {inv['sidecar_error']}")
        print("\nFix missing sidecars or run with `--add-template` to scaffold boilerplate sidecars.")
        return 1

    print("\n[PASS] All documents have valid sidecars with source, licence, and allowed_roles.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

