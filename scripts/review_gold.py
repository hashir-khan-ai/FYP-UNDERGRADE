"""Offline zero-dependency HTML gold-set review generator.

Generates ``reports/gold_review.html`` for fast single-item human verification
over a ``file://`` URL with no network server or external assets required.

Strictly presents gold questions, expected answers, and full verbatim source
clause text (never system answers or pipeline predictions), tracks a stratified
60-item minimum review queue (30 ``original_100`` + 20 ``agent_extra_40`` + 10
``unanswerable/role-boundary``), persists in ``localStorage``, and exports
decisions to ``gold_review_decisions.json`` for ``scripts/apply_review.py``.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.gold_set import GoldQuestionItem, load_gold_set, load_indexed_chunks  # noqa: E402
from src.ingestion.chunker import ClauseAwareChunker  # noqa: E402
from src.ingestion.loaders import DocumentLoader  # noqa: E402

TARGET_ORIGINAL_COUNT = 30
TARGET_EXTRA_COUNT = 20
TARGET_BOUNDARY_COUNT = 10
TARGET_TOTAL_COUNT = TARGET_ORIGINAL_COUNT + TARGET_EXTRA_COUNT + TARGET_BOUNDARY_COUNT


def load_clause_lookup(bm25_path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Load chunk metadata keyed by ``chunk_id`` from the BM25 index and corpus files."""
    lookup: dict[str, dict[str, Any]] = {}
    for chunk in load_indexed_chunks(bm25_path):
        chunk_id = str(chunk.get("chunk_id", "")).strip()
        if chunk_id:
            lookup[chunk_id] = chunk

    chunker = ClauseAwareChunker()
    for folder in (PROJECT_ROOT / "data" / "raw", PROJECT_ROOT / "data" / "synthetic"):
        if not folder.exists():
            continue
        for md_path in sorted(folder.glob("*.md")):
            try:
                loaded_doc = DocumentLoader.load(md_path)
                parsed = chunker.chunk_document(loaded_doc)
            except Exception:
                continue
            for chunk in parsed:
                if chunk.chunk_id not in lookup:
                    lookup[chunk.chunk_id] = dataclasses.asdict(chunk)
    return lookup


def load_sheet_metadata(csv_path: str | Path) -> dict[str, dict[str, str]]:
    """Read ``data/gold_review_sheet.csv`` rows keyed by question ``id``."""
    path = Path(csv_path)
    if not path.exists():
        return {}
    metadata: dict[str, dict[str, str]] = {}
    with open(path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            qid = (row.get("id") or "").strip()
            if qid:
                metadata[qid] = {k: (v or "").strip() for k, v in row.items() if k is not None}
    return metadata


def resolve_difficulty(item: GoldQuestionItem, sheet_row: dict[str, str] | None) -> str:
    """Resolve item difficulty from CSV sheet or deterministic heuristics."""
    if sheet_row:
        raw = (sheet_row.get("difficulty") or "").strip().lower()
        if raw in ("easy", "medium", "hard"):
            return raw

    if item.type in ("cross_reference", "multi_part") or len(item.gold_chunk_ids) > 1:
        return "hard"
    if item.type in ("role_restricted", "unanswerable"):
        return "hard" if len(item.unauthorized_keywords) >= 4 else "medium"
    if item.id.startswith("HARD-Q-"):
        return "medium"
    return "easy"


def _interleave_by_key(
    candidates: list[dict[str, Any]],
    limit: int,
    key_fn: Any,
) -> list[dict[str, Any]]:
    """Select up to ``limit`` items evenly across buckets defined by ``key_fn``."""
    if limit <= 0 or not candidates:
        return []
    buckets: dict[Any, list[dict[str, Any]]] = {}
    for rec in candidates:
        buckets.setdefault(key_fn(rec), []).append(rec)

    ordered_keys = sorted(buckets.keys(), key=lambda k: str(k))
    selected: list[dict[str, Any]] = []
    idx = 0
    while len(selected) < limit and any(buckets[k] for k in ordered_keys):
        key = ordered_keys[idx % len(ordered_keys)]
        if buckets[key]:
            selected.append(buckets[key].pop(0))
        idx += 1
    return selected


def build_review_records(
    items: list[GoldQuestionItem],
    clause_lookup: dict[str, dict[str, Any]],
    sheet_meta: dict[str, dict[str, str]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Build enriched review records ordered by stratified 60-item priority then overflow."""
    enriched: list[dict[str, Any]] = []
    for item in items:
        sheet_row = sheet_meta.get(item.id)
        source_subset = "original_100" if item.id.startswith("GS-") else "agent_extra_40"
        is_boundary = item.type in ("unanswerable", "role_restricted") or item.expected_behaviour == "refuse"
        difficulty = resolve_difficulty(item, sheet_row)

        chunk_ids: list[str] = list(item.gold_chunk_ids)
        if item.source_chunk_id and item.source_chunk_id not in chunk_ids:
            chunk_ids.append(item.source_chunk_id)

        clauses: list[dict[str, Any]] = []
        for cid in chunk_ids:
            meta = clause_lookup.get(cid)
            if meta:
                clauses.append(
                    {
                        "chunk_id": cid,
                        "doc_id": meta.get("doc_id", item.gold_doc),
                        "doc_title": meta.get("doc_title", ""),
                        "heading_path": meta.get("heading_path", "") or meta.get("clause_label", ""),
                        "section_label": meta.get("section_label", ""),
                        "clause_label": meta.get("clause_label", ""),
                        "page": meta.get("page"),
                        "allowed_roles": list(meta.get("allowed_roles", [])),
                        "text_content": meta.get("text_content", ""),
                        "missing": False,
                    }
                )
            else:
                clauses.append(
                    {
                        "chunk_id": cid,
                        "doc_id": item.gold_doc,
                        "doc_title": "",
                        "heading_path": item.clause,
                        "section_label": "",
                        "clause_label": item.clause,
                        "page": None,
                        "allowed_roles": [],
                        "text_content": "[Clause text not found in local BM25 index or corpus markdown.]",
                        "missing": True,
                    }
                )

        existing_notes = item.human_notes or (sheet_row.get("human_notes") if sheet_row else "") or ""

        enriched.append(
            {
                "id": item.id,
                "question": item.question,
                "type": item.type,
                "role_asking": item.role_asking,
                "difficulty": difficulty,
                "source_subset": source_subset,
                "is_boundary": is_boundary,
                "expected_behaviour": item.expected_behaviour,
                "gold_doc": item.gold_doc,
                "clause": item.clause,
                "gold_chunk_ids": list(item.gold_chunk_ids),
                "gold_answer": item.gold_answer,
                "unauthorized_keywords": list(item.unauthorized_keywords),
                "existing_human_notes": existing_notes,
                "clauses": clauses,
                "sample_stratum": None,
                "in_default_sample": False,
                "default_order": -1,
            }
        )

    picked_ids: set[str] = set()

    # 1. Stratified 10 unanswerable / role-boundary items: split evenly across GS-* and HARD-Q-*
    boundary_orig_candidates = [
        r
        for r in enriched
        if r["source_subset"] == "original_100"
        and r["is_boundary"]
        and r["expected_behaviour"] == "refuse"
    ] + [
        r
        for r in enriched
        if r["source_subset"] == "original_100"
        and r["is_boundary"]
        and r["expected_behaviour"] != "refuse"
    ]
    boundary_extra_candidates = [
        r
        for r in enriched
        if r["source_subset"] == "agent_extra_40"
        and r["is_boundary"]
        and r["expected_behaviour"] == "refuse"
    ] + [
        r
        for r in enriched
        if r["source_subset"] == "agent_extra_40"
        and r["is_boundary"]
        and r["expected_behaviour"] != "refuse"
    ]

    half_boundary = TARGET_BOUNDARY_COUNT // 2
    picked_boundary = _interleave_by_key(
        boundary_orig_candidates,
        half_boundary,
        lambda r: (r["type"], r["role_asking"]),
    ) + _interleave_by_key(
        boundary_extra_candidates,
        TARGET_BOUNDARY_COUNT - half_boundary,
        lambda r: (r["type"], r["role_asking"]),
    )
    if len(picked_boundary) < TARGET_BOUNDARY_COUNT:
        used_tmp = {r["id"] for r in picked_boundary}
        fallback_boundary = [r for r in enriched if r["is_boundary"] and r["id"] not in used_tmp]
        picked_boundary.extend(fallback_boundary[: TARGET_BOUNDARY_COUNT - len(picked_boundary)])

    for rec in picked_boundary:
        rec["sample_stratum"] = "unanswerable_role_boundary"
        rec["in_default_sample"] = True
        picked_ids.add(rec["id"])

    # 2. Stratified 20 agent_extra_40 items (prefer answerable items first so 10 boundary stays distinct)
    extra_answerable = [
        r
        for r in enriched
        if r["id"] not in picked_ids
        and r["source_subset"] == "agent_extra_40"
        and r["expected_behaviour"] == "answer"
    ]
    picked_extra = _interleave_by_key(
        extra_answerable,
        TARGET_EXTRA_COUNT,
        lambda r: (r["type"], r["difficulty"], r["role_asking"]),
    )
    if len(picked_extra) < TARGET_EXTRA_COUNT:
        used_tmp = picked_ids | {r["id"] for r in picked_extra}
        extra_rest = [
            r for r in enriched if r["id"] not in used_tmp and r["source_subset"] == "agent_extra_40"
        ]
        picked_extra.extend(extra_rest[: TARGET_EXTRA_COUNT - len(picked_extra)])

    for rec in picked_extra:
        rec["sample_stratum"] = "agent_extra_40"
        rec["in_default_sample"] = True
        picked_ids.add(rec["id"])

    # 3. Stratified 30 original_100 items (spread across single_fact, multi_part, cross_reference, difficulty, role)
    orig_primary = [
        r
        for r in enriched
        if r["id"] not in picked_ids
        and r["source_subset"] == "original_100"
        and not r["is_boundary"]
    ]
    picked_orig = _interleave_by_key(
        orig_primary,
        TARGET_ORIGINAL_COUNT,
        lambda r: (r["type"], r["difficulty"], r["role_asking"]),
    )
    if len(picked_orig) < TARGET_ORIGINAL_COUNT:
        used_tmp = picked_ids | {r["id"] for r in picked_orig}
        orig_rest = [
            r for r in enriched if r["id"] not in used_tmp and r["source_subset"] == "original_100"
        ]
        picked_orig.extend(orig_rest[: TARGET_ORIGINAL_COUNT - len(picked_orig)])

    for rec in picked_orig:
        rec["sample_stratum"] = "original_100"
        rec["in_default_sample"] = True
        picked_ids.add(rec["id"])

    # Interleave the 60 target items in balanced 3:2:1 blocks
    sample_ordered: list[dict[str, Any]] = []
    q_orig = list(picked_orig)
    q_extra = list(picked_extra)
    q_bound = list(picked_boundary)
    while q_orig or q_extra or q_bound:
        for _ in range(3):
            if q_orig:
                sample_ordered.append(q_orig.pop(0))
        for _ in range(2):
            if q_extra:
                sample_ordered.append(q_extra.pop(0))
        if q_bound:
            sample_ordered.append(q_bound.pop(0))

    overflow = [r for r in enriched if r["id"] not in picked_ids]
    ordered = sample_ordered + overflow
    for order_idx, rec in enumerate(ordered):
        rec["default_order"] = order_idx

    sample_target_ids = [r["id"] for r in sample_ordered]
    return ordered, sample_target_ids


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Compliance RAG — Offline Gold Set Review</title>
  <style>
    :root {
      --bg-page: #F6F5F1;
      --bg-panel: #ECEAE4;
      --bg-card: #FFFFFF;
      --bg-inset: #FAF9F6;
      --ink-primary: #1C1D20;
      --ink-secondary: #5A6068;
      --ink-muted: #6E737B;
      --accent: #FF5F00;
      --accent-soft: rgba(255, 95, 0, 0.12);
      --border: rgba(28, 29, 32, 0.12);
      --border-strong: rgba(28, 29, 32, 0.24);
      --ok: #15693B;
      --ok-bg: #E8F5EE;
      --warn: #9A4A00;
      --warn-bg: #FFF1E3;
      --bad: #A61B2B;
      --bad-bg: #FDECEE;
      --info: #1D4ED8;
      --info-bg: #EAF1FF;
      --skip: #4B5563;
      --skip-bg: #EEF0F3;
      --radius-sm: 8px;
      --radius-md: 12px;
      --radius-lg: 16px;
      --shadow-card: 0 1px 2px rgba(28, 29, 32, 0.05), 0 8px 24px rgba(28, 29, 32, 0.04);
      --font-sans: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
      --font-mono: ui-monospace, "Cascadia Code", "Fira Code", Consolas, monospace;
    }

    * { box-sizing: border-box; }

    html, body {
      margin: 0;
      padding: 0;
      background: var(--bg-page);
      color: var(--ink-primary);
      font-family: var(--font-sans);
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
    }

    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        transition: none !important;
        animation: none !important;
        scroll-behavior: auto !important;
      }
    }

    button:focus-visible,
    select:focus-visible,
    textarea:focus-visible,
    input:focus-visible {
      outline: 2px solid var(--accent);
      outline-offset: 2px;
    }

    .app-shell {
      max-width: 1460px;
      margin: 0 auto;
      padding: 16px 20px 32px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }

    .topbar {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      box-shadow: var(--shadow-card);
      padding: 14px 18px;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
    }

    .brand-group {
      display: flex;
      flex-direction: column;
      gap: 2px;
    }

    .brand-title {
      font-size: 1.05rem;
      font-weight: 700;
      letter-spacing: -0.015em;
      display: flex;
      align-items: center;
      gap: 8px;
    }

    .brand-dot {
      width: 10px;
      height: 10px;
      border-radius: 999px;
      background: var(--accent);
      display: inline-block;
      flex-shrink: 0;
    }

    .brand-subtitle {
      font-size: 0.8rem;
      color: var(--ink-secondary);
    }

    .quota-strip {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      font-variant-numeric: tabular-nums;
    }

    .quota-pill {
      background: var(--bg-inset);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      padding: 6px 10px;
      font-size: 0.78rem;
      display: flex;
      align-items: center;
      gap: 6px;
    }

    .quota-pill strong {
      font-weight: 700;
      color: var(--ink-primary);
    }

    .quota-pill.primary {
      background: var(--accent-soft);
      border-color: rgba(255, 95, 0, 0.35);
    }

    .quota-pill.complete {
      background: var(--ok-bg);
      border-color: rgba(21, 105, 59, 0.35);
      color: var(--ok);
    }

    .toolbar {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 10px 14px;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }

    .filter-group, .action-group {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
    }

    label.inline-label {
      font-size: 0.76rem;
      font-weight: 600;
      color: var(--ink-secondary);
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }

    select {
      font-family: var(--font-sans);
      font-size: 0.82rem;
      padding: 6px 10px;
      border-radius: var(--radius-sm);
      border: 1px solid var(--border-strong);
      background: var(--bg-card);
      color: var(--ink-primary);
      cursor: pointer;
    }

    .btn {
      font-family: var(--font-sans);
      font-size: 0.82rem;
      font-weight: 600;
      padding: 7px 12px;
      border-radius: var(--radius-sm);
      border: 1px solid var(--border-strong);
      background: var(--bg-card);
      color: var(--ink-primary);
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: background 120ms ease, border-color 120ms ease, transform 80ms ease;
    }

    .btn:hover:not(:disabled) {
      background: var(--bg-panel);
    }

    .btn:disabled {
      opacity: 0.45;
      cursor: not-allowed;
    }

    .btn-accent {
      background: var(--accent);
      border-color: var(--accent);
      color: #FFFFFF;
    }

    .btn-accent:hover:not(:disabled) {
      background: #E05200;
      border-color: #E05200;
    }

    .progress-bar-track {
      height: 5px;
      background: var(--bg-panel);
      border-radius: 999px;
      overflow: hidden;
    }

    .progress-bar-fill {
      height: 100%;
      background: var(--accent);
      width: 0%;
      transition: width 180ms ease;
    }

    .export-reminder {
      background: var(--warn-bg);
      border: 1.5px solid rgba(154, 74, 0, 0.45);
      border-radius: var(--radius-md);
      padding: 10px 14px;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      font-size: 0.84rem;
      font-weight: 600;
      color: var(--warn);
    }

    .export-reminder[hidden] { display: none; }

    .workspace {
      display: grid;
      grid-template-columns: minmax(0, 1.05fr) minmax(0, 0.95fr);
      gap: 16px;
      align-items: start;
    }

    @media (max-width: 960px) {
      .workspace {
        grid-template-columns: 1fr;
      }
    }

    .card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      box-shadow: var(--shadow-card);
      padding: 18px 20px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }

    .nav-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 12px;
    }

    .nav-counter {
      font-size: 0.85rem;
      font-weight: 600;
      font-variant-numeric: tabular-nums;
      color: var(--ink-secondary);
    }

    .badge-row {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      align-items: center;
    }

    .badge {
      font-size: 0.74rem;
      font-weight: 600;
      padding: 3px 9px;
      border-radius: 999px;
      background: var(--bg-panel);
      color: var(--ink-primary);
      border: 1px solid var(--border);
      font-variant-numeric: tabular-nums;
    }

    .badge.id {
      font-family: var(--font-mono);
      background: var(--ink-primary);
      color: #FFFFFF;
      border-color: var(--ink-primary);
    }

    .badge.role { background: var(--info-bg); color: var(--info); border-color: rgba(29, 78, 216, 0.25); }
    .badge.diff-easy { background: var(--ok-bg); color: var(--ok); }
    .badge.diff-medium { background: var(--warn-bg); color: var(--warn); }
    .badge.diff-hard { background: var(--bad-bg); color: var(--bad); }
    .badge.refuse { background: var(--bad-bg); color: var(--bad); }
    .badge.answer { background: var(--ok-bg); color: var(--ok); }
    .badge.stratum { background: var(--accent-soft); color: #9C3A00; border-color: rgba(255, 95, 0, 0.3); }

    .status-banner {
      padding: 8px 12px;
      border-radius: var(--radius-sm);
      font-size: 0.82rem;
      font-weight: 600;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      border: 1px solid var(--border);
    }
    .status-banner.status-undecided { background: var(--bg-inset); color: var(--ink-secondary); }
    .status-banner.status-approved { background: var(--ok-bg); color: var(--ok); border-color: rgba(21, 105, 59, 0.28); }
    .status-banner.status-needs_fix { background: var(--warn-bg); color: var(--warn); border-color: rgba(154, 74, 0, 0.28); }
    .status-banner.status-rejected { background: var(--bad-bg); color: var(--bad); border-color: rgba(166, 27, 43, 0.28); }
    .status-banner.status-unanswerable_correct { background: var(--info-bg); color: var(--info); border-color: rgba(29, 78, 216, 0.28); }
    .status-banner.status-skipped { background: var(--skip-bg); color: var(--skip); }

    .section-label {
      font-size: 0.72rem;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--ink-secondary);
      margin-bottom: 4px;
    }

    .question-text {
      font-size: 1.08rem;
      font-weight: 600;
      line-height: 1.48;
      margin: 0;
      color: var(--ink-primary);
    }

    .answer-box {
      background: var(--bg-inset);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 12px 14px;
      font-size: 0.94rem;
      line-height: 1.58;
      white-space: pre-wrap;
    }

    .meta-line {
      font-size: 0.8rem;
      color: var(--ink-secondary);
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
    }

    .meta-line code {
      font-family: var(--font-mono);
      font-size: 0.77rem;
      background: var(--bg-panel);
      padding: 1px 5px;
      border-radius: 4px;
    }

    .verdict-grid {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 8px;
    }

    @media (max-width: 640px) {
      .verdict-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }

    .verdict-btn {
      padding: 10px 8px;
      border-radius: var(--radius-sm);
      border: 1.5px solid var(--border-strong);
      background: var(--bg-card);
      color: var(--ink-primary);
      font-family: var(--font-sans);
      font-size: 0.8rem;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 4px;
      text-align: center;
      transition: background 120ms ease, border-color 120ms ease;
    }

    .verdict-btn:hover { background: var(--bg-panel); }

    .kbd {
      font-family: var(--font-mono);
      font-size: 0.72rem;
      font-weight: 700;
      padding: 1px 6px;
      border-radius: 4px;
      background: var(--bg-panel);
      border: 1px solid var(--border-strong);
      color: var(--ink-primary);
    }

    .verdict-btn.active-approved { background: var(--ok-bg); border-color: var(--ok); color: var(--ok); }
    .verdict-btn.active-needs_fix { background: var(--warn-bg); border-color: var(--warn); color: var(--warn); }
    .verdict-btn.active-rejected { background: var(--bad-bg); border-color: var(--bad); color: var(--bad); }
    .verdict-btn.active-unanswerable_correct { background: var(--info-bg); border-color: var(--info); color: var(--info); }
    .verdict-btn.active-skipped { background: var(--skip-bg); border-color: var(--skip); color: var(--skip); }

    .fix-panel {
      background: var(--warn-bg);
      border: 1px solid rgba(154, 74, 0, 0.32);
      border-radius: var(--radius-md);
      padding: 14px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }

    .fix-panel[hidden] { display: none; }

    textarea, input[type="text"] {
      width: 100%;
      font-family: var(--font-sans);
      font-size: 0.88rem;
      line-height: 1.5;
      padding: 8px 10px;
      border-radius: var(--radius-sm);
      border: 1px solid var(--border-strong);
      background: #FFFFFF;
      color: var(--ink-primary);
    }

    textarea { resize: vertical; min-height: 78px; }

    .clause-list {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }

    .clause-card {
      background: var(--bg-inset);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 14px 16px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }

    .clause-header {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 6px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 8px;
    }

    .clause-id {
      font-family: var(--font-mono);
      font-size: 0.78rem;
      font-weight: 700;
      color: var(--ink-primary);
      word-break: break-all;
    }

    .clause-heading-path {
      font-size: 0.84rem;
      font-weight: 700;
      color: var(--ink-primary);
    }

    .clause-text {
      font-size: 0.92rem;
      line-height: 1.65;
      white-space: pre-wrap;
      color: var(--ink-primary);
      margin: 0;
    }

    .role-mismatch {
      background: var(--bad-bg);
      color: var(--bad);
      border-color: rgba(166, 27, 43, 0.3);
    }

    .footer-hint {
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      font-size: 0.78rem;
      color: var(--ink-secondary);
      padding: 6px 2px;
    }

    .footer-hint code {
      font-family: var(--font-mono);
      background: var(--bg-panel);
      padding: 2px 6px;
      border-radius: 4px;
      color: var(--ink-primary);
    }

    .toast {
      position: fixed;
      bottom: 20px;
      right: 20px;
      background: var(--ink-primary);
      color: #FFFFFF;
      padding: 10px 14px;
      border-radius: var(--radius-sm);
      font-size: 0.83rem;
      font-weight: 600;
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.22);
      z-index: 50;
    }

    .toast[hidden] { display: none; }

    .empty-state {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: var(--radius-lg);
      padding: 36px 24px;
      text-align: center;
      color: var(--ink-secondary);
    }

    .visually-hidden {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }
  </style>
</head>
<body>
  <div class="app-shell">
    <header class="topbar">
      <div class="brand-group">
        <div class="brand-title">
          <span class="brand-dot" aria-hidden="true"></span>
          Gold Evaluation Set — Offline Human Review
        </div>
        <div class="brand-subtitle">
          Local-only static review (<code>file://</code>). Zero model outputs shown. Saves automatically to <code>localStorage</code>.
        </div>
      </div>

      <div class="quota-strip" aria-live="polite">
        <div id="pill-total-target" class="quota-pill primary">
          <span>60-Min Target:</span>
          <strong id="target-progress-text">0 / 60 decided (60 remaining)</strong>
        </div>
        <div class="quota-pill">
          <span>orig_100:</span>
          <strong id="rem-orig">30 left</strong>
        </div>
        <div class="quota-pill">
          <span>extra_40:</span>
          <strong id="rem-extra">20 left</strong>
        </div>
        <div class="quota-pill">
          <span>boundary:</span>
          <strong id="rem-bound">10 left</strong>
        </div>
        <div class="quota-pill">
          <span>All 140:</span>
          <strong id="all-decided-text">0 / 140</strong>
        </div>
      </div>
    </header>

    <div class="progress-bar-track" aria-label="60-item target progress">
      <div id="target-progress-fill" class="progress-bar-fill"></div>
    </div>

    <section class="toolbar" aria-label="Filters and export controls">
      <div class="filter-group">
        <label class="inline-label">
          Subset
          <select id="filter-subset">
            <option value="stratified_60">Stratified 60 Sample (Default)</option>
            <option value="remaining_60">Remaining for 60-Item Target</option>
            <option value="all">All Items (140)</option>
            <option value="original_100">original_100 (GS-*)</option>
            <option value="agent_extra_40">agent_extra_40 (HARD-Q-*)</option>
            <option value="unanswerable_role_boundary">unanswerable / role-boundary</option>
          </select>
        </label>

        <label class="inline-label">
          Difficulty
          <select id="filter-difficulty">
            <option value="all">All Difficulties</option>
            <option value="easy">easy</option>
            <option value="medium">medium</option>
            <option value="hard">hard</option>
          </select>
        </label>

        <label class="inline-label">
          Status
          <select id="filter-status">
            <option value="all">All Statuses</option>
            <option value="undecided">Undecided</option>
            <option value="approved">Approved (A)</option>
            <option value="needs_fix">Needs Fix (F)</option>
            <option value="rejected">Rejected (R)</option>
            <option value="unanswerable_correct">Unanswerable OK (U)</option>
            <option value="skipped">Skipped (S)</option>
          </select>
        </label>
      </div>

      <div class="action-group">
        <label class="inline-label" style="cursor:pointer;">
          <input id="chk-auto-advance" type="checkbox" checked />
          Auto-advance
        </label>
        <button id="btn-export" type="button" class="btn btn-accent">Export decisions</button>
        <label class="btn" for="input-import" style="cursor:pointer;">Import JSON</label>
        <input id="input-import" type="file" accept=".json,application/json" class="visually-hidden" />
        <button id="btn-reset" type="button" class="btn">Reset Drafts</button>
      </div>
    </section>

    <div id="export-reminder" class="export-reminder" role="status" aria-live="polite" hidden>
      <span id="export-reminder-text">Reminder: Export decisions now to save your progress.</span>
      <div class="action-group">
        <button id="btn-reminder-export" type="button" class="btn btn-accent">Export decisions</button>
        <button id="btn-reminder-dismiss" type="button" class="btn">Dismiss until next 15</button>
      </div>
    </div>

    <main id="workspace-root">
      <div class="workspace" id="main-grid">
        <!-- Left Pane: Question, Expected Answer, Decision Controls -->
        <article class="card" aria-label="Question under review">
          <div class="nav-row">
            <button id="btn-prev" type="button" class="btn">&larr; Prev</button>
            <span id="nav-counter" class="nav-counter">Item 0 of 0</span>
            <button id="btn-next" type="button" class="btn">Next &rarr;</button>
          </div>

          <div class="badge-row" id="item-badges"></div>

          <div id="status-banner" class="status-banner status-undecided">
            <span id="status-banner-text">Not yet reviewed</span>
            <span id="status-banner-time"></span>
          </div>

          <div>
            <div class="section-label">Question</div>
            <p id="item-question" class="question-text"></p>
          </div>

          <div>
            <div class="section-label">Expected Gold Answer</div>
            <div id="item-answer" class="answer-box"></div>
          </div>

          <div id="item-meta-line" class="meta-line"></div>

          <div>
            <div class="section-label">Human Verdict (Keys: A, F, R, U, S &bull; Move: &larr; / &rarr;)</div>
            <div class="verdict-grid">
              <button type="button" class="verdict-btn" data-verdict="approved">
                <span class="kbd">A</span>
                <span>Approve</span>
              </button>
              <button type="button" class="verdict-btn" data-verdict="needs_fix">
                <span class="kbd">F</span>
                <span>Needs Fix</span>
              </button>
              <button type="button" class="verdict-btn" data-verdict="rejected">
                <span class="kbd">R</span>
                <span>Reject</span>
              </button>
              <button type="button" class="verdict-btn" data-verdict="unanswerable_correct">
                <span class="kbd">U</span>
                <span>Unanswerable OK</span>
              </button>
              <button type="button" class="verdict-btn" data-verdict="skipped">
                <span class="kbd">S</span>
                <span>Skip</span>
              </button>
            </div>
          </div>

          <div id="fix-panel" class="fix-panel" hidden>
            <div class="section-label" style="color: var(--warn);">Needs Fix — Enter Corrected Answer &amp; Clause (Original Is Preserved)</div>
            <label class="inline-label" for="input-fixed-answer">Corrected Expected Answer</label>
            <textarea id="input-fixed-answer" placeholder="Enter corrected gold answer (leave unchanged if only clause needed editing)"></textarea>
            <label class="inline-label" for="input-fixed-clause">Corrected Clause Label / Chunk IDs (comma-separated chunk IDs or clause ref)</label>
            <input id="input-fixed-clause" type="text" placeholder="e.g. DOC-BASEL-III-2023_BASEL-CAP-1.1 or Clause ..." />
            <div style="display:flex; gap:8px; justify-content:flex-end;">
              <button id="btn-save-fix" type="button" class="btn btn-accent">Save Fix &amp; Next (Ctrl+Enter)</button>
            </div>
          </div>

          <div>
            <label class="section-label" for="input-notes" style="display:block;">Human Notes (Optional)</label>
            <textarea id="input-notes" rows="2" style="min-height:56px;" placeholder="Add reviewer rationale, boundary observations, or fix context..."></textarea>
          </div>
        </article>

        <!-- Right Pane: Full Cited Source Clauses -->
        <aside class="card" aria-label="Cited source clauses">
          <div class="nav-row" style="padding-bottom:10px;">
            <span class="section-label" style="margin:0;">Cited Source Clauses (Full Verbatim Corpus Text)</span>
            <span id="clause-count-pill" class="badge">0 clauses</span>
          </div>
          <div id="clause-list" class="clause-list"></div>
        </aside>
      </div>

      <div id="empty-state" class="empty-state" hidden>
        <p style="margin:0 0 10px; font-weight:600; color:var(--ink-primary);">No items match the current filters.</p>
        <button id="btn-clear-filters" type="button" class="btn">Reset Filters</button>
      </div>
    </main>

    <footer class="footer-hint">
      <span>
        Keys: <span class="kbd">A</span> Approve &middot; <span class="kbd">F</span> Fix &middot;
        <span class="kbd">R</span> Reject &middot; <span class="kbd">U</span> Unanswerable OK &middot;
        <span class="kbd">S</span> Skip &middot; <span class="kbd">&larr;</span>/<span class="kbd">&rarr;</span> Navigate
      </span>
      <span>
        After exporting <code>data/gold_review_decisions.json</code>, run <code>python scripts/apply_review.py</code>
      </span>
    </footer>
  </div>

  <div id="toast" class="toast" role="status" aria-live="polite" hidden></div>

  <script id="gold-review-data" type="application/json">__EMBEDDED_PAYLOAD__</script>
  <script>
    (function () {
      "use strict";

      var STORAGE_KEY = "compliance_rag_gold_review_v1";
      var rawData = document.getElementById("gold-review-data").textContent;
      var DATA = JSON.parse(rawData);
      var ITEMS = DATA.items || [];
      var TARGET_IDS = DATA.sample_target_ids || [];
      var TARGET_SET = {};
      TARGET_IDS.forEach(function (id) { TARGET_SET[id] = true; });

      var ACTIONABLE = {
        approved: true,
        needs_fix: true,
        rejected: true,
        unanswerable_correct: true
      };

      var STATUS_LABELS = {
        undecided: "Not yet reviewed",
        approved: "Approved (A)",
        needs_fix: "Needs Fix (F)",
        rejected: "Rejected (R)",
        unanswerable_correct: "Unanswerable / Refuse Correct (U)",
        skipped: "Skipped (S)"
      };

      var state = loadState();
      var currentItemId = null;

      var elSubset = document.getElementById("filter-subset");
      var elDifficulty = document.getElementById("filter-difficulty");
      var elStatus = document.getElementById("filter-status");
      var elAutoAdvance = document.getElementById("chk-auto-advance");
      var elNavCounter = document.getElementById("nav-counter");
      var elBtnPrev = document.getElementById("btn-prev");
      var elBtnNext = document.getElementById("btn-next");
      var elMainGrid = document.getElementById("main-grid");
      var elEmptyState = document.getElementById("empty-state");
      var elBadges = document.getElementById("item-badges");
      var elStatusBanner = document.getElementById("status-banner");
      var elStatusText = document.getElementById("status-banner-text");
      var elStatusTime = document.getElementById("status-banner-time");
      var elQuestion = document.getElementById("item-question");
      var elAnswer = document.getElementById("item-answer");
      var elMetaLine = document.getElementById("item-meta-line");
      var elFixPanel = document.getElementById("fix-panel");
      var elFixAnswer = document.getElementById("input-fixed-answer");
      var elFixClause = document.getElementById("input-fixed-clause");
      var elNotes = document.getElementById("input-notes");
      var elClauseList = document.getElementById("clause-list");
      var elClauseCount = document.getElementById("clause-count-pill");
      var elExportReminder = document.getElementById("export-reminder");
      var elExportReminderText = document.getElementById("export-reminder-text");
      var elToast = document.getElementById("toast");
      var toastTimer = null;
      var EXPORT_REMINDER_EVERY = 15;

      function loadState() {
        try {
          var saved = localStorage.getItem(STORAGE_KEY);
          if (saved) {
            var parsed = JSON.parse(saved);
            if (parsed && typeof parsed === "object") {
              return {
                decisions: parsed.decisions && typeof parsed.decisions === "object" ? parsed.decisions : {},
                filters: parsed.filters && typeof parsed.filters === "object"
                  ? parsed.filters
                  : { subset: "stratified_60", difficulty: "all", status: "all" },
                autoAdvance: typeof parsed.autoAdvance === "boolean" ? parsed.autoAdvance : true,
                lastItemId: typeof parsed.lastItemId === "string" ? parsed.lastItemId : null,
                lastExportMilestone: typeof parsed.lastExportMilestone === "number" ? parsed.lastExportMilestone : 0
              };
            }
          }
        } catch (err) {
          // Fallback to clean state if localStorage is restricted
        }
        return {
          decisions: {},
          filters: { subset: "stratified_60", difficulty: "all", status: "all" },
          autoAdvance: true,
          lastItemId: null,
          lastExportMilestone: 0
        };
      }

      function saveState() {
        try {
          localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
        } catch (err) {
          showToast("Warning: Could not persist to localStorage.");
        }
      }

      function showToast(msg) {
        elToast.textContent = msg;
        elToast.hidden = false;
        if (toastTimer) clearTimeout(toastTimer);
        toastTimer = setTimeout(function () {
          elToast.hidden = true;
        }, 3200);
      }

      function getDecision(id) {
        return state.decisions[id] || null;
      }

      function getFilteredItems() {
        var f = state.filters;
        return ITEMS.filter(function (item) {
          var dec = getDecision(item.id);
          var decStatus = dec ? dec.decision : "undecided";

          if (f.subset === "stratified_60" && !item.in_default_sample) return false;
          if (f.subset === "remaining_60") {
            if (!item.in_default_sample) return false;
            if (dec && ACTIONABLE[dec.decision]) return false;
          }
          if (f.subset === "original_100" && item.source_subset !== "original_100") return false;
          if (f.subset === "agent_extra_40" && item.source_subset !== "agent_extra_40") return false;
          if (f.subset === "unanswerable_role_boundary" && !item.is_boundary) return false;

          if (f.difficulty !== "all" && item.difficulty !== f.difficulty) return false;
          if (f.status !== "all" && decStatus !== f.status) return false;
          return true;
        });
      }

      function countActionableDecisions() {
        var total = 0;
        ITEMS.forEach(function (item) {
          var dec = getDecision(item.id);
          if (dec && ACTIONABLE[dec.decision]) total += 1;
        });
        return total;
      }

      function updateExportReminder(actionableCount) {
        if (!elExportReminder || !elExportReminderText) return;
        var milestone = Math.floor(actionableCount / EXPORT_REMINDER_EVERY) * EXPORT_REMINDER_EVERY;
        if (milestone >= EXPORT_REMINDER_EVERY && milestone > (state.lastExportMilestone || 0)) {
          elExportReminderText.textContent =
            "Export decisions reminder: " +
            actionableCount +
            " decisions recorded locally — export data/gold_review_decisions.json now.";
          elExportReminder.hidden = false;
        } else {
          elExportReminder.hidden = true;
        }
      }

      function updateProgressUI() {
        var doneOrig = 0, totalOrig = 0;
        var doneExtra = 0, totalExtra = 0;
        var doneBound = 0, totalBound = 0;
        var totalAllDecided = 0;

        ITEMS.forEach(function (item) {
          var dec = getDecision(item.id);
          var isDone = Boolean(dec && ACTIONABLE[dec.decision]);
          if (isDone) totalAllDecided += 1;
          if (item.in_default_sample) {
            if (item.sample_stratum === "original_100") {
              totalOrig += 1;
              if (isDone) doneOrig += 1;
            } else if (item.sample_stratum === "agent_extra_40") {
              totalExtra += 1;
              if (isDone) doneExtra += 1;
            } else if (item.sample_stratum === "unanswerable_role_boundary") {
              totalBound += 1;
              if (isDone) doneBound += 1;
            }
          }
        });

        var doneTarget = doneOrig + doneExtra + doneBound;
        var totalTarget = totalOrig + totalExtra + totalBound;
        var remTotal = Math.max(0, totalTarget - doneTarget);

        document.getElementById("target-progress-text").textContent =
          doneTarget + " / " + totalTarget + " decided (" + remTotal + " remaining)";
        document.getElementById("rem-orig").textContent = Math.max(0, totalOrig - doneOrig) + " / " + totalOrig + " left";
        document.getElementById("rem-extra").textContent = Math.max(0, totalExtra - doneExtra) + " / " + totalExtra + " left";
        document.getElementById("rem-bound").textContent = Math.max(0, totalBound - doneBound) + " / " + totalBound + " left";
        document.getElementById("all-decided-text").textContent = totalAllDecided + " / " + ITEMS.length;

        var pct = totalTarget > 0 ? Math.min(100, Math.round((doneTarget / totalTarget) * 100)) : 0;
        document.getElementById("target-progress-fill").style.width = pct + "%";

        var targetPill = document.getElementById("pill-total-target");
        targetPill.classList.toggle("complete", remTotal === 0 && totalTarget > 0);
        targetPill.classList.toggle("primary", remTotal > 0);

        updateExportReminder(totalAllDecided);
      }

      function makeBadge(text, cls) {
        var span = document.createElement("span");
        span.className = "badge " + (cls || "");
        span.textContent = text;
        return span;
      }

      function renderClauses(item) {
        elClauseList.innerHTML = "";
        var clauses = item.clauses || [];
        elClauseCount.textContent = clauses.length + (clauses.length === 1 ? " clause" : " clauses");

        if (clauses.length === 0) {
          var emptyCard = document.createElement("div");
          emptyCard.className = "clause-card";
          var msg = document.createElement("p");
          msg.className = "clause-text";
          msg.textContent =
            "No cited source clauses (gold_chunk_ids is empty). This item expects refusal because the topic is outside the indexed compliance corpus or restricted from this role.";
          emptyCard.appendChild(msg);
          if (item.unauthorized_keywords && item.unauthorized_keywords.length > 0) {
            var kw = document.createElement("div");
            kw.className = "meta-line";
            kw.innerHTML = "<span>Guarded keywords: <code>" +
              item.unauthorized_keywords.map(escapeHtml).join("</code> <code>") +
              "</code></span>";
            emptyCard.appendChild(kw);
          }
          elClauseList.appendChild(emptyCard);
          return;
        }

        clauses.forEach(function (clause) {
          var card = document.createElement("div");
          card.className = "clause-card";

          var header = document.createElement("div");
          header.className = "clause-header";

          var cidEl = document.createElement("span");
          cidEl.className = "clause-id";
          cidEl.textContent = clause.chunk_id;
          header.appendChild(cidEl);

          var rolesWrap = document.createElement("div");
          rolesWrap.className = "badge-row";
          var roles = clause.allowed_roles || [];
          var allowed = roles.length === 0 || roles.indexOf(item.role_asking) !== -1;
          var roleBadge = makeBadge(
            "allowed_roles: " + (roles.length ? roles.join(", ") : "unknown"),
            allowed ? "" : "role-mismatch"
          );
          rolesWrap.appendChild(roleBadge);
          if (clause.page !== null && clause.page !== undefined) {
            rolesWrap.appendChild(makeBadge("p." + clause.page, ""));
          }
          header.appendChild(rolesWrap);
          card.appendChild(header);

          if (clause.doc_title || clause.doc_id) {
            var docLine = document.createElement("div");
            docLine.className = "meta-line";
            docLine.textContent = [clause.doc_id, clause.doc_title].filter(Boolean).join(" — ");
            card.appendChild(docLine);
          }

          var hp = document.createElement("div");
          hp.className = "clause-heading-path";
          hp.textContent = "Heading Path: " + (clause.heading_path || clause.clause_label || item.clause || "—");
          card.appendChild(hp);

          var body = document.createElement("p");
          body.className = "clause-text";
          body.textContent = clause.text_content || "";
          card.appendChild(body);

          elClauseList.appendChild(card);
        });
      }

      function escapeHtml(text) {
        return String(text)
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;");
      }

      function renderCurrentItem() {
        updateProgressUI();
        var filtered = getFilteredItems();

        if (filtered.length === 0) {
          elMainGrid.hidden = true;
          elEmptyState.hidden = false;
          elNavCounter.textContent = "0 of 0";
          elBtnPrev.disabled = true;
          elBtnNext.disabled = true;
          return;
        }

        elMainGrid.hidden = false;
        elEmptyState.hidden = true;

        var idx = -1;
        if (currentItemId) {
          for (var i = 0; i < filtered.length; i += 1) {
            if (filtered[i].id === currentItemId) {
              idx = i;
              break;
            }
          }
        }
        if (idx === -1) {
          idx = 0;
        }
        var item = filtered[idx];
        currentItemId = item.id;
        state.lastItemId = item.id;

        elNavCounter.textContent = "Item " + (idx + 1) + " of " + filtered.length + " (" + ITEMS.length + " total)";
        elBtnPrev.disabled = idx <= 0;
        elBtnNext.disabled = idx >= filtered.length - 1;

        elBadges.innerHTML = "";
        elBadges.appendChild(makeBadge(item.id, "id"));
        elBadges.appendChild(makeBadge("role: " + item.role_asking, "role"));
        elBadges.appendChild(makeBadge("difficulty: " + item.difficulty, "diff-" + item.difficulty));
        elBadges.appendChild(makeBadge("type: " + item.type, ""));
        elBadges.appendChild(
          makeBadge("expect: " + item.expected_behaviour, item.expected_behaviour === "refuse" ? "refuse" : "answer")
        );
        elBadges.appendChild(
          makeBadge(
            item.sample_stratum
              ? "60-target: " + item.sample_stratum
              : "pool: " + item.source_subset,
            item.sample_stratum ? "stratum" : ""
          )
        );

        var dec = getDecision(item.id);
        var status = dec ? dec.decision : "undecided";
        elStatusBanner.className = "status-banner status-" + status;
        elStatusText.textContent = STATUS_LABELS[status] || status;
        elStatusTime.textContent = dec && dec.decided_at ? dec.decided_at.slice(0, 19).replace("T", " ") + " UTC" : "";

        elQuestion.textContent = item.question;
        elAnswer.textContent = item.gold_answer;

        elMetaLine.innerHTML =
          "<span>Doc: <code>" + escapeHtml(item.gold_doc || "none") + "</code></span>" +
          "<span>Clause: <code>" + escapeHtml(item.clause || "none") + "</code></span>";

        var buttons = document.querySelectorAll(".verdict-btn");
        buttons.forEach(function (btn) {
          var v = btn.getAttribute("data-verdict");
          btn.className = "verdict-btn" + (status === v ? " active-" + v : "");
        });

        elFixPanel.hidden = status !== "needs_fix";
        elFixAnswer.value = dec && dec.corrected_answer !== undefined ? dec.corrected_answer : item.gold_answer;
        elFixClause.value = dec && dec.corrected_clause !== undefined ? dec.corrected_clause : (item.clause || "");
        elNotes.value = dec && dec.human_notes !== undefined ? dec.human_notes : (item.existing_human_notes || "");

        renderClauses(item);
      }

      function upsertDecision(item, verdict, opts) {
        opts = opts || {};
        var prevActionable = countActionableDecisions();
        var prev = state.decisions[item.id] || {};
        var next = {
          id: item.id,
          decision: verdict,
          decided_at: new Date().toISOString(),
          corrected_answer:
            opts.corrected_answer !== undefined
              ? opts.corrected_answer
              : prev.corrected_answer !== undefined
                ? prev.corrected_answer
                : item.gold_answer,
          corrected_clause:
            opts.corrected_clause !== undefined
              ? opts.corrected_clause
              : prev.corrected_clause !== undefined
                ? prev.corrected_clause
                : item.clause || "",
          human_notes:
            opts.human_notes !== undefined
              ? opts.human_notes
              : elNotes.value
        };
        state.decisions[item.id] = next;
        saveState();
        var newActionable = countActionableDecisions();
        if (
          newActionable >= EXPORT_REMINDER_EVERY &&
          newActionable > prevActionable &&
          newActionable % EXPORT_REMINDER_EVERY === 0
        ) {
          showToast(
            "Reminder: " + newActionable + " decisions saved locally — click Export decisions!"
          );
        }
      }

      function moveRelative(delta) {
        var filtered = getFilteredItems();
        if (filtered.length === 0) return;
        var idx = filtered.findIndex(function (r) { return r.id === currentItemId; });
        if (idx === -1) idx = 0;
        var target = Math.max(0, Math.min(filtered.length - 1, idx + delta));
        if (target !== idx) {
          currentItemId = filtered[target].id;
          renderCurrentItem();
        }
      }

      function handleVerdict(verdict) {
        var filtered = getFilteredItems();
        var item = filtered.find(function (r) { return r.id === currentItemId; });
        if (!item) return;

        upsertDecision(item, verdict);

        if (verdict === "needs_fix") {
          renderCurrentItem();
          elFixPanel.hidden = false;
          elFixAnswer.focus();
          elFixAnswer.select();
          return;
        }

        if (elAutoAdvance.checked) {
          var nextIdx = filtered.findIndex(function (r) { return r.id === item.id; }) + 1;
          var after = getFilteredItems();
          if (after.length > 0) {
            // Preserve progression smoothly even when filtering by undecided/remaining
            var sameIdx = after.findIndex(function (r) { return r.id === item.id; });
            if (sameIdx !== -1 && sameIdx + 1 < after.length) {
              currentItemId = after[sameIdx + 1].id;
            } else if (sameIdx === -1 && nextIdx - 1 < after.length) {
              currentItemId = after[Math.min(nextIdx - 1, after.length - 1)].id;
            }
          }
        }
        renderCurrentItem();
      }

      // Bind UI controls
      elSubset.value = state.filters.subset || "stratified_60";
      elDifficulty.value = state.filters.difficulty || "all";
      elStatus.value = state.filters.status || "all";
      elAutoAdvance.checked = Boolean(state.autoAdvance);
      currentItemId = state.lastItemId;

      elSubset.addEventListener("change", function () {
        state.filters.subset = elSubset.value;
        saveState();
        renderCurrentItem();
      });
      elDifficulty.addEventListener("change", function () {
        state.filters.difficulty = elDifficulty.value;
        saveState();
        renderCurrentItem();
      });
      elStatus.addEventListener("change", function () {
        state.filters.status = elStatus.value;
        saveState();
        renderCurrentItem();
      });
      elAutoAdvance.addEventListener("change", function () {
        state.autoAdvance = elAutoAdvance.checked;
        saveState();
      });

      elBtnPrev.addEventListener("click", function () { moveRelative(-1); });
      elBtnNext.addEventListener("click", function () { moveRelative(1); });

      document.querySelectorAll(".verdict-btn").forEach(function (btn) {
        btn.addEventListener("click", function () {
          handleVerdict(btn.getAttribute("data-verdict"));
        });
      });

      function saveFixFields() {
        var filtered = getFilteredItems();
        var item = filtered.find(function (r) { return r.id === currentItemId; });
        if (!item) return;
        upsertDecision(item, "needs_fix", {
          corrected_answer: elFixAnswer.value,
          corrected_clause: elFixClause.value,
          human_notes: elNotes.value
        });
        updateProgressUI();
      }

      elFixAnswer.addEventListener("input", saveFixFields);
      elFixClause.addEventListener("input", saveFixFields);
      elNotes.addEventListener("input", function () {
        var filtered = getFilteredItems();
        var item = filtered.find(function (r) { return r.id === currentItemId; });
        if (!item) return;
        var prev = state.decisions[item.id];
        if (prev) {
          prev.human_notes = elNotes.value;
          saveState();
        } else if (elNotes.value.trim()) {
          // Keep draft notes attached even before final verdict button click
          state.decisions[item.id] = {
            id: item.id,
            decision: "skipped",
            decided_at: new Date().toISOString(),
            corrected_answer: item.gold_answer,
            corrected_clause: item.clause || "",
            human_notes: elNotes.value
          };
          saveState();
        }
      });

      document.getElementById("btn-save-fix").addEventListener("click", function () {
        saveFixFields();
        moveRelative(1);
        showToast("Fix saved locally.");
      });

      document.getElementById("btn-clear-filters").addEventListener("click", function () {
        state.filters = { subset: "all", difficulty: "all", status: "all" };
        elSubset.value = "all";
        elDifficulty.value = "all";
        elStatus.value = "all";
        saveState();
        renderCurrentItem();
      });

      function exportDecisionsJson() {
        var payload = {
          schema_version: 1,
          exported_at: new Date().toISOString(),
          reviewed_by: "human",
          sample_target_ids: TARGET_IDS,
          decisions: state.decisions
        };
        var blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = "gold_review_decisions.json";
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
        var actionable = countActionableDecisions();
        state.lastExportMilestone = Math.floor(actionable / EXPORT_REMINDER_EVERY) * EXPORT_REMINDER_EVERY;
        saveState();
        updateExportReminder(actionable);
        showToast("Exported gold_review_decisions.json — save in data/ and run apply_review.py");
      }

      document.getElementById("btn-export").addEventListener("click", exportDecisionsJson);
      document.getElementById("btn-reminder-export").addEventListener("click", exportDecisionsJson);
      document.getElementById("btn-reminder-dismiss").addEventListener("click", function () {
        var actionable = countActionableDecisions();
        state.lastExportMilestone = Math.floor(actionable / EXPORT_REMINDER_EVERY) * EXPORT_REMINDER_EVERY;
        saveState();
        updateExportReminder(actionable);
      });

      document.getElementById("input-import").addEventListener("change", function (ev) {
        var file = ev.target.files && ev.target.files[0];
        if (!file) return;
        var reader = new FileReader();
        reader.onload = function () {
          try {
            var imported = JSON.parse(String(reader.result || "{}"));
            var incoming = imported.decisions || imported;
            if (!incoming || typeof incoming !== "object") {
              throw new Error("Invalid decisions JSON format.");
            }
            Object.keys(incoming).forEach(function (qid) {
              state.decisions[qid] = incoming[qid];
            });
            saveState();
            renderCurrentItem();
            showToast("Imported " + Object.keys(incoming).length + " review entries.");
          } catch (err) {
            showToast("Import failed: " + err.message);
          }
        };
        reader.readAsText(file, "utf-8");
        ev.target.value = "";
      });

      document.getElementById("btn-reset").addEventListener("click", function () {
        if (!window.confirm("Clear all locally saved review decisions from this browser?")) {
          return;
        }
        state.decisions = {};
        state.lastExportMilestone = 0;
        saveState();
        renderCurrentItem();
        showToast("Local review drafts cleared.");
      });

      // Keyboard navigation & shortcuts (never hijack text inputs)
      document.addEventListener("keydown", function (ev) {
        var tag = (ev.target && ev.target.tagName ? ev.target.tagName : "").toLowerCase();
        var isEditable = tag === "input" || tag === "textarea" || tag === "select";

        if (isEditable) {
          if (ev.key === "Escape") {
            ev.target.blur();
          } else if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter" && !elFixPanel.hidden) {
            ev.preventDefault();
            saveFixFields();
            moveRelative(1);
            showToast("Fix saved locally.");
          }
          return;
        }

        if (ev.ctrlKey || ev.metaKey || ev.altKey) return;

        var key = ev.key;
        if (key === "ArrowLeft") {
          ev.preventDefault();
          moveRelative(-1);
        } else if (key === "ArrowRight") {
          ev.preventDefault();
          moveRelative(1);
        } else if (key === "a" || key === "A") {
          ev.preventDefault();
          handleVerdict("approved");
        } else if (key === "f" || key === "F") {
          ev.preventDefault();
          handleVerdict("needs_fix");
        } else if (key === "r" || key === "R") {
          ev.preventDefault();
          handleVerdict("rejected");
        } else if (key === "u" || key === "U") {
          ev.preventDefault();
          handleVerdict("unanswerable_correct");
        } else if (key === "s" || key === "S") {
          ev.preventDefault();
          handleVerdict("skipped");
        }
      });

      renderCurrentItem();
    })();
  </script>
</body>
</html>
"""


def generate_review_html(
    gold_path: str | Path = PROJECT_ROOT / "data" / "eval" / "gold_set.jsonl",
    sheet_path: str | Path = PROJECT_ROOT / "data" / "gold_review_sheet.csv",
    bm25_path: str | Path | None = None,
) -> tuple[str, list[dict[str, Any]], list[str]]:
    """Build the self-contained static HTML string plus structured queue metadata."""
    items = load_gold_set(gold_path, include_rejected=True)
    clause_lookup = load_clause_lookup(bm25_path)
    sheet_meta = load_sheet_metadata(sheet_path)
    records, sample_target_ids = build_review_records(items, clause_lookup, sheet_meta)

    payload = {
        "schema_version": 1,
        "total_items": len(records),
        "sample_target_ids": sample_target_ids,
        "items": records,
    }
    safe_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html = HTML_TEMPLATE.replace("__EMBEDDED_PAYLOAD__", safe_json)
    return html, records, sample_target_ids


def write_review_html(
    output_path: str | Path = PROJECT_ROOT / "reports" / "gold_review.html",
    gold_path: str | Path = PROJECT_ROOT / "data" / "eval" / "gold_set.jsonl",
    sheet_path: str | Path = PROJECT_ROOT / "data" / "gold_review_sheet.csv",
    bm25_path: str | Path | None = None,
) -> dict[str, Any]:
    """Generate and write ``reports/gold_review.html`` to disk without mutating gold files."""
    html, records, sample_target_ids = generate_review_html(
        gold_path=gold_path,
        sheet_path=sheet_path,
        bm25_path=bm25_path,
    )
    dest = Path(output_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(html, encoding="utf-8")

    strata_counts: dict[str, int] = {}
    for rec in records:
        stratum = rec.get("sample_stratum")
        if stratum:
            strata_counts[stratum] = strata_counts.get(stratum, 0) + 1

    return {
        "output_path": str(dest),
        "total_items": len(records),
        "sample_target_count": len(sample_target_ids),
        "strata_counts": strata_counts,
    }


def main() -> int:
    """CLI entry point to build ``reports/gold_review.html``."""
    parser = argparse.ArgumentParser(description="Generate offline static HTML gold review tool.")
    parser.add_argument("--gold-path", default=str(PROJECT_ROOT / "data" / "eval" / "gold_set.jsonl"))
    parser.add_argument("--sheet-path", default=str(PROJECT_ROOT / "data" / "gold_review_sheet.csv"))
    parser.add_argument("--output", default=str(PROJECT_ROOT / "reports" / "gold_review.html"))
    args = parser.parse_args()

    summary = write_review_html(
        output_path=args.output,
        gold_path=args.gold_path,
        sheet_path=args.sheet_path,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
