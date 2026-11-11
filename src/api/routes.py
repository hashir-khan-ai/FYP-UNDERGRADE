"""Phase 3 API routes: auth, sessions, RBAC-scoped chat and audit.

Every protected route derives the user and role from the signed bearer token.
Client-supplied role or user identifiers are ignored by construction.
"""

import json
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, status

from src.api.deps import ApiError, CurrentUser, get_current_user, require_role
from src.api.schemas import (
    AdminConfigResponse,
    AuditLogEntry,
    ChatQueryRequest,
    ChatQueryResponse,
    Citation,
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
    SessionSummary,
    SpendStats,
    UserProfile,
)
from src.config import settings
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
from src.core.memory import (
    MemoryContext,
    load_recent_turns,
    memory_metadata,
    rewrite_follow_up,
)
from src.core.router import (
    DIRECT,
    DIRECT_REPLIES,
    ROUTE_API_NAMES,
    SPLIT,
    RouteDecision,
    classify_question,
    router_metadata,
)
from src.core.spend_guard import spend_guard
from src.db.connection import get_db_connection
from src.db.repository import Repository
from src.rag.baseline import BaselineRAGResponse, baseline_pipeline

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


@router.post(
    "/api/v1/sessions",
    response_model=SessionSummary,
    status_code=status.HTTP_201_CREATED,
)
def create_session(
    payload: SessionCreateRequest | None = None,
    user: CurrentUser = Depends(get_current_user),
) -> SessionSummary:
    """Create a chat session owned by the authenticated user."""
    session_id = str(uuid.uuid4())
    title = (payload.title if payload and payload.title else "").strip() or "New Compliance Session"
    with get_db_connection() as conn:
        Repository(conn).create_session(session_id, user.id, title)
        row = Repository(conn).get_session_for_user(session_id, user.id)
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
    return {"status": "deleted", "session_id": session_id}


# ==============================================================================
# Chat (RBAC-scoped RAG)
# ==============================================================================
@router.post("/api/v1/chat/query", response_model=ChatQueryResponse)
def chat_query(
    payload: ChatQueryRequest,
    user: CurrentUser = Depends(get_current_user),
) -> ChatQueryResponse:
    """Execute the RAG pipeline with the caller's role enforced server-side.

    The role always comes from the authenticated session. ``config_overrides``
    is accepted for API compatibility but never disables RBAC or memory.
    """
    started = time.perf_counter()
    session_id = str(payload.session_id)
    query = payload.query.strip()
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
    router_enabled = settings.ENABLE_ADAPTIVE_ROUTER
    decision: RouteDecision | None = None
    route = SINGLE_SEARCH_API
    if router_enabled:
        decision = classify_question(
            baseline_pipeline.llm,
            memory.standalone_question,
            session_id=session_id,
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
        resolved_llm = settings.llm
        step_timings.append(
            {
                "step": "direct_reply",
                "latency_ms": round(decision.latency_ms, 2),
                "tokens": decision.tokens_used,
            }
        )
    else:
        if decision is not None and decision.route == SPLIT:
            result = baseline_pipeline.ask_split(
                memory.standalone_question,
                list(decision.sub_questions),
                role=user.role,
                session_id=session_id,
            )
            step_timings.extend(result.step_timings)
        else:
            result = baseline_pipeline.ask(
                query,
                role=user.role,
                rewritten_query=memory.standalone_question if memory.rewritten else None,
                session_id=session_id,
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
        resolved_llm = settings.llm

    latency_ms = (time.perf_counter() - started) * 1000.0

    citations = [
        Citation(
            doc_id=source.doc_id,
            doc_name=source.doc_title,
            section_title=source.section,
            clause_id=source.clause or "",
            page_number=source.page,
            snippet=source.snippet,
        )
        for source in sources
    ]

    if not router_enabled:
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
                    "latency_ms": round(latency_ms, 2),
                    "cached": cached,
                    "tokens_prompt": usage["prompt_tokens"],
                    "tokens_completion": usage["completion_tokens"],
                    "router": router_metadata(decision) if decision is not None else None,
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
            rewritten_query=rewritten_query,
            reasoning_trace=reasoning_trace,
            citations_json=[citation.model_dump() for citation in citations],
            tokens_prompt=usage["prompt_tokens"],
            tokens_completion=usage["completion_tokens"],
            llm_profile=resolved_llm.profile,
            llm_calls=usage["calls"],
            cached_calls=usage["cached_calls"],
            spend_guard_hit=spend_guard.exhausted,
            prompt_version=settings.PROMPT_VERSION,
            llm_model=resolved_llm.model,
            candidates_retrieved=candidates_retrieved,
            candidates_filtered=candidates_filtered,
            router_confidence=decision.confidence if decision is not None else None,
            router_fallback_reason=decision.fallback_reason if decision is not None else None,
            sub_questions=list(decision.sub_questions) if decision is not None else [],
            step_timings=step_timings,
        )

    return ChatQueryResponse(
        session_id=session_id,
        answer=answer,
        route_taken=route,
        citations=citations,
        reasoning_trace=reasoning_trace,
        retrieval_stats=RetrievalStats(
            total_chunks_retrieved=retrieval_total,
            top_rerank_score=top_rerank_score,
            retry_count=0,
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
        spend=SpendStats(
            calls_used=spend_guard.calls_count,
            calls_limit=spend_guard.max_calls,
            tokens_used=spend_guard.tokens_count,
            tokens_limit=spend_guard.max_tokens,
            exhausted=spend_guard.exhausted,
        ),
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
    )


# ==============================================================================
# Audit trail and admin configuration
# ==============================================================================
@router.get("/api/v1/audit/logs", response_model=list[AuditLogEntry])
def audit_logs(
    limit: int = Query(default=50, ge=1, le=200),
    user_id: int | None = Query(default=None),
    start_date: str | None = Query(default=None),
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
            user_id=user_id,
            start_date=start_date,
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
            created_at=str(row["created_at"]) if row["created_at"] is not None else None,
        )
        for row in rows
    ]


@router.get("/api/v1/admin/config", response_model=AdminConfigResponse)
def admin_config(user: CurrentUser = Depends(get_current_user)) -> AdminConfigResponse:
    """Expose the active profile, layer flags and spend caps (no secrets)."""
    resolved = settings.llm
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
        },
        spend_caps={
            "calls_limit": settings.LLM_MAX_CALLS_PER_RUN,
            "tokens_limit": settings.LLM_MAX_TOKENS_PER_RUN,
        },
        token_ttl_minutes=settings.AUTH_TOKEN_TTL_MINUTES,
    )


__all__ = ["router"]
