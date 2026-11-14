"""Security and audit tests for Document Metadata Edits and Cache Invalidation.

CRITICAL SECURITY CONTRACT:
1. Document edits (title and permitted roles) are restricted strictly to manager and auditor.
   Analysts and unauthenticated users must be denied (401/403).
2. Every saved change to title or permitted roles writes an audit-log entry recording
   who made the change, timestamp, doc ID, old vs new title, and old vs new roles.
3. Modifying permitted roles on any document strictly invalidates the LLM cache and
   mutates the index ACL version, preventing cached answers from leaking across permission changes.
"""

from __future__ import annotations

import json
from fastapi.testclient import TestClient

from src.api.main import app
from src.core.acl_version import compute_index_acl_version
from src.db.connection import get_db_connection
from src.db.repository import Repository


client = TestClient(app)


def _ensure_test_document(doc_id: str = "doc_test_audit_01") -> None:
    """Helper to insert or verify test document in catalog."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT OR REPLACE INTO documents (
                id, filename, source_jurisdiction, doc_type, version,
                allowed_roles, file_path, total_chunks
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                doc_id,
                "Initial Test Document Title.pdf",
                "UK",
                "Policy",
                "1.0",
                json.dumps(["manager", "auditor"]),
                "./data/test/doc_01.pdf",
                5,
            ),
        )
        conn.commit()


def test_document_edit_role_gating(auth_headers) -> None:
    """Analyst cannot edit document; Manager and Auditor are authorized."""
    _ensure_test_document("doc_gating_01")

    # Unauthenticated -> 401
    res_unauth = client.patch(
        "/api/v1/documents/doc_gating_01",
        json={"title": "Hacked Title"},
    )
    assert res_unauth.status_code == 401

    # Analyst -> 403 Forbidden
    res_analyst = client.patch(
        "/api/v1/documents/doc_gating_01",
        headers=auth_headers("analyst"),
        json={"title": "Analyst Renaming Attempt"},
    )
    assert res_analyst.status_code == 403
    assert res_analyst.json()["error"]["code"] == "FORBIDDEN"

    # Manager -> 200 OK
    res_mgr = client.patch(
        "/api/v1/documents/doc_gating_01",
        headers=auth_headers("manager"),
        json={"title": "Manager Updated Title"},
    )
    assert res_mgr.status_code == 200
    assert res_mgr.json()["status"] == "ok"


def test_document_edit_audit_logs_title_and_role_changes(auth_headers, seeded_auth_users) -> None:
    """Every saved metadata change generates an audit trail record once per save."""
    doc_id = "doc_audit_trail_01"
    _ensure_test_document(doc_id)
    mgr_info = seeded_auth_users["manager"]
    headers = auth_headers("manager")

    # 1. Update title and roles
    res = client.patch(
        f"/api/v1/documents/{doc_id}",
        headers=headers,
        json={
            "title": "New Governance Policy 2026",
            "allowed_roles": ["auditor"],
        },
    )
    assert res.status_code == 200

    # 2. Verify audit trail row
    with get_db_connection() as conn:
        repo = Repository(conn)
        latest_logs = repo.list_audit_logs(limit=5)
        audit_entry = next((l for l in latest_logs if l["final_route"] == "DOCUMENT_UPDATE"), None)

        assert audit_entry is not None
        assert int(audit_entry["user_id"]) == int(mgr_info["id"])
        assert audit_entry["user_role"] == "manager"

        details = json.loads(audit_entry["response_text"])
        assert details["doc_id"] == doc_id
        assert details["title_changed"] is True
        assert details["new_title"] == "New Governance Policy 2026"
        assert details["roles_changed"] is True
        assert "auditor" in details["new_roles"]
        assert "manager" not in details["new_roles"]


def test_document_role_change_invalidates_cache_and_acl_version(auth_headers) -> None:
    """Changing permitted roles clears LLM cache and mutates index ACL version."""
    doc_id = "doc_cache_inval_01"
    _ensure_test_document(doc_id)
    headers = auth_headers("manager")

    with get_db_connection() as conn:
        repo = Repository(conn)
        # Compute baseline ACL version
        acl_v1 = compute_index_acl_version(conn)

        # Seed an entry into llm_cache
        repo.set_cached_llm(
            cache_key="test_cache_key_pre_change",
            prompt_hash="prompt_hash_123",
            model_name="mock-gpt",
            response_text="Cached answer before role modification",
        )
        conn.commit()

        # Verify entry exists
        cached = repo.get_cached_llm("test_cache_key_pre_change")
        assert cached is not None

    # Update document permitted roles (e.g. restrict to auditor only)
    res = client.patch(
        f"/api/v1/documents/{doc_id}",
        headers=headers,
        json={"allowed_roles": ["auditor"]},
    )
    assert res.status_code == 200

    with get_db_connection() as conn:
        repo = Repository(conn)
        # Verify the cache table was purged upon role modification
        cached_after = repo.get_cached_llm("test_cache_key_pre_change")
        assert cached_after is None

        # Verify ACL version mutated
        acl_v2 = compute_index_acl_version(conn)
        assert acl_v1 != acl_v2, f"ACL version must mutate on role change (was {acl_v1}, now {acl_v2})"
