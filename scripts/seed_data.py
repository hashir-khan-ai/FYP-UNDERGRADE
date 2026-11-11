"""Database seeding script for synthetic roles, users, and documents."""

import json
import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.auth import hash_password
from src.db.connection import get_db_connection
from src.db.migrations import init_db
from src.db.repository import Repository

SYNTHETIC_DEMO_PASSWORD = os.environ.get("SEED_DEFAULT_PASSWORD", "password123")


def seed() -> None:
    print("Initializing SQLite schema...")
    init_db()

    with get_db_connection() as conn:
        repo = Repository(conn)

        # 1. Seed Roles
        print("Seeding roles...")
        repo.insert_role("analyst", "Front-line compliance and operations staff", 10)
        repo.insert_role("manager", "Compliance manager and supervisory lead", 20)
        repo.insert_role("auditor", "Internal/external auditor and executive risk officer", 30)

        analyst_role = repo.get_role_by_name("analyst")
        manager_role = repo.get_role_by_name("manager")
        auditor_role = repo.get_role_by_name("auditor")

        assert analyst_role and manager_role and auditor_role

        # 2. Seed Synthetic Users (Argon2id hashes; upsert preserves user IDs)
        print("Seeding synthetic users...")
        pwd_hash = hash_password(SYNTHETIC_DEMO_PASSWORD)

        repo.upsert_user(
            username="analyst_user",
            password_hash=pwd_hash,
            role_id=analyst_role["id"],
            full_name="Alice Analyst",
            email="alice.analyst@bank.local",
        )
        repo.upsert_user(
            username="manager_user",
            password_hash=pwd_hash,
            role_id=manager_role["id"],
            full_name="Bob Manager",
            email="bob.manager@bank.local",
        )
        repo.upsert_user(
            username="auditor_user",
            password_hash=pwd_hash,
            role_id=auditor_role["id"],
            full_name="Carol Auditor",
            email="carol.auditor@bank.local",
        )

        # 3. Seed Document Catalog
        print("Registering documents in catalog...")
        documents_meta = [
            {
                "id": "DOC-FCA-BCOBS-2024",
                "filename": "FCA-BCOBS-Banking-Conduct.md",
                "jurisdiction": "UK_FCA",
                "doc_type": "PUBLIC_REGULATION",
                "version": "2024.1",
                "allowed_roles": ["analyst", "manager", "auditor"],
                "file_path": "data/raw/FCA-BCOBS-Banking-Conduct.md",
            },
            {
                "id": "DOC-UK-MLR-2017",
                "filename": "FCA-MLR-2017-Money-Laundering.md",
                "jurisdiction": "UK_FCA",
                "doc_type": "PUBLIC_REGULATION",
                "version": "2017.3",
                "allowed_roles": ["analyst", "manager", "auditor"],
                "file_path": "data/raw/FCA-MLR-2017-Money-Laundering.md",
            },
            {
                "id": "DOC-BASEL-III-2023",
                "filename": "BASEL-III-Capital-Adequacy.md",
                "jurisdiction": "BASEL_BCBS",
                "doc_type": "PUBLIC_REGULATION",
                "version": "2023.1",
                "allowed_roles": ["analyst", "manager", "auditor"],
                "file_path": "data/raw/BASEL-III-Capital-Adequacy.md",
            },
            {
                "id": "DOC-INT-SOP-KYC-001",
                "filename": "SOP-KYC-CDD-001.md",
                "jurisdiction": "INTERNAL_SYNTHETIC",
                "doc_type": "INTERNAL_SOP",
                "version": "3.2",
                "allowed_roles": ["analyst", "manager", "auditor"],
                "file_path": "data/synthetic/SOP-KYC-CDD-001.md",
            },
            {
                "id": "DOC-INT-POL-MGT-002",
                "filename": "POLICY-SUPERVISORY-ESCALATION-002.md",
                "jurisdiction": "INTERNAL_SYNTHETIC",
                "doc_type": "INTERNAL_MANAGEMENT_POLICY",
                "version": "2.1",
                "allowed_roles": ["manager", "auditor"],
                "file_path": "data/synthetic/POLICY-SUPERVISORY-ESCALATION-002.md",
            },
            {
                "id": "DOC-INT-AUDIT-CONF-2025",
                "filename": "AUDIT-CONFIDENTIAL-FINDINGS-2025.md",
                "jurisdiction": "INTERNAL_SYNTHETIC",
                "doc_type": "CONFIDENTIAL_AUDIT_FINDINGS",
                "version": "1.0",
                "allowed_roles": ["auditor"],
                "file_path": "data/synthetic/AUDIT-CONFIDENTIAL-FINDINGS-2025.md",
            },
        ]

        for doc in documents_meta:
            repo.register_document(
                doc_id=doc["id"],
                filename=doc["filename"],
                source_jurisdiction=doc["jurisdiction"],
                doc_type=doc["doc_type"],
                version=doc["version"],
                allowed_roles=doc["allowed_roles"],
                file_path=doc["file_path"],
                total_chunks=0,
            )

    print("Database seeding completed successfully.")


if __name__ == "__main__":
    seed()

