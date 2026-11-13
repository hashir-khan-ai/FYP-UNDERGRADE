#!/usr/bin/env python3
"""Scan repository and git log history for leaked API keys, tokens, or credentials."""

import os
import re
import subprocess
import sys
from pathlib import Path

PATTERNS = [
    re.compile(r"(?i)(?:api[_-]?key|secret[_-]?key|access[_-]?token)\s*[:=]\s*['\"]([A-Za-z0-9_\-]{20,})['\"]"),
    re.compile(r"(?i)bearer\s+([A-Za-z0-9_\-\.]{25,})"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AIza[0-9A-Za-z-_]{35}"),
]

SAFE_TOKENS = {
    "change-in-production",
    "mock-key",
    "dummy",
    "placeholder",
    "your_key_here",
    "test-secret",
    "supersecretjwtkeyforlocaldevelopmentonly12345",
    "gsk_super_secret_test_key_xyz987",
    "gsk_test_mock_secret_key_12345",
    "bearer eyjhbgci",
}


def scan_git_history() -> list[str]:
    findings = []
    res = subprocess.run(["git", "log", "-p", "--all"], stdout=subprocess.PIPE, text=True, errors="ignore")
    for line in res.stdout.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            stripped = line[1:].strip()
            if any(safe in stripped.lower() for safe in SAFE_TOKENS):
                continue
            for pat in PATTERNS:
                if pat.search(stripped):
                    findings.append(stripped)
    return findings


def scan_workspace_files() -> list[tuple[str, str]]:
    findings = []
    root = Path(".")
    ignored_dirs = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules", "data/qdrant"}
    for p in root.rglob("*"):
        if p.is_file():
            if any(part in ignored_dirs for part in p.parts):
                continue
            if p.name == ".env":
                # Verify .env is git-ignored
                check = subprocess.run(["git", "check-ignore", str(p)], stdout=subprocess.PIPE, text=True)
                if check.returncode != 0:
                    findings.append((str(p), "Un-ignored .env file tracked or exposed!"))
                continue
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for line in content.splitlines():
                if any(safe in line.lower() for safe in SAFE_TOKENS):
                    continue
                for pat in PATTERNS:
                    if pat.search(line):
                        findings.append((str(p), line.strip()[:60]))
    return findings


def main() -> int:
    history_findings = scan_git_history()
    workspace_findings = scan_workspace_files()

    print(f"Secret Scan Results:")
    print(f"  Git history findings : {len(history_findings)}")
    print(f"  Working tree findings: {len(workspace_findings)}")

    if history_findings:
        print("\n[ALERT] Secrets found in git history:")
        for h in history_findings[:10]:
            print(f"  - {h[:80]}")

    if workspace_findings:
        print("\n[ALERT] Secrets found in workspace:")
        for path, line in workspace_findings[:10]:
            print(f"  - {path}: {line}")

    if not history_findings and not workspace_findings:
        print("\n[OK] Clean: zero leaked secrets found in repo or git history.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
