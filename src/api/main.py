"""FastAPI application exposing the Phase 2 baseline RAG endpoints."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.config import settings
from src.core.llm_client import LLMAuthError, LLMUnavailableError
from src.core.spend_guard import SpendGuardExceededError
from src.db.connection import get_db_connection
from src.db.migrations import init_db
from src.rag.baseline import BaselineRAGRequest, BaselineRAGResponse, baseline_pipeline

logger = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ensure the SQLite schema and additive telemetry migrations exist."""
    try:
        init_db()
    except Exception:
        logger.exception("Database initialisation failed at startup.")
    yield


app = FastAPI(
    title="Enterprise Banking Compliance Assistant",
    description="Regulatory RAG Assistant for banking compliance (COM6301)",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def _error(status_code: int, code: str, message: str, details: object = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details}},
    )


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
            "rbac_memory": settings.ENABLE_RBAC_MEMORY,
            "xai_output": settings.ENABLE_XAI_OUTPUT,
        },
    }


@app.get("/health")
def health_check():
    """Return database, active profile, local model and vector index status."""
    return _health_payload()


@app.get("/api/v1/admin/health")
def admin_health_check():
    """API.md-compatible alias for the baseline health endpoint."""
    return _health_payload()


@app.post("/ask", response_model=BaselineRAGResponse)
def ask_question(request: BaselineRAGRequest):
    """Answer a compliance question through the baseline hybrid RAG pipeline."""
    if not request.query.strip():
        return _error(
            status.HTTP_400_BAD_REQUEST,
            "EMPTY_QUERY",
            "Query string cannot be empty.",
        )
    return baseline_pipeline.ask(request.query.strip())


@app.post("/api/v1/chat/query", response_model=BaselineRAGResponse)
def chat_query_alias(request: BaselineRAGRequest):
    """Phase 2 baseline alias; session/RBAC fields land in Phase 3."""
    return ask_question(request)
