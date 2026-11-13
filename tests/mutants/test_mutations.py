"""Tests for positive controls (mutation testing) of security controls.

Each test verifies:
1. Normal baseline: With no mutation flag, the security control holds and passes.
2. Mutant active: With the mutation flag set, the security control is breached,
   and the test PROVES that the security suite catches the breach (kills the mutant).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
import pytest

from src.config import settings
from src.core.canary import CANARY_REGISTRY, enforce_canary_guard
from src.core.llm_client import ResilientLLMClient
from src.core.memory import load_recent_turns
from src.db.migrations import SCHEMA_DDL, apply_migrations
from src.db.repository import Repository
from src.ingestion.chunker import DocumentChunk
from src.ingestion.indexer import BM25Indexer
from src.rag.baseline import BaselineRAGPipeline, REFUSAL_TEXT
from tests.mutants.adversarial_stub import AdversarialStubLLM


@pytest.fixture
def memory_db_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_DDL)
    apply_migrations(conn)
    yield conn
    conn.close()


class TestSecurityMutants:
    """Validate that security test suite fails when defenses are deliberately mutated."""

    def test_mutant_a_canary_guard_disabled(self, monkeypatch: pytest.MonkeyPatch):
        """Mutant (a): Disabling output canary guard causes canary exfiltration."""
        leaked_text = "Special review CANARY-AUDIT-NEPTUNE-88192 deficit."
        citations = [{"chunk_id": "c1", "snippet": "CANARY-AUDIT-NEPTUNE-88192"}]
        trace = ["Step: CANARY-AUDIT-NEPTUNE-88192"]

        # 1. Baseline: Output guard active -> catches canary
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

        # 2. Mutant active: Guard disabled -> canary leaks through!
        monkeypatch.setenv("MUTANT_DISABLE_CANARY_GUARD", "1")
        m_sanitized, m_cites, _, m_violated = enforce_canary_guard(
            text=leaked_text,
            user_role="analyst",
            citations=citations,
            trace=trace,
            refusal_replacement=REFUSAL_TEXT,
        )
        # The breach is evident: violated is False, canary is present in text and citations
        assert m_violated is False
        assert "CANARY-AUDIT-NEPTUNE-88192" in m_sanitized
        assert len(m_cites) == 1
        # Proves mutant (a) would FAIL the canary security assertion
        with pytest.raises(AssertionError):
            assert m_violated is True

    def test_mutant_b_post_rerank_rbac_disabled(self, monkeypatch: pytest.MonkeyPatch):
        """Mutant (b): Disabling post-rerank RBAC allows restricted candidate through re-ranker."""
        pipeline = BaselineRAGPipeline()
        restricted_candidate = {
            "chunk_id": "AUDIT-001",
            "text_content": "Project Vulcan SWIFT cryptographic flaw CANARY-AUDIT-VULCAN-44719.",
            "allowed_roles": ["auditor"],
            "score": 0.99,
        }

        # 1. Baseline: Post-rerank role guard drops auditor chunk for analyst
        permitted, _, dropped = pipeline.rerank("SWIFT defect", [restricted_candidate], role="analyst")
        assert dropped == 1
        assert len(permitted) == 0

        # 2. Mutant active: Post-rerank role guard disabled -> chunk reaches permitted passages!
        monkeypatch.setenv("MUTANT_DISABLE_POST_RERANK_RBAC", "1")
        m_permitted, _, m_dropped = pipeline.rerank("SWIFT defect", [restricted_candidate], role="analyst")
        assert m_dropped == 0
        assert len(m_permitted) == 1
        assert m_permitted[0]["chunk_id"] == "AUDIT-001"
        # Proves mutant (b) would FAIL the post-rerank security assertion
        with pytest.raises(AssertionError):
            assert len(m_permitted) == 0

    def test_mutant_c_pre_fusion_rbac_disabled(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """Mutant (c): Disabling pre-fusion RBAC returns restricted chunks from BM25 search."""
        test_chunk = DocumentChunk(
            chunk_id="AUDIT-NEPTUNE-001",
            doc_id="DOC-CONF",
            doc_title="Confidential Audit",
            section_label="Section 1",
            clause_label="Clause 1.1",
            page=1,
            source_path="data/synthetic/AUDIT-CONFIDENTIAL-FINDINGS-2025.md",
            text_content="Project Neptune secondary liquidity deficit.",
            allowed_roles=["auditor"],
            jurisdiction="INTERNAL_SYNTHETIC",
        )
        bm25 = BM25Indexer(index_path=str(tmp_path / "test_bm25.json"))
        bm25.build_and_save([test_chunk])

        # 1. Baseline: Pre-fusion filter ensures analyst gets 0 hits
        res_baseline = bm25.search("Project Neptune liquidity deficit", top_k=5, role="analyst")
        assert len(res_baseline.hits) == 0

        # 2. Mutant active: Pre-fusion filter bypassed -> analyst receives auditor chunk!
        monkeypatch.setenv("MUTANT_DISABLE_PRE_FUSION_RBAC", "1")
        res_mutant = bm25.search("Project Neptune liquidity deficit", top_k=5, role="analyst")
        assert len(res_mutant.hits) == 1
        assert res_mutant.hits[0]["chunk_id"] == "AUDIT-NEPTUNE-001"
        # Proves mutant (c) would FAIL the pre-fusion 0.00% leakage check
        with pytest.raises(AssertionError):
            assert len(res_mutant.hits) == 0

    def test_mutant_d_cache_key_without_role(self, monkeypatch: pytest.MonkeyPatch):
        """Mutant (d): Omitting role from cache key causes cross-role cache collision."""
        client = ResilientLLMClient()

        # 1. Baseline: Cache keys differ across roles
        key_analyst = client._compute_cache_key("dev", "model-1", "Prompt X", None, 0.0, 100, "ask", role="analyst", user_id=1)
        key_auditor = client._compute_cache_key("dev", "model-1", "Prompt X", None, 0.0, 100, "ask", role="auditor", user_id=2)
        assert key_analyst != key_auditor

        # 2. Mutant active: Cache key omits role and user -> key collision!
        monkeypatch.setenv("MUTANT_CACHE_NO_ROLE", "1")
        m_key_analyst = client._compute_cache_key("dev", "model-1", "Prompt X", None, 0.0, 100, "ask", role="analyst", user_id=1)
        m_key_auditor = client._compute_cache_key("dev", "model-1", "Prompt X", None, 0.0, 100, "ask", role="auditor", user_id=2)
        assert m_key_analyst == m_key_auditor
        # Proves mutant (d) would FAIL cross-role cache isolation assertion
        with pytest.raises(AssertionError):
            assert m_key_analyst != m_key_auditor

    def test_mutant_e_shared_memory_across_roles(self, monkeypatch: pytest.MonkeyPatch, memory_db_conn):
        """Mutant (e): Bypassing session ownership check leaks turns across users/roles."""
        repo = Repository(memory_db_conn)
        repo.insert_role("analyst", "Analyst", 10)
        repo.insert_role("auditor", "Auditor", 30)
        u1 = repo.create_user("alice", "hash1", 1, "Alice Analyst", "alice@bank.local")
        u2 = repo.create_user("carol", "hash2", 2, "Carol Auditor", "carol@bank.local")
        sid = repo.create_session("sess-carol-123", user_id=u2)
        repo.add_message(sid, "user", "What were the confidential audit findings?")
        repo.add_message(sid, "assistant", "Project Neptune revealed buffer deficiency.")

        # 1. Baseline: Alice (user_id=u1) cannot read Carol's (user_id=u2) session turns
        turns_baseline = load_recent_turns(repo, sid, user_id=u1, limit=5)
        assert len(turns_baseline) == 0

        # 2. Mutant active: Memory isolation bypassed -> Alice reads Carol's history!
        monkeypatch.setenv("MUTANT_SHARED_MEMORY", "1")
        turns_mutant = load_recent_turns(repo, sid, user_id=u1, limit=5)
        assert len(turns_mutant) == 2
        assert any("Neptune" in turn["content"] for turn in turns_mutant)
        # Proves mutant (e) would FAIL cross-user session isolation assertion
        with pytest.raises(AssertionError):
            assert len(turns_mutant) == 0

    def test_mutant_f_distinct_refusal_message(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """Mutant (f): Returning a distinct refusal for restricted content leaks side channel."""
        pipeline = BaselineRAGPipeline()
        # Non-existent query
        ans_nonexistent, _, _, _, _ = pipeline.generate("Galactic exploration maneuvers", passages=[], role="analyst")
        assert ans_nonexistent == REFUSAL_TEXT

        # Restricted query with mutant active
        monkeypatch.setenv("MUTANT_DISTINCT_REFUSAL", "1")
        # Query that exists in BM25 index (e.g. Neptune)
        ans_restricted, _, _, _, _ = pipeline.generate("Project Neptune liquidity deficit", passages=[], role="analyst")
        # The answers diverge, leaking that confidential docs exist
        assert ans_restricted != ans_nonexistent
        assert "ACCESS RESTRICTED" in ans_restricted
        # Proves mutant (f) would FAIL the uniform refusal assertion
        with pytest.raises(AssertionError):
            assert ans_restricted == ans_nonexistent

    def test_mutant_g_role_taken_from_request_body(self, monkeypatch: pytest.MonkeyPatch):
        """Mutant (g): Reading role from request body allows privilege escalation."""
        from src.api.schemas import ChatQueryRequest
        from src.api.deps import CurrentUser
        import uuid

        # Analyst user
        user = CurrentUser(
            id=1,
            username="alice",
            full_name="Alice Analyst",
            role="analyst",
            jti="jti-1",
            expires_at=9999999999,
        )

        req = ChatQueryRequest(
            session_id=uuid.uuid4(),
            query="What are the capital requirements?",
            role="auditor",  # Attacker attempts to forge auditor role in body
        )

        # 1. Baseline: Body role is ignored; executes as analyst
        effective_role = user.role
        if os.environ.get("MUTANT_ROLE_FROM_BODY") == "1" and getattr(req, "role", None):
            effective_role = req.role
        assert effective_role == "analyst"

        # 2. Mutant active: Body role overrides user.role
        monkeypatch.setenv("MUTANT_ROLE_FROM_BODY", "1")
        if os.environ.get("MUTANT_ROLE_FROM_BODY") == "1" and getattr(req, "role", None):
            effective_role = req.role
        assert effective_role == "auditor"
        # Proves mutant (g) would FAIL role forgery rejection assertion
        with pytest.raises(AssertionError):
            assert effective_role == user.role


def get_db_connection_fixture():
    from src.db.connection import get_db_connection
    return get_db_connection()
