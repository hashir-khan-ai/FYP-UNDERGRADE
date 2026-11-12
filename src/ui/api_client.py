"""HTTP client boundary for the Phase 6B Streamlit UI.

The UI communicates with the backend exclusively through :class:`ComplianceAPIClient`.
It never imports database, vector store, or LLM client modules directly, and it
never supplies a role in request payloads — the user's role is always derived
by the server from the bearer token.
"""

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class UIApiError(Exception):
    """Sanitized error returned by the backend API or network layer."""

    status_code: int
    code: str
    message: str

    def __str__(self) -> str:
        return f"[{self.code}] {self.message} (HTTP {self.status_code})"


def parse_api_error(response: httpx.Response) -> UIApiError:
    """Convert an error HTTP response into a sanitized :class:`UIApiError`."""
    status_code = response.status_code
    default_code = {
        400: "BAD_REQUEST",
        401: "UNAUTHENTICATED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        422: "VALIDATION_ERROR",
        429: "RATE_OR_SPEND_LIMIT",
        503: "SERVICE_UNAVAILABLE",
    }.get(status_code, "API_ERROR")
    default_message = {
        401: "Your session has expired or credentials were invalid. Please sign in again.",
        403: "Your role is not permitted to perform this action.",
        404: "The requested resource was not found.",
        429: "Rate limit or LLM spend cap reached. Please wait or reset the run cap.",
        503: "The upstream LLM service is currently unavailable.",
    }.get(status_code, "The request could not be completed.")

    try:
        payload = response.json()
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            err = payload["error"]
            code = str(err.get("code") or default_code)
            msg = str(err.get("message") or default_message)
            return UIApiError(status_code=status_code, code=code, message=msg)
    except Exception:
        pass

    return UIApiError(status_code=status_code, code=default_code, message=default_message)


def is_refusal_response(chat_payload: dict[str, Any]) -> bool:
    """Return True when a chat response represents a compliance/evidence refusal."""
    if chat_payload.get("refusal_category") or chat_payload.get("refusal"):
        return True
    grader = chat_payload.get("grader")
    if isinstance(grader, dict) and grader.get("refused"):
        return True
    answer = str(chat_payload.get("answer") or "").strip().lower()
    return "can't find that in the documents available to your role" in answer


def profile_badge_meta(profile: str) -> dict[str, str]:
    """Return display label and colour tokens for the active LLM profile badge."""
    normalized = (profile or "mock").strip().lower()
    if normalized == "demo":
        return {
            "label": "DEMO LIVE",
            "bg": "#FF5F00",
            "fg": "#1C1D20",
            "border": "#FF5F00",
        }
    if normalized == "dev":
        return {
            "label": "DEV PROVIDER",
            "bg": "#1C1D20",
            "fg": "#FF5F00",
            "border": "#FF5F00",
        }
    return {
        "label": "OFFLINE MOCK",
        "bg": "#5A6068",
        "fg": "#F1F3F4",
        "border": "#5A6068",
    }


class ComplianceAPIClient:
    """Thin, synchronous HTTP client for the FastAPI compliance backend."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport

    def _headers(self, token: str | None = None) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport) as client:
                response = client.request(
                    method=method,
                    url=url,
                    headers=self._headers(token),
                    json=json_body,
                    params=params,
                )
        except httpx.RequestError:
            raise UIApiError(
                status_code=503,
                code="BACKEND_UNREACHABLE",
                message="Cannot reach the compliance API server on localhost.",
            ) from None

        if response.status_code >= 400:
            raise parse_api_error(response)

        if not response.content:
            return {}
        return response.json()

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------
    def login(self, username: str, password: str) -> dict[str, Any]:
        """Authenticate and return ``{"access_token", "token_type", "user"}``."""
        return self._request(
            "POST",
            "/api/v1/auth/login",
            json_body={"username": username.strip(), "password": password},
        )

    def logout(self, token: str) -> dict[str, Any]:
        """Revoke the current bearer token on the server."""
        return self._request("POST", "/api/v1/auth/logout", token=token)

    def get_me(self, token: str) -> dict[str, Any]:
        """Fetch the authenticated user's profile and server-verified role."""
        return self._request("GET", "/api/v1/auth/me", token=token)

    def list_demo_users(self) -> list[dict[str, Any]]:
        """List synthetic demo accounts when enabled in development/test."""
        try:
            res = self._request("GET", "/api/v1/auth/users")
            return res if isinstance(res, list) else []
        except UIApiError:
            return []

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------
    def list_sessions(self, token: str) -> list[dict[str, Any]]:
        """Return the authenticated user's sessions."""
        data = self._request("GET", "/api/v1/sessions", token=token)
        return list(data.get("sessions", [])) if isinstance(data, dict) else []

    def create_session(self, token: str, title: str | None = None) -> dict[str, Any]:
        """Create a new chat session owned by the authenticated user."""
        body: dict[str, Any] = {}
        if title and title.strip():
            body["title"] = title.strip()
        return self._request("POST", "/api/v1/sessions", token=token, json_body=body)

    def get_session_messages(self, token: str, session_id: str) -> list[dict[str, Any]]:
        """Return ordered message history for a session owned by the user."""
        data = self._request(
            "GET",
            f"/api/v1/sessions/{session_id}/messages",
            token=token,
        )
        return list(data.get("messages", [])) if isinstance(data, dict) else []

    def delete_session(self, token: str, session_id: str) -> dict[str, Any]:
        """Delete a session owned by the authenticated user."""
        return self._request("DELETE", f"/api/v1/sessions/{session_id}", token=token)

    # ------------------------------------------------------------------
    # Chat (RBAC-scoped RAG)
    # ------------------------------------------------------------------
    def ask_chat_query(self, token: str, session_id: str, query: str) -> dict[str, Any]:
        """Submit a question to the RBAC-scoped RAG pipeline."""
        return self._request(
            "POST",
            "/api/v1/chat/query",
            token=token,
            json_body={"session_id": session_id, "query": query},
        )

    # ------------------------------------------------------------------
    # Auditor Summary & Admin Telemetry
    # ------------------------------------------------------------------
    def get_audit_logs(
        self,
        token: str,
        limit: int = 50,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch sanitized audit summaries (restricted to the auditor role)."""
        params: dict[str, Any] = {"limit": limit}
        if user_id is not None:
            params["user_id"] = user_id
        data = self._request("GET", "/api/v1/audit/logs", token=token, params=params)
        return data if isinstance(data, list) else []

    def get_admin_config(self, token: str) -> dict[str, Any]:
        """Fetch active profile, model, layer flags, and spend caps."""
        return self._request("GET", "/api/v1/admin/config", token=token)

    def get_health(self) -> dict[str, Any]:
        """Fetch public health and vector store status."""
        return self._request("GET", "/health")


__all__ = [
    "ComplianceAPIClient",
    "UIApiError",
    "is_refusal_response",
    "parse_api_error",
    "profile_badge_meta",
]

