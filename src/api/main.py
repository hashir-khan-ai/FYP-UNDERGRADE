"""FastAPI application: baseline endpoints plus Phase 3 auth, RBAC and memory."""

import logging
import re
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api.deps import ApiError, CurrentUser, enforce_query_rate_limit, get_current_user
from src.api.routes import router as api_router
from src.config import settings
from src.core.llm_client import LLMAuthError, LLMUnavailableError
from src.core.rate_limiter import RateLimitExceededError
from src.core.spend_guard import SpendGuardExceededError, spend_guard
from src.core.telemetry import configure_correlation_logging, get_audit_id, request_correlation_scope
from src.db.connection import get_db_connection
from src.db.migrations import init_db
from src.ingestion.embeddings import ModelWeightsMissingError
from src.rag.baseline import BaselineRAGRequest, BaselineRAGResponse, baseline_pipeline

logger = logging.getLogger("api")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Configure logging, validate startup readiness, ensure schema, and release Qdrant on exit."""
    configure_correlation_logging()
    settings.ensure_directories()
    settings.validate_security_flags()
    try:
        settings.ensure_llm_ready()
    except Exception as exc:
        logger.warning("LLM configuration readiness check deferred (%s).", type(exc).__name__)
    try:
        init_db()
    except Exception:
        logger.exception("Database initialisation failed at startup.")
    try:
        yield
    finally:
        baseline_pipeline.close()


app = FastAPI(
    title="Enterprise Banking Compliance Assistant",
    description="Regulatory RAG Assistant for banking compliance (COM6301)",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Retry-After", "X-Request-ID"],
)

app.include_router(api_router)


@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    """Attach request and audit correlation IDs without logging sensitive payloads."""
    incoming = request.headers.get("X-Request-ID", "").strip()
    req_id = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex[:16]
    started = time.perf_counter()
    with request_correlation_scope(req_id):
        response = await call_next(request)
        latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
        response.headers["X-Request-ID"] = req_id
        logger.info(
            "request_completed method=%s path=%s status=%s latency_ms=%.2f request_id=%s audit_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            latency_ms,
            req_id,
            get_audit_id(),
        )
        return response


def _error(status_code: int, code: str, message: str, details: object = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details}},
    )


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    return _error(exc.status_code, exc.code, exc.message, exc.details)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    code = {401: "UNAUTHENTICATED", 403: "FORBIDDEN", 404: "NOT_FOUND"}.get(
        exc.status_code, "HTTP_ERROR"
    )
    detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
    return _error(exc.status_code, code, detail)


@app.exception_handler(SpendGuardExceededError)
async def spend_guard_exception_handler(request: Request, exc: SpendGuardExceededError):
    logger.warning("LLM guard triggered (%s): %s", exc.error_code, exc.internal_detail)
    return _error(
        exc.http_status,
        exc.error_code,
        exc.user_message,
    )


@app.exception_handler(RateLimitExceededError)
async def rate_limit_exception_handler(request: Request, exc: RateLimitExceededError):
    logger.warning("API rate limit exceeded (%s).", exc.scope)
    return JSONResponse(
        status_code=exc.http_status,
        content={"error": {"code": exc.error_code, "message": exc.user_message, "details": None}},
        headers={"Retry-After": str(exc.retry_after)},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    details = [
        {
            "location": list(error.get("loc", [])),
            "message": error.get("msg", "Invalid value"),
            "type": error.get("type", "value_error"),
        }
        for error in exc.errors()
    ]
    return _error(
        422,
        "VALIDATION_ERROR",
        "Invalid request body.",
        details,
    )


@app.exception_handler(LLMAuthError)
async def llm_auth_exception_handler(request: Request, exc: LLMAuthError):
    return _error(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "LLM_AUTH_ERROR",
        "The configured LLM provider rejected the server credentials.",
    )


@app.exception_handler(LLMUnavailableError)
async def llm_unavailable_exception_handler(request: Request, exc: LLMUnavailableError):
    return _error(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "LLM_UNAVAILABLE",
        "The LLM provider is currently unavailable. Please retry later.",
    )


@app.exception_handler(ModelWeightsMissingError)
async def model_weights_missing_handler(request: Request, exc: ModelWeightsMissingError):
    logger.error("Local offline model weights unavailable: %s", exc)
    return _error(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "MODEL_WEIGHTS_MISSING",
        "Local offline embedding or re-ranking model weights are unavailable on this server.",
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled server error: %s", type(exc).__name__, exc_info=True)
    return _error(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "INTERNAL_SERVER_ERROR",
        "An internal server error occurred.",
    )


def _health_payload() -> dict:
    db_ok = False
    try:
        with get_db_connection() as conn:
            conn.execute("SELECT 1;")
            db_ok = True
    except Exception:
        pass

    try:
        llm_info = {
            "profile": settings.llm.profile,
            "model": settings.llm.model,
            "is_mock": settings.llm.is_mock,
        }
    except Exception:
        llm_info = {
            "profile": settings.LLM_PROFILE,
            "model": "unconfigured",
            "is_mock": settings.LLM_PROFILE == "mock",
        }

    try:
        vector_count = baseline_pipeline.qdrant.count()
        vector_status = "online"
    except Exception:
        vector_count = 0
        vector_status = "unavailable"

    return {
        "status": "healthy" if db_ok else "degraded",
        "database": {"connected": db_ok, "engine": "sqlite"},
        "llm": llm_info,
        "models": {
            "embeddings": settings.EMBEDDING_MODEL_NAME,
            "reranker": settings.RERANKER_MODEL_NAME,
        },
        "vector_store": {
            "status": vector_status,
            "mode": "qdrant_embedded",
            "collection": "compliance_chunks",
            "total_vectors": vector_count,
        },
        "layers": {
            "adaptive_router": settings.ENABLE_ADAPTIVE_ROUTER,
            "corrective_grader": settings.ENABLE_CORRECTIVE_GRADER,
            "rbac": settings.rbac_enabled,
            "memory": settings.ENABLE_MEMORY,
            "rbac_memory": settings.rbac_enabled and settings.ENABLE_MEMORY,
            "xai_output": settings.ENABLE_XAI_OUTPUT,
            "heading_path": settings.ENABLE_HEADING_PATH,
        },
    }


@app.get("/health")
def health_check():
    """Return database, active profile, local model and vector index status."""
    return _health_payload()


@app.get("/ready")
def readiness_check():
    """Readiness probe verifying database connectivity, LLM config, and vector store."""
    payload = _health_payload()
    db_ok = bool(payload.get("database", {}).get("connected"))
    vector_online = payload.get("vector_store", {}).get("status") == "online"
    try:
        settings.ensure_llm_ready()
        llm_ready = True
    except Exception:
        llm_ready = False

    is_ready = db_ok and llm_ready and vector_online
    return JSONResponse(
        status_code=status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "status": "ready" if is_ready else "not_ready",
            "checks": {
                "database": db_ok,
                "llm_config": llm_ready,
                "vector_store": vector_online,
            },
            "profile": payload.get("llm", {}).get("profile"),
        },
    )


@app.get("/api/v1/admin/health")
def admin_health_check(user: CurrentUser = Depends(get_current_user)):
    """API.md health endpoint; requires authentication."""
    return _health_payload()


@app.post(
    "/ask",
    response_model=BaselineRAGResponse,
    dependencies=[Depends(enforce_query_rate_limit)],
)
def ask_question(
    request: BaselineRAGRequest,
    user: CurrentUser = Depends(get_current_user),
) -> BaselineRAGResponse:
    """Answer a compliance question with the caller's role enforced server-side."""
    query = request.query.strip()
    if not query:
        raise ApiError(400, "EMPTY_QUERY", "Query string cannot be empty.")
    resolved = settings.llm
    with spend_guard.run_scope(
        f"ask:{uuid.uuid4()}",
        profile=resolved.profile,
        has_paid_quota=resolved.has_paid_quota,
        is_local=resolved.is_local,
    ):
        return baseline_pipeline.ask(query, role=user.role, session_id=request.session_id)

