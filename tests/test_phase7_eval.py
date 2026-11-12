"""Unit tests for Phase 7 evaluation metrics, gold-set validation, and ablation runner.

All tests execute strictly under ``LLM_PROFILE=mock`` with zero network calls.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from src.config import settings
from src.evaluation.ablation import (
    ABLATION_MATRIX,
    DEMO_ONLY_BANNER,
    ProfileMismatchError,
    aggregate_ablation_rows,
    append_checkpoint_row,
    apply_ablation_config,
    ensure_same_profile,
    load_checkpoint_rows,
)
from src.evaluation.gold_set import GoldQuestionItem, validate_gold_set_file
from src.evaluation.metrics import (
    answer_correctness_score,
    bootstrap_ci,
    intervals_overlap,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)
from scripts.build_gold_set import suggest_questions_via_llm, write_templates
from scripts.make_report_tables import (
    generate_markdown_table,
    load_and_validate_ablation_files,
    write_csv_table,
)
from scripts.run_ablation import run_ablation_suite


# ==============================================================================
# 1. Metric functions on tiny hand-computed fixtures
# ==============================================================================
def test_recall_at_k_hand_computed() -> None:
    retrieved = ["C1", "C2", "C3", "C4", "C5"]
    gold_single = ["C3"]
    assert recall_at_k(retrieved, gold_single, 1) == 0.0
    assert recall_at_k(retrieved, gold_single, 3) == 1.0
    assert recall_at_k(retrieved, gold_single, 5) == 1.0

    gold_multi = ["C2", "C5"]
    assert recall_at_k(retrieved, gold_multi, 1) == 0.0
    assert recall_at_k(retrieved, gold_multi, 3) == 0.5
    assert recall_at_k(retrieved, gold_multi, 5) == 1.0
    assert recall_at_k(retrieved, [], 5) == 0.0

    with pytest.raises(ValueError):
        recall_at_k(retrieved, gold_single, 0)


def test_reciprocal_rank_hand_computed() -> None:
    retrieved = ["C10", "C20", "C30", "C40"]
    assert reciprocal_rank(retrieved, ["C10"]) == 1.0
    assert reciprocal_rank(retrieved, ["C30"]) == pytest.approx(1.0 / 3.0)
    assert reciprocal_rank(retrieved, ["C99"]) == 0.0
    assert reciprocal_rank(retrieved, []) == 0.0


def test_ndcg_at_k_hand_computed_and_deduplicated() -> None:
    retrieved = ["C1", "C2", "C3"]
    # Hit at rank 1 -> DCG = 1/log2(2) = 1.0, IDCG = 1.0 -> nDCG = 1.0
    assert ndcg_at_k(retrieved, ["C1"], 3) == pytest.approx(1.0)

    # Hit at rank 2 -> DCG = 1/log2(3), IDCG = 1.0
    expected_r2 = (1.0 / math.log2(3)) / 1.0
    assert ndcg_at_k(retrieved, ["C2"], 3) == pytest.approx(expected_r2)

    # Duplicate retrieved IDs must not inflate nDCG above 1.0
    dup_retrieved = ["C1", "C1", "C1"]
    assert ndcg_at_k(dup_retrieved, ["C1"], 3) == pytest.approx(1.0)


def test_answer_correctness_and_bootstrap_ci() -> None:
    gold = "Minimum CET1 ratio is 4.5% of total risk-weighted assets."
    pred_exact = "Minimum CET1 ratio is 4.5% of total risk-weighted assets."
    pred_none = "Unrelated response about office cafeteria menus."
    assert answer_correctness_score(pred_exact, gold) == pytest.approx(1.0)
    assert answer_correctness_score(pred_none, gold) == 0.0

    high_vals = [1.0, 1.0, 0.95, 1.0, 0.98, 1.0, 0.97, 1.0]
    low_vals = [0.1, 0.0, 0.15, 0.05, 0.1, 0.0, 0.12, 0.08]
    ci_high = bootstrap_ci(high_vals, n_boot=500, seed=42)
    ci_low = bootstrap_ci(low_vals, n_boot=500, seed=42)

    assert ci_high["n"] == 8
    assert ci_high["ci_low"] <= ci_high["mean"] <= ci_high["ci_high"]
    assert intervals_overlap(ci_high, ci_low) is False
    assert intervals_overlap(ci_high, ci_high) is True


# ==============================================================================
# 2. Gold-set validation & LLM suggestion status guard
# ==============================================================================
def test_gold_set_validator_passes_real_file() -> None:
    report = validate_gold_set_file("data/eval/gold_set.jsonl", min_per_type=15)
    assert report.valid is True
    assert report.total_count == 100
    for qtype in ("single_fact", "multi_part", "cross_reference", "role_restricted", "unanswerable"):
        assert report.counts_by_type[qtype] >= 15


def test_gold_set_validator_catches_missing_chunks_and_quotas(tmp_path: Path) -> None:
    bad_file = tmp_path / "bad_gold.jsonl"
    row_missing_chunk = {
        "id": "BAD-001",
        "question": "What is the minimum CET1 ratio under Basel III?",
        "type": "single_fact",
        "role_asking": "analyst",
        "gold_chunk_ids": ["NON-EXISTENT-CHUNK-999"],
        "gold_doc": "DOC-BASEL-III-2023",
        "clause": "BASEL-CAP-1.1",
        "gold_answer": "4.5% of RWA.",
        "expected_behaviour": "answer",
        "status": "reviewed",
    }
    row_empty_gold_for_answer = {
        "id": "BAD-002",
        "question": "What is the Tier 1 ratio under Basel III?",
        "type": "single_fact",
        "role_asking": "analyst",
        "gold_chunk_ids": [],
        "gold_doc": "DOC-BASEL-III-2023",
        "clause": "BASEL-CAP-1.2",
        "gold_answer": "6.0% of RWA.",
        "expected_behaviour": "answer",
        "status": "reviewed",
    }
    bad_file.write_text(
        json.dumps(row_missing_chunk) + "\n" + json.dumps(row_empty_gold_for_answer) + "\n",
        encoding="utf-8",
    )

    report = validate_gold_set_file(
        bad_file,
        known_chunk_ids={"DOC-BASEL-III-2023_BASEL-CAP-1.1"},
        min_per_type=1,
    )
    assert report.valid is False
    assert any("NON-EXISTENT-CHUNK-999" in err for err in report.missing_chunk_errors)
    assert any("BAD-002" in err for err in report.schema_errors)
    assert len(report.type_quota_errors) >= 4


def test_suggest_mode_never_marks_questions_reviewed(tmp_path: Path) -> None:
    fake_chunks = [
        {
            "chunk_id": "DOC-BASEL-III-2023_BASEL-CAP-1.1",
            "doc_id": "DOC-BASEL-III-2023",
            "doc_title": "Basel III",
            "heading_path": "Section 1 > BASEL-CAP-1.1",
            "clause_label": "BASEL-CAP-1.1",
            "allowed_roles": ["analyst", "manager", "auditor"],
            "text_content": "Institutions must maintain a minimum CET1 ratio of 4.5%.",
        }
    ]
    out_jsonl = tmp_path / "suggestions.jsonl"
    suggestions = suggest_questions_via_llm(
        chunks=fake_chunks,
        profile="mock",
        max_calls=1,
        output_path=out_jsonl,
    )
    assert len(suggestions) == 1
    assert suggestions[0].status == "draft"
    assert suggestions[0].source_chunk_id == "DOC-BASEL-III-2023_BASEL-CAP-1.1"

    csv_p = tmp_path / "tpl.csv"
    jsonl_p = tmp_path / "tpl.jsonl"
    count, _, _ = write_templates(fake_chunks, csv_path=csv_p, jsonl_path=jsonl_p)
    assert count == 1
    assert csv_p.exists() and jsonl_p.exists()


# ==============================================================================
# 3. Ablation config isolation & RBAC_OFF_DEMO guard
# ==============================================================================
def test_ablation_config_isolation_restores_flags() -> None:
    orig_hp = settings.ENABLE_HEADING_PATH
    orig_rbac = settings.ENABLE_RBAC
    orig_base = settings.BASELINE_ABLATION
    orig_mem = settings.ENABLE_MEMORY
    orig_rt = settings.ENABLE_ADAPTIVE_ROUTER
    orig_gr = settings.ENABLE_CORRECTIVE_GRADER
    orig_xai = settings.ENABLE_XAI_OUTPUT

    with apply_ablation_config(ABLATION_MATRIX["A0_baseline"]):
        assert settings.ENABLE_HEADING_PATH is False
        assert settings.ENABLE_RBAC is True
        assert settings.ENABLE_MEMORY is False
        assert settings.ENABLE_ADAPTIVE_ROUTER is False
        assert settings.ENABLE_CORRECTIVE_GRADER is False
        assert settings.ENABLE_XAI_OUTPUT is False

    with apply_ablation_config(ABLATION_MATRIX["A3_router"]):
        assert settings.ENABLE_HEADING_PATH is True
        assert settings.ENABLE_RBAC is True
        assert settings.ENABLE_MEMORY is True
        assert settings.ENABLE_ADAPTIVE_ROUTER is True
        assert settings.ENABLE_CORRECTIVE_GRADER is False
        assert settings.ENABLE_XAI_OUTPUT is False

    # Verify RBAC_OFF_DEMO is rejected unless allow_rbac_off=True
    with pytest.raises(RuntimeError, match="allow_rbac_off=True"):
        with apply_ablation_config(ABLATION_MATRIX["RBAC_OFF_DEMO"], allow_rbac_off=False):
            pass

    with apply_ablation_config(ABLATION_MATRIX["RBAC_OFF_DEMO"], allow_rbac_off=True) as spec:
        assert settings.ENABLE_RBAC is False
        assert settings.BASELINE_ABLATION is True
        assert spec.is_demonstration_only is True
        assert spec.warning_banner == DEMO_ONLY_BANNER

    assert settings.ENABLE_HEADING_PATH == orig_hp
    assert settings.ENABLE_RBAC == orig_rbac
    assert settings.BASELINE_ABLATION == orig_base
    assert settings.ENABLE_MEMORY == orig_mem
    assert settings.ENABLE_ADAPTIVE_ROUTER == orig_rt
    assert settings.ENABLE_CORRECTIVE_GRADER == orig_gr
    assert settings.ENABLE_XAI_OUTPUT == orig_xai


# ==============================================================================
# 4. Profile recording, resume behaviour, and refusal to mix profiles
# ==============================================================================
def test_checkpoint_resume_and_profile_mismatch_guard(tmp_path: Path) -> None:
    ckpt = tmp_path / "ckpt.jsonl"
    row_mock = {
        "id": "GS-001",
        "type": "single_fact",
        "role_asking": "analyst",
        "expected_behaviour": "answer",
        "llm_profile": "mock",
        "llm_model": "mock-deterministic",
        "route_used": "SINGLE_SEARCH",
        "expected_route": "SINGLE_SEARCH",
        "route_correct": 1.0,
        "is_refusal": False,
        "correct_refusal": 0.0,
        "false_refusal": 0.0,
        "leaked": 0.0,
        "recall@1": 1.0,
        "recall@3": 1.0,
        "recall@5": 1.0,
        "mrr": 1.0,
        "ndcg@5": 1.0,
        "answer_correctness": 0.9,
        "citation_validity": 1.0,
        "citation_support": 1.0,
        "faithfulness": None,
        "context_precision": None,
        "latency_ms": 5.0,
        "llm_calls": 1,
        "llm_tokens": 50,
    }
    append_checkpoint_row(ckpt, row_mock)

    loaded = load_checkpoint_rows(ckpt, expected_profile="mock", expected_model="mock-deterministic")
    assert "GS-001" in loaded

    # Attempting to load a mock checkpoint into a dev run must fail fast
    with pytest.raises(ProfileMismatchError, match="Refusing to mix LLM profiles"):
        load_checkpoint_rows(ckpt, expected_profile="dev", expected_model="llama-3.1-8b-instant")

    # Attempting to combine result files across profiles in make_report_tables must fail fast
    f_mock = tmp_path / "ablation_mock.json"
    f_dev = tmp_path / "ablation_dev.json"
    f_mock.write_text(
        json.dumps({"llm_profile": "mock", "llm_model": "mock-deterministic", "configurations": []}),
        encoding="utf-8",
    )
    f_dev.write_text(
        json.dumps({"llm_profile": "dev", "llm_model": "llama-3.1-8b-instant", "configurations": []}),
        encoding="utf-8",
    )
    with pytest.raises(ProfileMismatchError, match="Cannot combine ablation results"):
        load_and_validate_ablation_files([f_mock, f_dev])


def test_ablation_suite_records_profile_and_resumes_cleanly(tmp_path: Path) -> None:
    sample_questions = [
        GoldQuestionItem(
            id="GS-TEST-1",
            question="What is the minimum CET1 ratio required under Basel III?",
            type="single_fact",
            role_asking="analyst",
            gold_chunk_ids=["DOC-BASEL-III-2023_BASEL-CAP-1.1"],
            gold_doc="DOC-BASEL-III-2023",
            clause="BASEL-CAP-1.1",
            gold_answer="4.5% of total risk-weighted assets.",
            expected_behaviour="answer",
            status="draft",
            expected_route="SINGLE_SEARCH",
        ),
        GoldQuestionItem(
            id="GS-TEST-2",
            question="What is the deadline in POL-MGT-1.1 for notifying the PRA and FCA?",
            type="role_restricted",
            role_asking="analyst",
            gold_chunk_ids=["DOC-INT-POL-MGT-002_POL-MGT-1.1"],
            gold_doc="DOC-INT-POL-MGT-002",
            clause="POL-MGT-1.1",
            gold_answer="I can't find that in the documents available to your role.",
            expected_behaviour="refuse",
            status="draft",
            expected_route="SINGLE_SEARCH",
            unauthorized_keywords=["24 hours", "FCA Connect"],
        ),
    ]

    cache_dir = tmp_path / "cache"
    out_dir = tmp_path / "results"

    payload_1 = run_ablation_suite(
        profile="mock",
        questions=sample_questions[:1],
        config_names=["A0_baseline", "A5_full_xai"],
        include_rbac_off=True,
        resume=False,
        mock_reranker=True,
        cache_dir=cache_dir,
        out_dir=out_dir,
    )
    assert payload_1["llm_profile"] == "mock"
    assert payload_1["llm_model"] == "mock"
    assert "HARNESS CHECK ONLY" in payload_1["harness_mode_banner"]

    # Now resume with both questions: GS-TEST-1 is loaded from checkpoint, GS-TEST-2 is evaluated
    payload_2 = run_ablation_suite(
        profile="mock",
        questions=sample_questions,
        config_names=["A0_baseline", "A5_full_xai"],
        include_rbac_off=True,
        resume=True,
        mock_reranker=True,
        cache_dir=cache_dir,
        out_dir=out_dir,
    )
    assert payload_2["questions_evaluated"] == 2
    cfg_map = {c["config_name"]: c for c in payload_2["configurations"]}
    assert cfg_map["A0_baseline"]["metrics"]["leakage_rate"] == 0.0
    assert cfg_map["A5_full_xai"]["metrics"]["leakage_rate"] == 0.0
    assert cfg_map["RBAC_OFF_DEMO"]["is_demonstration_only"] is True
    assert cfg_map["RBAC_OFF_DEMO"]["warning_banner"] == DEMO_ONLY_BANNER
    assert cfg_map["RBAC_OFF_DEMO"]["metrics"]["leakage_rate"] > 0.0

    md_text = generate_markdown_table(payload_2)
    assert "HARNESS CHECK ONLY" in md_text
    assert DEMO_ONLY_BANNER in md_text

    csv_file = out_dir / "ablation_table.csv"
    write_csv_table(payload_2, csv_file)
    assert csv_file.exists()


# ==============================================================================
# 5. Phase 7b: Routing accuracy "n/a", cost separation, and review gates
# ==============================================================================
def test_routing_accuracy_na_when_router_off_and_cost_separation() -> None:
    spec_a0 = ABLATION_MATRIX["A0_baseline"]  # router off
    spec_a3 = ABLATION_MATRIX["A3_router"]    # router on

    sample_rows = [
        {
            "id": "Q1",
            "type": "single_fact",
            "expected_behaviour": "answer",
            "router_enabled": False,
            "route_used": "SINGLE_SEARCH",
            "expected_route": "SINGLE_SEARCH",
            "route_correct": None,
            "is_refusal": False,
            "correct_refusal": 0.0,
            "false_refusal": 0.0,
            "leaked": 0.0,
            "recall@1": 1.0,
            "recall@3": 1.0,
            "recall@5": 1.0,
            "mrr": 1.0,
            "ndcg@5": 1.0,
            "answer_correctness": 0.9,
            "citation_validity": 1.0,
            "citation_support": 1.0,
            "faithfulness": None,
            "context_precision": None,
            "latency_ms": 10.0,
            "live_calls": 1,
            "cached_calls": 0,
            "live_tokens": 120,
            "cached_tokens": 0,
            "refused_without_llm": False,
        },
        {
            "id": "Q2",
            "type": "unanswerable",
            "expected_behaviour": "refuse",
            "router_enabled": False,
            "route_used": "SINGLE_SEARCH",
            "expected_route": "REFUSE",
            "route_correct": None,
            "is_refusal": True,
            "correct_refusal": 1.0,
            "false_refusal": 0.0,
            "leaked": 0.0,
            "recall@1": 0.0,
            "recall@3": 0.0,
            "recall@5": 0.0,
            "mrr": 0.0,
            "ndcg@5": 0.0,
            "answer_correctness": 1.0,
            "citation_validity": 1.0,
            "citation_support": 1.0,
            "faithfulness": None,
            "context_precision": None,
            "latency_ms": 2.0,
            "live_calls": 0,
            "cached_calls": 0,
            "live_tokens": 0,
            "cached_tokens": 0,
            "refused_without_llm": True,
        },
        {
            "id": "Q3",
            "type": "single_fact",
            "expected_behaviour": "answer",
            "router_enabled": False,
            "route_used": "SINGLE_SEARCH",
            "expected_route": "SINGLE_SEARCH",
            "route_correct": None,
            "is_refusal": False,
            "correct_refusal": 0.0,
            "false_refusal": 0.0,
            "leaked": 0.0,
            "recall@1": 1.0,
            "recall@3": 1.0,
            "recall@5": 1.0,
            "mrr": 1.0,
            "ndcg@5": 1.0,
            "answer_correctness": 0.95,
            "citation_validity": 1.0,
            "citation_support": 1.0,
            "faithfulness": None,
            "context_precision": None,
            "latency_ms": 1.0,
            "live_calls": 0,
            "cached_calls": 1,
            "live_tokens": 0,
            "cached_tokens": 110,
            "refused_without_llm": False,
        },
    ]

    agg_a0 = aggregate_ablation_rows(spec_a0, sample_rows)
    assert agg_a0["metrics"]["routing_accuracy"] is None  # Must be None, not 0.6!
    assert agg_a0["metrics"]["live_calls_per_query"] == pytest.approx(1 / 3, abs=0.01)
    assert agg_a0["metrics"]["cached_calls_per_query"] == pytest.approx(1 / 3, abs=0.01)
    assert agg_a0["metrics"]["refusals_without_llm"] == 1
    assert agg_a0["metrics"]["live_tokens_per_query"] == pytest.approx(40.0)

    # When router is ON and items have route_correct values
    sample_rows_a3 = [dict(r, router_enabled=True, route_correct=1.0) for r in sample_rows]
    agg_a3 = aggregate_ablation_rows(spec_a3, sample_rows_a3)
    assert agg_a3["metrics"]["routing_accuracy"] == 1.0

    # In markdown output, None must render as "n/a"
    mock_payload = {
        "llm_profile": "mock",
        "llm_model": "mock",
        "harness_mode_banner": "HARNESS CHECK",
        "date": "2026-11-12",
        "questions_evaluated": 3,
        "configurations": [agg_a0, agg_a3],
    }
    md_text = generate_markdown_table(mock_payload)
    assert "| `A0_baseline` |" in md_text
    assert "n/a" in md_text


def test_final_ablation_requires_reviewed_gate(tmp_path: Path) -> None:
    from scripts.run_ablation import enforce_reviewed_gate
    from src.evaluation.gold_set import InsufficientReviewedQuestionsError

    draft_items = [
        GoldQuestionItem(
            id=f"Q-{i}",
            question=f"Question {i}?",
            type="single_fact",
            role_asking="analyst",
            gold_chunk_ids=["DOC-BASEL-III-2023_BASEL-CAP-1.1"],
            gold_doc="DOC-BASEL-III-2023",
            clause="BASEL-CAP-1.1",
            gold_answer="Answer.",
            expected_behaviour="answer",
            status="draft",
        )
        for i in range(10)
    ]

    p = tmp_path / "gold.jsonl"
    p.write_text("\n".join(json.dumps(it.model_dump()) for it in draft_items), encoding="utf-8")

    # Refuses when 0 reviewed items exist
    with pytest.raises(InsufficientReviewedQuestionsError, match="Final ablation refused"):
        enforce_reviewed_gate(p, draft_items, min_reviewed=5)

    # Passes when >= min_reviewed items are reviewed
    for it in draft_items[:5]:
        it.status = "reviewed"
    p.write_text("\n".join(json.dumps(it.model_dump()) for it in draft_items), encoding="utf-8")
    reviewed_only = enforce_reviewed_gate(p, draft_items, min_reviewed=5)
    assert len(reviewed_only) == 5
    assert all(it.status == "reviewed" for it in reviewed_only)


def test_corpus_manifest_validator(tmp_path: Path) -> None:
    from scripts.corpus_manifest import inspect_document, add_template_sidecar
    from src.ingestion.chunker import ClauseAwareChunker

    # Document missing sidecar
    test_doc = tmp_path / "TEST-DOC.md"
    test_doc.write_text("# Test Document\n\n### Clause 1.1\nSome regulatory content.", encoding="utf-8")

    chunker = ClauseAwareChunker()
    res = inspect_document(test_doc, chunker)
    assert res["is_complete"] is False
    assert "source" in res["missing_fields"]

    # Generate template
    sidecar_p = add_template_sidecar(test_doc)
    assert sidecar_p.is_file()

    # Now inspect again
    res2 = inspect_document(test_doc, chunker)
    assert res2["is_complete"] is True
    assert res2["chunk_count"] >= 1

