"""Pydantic v2 request and response models for the Phase 3 API surface.

Shapes follow API.md section 4. Session and audit models cover the endpoints
implemented in Phase 3.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field, UUID4


class LoginRequest(BaseModel):
    """Synthetic user credentials."""

    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=200)


class UserProfile(BaseModel):
    """Public user identity; never includes the password hash."""

    id: int
    username: str
    full_name: str
    role: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserProfile


class ConfigOverrides(BaseModel):
    """Ablation switches accepted for contract compatibility.

    Phase 3 ignores these for security: RBAC and memory are server-authoritative
    configuration and cannot be disabled by a client request.
    """

    enable_adaptive_router: bool | None = None
    enable_corrective_grader: bool | None = None
    enable_rbac_memory: bool | None = None
    enable_xai_output: bool | None = None


class Citation(BaseModel):
    doc_id: str
    doc_name: str
    section_title: str
    clause_id: str
    page_number: int | None = None
    snippet: str
    # Phase 6A structured citation fields (kept alongside Phase 3 fields for backward compatibility)
    chunk_id: str = ""
    doc_title: str = ""
    heading_path: str = ""
    clause: str = ""
    page: int | None = None
    quote_snippet: str = ""
    # Verifiable source metadata
    source_url: str | None = None
    verification_url: str | None = None
    source_name: str | None = None
    content_origin: str | None = None
    is_internal: bool = False
    # Roles permitted to retrieve this source; used only to label access in the UI.
    allowed_roles: list[str] = Field(default_factory=list)


class LLMStats(BaseModel):
    profile: str
    model: str
    prompt_version: str
    calls: int
    cached_calls: int
    prompt_tokens: int
    completion_tokens: int
    cached_response: bool


class SpendStats(BaseModel):
    calls_used: int
    calls_limit: int
    tokens_used: int
    tokens_limit: int
    exhausted: bool
    calls_remaining: int = 0
    tokens_remaining: int = 0
    scope: str = "offline"
    profile: str = "mock"
    is_paid: bool = False
    run_id: str | None = None
    offline_calls: int = 0
    offline_tokens: int = 0
    local_calls: int = 0
    local_tokens: int = 0
    cached_calls: int = 0
    saved_tokens: int = 0
    session_calls: int = 0
    session_tokens: int = 0
    session_calls_limit: int = 0
    session_tokens_limit: int = 0
    tokens_estimated: bool = False


class RetrievalStats(BaseModel):
    total_chunks_retrieved: int
    top_rerank_score: float
    retry_count: int
    rewritten_query: str | None = None


class ChatQueryRequest(BaseModel):
    session_id: UUID4 = Field(..., description="UUIDv4 session identifier")
    query: str = Field(..., min_length=2, max_length=2000)
    role: str | None = Field(
        default=None,
        description="Client-supplied role (ignored in production, used only in mutant testing)",
    )
    config_overrides: ConfigOverrides | None = None
    response_mode: Literal["compliance", "explain"] = Field(
        default="compliance",
        description="Response mode: 'compliance' (strict, concise) or 'explain' (conversational AI overview)",
    )
    intent_mode: Literal["auto", "rag", "general"] = Field(
        default="auto",
        description="Intent routing mode: 'auto' (smart classification), 'rag' (force Company Docs RAG), or 'general' (force General Chat)",
    )
    fallback_offline: bool = Field(
        default=False,
        description="When true, execute this turn using the offline deterministic fallback profile.",
    )


class RouterStats(BaseModel):
    """Adaptive router observability for one request (no passage or prompt text)."""

    enabled: bool = False
    route: str = "SINGLE_SEARCH"
    confidence: float | None = None
    sub_questions: list[str] = Field(default_factory=list)
    fallback_used: bool = False
    fallback_reason: str | None = None
    direct_category: str | None = None
    latency_ms: float = 0.0
    tokens_used: int = 0


class GraderStats(BaseModel):
    """Phase 5 corrective grader observability for one request (no passage text)."""

    enabled: bool = False
    path: str | None = None  # shortcut_keep | shortcut_reject | llm_grade
    relevant_count: int = 0
    ambiguous_count: int = 0
    irrelevant_count: int = 0
    rewrite_used: bool = False
    refused: bool = False
    refusal_reason: str = ""
    grader_calls: int = 0
    tokens_used: int = 0
    latency_ms: float = 0.0


class ChatQueryResponse(BaseModel):
    session_id: str
    answer: str
    route_taken: str
    route: str = "SINGLE_SEARCH"
    citations: list[Citation]
    reasoning_trace: list[str]
    retrieval_stats: RetrievalStats
    llm_stats: LLMStats
    spend: SpendStats
    latency_ms: float
    audit_id: int
    role: str
    rbac_enabled: bool
    candidates_filtered_by_role: int
    router: RouterStats = Field(default_factory=RouterStats)
    grader: GraderStats = Field(default_factory=GraderStats)
    # Phase 6A structured fields
    grader_path: str | None = None
    refusal: str | None = None
    refusal_category: str | None = None
    timings: dict[str, float] = Field(default_factory=dict)
    citations_dropped: int = 0
    heading_path_enabled: bool = True
    response_mode: str = "compliance"
    intent_mode: str = "auto"
    response_type: str = "rag"
    grounded: bool = True
    suggested_follow_ups: list[str] = Field(default_factory=list)
    active_layers: dict[str, bool] = Field(default_factory=dict)
    claim_check: dict[str, Any] | None = None
    calculator: dict[str, Any] | None = None
    session_title: str | None = None


class SessionCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=120)


class SessionRenameRequest(BaseModel):
    """New title for a session owned by the authenticated caller."""

    title: str = Field(..., min_length=1, max_length=120)


class SessionSummary(BaseModel):
    id: str
    title: str
    title_source: str = "default"
    title_locked: bool = False
    created_at: str | None = None
    updated_at: str | None = None


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary]


class MessageSummary(BaseModel):
    id: int
    sender: Literal["user", "assistant", "system"]
    content: str
    route_used: str | None = None
    user_role: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: str | None = None


class SessionMessagesResponse(BaseModel):
    session_id: str
    messages: list[MessageSummary]


class AuditLogEntry(BaseModel):
    """Audit *summary* row.

    Stored ``query_text`` and ``response_text`` are deliberately not exposed
    here: the auditor may read summaries, but a user's own turn text is only
    available to that user through their own session messages endpoint.
    """

    audit_id: int
    session_id: str | None = None
    user_id: int
    user_role: str
    final_route: str
    retrieved_chunk_ids: list[str] = Field(default_factory=list)
    latency_ms: float
    tokens_prompt: int = 0
    tokens_completion: int = 0
    llm_profile: str = "mock"
    llm_model: str | None = None
    llm_calls: int = 0
    cached_calls: int = 0
    candidates_retrieved: int = 0
    candidates_filtered: int = 0
    router_confidence: float | None = None
    router_fallback_reason: str | None = None
    citation_count: int | None = None
    citations_dropped: int | None = None
    heading_path_enabled: bool | None = None
    created_at: str | None = None


class AuditLogListResponse(BaseModel):
    logs: list[AuditLogEntry]


class AdminConfigResponse(BaseModel):
    profile: str
    model: str
    prompt_version: str
    rbac_enabled: bool
    memory_enabled: bool
    layers: dict[str, bool]
    spend_caps: dict[str, int]
    token_ttl_minutes: int
    run_budget: SpendStats | None = None


class LatencyMetrics(BaseModel):
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    avg_ms: float = 0.0
    sample_count: int = 0


class IndexMetrics(BaseModel):
    vector_count: int = 0
    bm25_chunks: int = 0
    status: str = "online"


class AuditMetrics(BaseModel):
    total_turns: int = 0
    total_role_filtered: int = 0
    total_citations_dropped: int = 0


class AdminMetricsResponse(BaseModel):
    profile: str
    model: str
    prompt_version: str
    is_mock: bool
    is_local: bool
    is_paid: bool
    total_calls: int = 0
    cached_calls: int = 0
    error_calls: int = 0
    cache_hit_rate: float = 0.0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    latency: LatencyMetrics
    index: IndexMetrics
    audit: AuditMetrics
    guard_status: SpendStats


class LogoutResponse(BaseModel):
    status: str = "ok"


class DocumentUploadResponse(BaseModel):
    doc_id: str
    filename: str
    title: str
    chunks_indexed: int
    allowed_roles: list[str]
    doc_type: str
    file_path: str
    message: str = "Document successfully ingested and indexed."


class DocumentListItem(BaseModel):
    id: str
    filename: str
    source_jurisdiction: str
    doc_type: str
    version: str
    allowed_roles: list[str]
    file_path: str
    total_chunks: int
    created_at: str | None = None
    # Additive trust metadata: official URL only from trusted sidecars;
    # internal documents carry no public link.
    source_url: str | None = None
    source_name: str | None = None
    is_internal: bool = False


class DocumentListResponse(BaseModel):
    documents: list[DocumentListItem]
    total: int

