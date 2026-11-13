"""Phase 8 Streamlit AppTest Suite for Enterprise Banking Regulatory Compliance UI.

Uses ``streamlit.testing.v1.AppTest`` to run fully offline without a browser against
a mock ``ComplianceAPIClient``. Verifies:
1. Login screen renders and displays health & profile warning badges
2. Login failure displays sanitized error message
3. Login success transitions to compliance chat and loads sessions
4. Unauthorized role (analyst/manager) cannot access auditor view
5. Auditor role accesses sanitized audit log summaries with 0.00% leakage KPI
6. Expired token (HTTP 401) clears auth state and redirects to login
7. Refusal state renders distinct refusal card with uniform wording
8. Long multi-clause answers render cleanly with citations panel
9. Backend API down displays actionable warning
10. Session creation, selection, and deletion lifecycle
11. Demo preset buttons trigger queries through the client
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
from streamlit.testing.v1 import AppTest

from src.ui.api_client import ComplianceAPIClient, UIApiError


def _make_mock_client(role: str = "analyst") -> MagicMock:
    """Build a standard mock ComplianceAPIClient."""
    mock = MagicMock(spec=ComplianceAPIClient)
    mock.get_health.return_value = {
        "status": "ok",
        "llm": {"profile": "mock", "model": "mock-deterministic"},
        "vector_store": {"total_vectors": 26},
    }
    mock.list_demo_users.return_value = [
        {"username": "analyst_user", "role": "analyst", "full_name": "Alex Analyst"},
        {"username": "manager_user", "role": "manager", "full_name": "Morgan Manager"},
        {"username": "auditor_user", "role": "auditor", "full_name": "Aubrey Auditor"},
    ]
    mock.login.return_value = {
        "access_token": f"tok-{role}",
        "token_type": "bearer",
        "user": {
            "id": 1 if role == "analyst" else (2 if role == "manager" else 3),
            "username": f"{role}_user",
            "full_name": f"{role.title()} User",
            "role": role,
        },
    }
    mock.get_me.return_value = {
        "id": 1 if role == "analyst" else (2 if role == "manager" else 3),
        "username": f"{role}_user",
        "full_name": f"{role.title()} User",
        "role": role,
    }
    mock.list_sessions.return_value = [
        {"id": "sess-001", "title": "Basel Capital Adequacy", "created_at": "2026-11-13T00:00:00Z"}
    ]
    mock.create_session.return_value = {
        "id": "sess-002",
        "title": "New Compliance Session",
        "created_at": "2026-11-13T00:01:00Z",
    }
    mock.get_admin_config.return_value = {
        "profile": "mock",
        "model": "mock-deterministic",
        "prompt_version": "v1",
        "layers": {
            "server_side_rbac": True,
            "session_memory": True,
            "adaptive_router": True,
            "corrective_grader": True,
            "xai_output": True,
            "heading_path_citations": True,
        },
        "spend_caps": {"calls_limit": 50, "tokens_limit": 25000},
    }
    mock.get_session_messages.return_value = []
    mock.ask_chat_query.return_value = {
        "session_id": "sess-001",
        "answer": "Minimum CET1 capital ratio is 4.5% under Basel III.",
        "route_taken": "SINGLE_SEARCH",
        "route": "SINGLE_SEARCH",
        "grader_path": "graded_pass",
        "latency_ms": 142.5,
        "citations": [
            {
                "chunk_id": "CH-001",
                "doc_title": "Basel III Capital Accord",
                "heading_path": "Part 2 > Capital Requirements > CET1",
                "clause": "Para 49",
                "page": 14,
                "quote_snippet": "Common Equity Tier 1 must be at least 4.5% of risk-weighted assets at all times.",
            }
        ],
        "reasoning_trace": [
            "1. Role Verification: analyst permissions confirmed",
            "2. Query Classification: SINGLE_SEARCH route selected",
            "3. Server-Side RBAC: Qdrant filtered to allowed_roles",
            "4. Cross-Encoder Re-Ranking applied",
            "5. Corrective Grader: 1 relevant passage confirmed",
            "6. Answer Generation & Citation Validation complete",
        ],
    }
    mock.get_audit_logs.return_value = [
        {
            "audit_id": 101,
            "created_at": "2026-11-13T00:00:00Z",
            "user_role": "analyst",
            "final_route": "SINGLE_SEARCH",
            "retrieved_chunk_ids": ["CH-001"],
            "citation_count": 1,
            "citations_dropped": 0,
            "heading_path_enabled": True,
            "candidates_filtered": 4,
            "latency_ms": 142.5,
            "llm_profile": "mock",
        }
    ]
    return mock


def _collect_all_markdowns(at: AppTest) -> str:
    """Collect markdown values across root level and all nested chat messages."""
    items = [m.value for m in at.markdown]
    for cm in at.chat_message:
        items.extend(m.value for m in cm.markdown)
    return " ".join(items)


def test_login_screen_renders_unauthenticated_and_shows_health_badge() -> None:
    """Unauthenticated access displays login form with model/profile badge."""
    client = _make_mock_client("analyst")
    at = AppTest.from_file("src/ui/app.py")
    at.session_state["api_client"] = client
    at.run()

    assert not at.exception
    # Profile warning badge rendered because profile is 'mock' (not demo)
    all_text = _collect_all_markdowns(at)
    assert "Enterprise Banking Regulatory Compliance Assistant" in all_text
    assert "OFFLINE MOCK" in all_text
    assert "Indexed Chunks: 26" in all_text
    # Login inputs exist
    assert any(inp.label == "Username" for inp in at.text_input)
    assert any(inp.label == "Password" for inp in at.text_input)


def test_login_failure_displays_error() -> None:
    """Invalid credentials display sanitized system error notice."""
    client = _make_mock_client("analyst")
    client.login.side_effect = UIApiError(401, "UNAUTHENTICATED", "Invalid compliance credentials.")
    at = AppTest.from_file("src/ui/app.py")
    at.session_state["api_client"] = client
    at.run()

    # Input invalid credentials and submit form
    at.text_input[0].input("analyst_user")
    at.text_input[1].input("bad-pass")
    at.button[0].click()  # Sign In button
    at.run()

    assert not at.exception
    assert at.session_state["access_token"] is None
    # Error displayed
    assert len(at.error) > 0
    assert "Invalid compliance credentials" in at.error[0].value


def test_login_success_populates_sessions_and_transitions_to_chat() -> None:
    """Valid credentials set access token and transition to compliance chat workspace."""
    client = _make_mock_client("analyst")
    at = AppTest.from_file("src/ui/app.py")
    at.session_state["api_client"] = client
    at.run()

    # Enter valid credentials and submit
    at.text_input[0].input("analyst_user")
    at.text_input[1].input("valid-pass")
    at.button[0].click()
    at.run()

    assert not at.exception
    assert at.session_state["access_token"] == "tok-analyst"
    assert at.session_state["user"]["role"] == "analyst"
    assert len(at.session_state["sessions"]) == 1
    # Workspace header rendered
    all_text = _collect_all_markdowns(at)
    assert "Regulatory Compliance Workspace" in all_text
    assert "ROLE: ANALYST" in all_text


def test_unauthorized_role_cannot_access_auditor_view() -> None:
    """Analyst role has no workspace view radio, and forced audit view is blocked."""
    client = _make_mock_client("analyst")
    at = AppTest.from_file("src/ui/app.py")
    at.session_state["api_client"] = client
    at.session_state["access_token"] = "tok-analyst"
    at.session_state["user"] = {"id": 1, "username": "analyst_user", "role": "analyst", "full_name": "Alex Analyst"}
    at.session_state["sessions"] = [{"id": "sess-001", "title": "Basel Capital"}]
    at.session_state["active_session_id"] = "sess-001"
    at.run()

    assert not at.exception
    # Radio switcher is not rendered for analyst
    assert len(at.radio) == 0

    # Even if active_view is injected as 'audit', main() guards against it
    at.session_state["active_view"] = "audit"
    at.run()
    assert not at.exception
    all_text = _collect_all_markdowns(at)
    # Renders chat workspace instead, not auditor summary
    assert "Regulatory Compliance Workspace" in all_text
    assert "Auditor Compliance & RBAC Summary View" not in all_text


def test_auditor_role_accesses_sanitized_audit_logs_with_zero_leakage_kpi() -> None:
    """Auditor role can switch to audit view and inspect summaries with 0.00% leakage rate."""
    client = _make_mock_client("auditor")
    at = AppTest.from_file("src/ui/app.py")
    at.session_state["api_client"] = client
    at.session_state["access_token"] = "tok-auditor"
    at.session_state["user"] = {"id": 3, "username": "auditor_user", "role": "auditor", "full_name": "Aubrey Auditor"}
    at.session_state["sessions"] = [{"id": "sess-001", "title": "Audit Review"}]
    at.session_state["active_session_id"] = "sess-001"
    at.session_state["active_view"] = "audit"
    at.run()

    assert not at.exception
    all_text = _collect_all_markdowns(at)
    assert "Auditor Compliance & RBAC Summary View" in all_text
    assert "SUMMARIES ONLY — ZERO CONVERSATION TEXT EXPOSED" in all_text
    # Verify 0.00% leakage KPI metric is present
    metrics = [m.value for m in at.metric]
    assert "0.00%" in metrics


def test_expired_token_redirects_to_login() -> None:
    """HTTP 401 response from backend clears session state and forces re-login."""
    client = _make_mock_client("analyst")
    client.ask_chat_query.side_effect = UIApiError(401, "UNAUTHENTICATED", "Token expired.")

    at = AppTest.from_file("src/ui/app.py")
    at.session_state["api_client"] = client
    at.session_state["access_token"] = "tok-expired"
    at.session_state["user"] = {"id": 1, "username": "analyst_user", "role": "analyst", "full_name": "Alex Analyst"}
    at.session_state["sessions"] = [{"id": "sess-001", "title": "Session"}]
    at.session_state["active_session_id"] = "sess-001"
    at.run()

    # Submit query through chat_input
    at.chat_input[0].set_value("What is CET1?").run()

    assert at.session_state["access_token"] is None
    assert at.session_state["user"] is None


def test_refusal_state_displays_refusal_card() -> None:
    """Refusal turns render the distinct refusal card with category and uniform wording."""
    client = _make_mock_client("analyst")
    at = AppTest.from_file("src/ui/app.py")
    at.session_state["api_client"] = client
    at.session_state["access_token"] = "tok-analyst"
    at.session_state["user"] = {"id": 1, "username": "analyst_user", "role": "analyst", "full_name": "Alex Analyst"}
    at.session_state["sessions"] = [{"id": "sess-001", "title": "Refusal Test"}]
    at.session_state["active_session_id"] = "sess-001"
    at.session_state["messages"] = [
        {"id": 1, "sender": "user", "content": "What did the confidential audit conclude?"},
        {
            "id": 2,
            "sender": "assistant",
            "content": "I cannot find sufficient evidence in the authoritative documents available to your role to answer this question.",
        },
    ]
    at.session_state["turn_details"] = {
        2: {
            "session_id": "sess-001",
            "answer": "I cannot find sufficient evidence in the authoritative documents available to your role to answer this question.",
            "refusal_category": "role_restricted",
            "route_taken": "SINGLE_SEARCH",
            "route": "SINGLE_SEARCH",
            "citations": [],
            "latency_ms": 110.0,
        }
    }
    at.run()

    assert not at.exception
    all_text = _collect_all_markdowns(at)
    assert "COMPLIANCE REFUSAL" in all_text
    assert "Category: role_restricted" in all_text
    assert "Server-side role filters (Qdrant & BM25)" in all_text


def test_long_answer_renders_cleanly_with_citations() -> None:
    """Long multi-paragraph answer with structured citations renders without error."""
    client = _make_mock_client("analyst")
    at = AppTest.from_file("src/ui/app.py")
    at.session_state["api_client"] = client
    at.session_state["access_token"] = "tok-analyst"
    at.session_state["user"] = {"id": 1, "username": "analyst_user", "role": "analyst", "full_name": "Alex Analyst"}
    at.session_state["sessions"] = [{"id": "sess-001", "title": "Detailed Answer"}]
    at.session_state["active_session_id"] = "sess-001"

    long_answer = (
        "Under Basel III capital adequacy guidelines, institutions must maintain a robust capital structure. "
        "First, Common Equity Tier 1 (CET1) capital must be at least 4.5% of total risk-weighted assets at all times. "
        "Second, Tier 1 capital must comprise at least 6.0% of risk-weighted assets. "
        "Third, total capital (Tier 1 plus Tier 2) must remain above the 8.0% minimum threshold. "
        "Furthermore, a capital conservation buffer of 2.5% comprised of CET1 is required above these regulatory minimums."
    )
    at.session_state["messages"] = [
        {"id": 1, "sender": "user", "content": "Explain all Basel III capital ratios."},
        {"id": 2, "sender": "assistant", "content": long_answer},
    ]
    at.session_state["turn_details"] = {
        2: {
            "session_id": "sess-001",
            "answer": long_answer,
            "route_taken": "SINGLE_SEARCH",
            "route": "SINGLE_SEARCH",
            "grader_path": "graded_pass",
            "latency_ms": 235.0,
            "citations": [
                {
                    "chunk_id": "CH-BASEL-01",
                    "doc_title": "Basel III Capital Accord",
                    "heading_path": "Part 2 > Capital Framework > CET1 Ratio",
                    "clause": "Para 49",
                    "page": 14,
                    "quote_snippet": "Common Equity Tier 1 must be at least 4.5% of risk-weighted assets.",
                },
                {
                    "chunk_id": "CH-BASEL-02",
                    "doc_title": "Basel III Capital Accord",
                    "heading_path": "Part 2 > Capital Framework > Tier 1 Ratio",
                    "clause": "Para 50",
                    "page": 15,
                    "quote_snippet": "Tier 1 capital must be at least 6.0% of risk-weighted assets.",
                },
            ],
            "reasoning_trace": [
                "1. Role Verification: analyst verified",
                "2. Adaptive Route: SINGLE_SEARCH",
                "3. Server RBAC: filtered to analyst permitted documents",
                "4. Re-ranker: ms-marco cross-encoder applied",
                "5. Corrective Grader: 2 passages graded relevant",
                "6. Citation validation: 2 valid citations retained",
            ],
        }
    }
    at.run()

    assert not at.exception
    all_text = _collect_all_markdowns(at)
    assert "Common Equity Tier 1 (CET1)" in all_text
    assert "Verified Authoritative Citations (2)" in all_text
    assert "CH-BASEL-01" in all_text
    assert "Capital Framework" in all_text


def test_backend_api_down_displays_warning() -> None:
    """When the FastAPI backend is down, UI renders an actionable warning banner."""
    client = _make_mock_client("analyst")
    client.get_health.side_effect = UIApiError(503, "BACKEND_UNREACHABLE", "Cannot reach backend")
    at = AppTest.from_file("src/ui/app.py")
    at.session_state["api_client"] = client
    at.run()

    assert not at.exception
    assert len(at.warning) > 0
    assert "Backend API is currently unreachable" in at.warning[0].value
    assert "uvicorn src.api.main:app" in at.warning[0].value


def test_session_create_open_and_delete() -> None:
    """Verify creating, selecting, and deleting compliance sessions in the sidebar."""
    client = _make_mock_client("analyst")
    client.list_sessions.return_value = [
        {"id": "sess-001", "title": "Basel Session"},
        {"id": "sess-002", "title": "AML Session"},
    ]
    at = AppTest.from_file("src/ui/app.py")
    at.session_state["api_client"] = client
    at.session_state["access_token"] = "tok-analyst"
    at.session_state["user"] = {"id": 1, "username": "analyst_user", "role": "analyst", "full_name": "Alex Analyst"}
    at.session_state["sessions"] = client.list_sessions()
    at.session_state["active_session_id"] = "sess-001"
    at.run()

    assert not at.exception
    # Delete sess-002 button exists
    del_btn = next((b for b in at.button if b.key == "del_sess-002"), None)
    assert del_btn is not None
    del_btn.click()
    at.run()

    assert not at.exception
    client.delete_session.assert_called_with("tok-analyst", "sess-002")


def test_demo_preset_triggers_query() -> None:
    """Clicking a demo preset button invokes ask_chat_query with the preset text."""
    client = _make_mock_client("analyst")
    at = AppTest.from_file("src/ui/app.py")
    at.session_state["api_client"] = client
    at.session_state["access_token"] = "tok-analyst"
    at.session_state["user"] = {"id": 1, "username": "analyst_user", "role": "analyst", "full_name": "Alex Analyst"}
    at.session_state["sessions"] = [{"id": "sess-001", "title": "Demo Session"}]
    at.session_state["active_session_id"] = "sess-001"
    at.run()

    assert not at.exception
    # Find demo preset button 1 (public)
    demo_btn = next((b for b in at.button if b.key == "demo_btn_public"), None)
    assert demo_btn is not None
    demo_btn.click()
    at.run()

    assert not at.exception
    client.ask_chat_query.assert_called_once()
    call_args = client.ask_chat_query.call_args
    assert "MLR 2017" in call_args.kwargs.get("query", "")


def test_citation_verifiable_links_and_internal_badge() -> None:
    """Public citations render verifiable source/google links while internal citations display an institutional badge."""
    client = _make_mock_client("manager")
    at = AppTest.from_file("src/ui/app.py")
    at.session_state["api_client"] = client
    at.session_state["access_token"] = "tok-manager"
    at.session_state["user"] = {"id": 2, "username": "mgr_user", "role": "manager", "full_name": "Morgan Manager"}
    at.session_state["sessions"] = [{"id": "sess-001", "title": "Verification Test"}]
    at.session_state["active_session_id"] = "sess-001"
    at.session_state["messages"] = [
        {"id": 1, "sender": "user", "content": "What is the policy?"},
        {"id": 2, "sender": "assistant", "content": "Summary of requirements."},
    ]
    at.session_state["turn_details"] = {
        2: {
            "session_id": "sess-001",
            "answer": "Summary of requirements.",
            "route": "SINGLE_SEARCH",
            "latency_ms": 110.0,
            "citations": [
                {
                    "chunk_id": "CH-PUB-01",
                    "doc_title": "Basel Framework",
                    "heading_path": "Part 1 > Capital",
                    "clause": "1.1",
                    "snippet": "Minimum ratio is 4.5%.",
                    "is_internal": False,
                    "source_url": "https://www.bis.org/bcbs/basel3.htm",
                    "verification_url": "https://www.google.com/search?q=Basel+Framework",
                    "source_name": "Basel Committee (BIS)",
                },
                {
                    "chunk_id": "CH-INT-02",
                    "doc_title": "Bank Internal Policy POL-042",
                    "heading_path": "Section 2 > Escalation",
                    "clause": "2.1",
                    "snippet": "Escalate to ExCo within 24 hours.",
                    "is_internal": True,
                    "source_name": "Internal Bank Policy",
                },
            ],
        }
    }
    at.run()

    assert not at.exception
    all_text = _collect_all_markdowns(at)
    # Check public citation link elements
    assert "Open Source ↗" in all_text
    assert "Verify on Google ↗" in all_text
    assert "Basel Committee (BIS)" in all_text
    # Check internal citation badge
    assert "Internal Document — No public verification link" in all_text


def test_unauthorized_citation_shows_access_warning() -> None:
    """A citation outside the caller's role renders a red unauthorized-access indicator."""
    client = _make_mock_client("analyst")
    at = AppTest.from_file("src/ui/app.py")
    at.session_state["api_client"] = client
    at.session_state["access_token"] = "tok-analyst"
    at.session_state["user"] = {"id": 1, "username": "analyst_user", "role": "analyst", "full_name": "Alex Analyst"}
    at.session_state["sessions"] = [{"id": "sess-001", "title": "Access Test"}]
    at.session_state["active_session_id"] = "sess-001"
    at.session_state["messages"] = [
        {"id": 1, "sender": "user", "content": "What did the audit find?"},
        {"id": 2, "sender": "assistant", "content": "Summary of findings."},
    ]
    at.session_state["turn_details"] = {
        2: {
            "session_id": "sess-001",
            "answer": "Summary of findings.",
            "route": "SINGLE_SEARCH",
            "latency_ms": 120.0,
            "citations": [
                {
                    "chunk_id": "CH-AUD-01",
                    "doc_title": "Internal Audit KYC Review AUD-2024-03",
                    "heading_path": "Part 9 > Findings",
                    "clause": "9.1",
                    "snippet": "Two control gaps were identified.",
                    "is_internal": True,
                    "allowed_roles": ["auditor"],
                    "source_name": "Internal Audit Findings",
                },
            ],
        }
    }
    at.run()

    assert not at.exception
    all_text = _collect_all_markdowns(at)
    assert "Unauthorized access" in all_text
    assert "restricted to Auditor" in all_text
    assert "Internal Document — No public verification link" not in all_text
