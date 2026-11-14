"""Capture Phase 16 responsive screenshots (before and after redesign) and check layout metrics."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import tornado.websocket  # noqa: E402
from src.core.auth import create_access_token  # noqa: E402
from src.db.connection import get_db_connection  # noqa: E402
from src.db.repository import Repository  # noqa: E402

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
BASE_URL = "http://localhost:3000"

EMPTY_SESSION_ID = "00000000-0000-4000-8000-000000000001"
ANSWER_SESSION_ID = "00000000-0000-4000-8000-000000000010"

VIEWPORTS_BEFORE = [
    ("390", 390, 844, True),
    ("1440", 1440, 900, False),
]

VIEWPORTS_AFTER = [
    ("390", 390, 844, True),
    ("768", 768, 1024, True),
    ("1440", 1440, 900, False),
    ("1920", 1920, 1080, False),
]


class CdpClient:
    """Minimal Tornado-backed CDP client supporting async event waits and Fetch interception."""

    def __init__(self, ws):
        self.ws = ws
        self._req_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self.events: asyncio.Queue[dict] = asyncio.Queue()
        self._reader_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self):
        while True:
            raw = await self.ws.read_message()
            if not raw:
                break
            msg = json.loads(raw)
            if "id" in msg:
                fut = self._pending.pop(msg["id"], None)
                if fut and not fut.done():
                    fut.set_result(msg.get("result", {}))
            elif "method" in msg:
                await self.events.put(msg)

    async def send(self, method: str, params: dict | None = None) -> dict:
        self._req_id += 1
        rid = self._req_id
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        await self.ws.write_message(json.dumps({"id": rid, "method": method, "params": params or {}}))
        return await fut

    async def wait_event(self, method: str, timeout: float = 10.0) -> dict | None:
        deadline = time.monotonic() + timeout
        buffered = []
        found = None
        while time.monotonic() < deadline:
            remaining = max(0.05, deadline - time.monotonic())
            try:
                ev = await asyncio.wait_for(self.events.get(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            if ev.get("method") == method:
                found = ev
                break
            buffered.append(ev)
        for ev in buffered:
            await self.events.put(ev)
        return found

    async def close(self):
        self._reader_task.cancel()
        self.ws.close()


def seed_demo_data() -> tuple[str, str]:
    """Seed deterministic empty and cited-answer sessions for Phase 16 captures."""
    with get_db_connection() as conn:
        repo = Repository(conn)
        analyst = repo.get_user_by_username("analyst_user")
        auditor = repo.get_user_by_username("auditor_user")
        analyst_id = int(analyst["id"]) if analyst else 1
        auditor_id = int(auditor["id"]) if auditor else 3

        # Ensure empty session has no leftover messages
        if repo.get_session(EMPTY_SESSION_ID) is None:
            repo.create_session(EMPTY_SESSION_ID, analyst_id, "Basel III Capital & Liquidity Desk")
        conn.execute("DELETE FROM messages WHERE session_id = ?", (EMPTY_SESSION_ID,))

        # Ensure secondary sessions exist for date grouping in sidebar
        for sid, title, delta in [
            ("00000000-0000-4000-8000-000000000002", "FCA Outsourcing SYSC 8 Review", "-3 days"),
            ("00000000-0000-4000-8000-000000000003", "AML Verification Guidelines 2024", "-14 days"),
        ]:
            if repo.get_session(sid) is None:
                repo.create_session(sid, analyst_id, title)
            conn.execute(f"UPDATE sessions SET updated_at = datetime('now', '{delta}') WHERE id = ?", (sid,))

        # Create/refresh rich cited-answer session from verbatim indexed corpus clauses
        if repo.get_session(ANSWER_SESSION_ID) is None:
            repo.create_session(ANSWER_SESSION_ID, analyst_id, "FCA CASS Client Money Segregation")
        conn.execute("DELETE FROM messages WHERE session_id = ?", (ANSWER_SESSION_ID,))

        repo.add_message(
            session_id=ANSWER_SESSION_ID,
            sender="user",
            content="What are the mandatory segregation and daily reconciliation duties for client money under FCA CASS?",
            user_role="analyst",
        )

        answer_text = (
            "Under the Financial Conduct Authority Client Assets Sourcebook (**CASS**), authorised firms holding "
            "client assets or client money must maintain strict legal and operational separation from firm funds [1].\n\n"
            "### 1. Statutory Segregation Duties\n"
            "Any client money received must be placed promptly into one or more **statutory segregated client bank accounts** "
            "opened with an approved bank [1]. Commingling client money with the firm's general corporate bank accounts is "
            "prohibited [1], and safe custody assets must similarly remain segregated from proprietary assets on the firm's books [2].\n\n"
            "### 2. Daily Reconciliation & Shortfall Funding\n"
            "Firms are required to perform **internal client money reconciliations every business day**, reconciling internal "
            "client ledger balances against external bank account balances [3]. Any discrepancy identified must be investigated "
            "and corrected on the same business day—including funding any client money shortfall directly from the firm's own capital [3]."
        )

        metadata = {
            "route_used": "SINGLE_SEARCH",
            "refused": False,
            "refusal_category": None,
            "citations": [
                {
                    "doc_id": "DOC-FCA-CASS-2024",
                    "doc_name": "FCA Client Assets Sourcebook (CASS)",
                    "doc_title": "FCA Client Assets Sourcebook (CASS)",
                    "section_title": "Chapter 7: Client Money Rules",
                    "heading_path": "FCA CASS > Chapter 7: Client Money Rules",
                    "clause_id": "CASS-7.13.1R",
                    "clause": "CASS-7.13.1R",
                    "page_number": 12,
                    "page": 12,
                    "chunk_id": "DOC-FCA-CASS-2024::c002",
                    "snippet": (
                        "A firm must promptly place any client money received into one or more statutory segregated "
                        "client bank accounts opened with an approved bank. Client money must never be commingled "
                        "with the firm's own general corporate bank accounts."
                    ),
                    "source_url": "https://www.handbook.fca.org.uk/handbook/CASS/7/13.html",
                    "verification_url": "https://www.handbook.fca.org.uk/handbook/CASS/7/13.html",
                    "source_name": "FCA Handbook",
                    "content_origin": "public_regulation",
                    "is_internal": False,
                    "allowed_roles": ["analyst", "manager", "auditor"],
                },
                {
                    "doc_id": "DOC-FCA-CASS-2024",
                    "doc_name": "FCA Client Assets Sourcebook (CASS)",
                    "doc_title": "FCA Client Assets Sourcebook (CASS)",
                    "section_title": "Chapter 6: Custody Rules",
                    "heading_path": "FCA CASS > Chapter 6: Custody Rules",
                    "clause_id": "CASS-6.2.1R",
                    "clause": "CASS-6.2.1R",
                    "page_number": 6,
                    "page": 6,
                    "chunk_id": "DOC-FCA-CASS-2024::c001",
                    "snippet": (
                        "A firm must, when holding safe custody assets belonging to clients, make adequate arrangements "
                        "to safeguard clients' ownership rights and prevent the use of safe custody assets for its own "
                        "account. A firm must ensure that custody assets are segregated from the firm's own proprietary "
                        "assets on its books and records."
                    ),
                    "source_url": "https://www.handbook.fca.org.uk/handbook/CASS/6/2.html",
                    "verification_url": "https://www.handbook.fca.org.uk/handbook/CASS/6/2.html",
                    "source_name": "FCA Handbook",
                    "content_origin": "public_regulation",
                    "is_internal": False,
                    "allowed_roles": ["analyst", "manager", "auditor"],
                },
                {
                    "doc_id": "DOC-FCA-CASS-2024",
                    "doc_name": "FCA Client Assets Sourcebook (CASS)",
                    "doc_title": "FCA Client Assets Sourcebook (CASS)",
                    "section_title": "Chapter 7: Client Money Rules",
                    "heading_path": "FCA CASS > Chapter 7: Client Money Rules",
                    "clause_id": "CASS-7.15.2R",
                    "clause": "CASS-7.15.2R",
                    "page_number": 18,
                    "page": 18,
                    "chunk_id": "DOC-FCA-CASS-2024::c003",
                    "snippet": (
                        "A firm must perform internal client money reconciliations every business day, comparing client "
                        "ledger balances with client bank account balances. Any discrepancy between internal client "
                        "records and physical bank balances must be investigated and corrected on the same business day, "
                        "including funding any client money shortfall from the firm's own capital."
                    ),
                    "source_url": "https://www.handbook.fca.org.uk/handbook/CASS/7/15.html",
                    "verification_url": "https://www.handbook.fca.org.uk/handbook/CASS/7/15.html",
                    "source_name": "FCA Handbook",
                    "content_origin": "public_regulation",
                    "is_internal": False,
                    "allowed_roles": ["analyst", "manager", "auditor"],
                },
            ],
            "router": {
                "enabled": True,
                "route": "SINGLE_SEARCH",
                "confidence": 0.96,
                "sub_questions": [],
                "fallback_used": False,
                "fallback_reason": None,
                "direct_category": None,
                "latency_ms": 14,
                "tokens_used": 68,
            },
            "grader": {
                "enabled": True,
                "path": "direct_pass",
                "relevant_count": 3,
                "ambiguous_count": 0,
                "irrelevant_count": 0,
                "rewrite_used": False,
                "refused": False,
                "refusal_reason": "",
                "grader_calls": 1,
                "tokens_used": 142,
                "latency_ms": 38,
            },
            "retrieval": {
                "total_chunks_retrieved": 8,
                "top_rerank_score": 0.942,
                "retry_count": 0,
                "rewritten_query": None,
            },
            "llm": {
                "profile": "mock",
                "model": "mock",
                "prompt_version": "v1",
                "calls": 2,
                "cached_calls": 0,
                "prompt_tokens": 580,
                "completion_tokens": 210,
                "cached_response": False,
            },
            "spend": {
                "calls_used": 2,
                "calls_limit": 40,
                "tokens_used": 790,
                "tokens_limit": 120000,
                "exhausted": False,
                "scope": "offline",
            },
            "active_layers": ["adaptive_router", "rbac", "heading_path"],
            "response_type": "rag",
            "suggested_follow_ups": [
                "How do FCA COBS best execution duties interact with client order allocation?",
                "What records must be retained for annual CASS audits?",
            ],
            "latency_ms": 184,
            "stage_latencies_ms": {
                "route": 14,
                "retrieve": 48,
                "rerank": 52,
                "grade": 38,
                "answer": 32,
            },
        }

        repo.add_message(
            session_id=ANSWER_SESSION_ID,
            sender="assistant",
            content=answer_text,
            route_used="SINGLE_SEARCH",
            metadata_json=json.dumps(metadata),
            user_role="analyst",
        )
        conn.execute("UPDATE sessions SET updated_at = datetime('now', '-2 hours') WHERE id = ?", (ANSWER_SESSION_ID,))
        conn.execute("UPDATE sessions SET updated_at = datetime('now') WHERE id = ?", (EMPTY_SESSION_ID,))
        conn.commit()

        analyst_token = create_access_token(analyst_id, "analyst_user", "analyst")
        auditor_token = create_access_token(auditor_id, "auditor_user", "auditor")
        return analyst_token, auditor_token


async def set_session_cookie(cdp: CdpClient, token: str):
    await cdp.send(
        "Network.setCookie",
        {
            "name": "crcs_session",
            "value": token,
            "url": BASE_URL,
            "path": "/",
            "httpOnly": True,
            "secure": False,
            "sameSite": "Lax",
        },
    )


async def clear_session_cookie(cdp: CdpClient):
    await cdp.send("Network.deleteCookies", {"name": "crcs_session", "url": BASE_URL})


async def capture_shot(
    cdp: CdpClient,
    out_dir: Path,
    name: str,
    width: int,
    height: int,
    is_mobile: bool,
) -> dict:
    shot = await cdp.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
    b64 = shot.get("data", "")
    out_path = out_dir / name
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if b64:
        out_path.write_bytes(base64.b64decode(b64))
    metrics_res = await cdp.send(
        "Runtime.evaluate",
        {
            "expression": "({ scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth, overflow: document.documentElement.scrollWidth > window.innerWidth })",
            "returnByValue": True,
        },
    )
    val = metrics_res.get("result", {}).get("value", {})
    overflow = bool(val.get("overflow"))
    print(f"  saved {out_path.name} ({width}x{height}) overflow={overflow} sw={val.get('scrollWidth')}/iw={val.get('innerWidth')}")
    return {"name": out_path.name, "width": width, "height": height, "is_mobile": is_mobile, **val}


async def navigate_and_wait(cdp: CdpClient, url: str, width: int, height: int, is_mobile: bool, wait_sec: float = 0.85):
    await cdp.send(
        "Emulation.setDeviceMetricsOverride",
        {
            "width": width,
            "height": height,
            "deviceScaleFactor": 2 if is_mobile else 1,
            "mobile": is_mobile,
        },
    )
    await cdp.send("Page.navigate", {"url": url})
    await asyncio.sleep(wait_sec)


async def run_capture(mode: str):
    out_dir = PROJECT_ROOT / "docs" / "screenshots" / "phase16" / mode
    out_dir.mkdir(parents=True, exist_ok=True)
    viewports = VIEWPORTS_BEFORE if mode == "before" else VIEWPORTS_AFTER

    analyst_token, auditor_token = seed_demo_data()
    chrome_port = 9226
    user_data_dir = PROJECT_ROOT / f".chrome_phase16_{mode}"
    if user_data_dir.exists():
        shutil.rmtree(user_data_dir, ignore_errors=True)
    user_data_dir.mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen(
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
    overflow_results: list[dict] = []

    try:
        ws_url = None
        for _ in range(25):
            await asyncio.sleep(0.4)
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
        await cdp.send("Network.enable")

        try:
            # 1. Login
            print("[1/10] Login screen")
            await clear_session_cookie(cdp)
            for label, w, h, mob in viewports:
                await navigate_and_wait(cdp, f"{BASE_URL}/login", w, h, mob, 0.8)
                overflow_results.append(await capture_shot(cdp, out_dir, f"01_login_{label}px.png", w, h, mob))

            # Authenticate as analyst for Chat, 404, Palette, Drawer, Loading, Error 429
            await set_session_cookie(cdp, analyst_token)

            # 2. Empty chat
            print("[2/10] Empty chat")
            for label, w, h, mob in viewports:
                await navigate_and_wait(cdp, f"{BASE_URL}/chat/{EMPTY_SESSION_ID}", w, h, mob, 0.9)
                overflow_results.append(await capture_shot(cdp, out_dir, f"02_empty_chat_{label}px.png", w, h, mob))

            # 3. Answer with citations (open citations panel cleanly if collapsed)
            print("[3/10] Answer with citations")
            for label, w, h, mob in viewports:
                await navigate_and_wait(cdp, f"{BASE_URL}/chat/{ANSWER_SESSION_ID}", w, h, mob, 0.9)
                await cdp.send(
                    "Runtime.evaluate",
                    {
                        "expression": """
                        (() => {
                          const triggers = Array.from(document.querySelectorAll('button'));
                          const srcBtn = triggers.find(b => /Sources/i.test(b.textContent || ''));
                          if (srcBtn && srcBtn.getAttribute('aria-expanded') === 'false') {
                            srcBtn.click();
                          }
                        })()
                        """
                    },
                )
                await asyncio.sleep(0.35)
                overflow_results.append(await capture_shot(cdp, out_dir, f"03_answer_citations_{label}px.png", w, h, mob))

            # 4 & 5. Loading state & Error 429 state via Fetch interception on /api/backend/chat/query
            print("[4/10 & 5/10] Loading state and Error 429")
            await cdp.send(
                "Fetch.enable",
                {"patterns": [{"urlPattern": "*://localhost:3000/api/backend/chat/query*", "requestStage": "Request"}]},
            )
            for label, w, h, mob in viewports:
                await navigate_and_wait(cdp, f"{BASE_URL}/chat/{EMPTY_SESSION_ID}", w, h, mob, 0.8)
                # Clear stale events
                while not cdp.events.empty():
                    await cdp.events.get()

                # Trigger first starter card or submit prompt
                await cdp.send(
                    "Runtime.evaluate",
                    {
                        "expression": """
                        (() => {
                          const ta = document.querySelector('textarea');
                          if (ta) {
                            const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
                            setter.call(ta, 'What daily client money reconciliation obligations apply under FCA CASS?');
                            ta.dispatchEvent(new Event('input', { bubbles: true }));
                          }
                        })()
                        """
                    },
                )
                await asyncio.sleep(0.2)
                await cdp.send(
                    "Runtime.evaluate",
                    {
                        "expression": """
                        (() => {
                          const btn = document.querySelector('button[aria-label*="Send"], button[type="submit"]');
                          if (btn) btn.click();
                        })()
                        """
                    },
                )
                ev = await cdp.wait_event("Fetch.requestPaused", timeout=5.0)
                await asyncio.sleep(1.3)  # Let pipeline stage tick to stage 1
                overflow_results.append(await capture_shot(cdp, out_dir, f"04_loading_{label}px.png", w, h, mob))

                if ev:
                    req_id = ev["params"]["requestId"]
                    err_body = json.dumps({
                        "error": {
                            "code": "RATE_OR_SPEND_LIMIT",
                            "message": "Spend guard triggered: session token cap reached (12,000 / 12,000 tokens). Start a new run or wait before retrying.",
                        }
                    })
                    await cdp.send(
                        "Fetch.fulfillRequest",
                        {
                            "requestId": req_id,
                            "responseCode": 429,
                            "responseHeaders": [{"name": "Content-Type", "value": "application/json"}],
                            "body": base64.b64encode(err_body.encode()).decode(),
                        },
                    )
                    await asyncio.sleep(0.5)
                overflow_results.append(await capture_shot(cdp, out_dir, f"05_error_429_{label}px.png", w, h, mob))
            await cdp.send("Fetch.disable")

            # 8. Not found (404)
            print("[8/10] 404 Not Found")
            for label, w, h, mob in viewports:
                await navigate_and_wait(cdp, f"{BASE_URL}/non-existent-compliance-route", w, h, mob, 0.7)
                overflow_results.append(await capture_shot(cdp, out_dir, f"08_not_found_{label}px.png", w, h, mob))

            # 9. Command Palette
            print("[9/10] Command Palette")
            for label, w, h, mob in viewports:
                await navigate_and_wait(cdp, f"{BASE_URL}/chat/{EMPTY_SESSION_ID}", w, h, mob, 1.0)
                await cdp.send(
                    "Input.dispatchKeyEvent",
                    {"type": "keyDown", "modifiers": 2, "key": "k", "code": "KeyK", "windowsVirtualKeyCode": 75},
                )
                await cdp.send(
                    "Input.dispatchKeyEvent",
                    {"type": "keyUp", "modifiers": 2, "key": "k", "code": "KeyK", "windowsVirtualKeyCode": 75},
                )
                await asyncio.sleep(0.4)
                overflow_results.append(await capture_shot(cdp, out_dir, f"09_command_palette_{label}px.png", w, h, mob))

            # 10. Mobile Drawer (390/768) & Sidebar System / Collapsed State (1440/1920)
            print("[10/10] Mobile Drawer / Desktop Sidebar state")
            for label, w, h, mob in viewports:
                await navigate_and_wait(cdp, f"{BASE_URL}/chat/{EMPTY_SESSION_ID}", w, h, mob, 0.8)
                if w < 1024:
                    await cdp.send(
                        "Runtime.evaluate",
                        {"expression": "document.querySelector('button[aria-label=\"Open navigation\"]')?.click()"},
                    )
                else:
                    await cdp.send(
                        "Runtime.evaluate",
                        {"expression": "document.querySelector('button[aria-label*=\"System\"]')?.click()"},
                    )
                await asyncio.sleep(0.4)
                overflow_results.append(await capture_shot(cdp, out_dir, f"10_mobile_drawer_{label}px.png", w, h, mob))

            # Authenticate as auditor for Documents and Audit views
            await set_session_cookie(cdp, auditor_token)

            # 6. Documents
            print("[6/10] Documents catalog")
            for label, w, h, mob in viewports:
                await navigate_and_wait(cdp, f"{BASE_URL}/documents", w, h, mob, 0.85)
                overflow_results.append(await capture_shot(cdp, out_dir, f"06_documents_{label}px.png", w, h, mob))

            # 7. Audit
            print("[7/10] Audit log & RBAC summary")
            for label, w, h, mob in viewports:
                await navigate_and_wait(cdp, f"{BASE_URL}/audit", w, h, mob, 0.85)
                overflow_results.append(await capture_shot(cdp, out_dir, f"07_audit_{label}px.png", w, h, mob))

        finally:
            await cdp.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(user_data_dir, ignore_errors=True)

    summary_path = out_dir / "capture_metrics.json"
    summary_path.write_text(json.dumps(overflow_results, indent=2), encoding="utf-8")
    overflows = [r for r in overflow_results if r.get("overflow")]
    print(f"\nCaptured {len(overflow_results)} screenshots in {out_dir}. Horizontal overflows: {len(overflows)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["before", "after"], default="before")
    args = parser.parse_args()
    asyncio.run(run_capture(args.mode))
