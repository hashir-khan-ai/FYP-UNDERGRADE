"""FastAPI application: baseline endpoints plus Phase 3 auth, RBAC and memory."""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.api.deps import ApiError, CurrentUser, get_current_user
from src.api.routes import router as api_router
from src.config import settings
from src.core.llm_client import LLMAuthError, LLMUnavailableError
from src.core.spend_guard import SpendGuardExceededError
from src.db.connection import get_db_connection
from src.db.migrations import init_db
from src.rag.baseline import BaselineRAGRequest, BaselineRAGResponse, baseline_pipeline

logger = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate security flags, ensure the schema, and release Qdrant on exit."""
    settings.validate_security_flags()
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
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(api_router)


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
    return _error(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "LLM_SPEND_LIMIT",
        str(exc),
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
        },
    }


@app.get("/health")
def health_check():
    """Return database, active profile, local model and vector index status."""
    return _health_payload()


@app.get("/api/v1/admin/health")
def admin_health_check(user: CurrentUser = Depends(get_current_user)):
    """API.md health endpoint; requires authentication."""
    return _health_payload()


@app.post("/ask", response_model=BaselineRAGResponse)
def ask_question(
    request: BaselineRAGRequest,
    user: CurrentUser = Depends(get_current_user),
) -> BaselineRAGResponse:
    """Answer a compliance question with the caller's role enforced server-side."""
    query = request.query.strip()
    if not query:
        raise ApiError(400, "EMPTY_QUERY", "Query string cannot be empty.")
    return baseline_pipeline.ask(query, role=user.role, session_id=request.session_id)

