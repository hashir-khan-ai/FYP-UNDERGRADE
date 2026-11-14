"""Security tests for Audit Log CSV Exports.

CRITICAL SECURITY CONTRACT:
1. Role Clearance: Only 'auditor' role may export audit records. All other roles
   ('analyst', 'manager', unauthenticated) must be strictly denied (401/403).
2. Audit Trail: Every export action writes a verifiable, hash-chained audit-log entry
   recording who performed the export, timestamp, row count, and filter parameters.
3. Formula Injection Neutralization: All CSV cells beginning with formula triggers
   ('=', '+', '-', '@', tab, CR) must be sanitized with a single-quote prefix.
"""

from __future__ import annotations

import csv
import io
import json
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.routes import sanitize_csv_cell
from src.db.connection import get_db_connection
from src.db.repository import Repository


client = TestClient(app)


def test_audit_export_role_gating(auth_headers, seeded_auth_users) -> None:
    """Only 'auditor' role is permitted to export audit logs. Analyst/manager denied 403."""
    # Unauthenticated request fails 401
    res_unauth = client.get("/api/v1/audit/export")
    assert res_unauth.status_code == 401

    # Analyst fails 403
    res_analyst = client.get("/api/v1/audit/export", headers=auth_headers("analyst"))
    assert res_analyst.status_code == 403
    assert res_analyst.json()["error"]["code"] == "FORBIDDEN"

    # Manager fails 403
    res_manager = client.get("/api/v1/audit/export", headers=auth_headers("manager"))
    assert res_manager.status_code == 403
    assert res_manager.json()["error"]["code"] == "FORBIDDEN"

    # Auditor succeeds 200
    res_auditor = client.get("/api/v1/audit/export", headers=auth_headers("auditor"))
    assert res_auditor.status_code == 200
    assert "text/csv" in res_auditor.headers["content-type"]
    assert "attachment; filename=" in res_auditor.headers["content-disposition"]


def test_audit_export_writes_audit_log_entry(auth_headers, seeded_auth_users) -> None:
    """An export event creates an immutable audit trail entry recording who, when, count, and filters."""
    auditor_info = seeded_auth_users["auditor"]
    headers = auth_headers("auditor")

    # Fetch initial audit log count
    with get_db_connection() as conn:
        repo = Repository(conn)
        initial_logs = repo.list_audit_logs(limit=200)
        initial_count = len(initial_logs)

    # Perform audit export with specific filter
    res = client.get(
        "/api/v1/audit/export",
        headers=headers,
        params={"user_role": "analyst", "limit": 25},
    )
    assert res.status_code == 200

    # Inspect the newly recorded audit log row
    with get_db_connection() as conn:
        repo = Repository(conn)
        latest_logs = repo.list_audit_logs(limit=10)
        latest_row = latest_logs[0]

        assert latest_row["final_route"] == "AUDIT_EXPORT"
        assert int(latest_row["user_id"]) == int(auditor_info["id"])
        assert latest_row["user_role"] == "auditor"

        details = json.loads(latest_row["response_text"])
        assert "row_count" in details
        assert details["filters"]["user_role"] == "analyst"
        assert details["filters"]["limit"] == 25
        assert latest_row["entry_hash"] is not None
        assert len(latest_row["entry_hash"]) == 64


def test_sanitize_csv_cell_unit_neutralization() -> None:
    """Formula injection prefixes (=, +, -, @, \\t, \\r) are neutralized with a leading single quote."""
    # Formula triggers
    assert sanitize_csv_cell("=cmd|' /C calc'!A0") == "'=cmd|' /C calc'!A0"
    assert sanitize_csv_cell("+123456") == "'+123456"
    assert sanitize_csv_cell("-SUM(A1:A10)") == "'-SUM(A1:A10)"
    assert sanitize_csv_cell("@SUM(1+1)") == "'@SUM(1+1)"
    assert sanitize_csv_cell("\tMALICIOUS_TAB") == "'\tMALICIOUS_TAB"
    assert sanitize_csv_cell("\rMALICIOUS_CR") == "'\rMALICIOUS_CR"

    # Benign content remains unchanged
    assert sanitize_csv_cell("normal text") == "normal text"
    assert sanitize_csv_cell("12345") == "12345"
    assert sanitize_csv_cell(None) == ""
    assert sanitize_csv_cell("") == ""


def test_csv_formula_injection_end_to_end_in_export(auth_headers, seeded_auth_users) -> None:
    """CSV output contains escaped cells for adversarial strings injected into audit fields."""
    headers = auth_headers("auditor")

    # Insert a synthetic row containing dangerous formula injection triggers in text fields
    with get_db_connection() as conn:
        repo = Repository(conn)
        repo.create_audit_log(
            session_id=None,
            user_id=seeded_auth_users["auditor"]["id"],
            user_role="auditor",
            query_text="=HYPERLINK(\"http://malicious.site\",\"Click Me\")",
            final_route="+DDE(\"cmd\";\"/C calc.exe\";\"!A0\")",
            retrieved_chunk_ids=[],
            relevance_scores=[],
            response_text="-2+5+cmd|' /C calc'!A0",
            latency_ms=10.0,
            llm_profile="@malicious_profile",
            llm_model="\tmalicious_model",
        )
        conn.commit()

    # Request export
    res = client.get("/api/v1/audit/export", headers=headers, params={"limit": 50})
    assert res.status_code == 200

    csv_reader = csv.reader(io.StringIO(res.text))
    rows = list(csv_reader)
    assert len(rows) > 1  # Header + data rows

    # Verify that in EVERY cell of EVERY row, no raw formula trigger exists at index 0
    # Formula triggers are '= + - @ \\t \\r'
    for r_idx, row in enumerate(rows[1:], start=1):
        for c_idx, cell in enumerate(row):
            if cell:
                # If the underlying data was a formula, it must start with a single quote
                if cell[0] in ("=", "+", "-", "@", "\t", "\r"):
                    pytest.fail(
                        f"Unsanitized formula trigger found in row {r_idx}, col {c_idx}: {cell!r}"
                    )

