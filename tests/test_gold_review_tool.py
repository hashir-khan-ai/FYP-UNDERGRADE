"""Tests for scripts/review_gold.py, scripts/apply_review.py, and rejected-item exclusion."""

from __future__ import annotations

import csv
import json
import re
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.apply_review import apply_review  # noqa: E402
from scripts.review_gold import generate_review_html, write_review_html  # noqa: E402
from src.evaluation.gold_set import (  # noqa: E402
    exclude_rejected_questions,
    load_gold_set,
    select_reviewed_questions,
)


def test_review_gold_html_offline_and_stratified_queue(tmp_path: Path) -> None:
    """Generated HTML must be zero-dependency offline HTML with a 30+20+10 stratified sample."""
    out_file = tmp_path / "gold_review.html"
    summary = write_review_html(output_path=out_file)

    assert summary["total_items"] == 140
    assert summary["sample_target_count"] == 60
    assert summary["strata_counts"] == {
        "original_100": 30,
        "agent_extra_40": 20,
        "unanswerable_role_boundary": 10,
    }

    html = out_file.read_text(encoding="utf-8")
    # Zero external script/css/network calls
    assert "<script src=" not in html.lower()
    assert '<link rel="stylesheet"' not in html.lower()
    assert "http://" not in html.lower()
    assert "https://" not in html.lower()
    assert "fetch(" not in html

    # Interactive controls & shortcut keys present
    for required in ("localStorage", "gold_review_decisions.json", "ArrowLeft", "ArrowRight", "Approve", "Needs Fix", "Reject", "Unanswerable OK", "Skip"):
        assert required in html

    match = re.search(
        r'<script id="gold-review-data" type="application/json">(.*?)</script>',
        html,
        flags=re.DOTALL,
    )
    assert match is not None
    payload = json.loads(match.group(1).replace("<\\/", "</"))

    assert len(payload["sample_target_ids"]) == 60
    assert len(set(payload["sample_target_ids"])) == 60
    assert len(payload["items"]) == 140
    assert len({item["id"] for item in payload["items"]}) == 140

    # Verify full clause heading_path & text rendered on cited items and no leaked system outputs
    gs001 = next(item for item in payload["items"] if item["id"] == "GS-001")
    assert gs001["clauses"], "GS-001 must include full cited source clause"
    assert gs001["clauses"][0]["heading_path"]
    assert "4.5%" in gs001["clauses"][0]["text_content"]

    forbidden_keys = {"system_answer", "model_answer", "retrieved_chunks", "rag_output", "rerank_scores"}
    assert not (forbidden_keys & set(gs001.keys()))


def test_apply_review_updates_only_decided_items_and_preserves_originals(tmp_path: Path) -> None:
    """apply_review.py writes reviewed_by='human' ONLY for decided items and keeps original+fixed."""
    real_jsonl = PROJECT_ROOT / "data" / "eval" / "gold_set.jsonl"
    real_csv = PROJECT_ROOT / "data" / "gold_review_sheet.csv"

    selected_ids = {"GS-001", "GS-002", "GS-003", "GS-004", "GS-005", "GS-081", "HARD-Q-01", "HARD-Q-02"}
    subset_rows = [
        json.loads(line)
        for line in real_jsonl.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line)["id"] in selected_ids
    ]

    tmp_jsonl = tmp_path / "gold_set.jsonl"
    tmp_jsonl.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in subset_rows) + "\n", encoding="utf-8")

    tmp_v2_jsonl = tmp_path / "gold_v2.jsonl"
    v2_subset = [r for r in subset_rows if r["id"].startswith("GS-")]
    tmp_v2_jsonl.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in v2_subset) + "\n", encoding="utf-8")

    tmp_v2_json = tmp_path / "gold_v2.json"
    tmp_v2_json.write_text(json.dumps(v2_subset, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    tmp_csv = tmp_path / "gold_review_sheet.csv"
    with open(real_csv, "r", encoding="utf-8", newline="") as src, open(tmp_csv, "w", encoding="utf-8", newline="") as dst:
        reader = csv.DictReader(src)
        writer = csv.DictWriter(dst, fieldnames=reader.fieldnames)
        writer.writeheader()
        for row in reader:
            if row["id"] in selected_ids:
                writer.writerow(row)

    orig_gs002 = next(r for r in subset_rows if r["id"] == "GS-002")
    orig_hard_q_02 = next(r for r in subset_rows if r["id"] == "HARD-Q-02")

    decisions_file = tmp_path / "gold_review_decisions.json"
    decisions_payload = {
        "schema_version": 1,
        "exported_at": "2026-11-15T01:00:00Z",
        "reviewed_by": "human",
        "decisions": {
            "GS-001": {
                "id": "GS-001",
                "decision": "approved",
                "decided_at": "2026-11-15T00:55:00Z",
                "human_notes": "Verified against Basel CAP 1.1",
            },
            "GS-002": {
                "id": "GS-002",
                "decision": "needs_fix",
                "decided_at": "2026-11-15T00:56:00Z",
                "corrected_answer": "Corrected Tier 1 ratio is 6.0% of RWA (verified).",
                "corrected_clause": "Clause BASEL-CAP-1.2 Revised",
                "human_notes": "Tightened wording",
            },
            "GS-003": {
                "id": "GS-003",
                "decision": "rejected",
                "decided_at": "2026-11-15T00:57:00Z",
                "human_notes": "Duplicate phrasing",
            },
            "GS-081": {
                "id": "GS-081",
                "decision": "unanswerable_correct",
                "decided_at": "2026-11-15T00:58:00Z",
                "human_notes": "Scotland LTV out of corpus",
            },
            "GS-004": {
                "id": "GS-004",
                "decision": "skipped",
                "decided_at": "2026-11-15T00:58:30Z",
                "human_notes": "Skip for later",
            },
            "HARD-Q-01": {
                "id": "HARD-Q-01",
                "decision": "approved",
                "decided_at": "2026-11-15T00:59:00Z",
                "human_notes": "Role boundary verified",
            },
        },
    }
    decisions_file.write_text(json.dumps(decisions_payload, indent=2), encoding="utf-8")

    summary = apply_review(
        decisions_path=decisions_file,
        gold_jsonl_path=tmp_jsonl,
        sheet_csv_path=tmp_csv,
        sync_paths=[tmp_v2_jsonl, tmp_v2_json],
    )

    assert summary["actionable_decisions"] == 5
    assert summary["updated_gold_jsonl"] == 5
    assert summary["updated_csv_rows"] == 5

    by_id = {
        row["id"]: row
        for row in (json.loads(l) for l in tmp_jsonl.read_text(encoding="utf-8").splitlines() if l.strip())
    }

    # Decided items updated to reviewed_by='human'
    assert by_id["GS-001"]["reviewed_by"] == "human"
    assert by_id["GS-001"]["reviewed_at"] == "2026-11-15T00:55:00Z"
    assert by_id["GS-001"]["human_notes"] == "Verified against Basel CAP 1.1"
    assert by_id["GS-001"]["status"] == "reviewed"

    # Fixed item retains BOTH original and corrected versions
    assert by_id["GS-002"]["reviewed_by"] == "human"
    assert by_id["GS-002"]["review_status"] == "needs_fix"
    assert by_id["GS-002"]["status"] == "reviewed"
    assert by_id["GS-002"]["original_gold_answer"] == orig_gs002["gold_answer"]
    assert by_id["GS-002"]["gold_answer"] == "Corrected Tier 1 ratio is 6.0% of RWA (verified)."
    assert by_id["GS-002"]["original_clause"] == orig_gs002["clause"]
    assert by_id["GS-002"]["clause"] == "Clause BASEL-CAP-1.2 Revised"

    # Skipped and undecided items remain COMPLETELY untouched
    assert by_id["GS-004"]["reviewed_by"] is None
    assert by_id["GS-004"]["review_status"] == "unreviewed_draft"
    assert by_id["GS-005"]["reviewed_by"] is None
    assert by_id["GS-005"]["review_status"] == "unreviewed_draft"
    assert by_id["HARD-Q-02"]["reviewed_by"] is None
    assert by_id["HARD-Q-02"]["review_status"] == "unreviewed_draft"
    assert by_id["HARD-Q-02"] == orig_hard_q_02

    # HARD-Q-01 was decided -> updated in JSONL and added to CSV
    assert by_id["HARD-Q-01"]["reviewed_by"] == "human"

    # Synced v2 files also received GS-001..003 & GS-081 updates
    v2_json_map = {r["id"]: r for r in json.loads(tmp_v2_json.read_text(encoding="utf-8"))}
    assert v2_json_map["GS-002"]["gold_answer"] == "Corrected Tier 1 ratio is 6.0% of RWA (verified)."
    assert v2_json_map["GS-002"]["original_gold_answer"] == orig_gs002["gold_answer"]
    assert v2_json_map["GS-005"]["reviewed_by"] is None

    # CSV assertions
    with open(tmp_csv, "r", encoding="utf-8", newline="") as handle:
        csv_by_id = {r["id"]: r for r in csv.DictReader(handle)}

    assert csv_by_id["GS-001"]["reviewed_by"] == "human"
    assert csv_by_id["GS-001"]["reviewed_at"] == "2026-11-15T00:55:00Z"
    assert csv_by_id["GS-001"]["human_notes"] == "Verified against Basel CAP 1.1"
    assert csv_by_id["GS-002"]["expected answer"] == "Corrected Tier 1 ratio is 6.0% of RWA (verified)."
    assert "original_answer=" in csv_by_id["GS-002"]["human_notes"]
    assert csv_by_id["GS-003"]["review_status"] == "rejected"
    assert csv_by_id["GS-004"]["reviewed_by"] == ""
    assert csv_by_id["GS-005"]["reviewed_by"] == ""
    assert "HARD-Q-01" in csv_by_id
    assert "HARD-Q-02" not in csv_by_id

    # Metric exclusion assertions
    all_loaded = load_gold_set(tmp_jsonl, include_rejected=True)
    non_rejected = load_gold_set(tmp_jsonl, include_rejected=False)
    assert any(item.id == "GS-003" for item in all_loaded)
    assert all(item.id != "GS-003" for item in non_rejected)
    assert all(item.id != "GS-003" for item in exclude_rejected_questions(all_loaded))

    reviewed_only = select_reviewed_questions(all_loaded, min_reviewed=1)
    reviewed_ids = {item.id for item in reviewed_only}
    assert {"GS-001", "GS-002", "GS-081", "HARD-Q-01"}.issubset(reviewed_ids)
    assert "GS-003" not in reviewed_ids
    assert "GS-004" not in reviewed_ids
    assert "GS-005" not in reviewed_ids


def test_real_repo_gold_files_not_marked_human_by_agent() -> None:
    """Safeguard: automated build must never stamp reviewed_by='human' on real gold files unless human exported decisions."""
    decisions_path = PROJECT_ROOT / "data" / "gold_review_decisions.json"
    if not decisions_path.exists():
        items = load_gold_set(PROJECT_ROOT / "data" / "eval" / "gold_set.jsonl")
        assert all(item.reviewed_by != "human" for item in items)


def test_review_gold_no_system_output_and_export_reminder(tmp_path: Path) -> None:
    """gold_review.html must omit all system/router outputs and show an 'Export decisions' reminder every 15 decisions."""
    out_file = tmp_path / "gold_review_check.html"
    write_review_html(output_path=out_file)
    html = out_file.read_text(encoding="utf-8")

    match = re.search(
        r'<script id="gold-review-data" type="application/json">(.*?)</script>',
        html,
        flags=re.DOTALL,
    )
    assert match is not None
    payload = json.loads(match.group(1).replace("<\\/", "</"))

    allowed_item_keys = {
        "id",
        "question",
        "type",
        "role_asking",
        "difficulty",
        "source_subset",
        "is_boundary",
        "expected_behaviour",
        "gold_doc",
        "clause",
        "gold_chunk_ids",
        "gold_answer",
        "unauthorized_keywords",
        "existing_human_notes",
        "clauses",
        "sample_stratum",
        "in_default_sample",
        "default_order",
    }
    forbidden_output_keys = {
        "system_answer",
        "model_answer",
        "retrieved_chunks",
        "rag_output",
        "rerank_scores",
        "grader_verdict",
        "latency_ms",
        "audit_id",
        "llm_profile",
        "expected_route",
        "pipeline_stages",
    }

    for item in payload["items"]:
        keys = set(item.keys())
        assert keys == allowed_item_keys, f"Unexpected item keys in {item['id']}: {keys - allowed_item_keys}"
        assert not (forbidden_output_keys & keys)
        for clause in item["clauses"]:
            assert set(clause.keys()) == {
                "chunk_id",
                "doc_id",
                "doc_title",
                "heading_path",
                "section_label",
                "clause_label",
                "page",
                "allowed_roles",
                "text_content",
                "missing",
            }

    # UI must not display router/system output labels and must include the 15-decision Export reminder
    assert "<span>Route:" not in html
    assert 'id="export-reminder"' in html
    assert 'id="btn-reminder-export"' in html
    assert "Export decisions" in html
    assert "EXPORT_REMINDER_EVERY = 15" in html
    assert "newActionable % EXPORT_REMINDER_EVERY === 0" in html
    assert "Math.floor(actionableCount / EXPORT_REMINDER_EVERY) * EXPORT_REMINDER_EVERY" in html


