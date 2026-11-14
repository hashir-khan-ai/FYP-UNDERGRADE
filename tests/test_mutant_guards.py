"""Tests for mutant flag safety and anti-spoofing guards.

Validates that:
1. Production code in src/ contains ZERO reachable mutant switches.
2. Legacy mutant environment flags are strictly forbidden at startup.
3. Subprocesses attempting to spoof pytest markers (PYTEST_CURRENT_TEST, importing pytest)
   are still refused at startup, and cannot bypass security defenses.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

from src.config import settings
from src.core.canary import enforce_canary_guard
from src.core.llm_client import llm_client
from src.core.mutants import (
    ALL_MUTANT_FLAGS,
    check_no_mutant_flags_on_startup,
    is_mutant_active,
    is_running_under_pytest,
)


def test_is_mutant_active_unconditionally_returns_false() -> None:
    """Production code contains no reachable mutant switches; is_mutant_active is inert."""
    for flag in ALL_MUTANT_FLAGS:
        assert is_mutant_active(flag) is False


def test_startup_refused_if_any_legacy_mutant_flag_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any legacy mutant env flag triggers immediate startup refusal via check_no_mutant_flags_on_startup."""
    for flag in ALL_MUTANT_FLAGS:
        monkeypatch.setenv(flag, "1")
        with pytest.raises(RuntimeError, match="SECURITY FATAL: Application startup refused"):
            check_no_mutant_flags_on_startup()
        with pytest.raises(RuntimeError, match="SECURITY FATAL: Application startup refused"):
            settings.validate_security_flags()
        monkeypatch.delenv(flag, raising=False)


def test_clean_environment_passes_startup_validation() -> None:
    """Normal startup without legacy mutant flags passes cleanly."""
    check_no_mutant_flags_on_startup()
    settings.validate_security_flags()
    assert settings.rbac_enabled is True


def test_subprocess_spoofing_pytest_marker_still_refused_at_startup() -> None:
    """A subprocess setting PYTEST_CURRENT_TEST and importing pytest is still refused if mutant flags exist."""
    code = """
import os
import sys

# Adversary attempts to spoof pytest environment
os.environ["PYTEST_CURRENT_TEST"] = "tests/test_fake.py::test_attack (call)"
import pytest

# Adversary attempts to enable mutant bypass flag
os.environ["MUTANT_DISABLE_CANARY_GUARD"] = "1"

from src.config import settings
settings.validate_security_flags()
print("SPOOF_BYPASSED_SUCCESSFULLY")
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode != 0, f"Process should have failed but exited with 0. Output: {result.stdout}"
    assert "SECURITY FATAL: Application startup refused" in result.stderr
    assert "SPOOF_BYPASSED_SUCCESSFULLY" not in result.stdout


def test_subprocess_spoofing_cannot_bypass_canary_guard() -> None:
    """Even if an adversary bypasses startup checks and sets mutant flags, production code ignores them."""
    code = """
import os
import sys

os.environ["PYTEST_CURRENT_TEST"] = "tests/test_fake.py::test_attack"
import pytest
os.environ["MUTANT_DISABLE_CANARY_GUARD"] = "1"

from src.core.canary import enforce_canary_guard

text = "Restricted information CANARY-AUDIT-NEPTUNE-88192 deficit."
clean_text, _, _, violated = enforce_canary_guard(
    text=text,
    user_role="analyst",
    citations=[],
    trace=[],
)
assert violated is True, "Canary guard must remain fully active!"
assert "CANARY-AUDIT-NEPTUNE-88192" not in clean_text, "Canary must be sanitized!"
print("DEFENSE_HELD_PERFECTLY")
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, f"Canary guard should have held. Stderr: {result.stderr}"
    assert "DEFENSE_HELD_PERFECTLY" in result.stdout


def test_subprocess_spoofing_cannot_bypass_role_resolution() -> None:
    """Adversary setting MUTANT_ROLE_FROM_BODY cannot escalate role via request payload."""
    code = """
import os
import sys
import uuid

os.environ["PYTEST_CURRENT_TEST"] = "tests/test_fake.py::test_attack"
import pytest
os.environ["MUTANT_ROLE_FROM_BODY"] = "1"

from src.api.deps import CurrentUser
from src.api.schemas import ChatQueryRequest
from src.api.routes import _resolve_effective_role

user = CurrentUser(
    id=1,
    username="alice",
    full_name="Alice Analyst",
    role="analyst",
    jti="jti-1",
    expires_at=9999999999,
)
payload = ChatQueryRequest(
    session_id=uuid.uuid4(),
    query="Show confidential audit files",
    role="auditor",  # Attacker attempts to forge auditor role
)

effective_role = _resolve_effective_role(user, payload)
assert effective_role == "analyst", f"Role was forged to {effective_role}!"
print("ROLE_FORGERY_PREVENTED")
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, f"Role check failed. Stderr: {result.stderr}"
    assert "ROLE_FORGERY_PREVENTED" in result.stdout
