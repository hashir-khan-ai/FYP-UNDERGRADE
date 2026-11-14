"""Runner script to launch FastAPI and Next.js, run capture_partb_screenshots, and clean up."""

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON_EXE = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"


def wait_for_url(url: str, timeout: float = 25.0) -> bool:
    start = time.time()
    proxy_handler = urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(proxy_handler)
    while time.time() - start < timeout:
        try:
            with opener.open(url, timeout=2.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def main():
    print("=== Launching FastAPI and Next.js for Screenshot Capture ===")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    env["APP_ENV"] = "test"
    env["LLM_PROFILE"] = "mock"
    env["NO_PROXY"] = "localhost,127.0.0.1"
    env["no_proxy"] = "localhost,127.0.0.1"

    # 1. Start FastAPI backend
    fastapi_cmd = [
        str(PYTHON_EXE),
        "-m",
        "uvicorn",
        "src.api.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        "--log-level",
        "warning",
    ]
    print("Starting FastAPI on 127.0.0.1:8000...")
    fastapi_proc = subprocess.Popen(
        fastapi_cmd, cwd=str(PROJECT_ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

    # 2. Start Next.js
    next_cmd = ["cmd", "/c", "npm", "run", "start"]
    print("Starting Next.js on 127.0.0.1:3000...")
    next_proc = subprocess.Popen(
        next_cmd,
        cwd=str(PROJECT_ROOT / "web"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        print("Waiting for FastAPI (127.0.0.1:8000/health)...")
        if not wait_for_url("http://127.0.0.1:8000/health", 25.0):
            raise RuntimeError("FastAPI failed to become ready on port 8000")
        print("FastAPI is online.")

        print("Waiting for Next.js (127.0.0.1:3000)...")
        if not wait_for_url("http://127.0.0.1:3000", 25.0):
            raise RuntimeError("Next.js failed to become ready on port 3000")
        print("Next.js is online.")

        # 3. Run screenshot capture
        print("\n=== Running capture_partb_screenshots.py ===")
        capture_cmd = [str(PYTHON_EXE), str(PROJECT_ROOT / "scripts" / "capture_partb_screenshots.py")]
        res = subprocess.run(capture_cmd, cwd=str(PROJECT_ROOT), env=env, check=True)
        print(f"Capture finished with exit code {res.returncode}")

    finally:
        print("\nShutting down Next.js and FastAPI...")
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(next_proc.pid)], capture_output=True)
        except Exception:
            pass
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(fastapi_proc.pid)], capture_output=True)
        except Exception:
            pass
        print("Processes cleaned up.")


if __name__ == "__main__":
    main()
