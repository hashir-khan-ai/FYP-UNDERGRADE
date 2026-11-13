"""Application configuration management using Pydantic Settings."""

import os
from pathlib import Path
from typing import Literal

# Ensure local CPU embedding and cross-encoder models default to offline cached mode
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


from urllib.parse import urlparse
from pydantic import model_validator

_LOCAL_PROVIDER_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"})


def is_local_provider_url(base_url: str | None) -> bool:
    """Return True when a configured OpenAI-compatible base_url points to a loopback/local host."""
    if not base_url:
        return False
    parsed = urlparse(base_url.strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    return host in _LOCAL_PROVIDER_HOSTS or host.endswith(".local")


class ResolvedLLM(BaseModel):
    """Fully resolved LLM provider settings for the active profile."""

    profile: Literal["mock", "dev", "demo"]
    model: str
    base_url: str | None = None
    api_key: str | None = None
    temperature: float = 0.0
    timeout_seconds: float = 15.0
    max_retries: int = 3
    max_rpm: int = 20
    is_mock: bool = False
    is_local: bool = False
    has_paid_quota: bool = False

    @model_validator(mode="after")
    def _derive_quota_flags(self) -> "ResolvedLLM":
        """Derive single-source-of-truth local and paid-quota flags on resolved settings."""
        if "is_local" not in self.model_fields_set:
            if self.profile == "mock" or self.is_mock:
                self.is_local = True
            elif self.profile == "dev":
                self.is_local = is_local_provider_url(self.base_url)
            else:
                self.is_local = False

        if "has_paid_quota" not in self.model_fields_set:
            if self.profile == "mock" or self.is_mock:
                self.has_paid_quota = False
            elif self.profile == "dev":
                self.has_paid_quota = not self.is_local
            else:
                self.has_paid_quota = True

        return self


class Settings(BaseSettings):
    """Central application settings loaded from environment and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server Configuration
    APP_ENV: str = Field(default="development", description="Execution environment")
    API_HOST: str = Field(default="127.0.0.1", description="FastAPI bind address")
    API_PORT: int = Field(default=8000, description="FastAPI port")
    CORS_ORIGINS: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000,http://localhost:8501,http://127.0.0.1:8501",
        description="Comma-separated permitted CORS origins",
    )
    SECRET_KEY: str = Field(
        default="dev-secret-key-change-in-production-32-chars-min",
        description="Cryptographic secret for local session JWTs",
    )

    # LLM Profile: "mock" (no network, for tests), "dev" (free provider), "demo" (paid)
    LLM_PROFILE: Literal["mock", "dev", "demo"] = Field(
        default="dev",
        description="Active LLM profile; tests force 'mock' via tests/conftest.py",
    )

    # dev profile (free-tier or local $0 Ollama OpenAI-compatible provider)
    LLM_BASE_URL: str = Field(
        default="https://api.groq.com/openai/v1",
        description="Base URL for the dev provider (e.g. Groq or local Ollama http://localhost:11434/v1)",
    )
    LLM_API_KEY: str = Field(
        default="",
        description="API key for the dev provider (or 'ollama' when using local Ollama)",
    )
    LLM_MODEL: str = Field(
        default="llama-3.1-8b-instant",
        description="Model identifier for the dev profile (e.g. llama-3.1-8b-instant or local llama3.1:8b / qwen2.5:7b-instruct)",
    )

    # demo profile (paid OpenAI-compatible provider; never borrows dev credentials)
    DEMO_LLM_BASE_URL: str = Field(
        default="https://api.openai.com/v1",
        description="Base URL for the paid provider used by the demo profile",
    )
    DEMO_LLM_API_KEY: str = Field(
        default="",
        description="API key for the paid provider used by the demo profile",
    )
    DEMO_LLM_MODEL: str = Field(
        default="gpt-4o-mini",
        description="Model identifier for the demo profile",
    )

    LLM_TEMPERATURE: float = Field(
        default=0.0,
        description="Deterministic sampling temperature",
    )
    LLM_TIMEOUT_SECONDS: float = Field(
        default=15.0,
        description="Per-request timeout in seconds",
    )
    LLM_MAX_RPM: int = Field(
        default=20,
        description="Token-bucket requests per minute to avoid HTTP 429 errors",
    )
    LLM_MAX_RETRIES: int = Field(
        default=3,
        description="Retries with exponential backoff and jitter before failing",
    )
    LLM_RETRY_BASE_SECONDS: float = Field(
        default=1.0,
        description="Base delay for exponential backoff between safe retries",
    )
    LLM_CACHE_ENABLED: bool = Field(
        default=True,
        description="Serve repeated requests from the on-disk response cache",
    )
    LLM_CACHE_TTL_DAYS: int = Field(
        default=30,
        description="Maximum age of a cached LLM response in days",
    )
    PROMPT_VERSION: str = Field(
        default="v1",
        description="Version folder used under prompts/ and recorded in cache keys/audit rows",
    )

    # Spend guard (per-query + per-session caps for live/paid quota only; mock & local dev bypass paid limits)
    # Adaptive pipeline uses up to 5-7 calls/query (~8k-12k tokens); 25 calls / 120k tokens protects single turns,
    # while 150 calls / 400k tokens caps cumulative live session usage until reset.
    LLM_MAX_CALLS_PER_RUN: int = Field(
        default=25,
        description="Per-query hard cap on paid-profile LLM calls (reset at each user query)",
    )
    LLM_MAX_TOKENS_PER_RUN: int = Field(
        default=120_000,
        description="Per-query hard cap on paid-profile prompt + completion tokens (reset at each user query)",
    )
    LLM_MAX_CALLS_PER_SESSION: int = Field(
        default=150,
        description="Cumulative per-session hard cap on paid-profile LLM calls before user reset",
    )
    LLM_MAX_TOKENS_PER_SESSION: int = Field(
        default=400_000,
        description="Cumulative per-session hard cap on paid-profile tokens before user reset",
    )
    LLM_LOCAL_SAFETY_CALLS: int = Field(
        default=1000,
        description="Runaway-loop call safety ceiling for local/self-hosted dev models (never billed as API quota)",
    )
    LLM_LOCAL_SAFETY_TOKENS: int = Field(
        default=4_000_000,
        description="Runaway-loop token safety ceiling for local/self-hosted dev models (never billed as API quota)",
    )

    # Optional dev-only failover (unused under demo to keep runs reproducible)
    FALLBACK_LLM_BASE_URL: str = Field(
        default="https://openrouter.ai/api/v1",
        description="Base URL for fallback OpenAI-compatible API endpoint",
    )
    FALLBACK_LLM_API_KEY: str = Field(
        default="",
        description="API Key for fallback LLM provider",
    )
    FALLBACK_LLM_MODEL: str = Field(
        default="meta-llama/llama-3.1-8b-instruct:free",
        description="Model identifier for fallback LLM",
    )

    # Local CPU Models
    EMBEDDING_MODEL_NAME: str = Field(
        default="BAAI/bge-small-en-v1.5",
        description="Local CPU HuggingFace embedding model",
    )
    RERANKER_MODEL_NAME: str = Field(
        default="cross-encoder/ms-marco-MiniLM-L-6-v2",
        description="Local CPU Cross-Encoder re-ranking model",
    )

    # Storage Directories
    DATABASE_PATH: str = Field(
        default="./data/sqlite/app.db",
        description="Path to SQLite database file",
    )
    QDRANT_STORAGE_PATH: str = Field(
        default="./data/qdrant",
        description="Directory for local embedded Qdrant vector storage",
    )
    BM25_INDEX_PATH: str = Field(
        default="./data/sqlite/bm25_index.pkl",
        description="Pickled BM25 index built from the same chunks as Qdrant",
    )
    UPLOAD_DIR: str = Field(
        default="./data/uploads",
        description="Directory for user-uploaded documents",
    )
    UPLOAD_MAX_FILE_SIZE_MB: int = Field(
        default=10,
        description="Maximum upload file size in megabytes",
    )
    UPLOAD_ALLOWED_EXTENSIONS: list[str] = Field(
        default=["md", "txt", "pdf", "html", "htm"],
        description="Allowed file extensions for dynamic document uploads",
    )
    UPLOAD_ALLOWED_ROLES: list[str] = Field(
        default=["manager", "auditor"],
        description="User roles permitted to upload and index documents dynamically",
    )

    # Ablation Experiment Flags. Phase 2 is baseline-only, so every later layer is
    # explicitly disabled until its phase is authorised.
    ENABLE_ADAPTIVE_ROUTER: bool = Field(
        default=False,
        description="Layer 1: Adaptive Router (direct reply, single search, split)",
    )
    ENABLE_CORRECTIVE_GRADER: bool = Field(
        default=False,
        description="Layer 2: Corrective Grader (passage check, retry rewrite, refusal)",
    )
    ENABLE_RBAC_MEMORY: bool = Field(
        default=False,
        description="Layer 3: Session Memory and Server-side RBAC retrieval filtering",
    )
    ENABLE_XAI_OUTPUT: bool = Field(
        default=False,
        description="Layer 4: Clause-level citations, reasoning trace, audit log",
    )
    ENABLE_HEADING_PATH: bool = Field(
        default=True,
        description="Structure-aware retrieval: include full heading path in chunk embeddings and BM25",
    )
    ENABLE_GRAPH_RAG: bool = Field(
        default=False,
        description="Enable local SQLite knowledge-graph cross-reference augmentation in hybrid retrieval",
    )
    ENABLE_CLAIM_CHECK: bool = Field(
        default=False,
        description="Phase 8C: Verify atomic answer claims against retrieved role-permitted passages",
    )
    ENABLE_CALCULATOR: bool = Field(
        default=False,
        description="Phase 8C: Deterministic AST-whitelisted compliance calculator with cited operands",
    )

    # Phase 3 security and memory flags. RBAC is on by default and may only be
    # disabled in tests or in an explicitly labelled baseline ablation.
    ENABLE_RBAC: bool = Field(
        default=True,
        description="Server-side role filtering in Qdrant and BM25 (must stay on)",
    )
    ENABLE_MEMORY: bool = Field(
        default=False,
        description="Short-term session memory and follow-up query rewriting",
    )
    BASELINE_ABLATION: bool = Field(
        default=False,
        description="Explicit label allowing ENABLE_RBAC=false for a documented baseline run",
    )
    DEMO_MODE: bool = Field(
        default=False,
        description="Show 1-click quick-fill demo persona buttons on the login screen when true",
    )
    MEMORY_MAX_TURNS: int = Field(
        default=6,
        description="Number of previous messages loaded into short-term memory",
    )

    # Phase 4 adaptive router. All caps degrade to SINGLE_SEARCH, never to a
    # direct reply, so a misclassification can never bypass retrieval or RBAC.
    ROUTER_CONFIDENCE_THRESHOLD: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Router confidence below which the route degrades to SINGLE_SEARCH",
    )
    ROUTER_MAX_SUB_QUESTIONS: int = Field(
        default=3,
        ge=2,
        le=3,
        description="Hard cap on decomposed sub-questions (PLAN.md allows 2-3)",
    )
    ROUTER_MAX_RETRIEVAL_CALLS: int = Field(
        default=3,
        ge=1,
        description="Hard cap on hybrid retrieval calls per request",
    )

    # Phase 5 corrective grader. Thresholds apply to cross-encoder scores after
    # sigmoid normalisation when the re-ranker emits raw logits.
    GRADER_MIN_RELEVANT_PASSAGES: int = Field(
        default=1,
        ge=1,
        description="Relevant passages required before generation; below this the query is retried",
    )
    GRADER_MAX_AMBIGUOUS_KEPT: int = Field(
        default=2,
        ge=0,
        description="Ambiguous passages that may be kept alongside relevant ones",
    )
    GRADER_MAX_CALLS_PER_REQUEST: int = Field(
        default=2,
        ge=1,
        le=4,
        description="Hard cap on grader LLM calls per request (first pass + one retry)",
    )
    GRADER_SHORTCUT_ENABLED: bool = Field(
        default=True,
        description="Skip the grading LLM call when cross-encoder scores are decisive",
    )
    GRADER_SHORTCUT_KEEP_SCORE: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Top score at or above which the shortcut may keep passages ungraded",
    )
    GRADER_SHORTCUT_MEDIUM_SCORE: float = Field(
        default=0.65,
        ge=0.0,
        le=1.0,
        description="Score a passage must reach to count towards the shortcut keep minimum",
    )
    GRADER_SHORTCUT_REJECT_SCORE: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        description="If every passage scores below this, skip grading and go to rewrite/refuse",
    )
    GRADER_MAX_REWRITE_CHARS: int = Field(
        default=300,
        ge=50,
        description="Maximum length of a rewritten query accepted by the grader retry",
    )

    # Local demo authentication
    AUTH_TOKEN_TTL_MINUTES: int = Field(
        default=60,
        description="Lifetime of a signed access token in minutes",
    )
    AUTH_MAX_LOGIN_ATTEMPTS: int = Field(
        default=5,
        description="Failed logins allowed before the account is temporarily locked",
    )
    AUTH_LOCKOUT_SECONDS: int = Field(
        default=300,
        description="Lockout duration after too many failed logins",
    )
    AUTH_LOGIN_RATE_LIMIT_PER_MINUTE: int = Field(
        default=10,
        description="Login attempts allowed per minute per username and client",
    )
    API_RATE_LIMIT_PER_MINUTE: int = Field(
        default=60,
        ge=1,
        description="API query requests allowed per minute per authenticated user and IP",
    )
    API_UPLOAD_RATE_LIMIT_PER_MINUTE: int = Field(
        default=20,
        ge=1,
        description="Document upload requests allowed per minute per authenticated user and IP",
    )

    # Seed script credential. Intentionally has no built-in default: the seed
    # script refuses to run outside APP_ENV=test unless this is supplied.
    SEED_DEFAULT_PASSWORD: str = Field(
        default="",
        description="Password hashed for the three synthetic demo users by scripts/seed_data.py",
    )

    # Retrieval Hyperparameters
    RETRIEVAL_TOP_K_HYBRID: int = Field(
        default=20,
        description="Number of candidate passages from BM25 + Vector before re-ranking",
    )
    RETRIEVAL_RRF_K: int = Field(
        default=60,
        description="Reciprocal Rank Fusion smoothing constant k",
    )
    RERANKER_TOP_N: int = Field(
        default=5,
        description="Number of passages passed to generation after Cross-Encoder scoring",
    )
    GRADER_RELEVANCE_THRESHOLD: float = Field(
        default=0.65,
        description="Minimum average score for retrieved chunks before triggering rewrite/refusal",
    )

    @property
    def rbac_enabled(self) -> bool:
        """Return whether server-side role filtering is active.

        Disabling RBAC is refused unless this is the test environment or the
        run is explicitly labelled as a baseline ablation, so a typo in ``.env``
        can never silently expose restricted documents.

        Raises:
            RuntimeError: if RBAC is disabled without a permitted label.
        """
        if not self.ENABLE_RBAC:
            permitted = self.APP_ENV == "test" or self.BASELINE_ABLATION
            if not permitted:
                raise RuntimeError(
                    "ENABLE_RBAC=false is only permitted when APP_ENV=test or "
                    "BASELINE_ABLATION=true (labelled baseline experiment)."
                )
        return self.ENABLE_RBAC

    def validate_security_flags(self) -> None:
        """Fail fast at startup when security flags are unsafe.

        Raises:
            RuntimeError: if RBAC is disabled without a permitted label.
        """
        _ = self.rbac_enabled

    @property
    def llm(self) -> ResolvedLLM:
        """Resolve the active profile into concrete provider settings.

        Returns a :class:`ResolvedLLM` with the endpoint, key and model for the
        selected ``LLM_PROFILE``.

        Raises:
            RuntimeError: if ``APP_ENV=test`` and a live profile is selected.
            ValueError: if the selected live profile has no API key configured.
        """
        profile = self.LLM_PROFILE
        if self.APP_ENV == "test" and profile != "mock":
            raise RuntimeError(
                "LLM_PROFILE must be 'mock' when APP_ENV=test; "
                "live profiles are forbidden in automated tests."
            )

        if profile == "mock":
            return ResolvedLLM(
                profile="mock",
                model="mock",
                temperature=self.LLM_TEMPERATURE,
                timeout_seconds=self.LLM_TIMEOUT_SECONDS,
                max_retries=self.LLM_MAX_RETRIES,
                max_rpm=self.LLM_MAX_RPM,
                is_mock=True,
            )

        if profile == "dev":
            base_url = self.LLM_BASE_URL
            api_key = self.LLM_API_KEY
            model = self.LLM_MODEL
            key_name = "LLM_API_KEY"
        else:
            base_url = self.DEMO_LLM_BASE_URL
            api_key = self.DEMO_LLM_API_KEY
            model = self.DEMO_LLM_MODEL
            key_name = "DEMO_LLM_API_KEY"

        if not api_key:
            raise ValueError(
                f"LLM profile '{profile}' requires {key_name}; "
                "configure it in .env or switch LLM_PROFILE."
            )

        return ResolvedLLM(
            profile=profile,
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=self.LLM_TEMPERATURE,
            timeout_seconds=self.LLM_TIMEOUT_SECONDS,
            max_retries=self.LLM_MAX_RETRIES,
            max_rpm=self.LLM_MAX_RPM,
        )

    def ensure_llm_ready(self) -> ResolvedLLM:
        """Fail fast at startup if the active LLM profile cannot be used."""
        return self.llm

    @property
    def cors_origins_list(self) -> list[str]:
        """Return CORS origins as a trimmed list."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    def ensure_directories(self) -> None:
        """Create necessary storage directories on startup."""
        Path(self.DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
        Path(self.QDRANT_STORAGE_PATH).mkdir(parents=True, exist_ok=True)


# Global singleton instance
settings = Settings()
