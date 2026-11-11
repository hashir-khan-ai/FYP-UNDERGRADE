"""Local demo authentication: Argon2id password hashing and signed bearer tokens.

Only synthetic demo users are supported. Passwords are hashed with Argon2id and
are never stored or logged in plaintext. Access tokens are HMAC-SHA256 signed
with ``SECRET_KEY``, carry an expiry and a unique ``jti``, and are validated
server-side on every protected request. Tokens, passwords and password hashes
are never written to logs.
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from src.config import settings

logger = logging.getLogger(__name__)

_PASSWORD_HASHER = PasswordHasher()
_INVALID_PASSWORD = "invalid-password-placeholder"
_DUMMY_HASH = _PASSWORD_HASHER.hash(_INVALID_PASSWORD)


class TokenError(ValueError):
    """Raised when a bearer token is malformed, tampered, expired or revoked."""


class LoginRateLimitedError(RuntimeError):
    """Raised when the login endpoint is called too often for one identity."""


class AccountLockedError(RuntimeError):
    """Raised while an identity is temporarily locked after repeated failures."""


def hash_password(password: str) -> str:
    """Return an Argon2id hash for a plaintext password."""
    return _PASSWORD_HASHER.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    """Verify a password against an Argon2id hash without raising."""
    try:
        return bool(_PASSWORD_HASHER.verify(stored_hash, password))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    except Exception:
        return False


def dummy_verify(password: str) -> None:
    """Burn comparable time for unknown usernames to limit enumeration."""
    verify_password(_DUMMY_HASH, password)


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign(payload: bytes) -> str:
    return _b64encode(
        hmac.new(settings.SECRET_KEY.encode("utf-8"), payload, hashlib.sha256).digest()
    )


@dataclass(frozen=True)
class TokenClaims:
    """Validated claims from a signed access token."""

    user_id: int
    username: str
    role: str
    jti: str
    issued_at: int
    expires_at: int


_REVOKED_TOKENS: dict[str, int] = {}
_REVOCATION_LOCK = threading.Lock()


def create_access_token(user_id: int, username: str, role: str) -> str:
    """Create a short-lived signed access token.

    Args:
        user_id: Authenticated user identifier.
        username: Username for display and audit.
        role: Role at issue time. Routes still reload the role from SQLite so a
            role change takes effect immediately.

    Returns:
        ``<payload>.<signature>`` using base64url encoding.
    """
    issued_at = int(time.time())
    payload = {
        "sub": int(user_id),
        "username": username,
        "role": role,
        "jti": secrets.token_urlsafe(16),
        "iat": issued_at,
        "exp": issued_at + int(settings.AUTH_TOKEN_TTL_MINUTES * 60),
    }
    encoded = _b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    return f"{encoded}.{_sign(encoded.encode('ascii'))}"


def decode_access_token(token: str, now: int | None = None) -> TokenClaims:
    """Validate a signed access token and return its claims.

    Raises:
        TokenError: if the token is malformed, has a bad signature, is expired,
            or has been revoked.
    """
    if not token or token.count(".") != 1:
        raise TokenError("Malformed access token.")

    encoded, signature = token.split(".", 1)
    expected = _sign(encoded.encode("ascii", errors="ignore"))
    if not hmac.compare_digest(expected, signature):
        raise TokenError("Invalid access token signature.")

    try:
        payload = json.loads(_b64decode(encoded))
    except Exception as exc:
        raise TokenError("Malformed access token payload.") from exc

    current = int(now if now is not None else time.time())
    try:
        claims = TokenClaims(
            user_id=int(payload["sub"]),
            username=str(payload["username"]),
            role=str(payload["role"]),
            jti=str(payload["jti"]),
            issued_at=int(payload["iat"]),
            expires_at=int(payload["exp"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise TokenError("Access token is missing required claims.") from exc

    if claims.expires_at <= current:
        raise TokenError("Access token has expired.")
    with _REVOCATION_LOCK:
        revoked = _REVOKED_TOKENS.get(claims.jti)
        if revoked is not None:
            if revoked > current:
                raise TokenError("Access token has been revoked.")
            _REVOKED_TOKENS.pop(claims.jti, None)
    return claims


def revoke_token(claims: TokenClaims) -> None:
    """Revoke one token until its natural expiry."""
    with _REVOCATION_LOCK:
        now = int(time.time())
        for key in [key for key, expiry in _REVOKED_TOKENS.items() if expiry <= now]:
            _REVOKED_TOKENS.pop(key, None)
        _REVOKED_TOKENS[claims.jti] = claims.expires_at


class LoginThrottle:
    """In-memory login rate limiter and lockout tracker.

    State is per process, which matches the single-instance local demo scope.
    A production deployment would move this to shared storage.
    """

    def __init__(self) -> None:
        self._attempts: dict[tuple[str, str], list[float]] = {}
        self._failures: dict[str, int] = {}
        self._locked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def check_allowed(self, username: str, client_key: str) -> None:
        """Raise when the caller is rate limited or locked out."""
        now = time.time()
        key = (username, client_key)
        with self._lock:
            locked_until = self._locked_until.get(username, 0.0)
            if locked_until > now:
                raise AccountLockedError(
                    "Too many failed sign-in attempts. This account is temporarily locked."
                )

            window_start = now - 60.0
            attempts = [stamp for stamp in self._attempts.get(key, []) if stamp > window_start]
            self._attempts[key] = attempts
            if len(attempts) >= settings.AUTH_LOGIN_RATE_LIMIT_PER_MINUTE:
                raise LoginRateLimitedError(
                    "Too many sign-in attempts. Please wait a minute and try again."
                )

    def record_attempt(self, username: str, client_key: str) -> None:
        """Record one attempt for the per-minute window."""
        with self._lock:
            self._attempts.setdefault((username, client_key), []).append(time.time())

    def record_failure(self, username: str) -> None:
        """Increment the failure counter and lock the identity if needed."""
        with self._lock:
            failures = self._failures.get(username, 0) + 1
            self._failures[username] = failures
            if failures >= settings.AUTH_MAX_LOGIN_ATTEMPTS:
                self._locked_until[username] = time.time() + settings.AUTH_LOCKOUT_SECONDS
                self._failures[username] = 0

    def record_success(self, username: str) -> None:
        """Clear failure state after a successful login."""
        with self._lock:
            self._failures.pop(username, None)
            self._locked_until.pop(username, None)

    def reset(self) -> None:
        """Clear all throttle state (used by tests)."""
        with self._lock:
            self._attempts.clear()
            self._failures.clear()
            self._locked_until.clear()


login_throttle = LoginThrottle()

__all__ = [
    "AccountLockedError",
    "LoginRateLimitedError",
    "LoginThrottle",
    "TokenClaims",
    "TokenError",
    "create_access_token",
    "decode_access_token",
    "dummy_verify",
    "hash_password",
    "login_throttle",
    "revoke_token",
    "verify_password",
]
