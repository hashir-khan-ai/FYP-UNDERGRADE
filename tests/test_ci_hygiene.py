"""CI hygiene tests: verify complete absence of Streamlit and port 8501 from active source and config."""

from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_requirements_contains_no_streamlit() -> None:
    """requirements.txt must not contain streamlit."""
    req_path = REPO_ROOT / "requirements.txt"
    assert req_path.exists(), "requirements.txt not found"
    content = req_path.read_text(encoding="utf-8").lower()
    assert "streamlit" not in content, "streamlit found in requirements.txt"


def test_active_source_contains_no_streamlit() -> None:
    """src/ directory must contain zero occurrences of streamlit."""
    src_dir = REPO_ROOT / "src"
    assert src_dir.exists(), "src/ directory not found"
    for py_file in src_dir.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8").lower()
        assert "streamlit" not in text, f"Found 'streamlit' in active source file: {py_file}"


def test_docker_and_makefile_contain_no_streamlit_or_8501() -> None:
    """Build files (Dockerfile, docker-compose.yml, Makefile) must not contain streamlit or port 8501."""
    for filename in ("Dockerfile", "docker-compose.yml", "Makefile"):
        filepath = REPO_ROOT / filename
        if filepath.exists():
            text = filepath.read_text(encoding="utf-8").lower()
            assert "streamlit" not in text, f"Found 'streamlit' in {filename}"
            assert "8501" not in text, f"Found port '8501' in {filename}"


def test_web_contains_no_8501() -> None:
    """web/ workspace must not contain port 8501."""
    web_dir = REPO_ROOT / "web"
    assert web_dir.exists(), "web/ directory not found"
    for path in web_dir.rglob("*"):
        if path.is_file() and not any(part in path.parts for part in ("node_modules", ".next")):
            if path.suffix in (".ts", ".tsx", ".js", ".mjs", ".json", ".css", ".md"):
                text = path.read_text(encoding="utf-8", errors="ignore")
                assert "8501" not in text, f"Found '8501' in web file: {path}"

