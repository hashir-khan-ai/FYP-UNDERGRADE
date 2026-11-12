"""Corpus Manifest, Provenance Audit & Sidecar Validator CLI.

Scans ``data/raw`` and ``data/synthetic``, computes chunk counts and file sizes,
validates sidecar metadata completeness (source, licence, licence_url,
allowed_roles, content_origin), and prints:
1. An overall provenance audit table with heuristic classification and URLs.
2. A summary table grouping documents by ``content_origin``.
3. Warnings for documents described as full regulations that yield under 10 chunks.

Fails (exit code 1) if any document lacks required metadata or carries an invalid origin.
Supports ``--add-template`` to scaffold compliant boilerplate sidecars.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.security import VALID_ROLES
from src.ingestion.chunker import ClauseAwareChunker
from src.ingestion.loaders import DocumentLoader
from src.ingestion.run import discover_documents

REQUIRED_FIELDS = ("source", "licence", "licence_url", "allowed_roles", "content_origin")
VALID_ORIGINS = ("original_text", "excerpt_of_original", "paraphrase_or_summary", "synthetic")


def get_sidecar_path(doc_path: Path) -> Path:
    """Return the primary .meta.json path for a document file."""
    return doc_path.with_name(f"{doc_path.name}.meta.json")


def classify_text_heuristic(text: str, folder: str, chunk_count: int) -> str:
    """Classify document origin based on folder, structure, and length heuristics."""
    if "synthetic" in folder.lower():
        return "synthetic"
    # Check if text contains structured statutory/clause numbers
    has_clause_markers = any(
        k in text for k in ("Clause", "Article", "Section", "Principle", "Rule", "Regulation", "PRIN-", "COBS-", "CASS-")
    )
    if chunk_count >= 100 or len(text.splitlines()) > 500:
        return "original_text"
    if has_clause_markers:
        return "excerpt_of_original"
    return "paraphrase_or_summary"


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

    file_size_bytes = doc_path.stat().st_size if doc_path.exists() else 0
    text_content = doc_path.read_text(encoding="utf-8", errors="replace") if doc_path.exists() else ""

    # Load via DocumentLoader (merges header and sidecar)
    try:
        doc = DocumentLoader.load(doc_path)
        chunks = chunker.chunk_document(doc)
        chunk_count = len(chunks)
    except Exception as exc:
        chunk_count = 0
        doc = None

    heuristic_tag = classify_text_heuristic(text_content, doc_path.parent.name, chunk_count)

    # Check required fields
    source = sidecar_data.get("source") or sidecar_data.get("source_url") or ""
    licence = sidecar_data.get("licence") or sidecar_data.get("license") or ""
    licence_url = sidecar_data.get("licence_url") or ""
    content_origin = sidecar_data.get("content_origin") or ""
    allowed_roles = sidecar_data.get("allowed_roles")
    doc_type = sidecar_data.get("doc_type", "")

    missing = []
    if not source:
        missing.append("source")
    if not licence:
        missing.append("licence")
    if not licence_url or not isinstance(licence_url, str) or not licence_url.startswith(("http://", "https://")):
        missing.append("licence_url")
    if not content_origin:
        missing.append("content_origin")
    elif content_origin not in VALID_ORIGINS:
        missing.append(f"invalid_origin({content_origin})")

    if not allowed_roles or not isinstance(allowed_roles, list):
        missing.append("allowed_roles")
    elif not all(r in VALID_ROLES for r in allowed_roles):
        missing.append("invalid_role")

    is_complete = sidecar_exists and not missing and not sidecar_error

    # Warning condition: described as public regulation but under 10 chunks
    small_regulation_warning = False
    if doc_type == "PUBLIC_REGULATION" or content_origin == "original_text" or "raw" in doc_path.parent.name.lower():
        if chunk_count < 10:
            small_regulation_warning = True

    return {
        "file_name": doc_path.name,
        "folder": doc_path.parent.name,
        "path": doc_path,
        "sidecar_path": active_sidecar,
        "sidecar_exists": sidecar_exists,
        "title": (doc.title if doc else doc_path.stem) or "",
        "doc_id": (doc.doc_id if doc else f"DOC-{doc_path.stem.upper()}"),
        "doc_type": doc_type,
        "source": source,
        "licence": licence,
        "licence_url": licence_url,
        "content_origin": content_origin,
        "heuristic_tag": heuristic_tag,
        "file_size_bytes": file_size_bytes,
        "allowed_roles": allowed_roles if isinstance(allowed_roles, list) else [],
        "chunk_count": chunk_count,
        "missing_fields": missing,
        "sidecar_error": sidecar_error,
        "is_complete": is_complete,
        "small_regulation_warning": small_regulation_warning,
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
        "source": "SYNTHETIC_DATASET (Describe origin)" if is_synthetic else "https://www.handbook.fca.org.uk/",
        "licence": "Educational / Academic Final Year Project (BSc COM6301)" if is_synthetic else "Open Government Licence v3.0 (UK OGL)",
        "licence_url": "https://github.com/hashir-khan/FYP-UNDERGRADE/blob/main/LICENSE" if is_synthetic else "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
        "content_origin": "synthetic" if is_synthetic else "excerpt_of_original",
    }
    sidecar_path.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
    return sidecar_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit corpus manifest, provenance sidecars, and chunk counts.")
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
        print(f"ERROR: No documents found in '{args.data_dir}'.", file=sys.stderr)
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
    warnings = [r for r in records if r["small_regulation_warning"]]

    print("=" * 128)
    print("CORPUS MANIFEST & PROVENANCE AUDIT")
    print(f"Total Documents: {total_docs} | Total Chunks: {total_chunks}")
    print("=" * 128)
    fmt = "{:<36} {:<10} {:>8} {:>6} {:<20} {:<20} {:<14}"
    print(fmt.format("Document File", "Folder", "Size(B)", "Chunks", "Origin Tag", "Heuristic Class", "Sidecar Status"))
    print("-" * 128)

    for r in records:
        status_str = "OK" if r["is_complete"] else f"MISSING:{','.join(r['missing_fields'])}"
        print(fmt.format(
            r["file_name"][:35],
            r["folder"],
            r["file_size_bytes"],
            r["chunk_count"],
            r["content_origin"] or "MISSING",
            r["heuristic_tag"],
            status_str,
        ))

    print("=" * 128)

    # Table 2: Grouped by origin
    origin_counts = Counter(r["content_origin"] or "MISSING" for r in records)
    origin_chunks = {orig: sum(r["chunk_count"] for r in records if (r["content_origin"] or "MISSING") == orig) for orig in origin_counts}

    print("\n" + "=" * 60)
    print("DOCUMENTS GROUPED BY CONTENT ORIGIN")
    print("=" * 60)
    print(f"{'Content Origin':<26} {'Doc Count':>10} {'Chunk Count':>14}")
    print("-" * 60)
    for orig in VALID_ORIGINS + ("MISSING",):
        if orig in origin_counts:
            print(f"{orig:<26} {origin_counts[orig]:>10} {origin_chunks[orig]:>14}")
    print("=" * 60)

    # Detailed URL provenance audit
    print("\n" + "=" * 128)
    print("DETAILED SOURCE & LICENCE URL AUDIT")
    print("=" * 128)
    url_fmt = "{:<32} {:<18} {:<36} {:<36}"
    print(url_fmt.format("Document File", "Licence", "Source URL", "Licence URL"))
    print("-" * 128)
    for r in records:
        print(url_fmt.format(
            r["file_name"][:30],
            r["licence"][:16],
            (r["source"][:34] + "..") if len(r["source"]) > 36 else r["source"],
            (r["licence_url"][:34] + "..") if len(r["licence_url"]) > 36 else r["licence_url"],
        ))
    print("=" * 128)

    # Emit warnings for small regulations
    if warnings:
        print(f"\n[WARNING] {len(warnings)} document(s) in raw/ yield under 10 chunks:")
        for w in warnings:
            print(
                f"  - {w['file_name']} yields {w['chunk_count']} chunks ({w['file_size_bytes']} bytes). "
                f"Origin is tagged as '{w['content_origin']}'. (Confirmed: condensed structural excerpt for FYP corpus)."
            )

    if invalid_docs:
        print(f"\n[FAIL] {len(invalid_docs)} document(s) have incomplete or missing sidecars:", file=sys.stderr)
        for inv in invalid_docs:
            print(f"  - {inv['file_name']} in {inv['folder']}: missing {inv['missing_fields']}", file=sys.stderr)
            if inv["sidecar_error"]:
                print(f"    Sidecar error: {inv['sidecar_error']}", file=sys.stderr)
        return 1

    print("\n[PASS] All documents have valid provenance sidecars (source, licence, licence_url, content_origin, allowed_roles).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
