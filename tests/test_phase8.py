"""Phase 8 verification tests: integrity fixes, citation cards, stretch features, and UI truth."""

from __future__ import annotations

import pickle
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.ingestion.chunker import (
    HTML_TAG_RE,
    MD_HEADING_PREFIX_RE,
    ClauseAwareChunker,
    DocumentChunk,
)
from src.ingestion.loaders import DocumentLoader, LoadedDocument, LoadedPage
from src.ingestion.run import discover_documents


def test_8a1_chunker_strips_html_tags_and_markdown_headings() -> None:
    """Chunker must strip HTML tags and markdown heading markers from chunk text and headings."""
    doc = LoadedDocument(
        file_path="synthetic.md",
        doc_id="DOC-TEST",
        title="Test Regulation",
        pages=[
            LoadedPage(
                page_number=1,
                content=(
                    "# Main Document Title\n"
                    "## Section 1: Customer Checks\n"
                    "### Clause 1.1\n"
                    "<div class=\"internal-badge\">Restricted</div> Firms must verify identity.\n"
                    "<script>alert('xss')</script>Ongoing monitoring is mandatory.\n"
                ),
            )
        ],
        allowed_roles=["analyst", "manager", "auditor"],
    )
    chunks = ClauseAwareChunker().chunk_document(doc)
    assert chunks, "Expected at least one chunk"
    for chunk in chunks:
        assert not HTML_TAG_RE.search(chunk.text_content), chunk.text_content
        assert not MD_HEADING_PREFIX_RE.search(chunk.text_content), chunk.text_content
        assert not HTML_TAG_RE.search(chunk.heading_path), chunk.heading_path


def test_8a1_corpus_chunks_and_bm25_contain_no_html_or_md_headings() -> None:
    """Full corpus chunks and persisted BM25 index must contain zero HTML tags or # headings."""
    paths = discover_documents("data")
    assert paths, "Expected corpus files under data/raw and data/synthetic"
    chunker = ClauseAwareChunker()
    for path in paths:
        doc = DocumentLoader.load(path)
        for chunk in chunker.chunk_document(doc):
            assert not HTML_TAG_RE.search(chunk.text_content), f"{path.name}: {chunk.text_content[:120]}"
            assert not MD_HEADING_PREFIX_RE.search(chunk.text_content), (
                f"{path.name}: {chunk.text_content[:120]}"
            )

    bm25_path = Path("data/bm25_index.pkl")
    if bm25_path.exists():
        with open(bm25_path, "rb") as handle:
            payload = pickle.load(handle)
        for row in payload.get("chunks", []):
            txt = str(row.get("text_content", ""))
            assert not HTML_TAG_RE.search(txt), f"HTML tag in BM25 chunk {row.get('chunk_id')}"
            assert not MD_HEADING_PREFIX_RE.search(txt), (
                f"Markdown heading in BM25 chunk {row.get('chunk_id')}"
            )


# ==============================================================================
# Phase 8A.2 — Spend Guard (Mock Bypass, Per-Query + Session Caps, Reset UI)
# ==============================================================================
def test_8a2_mock_does_not_count_or_enforce_max_calls_per_run() -> None:
    """In mock/offline profiles, LLM_MAX_CALLS_PER_RUN is neither counted nor enforced."""
    from src.core.spend_guard import SpendGuard

    guard = SpendGuard(max_calls=1, max_tokens=10, session_max_calls=2, session_max_tokens=20)
    for _ in range(10):
        guard.check_call_allowed(profile="mock", has_paid_quota=False, is_local=True, run_id="mock-sess")
        guard.reserve_call(profile="mock", has_paid_quota=False, is_local=True, run_id="mock-sess")
        guard.commit_usage(50, 50, profile="mock", has_paid_quota=False, is_local=True, run_id="mock-sess")

    snap = guard.status(profile="mock", has_paid_quota=False, is_local=True, run_id="mock-sess")
    assert snap.exhausted is False
    assert snap.paid_calls == 0
    assert snap.paid_tokens == 0
    assert snap.calls_limit == 0
    assert snap.tokens_limit == 0
    assert snap.tokens_estimated is True
    assert snap.offline_calls == 10
    assert snap.offline_tokens == 1000


def test_8a2_live_budget_resets_per_query_and_enforces_session_cap() -> None:
    """Live profiles reset per-query cap cleanly via begin_query while tracking cumulative session cap."""
    from src.core.spend_guard import CallCapExceededError, SpendGuard

    guard = SpendGuard(max_calls=2, max_tokens=5000, session_max_calls=3, session_max_tokens=10_000)
    rid = "live-sess-01"

    # Query 1 consumes 2 calls (per-query limit) -> Query 2 works after begin_query
    guard.begin_query(rid)
    for _ in range(2):
        guard.reserve_call(profile="demo", has_paid_quota=True, is_local=False, run_id=rid)
        guard.commit_usage(10, 10, profile="demo", has_paid_quota=True, is_local=False, run_id=rid)
    with pytest.raises(CallCapExceededError):
        guard.check_call_allowed(profile="demo", has_paid_quota=True, is_local=False, run_id=rid)

    # New query resets per-query counter, leaving 1 session call remaining (session cap = 3)
    guard.begin_query(rid)
    guard.reserve_call(profile="demo", has_paid_quota=True, is_local=False, run_id=rid)
    guard.commit_usage(10, 10, profile="demo", has_paid_quota=True, is_local=False, run_id=rid)

    # 4th call in session hits cumulative session cap
    guard.begin_query(rid)
    with pytest.raises(CallCapExceededError) as exc_info:
        guard.check_call_allowed(profile="demo", has_paid_quota=True, is_local=False, run_id=rid)
    assert "session" in str(exc_info.value).lower()
    assert "protect api quota" not in str(exc_info.value).lower()

    snap = guard.status(profile="demo", has_paid_quota=True, is_local=False, run_id=rid)
    assert snap.session_calls == 3
    assert snap.session_calls_limit == 3
    assert snap.tokens_estimated is False
    assert snap.exhausted is True


# ---------------------------------------------------------------------------
# Phase 8C: Stretch Features (claim_check, AST calculator, RBAC, ablation, gold_v2)
# ---------------------------------------------------------------------------
def test_phase8c_claim_check_scoring_removal_and_rbac():
    from src.core.claim_check import split_atomic_claims, verify_answer_claims

    passages = [
        {
            "chunk_id": "DOC-BASEL-III-2023_BASEL-CAP-1.1",
            "heading_path": "Part 1 · Clause BASEL-CAP-1.1",
            "text_content": (
                "Institutions must maintain at all times a minimum Common Equity Tier 1 (CET1) "
                "capital ratio of 4.5% of total risk-weighted assets (RWA)."
            ),
            "allowed_roles": ["analyst", "manager", "auditor"],
        },
        {
            "chunk_id": "DOC-INT-POL-MGT-002_POL-MGT-1.3",
            "heading_path": "Section 1 · Clause POL-MGT-1.3",
            "text_content": (
                "Any single compliance failure resulting in an unhedged financial exposure "
                "exceeding £500,000 triggers mandatory notification to SMF 16."
            ),
            "allowed_roles": ["manager", "auditor"],
        },
    ]

    answer = (
        "Institutions must maintain a minimum CET1 capital ratio of 4.5% of risk-weighted assets [1]. "
        "Banks must also hold a 99% emergency cryptocurrency reserve fund [99]."
    )
    claims = split_atomic_claims(answer)
    assert len(claims) == 2

    res_analyst = verify_answer_claims(answer, passages, role="analyst", rbac_enabled=True)
    assert res_analyst.rbac_dropped_passages == 1
    assert res_analyst.supported_count == 1
    assert res_analyst.unsupported_count == 1
    assert res_analyst.unsupported_claim_rate == 0.5
    assert "4.5%" in res_analyst.revised_answer
    assert "cryptocurrency" not in res_analyst.revised_answer

    # Manager-only fact must NOT be validated for analyst even if leaked in passages list
    restricted_claim = "Any unhedged financial exposure exceeding £500,000 triggers notification to SMF 16."
    analyst_restricted = verify_answer_claims(restricted_claim, passages, role="analyst", rbac_enabled=True)
    assert analyst_restricted.supported_count == 0
    assert analyst_restricted.unsupported_count == 1

    manager_allowed = verify_answer_claims(restricted_claim, passages, role="manager", rbac_enabled=True)
    assert manager_allowed.rbac_dropped_passages == 0
    assert manager_allowed.supported_count == 1
    assert manager_allowed.unsupported_count == 0


def test_phase8c_calculator_ast_whitelist_injection_and_rbac():
    from src.core.calculator import (
        UnsafeExpressionError,
        run_compliance_calculator,
        safe_eval_arithmetic,
    )

    assert safe_eval_arithmetic("4.5 + 2.5") == 7.0
    assert safe_eval_arithmetic("round((1000000 * 4.5) / 100, 2)") == 45000.0
    assert safe_eval_arithmetic("max(4.5, 6.0) - min(2.5, 1.0)") == 5.0

    injection_payloads = [
        "__import__('os').system('echo pwned')",
        "__import__('os')",
        "(1).__class__.__base__.__subclasses__()",
        "eval('1 + 1')",
        "exec('import os')",
        "open('C:/Windows/win.ini').read()",
        "1 / 0",
        "2 ** 1000",
        "min([1, 2], key=lambda x: x)",
    ]
    for expr in injection_payloads:
        with pytest.raises(UnsafeExpressionError):
            safe_eval_arithmetic(expr)

    passages = [
        {
            "chunk_id": "DOC-BASEL-III-2023_BASEL-CAP-1.1",
            "text_content": "Minimum Common Equity Tier 1 (CET1) capital ratio of 4.5% of RWA.",
            "allowed_roles": ["analyst", "manager", "auditor"],
        },
        {
            "chunk_id": "DOC-BASEL-III-2023_BASEL-CAP-2.1",
            "text_content": "Institutions must maintain a Capital Conservation Buffer (CCB) of 2.5% of RWA.",
            "allowed_roles": ["analyst", "manager", "auditor"],
        },
        {
            "chunk_id": "DOC-INT-POL-MGT-002_POL-MGT-1.3",
            "text_content": "Any compliance failure with unhedged financial exposure exceeding £500,000 triggers SMF 16 escalation.",
            "allowed_roles": ["manager", "auditor"],
        },
    ]

    calc_ok = run_compliance_calculator(
        "Calculate combined CET1 minimum and Capital Conservation Buffer.",
        passages,
        role="analyst",
    )
    assert calc_ok.triggered is True
    assert calc_ok.refused is False
    assert calc_ok.result == 7.0
    assert calc_ok.formatted_result == "7.0%"
    cited_ids = {i.chunk_id for i in calc_ok.inputs if i.chunk_id}
    assert cited_ids == {
        "DOC-BASEL-III-2023_BASEL-CAP-1.1",
        "DOC-BASEL-III-2023_BASEL-CAP-2.1",
    }

    # Missing operand causes explicit refusal rather than hallucination
    calc_missing = run_compliance_calculator(
        "Calculate combined CET1 minimum and NSFR ratio.",
        passages,
        role="analyst",
    )
    assert calc_missing.triggered is True
    assert calc_missing.refused is True
    assert "nsfr_minimum" in calc_missing.refusal_reason.lower()

    # RBAC blocks analyst from computing over manager-only threshold even if passage passed
    calc_analyst_restricted = run_compliance_calculator(
        "Calculate the excess over the internal unhedged exposure threshold for £750,000.",
        passages,
        role="analyst",
    )
    assert calc_analyst_restricted.triggered is True
    assert calc_analyst_restricted.refused is True
    assert "500000" not in str(calc_analyst_restricted.model_dump())

    calc_manager_ok = run_compliance_calculator(
        "Calculate the excess over the internal unhedged exposure threshold for £750,000.",
        passages,
        role="manager",
    )
    assert calc_manager_ok.triggered is True
    assert calc_manager_ok.refused is False
    assert calc_manager_ok.result == 250000.0
    assert calc_manager_ok.formatted_result == "£250,000"

    # Prompt injection through calculator query is refused safely
    calc_inject = run_compliance_calculator(
        "Calculate __import__('os').system('id')",
        passages,
        role="analyst",
    )
    assert calc_inject.triggered is True
    assert calc_inject.refused is True


def test_phase8c_gold_v2_and_ablation_metrics():
    import hashlib
    from pathlib import Path
    import json
    from src.evaluation.ablation import ABLATION_MATRIX, aggregate_ablation_rows
    from src.evaluation.gold_set import validate_gold_set_file
    from src.evaluation.metrics import numeric_exact_match

    orig_lines = Path("data/eval/gold_set.jsonl").read_text(encoding="utf-8").splitlines()
    v2_lines = Path("data/gold_v2.jsonl").read_text(encoding="utf-8").splitlines()
    v2_eval_lines = Path("data/eval/gold_v2.jsonl").read_text(encoding="utf-8").splitlines()
    v2_json = json.loads(Path("data/gold_v2.json").read_text(encoding="utf-8"))

    assert len(orig_lines) == 140
    assert len(v2_lines) == 115
    assert v2_lines[:100] == orig_lines[:100]
    assert v2_eval_lines == v2_lines
    assert len(v2_json) == 115

    orig_rows = [json.loads(line) for line in orig_lines]
    assert all(r.get("subset") == "original_100" for r in orig_rows[:100])
    assert all(
        r.get("subset") == "agent_extra_40"
        and r.get("authored_by") == "agent"
        and r.get("review_status") == "unreviewed_draft"
        and r.get("reviewed_by") is None
        for r in orig_rows[100:]
    )
    canonical_orig_100 = "\n".join(
        json.dumps({k: v for k, v in r.items() if k != "subset"}, sort_keys=True, ensure_ascii=False)
        for r in orig_rows[:100]
    )
    assert hashlib.sha256(canonical_orig_100.encode("utf-8")).hexdigest() == (
        "ea226229ff95684915465ec994346fd29aea555bec866d1d3bbd86f3469f6ffb"
    )

    report = validate_gold_set_file("data/eval/gold_v2.jsonl", min_per_type=0)
    assert report.valid is True
    assert not report.schema_errors
    assert not report.missing_chunk_errors

    assert "A6_claim_check" in ABLATION_MATRIX
    assert "A7_calculator" in ABLATION_MATRIX
    assert ABLATION_MATRIX["A0_baseline"].enable_claim_check is False
    assert ABLATION_MATRIX["A0_baseline"].enable_calculator is False
    assert ABLATION_MATRIX["A6_claim_check"].enable_claim_check is True
    assert ABLATION_MATRIX["A7_calculator"].enable_calculator is True

    assert numeric_exact_match("The combined ratio is 7.0%.", "Combined ratio is 7.0%.") == 1.0
    assert numeric_exact_match("The combined ratio is 5.0%.", "Combined ratio is 7.0%.") == 0.0
    assert numeric_exact_match(
        "Mock text", "Combined ratio is 7.0%.", {"triggered": True, "refused": False, "result": 7.0}
    ) == 1.0
    assert numeric_exact_match("Policy applies to firms.", "Policy applies to firms.") is None

    mock_row = {
        "id": "GS-101",
        "type": "cross_reference",
        "role_asking": "analyst",
        "expected_behaviour": "answer",
        "llm_profile": "mock",
        "llm_model": "mock-deterministic",
        "recall@1": 1.0,
        "recall@3": 1.0,
        "recall@5": 1.0,
        "mrr": 1.0,
        "ndcg@5": 1.0,
        "answer_correctness": 1.0,
        "citation_validity": 1.0,
        "citation_support": 1.0,
        "correct_refusal": 0.0,
        "false_refusal": 0.0,
        "leaked": 0.0,
        "unsupported_claim_rate": 0.0,
        "numeric_exact_match": 1.0,
        "latency_ms": 5.0,
    }
    agg = aggregate_ablation_rows(ABLATION_MATRIX["A7_calculator"], [mock_row])
    assert agg["evidence_status"] == "MOCK, not evidence"
    assert agg["metrics"]["unsupported_claim_rate"] == 0.0
    assert agg["metrics"]["numeric_exact_match"] == 1.0


def test_phase8c_pipeline_ui_and_audit_persistence(tmp_path):
    from contextlib import contextmanager
    import sqlite3
    from src.config import settings
    from src.db.migrations import SCHEMA_DDL, apply_migrations
    from src.db.repository import Repository
    from src.ingestion.indexer import BM25Indexer, SearchResult
    from src.rag.baseline import BaselineRAGPipeline, MockCrossEncoderReranker
    from src.core.llm_client import ResilientLLMClient

    # 1. Pipeline integration with ENABLE_CLAIM_CHECK=True & ENABLE_CALCULATOR=True (mock profile)
    chunks = [
        {
            "chunk_id": "DOC-BASEL-III-2023_BASEL-CAP-1.1",
            "doc_id": "DOC-BASEL-III-2023",
            "doc_title": "Basel III Framework",
            "section": "Capital",
            "heading_path": "Part 1 · BASEL-CAP-1.1",
            "clause": "BASEL-CAP-1.1",
            "page_number": 1,
            "allowed_roles": ["analyst", "manager", "auditor"],
            "text_content": "Minimum Common Equity Tier 1 (CET1) capital ratio of 4.5% of RWA.",
            "score": 0.95,
        },
        {
            "chunk_id": "DOC-BASEL-III-2023_BASEL-CAP-2.1",
            "doc_id": "DOC-BASEL-III-2023",
            "doc_title": "Basel III Framework",
            "section": "Capital",
            "heading_path": "Part 1 · BASEL-CAP-2.1",
            "clause": "BASEL-CAP-2.1",
            "page_number": 2,
            "allowed_roles": ["analyst", "manager", "auditor"],
            "text_content": "Capital Conservation Buffer (CCB) of 2.5% of total RWA.",
            "score": 0.90,
        },
    ]

    class _FakeIdx:
        def search(self, query: str, top_k: int = 10, role: str | None = None) -> SearchResult:
            return SearchResult(hits=chunks, considered=len(chunks), filtered=0)

    pipe = BaselineRAGPipeline(
        qdrant_indexer=_FakeIdx(),  # type: ignore[arg-type]
        bm25_indexer=_FakeIdx(),  # type: ignore[arg-type]
        reranker=MockCrossEncoderReranker(),  # type: ignore[arg-type]
        llm=ResilientLLMClient(),
    )

    prev_claim, prev_calc, prev_prof = (
        settings.ENABLE_CLAIM_CHECK,
        settings.ENABLE_CALCULATOR,
        settings.LLM_PROFILE,
    )
    try:
        settings.LLM_PROFILE = "mock"
        settings.ENABLE_CLAIM_CHECK = True
        settings.ENABLE_CALCULATOR = True
        resp = pipe.ask("Calculate combined CET1 minimum and Capital Conservation Buffer.", role="analyst")
        assert resp.claim_check is not None
        assert resp.calculator is not None
        assert resp.calculator["triggered"] is True
        assert resp.calculator["result"] == 7.0
        assert "7.0%" in resp.answer
    finally:
        settings.ENABLE_CLAIM_CHECK = prev_claim
        settings.ENABLE_CALCULATOR = prev_calc
        settings.LLM_PROFILE = prev_prof

    # 2. SQLite audit log persistence for claim_check_json & calculator_json
    db_file = tmp_path / "phase8c_audit.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_DDL)
    apply_migrations(conn)
    repo = Repository(conn)
    uid = repo.create_user("alice", "pw", "analyst", "Alice Analyst", "alice@example.com")
    sid = "sess-8c"
    repo.create_session(sid, uid, title="8c")
    aid = repo.create_audit_log(
        session_id=sid,
        user_id=uid,
        user_role="analyst",
        query_text="Calculate CET1 + CCB",
        final_route="SINGLE_SEARCH",
        retrieved_chunk_ids=["DOC-BASEL-III-2023_BASEL-CAP-1.1"],
        relevance_scores=[0.95],
        response_text="7.0%",
        latency_ms=12.0,
        claim_check_json=resp.claim_check,
        calculator_json=resp.calculator,
    )
    row = conn.execute("SELECT claim_check_json, calculator_json FROM audit_log WHERE id = ?", (aid,)).fetchone()
    assert row is not None
    assert "7.0" in str(row["calculator_json"])
    assert "claims" in str(row["claim_check_json"])
    conn.close()



