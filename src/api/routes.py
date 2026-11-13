"""Phase 3 API routes: auth, sessions, RBAC-scoped chat and audit.

Every protected route derives the user and role from the signed bearer token.
Client-supplied role or user identifiers are ignored by construction.
"""

import inspect
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status

from src.api.deps import (
    ApiError,
    CurrentUser,
    enforce_query_rate_limit,
    enforce_upload_rate_limit,
    get_current_user,
    require_role,
)
from src.api.schemas import (
    AdminConfigResponse,
    AdminMetricsResponse,
    AuditLogEntry,
    AuditMetrics,
    ChatQueryRequest,
    ChatQueryResponse,
    Citation,
    DocumentListItem,
    DocumentListResponse,
    DocumentUploadResponse,
    GraderStats,
    IndexMetrics,
    LatencyMetrics,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    LLMStats,
    MessageSummary,
    RetrievalStats,
    RouterStats,
    SessionCreateRequest,
    SessionListResponse,
    SessionMessagesResponse,
    SessionRenameRequest,
    SessionSummary,
    SpendStats,
    UserProfile,
)
from src.config import ResolvedLLM, settings
from src.core.auth import (
    AccountLockedError,
    LoginRateLimitedError,
    TokenClaims,
    create_access_token,
    dummy_verify,
    login_throttle,
    revoke_token,
    verify_password,
)
from src.core.llm_client import active_resolved_llm, llm_profile_scope
from src.core.memory import (
    MemoryContext,
    format_history,
    load_recent_turns,
    memory_metadata,
    rewrite_follow_up,
)
from src.core.prompts import load_prompt
from src.core.router import (
    DIRECT,
    DIRECT_REPLIES,
    INTENT_GENERAL_CHAT,
    ROUTE_API_NAMES,
    SPLIT,
    RouteDecision,
    classify_question,
    router_metadata,
    rule_precheck,
)
from src.core.spend_guard import spend_guard
from src.core.telemetry import bind_audit_id
from src.core.xai import build_safe_reasoning_trace
from src.db.connection import get_db_connection
from src.db.repository import Repository
from src.rag.baseline import (
    BaselineRAGResponse,
    baseline_pipeline,
    build_verification_metadata,
)

logger = logging.getLogger(__name__)
router = APIRouter()
PUBLIC_USER_LIST_ENVS = {"development", "test"}
SINGLE_SEARCH_API = ROUTE_API_NAMES["single_search"]


def _user_profile(row: Any) -> UserProfile:
    return UserProfile(
        id=int(row["id"]),
        username=str(row["username"]),
        full_name=str(row["full_name"]),
        role=str(row["role_name"]),
    )


def _json_list(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


# ==============================================================================
# Authentication
# ==============================================================================
@router.post("/api/v1/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request) -> LoginResponse:
    """Authenticate a synthetic user and return a short-lived signed token."""
    username = payload.username.strip().lower()
    client_key = request.client.host if request.client else "unknown"

    try:
        login_throttle.check_allowed(username, client_key)
    except AccountLockedError as exc:
        raise ApiError(429, "ACCOUNT_LOCKED", str(exc)) from exc
    except LoginRateLimitedError as exc:
        raise ApiError(429, "LOGIN_RATE_LIMITED", str(exc)) from exc

    login_throttle.record_attempt(username, client_key)

    with get_db_connection() as conn:
        row = Repository(conn).get_user_by_username(username)

    if row is None or not int(row["is_active"] or 0):
        # Equalise timing so unknown usernames are not distinguishable.
        dummy_verify(payload.password)
        login_throttle.record_failure(username)
        raise ApiError(401, "INVALID_CREDENTIALS", "Invalid username or password.")

    if not verify_password(str(row["password_hash"]), payload.password):
        login_throttle.record_failure(username)
        raise ApiError(401, "INVALID_CREDENTIALS", "Invalid username or password.")

    login_throttle.record_success(username)
    token = create_access_token(
        user_id=int(row["id"]),
        username=str(row["username"]),
        role=str(row["role_name"]),
    )
    return LoginResponse(access_token=token, user=_user_profile(row))


@router.get("/api/v1/auth/users", response_model=list[UserProfile])
def list_synthetic_users() -> list[UserProfile]:
    """List synthetic users for the local demo switcher (dev environments only)."""
    if settings.APP_ENV not in PUBLIC_USER_LIST_ENVS:
        raise ApiError(403, "FORBIDDEN", "User listing is disabled in this environment.")
    with get_db_connection() as conn:
        rows = Repository(conn).list_users()
    return [
        UserProfile(
            id=int(row["id"]),
            username=str(row["username"]),
            full_name=str(row["full_name"]),
            role=str(row["role_name"]),
        )
        for row in rows
    ]


@router.get("/api/v1/auth/me", response_model=UserProfile)
def me(user: CurrentUser = Depends(get_current_user)) -> UserProfile:
    """Return the authenticated user's profile and server-side role."""
    return UserProfile(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        role=user.role,
    )


@router.post("/api/v1/auth/logout", response_model=LogoutResponse)
def logout(user: CurrentUser = Depends(get_current_user)) -> LogoutResponse:
    """Revoke the presented token until its natural expiry."""
    revoke_token(
        TokenClaims(
            user_id=user.id,
            username=user.username,
            role=user.role,
            jti=user.jti,
            issued_at=0,
            expires_at=user.expires_at,
        )
    )
    return LogoutResponse()


# ==============================================================================
# Sessions
# ==============================================================================
def _session_summary(row: Any) -> SessionSummary:
    return SessionSummary(
        id=str(row["id"]),
        title=str(row["title"]),
        created_at=str(row["created_at"]) if row["created_at"] is not None else None,
        updated_at=str(row["updated_at"]) if row["updated_at"] is not None else None,
    )


def _spend_stats_from_snapshot(snap: Any) -> SpendStats:
    """Convert a SpendGuardStatus snapshot into a sanitized API SpendStats payload."""
    return SpendStats(
        calls_used=snap.calls,
        calls_limit=snap.calls_limit,
        tokens_used=snap.tokens,
        tokens_limit=snap.tokens_limit,
        exhausted=snap.exhausted,
        calls_remaining=snap.calls_remaining,
        tokens_remaining=snap.tokens_remaining,
        scope=snap.scope,
        profile=snap.profile,
        is_paid=snap.is_paid,
        run_id=snap.run_id,
        offline_calls=snap.offline_calls,
        offline_tokens=snap.offline_tokens,
        local_calls=snap.local_calls,
        local_tokens=snap.local_tokens,
        cached_calls=snap.cached_calls,
        saved_tokens=snap.saved_tokens,
    )


@router.post(
    "/api/v1/sessions",
    response_model=SessionSummary,
    status_code=status.HTTP_201_CREATED,
)
def create_session(
    payload: SessionCreateRequest | None = None,
    user: CurrentUser = Depends(get_current_user),
) -> SessionSummary:
    """Create a chat session owned by the authenticated user and initialize a fresh run budget."""
    session_id = str(uuid.uuid4())
    title = (payload.title if payload and payload.title else "").strip() or "New Compliance Session"
    with get_db_connection() as conn:
        Repository(conn).create_session(session_id, user.id, title)
        row = Repository(conn).get_session_for_user(session_id, user.id)
    spend_guard.reset(run_id=f"session:{session_id}")
    return _session_summary(row)


@router.get("/api/v1/sessions", response_model=SessionListResponse)
def list_sessions(user: CurrentUser = Depends(get_current_user)) -> SessionListResponse:
    """List only the authenticated user's sessions."""
    with get_db_connection() as conn:
        rows = Repository(conn).list_sessions_by_user(user.id)
    return SessionListResponse(sessions=[_session_summary(row) for row in rows])


@router.get(
    "/api/v1/sessions/{session_id}/messages",
    response_model=SessionMessagesResponse,
)
def session_messages(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> SessionMessagesResponse:
    """Return history for one session owned by the caller.

    A session owned by someone else is reported as 404 to avoid confirming that
    it exists (IDOR guard).
    """
    with get_db_connection() as conn:
        repo = Repository(conn)
        if repo.get_session_for_user(session_id, user.id) is None:
            raise ApiError(404, "SESSION_NOT_FOUND", "Session not found.")
        rows = repo.get_session_messages(session_id, limit=200)

    messages: list[MessageSummary] = []
    for row in rows:
        metadata = None
        if row["metadata_json"]:
            try:
                parsed = json.loads(row["metadata_json"])
                metadata = parsed if isinstance(parsed, dict) else None
            except (TypeError, ValueError):
                metadata = None
        messages.append(
            MessageSummary(
                id=int(row["id"]),
                sender=str(row["sender"]),
                content=str(row["content"]),
                route_used=row["route_used"],
                user_role=row["user_role"],
                metadata=metadata,
                created_at=str(row["created_at"]) if row["created_at"] is not None else None,
            )
        )
    return SessionMessagesResponse(session_id=session_id, messages=messages)


@router.delete("/api/v1/sessions/{session_id}")
def delete_session(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Delete one session and its messages when owned by the caller."""
    with get_db_connection() as conn:
        deleted = Repository(conn).delete_session_for_user(session_id, user.id)
    if not deleted:
        raise ApiError(404, "SESSION_NOT_FOUND", "Session not found.")
    spend_guard.reset(run_id=f"session:{session_id}")
    return {"status": "deleted", "session_id": session_id}


@router.post("/api/v1/sessions/{session_id}/new-run", response_model=SpendStats)
def reset_session_run(
    session_id: str,
    user: CurrentUser = Depends(get_current_user),
) -> SpendStats:
    """Reset the run-scoped LLM budget counters for an owned session."""
    with get_db_connection() as conn:
        if Repository(conn).get_session_for_user(session_id, user.id) is None:
            raise ApiError(404, "SESSION_NOT_FOUND", "Session not found.")
    resolved = settings.llm
    run_id = f"session:{session_id}"
    spend_guard.reset(run_id=run_id)
    snap = spend_guard.status(
        profile=resolved.profile,
        has_paid_quota=resolved.has_paid_quota,
        is_local=resolved.is_local,
        run_id=run_id,
    )
    return _spend_stats_from_snapshot(snap)


@router.patch(
    "/api/v1/sessions/{session_id}",
    response_model=SessionSummary,
)
def rename_session(
    session_id: str,
    payload: SessionRenameRequest,
    user: CurrentUser = Depends(get_current_user),
) -> SessionSummary:
    """Rename a session owned by the caller (IDOR-safe)."""
    title = payload.title.strip()
    if not title:
        raise ApiError(400, "EMPTY_TITLE", "Session title cannot be empty.")
    with get_db_connection() as conn:
        row = Repository(conn).rename_session_for_user(session_id, user.id, title)
    if row is None:
        raise ApiError(404, "SESSION_NOT_FOUND", "Session not found.")
    return _session_summary(row)


# ==============================================================================
# Chat (RBAC-scoped RAG)
# ==============================================================================
@router.post(
    "/api/v1/chat/query",
    response_model=ChatQueryResponse,
    dependencies=[Depends(enforce_query_rate_limit)],
)
def chat_query(
    payload: ChatQueryRequest,
    user: CurrentUser = Depends(get_current_user),
) -> ChatQueryResponse:
    """Execute the RAG pipeline inside an isolated per-session run boundary.

    The role always comes from the authenticated session. ``config_overrides``
    is accepted for API compatibility but never disables RBAC or memory.
    """
    if payload.fallback_offline:
        resolved = ResolvedLLM(
            profile="mock",
            model="mock-offline-fallback",
            temperature=settings.LLM_TEMPERATURE,
            timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
            max_retries=0,
            max_rpm=0,
            is_mock=True,
            is_local=True,
            has_paid_quota=False,
        )
    else:
        resolved = settings.llm

    with (
        llm_profile_scope(resolved),
        spend_guard.run_scope(
            f"session:{payload.session_id}",
            profile=resolved.profile,
            has_paid_quota=resolved.has_paid_quota,
            is_local=resolved.is_local,
        ),
    ):
        return _execute_chat_turn(payload=payload, user=user)


def _execute_chat_turn(
    payload: ChatQueryRequest,
    user: CurrentUser,
) -> ChatQueryResponse:
    started = time.perf_counter()
    session_id = str(payload.session_id)
    query = payload.query.strip()
    response_mode = getattr(payload, "response_mode", "compliance")
    if len(query) < 2:
        raise ApiError(400, "EMPTY_QUERY", "Query string cannot be empty.")

    with get_db_connection() as conn:
        repo = Repository(conn)
        if repo.get_session_for_user(session_id, user.id) is None:
            raise ApiError(404, "SESSION_NOT_FOUND", "Session not found.")
        usage_floor = repo.get_max_llm_call_id()
        turns = (
            load_recent_turns(repo, session_id, user.id, settings.MEMORY_MAX_TURNS)
            if settings.ENABLE_MEMORY
            else []
        )

    step_timings: list[dict[str, Any]] = []
    rewrite_started = time.perf_counter()
    rewrite_tokens_before = spend_guard.tokens_count
    if settings.ENABLE_MEMORY:
        memory = rewrite_follow_up(
            baseline_pipeline.llm,
            query,
            turns,
            session_id=session_id,
        )
        step_timings.append(
            {
                "step": "memory_rewrite",
                "latency_ms": round((time.perf_counter() - rewrite_started) * 1000.0, 2),
                "tokens": spend_guard.tokens_count - rewrite_tokens_before,
            }
        )
    else:
        memory = MemoryContext(standalone_question=query, rewritten=False, turns_used=0)

    # Routing happens after the memory rewrite and the server-derived role, and
    # before any retrieval. Every fallback inside the router is SINGLE_SEARCH.
    intent_mode = getattr(payload, "intent_mode", "auto")
    router_enabled = settings.ENABLE_ADAPTIVE_ROUTER
    decision: RouteDecision | None = None
    route = SINGLE_SEARCH_API
    if router_enabled:
        router_kwargs: dict[str, Any] = {
            "session_id": session_id,
            "intent_mode": intent_mode,
            "user_role": user.role,
        }
        try:
            sig = inspect.signature(classify_question)
            if not any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
            ):
                router_kwargs = {k: v for k, v in router_kwargs.items() if k in sig.parameters}
        except (TypeError, ValueError):
            pass
        decision = classify_question(
            baseline_pipeline.llm,
            memory.standalone_question,
            **router_kwargs,
        )
        route = decision.api_route
    else:
        # Check rule pre-check for safety invariants even if adaptive LLM router is off
        prechecked = rule_precheck(memory.standalone_question, role=user.role)
        if prechecked is not None and prechecked.direct_category in ("injection", "unsafe", "system_info"):
            decision = prechecked
            route = decision.api_route
        elif intent_mode == "general":
            decision = RouteDecision(
                route=INTENT_GENERAL_CHAT,
                confidence=1.0,
                source="intent_mode",
                intent="general_chat",
                response_type="general_chat",
                grounded=False,
            )
            route = decision.api_route

    result: BaselineRAGResponse | None = None
    direct_category: str | None = None
    if decision is not None and decision.route == DIRECT:
        # Fixed template only: never model-written factual content.
        answer = decision.direct_reply or DIRECT_REPLIES["out_of_scope"]
        direct_category = decision.direct_category
        sources = []
        cached = False
        rewritten_query: str | None = None
        retrieval_total = 0
        top_rerank_score = 0.0
        candidates_retrieved = 0
        candidates_filtered = 0
        resolved_llm = active_resolved_llm()
        step_timings.append(
            {
                "step": "direct_reply",
                "latency_ms": round(decision.latency_ms, 2),
                "tokens": decision.tokens_used,
            }
        )
    elif decision is not None and decision.route == INTENT_GENERAL_CHAT:
        prompt_tmpl = load_prompt("general")
        history_str = format_history(turns) if turns else "(no previous turns)"
        history_section = (
            f"<conversation_history>\n{history_str}\n</conversation_history>" if turns else ""
        )
        general_prompt = prompt_tmpl.format(
            question=query,
            history_section=history_section,
        )
        gen_start = time.perf_counter()
        llm_response = baseline_pipeline.llm.complete(
            prompt=general_prompt,
            step="general_chat",
            session_id=session_id,
        )
        gen_latency = (time.perf_counter() - gen_start) * 1000.0
        step_timings.append(
            {
                "step": "general_generation",
                "latency_ms": round(gen_latency, 2),
                "tokens": llm_response.prompt_tokens + llm_response.completion_tokens,
            }
        )
        answer = f"*(Note: Answered from general AI knowledge, not grounded in company documents.)*\n\n{llm_response.content.strip()}"
        sources = []
        cached = llm_response.cached
        rewritten_query = None
        retrieval_total = 0
        top_rerank_score = 0.0
        candidates_retrieved = 0
        candidates_filtered = 0
        resolved_llm = active_resolved_llm()
    else:
        if decision is not None and decision.route == SPLIT:
            result = baseline_pipeline.ask_split(
                memory.standalone_question,
                list(decision.sub_questions),
                role=user.role,
                session_id=session_id,
                response_mode=response_mode,
                history=turns,
            )
            step_timings.extend(result.step_timings)
        else:
            result = baseline_pipeline.ask(
                query,
                role=user.role,
                rewritten_query=memory.standalone_question if memory.rewritten else None,
                session_id=session_id,
                response_mode=response_mode,
                history=turns,
            )
            step_timings.extend(
                [
                    {
                        "step": "retrieval",
                        "latency_ms": result.timings.retrieval_ms,
                        "tokens": 0,
                    },
                    {
                        "step": "rerank",
                        "latency_ms": result.timings.rerank_ms,
                        "tokens": 0,
                    },
                    {
                        "step": "generation",
                        "latency_ms": result.timings.generation_ms,
                        "tokens": (
                            result.llm_stats.prompt_tokens + result.llm_stats.completion_tokens
                        ),
                    },
                ]
            )
        answer = result.answer
        sources = result.sources
        cached = result.cached
        rewritten_query = result.retrieval_stats.rewritten_query
        retrieval_total = result.retrieval_stats.total_chunks_retrieved
        top_rerank_score = result.retrieval_stats.top_rerank_score
        candidates_retrieved = result.retrieval_stats.candidates_retrieved
        candidates_filtered = result.retrieval_stats.candidates_filtered_by_role
        resolved_llm = active_resolved_llm()

    latency_ms = (time.perf_counter() - started) * 1000.0
    spend_guard.record_latency(latency_ms, run_id=f"session:{session_id}")
    spend_snap = spend_guard.status(
        profile=resolved_llm.profile,
        has_paid_quota=resolved_llm.has_paid_quota,
        is_local=resolved_llm.is_local,
        run_id=f"session:{session_id}",
    )
    citations_dropped = result.citations_dropped if result is not None else 0

    citations = [
        Citation(
            doc_id=source.doc_id,
            doc_name=source.doc_title,
            section_title=source.section,
            clause_id=source.clause or "",
            page_number=source.page,
            snippet=source.snippet,
            chunk_id=source.chunk_id,
            doc_title=source.doc_title,
            heading_path=source.heading_path or source.section,
            clause=source.clause or "",
            page=source.page,
            quote_snippet=source.quote_snippet or source.snippet,
            source_url=getattr(source, "source_url", None),
            verification_url=getattr(source, "verification_url", None),
            source_name=getattr(source, "source_name", None),
            content_origin=getattr(source, "content_origin", None),
            is_internal=getattr(source, "is_internal", False),
            allowed_roles=list(getattr(source, "allowed_roles", []) or []),
        )
        for source in sources
    ]

    refusal_category: str | None = None
    if decision is not None and decision.route == DIRECT:
        refusal_category = decision.direct_category
    elif result is not None and result.grader_refused:
        refusal_category = result.grader_refusal_reason or "insufficient_evidence"
    elif result is not None and retrieval_total == 0:
        refusal_category = "no_permitted_passages"

    timings_dict: dict[str, float] = {
        "retrieval_ms": round(result.timings.retrieval_ms, 2) if result is not None else 0.0,
        "rerank_ms": round(result.timings.rerank_ms, 2) if result is not None else 0.0,
        "generation_ms": round(result.timings.generation_ms, 2) if result is not None else 0.0,
        "total_ms": round(latency_ms, 2),
    }

    if settings.ENABLE_XAI_OUTPUT:
        passages_retrieved_count = (
            result.initial_passages_retrieved
            if (result is not None and result.initial_passages_retrieved > 0)
            else retrieval_total
        )
        reasoning_trace = build_safe_reasoning_trace(
            question_rewritten=bool(
                memory.rewritten or (result is not None and result.grader_rewrite_used)
            ),
            route=route,
            passages_retrieved=passages_retrieved_count,
            passages_kept=retrieval_total,
            grader_path=(
                result.grader_path
                if (result is not None and settings.ENABLE_CORRECTIVE_GRADER)
                else None
            ),
            retry_used=bool(result is not None and result.grader_rewrite_used),
            limits_hit=bool(
                spend_guard.exhausted or (decision is not None and decision.fallback_used)
            ),
        )
    elif not router_enabled:
        # Router-off path: identical trace to the Phase 3 baseline.
        reasoning_trace = [
            f"Step 1: Authenticated as role '{user.role}'.",
            "Step 2: Server-side RBAC filter applied to BM25 candidates and Qdrant payloads.",
            (
                f"Step 3: Hybrid retrieval returned {candidates_retrieved} "
                f"candidates; {candidates_filtered} excluded by role."
            ),
            (
                f"Step 4: Cross-encoder re-ranked to "
                f"{retrieval_total} permitted passage(s)."
            ),
            "Step 5: Grounded answer generated from permitted passages only.",
        ]
        if memory.rewritten:
            reasoning_trace.insert(
                2,
                f"Step 2b: Follow-up rewritten using {memory.turns_used} prior turn(s).",
            )
    else:
        assert decision is not None
        confidence_label = (
            f"{decision.confidence:.2f}" if decision.confidence is not None else "n/a"
        )
        reasoning_trace = [
            f"Step 1: Authenticated as role '{user.role}'.",
            (
                f"Step 2: Adaptive router selected {route} "
                f"(confidence {confidence_label}, source {decision.source})."
            ),
        ]
        if memory.rewritten:
            reasoning_trace.append(
                f"Step 2b: Follow-up rewritten using {memory.turns_used} prior turn(s)."
            )
        if decision.fallback_used:
            reasoning_trace.append(
                f"Step 2c: Router degraded to SINGLE_SEARCH ({decision.fallback_reason})."
            )
        if decision.route == SPLIT:
            reasoning_trace.append(
                "Step 2d: Sub-questions: "
                + "; ".join(f'"{question}"' for question in decision.sub_questions)
            )
        if decision.route == DIRECT:
            reasoning_trace.append(
                "Step 3: Direct reply template returned; no retrieval was performed."
            )
        else:
            reasoning_trace.append(
                "Step 3: Server-side RBAC filter applied to every BM25 candidate and "
                "Qdrant payload for this route."
            )
            retrieval_calls = (
                len(decision.sub_questions) if decision.route == SPLIT else 1
            )
            reasoning_trace.append(
                f"Step 4: Hybrid retrieval ran {retrieval_calls} time(s) and returned "
                f"{candidates_retrieved} candidates; {candidates_filtered} excluded by role."
            )
            reasoning_trace.append(
                f"Step 5: Cross-encoder re-ranked to {retrieval_total} permitted passage(s)."
            )
            reasoning_trace.append(
                "Step 6: One grounded answer generated from the permitted passages only."
            )

    suggested_follow_ups: list[str] = []
    if decision is not None and decision.route == INTENT_GENERAL_CHAT:
        suggested_follow_ups = [
            "How does this apply to banking compliance?",
            "Search company policy documents",
            "Explain in more technical detail",
        ]
    elif decision is not None and decision.direct_category == "system_info":
        suggested_follow_ups = [
            "What documents are in my role's corpus?",
            "What are the Basel III capital ratios?",
            "What are the KYC/CDD obligations?",
        ]
    elif decision is not None and decision.direct_category in ("injection", "unsafe"):
        suggested_follow_ups = [
            "What is Customer Due Diligence (CDD)?",
            "What is the Common Equity Tier 1 (CET1) requirement?",
        ]
    else:
        q_lower = query.lower()
        if "capital" in q_lower or "basel" in q_lower or "cet1" in q_lower:
            suggested_follow_ups = [
                "What is the Capital Conservation Buffer requirement?",
                "How are Risk-Weighted Assets (RWA) calculated?",
                "What are the Tier 2 capital eligibility criteria?",
            ]
        elif "cdd" in q_lower or "kyc" in q_lower or "laundering" in q_lower or "aml" in q_lower:
            suggested_follow_ups = [
                "When is Enhanced Due Diligence (EDD) mandatory?",
                "What are the internal escalation procedures for suspicious activity?",
                "How long must KYC verification records be retained?",
            ]
        elif "cass" in q_lower or "client asset" in q_lower:
            suggested_follow_ups = [
                "What are the rules for segregating client money under CASS 7?",
                "What internal reconciliations are required under CASS?",
            ]
        else:
            suggested_follow_ups = [
                "What are the specific clause numbers and citations?",
                "Explain the operational impact in simple terms",
                "What supervisory penalties apply for non-compliance?",
            ]

    response_type = decision.response_type if decision is not None else "rag"
    grounded = decision.grounded if decision is not None else True

    # Persist everything the UI needs to re-render a turn after a reload. This is
    # scoped to the caller's own session and contains no prompt text or secrets.
    with get_db_connection() as conn:
        repo = Repository(conn)
        usage = repo.get_llm_usage_since(usage_floor, session_id)

        repo.add_message(
            session_id=session_id,
            sender="user",
            content=query,
            user_role=user.role,
            metadata_json=json.dumps(memory_metadata(memory)),
        )
        repo.add_message(
            session_id=session_id,
            sender="assistant",
            content=answer,
            route_used=route,
            user_role=user.role,
            metadata_json=json.dumps(
                {
                    "chunk_ids": [source.chunk_id for source in sources],
                    "citations": [citation.model_dump() for citation in citations],
                    "reasoning_trace": reasoning_trace,
                    "latency_ms": round(latency_ms, 2),
                    "cached": cached,
                    "tokens_prompt": usage["prompt_tokens"],
                    "tokens_completion": usage["completion_tokens"],
                    "router": router_metadata(decision) if decision is not None else None,
                    "citations_dropped": citations_dropped,
                    "response_mode": response_mode,
                    "intent_mode": intent_mode,
                    "response_type": response_type,
                    "grounded": grounded,
                    "refusal_category": refusal_category,
                    "suggested_follow_ups": suggested_follow_ups,
                    "grader_path": result.grader_path if result is not None else None,
                    "llm_profile": resolved_llm.profile,
                    "llm_model": resolved_llm.model,
                    "timings": timings_dict,
                }
            ),
        )
        audit_id = repo.create_audit_log(
            session_id=session_id,
            user_id=user.id,
            user_role=user.role,
            query_text=query,
            final_route=route,
            retrieved_chunk_ids=[source.chunk_id for source in sources],
            relevance_scores=[round(source.score, 6) for source in sources],
            response_text=answer,
            latency_ms=round(latency_ms, 2),
            retry_count=1 if (result is not None and result.grader_rewrite_used) else 0,
            rewritten_query=rewritten_query,
            reasoning_trace=reasoning_trace,
            citations_json=[citation.model_dump() for citation in citations],
            tokens_prompt=usage["prompt_tokens"],
            tokens_completion=usage["completion_tokens"],
            llm_profile=resolved_llm.profile,
            llm_calls=usage["calls"],
            cached_calls=usage["cached_calls"],
            spend_guard_hit=spend_snap.exhausted,
            prompt_version=settings.PROMPT_VERSION,
            llm_model=resolved_llm.model,
            candidates_retrieved=candidates_retrieved,
            candidates_filtered=candidates_filtered,
            router_confidence=decision.confidence if decision is not None else None,
            router_fallback_reason=decision.fallback_reason if decision is not None else None,
            sub_questions=list(decision.sub_questions) if decision is not None else [],
            step_timings=step_timings,
            grader_path=result.grader_path if result is not None else None,
            grader_relevant_count=result.grader_relevant_count if result is not None else None,
            grader_ambiguous_count=result.grader_ambiguous_count if result is not None else None,
            grader_irrelevant_count=result.grader_irrelevant_count if result is not None else None,
            grader_rewrite_used=result.grader_rewrite_used if result is not None else None,
            grader_rewritten_query=result.grader_rewritten_query if result is not None else None,
            grader_refused=result.grader_refused if result is not None else None,
            grader_refusal_reason=result.grader_refusal_reason if result is not None else None,
            grader_calls=result.grader_calls if result is not None else None,
            grader_tokens=result.grader_tokens if result is not None else None,
            grader_latency_ms=result.grader_latency_ms if result is not None else None,
            citation_count=len(citations),
            citations_dropped=citations_dropped,
            heading_path_enabled=settings.ENABLE_HEADING_PATH,
        )
        bind_audit_id(audit_id)

    return ChatQueryResponse(
        session_id=session_id,
        answer=answer,
        route_taken=route,
        route=route,
        citations=citations,
        reasoning_trace=reasoning_trace,
        retrieval_stats=RetrievalStats(
            total_chunks_retrieved=retrieval_total,
            top_rerank_score=top_rerank_score,
            retry_count=1 if (result is not None and result.grader_rewrite_used) else 0,
            rewritten_query=rewritten_query,
        ),
        llm_stats=LLMStats(
            profile=resolved_llm.profile,
            model=resolved_llm.model,
            prompt_version=settings.PROMPT_VERSION,
            calls=usage["calls"],
            cached_calls=usage["cached_calls"],
            prompt_tokens=usage["prompt_tokens"],
            completion_tokens=usage["completion_tokens"],
            cached_response=cached,
        ),
        spend=_spend_stats_from_snapshot(spend_snap),
        latency_ms=round(latency_ms, 2),
        audit_id=int(audit_id),
        role=user.role,
        rbac_enabled=settings.rbac_enabled,
        candidates_filtered_by_role=candidates_filtered,
        router=RouterStats(
            enabled=router_enabled,
            route=route,
            confidence=decision.confidence if decision is not None else None,
            sub_questions=list(decision.sub_questions) if decision is not None else [],
            fallback_used=decision.fallback_used if decision is not None else False,
            fallback_reason=decision.fallback_reason if decision is not None else None,
            direct_category=direct_category,
            latency_ms=round(decision.latency_ms, 2) if decision is not None else 0.0,
            tokens_used=decision.tokens_used if decision is not None else 0,
        ),
        grader=GraderStats(
            enabled=settings.ENABLE_CORRECTIVE_GRADER,
            path=result.grader_path if result is not None else None,
            relevant_count=result.grader_relevant_count if result is not None else 0,
            ambiguous_count=result.grader_ambiguous_count if result is not None else 0,
            irrelevant_count=result.grader_irrelevant_count if result is not None else 0,
            rewrite_used=result.grader_rewrite_used if result is not None else False,
            refused=result.grader_refused if result is not None else False,
            refusal_reason=result.grader_refusal_reason if result is not None else "",
            grader_calls=result.grader_calls if result is not None else 0,
            tokens_used=result.grader_tokens if result is not None else 0,
            latency_ms=result.grader_latency_ms if result is not None else 0.0,
        ),
        grader_path=result.grader_path if result is not None else None,
        refusal=refusal_category,
        refusal_category=refusal_category,
        timings=timings_dict,
        citations_dropped=citations_dropped,
        heading_path_enabled=settings.ENABLE_HEADING_PATH,
        response_mode=response_mode,
        intent_mode=intent_mode,
        response_type=response_type,
        grounded=grounded,
        suggested_follow_ups=suggested_follow_ups,
    )


# ==============================================================================
# Audit trail and admin configuration
# ==============================================================================
def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return round(sorted_vals[0], 2)
    rank = (pct / 100.0) * (len(sorted_vals) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_vals) - 1)
    frac = rank - low
    return round(sorted_vals[low] + frac * (sorted_vals[high] - sorted_vals[low]), 2)


@router.get("/api/v1/audit/logs", response_model=list[AuditLogEntry])
def audit_logs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user_id: int | None = Query(default=None),
    start_date: str | None = Query(default=None),
    route: str | None = Query(default=None),
    user_role: str | None = Query(default=None),
    user: CurrentUser = Depends(require_role("auditor")),
) -> list[AuditLogEntry]:
    """Return audit *summaries*. Restricted to the auditor role.

    Stored query and response text is never returned here. A user's own turn
    text is only available to that user through their own session messages
    endpoint, so an auditor cannot read another user's conversation content.
    """
    with get_db_connection() as conn:
        rows = Repository(conn).list_audit_logs(
            limit=limit,
            offset=offset,
            user_id=user_id,
            start_date=start_date,
            route=route,
            user_role=user_role,
        )
    return [
        AuditLogEntry(
            audit_id=int(row["id"]),
            session_id=row["session_id"],
            user_id=int(row["user_id"]),
            user_role=str(row["user_role"]),
            final_route=str(row["final_route"]),
            retrieved_chunk_ids=_json_list(row["retrieved_chunk_ids"]),
            latency_ms=float(row["latency_ms"] or 0.0),
            tokens_prompt=int(row["tokens_prompt"] or 0),
            tokens_completion=int(row["tokens_completion"] or 0),
            llm_profile=str(row["llm_profile"] or "mock"),
            llm_model=row["llm_model"],
            llm_calls=int(row["llm_calls"] or 0),
            cached_calls=int(row["cached_calls"] or 0),
            candidates_retrieved=int(row["candidates_retrieved"] or 0),
            candidates_filtered=int(row["candidates_filtered"] or 0),
            router_confidence=(
                float(row["router_confidence"])
                if row["router_confidence"] is not None
                else None
            ),
            router_fallback_reason=row["router_fallback_reason"],
            citation_count=(
                int(row["citation_count"])
                if "citation_count" in row.keys() and row["citation_count"] is not None
                else None
            ),
            citations_dropped=(
                int(row["citations_dropped"])
                if "citations_dropped" in row.keys() and row["citations_dropped"] is not None
                else None
            ),
            heading_path_enabled=(
                bool(row["heading_path_enabled"])
                if "heading_path_enabled" in row.keys() and row["heading_path_enabled"] is not None
                else None
            ),
            created_at=str(row["created_at"]) if row["created_at"] is not None else None,
        )
        for row in rows
    ]


@router.get("/api/v1/admin/config", response_model=AdminConfigResponse)
def admin_config(
    session_id: str | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
) -> AdminConfigResponse:
    """Expose the active profile, layer flags, and current-run budget telemetry (no secrets)."""
    resolved = settings.llm
    run_id = "__unscoped_idle__"
    if session_id:
        with get_db_connection() as conn:
            if Repository(conn).get_session_for_user(session_id, user.id) is not None:
                run_id = f"session:{session_id}"
    snap = spend_guard.status(
        profile=resolved.profile,
        has_paid_quota=resolved.has_paid_quota,
        is_local=resolved.is_local,
        run_id=run_id,
    )
    spend_caps_payload: dict[str, int] = {
        "calls_used": snap.calls,
        "calls_limit": snap.calls_limit if snap.calls_limit > 0 else settings.LLM_MAX_CALLS_PER_RUN,
        "calls_remaining": snap.calls_remaining,
        "tokens_used": snap.tokens,
        "tokens_limit": snap.tokens_limit if snap.tokens_limit > 0 else settings.LLM_MAX_TOKENS_PER_RUN,
        "tokens_remaining": snap.tokens_remaining,
        "exhausted": int(snap.exhausted),
        "is_paid": int(snap.is_paid),
        "cached_calls": snap.cached_calls,
        "saved_tokens": snap.saved_tokens,
    }
    if snap.last_latency_ms is not None:
        spend_caps_payload["last_latency_ms"] = int(round(snap.last_latency_ms))

    return AdminConfigResponse(
        profile=resolved.profile,
        model=resolved.model,
        prompt_version=settings.PROMPT_VERSION,
        rbac_enabled=settings.rbac_enabled,
        memory_enabled=settings.ENABLE_MEMORY,
        layers={
            "adaptive_router": settings.ENABLE_ADAPTIVE_ROUTER,
            "corrective_grader": settings.ENABLE_CORRECTIVE_GRADER,
            "rbac": settings.rbac_enabled,
            "memory": settings.ENABLE_MEMORY,
            "xai_output": settings.ENABLE_XAI_OUTPUT,
            "heading_path": settings.ENABLE_HEADING_PATH,
        },
        spend_caps=spend_caps_payload,
        token_ttl_minutes=settings.AUTH_TOKEN_TTL_MINUTES,
        run_budget=_spend_stats_from_snapshot(snap),
    )


@router.get("/api/v1/admin/metrics", response_model=AdminMetricsResponse)
def admin_metrics(
    session_id: str | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
) -> AdminMetricsResponse:
    """Expose sanitized operational telemetry, latency percentiles, and guard status."""
    resolved = settings.llm
    run_id = "__unscoped_idle__"
    with get_db_connection() as conn:
        repo = Repository(conn)
        if session_id and repo.get_session_for_user(session_id, user.id) is not None:
            run_id = f"session:{session_id}"
        raw = repo.get_system_metrics()

    snap = spend_guard.status(
        profile=resolved.profile,
        has_paid_quota=resolved.has_paid_quota,
        is_local=resolved.is_local,
        run_id=run_id,
    )

    sorted_lat = sorted(float(v) for v in raw.get("latencies", []))
    total_calls = int(raw.get("total_calls", 0))
    cached_calls = int(raw.get("cached_calls", 0))
    cache_hit_rate = round((cached_calls / total_calls), 4) if total_calls > 0 else 0.0
    avg_ms = round(sum(sorted_lat) / len(sorted_lat), 2) if sorted_lat else 0.0

    try:
        vector_count = int(baseline_pipeline.qdrant.count())
        idx_status = "online"
    except Exception:
        vector_count = 0
        idx_status = "unavailable"
    try:
        bm25_chunks = len(getattr(baseline_pipeline.bm25, "chunks", []) or [])
    except Exception:
        bm25_chunks = 0

    return AdminMetricsResponse(
        profile=resolved.profile,
        model=resolved.model,
        prompt_version=settings.PROMPT_VERSION,
        is_mock=resolved.is_mock,
        is_local=resolved.is_local,
        is_paid=resolved.has_paid_quota,
        total_calls=total_calls,
        cached_calls=cached_calls,
        error_calls=int(raw.get("error_calls", 0)),
        cache_hit_rate=cache_hit_rate,
        total_prompt_tokens=int(raw.get("prompt_tokens", 0)),
        total_completion_tokens=int(raw.get("completion_tokens", 0)),
        total_tokens=int(raw.get("total_tokens", 0)),
        latency=LatencyMetrics(
            p50_ms=_percentile(sorted_lat, 50.0),
            p95_ms=_percentile(sorted_lat, 95.0),
            avg_ms=avg_ms,
            sample_count=len(sorted_lat),
        ),
        index=IndexMetrics(
            vector_count=vector_count,
            bm25_chunks=bm25_chunks,
            status=idx_status,
        ),
        audit=AuditMetrics(
            total_turns=int(raw.get("total_turns", 0)),
            total_role_filtered=int(raw.get("total_role_filtered", 0)),
            total_citations_dropped=int(raw.get("total_citations_dropped", 0)),
        ),
        guard_status=_spend_stats_from_snapshot(snap),
    )


# ==============================================================================
# Document Upload and Catalog
# ==============================================================================
@router.post(
    "/api/v1/documents/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_upload_rate_limit)],
)
def upload_document(
    file: UploadFile = File(...),
    allowed_roles: str = Form(default='["manager", "auditor"]'),
    title: str | None = Form(default=None),
    doc_id: str | None = Form(default=None),
    doc_type: str | None = Form(default=None),
    user: CurrentUser = Depends(get_current_user),
) -> DocumentUploadResponse:
    """Upload and dynamically index a compliance document into Qdrant & BM25.

    Role-gated: only roles in settings.UPLOAD_ALLOWED_ROLES (default: manager, auditor)
    are permitted to upload and index documents dynamically.
    """
    from src.ingestion.upload_ingest import ingest_uploaded_document, UploadValidationError
    from src.rag.baseline import invalidate_provenance_catalog

    if user.role not in settings.UPLOAD_ALLOWED_ROLES:
        raise ApiError(
            403,
            "FORBIDDEN",
            f"Role '{user.role}' is not authorized to upload documents.",
        )

    roles_list: list[str] = []
    try:
        parsed = json.loads(allowed_roles)
        if isinstance(parsed, list):
            roles_list = [str(r).strip() for r in parsed if str(r).strip()]
        elif isinstance(parsed, str):
            roles_list = [r.strip() for r in parsed.split(",") if r.strip()]
    except Exception:
        roles_list = [r.strip() for r in allowed_roles.split(",") if r.strip()]

    if not roles_list:
        roles_list = ["manager", "auditor"]

    if hasattr(file, "file") and hasattr(file.file, "read"):
        content = file.file.read()
    elif hasattr(file, "read"):
        content = file.read()
    else:
        content = b""
    filename = file.filename or "uploaded_document.txt"

    clean_doc_id = str(doc_id).strip() if (doc_id and isinstance(doc_id, str) and doc_id.strip()) else None
    clean_title = str(title).strip() if (title and isinstance(title, str) and title.strip()) else None
    clean_doc_type = str(doc_type).strip() if (doc_type and isinstance(doc_type, str) and doc_type.strip()) else "custom"

    try:
        result = ingest_uploaded_document(
            file_bytes=content,
            filename=filename,
            user_id=user.id,
            user_role=user.role,
            allowed_roles=roles_list,
            doc_id=clean_doc_id,
            title=clean_title,
            doc_type=clean_doc_type,
            qdrant_indexer=baseline_pipeline.qdrant,
            bm25_indexer=baseline_pipeline.bm25,
        )
        baseline_pipeline.bm25.load()
        invalidate_provenance_catalog()
    except UploadValidationError as exc:
        raise ApiError(400, "INVALID_UPLOAD", str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to ingest uploaded document '%s': %s", filename, exc)
        raise ApiError(500, "INGESTION_ERROR", "Document ingestion failed due to a server processing error.") from exc

    return DocumentUploadResponse(
        doc_id=result["doc_id"],
        filename=result["filename"],
        title=result["title"],
        chunks_indexed=result["chunks_indexed"],
        allowed_roles=result["allowed_roles"],
        doc_type=result["doc_type"],
        file_path=Path(str(result["file_path"])).name,
        message=result["message"],
    )


@router.get("/api/v1/documents", response_model=DocumentListResponse)
def list_documents(user: CurrentUser = Depends(get_current_user)) -> DocumentListResponse:
    """List documents in the compliance catalog visible to the caller's role."""
    with get_db_connection() as conn:
        rows = Repository(conn).list_documents()

    items: list[DocumentListItem] = []
    for r in rows:
        roles_raw = r["allowed_roles"]
        roles: list[str] = []
        try:
            roles = json.loads(roles_raw) if isinstance(roles_raw, str) else list(roles_raw)
        except Exception:
            roles = [r.strip() for r in str(roles_raw).split(",") if r.strip()]

        if user.role.lower() in [role.lower() for role in roles]:
            trust = build_verification_metadata(
                {
                    "doc_id": str(r["id"]),
                    "doc_title": str(r["filename"]),
                    "jurisdiction": str(r["source_jurisdiction"]),
                    "doc_type": str(r["doc_type"]),
                }
            )
            items.append(
                DocumentListItem(
                    id=str(r["id"]),
                    filename=str(r["filename"]),
                    source_jurisdiction=str(r["source_jurisdiction"]),
                    doc_type=str(r["doc_type"]),
                    version=str(r["version"]),
                    allowed_roles=roles,
                    file_path=Path(str(r["file_path"])).name,
                    total_chunks=int(r["total_chunks"] or 0),
                    created_at=str(r["created_at"]) if r["created_at"] is not None else None,
                    source_url=trust.get("source_url"),
                    source_name=trust.get("source_name"),
                    is_internal=bool(trust.get("is_internal", False)),
                )
            )

    return DocumentListResponse(documents=items, total=len(items))


__all__ = ["router"]
