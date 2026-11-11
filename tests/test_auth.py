"""Authentication tests: Argon2 hashing, signed tokens, lockout and token tampering."""

import time

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.config import settings
from src.core.auth import (
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    login_throttle,
    verify_password,
)

client = TestClient(app)


def _login(username: str, password: str):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def test_password_hashing_is_argon2id_and_verifiable() -> None:
    """Passwords are stored as salted Argon2id hashes, never plaintext."""
    password = "synthetic-demo-password"
    stored = hash_password(password)
    assert stored.startswith("$argon2id$")
    assert password not in stored
    assert verify_password(stored, password) is True
    assert verify_password(stored, "wrong-password") is False
    assert verify_password("not-a-hash", password) is False


def test_login_returns_token_without_secret_material(seeded_auth_users) -> None:
    info = seeded_auth_users["analyst"]
    response = _login(info["username"], info["password"])
    assert response.status_code == 200

    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"] == {
        "id": info["id"],
        "username": info["username"],
        "full_name": info["full_name"],
        "role": "analyst",
    }
    assert body["access_token"]
    assert "password" not in response.text.lower()
    assert "$argon2" not in response.text


def test_login_rejects_wrong_password(seeded_auth_users) -> None:
    info = seeded_auth_users["analyst"]
    response = _login(info["username"], "definitely-wrong")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_login_unknown_user_gets_the_same_generic_error(seeded_auth_users) -> None:
    response = _login("nobody_here", "definitely-wrong")
    assert response.status_code == 401
    assert response.json()["error"] == {
        "code": "INVALID_CREDENTIALS",
        "message": "Invalid username or password.",
        "details": None,
    }


def test_login_is_rate_limited(seeded_auth_users, monkeypatch: pytest.MonkeyPatch) -> None:
    """Repeated attempts within a minute are throttled with 429."""
    monkeypatch.setattr(settings, "AUTH_LOGIN_RATE_LIMIT_PER_MINUTE", 2)
    monkeypatch.setattr(settings, "AUTH_MAX_LOGIN_ATTEMPTS", 50)
    login_throttle.reset()

    info = seeded_auth_users["analyst"]
    assert _login(info["username"], "wrong-one").status_code == 401
    assert _login(info["username"], "wrong-two").status_code == 401
    limited = _login(info["username"], "wrong-three")
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "LOGIN_RATE_LIMITED"


def test_login_locks_out_after_repeated_failures(
    seeded_auth_users,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After N failures the identity is locked even for the correct password."""
    monkeypatch.setattr(settings, "AUTH_MAX_LOGIN_ATTEMPTS", 3)
    monkeypatch.setattr(settings, "AUTH_LOGIN_RATE_LIMIT_PER_MINUTE", 100)
    login_throttle.reset()

    info = seeded_auth_users["manager"]
    for _ in range(3):
        assert _login(info["username"], "wrong-password").status_code == 401

    locked = _login(info["username"], info["password"])
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "ACCOUNT_LOCKED"


def test_tampered_token_is_rejected(seeded_auth_users) -> None:
    info = seeded_auth_users["analyst"]
    token = create_access_token(info["id"], info["username"], "analyst")
    tampered = token[:-2] + ("aa" if not token.endswith("aa") else "bb")

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tampered}"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_expired_token_is_rejected(seeded_auth_users) -> None:
    info = seeded_auth_users["analyst"]
    token = create_access_token(info["id"], info["username"], "analyst")
    claims = decode_access_token(token)

    with pytest.raises(TokenError):
        decode_access_token(token, now=claims.expires_at + 1)

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {'x' * 10}.{'y' * 10}"},
    )
    assert response.status_code == 401


def test_server_reloads_role_from_database_not_from_the_token(seeded_auth_users) -> None:
    """A token claiming a different role cannot escalate privileges."""
    info = seeded_auth_users["analyst"]
    forged = create_access_token(info["id"], info["username"], "auditor")

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.status_code == 200
    assert response.json()["role"] == "analyst"


def test_client_supplied_role_and_user_id_are_ignored(seeded_auth_users) -> None:
    """Request bodies cannot override the role resolved from the session."""
    info = seeded_auth_users["analyst"]
    headers = {"Authorization": f"Bearer {create_access_token(info['id'], info['username'], 'analyst')}"}

    response = client.post(
        "/ask",
        json={"query": "What are the KYC requirements?", "role": "auditor", "user_id": 3},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["role"] == "analyst"


def test_logout_revokes_the_token(seeded_auth_users) -> None:
    info = seeded_auth_users["analyst"]
    token = create_access_token(info["id"], info["username"], "analyst")
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200

    revoked = client.get("/api/v1/auth/me", headers=headers)
    assert revoked.status_code == 401
    assert revoked.json()["error"]["code"] == "INVALID_TOKEN"


def test_token_expiry_claim_is_short_lived(seeded_auth_users) -> None:
    info = seeded_auth_users["auditor"]
    claims = decode_access_token(create_access_token(info["id"], info["username"], "auditor"))
    ttl_seconds = claims.expires_at - claims.issued_at
    assert ttl_seconds == int(settings.AUTH_TOKEN_TTL_MINUTES * 60)
    assert claims.expires_at > int(time.time())


def test_user_listing_never_exposes_hashes(seeded_auth_users) -> None:
    response = client.get("/api/v1/auth/users")
    assert response.status_code == 200
    users = response.json()
    assert len(users) >= 3
    for user in users:
        assert set(user) == {"id", "username", "full_name", "role"}
    assert "argon2" not in response.text.lower()
