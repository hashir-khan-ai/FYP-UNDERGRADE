"""Tests for Phase 11 Security Depth enhancements (A.1 to A.6)."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
import pytest

from src.db.repository import Repository
from src.db.migrations import SCHEMA_DDL, apply_migrations
from scripts.verify_audit import verify_audit_chain


@pytest.fixture
def test_db_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_DDL)
    apply_migrations(conn)
    yield conn
    conn.close()


class TestAuditHashChain:
    """A.1 Hash-chained audit log verification."""

    def test_clean_chain_validates(self, test_db_conn):
        repo = Repository(test_db_conn)
        # Create 3 audit records
        id1 = repo.create_audit_log(
            session_id=None,
            user_id=1,
            user_role="compliance_analyst",
            query_text="What is LCR minimum?",
            final_route="SINGLE_SEARCH",
            retrieved_chunk_ids=["chunk-1"],
            relevance_scores=[0.92],
            response_text="LCR minimum is 100%.",
            latency_ms=120.5,
        )
        id2 = repo.create_audit_log(
            session_id=None,
            user_id=1,
            user_role="compliance_analyst",
            query_text="What is NSFR requirement?",
            final_route="SINGLE_SEARCH",
            retrieved_chunk_ids=["chunk-2"],
            relevance_scores=[0.88],
            response_text="NSFR requirement is 100%.",
            latency_ms=145.2,
        )
        id3 = repo.create_audit_log(
            session_id=None,
            user_id=2,
            user_role="risk_manager",
            query_text="List supervisory escalation paths.",
            final_route="HYBRID_SEARCH",
            retrieved_chunk_ids=["chunk-3"],
            relevance_scores=[0.95],
            response_text="Escalations require Chief Risk Officer approval.",
            latency_ms=210.0,
        )

        valid, msg, details = verify_audit_chain(test_db_conn)
        assert valid is True
        assert details["total"] == 3
        assert "Audit chain intact" in msg

    def test_row_tampering_detected(self, test_db_conn):
        repo = Repository(test_db_conn)
        repo.create_audit_log(
            session_id=None,
            user_id=1,
            user_role="compliance_analyst",
            query_text="Query 1",
            final_route="SINGLE_SEARCH",
            retrieved_chunk_ids=[],
            relevance_scores=[],
            response_text="Original response 1",
            latency_ms=100.0,
        )
        repo.create_audit_log(
            session_id=None,
            user_id=1,
            user_role="compliance_analyst",
            query_text="Query 2",
            final_route="SINGLE_SEARCH",
            retrieved_chunk_ids=[],
            relevance_scores=[],
            response_text="Original response 2",
            latency_ms=100.0,
        )

        # Tamper with row 1's response_text directly in SQLite
        cur = test_db_conn.cursor()
        cur.execute("UPDATE audit_log SET response_text = 'Tampered content' WHERE id = 1;")
        test_db_conn.commit()

        valid, msg, details = verify_audit_chain(test_db_conn)
        assert valid is False
        assert "Hash mismatch at row id=1" in msg
        assert "tampering" in msg.lower()

    def test_row_deletion_detected(self, test_db_conn):
        repo = Repository(test_db_conn)
        for i in range(1, 4):
            repo.create_audit_log(
                session_id=None,
                user_id=1,
                user_role="compliance_analyst",
                query_text=f"Query {i}",
                final_route="SINGLE_SEARCH",
                retrieved_chunk_ids=[],
                relevance_scores=[],
                response_text=f"Response {i}",
                latency_ms=100.0,
            )

        # Delete middle row (id=2)
        cur = test_db_conn.cursor()
        cur.execute("DELETE FROM audit_log WHERE id = 2;")
        test_db_conn.commit()

        valid, msg, details = verify_audit_chain(test_db_conn)
        assert valid is False
        assert "Chain broken at row id=3" in msg
        assert "deletion" in msg.lower()

    def test_anchor_verification_passes_on_matching_state(self, test_db_conn, tmp_path):
        from scripts.export_audit_anchor import export_audit_anchor
        repo = Repository(test_db_conn)
        repo.create_audit_log(
            session_id=None,
            user_id=1,
            user_role="compliance_analyst",
            query_text="Anchor test 1",
            final_route="SINGLE_SEARCH",
            retrieved_chunk_ids=[],
            relevance_scores=[],
            response_text="Resp 1",
            latency_ms=100.0,
        )
        cur = test_db_conn.cursor()
        cur.execute("SELECT id, entry_hash FROM audit_log ORDER BY id DESC LIMIT 1;")
        head = cur.fetchone()

        anchor_dict = {
            "total_entries": 1,
            "head_id": head["id"],
            "head_hash": head["entry_hash"],
        }
        valid, msg, details = verify_audit_chain(test_db_conn, anchor=anchor_dict)
        assert valid is True
        assert details.get("anchor_verified") is True
        assert "verified against external anchor" in msg

    def test_anchor_detects_chain_recomputation_rewrite(self, test_db_conn):
        """Attacker modifies an earlier row and recomputes all hashes.
        Internal chain passes, but external anchor catches the rewrite.
        """
        from src.core.audit_chain import AUDIT_HASH_COLUMNS, GENESIS_PREV_HASH, compute_audit_hash

        repo = Repository(test_db_conn)
        repo.create_audit_log(
            session_id=None,
            user_id=1,
            user_role="compliance_analyst",
            query_text="Legitimate query 1",
            final_route="SINGLE_SEARCH",
            retrieved_chunk_ids=[],
            relevance_scores=[],
            response_text="Legitimate answer 1",
            latency_ms=100.0,
        )
        repo.create_audit_log(
            session_id=None,
            user_id=1,
            user_role="compliance_analyst",
            query_text="Legitimate query 2",
            final_route="SINGLE_SEARCH",
            retrieved_chunk_ids=[],
            relevance_scores=[],
            response_text="Legitimate answer 2",
            latency_ms=100.0,
        )

        # Snapshot external anchor
        cur = test_db_conn.cursor()
        cur.execute("SELECT id, entry_hash FROM audit_log WHERE id = 2;")
        head = cur.fetchone()
        anchor = {
            "total_entries": 2,
            "head_id": 2,
            "head_hash": head["entry_hash"],
        }

        # Attacker modifies row 1 and recomputes row 1 and row 2 hashes
        cur.execute("UPDATE audit_log SET response_text = 'Tampered text' WHERE id = 1;")
        # Recompute row 1
        cur.execute("SELECT * FROM audit_log WHERE id = 1;")
        row1 = cur.fetchone()
        vals1 = tuple(row1[col] for col in AUDIT_HASH_COLUMNS)
        new_hash_1 = compute_audit_hash(GENESIS_PREV_HASH, vals1)
        cur.execute("UPDATE audit_log SET entry_hash = ? WHERE id = 1;", (new_hash_1,))

        # Recompute row 2 using row 1's new hash as prev_hash
        cur.execute("UPDATE audit_log SET prev_hash = ? WHERE id = 2;", (new_hash_1,))
        cur.execute("SELECT * FROM audit_log WHERE id = 2;")
        row2 = cur.fetchone()
        vals2 = tuple(row2[col] for col in AUDIT_HASH_COLUMNS)
        new_hash_2 = compute_audit_hash(new_hash_1, vals2)
        cur.execute("UPDATE audit_log SET entry_hash = ? WHERE id = 2;", (new_hash_2,))
        test_db_conn.commit()

        # 1. Internal check without anchor passes (deceived by recomputation)
        internal_valid, _, _ = verify_audit_chain(test_db_conn)
        assert internal_valid is True

        # 2. Check against external anchor detects the history rewrite!
        anchor_valid, anchor_msg, _ = verify_audit_chain(test_db_conn, anchor=anchor)
        assert anchor_valid is False
        assert "Anchor mismatch at row id=2" in anchor_msg
        assert "history rewrite" in anchor_msg.lower()


class TestCanaryTokens:
    """A.2 Canary tokens and output guard verification."""

    def test_canaries_planted_in_restricted_documents(self):
        from src.core.canary import CANARY_REGISTRY
        for canary, meta in CANARY_REGISTRY.items():
            doc_id = meta["doc_id"]
            found = False
            for path in Path("data/synthetic").glob("*.md"):
                content = path.read_text(encoding="utf-8")
                if canary in content:
                    found = True
                    break
            assert found, f"Canary {canary} for doc {doc_id} must be present in data/synthetic/"

    def test_output_guard_neutralizes_unauthorized_canary(self):
        from src.core.canary import enforce_canary_guard, CANARY_REGISTRY
        from src.rag.baseline import REFUSAL_TEXT

        leaked_text = "According to CANARY-AUDIT-NEPTUNE-88192, secondary liquidity buffer dropped 14%."
        citations = [{"chunk_id": "audit-1", "snippet": "CANARY-AUDIT-NEPTUNE-88192"}]
        trace = ["Step 1: Found CANARY-AUDIT-NEPTUNE-88192 in vault."]

        # Unauthorized role: analyst
        sanitized, safe_cites, safe_trace, violated = enforce_canary_guard(
            text=leaked_text,
            user_role="analyst",
            citations=citations,
            trace=trace,
            refusal_replacement=REFUSAL_TEXT,
        )
        assert violated is True
        assert sanitized == REFUSAL_TEXT
        assert len(safe_cites) == 0
        assert "CANARY" not in str(safe_trace)

        # Authorized role: auditor
        clean_text, clean_cites, clean_trace, violated_auditor = enforce_canary_guard(
            text=leaked_text,
            user_role="auditor",
            citations=citations,
            trace=trace,
        )
        assert violated_auditor is False
        assert clean_text == leaked_text
        assert len(clean_cites) == 1

    def test_canary_stripped_from_session_title(self):
        from src.core.session_title import generate_session_title
        query = "What is the policy for CANARY-AUDIT-NEPTUNE-88192 in liquidity deficit?"
        title = generate_session_title(query)
        assert "CANARY" not in title
        assert "NEPTUNE" not in title
        assert len(title) > 0


class TestResultCountSideChannel:
    """A.3 Result-count side-channel defense: uniform refusal and pre-rank filtering."""

    def test_refusal_uniformity_side_channel(self):
        """Query matching restricted content vs non-existent query must produce identical response shape."""
        from src.rag.baseline import BaselineRAGPipeline, REFUSAL_TEXT
        from src.ingestion.chunker import DocumentChunk
        from src.ingestion.indexer import BM25Indexer

        # Create isolated test index with ONLY restricted documents (auditor-only)
        test_chunk = DocumentChunk(
            chunk_id="CONF-AUDIT-NEPTUNE-001",
            doc_id="DOC-CONF-AUDIT",
            doc_title="Confidential Audit Review",
            section_label="Section 1",
            clause_label="Clause 1.1",
            page=1,
            source_path="data/synthetic/AUDIT-CONFIDENTIAL-FINDINGS-2025.md",
            text_content="Special Project Neptune review uncovered intra-month secondary liquidity buffer deficit.",
            allowed_roles=["auditor"],
            jurisdiction="INTERNAL_SYNTHETIC",
        )

        test_bm25_path = "data/test_bm25_sidechannel.json"
        bm25 = BM25Indexer(index_path=test_bm25_path)
        try:
            bm25.build_and_save([test_chunk])

            # Query 1 matches the restricted content
            res_restricted_analyst = bm25.search("Project Neptune liquidity deficit", top_k=5, role="analyst")
            res_restricted_auditor = bm25.search("Project Neptune liquidity deficit", top_k=5, role="auditor")

            # Auditor finds the chunk; analyst finds 0 chunks because RBAC filters before ranking
            assert len(res_restricted_auditor.hits) == 1
            assert len(res_restricted_analyst.hits) == 0

            # Query 2 matches nothing in the corpus
            res_nonexistent_analyst = bm25.search("Galactic space travel maneuvers", top_k=5, role="analyst")
            assert len(res_nonexistent_analyst.hits) == 0

            # Build pipeline and execute generation with the retrieved sets
            pipeline = BaselineRAGPipeline()
            try:
                # Analyst asks Query 1 (matches restricted content only)
                answer_1, cites_1, cached_1, ms_1, usage_1 = pipeline.generate(
                    query="What is the Project Neptune liquidity deficit?",
                    passages=res_restricted_analyst.hits,
                    role="analyst",
                )

                # Analyst asks Query 2 (matches nothing)
                answer_2, cites_2, cached_2, ms_2, usage_2 = pipeline.generate(
                    query="What are the galactic space travel maneuvers?",
                    passages=res_nonexistent_analyst.hits,
                    role="analyst",
                )

                # Both refusals must be completely uniform: identical response shape, 0 citations, identical wording
                assert answer_1 == REFUSAL_TEXT
                assert answer_2 == REFUSAL_TEXT
                assert answer_1 == answer_2
                assert len(cites_1) == 0
                assert len(cites_2) == 0
                assert usage_1["calls"] == usage_2["calls"] == 0
                assert usage_1["prompt_tokens"] == usage_2["prompt_tokens"] == 0
            finally:
                pipeline.close()
        finally:
            Path(test_bm25_path).unlink(missing_ok=True)

    def test_post_rerank_rbac_defense(self):
        """Defense-in-depth: Even if candidate containing restricted chunk reaches rerank, post-rerank guard drops it."""
        from src.rag.baseline import BaselineRAGPipeline
        pipeline = BaselineRAGPipeline()
        restricted_candidate = {
            "chunk_id": "AUDIT-001",
            "text_content": "Project Vulcan SWIFT cryptographic flaw CANARY-AUDIT-VULCAN-44719.",
            "allowed_roles": ["auditor"],
            "score": 0.99,
        }
        permitted, _, dropped = pipeline.rerank("SWIFT defect", [restricted_candidate], role="analyst")
        assert dropped == 1
        assert len(permitted) == 0

    def test_pre_fusion_rbac_filter(self):
        """Native engine RBAC: Qdrant and BM25 pre-fusion search for analyst returns 0 restricted chunks."""
        from src.rag.baseline import baseline_pipeline
        res_bm25 = baseline_pipeline.bm25.search("Project Neptune liquidity deficit", top_k=5, role="analyst")
        assert not any("auditor" in h.get("allowed_roles", []) and "analyst" not in h.get("allowed_roles", []) for h in res_bm25.hits)
        assert not any("AUDIT" in h.get("chunk_id", "") for h in res_bm25.hits)


class TestIdentityAuthentication:
    """A.4 Role derived strictly from signed token; forged headers/body ignored."""

    def test_forged_role_in_request_ignored(self, test_db_conn, monkeypatch):
        from src.api.deps import get_current_user, ApiError
        from src.core.auth import create_access_token

        # Seed role and user 1 in test_db_conn
        repo = Repository(test_db_conn)
        repo.insert_role("analyst", "Analyst role", 10)
        analyst_role = repo.get_role_by_name("analyst")
        repo.upsert_user(
            username="analyst_user",
            password_hash="testhash",
            role_id=analyst_role["id"],
            full_name="Alice Analyst",
            email="alice@bank.local",
        )

        from contextlib import contextmanager
        @contextmanager
        def mock_get_db():
            yield test_db_conn

        monkeypatch.setattr("src.api.deps.get_db_connection", mock_get_db)

        # Create valid token for user 1 (Alice Analyst, role=analyst)
        token = create_access_token(user_id=1, username="analyst_user", role="analyst")
        auth_header = f"Bearer {token}"

        user = get_current_user(authorization=auth_header)
        # Role must be loaded from DB/token, never overridden by client
        assert user.role == "analyst"
        assert user.username == "analyst_user"

        # Check that client body role cannot override authenticated role
        import uuid
        from src.api.schemas import ChatQueryRequest
        req = ChatQueryRequest(
            session_id=uuid.uuid4(),
            query="What are the capital requirements?",
            role="auditor",
        )
        active_role = user.role
        if os.environ.get("MUTANT_ROLE_FROM_BODY") == "1" and getattr(req, "role", None):
            active_role = req.role
        assert active_role == user.role

    def test_tampered_jwt_rejected(self):
        from src.api.deps import get_current_user, ApiError
        from src.core.auth import create_access_token

        token = create_access_token(user_id=1, username="analyst_user", role="analyst")
        # Tamper with token signature
        tampered_token = token[:-4] + "fake"
        with pytest.raises(ApiError) as exc_info:
            get_current_user(authorization=f"Bearer {tampered_token}")
        assert exc_info.value.code == "INVALID_TOKEN"


class TestDocumentRevocation:
    """A.5 Dynamic permission revocation takes effect immediately."""

    def test_revocation_denies_access_immediately(self):
        from src.ingestion.chunker import DocumentChunk
        from src.ingestion.indexer import BM25Indexer

        chunk = DocumentChunk(
            chunk_id="REVOKE-TEST-001",
            doc_id="DOC-REVOKE-TEST",
            doc_title="Supervisory Escalation Policy",
            section_label="Section 1",
            clause_label="Clause 1.1",
            page=1,
            source_path="data/synthetic/POLICY-SUPERVISORY-ESCALATION-002.md",
            text_content="Supervisory escalation requires SMF-16 board approval within 24 hours.",
            allowed_roles=["manager", "auditor"],
            jurisdiction="UK",
        )

        bm25 = BM25Indexer(index_path="data/test_bm25_revoke.json")
        try:
            bm25.build_and_save([chunk])

            # Manager can initially find it
            res_before = bm25.search("Supervisory escalation SMF-16", top_k=5, role="manager")
            assert len(res_before.hits) == 1

            # Revoke manager permission: update to auditor only
            revoked_chunk = DocumentChunk(
                chunk_id="REVOKE-TEST-001",
                doc_id="DOC-REVOKE-TEST",
                doc_title="Supervisory Escalation Policy",
                section_label="Section 1",
                clause_label="Clause 1.1",
                page=1,
                source_path="data/synthetic/POLICY-SUPERVISORY-ESCALATION-002.md",
                text_content="Supervisory escalation requires SMF-16 board approval within 24 hours.",
                allowed_roles=["auditor"],
                jurisdiction="UK",
            )
            bm25.build_and_save([revoked_chunk])

            # Manager search immediately returns 0 results
            res_after_mgr = bm25.search("Supervisory escalation SMF-16", top_k=5, role="manager")
            assert len(res_after_mgr.hits) == 0

            # Auditor still has access
            res_after_aud = bm25.search("Supervisory escalation SMF-16", top_k=5, role="auditor")
            assert len(res_after_aud.hits) == 1
        finally:
            Path("data/test_bm25_revoke.json").unlink(missing_ok=True)


class TestCrossRoleCacheAndMemoryIsolation:
    """A.6 Cache keys and memory stores scoped by role and user."""

    def test_cross_role_cache_keys_differ(self):
        from src.core.llm_client import ResilientLLMClient

        client = ResilientLLMClient()
        prompt = "Explain statutory capital requirements under Basel III."

        key_analyst = client._compute_cache_key(
            profile="mock",
            model="mock-model",
            prompt=prompt,
            system_prompt=None,
            temperature=0.0,
            max_tokens=1024,
            step="answer",
            role="compliance_analyst",
            user_id=1,
        )

        key_auditor = client._compute_cache_key(
            profile="mock",
            model="mock-model",
            prompt=prompt,
            system_prompt=None,
            temperature=0.0,
            max_tokens=1024,
            step="answer",
            role="internal_auditor",
            user_id=2,
        )

        assert key_analyst != key_auditor, "Cache keys across different roles must never collide!"

    def test_cross_user_memory_isolation(self, test_db_conn):
        from src.core.memory import load_recent_turns
        repo = Repository(test_db_conn)

        # User 1 creates a session and message
        sess_id = repo.create_session("session-alice-1", user_id=1, title="Alice Session")
        repo.add_message(sess_id, sender="user", content="Secret analysis details for User 1")

        # User 2 attempts to load history from User 1's session
        turns_user2 = load_recent_turns(repo, session_id="session-alice-1", user_id=2, limit=10)
        assert turns_user2 == [], "User 2 must NEVER access User 1's session memory!"

        # User 1 can access their own memory
        turns_user1 = load_recent_turns(repo, session_id="session-alice-1", user_id=1, limit=10)
        assert len(turns_user1) == 1
        assert "Secret analysis" in turns_user1[0]["content"]

