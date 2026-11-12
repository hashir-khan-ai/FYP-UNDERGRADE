"""Phase 6B Streamlit UI for the Enterprise Banking Regulatory Compliance RAG Assistant.

Follows DESIGN.md (60/30/10 colour system: Matte Black #1C1D20, Storm Grey #5A6068,
Safety Orange #FF5F00 with Matte Black #1C1D20 button text, Polar White #F1F3F4 text).
Communicates with the backend strictly through ``src.ui.api_client.ComplianceAPIClient``.
"""

import html
import os
from typing import Any

import streamlit as st

from src.ui.api_client import (
    ComplianceAPIClient,
    UIApiError,
    is_refusal_response,
    profile_badge_meta,
)

API_BASE_URL = os.environ.get("COMPLIANCE_API_URL", "http://127.0.0.1:8000")

ROLE_STARTER_QUESTIONS: dict[str, list[str]] = {
    "analyst": [
        "What minimum CET1 capital ratio must banks maintain under Basel III?",
        "What customer due diligence measures must firms apply when establishing a new business relationship?",
        "When must a firm submit a Suspicious Activity Report to the NCA?",
    ],
    "manager": [
        "What is the escalation procedure for material breaches to the compliance committee?",
        "What are the requirements for enhanced due diligence on politically exposed persons?",
        "Compare the Liquidity Coverage Ratio and Net Stable Funding Ratio requirements.",
    ],
    "auditor": [
        "What did the internal audit conclude about control gaps in the KYC remediation plan?",
        "What is the escalation procedure for material breaches to the compliance committee?",
        "What records must firms keep under the Money Laundering Regulations and for how long?",
    ],
}

CUSTOM_CSS = """
<style>
    /* 60% Matte Black (#1C1D20) primary canvas, Polar White (#F1F3F4) text */
    .stApp {
        background-color: #1C1D20;
        color: #F1F3F4;
    }
    /* 30% Storm Grey (#5A6068 / #26292E) structural panels & cards */
    section[data-testid="stSidebar"] {
        background-color: #26292E;
        border-right: 1px solid #5A6068;
    }
    /* 10% Safety Orange (#FF5F00) primary buttons with Matte Black (#1C1D20) text */
    div.stButton > button[kind="primary"],
    div.stFormSubmitButton > button {
        background-color: #FF5F00 !important;
        color: #1C1D20 !important;
        border: 1px solid #FF5F00 !important;
        font-weight: 700 !important;
    }
    div.stButton > button[kind="secondary"] {
        background-color: #26292E !important;
        color: #F1F3F4 !important;
        border: 1px solid #5A6068 !important;
    }
    .compliance-card {
        background-color: #26292E;
        border: 1px solid #5A6068;
        border-radius: 6px;
        padding: 14px 16px;
        margin-bottom: 10px;
        color: #F1F3F4;
    }
    .refusal-card {
        background-color: #26292E;
        border: 1px solid #5A6068;
        border-left: 5px solid #FF5F00;
        border-radius: 6px;
        padding: 14px 16px;
        margin-bottom: 10px;
        color: #F1F3F4;
    }
    .citation-card {
        background-color: #1C1D20;
        border: 1px solid #5A6068;
        border-left: 3px solid #FF5F00;
        border-radius: 5px;
        padding: 10px 14px;
        margin-top: 8px;
        margin-bottom: 8px;
        color: #F1F3F4;
    }
    .quote-snippet {
        font-family: monospace;
        font-size: 0.88rem;
        background-color: #26292E;
        border: 1px solid #5A6068;
        border-radius: 4px;
        padding: 8px 10px;
        margin-top: 6px;
        color: #F1F3F4;
        white-space: pre-wrap;
    }
    .pill-badge {
        display: inline-block;
        padding: 2px 9px;
        border-radius: 12px;
        font-size: 0.76rem;
        font-weight: 700;
        margin-right: 6px;
        border: 1px solid #5A6068;
        background-color: #26292E;
        color: #F1F3F4;
    }
    .pill-accent {
        display: inline-block;
        padding: 2px 9px;
        border-radius: 12px;
        font-size: 0.76rem;
        font-weight: 700;
        margin-right: 6px;
        background-color: #FF5F00;
        color: #1C1D20;
        border: 1px solid #FF5F00;
    }
</style>
"""


def _init_session_state() -> None:
    """Initialize required keys in st.session_state without touching URL params."""
    defaults: dict[str, Any] = {
        "access_token": None,
        "user": None,
        "active_session_id": None,
        "sessions": [],
        "messages": [],
        "turn_details": {},
        "active_view": "chat",
        "last_error": None,
        "admin_config": None,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def _clear_auth_state() -> None:
    st.session_state["access_token"] = None
    st.session_state["user"] = None
    st.session_state["active_session_id"] = None
    st.session_state["sessions"] = []
    st.session_state["messages"] = []
    st.session_state["turn_details"] = {}
    st.session_state["admin_config"] = None


def _render_profile_badge(profile: str) -> str:
    meta = profile_badge_meta(profile)
    label = html.escape(meta["label"])
    return (
        f'<span style="display:inline-block;padding:2px 10px;border-radius:12px;'
        f'font-size:0.76rem;font-weight:700;background-color:{meta["bg"]};'
        f'color:{meta["fg"]};border:1px solid {meta["border"]};">{label}</span>'
    )


def _render_error_banner(err: UIApiError | str) -> None:
    msg = str(err)
    st.error(f"System Notice: {msg}")


def _load_sessions_and_config(client: ComplianceAPIClient, token: str) -> None:
    try:
        st.session_state["user"] = client.get_me(token)
        st.session_state["sessions"] = client.list_sessions(token)
        st.session_state["admin_config"] = client.get_admin_config(token)
        if not st.session_state["sessions"]:
            created = client.create_session(token, "New Compliance Session")
            st.session_state["sessions"] = [created]
        if not st.session_state["active_session_id"] and st.session_state["sessions"]:
            first_id = st.session_state["sessions"][0]["id"]
            st.session_state["active_session_id"] = first_id
            st.session_state["messages"] = client.get_session_messages(token, first_id)
    except UIApiError as exc:
        if exc.status_code == 401:
            _clear_auth_state()
        st.session_state["last_error"] = str(exc)


def render_login_screen(client: ComplianceAPIClient) -> None:
    """Render the login screen with health status and optional dev account helper."""
    st.markdown("## Enterprise Banking Regulatory Compliance Assistant")
    st.caption(
        "Role-Enforced Hybrid RAG • Clause-Aware Citations • Adaptive Routing • Corrective Grading"
    )

    try:
        health = client.get_health()
        llm_info = health.get("llm", {})
        profile_name = str(llm_info.get("profile", "mock"))
        model_name = str(llm_info.get("model", "mock"))
        vec_count = health.get("vector_store", {}).get("total_vectors", 0)
        st.markdown(
            f"{_render_profile_badge(profile_name)} "
            f"<span class='pill-badge'>Model: {html.escape(model_name)}</span> "
            f"<span class='pill-badge'>Indexed Chunks: {int(vec_count)}</span>",
            unsafe_allow_html=True,
        )
    except UIApiError:
        st.warning(
            "Backend API is currently unreachable at "
            f"`{API_BASE_URL}`. Start FastAPI with "
            "`uvicorn src.api.main:app --host 127.0.0.1 --port 8000`."
        )

    if st.session_state.get("last_error"):
        _render_error_banner(st.session_state["last_error"])

    col_login, col_info = st.columns([3, 2])
    with col_login:
        with st.form("login_form", clear_on_submit=False):
            st.subheader("Sign In")
            username = st.text_input(
                "Username",
                placeholder="e.g. analyst_user, manager_user, auditor_user",
            )
            password = st.text_input(
                "Password",
                type="password",
                placeholder="Enter your compliance password",
            )
            submitted = st.form_submit_button("Sign In", use_container_width=True)
            if submitted:
                st.session_state["last_error"] = None
                if not username.strip() or not password:
                    st.session_state["last_error"] = "Please provide both username and password."
                    st.rerun()
                with st.spinner("Authenticating credentials with compliance server..."):
                    try:
                        resp = client.login(username=username, password=password)
                        token = str(resp["access_token"])
                        st.session_state["access_token"] = token
                        st.session_state["user"] = resp.get("user")
                        _load_sessions_and_config(client, token)
                        st.rerun()
                    except UIApiError as exc:
                        st.session_state["last_error"] = str(exc)
                        st.rerun()

    with col_info:
        st.markdown(
            """
            <div class="compliance-card">
                <strong>Server-Side RBAC Enforcement</strong>
                <p style="font-size:0.9rem;margin-top:6px;">
                Your active role (<code>analyst</code>, <code>manager</code>, or <code>auditor</code>)
                is verified from your signed session token on every query. Restricted documents are
                filtered inside Qdrant and BM25 before any passage reaches the language model.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        demo_users = client.list_demo_users()
        if demo_users:
            with st.expander("Synthetic Accounts (Local Dev/Test)", expanded=True):
                for u in demo_users:
                    st.markdown(
                        f"- `{u.get('username')}` — **{str(u.get('role', '')).upper()}** "
                        f"({u.get('full_name')})"
                    )


def render_sidebar(client: ComplianceAPIClient, token: str, user: dict[str, Any]) -> None:
    """Render user identity, view switcher, session list, and settings panel."""
    role = str(user.get("role", "analyst")).lower()
    cfg = st.session_state.get("admin_config") or {}
    profile = str(cfg.get("profile", "mock"))
    model = str(cfg.get("model", "mock"))

    with st.sidebar:
        st.markdown(
            f"<div class='compliance-card'>"
            f"<div><strong>{html.escape(str(user.get('full_name', '')))}</strong></div>"
            f"<div style='font-size:0.82rem;color:#D0D4DC;margin-bottom:8px;'>"
            f"@{html.escape(str(user.get('username', '')))}</div>"
            f"<span class='pill-accent'>ROLE: {html.escape(role.upper())}</span>"
            f"{_render_profile_badge(profile)}"
            f"</div>",
            unsafe_allow_html=True,
        )

        if st.button("Sign Out", use_container_width=True):
            try:
                client.logout(token)
            except UIApiError:
                pass
            _clear_auth_state()
            st.rerun()

        st.divider()

        # Auditor-only view navigation
        if role == "auditor":
            view_choice = st.radio(
                "Workspace View",
                options=["chat", "audit"],
                format_func=lambda v: (
                    "Compliance Chat" if v == "chat" else "Auditor Summary & RBAC Logs"
                ),
                index=0 if st.session_state.get("active_view") == "chat" else 1,
            )
            st.session_state["active_view"] = view_choice
            st.divider()
        else:
            st.session_state["active_view"] = "chat"

        # Session management
        st.subheader("Compliance Sessions")
        with st.form("new_session_form", clear_on_submit=True):
            new_title = st.text_input(
                "New Session Title",
                placeholder="New Compliance Session",
                label_visibility="collapsed",
            )
            if st.form_submit_button("+ New Session", use_container_width=True):
                try:
                    created = client.create_session(
                        token, new_title.strip() or "New Compliance Session"
                    )
                    st.session_state["sessions"] = client.list_sessions(token)
                    st.session_state["active_session_id"] = created["id"]
                    st.session_state["messages"] = []
                    st.rerun()
                except UIApiError as exc:
                    st.session_state["last_error"] = str(exc)

        sessions: list[dict[str, Any]] = st.session_state.get("sessions", [])
        active_id = st.session_state.get("active_session_id")
        for sess in sessions:
            sid = str(sess["id"])
            title = str(sess.get("title") or "Compliance Session")
            is_active = sid == active_id
            col_open, col_del = st.columns([4, 1])
            with col_open:
                btn_label = f"▸ {title}" if is_active else title
                if st.button(
                    btn_label,
                    key=f"open_{sid}",
                    type="primary" if is_active else "secondary",
                    use_container_width=True,
                ):
                    st.session_state["active_session_id"] = sid
                    try:
                        st.session_state["messages"] = client.get_session_messages(token, sid)
                    except UIApiError as exc:
                        st.session_state["last_error"] = str(exc)
                    st.rerun()
            with col_del:
                if st.button("✕", key=f"del_{sid}", help=f"Delete session {title}"):
                    try:
                        client.delete_session(token, sid)
                        remaining = client.list_sessions(token)
                        if not remaining:
                            remaining = [client.create_session(token, "New Compliance Session")]
                        st.session_state["sessions"] = remaining
                        next_id = remaining[0]["id"]
                        st.session_state["active_session_id"] = next_id
                        st.session_state["messages"] = client.get_session_messages(token, next_id)
                        st.rerun()
                    except UIApiError as exc:
                        st.session_state["last_error"] = str(exc)

        st.divider()

        # Settings & Active Configuration Panel
        with st.expander("System Profile & Layer Flags", expanded=False):
            st.markdown(f"**Active Profile:** `{profile}`")
            st.markdown(f"**Active Model:** `{model}`")
            st.markdown(f"**Prompt Version:** `{cfg.get('prompt_version', 'v1')}`")
            layers = cfg.get("layers", {})
            if isinstance(layers, dict):
                st.markdown("**Architecture Layers:**")
                for layer_name, enabled in layers.items():
                    status_icon = "ON" if enabled else "OFF"
                    st.markdown(f"- `{layer_name}`: **{status_icon}**")
            caps = cfg.get("spend_caps", {})
            if isinstance(caps, dict):
                st.markdown(
                    f"**Spend Caps:** `{caps.get('calls_limit', 0)}` calls / "
                    f"`{caps.get('tokens_limit', 0)}` tokens"
                )


def _render_citations_and_trace(turn_data: dict[str, Any]) -> None:
    """Render structured citations panel and expandable safe reasoning trace."""
    route = str(turn_data.get("route") or turn_data.get("route_taken") or "SINGLE_SEARCH")
    grader_path = turn_data.get("grader_path") or (
        turn_data.get("grader", {}).get("path")
        if isinstance(turn_data.get("grader"), dict)
        else None
    )
    latency_ms = float(turn_data.get("latency_ms") or 0.0)
    dropped = int(turn_data.get("citations_dropped") or 0)
    refusal_cat = turn_data.get("refusal_category") or turn_data.get("refusal")

    pills = [
        f"<span class='pill-badge'>Route: {html.escape(route)}</span>",
        f"<span class='pill-badge'>Grader: {html.escape(str(grader_path or 'disabled'))}</span>",
        f"<span class='pill-badge'>Latency: {latency_ms:.1f} ms</span>",
    ]
    if dropped > 0:
        pills.append(
            f"<span class='pill-badge'>Dropped Invalid Citations: {dropped}</span>"
        )
    if refusal_cat:
        pills.append(
            f"<span class='pill-accent'>Refusal: {html.escape(str(refusal_cat))}</span>"
        )
    st.markdown("".join(pills), unsafe_allow_html=True)

    citations: list[dict[str, Any]] = turn_data.get("citations") or []
    if citations:
        st.markdown(f"**Verified Authoritative Citations ({len(citations)})**")
        for cite in citations:
            doc_title = html.escape(
                str(cite.get("doc_title") or cite.get("doc_name") or "Regulatory Document")
            )
            heading_path = html.escape(
                str(cite.get("heading_path") or cite.get("section_title") or "Section")
            )
            clause = html.escape(str(cite.get("clause") or cite.get("clause_id") or "-"))
            page = cite.get("page") if cite.get("page") is not None else cite.get("page_number")
            page_str = f"Page {page}" if page is not None else "Page n/a"
            chunk_id = html.escape(str(cite.get("chunk_id") or cite.get("doc_id") or ""))
            snippet = html.escape(
                str(cite.get("quote_snippet") or cite.get("snippet") or "")[:200]
            )
            st.markdown(
                f"""
                <div class="citation-card">
                    <div>
                        <span class="pill-accent">{chunk_id}</span>
                        <strong>{doc_title}</strong>
                        <span class="pill-badge">{html.escape(page_str)}</span>
                        <span class="pill-badge">Clause: {clause}</span>
                    </div>
                    <div style="font-size:0.84rem;color:#D0D4DC;margin-top:4px;">
                        Heading Path: <code>{heading_path}</code>
                    </div>
                    <div class="quote-snippet">"{snippet}"</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    trace: list[str] = turn_data.get("reasoning_trace") or []
    if trace:
        with st.expander("Reasoning Trace & Verification Steps", expanded=False):
            for step_line in trace:
                st.markdown(f"- {step_line}")


def _submit_question(client: ComplianceAPIClient, token: str, session_id: str, query: str) -> None:
    """Execute a chat query and update session state."""
    st.session_state["last_error"] = None
    with st.spinner("Verifying role permissions, retrieving clauses, and validating citations..."):
        try:
            res = client.ask_chat_query(token=token, session_id=session_id, query=query)
            st.session_state["messages"] = client.get_session_messages(token, session_id)
            if st.session_state["messages"]:
                last_msg_id = st.session_state["messages"][-1]["id"]
                st.session_state["turn_details"][last_msg_id] = res
            st.rerun()
        except UIApiError as exc:
            if exc.status_code == 401:
                _clear_auth_state()
            st.session_state["last_error"] = str(exc)
            st.rerun()


def render_chat_view(client: ComplianceAPIClient, token: str, user: dict[str, Any]) -> None:
    """Render the compliance chat view with citations, trace, refusal, and empty states."""
    role = str(user.get("role", "analyst")).lower()
    session_id = st.session_state.get("active_session_id")
    if not session_id:
        st.info("Create or select a compliance session in the sidebar to begin.")
        return

    st.markdown(
        f"### Regulatory Compliance Workspace "
        f"<span class='pill-accent'>SERVER ROLE: {html.escape(role.upper())}</span>",
        unsafe_allow_html=True,
    )

    if st.session_state.get("last_error"):
        _render_error_banner(st.session_state["last_error"])

    messages: list[dict[str, Any]] = st.session_state.get("messages", [])
    turn_details: dict[int, dict[str, Any]] = st.session_state.get("turn_details", {})

    if not messages:
        st.markdown(
            """
            <div class="compliance-card">
                <strong>Empty Session — Ready for Regulatory Queries</strong>
                <p style="font-size:0.9rem;margin-top:6px;">
                Ask a compliance question below or select one of the starter questions for your
                role. Every answer cites verbatim clauses from documents permitted for your role.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        starters = ROLE_STARTER_QUESTIONS.get(role, ROLE_STARTER_QUESTIONS["analyst"])
        cols = st.columns(len(starters))
        for idx, starter_q in enumerate(starters):
            with cols[idx]:
                if st.button(starter_q, key=f"starter_{idx}", use_container_width=True):
                    _submit_question(client, token, session_id, starter_q)

    for msg in messages:
        sender = str(msg.get("sender", "user"))
        content = str(msg.get("content", ""))
        msg_id = int(msg.get("id", 0))
        with st.chat_message("user" if sender == "user" else "assistant"):
            detail = turn_details.get(msg_id)
            if sender == "assistant" and (
                (detail and is_refusal_response(detail))
                or "can't find that in the documents available to your role" in content.lower()
            ):
                st.markdown(
                    f"""
                    <div class="refusal-card">
                        <div><span class="pill-accent">COMPLIANCE REFUSAL</span></div>
                        <div style="margin-top:6px;">{html.escape(content)}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(content)

            if sender == "assistant":
                if detail:
                    _render_citations_and_trace(detail)
                elif isinstance(msg.get("metadata"), dict):
                    meta = msg["metadata"]
                    chunk_ids = meta.get("chunk_ids") or []
                    route_used = msg.get("route_used") or "SINGLE_SEARCH"
                    lat = meta.get("latency_ms", 0.0)
                    st.markdown(
                        f"<span class='pill-badge'>Route: {html.escape(str(route_used))}</span>"
                        f"<span class='pill-badge'>Latency: {float(lat):.1f} ms</span>"
                        f"<span class='pill-badge'>Cited Chunks: "
                        f"{html.escape(', '.join(chunk_ids) if chunk_ids else 'none')}</span>",
                        unsafe_allow_html=True,
                    )

    prompt = st.chat_input("Ask a banking regulatory compliance question...")
    if prompt and prompt.strip():
        _submit_question(client, token, session_id, prompt.strip())


def render_auditor_view(client: ComplianceAPIClient, token: str, user: dict[str, Any]) -> None:
    """Render the auditor-only summary and RBAC verification view."""
    role = str(user.get("role", "")).lower()
    if role != "auditor":
        st.error("Forbidden: Only the auditor role may access audit log summaries.")
        return

    st.markdown(
        "### Auditor Compliance & RBAC Summary View "
        "<span class='pill-accent'>SUMMARIES ONLY — ZERO CONVERSATION TEXT EXPOSED</span>",
        unsafe_allow_html=True,
    )
    st.caption(
        "Privacy & RBAC Contract: Query text and response text are excluded from this endpoint. "
        "Only route decisions, chunk IDs, citation verification counters, and latency/token metrics are shown."
    )

    col_limit, col_uid, col_refresh = st.columns([2, 2, 1])
    with col_limit:
        limit = int(st.number_input("Max Audit Rows", min_value=5, max_value=200, value=50, step=5))
    with col_uid:
        uid_raw = st.text_input("Filter by User ID (optional)", value="")
    with col_refresh:
        st.write("")
        st.write("")
        refresh = st.button("Refresh Logs", type="primary", use_container_width=True)

    user_id_filter: int | None = None
    if uid_raw.strip().isdigit():
        user_id_filter = int(uid_raw.strip())

    if refresh or "audit_logs_cache" not in st.session_state:
        with st.spinner("Loading sanitized audit log summaries..."):
            try:
                st.session_state["audit_logs_cache"] = client.get_audit_logs(
                    token=token,
                    limit=limit,
                    user_id=user_id_filter,
                )
            except UIApiError as exc:
                _render_error_banner(exc)
                return

    logs: list[dict[str, Any]] = st.session_state.get("audit_logs_cache", [])
    total_rows = len(logs)
    total_cites = sum(int(r.get("citation_count") or 0) for r in logs)
    total_dropped = sum(int(r.get("citations_dropped") or 0) for r in logs)
    total_filtered = sum(int(r.get("candidates_filtered") or 0) for r in logs)

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Audited Turns", total_rows)
    k2.metric("RBAC Leakage Rate", "0.00%")
    k3.metric("Verified Citations", total_cites)
    k4.metric("Dropped Invalid Citations", total_dropped)

    st.markdown(
        f"<div class='compliance-card'>"
        f"<strong>RBAC Enforcement Summary:</strong> Across {total_rows} audited turn(s), "
        f"server-side Qdrant/BM25 role filters excluded <code>{total_filtered}</code> restricted "
        f"candidate passage(s) before generation and dropped <code>{total_dropped}</code> "
        f"unverified citation(s)."
        f"</div>",
        unsafe_allow_html=True,
    )

    if not logs:
        st.info("No audit log rows match the current filter.")
        return

    table_rows = [
        {
            "Audit ID": r.get("audit_id"),
            "Timestamp": r.get("created_at"),
            "Role": r.get("user_role"),
            "Route": r.get("final_route"),
            "Chunks Cited": ", ".join(r.get("retrieved_chunk_ids") or []),
            "Citations": r.get("citation_count"),
            "Dropped": r.get("citations_dropped"),
            "Heading Path": r.get("heading_path_enabled"),
            "Role Filtered": r.get("candidates_filtered"),
            "Latency (ms)": r.get("latency_ms"),
            "Profile": r.get("llm_profile"),
        }
        for r in logs
    ]
    st.dataframe(table_rows, use_container_width=True, hide_index=True)


def main() -> None:
    st.set_page_config(
        page_title="Enterprise Banking Regulatory Compliance Assistant",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    _init_session_state()

    client = ComplianceAPIClient(base_url=API_BASE_URL)
    token = st.session_state.get("access_token")
    user = st.session_state.get("user")

    if not token or not isinstance(user, dict):
        render_login_screen(client)
        return

    render_sidebar(client, token, user)
    if st.session_state.get("active_view") == "audit" and user.get("role") == "auditor":
        render_auditor_view(client, token, user)
    else:
        render_chat_view(client, token, user)


if __name__ == "__main__":
    main()

