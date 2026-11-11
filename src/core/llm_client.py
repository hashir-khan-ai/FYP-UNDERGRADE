"""Resilient, profile-driven LLM gateway with caching, retries, and spend guard.

Every live model call in the application must go through this module. It resolves
the active ``mock``/``dev``/``demo`` profile from :mod:`src.config`, applies a
request rate limiter, retries only safe failures, serves deterministic responses
from SQLite when possible, and records one telemetry row per call.

Credentials and full prompts are never written to logs.
"""

import collections
import hashlib
import json
import logging
import random
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from src.config import settings
from src.core.spend_guard import SpendGuardExceededError, spend_guard
from src.db.connection import get_db_connection
from src.db.migrations import SCHEMA_DDL, apply_migrations
from src.db.repository import Repository

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

_SAFE_RETRY_STATUSES = {429, 500, 502, 503, 504}
_SCHEMA_READY = False


class LLMClientError(RuntimeError):
    """Base class for sanitized LLM gateway failures."""


class LLMUnavailableError(LLMClientError):
    """Raised when the provider is offline or exhausted safe retries."""


class LLMAuthError(LLMClientError):
    """Raised when provider credentials are rejected; never retried."""


class LLMResponse(BaseModel):
    """Normalized response envelope from the LLM client."""

    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached: bool = False
    latency_ms: float = 0.0
    model: str = ""
    profile: str = ""


def parse_json_response(raw_text: str, schema: type[T]) -> T | None:
    """Extract a JSON object from model text and validate it with Pydantic.

    Returns ``None`` when the text is not valid JSON or does not conform to the
    schema. Callers decide whether to repair, fall back, or raise.
    """
    cleaned = raw_text.strip()
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if json_match:
        cleaned = json_match.group(1)
    elif "{" in cleaned and "}" in cleaned:
        cleaned = cleaned[cleaned.find("{") : cleaned.rfind("}") + 1]

    try:
        return schema.model_validate_json(cleaned)
    except Exception:
        return None


class RateLimiter:
    """In-memory sliding-window rate limiter enforcing max requests per minute."""

    def __init__(self, max_rpm: int = 20) -> None:
        self.max_rpm = max_rpm
        self.timestamps: collections.deque[float] = collections.deque()

    def acquire(self) -> None:
        """Block until a request slot is available, then reserve it."""
        if self.max_rpm <= 0:
            return
        now = time.time()
        while self.timestamps and now - self.timestamps[0] > 60.0:
            self.timestamps.popleft()

        if len(self.timestamps) >= self.max_rpm:
            sleep_needed = 60.0 - (now - self.timestamps[0]) + 0.1
            if sleep_needed > 0:
                logger.info(
                    "Rate limit reached (%s RPM); throttling for %.2fs.",
                    self.max_rpm,
                    sleep_needed,
                )
                time.sleep(sleep_needed)
                now = time.time()
                while self.timestamps and now - self.timestamps[0] > 60.0:
                    self.timestamps.popleft()

        self.timestamps.append(time.time())


def _ensure_schema() -> None:
    """Create/upgrade the SQLite schema once per process, before cache writes."""
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    try:
        with get_db_connection() as conn:
            conn.executescript(SCHEMA_DDL)
            apply_migrations(conn)
        _SCHEMA_READY = True
    except Exception as exc:  # pragma: no cover - defensive path
        logger.warning("Could not initialise LLM telemetry schema: %s", type(exc).__name__)


class ResilientLLMClient:
    """Profile-driven LLM gateway with cache, retries, telemetry and spend caps.

    Args:
        transport: Optional ``httpx`` transport, used by tests to simulate
            provider responses without network access.
    """

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self.rate_limiter = RateLimiter(max_rpm=settings.LLM_MAX_RPM)
        self.transport = transport

    def _compute_cache_key(
        self,
        profile: str,
        model: str,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        max_tokens: int,
        step: str,
    ) -> str:
        """Return the deterministic SHA-256 cache key for one request."""
        key_raw = (
            f"{profile}:{model}:{settings.PROMPT_VERSION}:{step}:"
            f"{system_prompt or ''}:{prompt}:{temperature:.2f}:{max_tokens}"
        )
        return hashlib.sha256(key_raw.encode("utf-8")).hexdigest()

    def _cache_row_is_fresh(self, created_at: Any) -> bool:
        """Honour the configured cache TTL, tolerating older timestamp formats."""
        ttl_days = settings.LLM_CACHE_TTL_DAYS
        if ttl_days <= 0 or not created_at:
            return True
        try:
            created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) - created <= timedelta(days=ttl_days)
        except ValueError:
            return True

    def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int = 1024,
        force_cache_refresh: bool = False,
        step: str = "answer",
        audit_id: int | None = None,
        session_id: str | None = None,
    ) -> LLMResponse:
        """Execute one completion through the active profile.

        Cache hits cost no quota and no spend-guard budget. Live calls are rate
        limited, retried only on 429/5xx/timeouts, and logged to ``llm_calls``.
        """
        _ensure_schema()
        resolved = settings.llm
        profile = resolved.profile
        model = resolved.model
        temp = temperature if temperature is not None else resolved.temperature

        cache_key = self._compute_cache_key(
            profile, model, prompt, system_prompt, temp, max_tokens, step
        )
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()

        if settings.LLM_CACHE_ENABLED and not force_cache_refresh:
            cached = self._read_cache(cache_key)
            if cached is not None:
                self._log_call(
                    profile=profile,
                    model=model,
                    prompt_tokens=cached["prompt_tokens"],
                    completion_tokens=cached["completion_tokens"],
                    latency_ms=0.0,
                    cache_hit=True,
                    step=step,
                    audit_id=audit_id,
                    session_id=session_id,
                )
                return LLMResponse(
                    content=cached["response_text"],
                    prompt_tokens=cached["prompt_tokens"],
                    completion_tokens=cached["completion_tokens"],
                    total_tokens=cached["prompt_tokens"] + cached["completion_tokens"],
                    cached=True,
                    latency_ms=0.0,
                    model=model,
                    profile=profile,
                )

        spend_guard.check_call_allowed()

        if profile == "mock" or resolved.is_mock:
            content = self._generate_mock_response(prompt)
            prompt_toks = max(len(prompt.split()), 1)
            completion_toks = max(len(content.split()), 1)
            spend_guard.record_usage(prompt_toks, completion_toks)
            self._write_cache(cache_key, prompt_hash, model, content, prompt_toks, completion_toks)
            self._log_call(
                profile=profile,
                model=model,
                prompt_tokens=prompt_toks,
                completion_tokens=completion_toks,
                latency_ms=1.0,
                cache_hit=False,
                step=step,
                audit_id=audit_id,
                session_id=session_id,
            )
            return LLMResponse(
                content=content,
                prompt_tokens=prompt_toks,
                completion_tokens=completion_toks,
                total_tokens=prompt_toks + completion_toks,
                cached=False,
                latency_ms=1.0,
                model=model,
                profile=profile,
            )

        self.rate_limiter.acquire()
        start_time = time.perf_counter()
        try:
            content, prompt_toks, completion_toks = self._execute_with_retry(
                resolved_llm=resolved,
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temp,
                max_tokens=max_tokens,
            )
        except LLMClientError as exc:
            self._log_call(
                profile=profile,
                model=model,
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=(time.perf_counter() - start_time) * 1000.0,
                cache_hit=False,
                step=step,
                call_status="error",
                error_message=str(exc)[:300],
                audit_id=audit_id,
                session_id=session_id,
            )
            raise

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        spend_guard.record_usage(prompt_toks, completion_toks)
        self._write_cache(cache_key, prompt_hash, model, content, prompt_toks, completion_toks)
        self._log_call(
            profile=profile,
            model=model,
            prompt_tokens=prompt_toks,
            completion_tokens=completion_toks,
            latency_ms=latency_ms,
            cache_hit=False,
            step=step,
            audit_id=audit_id,
            session_id=session_id,
        )
        return LLMResponse(
            content=content,
            prompt_tokens=prompt_toks,
            completion_tokens=completion_toks,
            total_tokens=prompt_toks + completion_toks,
            cached=False,
            latency_ms=latency_ms,
            model=model,
            profile=profile,
        )

    def _read_cache(self, cache_key: str) -> dict[str, Any] | None:
        """Read a fresh cache row, returning None on miss, expiry, or DB error."""
        try:
            with get_db_connection() as conn:
                row = Repository(conn).get_cached_llm(cache_key)
                if row is None:
                    return None
                if not self._cache_row_is_fresh(row["created_at"]):
                    return None
                return {
                    "response_text": row["response_text"],
                    "prompt_tokens": int(row["prompt_tokens"] or 0),
                    "completion_tokens": int(row["completion_tokens"] or 0),
                }
        except Exception as exc:
            logger.warning("LLM cache read failed (%s); continuing without cache.", type(exc).__name__)
            return None

    def _write_cache(
        self,
        cache_key: str,
        prompt_hash: str,
        model: str,
        content: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        if not settings.LLM_CACHE_ENABLED:
            return
        try:
            with get_db_connection() as conn:
                Repository(conn).set_cached_llm(
                    cache_key=cache_key,
                    prompt_hash=prompt_hash,
                    model_name=model,
                    response_text=content,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
        except Exception as exc:
            logger.warning("LLM cache write failed (%s); response was still returned.", type(exc).__name__)

    def _log_call(
        self,
        profile: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        cache_hit: bool,
        step: str,
        call_status: str = "success",
        error_message: str | None = None,
        audit_id: int | None = None,
        session_id: str | None = None,
    ) -> None:
        try:
            with get_db_connection() as conn:
                Repository(conn).log_llm_call(
                    profile=profile,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    latency_ms=latency_ms,
                    cache_hit=cache_hit,
                    call_status=call_status,
                    error_message=error_message,
                    step=step,
                    prompt_version=settings.PROMPT_VERSION,
                    audit_id=audit_id,
                    session_id=session_id,
                )
        except Exception as exc:
            logger.warning("LLM telemetry write failed (%s).", type(exc).__name__)

    def _execute_with_retry(
        self,
        resolved_llm: Any,
        prompt: str,
        system_prompt: str | None,
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, int, int]:
        """Call an OpenAI-compatible provider, retrying only safe failures."""
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        providers: list[dict[str, str]] = [
            {
                "base_url": (resolved_llm.base_url or "").rstrip("/"),
                "api_key": resolved_llm.api_key or "",
                "model": resolved_llm.model,
                "label": "primary",
            }
        ]
        # Fallback is dev-only so demo/evaluation runs stay reproducible.
        if (
            resolved_llm.profile == "dev"
            and settings.FALLBACK_LLM_BASE_URL
            and settings.FALLBACK_LLM_API_KEY
            and settings.FALLBACK_LLM_MODEL
        ):
            providers.append(
                {
                    "base_url": settings.FALLBACK_LLM_BASE_URL.rstrip("/"),
                    "api_key": settings.FALLBACK_LLM_API_KEY,
                    "model": settings.FALLBACK_LLM_MODEL,
                    "label": "fallback",
                }
            )

        last_failure = "no request attempted"
        for provider in providers:
            headers = {
                "Authorization": f"Bearer {provider['api_key']}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": provider["model"],
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

            for attempt in range(resolved_llm.max_retries + 1):
                try:
                    with httpx.Client(
                        timeout=resolved_llm.timeout_seconds,
                        transport=self.transport,
                    ) as client:
                        resp = client.post(
                            f"{provider['base_url']}/chat/completions",
                            headers=headers,
                            json=payload,
                        )
                except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
                    last_failure = type(exc).__name__
                    logger.warning(
                        "LLM %s provider network failure (%s), attempt %s/%s.",
                        provider["label"],
                        last_failure,
                        attempt + 1,
                        resolved_llm.max_retries + 1,
                    )
                    self._sleep_before_retry(attempt, resolved_llm.max_retries)
                    continue

                if resp.status_code == 200:
                    return self._parse_completion(resp)

                if resp.status_code in (401, 403):
                    raise LLMAuthError(
                        "The LLM provider rejected the configured credentials."
                    )

                if resp.status_code in _SAFE_RETRY_STATUSES:
                    last_failure = f"HTTP {resp.status_code}"
                    logger.warning(
                        "LLM %s provider returned HTTP %s, attempt %s/%s.",
                        provider["label"],
                        resp.status_code,
                        attempt + 1,
                        resolved_llm.max_retries + 1,
                    )
                    self._sleep_before_retry(attempt, resolved_llm.max_retries)
                    continue

                raise LLMUnavailableError(
                    f"The LLM provider returned HTTP {resp.status_code}."
                )

        raise LLMUnavailableError(
            f"The LLM provider is unavailable after retries ({last_failure})."
        )

    def _sleep_before_retry(self, attempt: int, max_retries: int) -> None:
        if attempt >= max_retries:
            return
        backoff = settings.LLM_RETRY_BASE_SECONDS * (2**attempt) + random.uniform(0.1, 0.5)
        time.sleep(backoff)

    def _parse_completion(self, resp: httpx.Response) -> tuple[str, int, int]:
        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            if content is None:
                raise KeyError("content")
            usage = data.get("usage", {})
            prompt_toks = int(usage.get("prompt_tokens") or max(len(str(data).split()), 1))
            completion_toks = int(
                usage.get("completion_tokens") or max(len(str(content).split()), 1)
            )
            return str(content), prompt_toks, completion_toks
        except Exception as exc:
            raise LLMUnavailableError(
                "The LLM provider returned a malformed completion payload."
            ) from exc

    def complete_json(
        self,
        prompt: str,
        schema: type[T],
        fallback: T | None = None,
        system_prompt: str | None = None,
        step: str = "answer",
    ) -> T:
        """Request schema-validated JSON with exactly one repair retry.

        On a second validation failure the caller-supplied fallback is returned.
        If no fallback exists, :class:`LLMClientError` is raised.
        """
        schema_json = json.dumps(schema.model_json_schema(), indent=2)
        instruction = (
            "\n\nOUTPUT INSTRUCTION: Respond ONLY with a valid JSON object matching "
            f"this schema:\n```json\n{schema_json}\n```\n"
            "Do not include explanation or text outside the JSON object."
        )
        full_prompt = prompt + instruction

        first = self.complete(
            prompt=full_prompt,
            system_prompt=system_prompt,
            temperature=0.0,
            step=step,
        )
        parsed = parse_json_response(first.content, schema)
        if parsed is not None:
            return parsed

        logger.warning("LLM output failed schema %s; one repair retry will run.", schema.__name__)
        repair_prompt = (
            f"Your previous response was invalid for the requested JSON schema.\n"
            f"Original request:\n{prompt}\n\n"
            f"Previous response:\n{first.content[:800]}\n\n"
            f"Return ONLY a valid JSON object matching:\n{schema_json}"
        )
        repaired = self.complete(
            prompt=repair_prompt,
            system_prompt=system_prompt,
            temperature=0.0,
            step=step,
        )
        parsed_repair = parse_json_response(repaired.content, schema)
        if parsed_repair is not None:
            return parsed_repair

        if fallback is not None:
            logger.warning(
                "LLM repair failed for %s; using caller fallback.",
                schema.__name__,
            )
            return fallback
        raise LLMClientError(
            f"Could not obtain valid {schema.__name__} JSON after one repair retry."
        )

    def _generate_mock_response(self, prompt: str) -> str:
        """Return a deterministic offline response, citing real prompt chunk IDs."""
        lowered = prompt.lower()
        chunk_ids = re.findall(r"\[Chunk ID:\s*([^\]]+)\]", prompt)

        if "authoritative_passages" in lowered or "supporting chunks:" in lowered:
            cited = ", ".join(chunk_ids[:5]) if chunk_ids else "NONE"
            return (
                "The supplied authoritative passages set out the applicable "
                "regulatory requirement and expected control.\n"
                f"Supporting Chunks: {cited}"
            )
        if "route" in lowered or "router" in lowered:
            return '{"route": "SINGLE_SEARCH", "reasoning": "Standard regulatory query"}'
        if "relevance" in lowered or "grader" in lowered:
            return '{"is_relevant": true, "relevance_score": 0.95, "reasoning": "Passage directly answers query"}'
        return "Mock regulatory compliance response strictly generated offline."


# Global client instance. Tests may construct their own client with a fake transport.
llm_client = ResilientLLMClient()


__all__ = [
    "LLMClientError",
    "LLMAuthError",
    "LLMUnavailableError",
    "LLMResponse",
    "RateLimiter",
    "ResilientLLMClient",
    "SpendGuardExceededError",
    "llm_client",
    "parse_json_response",
]
