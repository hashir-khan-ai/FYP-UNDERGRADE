"""Phase 16 Addendum multi-theme, multi-viewport screenshot + overflow capture script.

Captures light and dark themes across 390px, 768px, 1440px, and 1920px viewports into
docs/screenshots/phase16b/{before,after}/{light,dark}/.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import tornado.websocket

from scripts.capture_phase16_screenshots import (
    ANSWER_SESSION_ID,
    BASE_URL,
    CHROME_PATH,
    CdpClient,
    EMPTY_SESSION_ID,
    capture_shot,
    clear_session_cookie,
    navigate_and_wait,
    seed_demo_data,
    set_session_cookie,
)

VIEWPORTS = [
    ("390", 390, 844, True),
    ("768", 768, 1024, True),
    ("1440", 1440, 900, False),
    ("1920", 1920, 1080, False),
]

THEMES = ("light", "dark")


def wait_for_http(url: str, timeout_sec: float = 25.0) -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with opener.open(url, timeout=1.5) as resp:
                if resp.status < 500:
                    return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def start_next_server() -> subprocess.Popen | None:
    if wait_for_http(f"{BASE_URL}/login", timeout_sec=1.2):
        return None
    npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
    proc = subprocess.Popen(
        [npm_cmd, "--prefix", str(PROJECT_ROOT / "web"), "run", "start", "--", "-p", "3000"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not wait_for_http(f"{BASE_URL}/login", timeout_sec=25.0):
        kill_tree(proc)
        raise RuntimeError("Next.js server failed to start on port 3000 within 25s.")
    return proc


def kill_tree(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=4,
                check=False,
            )
        else:
            proc.terminate()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        proc.wait(timeout=2)
    except Exception:
        pass


async def apply_theme(cdp: CdpClient, theme: str, script_id_holder: dict) -> None:
    prev_id = script_id_holder.get("id")
    if prev_id:
        await cdp.send("Page.removeScriptToEvaluateOnNewDocument", {"identifier": prev_id})
    res = await cdp.send(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": (
                f"try{{window.localStorage.setItem('crcs_theme',{json.dumps(theme)});}}"
                f"catch(e){{}}"
                f"if(document.documentElement)document.documentElement.dataset.theme={json.dumps(theme)};"
            )
        },
    )
    script_id_holder["id"] = res.get("identifier")


async def run_js(cdp: CdpClient, expr: str):
    res = await cdp.send("Runtime.evaluate", {"expression": expr, "returnByValue": True})
    return res.get("result", {}).get("value")


async def capture_phase(phase: str, expand_citations: bool = False) -> None:
    out_root = PROJECT_ROOT / "docs" / "screenshots" / "phase16b" / phase
    out_root.mkdir(parents=True, exist_ok=True)
    analyst_token, auditor_token = seed_demo_data()

    next_proc = start_next_server()
    chrome_port = 9228
    user_data_dir = PROJECT_ROOT / f".chrome_phase16b_{phase}"
    if user_data_dir.exists():
        shutil.rmtree(user_data_dir, ignore_errors=True)
    user_data_dir.mkdir(parents=True, exist_ok=True)

    chrome_proc = subprocess.Popen(
        [
            CHROME_PATH,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--no-proxy-server",
            f"--user-data-dir={user_data_dir}",
            f"--remote-debugging-port={chrome_port}",
            "--disable-blink-features=AutomationControlled",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    metrics: list[dict] = []
    ws = None
    cdp: CdpClient | None = None

    try:
        ws_url = None
        for _ in range(30):
            await asyncio.sleep(0.35)
            try:
                with opener.open(f"http://localhost:{chrome_port}/json", timeout=2.0) as resp:
                    tabs = json.loads(resp.read().decode())
                    if tabs:
                        ws_url = tabs[0]["webSocketDebuggerUrl"]
                        break
            except Exception:
                pass
        if not ws_url:
            raise RuntimeError("Could not connect to headless Chrome CDP endpoint.")

        ws = await tornado.websocket.websocket_connect(ws_url, max_message_size=50 * 1024 * 1024)
        cdp = CdpClient(ws)
        await cdp.send("Page.enable")
        await cdp.send("Page.bringToFront")
        await cdp.send("Network.enable")

        script_holder: dict = {}

        for theme in THEMES:
            theme_dir = out_root / theme
            theme_dir.mkdir(parents=True, exist_ok=True)
            await apply_theme(cdp, theme, script_holder)
            print(f"\n=== Capturing phase={phase} theme={theme} ===")

            # 1. Login
            await clear_session_cookie(cdp)
            for label, w, h, mob in VIEWPORTS:
                await navigate_and_wait(cdp, f"{BASE_URL}/login", w, h, mob, 0.55)
                metrics.append(await capture_shot(cdp, theme_dir, f"01_login_{label}px.png", w, h, mob))

            # 2. Empty chat
            await set_session_cookie(cdp, analyst_token)
            for label, w, h, mob in VIEWPORTS:
                await navigate_and_wait(cdp, f"{BASE_URL}/chat/{EMPTY_SESSION_ID}", w, h, mob, 0.65)
                metrics.append(
                    await capture_shot(cdp, theme_dir, f"02_empty_chat_{label}px.png", w, h, mob)
                )

            # 3. Answer + Citations
            for label, w, h, mob in VIEWPORTS:
                await navigate_and_wait(cdp, f"{BASE_URL}/chat/{ANSWER_SESSION_ID}", w, h, mob, 0.75)
                if expand_citations:
                    await run_js(
                        cdp,
                        """(() => {
                            const btns = [...document.querySelectorAll('button')];
                            const src = btns.find(b => b.textContent && b.textContent.includes('Sources'));
                            if (src && src.getAttribute('aria-expanded') === 'false') src.click();
                        })()""",
                    )
                    await asyncio.sleep(0.25)
                    pin_rect = await run_js(
                        cdp,
                        """(() => {
                            const pin = document.querySelector('[data-cite-pin="1"]');
                            if (!pin) return null;
                            const r = pin.getBoundingClientRect();
                            return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
                        })()""",
                    )
                    if isinstance(pin_rect, dict) and pin_rect.get("x") is not None:
                        await cdp.send(
                            "Input.dispatchMouseEvent",
                            {"type": "mouseMoved", "x": pin_rect["x"], "y": pin_rect["y"]},
                        )
                        await run_js(cdp, "document.querySelector('[data-cite-pin=\"1\"]')?.focus()")
                    await asyncio.sleep(0.35)
                metrics.append(
                    await capture_shot(cdp, theme_dir, f"03_answer_citations_{label}px.png", w, h, mob)
                )

            if phase == "after":
                # Live PipelineStepper capture while chat POST is held in flight & cleanly aborted
                await navigate_and_wait(cdp, f"{BASE_URL}/chat/{EMPTY_SESSION_ID}", 1440, 900, False, 0.5)
                await cdp.send("Fetch.enable", {"patterns": [{"urlPattern": "*/api/backend/chat*", "requestStage": "Request"}]})
                paused_id = None
                try:
                    await run_js(
                        cdp,
                        """(() => {
                            const ta = document.querySelector('textarea[aria-label="Compliance question"]');
                            if (!ta) return;
                            const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
                            setter.call(ta, 'What internal governance controls apply to stress testing?');
                            ta.dispatchEvent(new Event('input', { bubbles: true }));
                            setTimeout(() => {
                                const form = ta.closest('form');
                                if (form) form.requestSubmit();
                            }, 60);
                        })()""",
                    )
                    paused_ev = await cdp.wait_event("Fetch.requestPaused", timeout=3.5)
                    if paused_ev:
                        paused_id = paused_ev.get("params", {}).get("requestId")
                    await asyncio.sleep(0.45)
                    metrics.append(
                        await capture_shot(cdp, theme_dir, "09_pipeline_loading_1440px.png", 1440, 900, False)
                    )
                finally:
                    if paused_id:
                        try:
                            await cdp.send(
                                "Fetch.failRequest",
                                {"requestId": paused_id, "errorReason": "Aborted"},
                            )
                        except Exception:
                            pass
                    await cdp.send("Fetch.disable")

            # 4. Documents + Audit as auditor
            await set_session_cookie(cdp, auditor_token)
            for label, w, h, mob in VIEWPORTS:
                await navigate_and_wait(cdp, f"{BASE_URL}/documents", w, h, mob, 0.7)
                metrics.append(
                    await capture_shot(cdp, theme_dir, f"04_documents_{label}px.png", w, h, mob)
                )

            for label, w, h, mob in VIEWPORTS:
                await navigate_and_wait(cdp, f"{BASE_URL}/audit", w, h, mob, 0.7)
                metrics.append(
                    await capture_shot(cdp, theme_dir, f"05_audit_{label}px.png", w, h, mob)
                )

            # 5. 404 + Command Palette + Mobile Drawer
            await set_session_cookie(cdp, analyst_token)
            for label, w, h, mob in VIEWPORTS:
                await navigate_and_wait(cdp, f"{BASE_URL}/nonexistent-compliance-route", w, h, mob, 0.5)
                metrics.append(
                    await capture_shot(cdp, theme_dir, f"06_not_found_{label}px.png", w, h, mob)
                )

            for label, w, h, mob in (("390", 390, 844, True), ("1440", 1440, 900, False)):
                await navigate_and_wait(cdp, f"{BASE_URL}/chat", w, h, mob, 0.55)
                await cdp.send(
                    "Input.dispatchKeyEvent",
                    {
                        "type": "keyDown",
                        "modifiers": 2,
                        "key": "k",
                        "code": "KeyK",
                        "windowsVirtualKeyCode": 75,
                    },
                )
                await cdp.send(
                    "Input.dispatchKeyEvent",
                    {
                        "type": "keyUp",
                        "modifiers": 2,
                        "key": "k",
                        "code": "KeyK",
                        "windowsVirtualKeyCode": 75,
                    },
                )
                await asyncio.sleep(0.32)
                metrics.append(
                    await capture_shot(cdp, theme_dir, f"07_command_palette_{label}px.png", w, h, mob)
                )

            for label, w, h, mob in (("390", 390, 844, True), ("768", 768, 1024, True)):
                await navigate_and_wait(cdp, f"{BASE_URL}/chat", w, h, mob, 0.55)
                await run_js(
                    cdp,
                    "document.querySelector('button[aria-label=\"Open navigation\"]')?.click()",
                )
                await asyncio.sleep(0.32)
                metrics.append(
                    await capture_shot(cdp, theme_dir, f"08_mobile_drawer_{label}px.png", w, h, mob)
                )

        overflows = [m for m in metrics if m.get("overflow")]
        (out_root / "capture_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
        print(f"\nSaved {len(metrics)} screenshots into {out_root}. Horizontal overflows: {len(overflows)}")
    finally:
        if cdp is not None:
            try:
                await cdp.send("Browser.close")
            except Exception:
                pass
            try:
                await cdp.close()
            except Exception:
                pass
        elif ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        kill_tree(chrome_proc)
        kill_tree(next_proc)
        shutil.rmtree(user_data_dir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["before", "after"], required=True)
    parser.add_argument("--expand-citations", action="store_true")
    args = parser.parse_args()
    asyncio.run(capture_phase(args.phase, expand_citations=args.expand_citations))


if __name__ == "__main__":
    main()
