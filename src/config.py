"""Application configuration management using Pydantic Settings."""

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
        default="http://localhost:8501,http://127.0.0.1:8501",
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

    # dev profile (free-tier OpenAI-compatible provider)
    LLM_BASE_URL: str = Field(
        default="https://api.groq.com/openai/v1",
        description="Base URL for the free-tier provider used by the dev profile",
    )
    LLM_API_KEY: str = Field(
        default="",
        description="API key for the free-tier provider used by the dev profile",
    )
    LLM_MODEL: str = Field(
        default="llama-3.1-8b-instant",
        description="Model identifier for the dev profile",
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

    # Spend guard (per run; evaluation applies one budget per benchmark run)
    LLM_MAX_CALLS_PER_RUN: int = Field(
        default=40,
        description="Hard cap on LLM calls per run before stopping",
    )
    LLM_MAX_TOKENS_PER_RUN: int = Field(
        default=120_000,
        description="Hard cap on prompt + completion tokens per run before stopping",
    )

    # Fallback Cloud LLM Provider
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

    # Storage & Cache Directories
    DATABASE_PATH: str = Field(
        default="./data/sqlite/app.db",
        description="Path to SQLite database file",
    )
    QDRANT_STORAGE_PATH: str = Field(
        default="./data/qdrant",
        description="Directory for local embedded Qdrant vector storage",
    )
    CACHE_DIR: str = Field(
        default="./data/cache",
        description="Directory for on-disk response memoization cache",
    )

    # Ablation Experiment Flags
    ENABLE_ADAPTIVE_ROUTER: bool = Field(
        default=True,
        description="Layer 1: Adaptive Router (direct reply, single search, split)",
    )
    ENABLE_CORRECTIVE_GRADER: bool = Field(
        default=True,
        description="Layer 2: Corrective Grader (passage check, retry rewrite, refusal)",
    )
    ENABLE_RBAC_MEMORY: bool = Field(
        default=True,
        description="Layer 3: Session Memory and Server-side RBAC retrieval filtering",
    )
    ENABLE_XAI_OUTPUT: bool = Field(
        default=True,
        description="Layer 4: Clause-level citations, reasoning trace, audit log",
    )

    # Retrieval Hyperparameters
    RETRIEVAL_TOP_K_HYBRID: int = Field(
        default=20,
        description="Number of candidate passages from BM25 + Vector before re-ranking",
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
    def llm(self) -> ResolvedLLM:
        """Resolve the active profile into concrete provider settings.

        Returns a :class:`ResolvedLLM` with the endpoint, key and model for the
        selected ``LLM_PROFILE``.

        Raises:
            RuntimeError: if a live profile is resolved while pytest is running.
            ValueError: if the selected live profile has no API key configured.
        """
        profile = self.LLM_PROFILE
        if profile != "mock" and os.environ.get("PYTEST_CURRENT_TEST"):
            raise RuntimeError(
                "Live LLM profiles are forbidden in automated tests; "
                "set LLM_PROFILE=mock in tests/conftest.py."
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
        Path(self.CACHE_DIR).mkdir(parents=True, exist_ok=True)


# Global singleton instance
settings = Settings()
