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


# ==============================================================================
# Phase 8A.3 — Profile Truth & XAI Flag Gating
# ==============================================================================
def test_8a3_ui_sidebar_flags_equal_loaded_config_and_hide_xai_when_off(
    auth_headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UI sidebar displays the exact loaded config flags; XAI OFF hides trace and XAI-only fields."""
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.config import settings

    monkeypatch.setattr(settings, "ENABLE_ADAPTIVE_ROUTER", True)
    monkeypatch.setattr(settings, "ENABLE_CORRECTIVE_GRADER", False)
    monkeypatch.setattr(settings, "ENABLE_MEMORY", True)
    monkeypatch.setattr(settings, "ENABLE_XAI_OUTPUT", False)
    monkeypatch.setattr(settings, "ENABLE_HEADING_PATH", True)
    monkeypatch.setattr(settings, "ENABLE_CLAIM_CHECK", False)
    monkeypatch.setattr(settings, "ENABLE_CALCULATOR", False)

    api = TestClient(app)
    headers = auth_headers("analyst")
    cfg_resp = api.get("/api/v1/admin/config", headers=headers)
    assert cfg_resp.status_code == 200
    loaded_cfg = cfg_resp.json()
    expected_layers = {
        "adaptive_router": True,
        "corrective_grader": False,
        "rbac": True,
        "memory": True,
        "xai_output": False,
        "heading_path": True,
        "claim_check": False,
        "calculator": False,
    }
    assert loaded_cfg["layers"] == expected_layers

    # Verify /api/v1/chat/query also echoes exact active_layers
    sess_id = api.post("/api/v1/sessions", json={"title": "Flag Truth"}, headers=headers).json()["id"]
    q_resp = api.post(
        "/api/v1/chat/query",
        json={"session_id": sess_id, "query": "What is CET1 under Basel III?"},
        headers=headers,
    )
    assert q_resp.status_code == 200
    q_body = q_resp.json()
    assert q_body["active_layers"] == expected_layers

    # Feed exact loaded config + response into UI AppTest and verify parity
    client = _make_mock_client("analyst")
    client.get_admin_config.return_value = loaded_cfg
    at = AppTest.from_file("src/ui/app.py")
    at.session_state["api_client"] = client
    at.session_state["access_token"] = "tok-analyst"
    at.session_state["user"] = {"id": 1, "username": "analyst_user", "role": "analyst", "full_name": "Alex Analyst"}
    at.session_state["sessions"] = [{"id": sess_id, "title": "Flag Truth"}]
    at.session_state["active_session_id"] = sess_id
    at.session_state["messages"] = [
        {"id": 1, "sender": "user", "content": "What is CET1 under Basel III?"},
        {"id": 2, "sender": "assistant", "content": q_body["answer"]},
    ]
    at.session_state["turn_details"] = {
        2: {
            **q_body,
            "citations_dropped": 2,
            "reasoning_trace": ["Step 1: Should NOT be visible when xai_output is OFF."],
        }
    }
    at.run()

    assert not at.exception
    rendered = _collect_all_markdowns(at)
    for layer_name, enabled in expected_layers.items():
        expected_state = "ON" if enabled else "OFF"
        assert f"`{layer_name}`: **{expected_state}**" in rendered

    # XAI OFF -> trace expander label & XAI-only fields must not be rendered
    assert "Should NOT be visible when xai_output is OFF" not in rendered
    assert "Dropped Invalid Citations" not in rendered
    expander_labels = [exp.label for exp in at.expander]
    assert not any("Reasoning Trace" in lbl for lbl in expander_labels)


# ==============================================================================
# Phase 8A.4 — Login Leakage Status & DEMO_MODE Gating
# ==============================================================================
def test_8a4_login_leakage_status_reads_report_or_shows_not_yet_measured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Login page reads reports/leakage_*.json instead of hardcoding '0.00% leakage'."""
    import json
    from src.ui.app import get_latest_leakage_status
    import src.ui.app as ui_app

    assert get_latest_leakage_status(tmp_path) == "not yet measured"

    # When cwd has no reports folder, login shows 'not yet measured'
    monkeypatch.chdir(tmp_path)
    client = _make_mock_client("analyst")
    at = AppTest.from_file(str(Path(ui_app.__file__).resolve()))
    at.session_state["api_client"] = client
    at.run()
    assert not at.exception
    rendered_no_report = _collect_all_markdowns(at)
    assert "not yet measured" in rendered_no_report
    assert "strictly 0.00% leakage" not in rendered_no_report

    # Add a leakage report file and verify rate + timestamp render on login card
    rep_dir = tmp_path / "reports"
    rep_dir.mkdir(parents=True, exist_ok=True)
    (rep_dir / "leakage_20261113T120000Z.json").write_text(
        json.dumps({"leakage_rate_pct": 0.0, "timestamp": "2026-11-13T12:00:00+00:00"}),
        encoding="utf-8",
    )
    at2 = AppTest.from_file(str(Path(ui_app.__file__).resolve()))
    at2.session_state["api_client"] = client
    at2.run()
    assert not at2.exception
    rendered_with_report = _collect_all_markdowns(at2)
    assert "0.00% leakage" in rendered_with_report
    assert "2026-11-13T12:00:00+00:00" in rendered_with_report


def test_8a4_quick_fill_persona_buttons_only_when_demo_mode_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Quick-fill persona buttons appear only when DEMO_MODE is True."""
    from src.config import settings

    client = _make_mock_client("analyst")

    monkeypatch.setattr(settings, "DEMO_MODE", False)
    at_off = AppTest.from_file("src/ui/app.py")
    at_off.session_state["api_client"] = client
    at_off.run()
    assert not at_off.exception
    btn_keys_off = {b.key for b in at_off.button}
    assert "quick_analyst" not in btn_keys_off
    assert "quick_manager" not in btn_keys_off
    assert "quick_auditor" not in btn_keys_off

    monkeypatch.setattr(settings, "DEMO_MODE", True)
    at_on = AppTest.from_file("src/ui/app.py")
    at_on.session_state["api_client"] = client
    at_on.run()
    assert not at_on.exception
    btn_keys_on = {b.key for b in at_on.button}
    assert "quick_analyst" in btn_keys_on
    assert "quick_manager" in btn_keys_on
    assert "quick_auditor" in btn_keys_on


# ==============================================================================
# Phase 8B — Citation Card Redesign Golden Tests
# ==============================================================================
def test_8b_golden_public_and_internal_citation_cards_order_and_content() -> None:
    """Golden-render test verifying exact order and fields for public and internal citation cards."""
    from src.ui.app import format_answer_with_citation_markers, render_citation_card_html

    public_cite = {
        "doc_id": "DOC-BASEL-01",
        "chunk_id": "CH-BASEL-49",
        "doc_title": "Basel III: A Global Regulatory Framework",
        "heading_path": "Part 2 > Para 49 > Minimum Capital Requirements",
        "clause": "Para 49",
        "page": 14,
        "quote_snippet": "Banks must hold a minimum CET1 ratio at all times. Common Equity Tier 1 must be at least 4.5% of risk-weighted assets.",
        "is_internal": False,
        "source_name": "Basel Committee (BIS)",
        "source_url": "https://www.bis.org/publ/bcbs189.pdf",
        "verification_url": "https://www.google.com/search?q=Basel+III+Para+49",
        "allowed_roles": ["analyst", "manager", "auditor"],
    }
    internal_cite = {
        "doc_id": "DOC-POL-MGT",
        "chunk_id": "CH-POL-MGT-13",
        "doc_title": "Bank Internal Management Policy: Regulatory Incident Escalation",
        "heading_path": "Section 1 > Threshold for Senior Management Regime Escalation",
        "clause": "POL-MGT-1.3",
        "page": 3,
        "quote_snippet": "### Clause Heading\nThresholds breached above tier two require immediate notification. Any material breach requires Senior Management Regime escalation within 24 hours.",
        "is_internal": True,
        "allowed_roles": ["manager", "auditor"],
    }

    pub_html = render_citation_card_html(
        public_cite, index=1, role="analyst", query="minimum CET1 ratio", msg_id=42
    )
    int_html = render_citation_card_html(
        internal_cite, index=2, role="manager", query="Senior Management Regime escalation 24 hours", msg_id=42
    )

    # Golden assertions for PUBLIC card & strict element order:
    assert "Basel III: A Global Regulatory Framework" in pub_html
    assert "Part 2 · Para 49 · Minimum Capital Requirements" in pub_html
    assert "Public · verifiable" in pub_html
    assert "Open Source ↗" in pub_html
    assert "Verify on Google ↗" in pub_html
    assert "Clause:" not in pub_html
    assert "Heading Path:" not in pub_html
    assert "<code>" not in pub_html
    assert '<mark class="cite-match">' in pub_html
    assert "<details class=\"tech-details\"><summary>Technical details</summary>" in pub_html
    assert "DOC-BASEL-01" in pub_html
    assert "Page 14" in pub_html
    assert "CH-BASEL-49" in pub_html
    assert (
        pub_html.index("Basel III: A Global Regulatory Framework")
        < pub_html.index("Part 2 · Para 49")
        < pub_html.index("Public · verifiable")
        < pub_html.index("<blockquote")
        < pub_html.index("<details class=\"tech-details\">")
    )

    # Golden assertions for INTERNAL card & strict element order:
    assert "Bank Internal Management Policy: Regulatory Incident Escalation" in int_html
    assert "Section 1 · Clause POL-MGT-1.3 · Threshold for Senior Management Regime Escalation" in int_html
    assert "<svg" in int_html  # lock icon
    assert "Internal · visible to Manager, Auditor" in int_html
    assert "no public verification link" not in int_html.lower()
    assert "no verification link" not in int_html.lower()
    assert "###" not in int_html
    assert "Clause:" not in int_html
    assert "Heading Path:" not in int_html
    assert '<mark class="cite-match">Any material breach requires Senior Management Regime escalation within 24 hours.</mark>' in int_html
    assert (
        int_html.index("Bank Internal Management Policy: Regulatory Incident Escalation")
        < int_html.index("Section 1 · Clause POL-MGT-1.3")
        < int_html.index("Internal · visible to Manager, Auditor")
        < int_html.index("<blockquote")
        < int_html.index("<details class=\"tech-details\">")
    )

    # Inline citation markers link cleanly to card IDs [1], [2]
    linked = format_answer_with_citation_markers(
        "CET1 must be 4.5% [1] and material breaches escalate in 24h [2].",
        [public_cite, internal_cite],
        msg_id=42,
    )
    assert 'href="#cite-card-42-1"' in linked
    assert 'href="#cite-card-42-2"' in linked
    assert 'class="cite-marker"' in linked
