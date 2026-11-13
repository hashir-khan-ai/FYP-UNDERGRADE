"""Index and seed the SQLite Knowledge Graph from document metadata and cross-references.

Builds kg_nodes and kg_edges in the SQLite database, connecting regulations,
topics, internal policies, and audit findings with strict server-side RBAC tags.
"""

import json
import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import settings
from src.retrieval.knowledge_graph import KnowledgeGraphStore

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("build_kg")

# Core regulatory topics
REGULATORY_TOPICS = {
    "topic:capital_adequacy": {
        "name": "Basel III Capital Adequacy & CET1 Standards",
        "roles": ["analyst", "manager", "auditor"],
    },
    "topic:market_risk": {
        "name": "Market Risk & Fundamental Review of Trading Book (FRTB)",
        "roles": ["analyst", "manager", "auditor"],
    },
    "topic:cdd_aml": {
        "name": "Customer Due Diligence & Anti-Money Laundering (MLR 2017 / EBA)",
        "roles": ["analyst", "manager", "auditor"],
    },
    "topic:client_assets": {
        "name": "FCA Client Assets (CASS 6 Custody & CASS 7 Client Money)",
        "roles": ["analyst", "manager", "auditor"],
    },
    "topic:conduct_business": {
        "name": "FCA Conduct of Business (COBS & BCOBS)",
        "roles": ["analyst", "manager", "auditor"],
    },
    "topic:consumer_credit": {
        "name": "Consumer Credit Sourcebook (CONC)",
        "roles": ["analyst", "manager", "auditor"],
    },
    "topic:dispute_resolution": {
        "name": "Dispute Resolution & Complaints Handling (DISP)",
        "roles": ["analyst", "manager", "auditor"],
    },
    "topic:market_abuse": {
        "name": "Market Abuse Regulation & Surveillance (MAR)",
        "roles": ["analyst", "manager", "auditor"],
    },
    "topic:operational_resilience": {
        "name": "PRA SS1/21 Operational Resilience & Impact Tolerances",
        "roles": ["analyst", "manager", "auditor"],
    },
    "topic:outsourcing": {
        "name": "PRA SS2/21 Outsourcing & Third-Party Risk Management",
        "roles": ["analyst", "manager", "auditor"],
    },
    "topic:data_protection": {
        "name": "UK GDPR & Data Protection Act 2018",
        "roles": ["analyst", "manager", "auditor"],
    },
    "topic:sanctions": {
        "name": "UK Sanctions & Anti-Terrorism Act 2000",
        "roles": ["analyst", "manager", "auditor"],
    },
    "topic:internal_policies": {
        "name": "Bank Internal Standard Operating Procedures & Escalations",
        "roles": ["manager", "auditor"],
    },
    "topic:audit_findings": {
        "name": "Confidential Supervisory & Penetration Audit Reports",
        "roles": ["auditor"],
    },
}

# Cross-reference rules: maps internal document prefix to regulatory doc IDs
CROSS_REFERENCES = [
    ("SOP-KYC-CDD-001", "FCA-MLR-2017-Money-Laundering", "implements"),
    ("SOP-KYC-CDD-001", "EBA-GL-2021-02-Customer-Due-Diligence", "implements"),
    ("SOP-TRANSACTION-MONITORING-002", "FCA-MLR-2017-Money-Laundering", "implements"),
    ("SOP-TRANSACTION-MONITORING-002", "UK-Sanctions-Anti-Terrorism-Act-2000", "implements"),
    ("SOP-VULNERABLE-CUSTOMERS-003", "FCA-CONC-Consumer-Credit", "implements"),
    ("SOP-VULNERABLE-CUSTOMERS-003", "FCA-PRIN-Principles-for-Businesses", "implements"),
    ("POLICY-SUPERVISORY-ESCALATION-002", "PRA-SS1-21-Operational-Resilience", "implements"),
    ("POLICY-SUPERVISORY-ESCALATION-002", "FCA-SYSC-Senior-Management", "implements"),
    ("POLICY-CYBER-INCIDENT-ESCALATION-003", "PRA-SS1-21-Operational-Resilience", "implements"),
    ("POLICY-CYBER-INCIDENT-ESCALATION-003", "UK-GDPR-Data-Protection-Act-2018", "implements"),
    ("POLICY-MARKET-ABUSE-SURVEILLANCE-004", "FCA-MAR-Market-Conduct", "implements"),
    ("AUDIT-CONFIDENTIAL-FINDINGS-2025", "FCA-CASS-Client-Assets", "audits"),
    ("AUDIT-CONFIDENTIAL-FINDINGS-2025", "FCA-MLR-2017-Money-Laundering", "audits"),
    ("AUDIT-CYBER-PENETRATION-FINDINGS-2025", "PRA-SS1-21-Operational-Resilience", "audits"),
    ("AUDIT-CYBER-PENETRATION-FINDINGS-2025", "PRA-SS2-21-Outsourcing-Third-Party", "audits"),
]


def build_knowledge_graph(db_path: str | Path | None = None) -> dict[str, int]:
    """Populate the knowledge graph store from raw and synthetic documents."""
    store = KnowledgeGraphStore(db_path=db_path)

    # 1. Seed Topic Nodes
    for topic_id, data in REGULATORY_TOPICS.items():
        store.add_node(
            node_id=topic_id,
            name=data["name"],
            node_type="topic",
            doc_id="CORE_TAXONOMY",
            allowed_roles=data["roles"],
        )

    # 2. Scan meta.json files
    meta_files = list((ROOT / "data" / "raw").glob("*.meta.json")) + list(
        (ROOT / "data" / "synthetic").glob("*.meta.json")
    )
    logger.info("Found %d metadata sidecars to process.", len(meta_files))

    doc_ids_seen = set()
    for meta_path in meta_files:
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception as exc:
            logger.warning("Could not read %s: %s", meta_path, exc)
            continue

        doc_id = meta.get("document_id") or meta_path.stem.replace(".meta", "")
        title = meta.get("title") or doc_id
        roles = meta.get("allowed_roles") or ["analyst", "manager", "auditor"]
        node_type = "regulation" if "raw" in str(meta_path) else (
            "audit_finding" if "AUDIT" in doc_id else "policy"
        )
        doc_node_id = f"doc:{doc_id}"
        doc_ids_seen.add(doc_id)

        store.add_node(
            node_id=doc_node_id,
            name=title,
            node_type=node_type,
            doc_id=doc_id,
            allowed_roles=roles,
            metadata=meta,
        )

        # Connect document to relevant topic
        doc_lower = doc_id.lower()
        if "basel" in doc_lower:
            store.add_edge(doc_node_id, "topic:capital_adequacy", "covers")
        elif "mlr" in doc_lower or "cdd" in doc_lower or "due-diligence" in doc_lower:
            store.add_edge(doc_node_id, "topic:cdd_aml", "covers")
        elif "cass" in doc_lower:
            store.add_edge(doc_node_id, "topic:client_assets", "covers")
        elif "mar" in doc_lower or "market-abuse" in doc_lower:
            store.add_edge(doc_node_id, "topic:market_abuse", "covers")
        elif "ss1-21" in doc_lower or "operational-resilience" in doc_lower:
            store.add_edge(doc_node_id, "topic:operational_resilience", "covers")
        elif "ss2-21" in doc_lower or "outsourcing" in doc_lower:
            store.add_edge(doc_node_id, "topic:outsourcing", "covers")
        elif "gdpr" in doc_lower:
            store.add_edge(doc_node_id, "topic:data_protection", "covers")
        elif "sanction" in doc_lower:
            store.add_edge(doc_node_id, "topic:sanctions", "covers")

        if node_type == "policy":
            store.add_edge(doc_node_id, "topic:internal_policies", "belongs_to")
        elif node_type == "audit_finding":
            store.add_edge(doc_node_id, "topic:audit_findings", "belongs_to")

    # 3. Add Explicit Cross-References
    for source_id, target_id, relation in CROSS_REFERENCES:
        src_node = f"doc:{source_id}"
        tgt_node = f"doc:{target_id}"
        store.add_edge(src_node, tgt_node, relation)
        logger.info("Indexed cross-reference: %s -[%s]-> %s", src_node, relation, tgt_node)

    stats = store.get_stats()
    logger.info("Knowledge Graph index complete: %d nodes, %d edges.", stats["nodes"], stats["edges"])
    return stats


if __name__ == "__main__":
    target_db = ROOT / "data" / "compliance.db"
    res = build_knowledge_graph(target_db)
    print(f"SUCCESS: Knowledge Graph indexed into {target_db}: {res['nodes']} nodes, {res['edges']} edges.")

