"""Profile-aware, run-scoped spend guard protecting paid external LLM API quotas."""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Literal

from src.config import settings

logger = logging.getLogger(__name__)

DEFAULT_RUN_ID = "default"
MAX_TRACKED_RUNS = 512

_ACTIVE_RUN_ID: ContextVar[str] = ContextVar("spend_guard_run_id", default=DEFAULT_RUN_ID)
_ACTIVE_PROFILE_CTX: ContextVar[tuple[str, bool, bool] | None] = ContextVar(
    "spend_guard_profile_ctx",
    default=None,
)


class SpendGuardExceededError(RuntimeError):
    """Base exception raised when an LLM run exceeds its configured guard limit."""

    cap_kind: str = "calls"
    scope: Literal["paid", "local"] = "paid"
    error_code: str = "LLM_SPEND_LIMIT"
    http_status: int = 429

    def __init__(
        self,
        message: str,
        *,
        user_message: str | None = None,
        internal_detail: str = "",
        cap_kind: str | None = None,
        scope: Literal["paid", "local"] | None = None,
        error_code: str | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.user_message = user_message or message
        self.internal_detail = internal_detail or message
        if cap_kind is not None:
            self.cap_kind = cap_kind
        if scope is not None:
            self.scope = scope
        if error_code is not None:
            self.error_code = error_code
        if http_status is not None:
            self.http_status = http_status


class CallCapExceededError(SpendGuardExceededError):
    """Raised when a paid-quota run reaches its maximum allowed LLM calls."""

    cap_kind = "calls"
    scope = "paid"
    error_code = "LLM_SPEND_LIMIT"
    http_status = 429


class TokenCapExceededError(SpendGuardExceededError):
    """Raised when a paid-quota run reaches its maximum allowed LLM tokens."""

    cap_kind = "tokens"
    scope = "paid"
    error_code = "LLM_SPEND_LIMIT"
    http_status = 429


class LocalSafetyLimitError(SpendGuardExceededError):
    """Raised when a local self-hosted dev model exceeds the runaway loop ceiling."""

    cap_kind = "local_safety"
    scope = "local"
    error_code = "LOCAL_SAFETY_LIMIT"
    http_status = 503


@dataclass(slots=True)
class SpendGuardStatus:
    """Sanitized, JSON-safe snapshot of a single run's LLM usage and budget state."""

    calls: int
    tokens: int
    calls_limit: int
    tokens_limit: int
    calls_remaining: int
    tokens_remaining: int
    paid_calls: int
    paid_tokens: int
    offline_calls: int
    offline_tokens: int
    local_calls: int
    local_tokens: int
    limits: dict[str, int]
    exhausted: bool
    scope: Literal["offline", "local", "paid"]
    profile: str
    is_paid: bool
    run_id: str | None = None
    last_latency_ms: float | None = None
    cached_calls: int = 0
    saved_tokens: int = 0
    session_calls: int = 0
    session_tokens: int = 0
    session_calls_limit: int = 0
    session_tokens_limit: int = 0
    tokens_estimated: bool = False

    def to_dict(self) -> dict[str, object]:
        """Return dictionary representation suitable for API telemetry responses."""
        return {
            "calls": self.calls,
            "tokens": self.tokens,
            "calls_limit": self.calls_limit,
            "tokens_limit": self.tokens_limit,
            "calls_remaining": self.calls_remaining,
            "tokens_remaining": self.tokens_remaining,
            "paid_calls": self.paid_calls,
            "paid_tokens": self.paid_tokens,
            "offline_calls": self.offline_calls,
            "offline_tokens": self.offline_tokens,
            "local_calls": self.local_calls,
            "local_tokens": self.local_tokens,
            "cached_calls": self.cached_calls,
            "saved_tokens": self.saved_tokens,
            "session_calls": self.session_calls,
            "session_tokens": self.session_tokens,
            "session_calls_limit": self.session_calls_limit,
            "session_tokens_limit": self.session_tokens_limit,
            "tokens_estimated": self.tokens_estimated,
            "limits": dict(self.limits),
            "exhausted": self.exhausted,
            "scope": self.scope,
            "profile": self.profile,
            "is_paid": self.is_paid,
            "run_id": self.run_id,
            "last_latency_ms": self.last_latency_ms,
        }


@dataclass(slots=True)
class _RunUsage:
    """Isolated usage state for a single logical run or user session."""

    paid_calls: int = 0
    paid_tokens: int = 0
    query_paid_calls: int = 0
    query_paid_tokens: int = 0
    offline_calls: int = 0
    offline_tokens: int = 0
    local_calls: int = 0
    local_tokens: int = 0
    cached_calls: int = 0
    saved_tokens: int = 0
    paid_exhausted: bool = False
    query_paid_exhausted: bool = False
    local_safety_tripped: bool = False
    last_profile: str = "mock"
    last_has_paid_quota: bool = False
    last_is_local: bool = True
    last_latency_ms: float | None = None
    reserved_paid: int = field(default=0, repr=False)
    reserved_local: int = field(default=0, repr=False)


class SpendGuard:
    """Thread-safe, profile-aware LLM spend & runaway-loop guard scoped per query + session."""

    def __init__(
        self,
        max_calls: int | None = None,
        max_tokens: int | None = None,
        safety_max_calls: int | None = None,
        safety_max_tokens: int | None = None,
        session_max_calls: int | None = None,
        session_max_tokens: int | None = None,
    ) -> None:
        self.max_calls = max_calls if max_calls is not None else settings.LLM_MAX_CALLS_PER_RUN
        self.max_tokens = max_tokens if max_tokens is not None else settings.LLM_MAX_TOKENS_PER_RUN
        default_session_calls = getattr(settings, "LLM_MAX_CALLS_PER_SESSION", 150)
        default_session_tokens = getattr(settings, "LLM_MAX_TOKENS_PER_SESSION", 400_000)
        self.session_max_calls = (
            session_max_calls
            if session_max_calls is not None
            else max(self.max_calls, default_session_calls)
        )
        self.session_max_tokens = (
            session_max_tokens
            if session_max_tokens is not None
            else max(self.max_tokens, default_session_tokens)
        )
        self.safety_max_calls = (
            safety_max_calls
            if safety_max_calls is not None
            else getattr(settings, "LLM_LOCAL_SAFETY_CALLS", 1000)
        )
        self.safety_max_tokens = (
            safety_max_tokens
            if safety_max_tokens is not None
            else getattr(settings, "LLM_LOCAL_SAFETY_TOKENS", 4_000_000)
        )
        self._lock = threading.Lock()
        self._runs: OrderedDict[str, _RunUsage] = OrderedDict()

    @staticmethod
    def current_run_id(run_id: str | None = None) -> str:
        """Resolve explicit or active ContextVar run identifier."""
        return run_id or _ACTIVE_RUN_ID.get()

    def enter_scope(
        self,
        run_id: str,
        *,
        profile: str | None = None,
        has_paid_quota: bool | None = None,
        is_local: bool | None = None,
    ) -> tuple[object, object]:
        """Bind an isolated run scope to ContextVars and return reset tokens."""
        resolved_profile, resolved_paid, resolved_local = self._resolve_mode(
            profile=profile,
            has_paid_quota=has_paid_quota,
            is_local=is_local,
        )
        with self._lock:
            state = self._get_or_create_run(run_id)
            state.last_profile = resolved_profile
            state.last_has_paid_quota = resolved_paid
            state.last_is_local = resolved_local

        token_run = _ACTIVE_RUN_ID.set(run_id)
        token_prof = _ACTIVE_PROFILE_CTX.set((resolved_profile, resolved_paid, resolved_local))
        return token_run, token_prof

    @staticmethod
    def exit_scope(tokens: tuple[object, object]) -> None:
        """Restore ContextVars previously captured by ``enter_scope``."""
        token_run, token_prof = tokens
        _ACTIVE_PROFILE_CTX.reset(token_prof)  # type: ignore[arg-type]
        _ACTIVE_RUN_ID.reset(token_run)  # type: ignore[arg-type]

    @contextmanager
    def run_scope(
        self,
        run_id: str,
        *,
        profile: str | None = None,
        has_paid_quota: bool | None = None,
        is_local: bool | None = None,
    ) -> Iterator[str]:
        """Bind an isolated run scope to the active execution context without mid-turn resets."""
        tokens = self.enter_scope(
            run_id,
            profile=profile,
            has_paid_quota=has_paid_quota,
            is_local=is_local,
        )
        try:
            yield run_id
        finally:
            self.exit_scope(tokens)

    def record_latency(self, latency_ms: float, *, run_id: str | None = None) -> None:
        """Record latest turn latency on the active or specified run."""
        rid = self.current_run_id(run_id)
        with self._lock:
            state = self._get_or_create_run(rid)
            state.last_latency_ms = round(float(latency_ms), 2)

    def _get_or_create_run(self, run_id: str) -> _RunUsage:
        state = self._runs.get(run_id)
        if state is None:
            state = _RunUsage()
            self._runs[run_id] = state
            while len(self._runs) > MAX_TRACKED_RUNS:
                evicted_key, _ = self._runs.popitem(last=False)
                if evicted_key == DEFAULT_RUN_ID:
                    # Keep default slot available if evicted accidentally.
                    self._runs[evicted_key] = _RunUsage()
                    break
        else:
            self._runs.move_to_end(run_id)
        return state

    @staticmethod
    def _resolve_mode(
        *,
        profile: str | None = None,
        has_paid_quota: bool | None = None,
        is_local: bool | None = None,
    ) -> tuple[str, bool, bool]:
        if profile is not None or has_paid_quota is not None or is_local is not None:
            prof = (profile or ("mock" if is_local and not has_paid_quota else "demo")).lower()
            if prof == "mock":
                return "mock", False, True
            paid = True if has_paid_quota is None else bool(has_paid_quota)
            local = False if is_local is None else bool(is_local)
            if local and has_paid_quota is None:
                paid = False
            return prof, paid, local

        ctx_prof = _ACTIVE_PROFILE_CTX.get()
        if ctx_prof is not None:
            return ctx_prof

        return "demo", True, False

    @staticmethod
    def _scope_for(profile: str, has_paid_quota: bool, is_local: bool) -> Literal["offline", "local", "paid"]:
        if profile == "mock":
            return "offline"
        if not has_paid_quota or is_local:
            return "local"
        return "paid"

    def begin_query(self, run_id: str | None = None) -> None:
        """Reset per-query live quota counters at the start of a new user query.

        Cumulative per-session counters (`paid_calls`, `paid_tokens`) remain untouched so
        both per-query runaway protection and per-session ceilings apply independently.
        """
        rid = self.current_run_id(run_id)
        with self._lock:
            state = self._get_or_create_run(rid)
            state.query_paid_calls = 0
            state.query_paid_tokens = 0
            state.query_paid_exhausted = False
            state.reserved_paid = 0

    def _raise_paid_call_cap(self, state: _RunUsage, *, is_session: bool = False) -> None:
        if is_session:
            state.paid_exhausted = True
            detail = (
                f"Paid session call limit reached ({state.paid_calls}/{self.session_max_calls}); "
                "reset budget or start a new session."
            )
            msg = "This session reached its LLM budget. Click Reset budget to continue."
        else:
            state.query_paid_exhausted = True
            detail = (
                f"Paid per-query call limit reached ({state.query_paid_calls}/{self.max_calls}); "
                "configure LLM_MAX_CALLS_PER_RUN or simplify the query."
            )
            msg = "This query reached its step limit. Try a simpler question or click Reset budget."
        logger.warning(detail)
        raise CallCapExceededError(
            f"Spend guard cap exceeded: {msg}",
            user_message=msg,
            internal_detail=detail,
        )

    def _raise_paid_token_cap(
        self,
        state: _RunUsage,
        prospective_tokens: int | None = None,
        *,
        is_session: bool = False,
    ) -> None:
        if is_session:
            state.paid_exhausted = True
            observed = prospective_tokens if prospective_tokens is not None else state.paid_tokens
            detail = (
                f"Paid session token limit reached ({observed}/{self.session_max_tokens}); "
                "reset budget or start a new session."
            )
            msg = "This session reached its LLM token budget. Click Reset budget to continue."
        else:
            state.query_paid_exhausted = True
            observed = prospective_tokens if prospective_tokens is not None else state.query_paid_tokens
            detail = (
                f"Paid per-query token limit reached ({observed}/{self.max_tokens}); "
                "configure LLM_MAX_TOKENS_PER_RUN or simplify the query."
            )
            msg = "This query reached its token limit. Try a simpler question or click Reset budget."
        logger.warning(detail)
        raise TokenCapExceededError(
            f"Spend guard token cap exceeded: {msg}",
            user_message=msg,
            internal_detail=detail,
        )

    def _raise_local_safety_cap(self, kind: str, used: int, limit: int) -> None:
        detail = (
            f"Local dev runaway safety {kind} ceiling reached ({used}/{limit}); "
            "configure LLM_LOCAL_SAFETY_* if legitimately needed."
        )
        logger.warning(detail)
        raise LocalSafetyLimitError(
            "This local run reached its loop safety limit. Start a new session to continue.",
            user_message="This local run reached its loop safety limit. Start a new session to continue.",
            internal_detail=detail,
        )

    def check_call_allowed(
        self,
        *,
        profile: str | None = None,
        has_paid_quota: bool | None = None,
        is_local: bool | None = None,
        run_id: str | None = None,
    ) -> None:
        """Verify that another LLM API call is permitted under the active profile and run."""
        prof, paid, local = self._resolve_mode(
            profile=profile,
            has_paid_quota=has_paid_quota,
            is_local=is_local,
        )
        if prof == "mock":
            return

        rid = self.current_run_id(run_id)
        with self._lock:
            state = self._get_or_create_run(rid)
            if not paid or local:
                if state.local_safety_tripped or state.local_calls >= self.safety_max_calls:
                    state.local_safety_tripped = True
                    self._raise_local_safety_cap("calls", state.local_calls, self.safety_max_calls)
                if state.local_tokens >= self.safety_max_tokens:
                    state.local_safety_tripped = True
                    self._raise_local_safety_cap("tokens", state.local_tokens, self.safety_max_tokens)
                return

            if state.paid_calls >= self.session_max_calls:
                self._raise_paid_call_cap(state, is_session=True)
            if state.paid_exhausted or state.paid_tokens >= self.session_max_tokens:
                self._raise_paid_token_cap(state, is_session=True)
            if state.query_paid_calls >= self.max_calls:
                self._raise_paid_call_cap(state, is_session=False)
            if state.query_paid_exhausted or state.query_paid_tokens >= self.max_tokens:
                self._raise_paid_token_cap(state, is_session=False)

    def reserve_call(
        self,
        *,
        profile: str | None = None,
        has_paid_quota: bool | None = None,
        is_local: bool | None = None,
        run_id: str | None = None,
    ) -> str:
        """Atomically verify quota and reserve one call slot before invoking a provider.

        Returns the active scope (``"offline"``, ``"local"``, or ``"paid"``).
        """
        prof, paid, local = self._resolve_mode(
            profile=profile,
            has_paid_quota=has_paid_quota,
            is_local=is_local,
        )
        rid = self.current_run_id(run_id)
        scope = self._scope_for(prof, paid, local)

        with self._lock:
            state = self._get_or_create_run(rid)
            state.last_profile = prof
            state.last_has_paid_quota = paid
            state.last_is_local = local

            if scope == "offline":
                state.offline_calls += 1
                return scope

            if scope == "local":
                if state.local_safety_tripped or state.local_calls >= self.safety_max_calls:
                    state.local_safety_tripped = True
                    self._raise_local_safety_cap("calls", state.local_calls, self.safety_max_calls)
                if state.local_tokens >= self.safety_max_tokens:
                    state.local_safety_tripped = True
                    self._raise_local_safety_cap("tokens", state.local_tokens, self.safety_max_tokens)
                state.local_calls += 1
                state.reserved_local += 1
                if state.local_calls >= self.safety_max_calls:
                    state.local_safety_tripped = True
                return scope

            # Paid quota path: atomic check-then-increment prevents concurrency overshoot.
            if state.paid_calls >= self.session_max_calls:
                self._raise_paid_call_cap(state, is_session=True)
            if state.paid_exhausted or state.paid_tokens >= self.session_max_tokens:
                self._raise_paid_token_cap(state, is_session=True)
            if state.query_paid_calls >= self.max_calls:
                self._raise_paid_call_cap(state, is_session=False)
            if state.query_paid_exhausted or state.query_paid_tokens >= self.max_tokens:
                self._raise_paid_token_cap(state, is_session=False)

            state.paid_calls += 1
            state.query_paid_calls += 1
            state.reserved_paid += 1
            if state.paid_calls >= self.session_max_calls:
                state.paid_exhausted = True
            if state.query_paid_calls >= self.max_calls:
                state.query_paid_exhausted = True
            return scope

    def release_call(
        self,
        *,
        profile: str | None = None,
        has_paid_quota: bool | None = None,
        is_local: bool | None = None,
        run_id: str | None = None,
    ) -> None:
        """Roll back an unbilled reserved call slot when an upstream call never completed."""
        prof, paid, local = self._resolve_mode(
            profile=profile,
            has_paid_quota=has_paid_quota,
            is_local=is_local,
        )
        rid = self.current_run_id(run_id)
        scope = self._scope_for(prof, paid, local)

        with self._lock:
            state = self._runs.get(rid)
            if state is None:
                return
            if scope == "offline":
                if state.offline_calls > 0:
                    state.offline_calls -= 1
                return
            if scope == "local":
                if state.reserved_local > 0 and state.local_calls > 0:
                    state.local_calls -= 1
                    state.reserved_local -= 1
                    state.local_safety_tripped = (
                        state.local_calls >= self.safety_max_calls
                        or state.local_tokens >= self.safety_max_tokens
                    )
                return
            if state.reserved_paid > 0 and state.paid_calls > 0:
                state.paid_calls -= 1
                if state.query_paid_calls > 0:
                    state.query_paid_calls -= 1
                state.reserved_paid -= 1
                state.paid_exhausted = (
                    state.paid_calls >= self.session_max_calls
                    or state.paid_tokens >= self.session_max_tokens
                )
                state.query_paid_exhausted = (
                    state.query_paid_calls >= self.max_calls
                    or state.query_paid_tokens >= self.max_tokens
                )

    def commit_usage(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        *,
        profile: str | None = None,
        has_paid_quota: bool | None = None,
        is_local: bool | None = None,
        run_id: str | None = None,
    ) -> None:
        """Commit token usage for a call slot previously acquired via ``reserve_call``."""
        call_tokens = max(int(prompt_tokens), 0) + max(int(completion_tokens), 0)
        prof, paid, local = self._resolve_mode(
            profile=profile,
            has_paid_quota=has_paid_quota,
            is_local=is_local,
        )
        rid = self.current_run_id(run_id)
        scope = self._scope_for(prof, paid, local)

        with self._lock:
            state = self._get_or_create_run(rid)
            state.last_profile = prof
            state.last_has_paid_quota = paid
            state.last_is_local = local

            if scope == "offline":
                state.offline_tokens += call_tokens
                return

            if scope == "local":
                if state.reserved_local > 0:
                    state.reserved_local -= 1
                else:
                    state.local_calls += 1
                state.local_tokens += call_tokens
                if state.local_calls >= self.safety_max_calls or state.local_tokens >= self.safety_max_tokens:
                    state.local_safety_tripped = True
                return

            if state.reserved_paid > 0:
                state.reserved_paid -= 1
            else:
                state.paid_calls += 1
                state.query_paid_calls += 1
            state.paid_tokens += call_tokens
            state.query_paid_tokens += call_tokens
            if state.paid_calls >= self.session_max_calls or state.paid_tokens >= self.session_max_tokens:
                state.paid_exhausted = True
            if state.query_paid_calls >= self.max_calls or state.query_paid_tokens >= self.max_tokens:
                state.query_paid_exhausted = True

    def record_usage(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        *,
        profile: str | None = None,
        has_paid_quota: bool | None = None,
        is_local: bool | None = None,
        run_id: str | None = None,
    ) -> None:
        """Atomically check budget and record one completed call and its token usage."""
        call_tokens = max(int(prompt_tokens), 0) + max(int(completion_tokens), 0)
        prof, paid, local = self._resolve_mode(
            profile=profile,
            has_paid_quota=has_paid_quota,
            is_local=is_local,
        )
        rid = self.current_run_id(run_id)
        scope = self._scope_for(prof, paid, local)

        with self._lock:
            state = self._get_or_create_run(rid)
            state.last_profile = prof
            state.last_has_paid_quota = paid
            state.last_is_local = local

            if scope == "offline":
                state.offline_calls += 1
                state.offline_tokens += call_tokens
                return

            if scope == "local":
                if state.local_safety_tripped or state.local_calls >= self.safety_max_calls:
                    state.local_safety_tripped = True
                    self._raise_local_safety_cap("calls", state.local_calls, self.safety_max_calls)
                prospective = state.local_tokens + call_tokens
                if prospective > self.safety_max_tokens:
                    state.local_safety_tripped = True
                    self._raise_local_safety_cap("tokens", prospective, self.safety_max_tokens)
                state.local_calls += 1
                state.local_tokens = prospective
                if state.local_calls >= self.safety_max_calls or state.local_tokens >= self.safety_max_tokens:
                    state.local_safety_tripped = True
                return

            # Paid quota path: enforce both cumulative session cap and per-query cap before mutation.
            if state.paid_calls >= self.session_max_calls:
                self._raise_paid_call_cap(state, is_session=True)
            prospective_session_tokens = state.paid_tokens + call_tokens
            if state.paid_exhausted or prospective_session_tokens > self.session_max_tokens:
                self._raise_paid_token_cap(state, prospective_tokens=prospective_session_tokens, is_session=True)

            if state.query_paid_calls >= self.max_calls:
                self._raise_paid_call_cap(state, is_session=False)
            prospective_query_tokens = state.query_paid_tokens + call_tokens
            if state.query_paid_exhausted or prospective_query_tokens > self.max_tokens:
                self._raise_paid_token_cap(state, prospective_tokens=prospective_query_tokens, is_session=False)

            state.paid_calls += 1
            state.paid_tokens = prospective_session_tokens
            state.query_paid_calls += 1
            state.query_paid_tokens = prospective_query_tokens
            if state.paid_calls >= self.session_max_calls or state.paid_tokens >= self.session_max_tokens:
                state.paid_exhausted = True
            if state.query_paid_calls >= self.max_calls or state.query_paid_tokens >= self.max_tokens:
                state.query_paid_exhausted = True

    def record_cache_hit(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        *,
        run_id: str | None = None,
    ) -> None:
        """Record one SQLite response-cache hit for per-run savings telemetry (costs 0 quota)."""
        saved = max(int(prompt_tokens), 0) + max(int(completion_tokens), 0)
        rid = self.current_run_id(run_id)
        with self._lock:
            state = self._get_or_create_run(rid)
            state.cached_calls += 1
            state.saved_tokens += saved

    def status(
        self,
        *,
        profile: str | None = None,
        has_paid_quota: bool | None = None,
        is_local: bool | None = None,
        run_id: str | None = None,
    ) -> SpendGuardStatus:
        """Build a clean per-run snapshot suitable for API responses and UI status drawers."""
        rid = self.current_run_id(run_id)
        with self._lock:
            state = self._runs.get(rid) or _RunUsage()
            if profile is not None or has_paid_quota is not None or is_local is not None:
                prof, paid, local = self._resolve_mode(
                    profile=profile,
                    has_paid_quota=has_paid_quota,
                    is_local=is_local,
                )
            elif state.offline_calls > 0 and state.paid_calls == 0 and state.local_calls == 0:
                prof, paid, local = "mock", False, True
            elif state.local_calls > 0 and state.paid_calls == 0:
                prof, paid, local = state.last_profile if state.last_profile != "mock" else "dev", False, True
            else:
                ctx_prof = _ACTIVE_PROFILE_CTX.get()
                if ctx_prof is not None:
                    prof, paid, local = ctx_prof
                else:
                    prof = state.last_profile if state.last_profile else "demo"
                    paid = state.last_has_paid_quota
                    local = state.last_is_local

            scope = self._scope_for(prof, paid, local)
            session_calls = 0
            session_tokens = 0
            session_calls_limit = 0
            session_tokens_limit = 0
            tokens_estimated = False
            if scope == "offline":
                active_calls = state.offline_calls
                active_tokens = state.offline_tokens
                calls_limit = 0
                tokens_limit = 0
                exhausted = False
                calls_remaining = 0
                tokens_remaining = 0
                tokens_estimated = True
            elif scope == "local":
                active_calls = state.local_calls
                active_tokens = state.local_tokens
                calls_limit = self.safety_max_calls
                tokens_limit = self.safety_max_tokens
                exhausted = bool(
                    state.local_safety_tripped
                    or state.local_calls >= self.safety_max_calls
                    or state.local_tokens >= self.safety_max_tokens
                )
                calls_remaining = max(calls_limit - active_calls, 0) if calls_limit > 0 else 0
                tokens_remaining = max(tokens_limit - active_tokens, 0) if tokens_limit > 0 else 0
            else:
                active_calls = state.query_paid_calls
                active_tokens = state.query_paid_tokens
                calls_limit = self.max_calls
                tokens_limit = self.max_tokens
                session_calls = state.paid_calls
                session_tokens = state.paid_tokens
                session_calls_limit = self.session_max_calls
                session_tokens_limit = self.session_max_tokens
                exhausted = bool(
                    state.paid_exhausted
                    or state.query_paid_exhausted
                    or state.query_paid_calls >= self.max_calls
                    or state.query_paid_tokens >= self.max_tokens
                    or state.paid_calls >= self.session_max_calls
                    or state.paid_tokens >= self.session_max_tokens
                )
                calls_remaining = max(calls_limit - active_calls, 0) if calls_limit > 0 else 0
                tokens_remaining = max(tokens_limit - active_tokens, 0) if tokens_limit > 0 else 0

            return SpendGuardStatus(
                calls=active_calls,
                tokens=active_tokens,
                calls_limit=calls_limit,
                tokens_limit=tokens_limit,
                calls_remaining=calls_remaining,
                tokens_remaining=tokens_remaining,
                paid_calls=state.paid_calls,
                paid_tokens=state.paid_tokens,
                offline_calls=state.offline_calls,
                offline_tokens=state.offline_tokens,
                local_calls=state.local_calls,
                local_tokens=state.local_tokens,
                limits={"calls": calls_limit, "tokens": tokens_limit},
                exhausted=exhausted,
                scope=scope,
                profile=prof,
                is_paid=(scope == "paid"),
                run_id=rid,
                last_latency_ms=state.last_latency_ms,
                cached_calls=state.cached_calls,
                saved_tokens=state.saved_tokens,
                session_calls=session_calls,
                session_tokens=session_tokens,
                session_calls_limit=session_calls_limit,
                session_tokens_limit=session_tokens_limit,
                tokens_estimated=tokens_estimated,
            )

    @property
    def exhausted(self) -> bool:
        """Return True when the active run's budget is exhausted (always False for offline mock)."""
        rid = self.current_run_id()
        with self._lock:
            state = self._runs.get(rid)
            if state is None:
                return False
            ctx_prof = _ACTIVE_PROFILE_CTX.get()
            if ctx_prof is not None:
                prof, paid, local = ctx_prof
                if prof == "mock":
                    return False
                if not paid or local:
                    return bool(
                        state.local_safety_tripped
                        or state.local_calls >= self.safety_max_calls
                        or state.local_tokens >= self.safety_max_tokens
                    )
                return bool(
                    state.paid_exhausted
                    or state.query_paid_exhausted
                    or state.query_paid_calls >= self.max_calls
                    or state.query_paid_tokens >= self.max_tokens
                    or state.paid_calls >= self.session_max_calls
                    or state.paid_tokens >= self.session_max_tokens
                )

            # Outside explicit run_scope (e.g. unit tests calling spend_guard.record_usage directly)
            if state.offline_calls > 0 and state.paid_calls == 0 and state.local_calls == 0:
                return False
            if state.local_calls > 0 and state.paid_calls == 0:
                return bool(
                    state.local_safety_tripped
                    or state.local_calls >= self.safety_max_calls
                    or state.local_tokens >= self.safety_max_tokens
                )
            return bool(
                state.paid_exhausted
                or state.query_paid_exhausted
                or state.query_paid_calls >= self.max_calls
                or state.query_paid_tokens >= self.max_tokens
                or state.paid_calls >= self.session_max_calls
                or state.paid_tokens >= self.session_max_tokens
            )

    def reset(self, run_id: str | None = None) -> None:
        """Reset spend counters for the given (or current active) run."""
        rid = self.current_run_id(run_id)
        with self._lock:
            self._runs[rid] = _RunUsage()

    def reset_all(self) -> None:
        """Clear spend counters across all tracked runs (benchmark/startup use only)."""
        with self._lock:
            self._runs.clear()

    @property
    def calls_count(self) -> int:
        """Total LLM calls executed in the active run across all modes (telemetry delta)."""
        rid = self.current_run_id()
        with self._lock:
            state = self._runs.get(rid)
            if state is None:
                return 0
            return state.paid_calls + state.offline_calls + state.local_calls

    @property
    def tokens_count(self) -> int:
        """Total LLM tokens consumed in the active run across all modes (telemetry delta)."""
        rid = self.current_run_id()
        with self._lock:
            state = self._runs.get(rid)
            if state is None:
                return 0
            return state.paid_tokens + state.offline_tokens + state.local_tokens

    @property
    def paid_calls_count(self) -> int:
        rid = self.current_run_id()
        with self._lock:
            state = self._runs.get(rid)
            return state.paid_calls if state is not None else 0

    @property
    def paid_tokens_count(self) -> int:
        rid = self.current_run_id()
        with self._lock:
            state = self._runs.get(rid)
            return state.paid_tokens if state is not None else 0

    @property
    def offline_calls_count(self) -> int:
        rid = self.current_run_id()
        with self._lock:
            state = self._runs.get(rid)
            return state.offline_calls if state is not None else 0

    @property
    def offline_tokens_count(self) -> int:
        rid = self.current_run_id()
        with self._lock:
            state = self._runs.get(rid)
            return state.offline_tokens if state is not None else 0

    @property
    def local_calls_count(self) -> int:
        rid = self.current_run_id()
        with self._lock:
            state = self._runs.get(rid)
            return state.local_calls if state is not None else 0

    @property
    def local_tokens_count(self) -> int:
        rid = self.current_run_id()
        with self._lock:
            state = self._runs.get(rid)
            return state.local_tokens if state is not None else 0


# Process-global singleton coordinating budgets cleanly per isolated run_id
spend_guard = SpendGuard()

__all__ = [
    "CallCapExceededError",
    "DEFAULT_RUN_ID",
    "LocalSafetyLimitError",
    "SpendGuard",
    "SpendGuardExceededError",
    "SpendGuardStatus",
    "TokenCapExceededError",
    "spend_guard",
]
