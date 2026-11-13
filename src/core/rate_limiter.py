"""Thread-safe per-user / per-IP sliding-window API rate limiter.

Independent of :mod:`src.core.spend_guard`: this limiter bounds inbound HTTP
request throughput per identity and client IP to protect server resources,
whereas SpendGuard bounds upstream paid LLM token/call spend per logical run.
"""

from __future__ import annotations

import collections
import math
import threading
import time
from typing import Callable


class RateLimitExceededError(RuntimeError):
    """Raised when an API client exceeds the per-minute request allowance."""

    def __init__(self, retry_after: int, scope: str = "api") -> None:
        self.retry_after = max(int(retry_after), 1)
        self.scope = scope
        self.http_status = 429
        self.error_code = "RATE_LIMIT_EXCEEDED"
        self.user_message = (
            f"Too many requests. Please wait {self.retry_after} seconds before trying again."
        )
        super().__init__(self.user_message)


class SlidingWindowRateLimiter:
    """In-memory, bounded sliding-window rate limiter keyed by user/IP scope."""

    MAX_BUCKETS = 4096

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or time.monotonic
        self._buckets: collections.OrderedDict[str, collections.deque[float]] = (
            collections.OrderedDict()
        )
        self._lock = threading.Lock()

    def check_and_record(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: float = 60.0,
        scope: str = "api",
    ) -> int:
        """Record one request for ``key`` and return remaining quota in the window.

        Raises:
            RateLimitExceededError: if the bucket has already reached ``limit``.
        """
        if limit <= 0:
            return 0
        now = self._clock()
        cutoff = now - window_seconds

        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= self.MAX_BUCKETS:
                    self._buckets.popitem(last=False)
                bucket = collections.deque()
                self._buckets[key] = bucket
            else:
                self._buckets.move_to_end(key)

            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= limit:
                oldest = bucket[0]
                retry_after = max(int(math.ceil(window_seconds - (now - oldest))), 1)
                raise RateLimitExceededError(retry_after=retry_after, scope=scope)

            bucket.append(now)
            return max(limit - len(bucket), 0)

    def remaining(
        self,
        key: str,
        *,
        limit: int,
        window_seconds: float = 60.0,
    ) -> int:
        """Inspect remaining slots for ``key`` without recording a request."""
        if limit <= 0:
            return 0
        now = self._clock()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                return limit
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            return max(limit - len(bucket), 0)

    def clear(self) -> None:
        """Reset all rate-limit buckets (used by isolated tests)."""
        with self._lock:
            self._buckets.clear()


api_rate_limiter = SlidingWindowRateLimiter()


__all__ = [
    "RateLimitExceededError",
    "SlidingWindowRateLimiter",
    "api_rate_limiter",
]
