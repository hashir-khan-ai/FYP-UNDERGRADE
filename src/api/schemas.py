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


class RetrievalStats(BaseModel):
    total_chunks_retrieved: int
    top_rerank_score: float
    retry_count: int
    rewritten_query: str | None = None


class ChatQueryRequest(BaseModel):
    session_id: UUID4 = Field(..., description="UUIDv4 session identifier")
    query: str = Field(..., min_length=2, max_length=2000)
    config_overrides: ConfigOverrides | None = None


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


class SessionCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=120)


class SessionSummary(BaseModel):
    id: str
    title: str
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


class LogoutResponse(BaseModel):
    status: str = "ok"
