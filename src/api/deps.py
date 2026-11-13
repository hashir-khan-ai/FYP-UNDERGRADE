"""Shared FastAPI dependencies: envelope errors and bearer-token authentication."""

from dataclasses import dataclass

from fastapi import Depends, Header, Request

from src.config import settings
from src.core.auth import TokenError, decode_access_token
from src.core.rate_limiter import api_rate_limiter
from src.db.connection import get_db_connection
from src.db.repository import Repository


class ApiError(Exception):
    """Sanitized API failure rendered as the documented error envelope."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: object = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


@dataclass(frozen=True)
class CurrentUser:
    """Authenticated identity derived from the token and the user table."""

    id: int
    username: str
    full_name: str
    role: str
    jti: str
    expires_at: int


def get_current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    """Resolve the authenticated user from the bearer token.

    The user identifier comes from the signed token, but the role is always
    reloaded from SQLite so a role change takes effect immediately and a
    client-supplied role field can never influence retrieval.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError(401, "UNAUTHENTICATED", "A valid bearer token is required.")

    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = decode_access_token(token)
    except TokenError as exc:
        raise ApiError(401, "INVALID_TOKEN", str(exc)) from exc

    with get_db_connection() as conn:
        row = Repository(conn).get_user_by_id(claims.user_id)

    if row is None or not int(row["is_active"] or 0):
        raise ApiError(401, "INVALID_TOKEN", "The account for this token is not active.")

    return CurrentUser(
        id=int(row["id"]),
        username=str(row["username"]),
        full_name=str(row["full_name"]),
        role=str(row["role_name"]),
        jti=claims.jti,
        expires_at=claims.expires_at,
    )


def require_role(*allowed_roles: str):
    """Build a dependency that allows only the listed roles."""

    def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed_roles:
            raise ApiError(403, "FORBIDDEN", "Your role is not permitted to use this endpoint.")
        return user

    return dependency


def _client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def enforce_query_rate_limit(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Apply sliding-window API rate limits per authenticated user and client IP."""
    key = f"query:user:{user.id}:{_client_ip(request)}"
    api_rate_limiter.check_and_record(
        key,
        limit=settings.API_RATE_LIMIT_PER_MINUTE,
        window_seconds=60.0,
        scope="query",
    )


def enforce_upload_rate_limit(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Apply stricter per-user/IP rate limits on document ingestion uploads."""
    key = f"upload:user:{user.id}:{_client_ip(request)}"
    api_rate_limiter.check_and_record(
        key,
        limit=settings.API_UPLOAD_RATE_LIMIT_PER_MINUTE,
        window_seconds=60.0,
        scope="upload",
    )


__all__ = [
    "ApiError",
    "CurrentUser",
    "enforce_query_rate_limit",
    "enforce_upload_rate_limit",
    "get_current_user",
    "require_role",
]
