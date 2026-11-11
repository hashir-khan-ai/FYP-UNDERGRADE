"""Spend guard enforcing hard caps on LLM calls and token budgets per run."""

import threading
from src.config import settings


class SpendGuardExceededError(RuntimeError):
    """Raised when the configured call or token budget per run has been reached."""
    pass


class SpendGuard:
    """Tracks token and API call expenditures to protect free and paid tier limits."""

    def __init__(self, max_calls: int | None = None, max_tokens: int | None = None) -> None:
        self.max_calls = max_calls if max_calls is not None else settings.LLM_MAX_CALLS_PER_RUN
        self.max_tokens = max_tokens if max_tokens is not None else settings.LLM_MAX_TOKENS_PER_RUN
        self._calls = 0
        self._tokens = 0
        self._lock = threading.Lock()

    def check_call_allowed(self) -> None:
        """Verify that another LLM API call is permitted within budget."""
        with self._lock:
            if self._calls >= self.max_calls:
                raise SpendGuardExceededError(
                    f"Spend guard cap exceeded: this run used {self._calls} of {self.max_calls} allowed LLM calls. "
                    "Stopping to protect API quota; raise LLM_MAX_CALLS_PER_RUN or start a new run."
                )
            if self._tokens >= self.max_tokens:
                raise SpendGuardExceededError(
                    f"Spend guard token cap exceeded: this run used {self._tokens} of {self.max_tokens} allowed tokens. "
                    "Stopping to protect API quota; raise LLM_MAX_TOKENS_PER_RUN or start a new run."
                )

    @property
    def exhausted(self) -> bool:
        """Return True when either the call or token budget is exhausted."""
        with self._lock:
            return self._calls >= self.max_calls or self._tokens >= self.max_tokens

    def record_usage(self, prompt_tokens: int, completion_tokens: int) -> None:
        """Record token usage and increment call count."""
        call_tokens = prompt_tokens + completion_tokens
        with self._lock:
            self._calls += 1
            self._tokens += call_tokens

            if self._tokens > self.max_tokens:
                raise SpendGuardExceededError(
                    f"Spend guard token cap exceeded: consumed {self._tokens} tokens "
                    f"(limit: {self.max_tokens} tokens). Stopping execution."
                )

    @property
    def calls_count(self) -> int:
        with self._lock:
            return self._calls

    @property
    def tokens_count(self) -> int:
        with self._lock:
            return self._tokens

    def reset(self) -> None:
        """Reset counters (used primarily between test suites or new batch runs)."""
        with self._lock:
            self._calls = 0
            self._tokens = 0


# Default global singleton
spend_guard = SpendGuard()

