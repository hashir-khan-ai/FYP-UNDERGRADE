"""Tests for SQLite Knowledge Graph store and server-side RBAC traversals."""

import json
from pathlib import Path
import pytest

from src.retrieval.knowledge_graph import KnowledgeGraphStore


@pytest.fixture
def temp_kg(tmp_path: Path) -> KnowledgeGraphStore:
    db_file = tmp_path / "test_kg.db"
    return KnowledgeGraphStore(db_path=db_file)


def test_kg_init_and_add_nodes_edges(temp_kg: KnowledgeGraphStore) -> None:
    """Verify nodes and edges can be inserted and stats reported."""
    temp_kg.add_node(
        node_id="doc:BASEL-III",
        name="Basel III Accord",
        node_type="regulation",
        doc_id="BASEL-III",
        allowed_roles=["analyst", "manager", "auditor"],
    )
    temp_kg.add_node(
        node_id="topic:capital",
        name="Capital Adequacy",
        node_type="topic",
        doc_id="TAXONOMY",
        allowed_roles=["analyst", "manager", "auditor"],
    )
    temp_kg.add_edge("doc:BASEL-III", "topic:capital", "covers")

    stats = temp_kg.get_stats()
    assert stats["nodes"] == 2
    assert stats["edges"] == 1


def test_kg_rbac_enforcement_analyst_cannot_retrieve_manager_or_auditor_nodes(
    temp_kg: KnowledgeGraphStore,
) -> None:
    """Server-side RBAC ensures analyst queries never retrieve restricted nodes."""
    # 1. Public node
    temp_kg.add_node(
        node_id="doc:FCA-CASS",
        name="Client Assets Sourcebook",
        node_type="regulation",
        doc_id="FCA-CASS",
        allowed_roles=["analyst", "manager", "auditor"],
    )
    # 2. Manager internal policy
    temp_kg.add_node(
        node_id="doc:POL-042",
        name="Internal Custody Reconciliation Policy",
        node_type="policy",
        doc_id="POL-042",
        allowed_roles=["manager", "auditor"],
    )
    # 3. Auditor confidential report
    temp_kg.add_node(
        node_id="doc:AUDIT-2025-01",
        name="Confidential CASS Discrepancy Findings",
        node_type="audit_finding",
        doc_id="AUDIT-2025-01",
        allowed_roles=["auditor"],
    )

    # Cross references
    temp_kg.add_edge("doc:POL-042", "doc:FCA-CASS", "implements")
    temp_kg.add_edge("doc:AUDIT-2025-01", "doc:FCA-CASS", "audits")

    # Search as analyst
    analyst_results = temp_kg.search_nodes("Custody Discrepancy Reconciliation", role="analyst")
    for r in analyst_results:
        assert "analyst" in r["allowed_roles"]
        assert r["id"] != "doc:POL-042"
        assert r["id"] != "doc:AUDIT-2025-01"

    # Traversal from public node as analyst
    traversed_analyst = temp_kg.traverse_cross_references(["doc:FCA-CASS"], role="analyst")
    assert len(traversed_analyst) == 0  # Connected edges are restricted to manager/auditor

    # Traversal as auditor
    traversed_auditor = temp_kg.traverse_cross_references(["doc:FCA-CASS"], role="auditor")
    found_ids = {n["id"] for n in traversed_auditor}
    assert "doc:POL-042" in found_ids
    assert "doc:AUDIT-2025-01" in found_ids

