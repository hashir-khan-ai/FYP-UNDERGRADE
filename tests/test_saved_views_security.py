"""Security and isolation tests for Saved Views.

CRITICAL SECURITY CONTRACT:
1. Saved views are strictly isolated per user account. User A cannot read, update,
   or delete User B's view by ID.
2. Unauthenticated requests to saved view endpoints must immediately fail with 401.
3. Client-stored filters (e.g. attempting to specify higher privilege roles like 'auditor')
   must never widen retrieval or authorization beyond the authenticated caller's role.
"""

from __future__ import annotations

import json
from fastapi.testclient import TestClient

from src.api.main import app
from src.core.auth import create_access_token


client = TestClient(app)


def test_saved_views_unauthenticated_requests_fail() -> None:
    """Unauthenticated requests to all saved view endpoints return 401."""
    # List views
    res = client.get("/api/v1/views")
    assert res.status_code == 401

    # Get single view
    res = client.get("/api/v1/views/view_test123")
    assert res.status_code == 401

    # Create view
    res = client.post(
        "/api/v1/views",
        json={"view_name": "Test View", "page": "documents", "filters_json": "{}"},
    )
    assert res.status_code == 401

    # Update view
    res = client.put(
        "/api/v1/views/view_test123",
        json={"view_name": "Updated", "filters_json": "{}"},
    )
    assert res.status_code == 401

    # Delete view
    res = client.delete("/api/v1/views/view_test123")
    assert res.status_code == 401


def test_user_cannot_read_another_users_view(auth_headers, seeded_auth_users) -> None:
    """User B cannot read User A's view by ID or list it in catalog."""
    headers_a = auth_headers("analyst")
    headers_b = auth_headers("manager")

    # User A creates a saved view
    res_create = client.post(
        "/api/v1/views",
        headers=headers_a,
        json={
            "view_name": "Analyst Confidential View",
            "page": "documents",
            "filters_json": json.dumps({"search": "aml"}),
        },
    )
    assert res_create.status_code == 200
    view_id = res_create.json()["id"]

    # User A can read it
    res_a_read = client.get(f"/api/v1/views/{view_id}", headers=headers_a)
    assert res_a_read.status_code == 200
    assert res_a_read.json()["view_name"] == "Analyst Confidential View"

    # User B attempts to read User A's view by ID -> 404
    res_b_read = client.get(f"/api/v1/views/{view_id}", headers=headers_b)
    assert res_b_read.status_code == 404
    assert res_b_read.json()["error"]["code"] == "VIEW_NOT_FOUND"

    # User B's list view must not contain User A's view
    res_b_list = client.get("/api/v1/views", headers=headers_b)
    assert res_b_list.status_code == 200
    b_view_ids = [v["id"] for v in res_b_list.json()["views"]]
    assert view_id not in b_view_ids


def test_user_cannot_update_another_users_view(auth_headers, seeded_auth_users) -> None:
    """User B cannot update User A's view by ID."""
    headers_a = auth_headers("analyst")
    headers_b = auth_headers("manager")

    # User A creates a saved view
    res_create = client.post(
        "/api/v1/views",
        headers=headers_a,
        json={
            "view_name": "Original Name A",
            "page": "audit",
            "filters_json": json.dumps({"role": "analyst"}),
        },
    )
    assert res_create.status_code == 200
    view_id = res_create.json()["id"]

    # User B attempts to overwrite User A's view
    res_b_update = client.put(
        f"/api/v1/views/{view_id}",
        headers=headers_b,
        json={
            "view_name": "Hijacked By User B",
            "filters_json": json.dumps({"role": "manager"}),
        },
    )
    assert res_b_update.status_code == 404
    assert res_b_update.json()["error"]["code"] == "VIEW_NOT_FOUND"

    # Verify User A's view is unchanged
    res_a_check = client.get(f"/api/v1/views/{view_id}", headers=headers_a)
    assert res_a_check.status_code == 200
    assert res_a_check.json()["view_name"] == "Original Name A"


def test_user_cannot_delete_another_users_view(auth_headers, seeded_auth_users) -> None:
    """User B cannot delete User A's view by ID."""
    headers_a = auth_headers("analyst")
    headers_b = auth_headers("manager")

    # User A creates a saved view
    res_create = client.post(
        "/api/v1/views",
        headers=headers_a,
        json={
            "view_name": "Delete Isolation Check",
            "page": "chat",
            "filters_json": json.dumps({"preset": "default"}),
        },
    )
    assert res_create.status_code == 200
    view_id = res_create.json()["id"]

    # User B attempts to delete User A's view -> 404
    res_b_delete = client.delete(f"/api/v1/views/{view_id}", headers=headers_b)
    assert res_b_delete.status_code == 404
    assert res_b_delete.json()["error"]["code"] == "VIEW_NOT_FOUND"

    # Verify User A's view still exists
    res_a_check = client.get(f"/api/v1/views/{view_id}", headers=headers_a)
    assert res_a_check.status_code == 200
    assert res_a_check.json()["id"] == view_id


def test_stored_filter_cannot_widen_results_beyond_caller_role(auth_headers, seeded_auth_users) -> None:
    """A client-stored filter attempting to request auditor clearance fails to escalate privileges."""
    headers_analyst = auth_headers("analyst")

    # Analyst saves a view pretending to request auditor-only records
    res_create = client.post(
        "/api/v1/views",
        headers=headers_analyst,
        json={
            "view_name": "Privilege Escalation Attempt",
            "page": "audit",
            "filters_json": json.dumps({"user_role": "auditor", "role": "auditor"}),
        },
    )
    assert res_create.status_code == 200
    stored_filter = json.loads(res_create.json()["filters_json"])

    # Attempting to use this filter against the audit endpoint fails with 403 Forbidden
    res_audit = client.get(
        "/api/v1/audit/logs",
        headers=headers_analyst,
        params=stored_filter,
    )
    assert res_audit.status_code == 403
    assert res_audit.json()["error"]["code"] == "FORBIDDEN"

    # Attempting to query documents catalog as analyst never leaks auditor-only documents
    res_docs = client.get("/api/v1/documents", headers=headers_analyst)
    assert res_docs.status_code == 200
    docs = res_docs.json()["documents"]
    for doc in docs:
        allowed = doc.get("allowed_roles") or []
        assert "analyst" in allowed, f"Analyst retrieved restricted doc {doc['id']} with roles {allowed}"
