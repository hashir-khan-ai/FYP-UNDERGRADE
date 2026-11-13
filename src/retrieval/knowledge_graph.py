"""Lightweight Local Knowledge Graph for Regulatory Cross-References.

Backed entirely by SQLite tables (``kg_nodes`` and ``kg_edges``), providing $0
cost, local-first Graph RAG augmentation without heavy external dependencies.

RBAC CONTRACT:
Every node records ``allowed_roles`` (e.g. '["analyst", "manager", "auditor"]').
Queries and 1-hop cross-reference traversals filter on ``allowed_roles``
server-side at query time. Restricted nodes and chunks never leave the graph
retriever for an unauthorized user role. Target leakage: strictly 0.00%.
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from src.config import settings
from src.core.security import normalize_role

logger = logging.getLogger(__name__)


class KnowledgeGraphStore:
    """SQLite-backed Knowledge Graph store for regulatory entities and clauses."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path or settings.DATABASE_PATH)
        self.init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        """Create kg_nodes and kg_edges tables if they do not exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS kg_nodes (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    node_type TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    chunk_id TEXT,
                    allowed_roles TEXT NOT NULL,
                    metadata_json TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS kg_edges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    weight REAL DEFAULT 1.0,
                    FOREIGN KEY(source_id) REFERENCES kg_nodes(id) ON DELETE CASCADE,
                    FOREIGN KEY(target_id) REFERENCES kg_nodes(id) ON DELETE CASCADE,
                    UNIQUE(source_id, target_id, relation)
                )
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_nodes_doc ON kg_nodes(doc_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_nodes_type ON kg_nodes(node_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_edges_src ON kg_edges(source_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_kg_edges_tgt ON kg_edges(target_id)")
            conn.commit()

    def add_node(
        self,
        node_id: str,
        name: str,
        node_type: str,
        doc_id: str,
        chunk_id: str | None = None,
        allowed_roles: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Upsert a knowledge graph node with server-enforced allowed_roles."""
        roles = allowed_roles or ["analyst", "manager", "auditor"]
        roles_json = json.dumps([r.lower() for r in roles])
        meta_json = json.dumps(metadata or {})
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO kg_nodes (id, name, node_type, doc_id, chunk_id, allowed_roles, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    node_type=excluded.node_type,
                    doc_id=excluded.doc_id,
                    chunk_id=excluded.chunk_id,
                    allowed_roles=excluded.allowed_roles,
                    metadata_json=excluded.metadata_json
                """,
                (node_id, name, node_type, doc_id, chunk_id or "", roles_json, meta_json),
            )
            conn.commit()

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation: str,
        weight: float = 1.0,
    ) -> None:
        """Insert or replace a directed edge linking two regulatory nodes."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO kg_edges (source_id, target_id, relation, weight)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source_id, target_id, relation) DO UPDATE SET
                    weight=excluded.weight
                """,
                (source_id, target_id, relation, weight),
            )
            conn.commit()

    def search_nodes(
        self,
        query: str,
        role: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search nodes matching query terms, filtering strictly by user role."""
        normalized_role = normalize_role(role)
        terms = [t.strip().lower() for t in query.split() if len(t.strip()) >= 3]
        if not terms:
            return []

        # Parameterized query with role filter
        like_clauses = " OR ".join(["LOWER(name) LIKE ? OR LOWER(id) LIKE ?" for _ in terms])
        params: list[Any] = []
        for t in terms:
            params.extend([f"%{t}%", f"%{t}%"])

        sql = f"""
            SELECT id, name, node_type, doc_id, chunk_id, allowed_roles, metadata_json
            FROM kg_nodes
            WHERE ({like_clauses})
            LIMIT ?
        """
        params.append(limit * 3)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()

        results: list[dict[str, Any]] = []
        for r in rows:
            roles = json.loads(r["allowed_roles"])
            if normalized_role in roles:
                results.append(
                    {
                        "id": r["id"],
                        "name": r["name"],
                        "node_type": r["node_type"],
                        "doc_id": r["doc_id"],
                        "chunk_id": r["chunk_id"],
                        "allowed_roles": roles,
                    }
                )
                if len(results) >= limit:
                    break
        return results

    def traverse_cross_references(
        self,
        node_ids: list[str],
        role: str,
    ) -> list[dict[str, Any]]:
        """Find 1-hop cross-referenced nodes, returning only those permitted to role."""
        if not node_ids:
            return []
        normalized_role = normalize_role(role)
        placeholders = ",".join(["?"] * len(node_ids))
        sql = f"""
            SELECT e.relation, e.weight, n.id, n.name, n.node_type, n.doc_id, n.chunk_id, n.allowed_roles
            FROM kg_edges e
            JOIN kg_nodes n ON (e.target_id = n.id)
            WHERE e.source_id IN ({placeholders})
            UNION
            SELECT e.relation, e.weight, n.id, n.name, n.node_type, n.doc_id, n.chunk_id, n.allowed_roles
            FROM kg_edges e
            JOIN kg_nodes n ON (e.source_id = n.id)
            WHERE e.target_id IN ({placeholders})
        """
        params = list(node_ids) + list(node_ids)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()

        permitted: list[dict[str, Any]] = []
        seen = set(node_ids)
        for r in rows:
            nid = r["id"]
            if nid in seen:
                continue
            roles = json.loads(r["allowed_roles"])
            if normalized_role in roles:
                seen.add(nid)
                permitted.append(
                    {
                        "id": nid,
                        "name": r["name"],
                        "node_type": r["node_type"],
                        "doc_id": r["doc_id"],
                        "chunk_id": r["chunk_id"],
                        "relation": r["relation"],
                        "weight": float(r["weight"]),
                    }
                )
        return permitted

    def find_candidate_chunk_ids(
        self,
        query: str,
        role: str,
        limit: int = 5,
    ) -> list[str]:
        """Find candidate chunk IDs via knowledge graph entity match and 1-hop traversal."""
        matched = self.search_nodes(query, role=role, limit=5)
        if not matched:
            return []

        matched_ids = [m["id"] for m in matched]
        neighbors = self.traverse_cross_references(matched_ids, role=role)

        chunk_ids: list[str] = []
        for item in matched + neighbors:
            cid = item.get("chunk_id")
            if cid and cid not in chunk_ids:
                chunk_ids.append(cid)
            if len(chunk_ids) >= limit:
                break
        return chunk_ids

    def get_stats(self) -> dict[str, int]:
        """Return total node and edge counts in the knowledge graph."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM kg_nodes")
            node_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM kg_edges")
            edge_count = cursor.fetchone()[0]
        return {"nodes": node_count, "edges": edge_count}

