"""Tests for LLM profile resolution and the zero-quota test guard."""

import pytest

from src.config import Settings


def _settings(**overrides: object) -> Settings:
    """Build isolated settings without reading the developer's .env file."""
    return Settings(_env_file=None, **overrides)


def test_mock_profile_needs_no_credentials() -> None:
    llm = _settings(LLM_PROFILE="mock").llm

    assert llm.is_mock is True
    assert llm.profile == "mock"
    assert llm.model == "mock"
    assert llm.base_url is None
    assert llm.api_key is None


def test_dev_profile_resolves_free_provider_credentials() -> None:
    llm = _settings(
        APP_ENV="development",
        LLM_PROFILE="dev",
        LLM_BASE_URL="https://free.example/v1",
        LLM_API_KEY="dev-key",
        LLM_MODEL="free-model",
    ).llm

    assert llm.is_mock is False
    assert llm.base_url == "https://free.example/v1"
    assert llm.model == "free-model"
    assert llm.api_key == "dev-key"


def test_demo_profile_never_borrows_dev_credentials() -> None:
    llm = _settings(
        APP_ENV="development",
        LLM_PROFILE="demo",
        LLM_API_KEY="dev-key",
        DEMO_LLM_BASE_URL="https://paid.example/v1",
        DEMO_LLM_API_KEY="demo-key",
        DEMO_LLM_MODEL="paid-model",
    ).llm

    assert llm.base_url == "https://paid.example/v1"
    assert llm.model == "paid-model"
    assert llm.api_key == "demo-key"


def test_demo_profile_without_its_own_key_fails_fast() -> None:
    with pytest.raises(ValueError, match="DEMO_LLM_API_KEY"):
        _settings(
            APP_ENV="development",
            LLM_PROFILE="demo",
            LLM_API_KEY="dev-key",
        ).llm


def test_live_profile_is_rejected_when_app_env_is_test() -> None:
    with pytest.raises(RuntimeError, match="APP_ENV=test"):
        _settings(
            APP_ENV="test",
            LLM_PROFILE="dev",
            LLM_API_KEY="dev-key",
        ).llm


def test_mock_profile_remains_usable_when_app_env_is_test() -> None:
    assert _settings(APP_ENV="test", LLM_PROFILE="mock").ensure_llm_ready().is_mock is True


def test_seed_password_is_required_outside_the_test_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A shared environment must never be seeded with a built-in default."""
    from scripts.seed_data import resolve_seed_password
    from src.config import settings

    monkeypatch.setattr(settings, "SEED_DEFAULT_PASSWORD", "")
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.delenv("SEED_DEFAULT_PASSWORD", raising=False)

    with pytest.raises(SystemExit, match="SEED_DEFAULT_PASSWORD"):
        resolve_seed_password()


def test_seed_password_falls_back_only_when_app_env_is_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.seed_data import TEST_ONLY_SEED_PASSWORD, resolve_seed_password
    from src.config import settings

    monkeypatch.setattr(settings, "SEED_DEFAULT_PASSWORD", "")
    monkeypatch.setattr(settings, "APP_ENV", "test")
    monkeypatch.delenv("SEED_DEFAULT_PASSWORD", raising=False)

    assert resolve_seed_password() == TEST_ONLY_SEED_PASSWORD


def test_configured_seed_password_is_used_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.seed_data import resolve_seed_password
    from src.config import settings

    monkeypatch.setattr(settings, "SEED_DEFAULT_PASSWORD", "local-demo-secret")
    monkeypatch.setattr(settings, "APP_ENV", "development")

    assert resolve_seed_password() == "local-demo-secret"
