"""Mutant testing guards and startup invariants.

CRITICAL ARCHITECTURAL CONTRACT:
Production application code in `src/` contains ZERO reachable mutant switches.
Mutants for positive controls (mutation testing) are applied EXCLUSIVELY by test
fixtures via monkeypatching specific target functions, NEVER via environment flags
or runtime switches in `src/`.

To guarantee absolute defense against accidental misconfiguration or privilege
spoofing, any attempt to set legacy `MUTANT_*` environment variables causes
immediate startup refusal via `check_no_mutant_flags_on_startup()`.
"""

from __future__ import annotations

import os
import sys

LEGACY_MUTANT_ENV_VARS: tuple[str, ...] = (
    "MUTANT_DISABLE_CANARY_GUARD",
    "MUTANT_DISABLE_POST_RERANK_RBAC",
    "MUTANT_DISABLE_PRE_FUSION_RBAC",
    "MUTANT_CACHE_NO_ROLE",
    "MUTANT_SHARED_MEMORY",
    "MUTANT_DISTINCT_REFUSAL",
    "MUTANT_ROLE_FROM_BODY",
)

ALL_MUTANT_FLAGS: tuple[str, ...] = LEGACY_MUTANT_ENV_VARS


def is_running_under_pytest() -> bool:
    """Informational check: returns True if executing within a pytest session.

    HISTORICAL CONTEXT:
    Previously, mutant flags checked this function to decide whether to activate.
    This was redesigned because an adversary could set PYTEST_CURRENT_TEST=1 or
    import pytest in a subprocess to bypass defenses. Now, production code NEVER
    branches on this check, and production code has ZERO reachable mutant switches.
    """
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


def is_mutant_active(flag_name: str) -> bool:
    """Legacy compatibility stub.

    Production code has zero reachable mutant switches and does not call this function.
    Always returns False to guarantee no bypass is ever possible via environment flags.
    """
    return False


def check_no_mutant_flags_on_startup() -> None:
    """Validate that no legacy test-only mutant environment flags are set.

    Production code contains NO reachable mutant switches. Mutants in tests are
    applied strictly via monkeypatch fixtures, never via environment flags.
    If any legacy mutant environment variable is detected in os.environ (even if
    PYTEST_CURRENT_TEST is spoofed or pytest is imported), startup is immediately
    refused.

    Raises:
        RuntimeError: if any legacy mutant environment variable is detected.
    """
    detected = [flag for flag in ALL_MUTANT_FLAGS if os.environ.get(flag) is not None]
    if detected:
        raise RuntimeError(
            f"SECURITY FATAL: Application startup refused. Legacy mutant environment variables detected: "
            f"{', '.join(detected)}. Production code contains zero reachable mutant switches. "
            f"Mutant testing is performed strictly via monkeypatch test fixtures, and env flags "
            f"are forbidden."
        )
