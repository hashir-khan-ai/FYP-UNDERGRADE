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
    offline_calls: int = 0
    offline_tokens: int = 0
    local_calls: int = 0
    local_tokens: int = 0
    cached_calls: int = 0
    saved_tokens: int = 0
    paid_exhausted: bool = False
    local_safety_tripped: bool = False
    last_profile: str = "mock"
    last_has_paid_quota: bool = False
    last_is_local: bool = True
    last_latency_ms: float | None = None
    reserved_paid: int = field(default=0, repr=False)
    reserved_local: int = field(default=0, repr=False)


class SpendGuard:
    """Thread-safe, profile-aware LLM spend & runaway-loop guard scoped per run."""

    def __init__(
        self,
        max_calls: int | None = None,
        max_tokens: int | None = None,
        safety_max_calls: int | None = None,
        safety_max_tokens: int | None = None,
    ) -> None:
        self.max_calls = max_calls if max_calls is not None else settings.LLM_MAX_CALLS_PER_RUN
        self.max_tokens = max_tokens if max_tokens is not None else settings.LLM_MAX_TOKENS_PER_RUN
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

    def _raise_paid_call_cap(self, state: _RunUsage) -> None:
        state.paid_exhausted = True
        detail = (
            f"Paid quota call limit reached ({state.paid_calls}/{self.max_calls}); "
            "configure LLM_MAX_CALLS_PER_RUN or start a new session."
        )
        logger.warning(detail)
        raise CallCapExceededError(
            "Spend guard cap exceeded: this run reached its LLM call budget. Start a new session to continue.",
            user_message="This run reached its LLM call budget. Start a new session to continue.",
            internal_detail=detail,
        )

    def _raise_paid_token_cap(self, state: _RunUsage, prospective_tokens: int | None = None) -> None:
        state.paid_exhausted = True
        observed = prospective_tokens if prospective_tokens is not None else state.paid_tokens
        detail = (
            f"Paid quota token limit reached ({observed}/{self.max_tokens}); "
            "configure LLM_MAX_TOKENS_PER_RUN or start a new session."
        )
        logger.warning(detail)
        raise TokenCapExceededError(
            "Spend guard token cap exceeded: this run reached its LLM token budget. Start a new session to continue.",
            user_message="This run reached its LLM token budget. Start a new session to continue.",
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

            if state.paid_calls >= self.max_calls:
                self._raise_paid_call_cap(state)
            if state.paid_exhausted or state.paid_tokens >= self.max_tokens:
                self._raise_paid_token_cap(state)

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
            if state.paid_calls >= self.max_calls:
                self._raise_paid_call_cap(state)
            if state.paid_exhausted or state.paid_tokens >= self.max_tokens:
                self._raise_paid_token_cap(state)

            state.paid_calls += 1
            state.reserved_paid += 1
            if state.paid_calls >= self.max_calls:
                state.paid_exhausted = True
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
                state.reserved_paid -= 1
                state.paid_exhausted = (
                    state.paid_calls >= self.max_calls or state.paid_tokens >= self.max_tokens
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
        """Commit token usage for a call slot previously acquired via ``reserve_call``.

        Unlike the legacy increment-then-raise pattern, this records actual billed tokens
        for the already-completed call and marks the budget exhausted for subsequent calls
        without discarding a valid LLM response.
        """
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
            state.paid_tokens += call_tokens
            if state.paid_calls >= self.max_calls or state.paid_tokens >= self.max_tokens:
                state.paid_exhausted = True

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
        """Atomically check budget and record one completed call and its token usage.

        Used by standalone callers and tests; checks limits before mutating counters so
        blocked calls never overshoot ``max_calls`` or ``max_tokens``.
        """
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

            # Paid quota path: atomic check BEFORE mutation to prevent increment-then-raise overshoot.
            if state.paid_calls >= self.max_calls:
                self._raise_paid_call_cap(state)
            if state.paid_exhausted or state.paid_tokens >= self.max_tokens:
                self._raise_paid_token_cap(state)
            prospective_tokens = state.paid_tokens + call_tokens
            if prospective_tokens > self.max_tokens:
                self._raise_paid_token_cap(state, prospective_tokens=prospective_tokens)

            state.paid_calls += 1
            state.paid_tokens = prospective_tokens
            if state.paid_calls >= self.max_calls or state.paid_tokens >= self.max_tokens:
                state.paid_exhausted = True

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
            if scope == "offline":
                active_calls = state.offline_calls
                active_tokens = state.offline_tokens
                calls_limit = self.max_calls
                tokens_limit = self.max_tokens
                exhausted = False
                calls_remaining = calls_limit
                tokens_remaining = tokens_limit
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
                active_calls = state.paid_calls
                active_tokens = state.paid_tokens
                calls_limit = self.max_calls
                tokens_limit = self.max_tokens
                exhausted = bool(
                    state.paid_exhausted
                    or state.paid_calls >= self.max_calls
                    or state.paid_tokens >= self.max_tokens
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
                    or state.paid_calls >= self.max_calls
                    or state.paid_tokens >= self.max_tokens
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
                or state.paid_calls >= self.max_calls
                or state.paid_tokens >= self.max_tokens
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
