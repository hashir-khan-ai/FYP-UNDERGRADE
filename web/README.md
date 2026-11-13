# Compliance Desk — Next.js Workspace

Local-first web client for the Enterprise Banking Regulatory Compliance RAG
Assistant. It talks to the existing FastAPI backend and keeps the Streamlit app
(`src/ui/app.py`) fully runnable as the legacy client.

## Stack

| Concern | Choice |
| :--- | :--- |
| Framework | Next.js `16.4.6` App Router, React `19.3.1`, TypeScript `5.9.3` |
| Styling | Tailwind CSS `4.3.5` with semantic CSS variables in `styles/tokens.css` |
| Primitives | Radix UI (`dialog`, `dropdown-menu`, `collapsible`, `tooltip`) |
| Motion | CSS transitions/keyframes + Framer Motion dependency (not required for core flows) |
| Icons | `lucide-react` |
| Markdown | `react-markdown` + `remark-gfm` (raw HTML disabled) |
| Toasts | `sonner` |
| Tests | Vitest + Testing Library + jsdom |

No web fonts, CDNs, analytics, telemetry or remote images are used at runtime.

## Run locally

```powershell
# Terminal 1 — FastAPI backend
$env:HF_HUB_OFFLINE="1"
.\.venv\Scripts\python.exe -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000

# Terminal 2 — web client
cd web
npm install
npm run dev          # http://localhost:3000
```

Environment variables for the web process:

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `BACKEND_API_URL` | `http://127.0.0.1:8000` | Server-side FastAPI base URL used by Server Components and the BFF |
| `COOKIE_SECURE` | `false` | Set `true` only when serving over HTTPS |

The browser never receives `BACKEND_API_URL`; it only calls same-origin routes.

## Architecture

```
Browser
  │  same-origin fetch, httpOnly cookie
  ▼
Next.js BFF
  ├── /api/auth/login        → FastAPI /api/v1/auth/login, sets crcs_session
  ├── /api/auth/logout       → revokes upstream token, clears cookie
  └── /api/backend/[...path] → explicit allowlist, attaches Bearer token
  ▼
FastAPI (RAG, RBAC, citation verification, audit)
```

- The JWT is stored in an `httpOnly`, `SameSite=Lax` cookie (`crcs_session`).
  It is never placed in a URL, local storage, client state or logs.
- The proxy is not an open relay. Only allowlisted paths/methods are forwarded;
  session identifiers must match a UUID pattern.
- Server Components perform initial reads (user, sessions, messages, audit,
  documents). Client Components mutate through the BFF.

### Routes

| Route | Purpose |
| :--- | :--- |
| `/login` | Persona quick-fill (username only) and sign-in |
| `/chat` | Redirects to the newest session, or shows the no-session landing |
| `/chat/[sessionId]` | Conversation, mode controls, citations, pipeline details |
| `/documents` | Role-filtered catalog; upload for manager/auditor |
| `/audit` | Auditor-only sanitised audit summaries |

## Security invariants

1. **RBAC is server-side.** The UI never sends a role. Retrieval filtering happens
   inside Qdrant/BM25 before generation. Hiding the audit nav from non-auditors is
   UX only; the API still enforces the role.
2. **Citation links are safe.** Only absolute `http(s)` URLs from trusted metadata
   are rendered. `javascript:`, `data:`, relative, localhost and credential-bearing
   URLs are rejected. Internal/synthetic documents never receive an external link.
3. **Prompt injection remains untrusted data.** The UI only displays the backend's
   answer; it does not execute document content. Advanced details state the XML
   boundary explicitly.
4. **No secret material in the client.** Persona quick-fill fills the username only.
   The synthetic demo password is deliberately not embedded in client code.
5. **Errors are sanitised.** The API client maps statuses/codes to stable messages
   and truncates upstream text to 400 characters.

## Verification

```powershell
cd web
npm run typecheck
npm test
npm run build
```

Backend checks (from the repository root):

```powershell
$env:HF_HUB_OFFLINE="1"
.\.venv\Scripts\python.exe -m pytest -q -m "not slow"
.\.venv\Scripts\python.exe scripts/leakage_check.py
```

See `../docs/WEB_UI_QA.md` for the full checklist and recorded results.

## Known limits

- The backend returns a complete answer synchronously. The “progressive” reveal is
  a presentation effect, not token streaming. It is documented as such in the UI
  code and in `docs/WEB_UI_MIGRATION.md`.
- The UI supports the mock/dev/demo profiles without code changes, but live paid
  profiles have not been exercised in this workspace.
- No browser E2E tool (Playwright) is installed; coverage is Server Component
  HTTP smoke tests plus Vitest component/unit tests.
