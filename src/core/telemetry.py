"""Structured correlation logging helpers for API requests and audit turns."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_REQUEST_ID_CTX: ContextVar[str] = ContextVar("correlation_request_id", default="-")
_AUDIT_ID_CTX: ContextVar[str] = ContextVar("correlation_audit_id", default="-")
_HOLDER_CTX: ContextVar[dict[str, str] | None] = ContextVar("correlation_holder", default=None)


def get_request_id() -> str:
    """Return active request correlation identifier or '-' outside a request."""
    holder = _HOLDER_CTX.get()
    if holder is not None:
        return holder.get("request_id", "-")
    return _REQUEST_ID_CTX.get()


def get_audit_id() -> str:
    """Return active audit correlation identifier or '-' when unset."""
    holder = _HOLDER_CTX.get()
    if holder is not None:
        return holder.get("audit_id", "-")
    return _AUDIT_ID_CTX.get()


@contextmanager
def request_correlation_scope(request_id: str) -> Iterator[str]:
    """Bind a sanitized correlation ID to the active execution context."""
    holder = {"request_id": request_id, "audit_id": "-"}
    tok_holder = _HOLDER_CTX.set(holder)
    tok_req = _REQUEST_ID_CTX.set(request_id)
    tok_aud = _AUDIT_ID_CTX.set("-")
    try:
        yield request_id
    finally:
        _AUDIT_ID_CTX.reset(tok_aud)
        _REQUEST_ID_CTX.reset(tok_req)
        _HOLDER_CTX.reset(tok_holder)


def bind_audit_id(audit_id: int | str) -> None:
    """Attach the persisted audit row ID to the active correlation scope."""
    val = str(audit_id)
    holder = _HOLDER_CTX.get()
    if holder is not None:
        holder["audit_id"] = val
    _AUDIT_ID_CTX.set(val)


class CorrelationLogFilter(logging.Filter):
    """Ensure every LogRecord exposes safe ``request_id`` and ``audit_id`` attributes."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = get_request_id()
        if not hasattr(record, "audit_id"):
            record.audit_id = get_audit_id()
        return True


def configure_correlation_logging() -> None:
    """Attach correlation filter safely to existing handlers or initialize clean root logging."""
    root = logging.getLogger()
    filt = CorrelationLogFilter()
    if not any(isinstance(f, CorrelationLogFilter) for f in root.filters):
        root.addFilter(filt)
    for handler in root.handlers:
        if not any(isinstance(f, CorrelationLogFilter) for f in handler.filters):
            handler.addFilter(filt)


__all__ = [
    "CorrelationLogFilter",
    "bind_audit_id",
    "configure_correlation_logging",
    "get_audit_id",
    "get_request_id",
    "request_correlation_scope",
]
