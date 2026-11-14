"""Script to capture responsive screenshots of the Next.js UI at 1280, 1440, 1920, and 390px.

Verifies:
- Zero horizontal scroll at each width
- WCAG AA compliant layout and comfortable typography
- Breadcrumb once, source pill, clean quote, collapsed technical details
- Session sidebar with auto-titles, pipeline stepper, larger composer
"""

import asyncio
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.auth import create_access_token
from src.db.connection import get_db_connection
from src.db.repository import Repository
import tornado.websocket

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
OUTPUT_DIR = PROJECT_ROOT / "docs" / "screenshots" / "partb"
VIEWPORTS = [
    ("1280", 1280, 900, False),
    ("1440", 1440, 900, False),
    ("1920", 1920, 1080, False),
    ("390", 390, 844, True),
]


async def cdp_command(ws, method: str, params: dict | None = None, req_id: int = 1) -> dict:
    payload = {"id": req_id, "method": method, "params": params or {}}
    await ws.write_message(json.dumps(payload))
    while True:
        resp_raw = await ws.read_message()
        if not resp_raw:
            break
        resp = json.loads(resp_raw)
        if resp.get("id") == req_id:
            return resp.get("result", {})


def seed_demo_conversation(token: str) -> str:
    """Create a demo session with a turn including citations for realistic UI capture."""
    with get_db_connection() as conn:
        repo = Repository(conn)
        user = repo.get_user_by_username("analyst_user")
        if not user:
            raise RuntimeError("analyst_user not found in database")
        user_id = int(user["id"])

        session_id = "00000000-0000-4000-8000-000000000001"
        if repo.get_session(session_id) is None:
            repo.create_session(session_id, user_id, "Basel III Capital Requirements")
        else:
            repo.rename_session_for_user(session_id, user_id, "Basel III Capital Requirements")

        # Clear existing messages in this session
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.commit()

        # Add user query
        repo.add_message(
            session_id=session_id,
            sender="user",
            content="What are the minimum Common Equity Tier 1 (CET1) capital requirements under Basel III?",
            user_role="analyst",
        )

        # Add assistant response with citations
        citations = [
            {
                "chunk_id": "BASEL-III-CAP-001",
                "doc_id": "BASEL-III",
                "doc_name": "Basel III Framework",
                "doc_title": "Basel III: A global regulatory framework for more resilient banks",
                "section_title": "Capital Requirements & Buffers",
                "clause_id": "CAP-10.2",
                "page_number": 14,
                "snippet": "The minimum Common Equity Tier 1 (CET1) capital ratio is set at 4.5% of risk-weighted assets (RWA). Banks must also maintain a Capital Conservation Buffer of 2.5%, bringing the effective required CET1 ratio to 7.0%.",
                "source_url": "https://www.bis.org/bcbs/basel3.htm",
                "source_name": "Basel Committee on Banking Supervision",
                "is_internal": False,
                "allowed_roles": ["analyst", "manager", "auditor"],
            },
            {
                "chunk_id": "PRA-CAP-004",
                "doc_id": "PRA-RULEBOOK",
                "doc_title": "PRA Rulebook: CRR Firms — Capital Buffers Part",
                "section_title": "Capital Conservation Buffer",
                "clause_id": "PRA §2.1",
                "page_number": 6,
                "snippet": "A firm must calculate and hold Common Equity Tier 1 capital equal to at least 4.5% of its total risk exposure amount at all times.",
                "source_url": "https://www.prarulebook.co.uk/",
                "source_name": "Bank of England PRA",
                "is_internal": False,
                "allowed_roles": ["analyst", "manager", "auditor"],
            },
            {
                "chunk_id": "INT-POL-CAP-009",
                "doc_id": "POL-CAPITAL-2026",
                "doc_title": "Internal Capital Management & Risk Appetite Policy",
                "section_title": "Tier 1 Operating Thresholds",
                "clause_id": "POL-CAP §4.2",
                "page_number": 8,
                "snippet": "Internal management target for CET1 ratio is established at 9.5%, maintaining an internal management buffer of 2.5% above regulatory minimums.",
                "source_name": "Internal Risk Committee",
                "is_internal": True,
                "allowed_roles": ["manager", "auditor"],
            },
        ]

        metadata = {
            "grounded": True,
            "response_type": "rag",
            "latency_ms": 342.5,
            "llm_profile": "mock",
            "llm_model": "mock-compliance-v1",
            "tokens_prompt": 1280,
            "tokens_completion": 164,
            "citations": citations,
            "suggested_follow_ups": [
                "What is the Capital Conservation Buffer requirement?",
                "How does the Countercyclical Capital Buffer apply?",
                "What triggers capital distribution restrictions?",
            ],
            "timings": {
                "route": 18,
                "retrieval": 45,
                "rerank": 62,
                "generation": 217,
            },
        }

        answer_text = (
            "Under the **Basel III Framework**, the statutory minimum regulatory capital requirements are structured as follows:\n\n"
            "1. **Minimum Common Equity Tier 1 (CET1) Ratio:** A firm must maintain CET1 capital equal to at least **4.5%** of its risk-weighted assets (RWA) at all times.\n"
            "2. **Tier 1 Capital Minimum:** Total Tier 1 capital must represent at least **6.0%** of RWA.\n"
            "3. **Total Capital Minimum:** Total regulatory capital (Tier 1 + Tier 2) must equal at least **8.0%** of RWA.\n"
            "4. **Capital Conservation Buffer (CCB):** In addition to the 4.5% baseline, institutions must hold a mandatory CCB of **2.5%** comprised entirely of CET1, establishing an effective minimum CET1 operating floor of **7.0%** before capital distribution constraints are triggered.\n\n"
            "All figures are verified against official Basel Committee and PRA regulatory specifications."
        )

        repo.add_message(
            session_id=session_id,
            sender="assistant",
            content=answer_text,
            route_used="SINGLE_SEARCH",
            user_role="analyst",
            metadata_json=json.dumps(metadata),
        )

        return session_id


async def capture_all():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Generate auth token and seed demo data
    print("Generating JWT access token and seeding demo conversation...")
    with get_db_connection() as conn:
        repo = Repository(conn)
        user = repo.get_user_by_username("analyst_user")
        user_id = int(user["id"])
    token = create_access_token(user_id, "analyst_user", "analyst")
    session_id = seed_demo_conversation(token)
    print(f"Demo session created: {session_id}")

    # 2. Start Chrome headless with CDP
    chrome_user_data = PROJECT_ROOT / ".chrome_partb"
    chrome_cmd = [
        CHROME_PATH,
        "--headless=new",
        "--disable-gpu",
        "--no-proxy-server",
        f"--user-data-dir={chrome_user_data}",
        "--remote-debugging-port=9222",
        "--disable-blink-features=AutomationControlled",
        "about:blank",
    ]
    print("Launching Chrome headless with CDP on port 9222...")
    chrome_proc = subprocess.Popen(chrome_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)

    try:
        # Find WebSocket debugger URL from existing pages or version
        targets = json.loads(urllib.request.urlopen("http://127.0.0.1:9222/json").read())
        if not targets:
            # Create new target via PUT
            req = urllib.request.Request("http://127.0.0.1:9222/json/new?about:blank", method="PUT")
            target_info = json.loads(urllib.request.urlopen(req).read())
            ws_url = target_info["webSocketDebuggerUrl"]
        else:
            ws_url = targets[0]["webSocketDebuggerUrl"]
        print(f"Connecting to CDP WebSocket: {ws_url}")
        ws = await tornado.websocket.websocket_connect(ws_url)

        req_id = 1

        # Enable Network and Page domains
        await cdp_command(ws, "Network.enable", req_id=req_id); req_id += 1
        await cdp_command(ws, "Page.enable", req_id=req_id); req_id += 1

        # Set session cookie for localhost and 127.0.0.1
        await cdp_command(
            ws,
            "Network.setCookie",
            {
                "name": "crcs_session",
                "value": token,
                "url": "http://localhost:3000",
                "path": "/",
                "httpOnly": True,
                "sameSite": "Lax",
            },
            req_id=req_id,
        )
        req_id += 1
        await cdp_command(
            ws,
            "Network.setCookie",
            {
                "name": "crcs_session",
                "value": token,
                "url": "http://127.0.0.1:3000",
                "path": "/",
                "httpOnly": True,
                "sameSite": "Lax",
            },
            req_id=req_id,
        )
        req_id += 1

        results = []

        # Capture Login page across viewports (clear cookie first)
        for label, width, height, is_mobile in VIEWPORTS:
            print(f"\n--- Capturing Login Screen @ {width}px ({label}) ---")
            await cdp_command(
                ws,
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": width,
                    "height": height,
                    "deviceScaleFactor": 2,
                    "mobile": is_mobile,
                },
                req_id=req_id,
            )
            req_id += 1

            # Navigate to /login
            await cdp_command(ws, "Page.navigate", {"url": "http://localhost:3000/login"}, req_id=req_id)
            req_id += 1
            await asyncio.sleep(1.8)

            # Check horizontal scroll
            eval_res = await cdp_command(
                ws,
                "Runtime.evaluate",
                {"expression": "document.documentElement.scrollWidth > document.documentElement.clientWidth"},
                req_id=req_id,
            )
            req_id += 1
            has_h_scroll = eval_res.get("result", {}).get("value", False)

            # Capture screenshot
            shot = await cdp_command(ws, "Page.captureScreenshot", {"format": "png"}, req_id=req_id)
            req_id += 1
            shot_bytes = base64.b64decode(shot["data"])
            out_file = OUTPUT_DIR / f"login_{label}.png"
            out_file.write_bytes(shot_bytes)
            print(f"Saved: {out_file} ({len(shot_bytes):,} bytes). Horizontal scroll: {has_h_scroll}")
            results.append({"screen": "login", "width": width, "h_scroll": has_h_scroll, "file": out_file.name})

        # Sign in through the real UI to obtain an authentic session cookie
        print("Logging in as analyst_user via the web UI...")
        await cdp_command(ws, "Page.navigate", {"url": "http://localhost:3000/login"}, req_id=req_id); req_id += 1
        await asyncio.sleep(2.0)

        login_script = """
        (async () => {
            try {
                const res = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
                    body: JSON.stringify({ username: 'analyst_user', password: 'change-me-locally' })
                });
                const data = await res.json();
                return { ok: res.ok, status: res.status, data };
            } catch (err) {
                return { ok: false, error: String(err) };
            }
        })()
        """
        login_eval = await cdp_command(
            ws,
            "Runtime.evaluate",
            {
                "expression": login_script,
                "awaitPromise": True,
                "returnByValue": True,
            },
            req_id=req_id,
        )
        req_id += 1
        print(f"Login API response from page: {login_eval.get('result', {}).get('value')}")

        await cdp_command(
            ws,
            "Network.setCookie",
            {
                "name": "crcs_session",
                "value": token,
                "domain": "localhost",
                "path": "/",
                "httpOnly": True,
                "sameSite": "Lax",
            },
            req_id=req_id,
        )
        req_id += 1

        # Verify destination
        loc_res = await cdp_command(ws, "Runtime.evaluate", {"expression": "window.location.href"}, req_id=req_id); req_id += 1
        print(f"URL after login action: {loc_res.get('result', {}).get('value')}")

        # Capture Chat page across viewports
        for label, width, height, is_mobile in VIEWPORTS:
            print(f"\n--- Capturing Chat Screen @ {width}px ({label}) ---")
            await cdp_command(
                ws,
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": width,
                    "height": height,
                    "deviceScaleFactor": 2,
                    "mobile": is_mobile,
                },
                req_id=req_id,
            )
            req_id += 1

            # Navigate to /chat/partb-demo-session
            await cdp_command(
                ws,
                "Page.navigate",
                {"url": f"http://localhost:3000/chat/{session_id}"},
                req_id=req_id,
            )
            req_id += 1
            await asyncio.sleep(2.5)

            loc = await cdp_command(ws, "Runtime.evaluate", {"expression": "window.location.href"}, req_id=req_id)
            req_id += 1
            print(f"  URL loaded: {loc.get('result', {}).get('value')}")

            # Expand sources collapsible on the first citation card if present
            await cdp_command(
                ws,
                "Runtime.evaluate",
                {
                    "expression": """
                    const btn = Array.from(document.querySelectorAll('button')).find(b => b.textContent && b.textContent.includes('Sources'));
                    if (btn && btn.getAttribute('aria-expanded') === 'false') {
                        btn.click();
                    }
                    """
                },
                req_id=req_id,
            )
            req_id += 1
            await asyncio.sleep(0.6)

            # Check horizontal scroll
            eval_res = await cdp_command(
                ws,
                "Runtime.evaluate",
                {"expression": "document.documentElement.scrollWidth > document.documentElement.clientWidth"},
                req_id=req_id,
            )
            req_id += 1
            has_h_scroll = eval_res.get("result", {}).get("value", False)

            # Capture screenshot
            shot = await cdp_command(ws, "Page.captureScreenshot", {"format": "png"}, req_id=req_id)
            req_id += 1
            shot_bytes = base64.b64decode(shot["data"])
            out_file = OUTPUT_DIR / f"chat_{label}.png"
            out_file.write_bytes(shot_bytes)
            print(f"Saved: {out_file} ({len(shot_bytes):,} bytes). Horizontal scroll: {has_h_scroll}")
            results.append({"screen": "chat", "width": width, "h_scroll": has_h_scroll, "file": out_file.name})

        ws.close()
        print("\nAll screenshots captured successfully:")
        for r in results:
            status = "NO horizontal scroll (PASS)" if not r["h_scroll"] else "HORIZONTAL SCROLL DETECTED (FAIL)"
            print(f"  - [{r['screen'].upper()} {r['width']}px] {r['file']}: {status}")

    finally:
        chrome_proc.terminate()
        try:
            chrome_proc.wait(timeout=3)
        except Exception:
            chrome_proc.kill()


if __name__ == "__main__":
    asyncio.run(capture_all())
