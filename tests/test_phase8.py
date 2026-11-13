"""Phase 8 verification tests: integrity fixes, citation cards, stretch features, and UI truth."""

from __future__ import annotations

import pickle
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from streamlit.testing.v1 import AppTest

from src.ingestion.chunker import (
    HTML_TAG_RE,
    MD_HEADING_PREFIX_RE,
    ClauseAwareChunker,
    DocumentChunk,
)
from src.ingestion.loaders import DocumentLoader, LoadedDocument, LoadedPage
from src.ingestion.run import discover_documents
from src.ui.app import sanitize_quote_for_display
from tests.test_ui_app import _collect_all_markdowns, _make_mock_client


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


def test_8a1_rendered_quote_escapes_html_and_never_leaks_internal_badge() -> None:
    """Rendered quote HTML escapes markup cleanly and never embeds internal badges inside quotes."""
    raw_snippet = '### Heading\n<div class="internal-badge">Fake</div> & <script>alert(1)</script> Clause body.'
    sanitized = sanitize_quote_for_display(raw_snippet)
    assert "<div" not in sanitized
    assert "<script>" not in sanitized
    assert "###" not in sanitized
    assert "&amp;" in sanitized

    client = _make_mock_client("manager")
    at = AppTest.from_file("src/ui/app.py")
    at.session_state["api_client"] = client
    at.session_state["access_token"] = "tok-manager"
    at.session_state["user"] = {
        "id": 2,
        "username": "mgr_user",
        "role": "manager",
        "full_name": "Morgan Manager",
    }
    at.session_state["sessions"] = [{"id": "sess-001", "title": "HTML Sanitization"}]
    at.session_state["active_session_id"] = "sess-001"
    at.session_state["messages"] = [
        {"id": 1, "sender": "user", "content": "Check escalation policy."},
        {"id": 2, "sender": "assistant", "content": "Escalate within 24 hours."},
    ]
    at.session_state["turn_details"] = {
        2: {
            "session_id": "sess-001",
            "answer": "Escalate within 24 hours.",
            "route": "SINGLE_SEARCH",
            "latency_ms": 95.0,
            "citations": [
                {
                    "chunk_id": "CH-HTML-01",
                    "doc_title": "Internal Policy",
                    "heading_path": "Section 1 > Clause 1.3",
                    "clause": "Clause 1.3",
                    "quote_snippet": 'Policy text with <img src=x onerror=alert(1)> and <div class="internal-badge">injected</div>.',
                    "is_internal": True,
                    "allowed_roles": ["manager", "auditor"],
                }
            ],
        }
    }
    at.run()

    assert not at.exception
    rendered = _collect_all_markdowns(at)
    assert "<img" not in rendered
    assert "onerror=" not in rendered
    # The badge element itself must not be indented >= 4 spaces into a CommonMark code block
    assert "                        <div class=\"internal-badge\">" not in rendered
    assert "    <div class=\"internal-badge\">" not in rendered


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


def test_8a2_ui_renders_human_budget_reset_and_estimated_mock_tokens() -> None:
    """UI removes 'System Notice', offers Reset budget on cap errors, and labels mock tokens estimated."""
    client = _make_mock_client("analyst")
    client.get_admin_config.return_value["spend_caps"] = {
        "calls_used": 4,
        "calls_limit": 0,
        "tokens_used": 320,
        "tokens_limit": 0,
        "tokens_estimated": 1,
        "exhausted": 0,
        "is_paid": 0,
    }
    at = AppTest.from_file("src/ui/app.py")
    at.session_state["api_client"] = client
    at.session_state["access_token"] = "tok-analyst"
    at.session_state["user"] = {"id": 1, "username": "analyst_user", "role": "analyst", "full_name": "Alex Analyst"}
    at.session_state["sessions"] = [{"id": "sess-001", "title": "Budget Session"}]
    at.session_state["active_session_id"] = "sess-001"
    at.session_state["last_error"] = "Spend guard cap exceeded to protect API quota."
    at.run()

    assert not at.exception
    rendered = _collect_all_markdowns(at)
    assert "System Notice" not in rendered
    assert "estimated tokens" in rendered.lower()
    assert any("reached its LLM budget" in w.value for w in at.warning)

    reset_btn = next((b for b in at.button if b.key == "error_reset_budget_btn"), None)
    assert reset_btn is not None
    reset_btn.click()
    at.run()

    assert not at.exception
    client.reset_session_run.assert_called_with("tok-analyst", "sess-001")
