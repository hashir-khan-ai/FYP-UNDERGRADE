"""Runner script to launch FastAPI and Next.js, execute capture_phase15_screenshots, and clean up."""

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PYTHON_EXE = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"


def wait_for_url(url: str, timeout: float = 30.0) -> bool:
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
    print("=== Launching FastAPI and Next.js for Phase 15 Screenshot Capture ===")
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
        "info",
    ]
    print("Starting FastAPI on 127.0.0.1:8000...")
    fastapi_log = open(PROJECT_ROOT / "fastapi_test.log", "w", encoding="utf-8")
    fastapi_proc = subprocess.Popen(
        fastapi_cmd, cwd=str(PROJECT_ROOT), env=env, stdout=fastapi_log, stderr=subprocess.STDOUT
    )

    # 2. Start Next.js
    next_cmd = ["cmd", "/c", "npm", "run", "start"]
    print("Starting Next.js on 127.0.0.1:3000...")
    next_proc = subprocess.Popen(
        next_cmd,
        cwd=str(PROJECT_ROOT / "web"),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        print("Waiting for FastAPI (http://127.0.0.1:8000/health)...")
        if not wait_for_url("http://127.0.0.1:8000/health", 25.0):
            print("FastAPI failed to start in time.")
            sys.exit(1)
        print("FastAPI is ready.")

        print("Waiting for Next.js (http://localhost:3000/login)...")
        if not wait_for_url("http://localhost:3000/login", 30.0):
            print("Next.js failed to start in time.")
            sys.exit(1)
        print("Next.js is ready.")

        # 3. Run screenshot capture script
        print("\n=== Executing Phase 15 Screenshot Capture & A11y Audit ===")
        capture_cmd = [str(PYTHON_EXE), str(PROJECT_ROOT / "scripts" / "capture_phase15_screenshots.py")]
        res = subprocess.run(capture_cmd, cwd=str(PROJECT_ROOT), env=env)
        if res.returncode != 0:
            print(f"Screenshot capture exited with code {res.returncode}")
            sys.exit(res.returncode)
        print("Screenshot capture completed successfully.")

    finally:
        print("\nShutting down Next.js and FastAPI servers...")
        next_proc.terminate()
        try:
            next_proc.wait(timeout=5)
        except Exception:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(next_proc.pid)], capture_output=True)

        fastapi_proc.terminate()
        try:
            fastapi_proc.wait(timeout=5)
        except Exception:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(fastapi_proc.pid)], capture_output=True)
        print("Servers stopped.")


if __name__ == "__main__":
    main()
