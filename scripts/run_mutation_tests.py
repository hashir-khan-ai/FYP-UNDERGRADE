#!/usr/bin/env python3
"""Mutation testing runner for RAG security controls (Positive Controls).

Verifies that the security suite is capable of failing when defenses are
deliberately broken.

For each mutant:
  - Executes the targeted security test with the mutant flag active.
  - If the test FAILS (non-zero exit code), the mutant is KILLED.
  - If the test PASSES (zero exit code), the mutant SURVIVED (test is blind).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON_EXE = sys.executable

MUTANTS = [
    {
        "id": "MUTANT-A",
        "env_var": "MUTANT_DISABLE_CANARY_GUARD",
        "description": "Output canary guard disabled (canaries not scrubbed/blocked)",
        "target_defense": "Canary Output Guard",
        "test_command": [
            PYTHON_EXE,
            "-m",
            "pytest",
            "tests/test_security_depth.py::TestCanaryTokens::test_output_guard_neutralizes_unauthorized_canary",
            "-q",
        ],
    },
    {
        "id": "MUTANT-B",
        "env_var": "MUTANT_DISABLE_POST_RERANK_RBAC",
        "description": "Post-rerank RBAC defense-in-depth filter disabled",
        "target_defense": "Post-Rerank Role Enforcement",
        "test_command": [
            PYTHON_EXE,
            "-m",
            "pytest",
            "tests/test_security_depth.py::TestResultCountSideChannel::test_post_rerank_rbac_defense",
            "-q",
        ],
    },
    {
        "id": "MUTANT-C",
        "env_var": "MUTANT_DISABLE_PRE_FUSION_RBAC",
        "description": "Pre-fusion RBAC vector/lexical search payload filter disabled",
        "target_defense": "Vector & Lexical Native RBAC",
        "test_command": [
            PYTHON_EXE,
            "-m",
            "pytest",
            "tests/test_security_depth.py::TestResultCountSideChannel::test_pre_fusion_rbac_filter",
            "-q",
        ],
    },
    {
        "id": "MUTANT-D",
        "env_var": "MUTANT_CACHE_NO_ROLE",
        "description": "Cache key computed without user_role or user_id",
        "target_defense": "Cache Role Partitioning",
        "test_command": [
            PYTHON_EXE,
            "-m",
            "pytest",
            "tests/test_security_depth.py::TestCrossRoleCacheAndMemoryIsolation::test_cross_role_cache_keys_differ",
            "-q",
        ],
    },
    {
        "id": "MUTANT-E",
        "env_var": "MUTANT_SHARED_MEMORY",
        "description": "Session memory shared across users/roles (ownership check bypassed)",
        "target_defense": "Session Memory Boundary",
        "test_command": [
            PYTHON_EXE,
            "-m",
            "pytest",
            "tests/test_security_depth.py::TestCrossRoleCacheAndMemoryIsolation::test_cross_user_memory_isolation",
            "-q",
        ],
    },
    {
        "id": "MUTANT-F",
        "env_var": "MUTANT_DISTINCT_REFUSAL",
        "description": "Uniform refusal replaced by distinct 'ACCESS RESTRICTED' text",
        "target_defense": "Side-Channel Refusal Uniformity",
        "test_command": [
            PYTHON_EXE,
            "-m",
            "pytest",
            "tests/test_security_depth.py::TestResultCountSideChannel::test_refusal_uniformity_side_channel",
            "-q",
        ],
    },
    {
        "id": "MUTANT-G",
        "env_var": "MUTANT_ROLE_FROM_BODY",
        "description": "Role taken from client request body rather than signed JWT",
        "target_defense": "Signed Token Identity",
        "test_command": [
            PYTHON_EXE,
            "-m",
            "pytest",
            "tests/test_security_depth.py::TestIdentityAuthentication::test_forged_role_in_request_ignored",
            "-q",
        ],
    },
]


def run_single_mutant(mutant: dict[str, Any]) -> dict[str, Any]:
    """Run one mutant under isolated subprocess with environment variable toggled."""
    env = os.environ.copy()
    env[mutant["env_var"]] = "1"
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"

    cmd = mutant["test_command"]
    res = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    # If the targeted test FAILS with non-zero exit code, the security check CAUGHT the mutant!
    killed = res.returncode != 0
    return {
        "id": mutant["id"],
        "env_var": mutant["env_var"],
        "description": mutant["description"],
        "target_defense": mutant["target_defense"],
        "command": " ".join(cmd),
        "returncode": res.returncode,
        "stdout": res.stdout.strip()[:400],
        "killed": killed,
        "status": "KILLED" if killed else "SURVIVED",
    }


def run_all_mutations(output_dir: Path = Path("reports")) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    total = len(MUTANTS)
    killed_count = 0

    print("=" * 80)
    print("RUNNING POSITIVE CONTROL MUTATION TESTING (SECURITY SUITE)")
    print("=" * 80)

    for m in MUTANTS:
        res = run_single_mutant(m)
        results.append(res)
        if res["killed"]:
            killed_count += 1
            print(f"[{res['id']}] {res['env_var']}: KILLED (Test failed as expected when defense broken)")
        else:
            print(f"[{res['id']}] {res['env_var']}: SURVIVED (WARNING: Test passed despite broken defense!)")

    survived_count = total - killed_count
    kill_rate_pct = round((killed_count / total) * 100.0, 1) if total > 0 else 0.0

    report = {
        "total_mutants": total,
        "killed_count": killed_count,
        "survived_count": survived_count,
        "kill_rate_pct": kill_rate_pct,
        "mutants": results,
    }

    report_path = output_dir / "mutation_testing_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("-" * 80)
    print(f"Mutation Testing Summary: {killed_count}/{total} mutants killed ({kill_rate_pct}% kill rate)")
    print(f"Report saved: {report_path}")
    print("=" * 80)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run mutation tests on security controls.")
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    args = parser.parse_args()

    report = run_all_mutations(args.output_dir)
    return 0 if report["survived_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
