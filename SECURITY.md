# Security Policy

## 1. Supported Scope

This project is an academic Final Year Project (BSc COM6301) demonstrating security hardening in Retrieval-Augmented Generation (RAG) for banking compliance.

Security patches and bug fixes are maintained for the latest release on the default branch.

## 2. Core Security Invariants

The architecture enforces the following non-negotiable security controls:
1. **Server-Side RBAC Filtering:** Role-based access control is enforced strictly at the database / vector query engine level (`allowed_roles` payload filters in Qdrant and BM25). Filter rules are never trusted to the client, UI, or post-filtering.
2. **Canary Token Isolation:** Unique canary tokens are planted in restricted documents. The output guard intercepts answers, citations, titles, and traces, neutralizing unauthorized leakage.
3. **Cryptographic Audit Chain:** Every entry in `audit_log` stores `prev_hash` and `entry_hash = SHA-256(prev_hash + fields)`. Any modification or deletion is detected by `scripts/verify_audit.py`.
4. **Token-Derived Identity:** User roles are loaded strictly from the signed HMAC-SHA256 JWT token verified against SQLite. Client-supplied headers or body fields cannot elevate permissions.
5. **Prompt Injection Boundaries:** Document passages are wrapped in XML delimiters (`<authoritative_documents>`) and treated strictly as untrusted data.
6. **Zero Hardcoded Secrets:** Credentials, API keys, and filesystem paths resolve exclusively from `.env`. Tracked files are scanned via `scripts/scan_secrets.py`.

## 3. Reporting a Vulnerability

If you discover a security vulnerability or access control bypass:
- Please report it directly to the repository maintainer via private security advisory or email: `hashir.khan@bank.local` (or student contact).
- Do NOT open a public GitHub issue disclosing confidential exploit payloads.
- We aim to acknowledge reports within 48 hours and provide a fix within 7 business days.

