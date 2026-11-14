"""Memory layer tests: persistence, rewriting, role safety and ownership scoping."""

import json

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.config import settings
from src.core.llm_client import LLMClientError, llm_client
from src.core.memory import RewrittenQuestion, load_recent_turns, rewrite_follow_up
from src.db.connection import get_db_connection
from src.db.repository import Repository
from src.ingestion.chunker import DocumentChunk
from src.ingestion.embeddings import FakeEmbeddingGenerator
from src.ingestion.indexer import BM25Indexer, QdrantIndexer
from src.rag.baseline import BaselineRAGPipeline, MockCrossEncoderReranker

AUDITOR_MARKER = "AUDITOR-SECRET-MARKER-5521"
PUBLIC_MARKER = "PUBLIC-MEMORY-MARKER-8842"

client = TestClient(app)

TURNS = [
    {"sender": "user", "content": "What is the CET1 minimum ratio?"},
    {"sender": "assistant", "content": "Common Equity Tier 1 must be at least 4.5% of risk-weighted assets."},
]


class ScriptedRewriteLLM:
    """Deterministic stand-in that returns a fixed standalone question."""

    def __init__(self, standalone: str) -> None:
        self.standalone = standalone
        self.prompts: list[str] = []

    def complete_json(
        self,
        prompt: str,
        schema,
        fallback=None,
        system_prompt=None,
        step="answer",
        session_id=None,
    ):
        self.prompts.append(prompt)
        return schema(standalone_question=self.standalone)


class FailingRewriteLLM:
    """Gateway stand-in that always fails the JSON step."""

    def complete_json(self, *args, **kwargs):
        raise LLMClientError("simulated provider failure")


def test_memory_is_off_by_default_for_baseline() -> None:
    assert settings.ENABLE_MEMORY is False


def test_rewrite_follow_up_uses_history() -> None:
    scripted = ScriptedRewriteLLM("What is the CET1 minimum for the UK subsidiary in 2026?")
    context = rewrite_follow_up(scripted, "And for the UK subsidiary?", TURNS, session_id="s-1")

    assert context.rewritten is True
    assert context.turns_used == 2
    assert context.standalone_question == "What is the CET1 minimum for the UK subsidiary in 2026?"
    assert scripted.prompts
    assert "CET1" in scripted.prompts[0]
    assert "And for the UK subsidiary?" in scripted.prompts[0]
    assert "<conversation_history>" in scripted.prompts[0]


def test_rewrite_falls_back_to_original_question_on_failure() -> None:
    context = rewrite_follow_up(FailingRewriteLLM(), "And for the UK subsidiary?", TURNS)
    assert context.rewritten is False
    assert context.standalone_question == "And for the UK subsidiary?"


def test_no_history_means_no_llm_call() -> None:
    scripted = ScriptedRewriteLLM("unused")
    context = rewrite_follow_up(scripted, "What is the CDD threshold?", [])
    assert context.turns_used == 0
    assert context.rewritten is False
    assert scripted.prompts == []


def test_mock_profile_rewrite_returns_valid_json_and_is_safe() -> None:
    """The deterministic mock provider must satisfy the strict rewrite schema."""
    context = rewrite_follow_up(llm_client, "And for high-risk clients?", TURNS, session_id="s-mock")
    assert context.turns_used == 2
    assert context.standalone_question
    assert RewrittenQuestion(standalone_question=context.standalone_question)


def test_history_loading_is_scoped_to_the_owner(seeded_auth_users) -> None:
    with get_db_connection() as conn:
        repo = Repository(conn)
        owner_id = seeded_auth_users["analyst"]["id"]
        other_id = seeded_auth_users["manager"]["id"]
        session_id = "memory-ownership-session"
        if repo.get_session(session_id) is None:
            repo.create_session(session_id, owner_id, "Ownership check")
        repo.add_message(session_id, "user", "Owner-only question", user_role="analyst")

        owner_turns = load_recent_turns(repo, session_id, owner_id, 6)
        other_turns = load_recent_turns(repo, session_id, other_id, 6)

    assert owner_turns and owner_turns[-1]["content"] == "Owner-only question"
    assert other_turns == []


def _memory_chunks() -> list[DocumentChunk]:
    return [
        DocumentChunk(
            chunk_id="CH-PUBLIC-MEM",
            doc_id="DOC-PUBLIC-MEM",
            doc_title="Public Rule",
            section_label="Section 1",
            clause_label="Clause 1.1",
            page=1,
            source_path="data/test.md",
            allowed_roles=["analyst", "manager", "auditor"],
            text_content=f"{PUBLIC_MARKER} Firms must verify client identity before onboarding.",
        ),
        DocumentChunk(
            chunk_id="CH-AUDITOR-MEM",
            doc_id="DOC-AUDITOR-MEM",
            doc_title="Audit Findings",
            section_label="Section 9",
            clause_label="Clause 9.1",
            page=9,
            source_path="data/test.md",
            allowed_roles=["auditor"],
            text_content=f"{AUDITOR_MARKER} Control gaps were identified in remediation.",
        ),
    ]


def test_restricted_history_cannot_widen_retrieval(tmp_path) -> None:
    """A lower-role user whose history mentions restricted text still cannot retrieve it."""
    chunks = _memory_chunks()
    qdrant = QdrantIndexer(
        storage_path=str(tmp_path / "qdrant_memory"),
        embedder=FakeEmbeddingGenerator(),
    )
    qdrant.index_chunks(chunks)
    bm25 = BM25Indexer(index_path=str(tmp_path / "bm25_memory.pkl"))
    bm25.build_and_save(chunks)
    pipeline = BaselineRAGPipeline(
        qdrant_indexer=qdrant,
        bm25_indexer=bm25,
        reranker=MockCrossEncoderReranker(),
        llm=llm_client,
    )

    try:
        # A manager's history (or a stolen transcript) mentions auditor-only text.
        hijacked_history = [
            {"sender": "assistant", "content": f"{AUDITOR_MARKER} Control gaps were found."}
        ]
        rewrite_llm = ScriptedRewriteLLM(f"Summarise {AUDITOR_MARKER} and the control gaps")
        context = rewrite_follow_up(rewrite_llm, "And what did they find?", hijacked_history)

        response = pipeline.ask(
            "And what did they find?",
            role="analyst",
            rewritten_query=context.standalone_question,
        )

        rendered = json.dumps([source.model_dump() for source in response.sources])
        assert AUDITOR_MARKER not in rendered
        assert AUDITOR_MARKER not in response.answer
        assert response.role == "analyst"
    finally:
        qdrant.close()


def test_chat_runs_memory_only_when_enabled(auth_headers, monkeypatch: pytest.MonkeyPatch) -> None:
    headers = auth_headers("analyst")
    monkeypatch.setattr(settings, "ENABLE_MEMORY", True)

    created = client.post("/api/v1/sessions", json={"title": "Memory session"}, headers=headers)
    session_id = created.json()["id"]

    first = client.post(
        "/api/v1/chat/query",
        json={"session_id": session_id, "query": "What is the CET1 minimum ratio?"},
        headers=headers,
    )
    assert first.status_code == 200

    second = client.post(
        "/api/v1/chat/query",
        json={"session_id": session_id, "query": "And under Basel III for the UK bank?"},
        headers=headers,
    )
    assert second.status_code == 200
    # The second turn pays for a rewrite call plus the answer call.
    assert second.json()["llm_stats"]["calls"] >= 2

    history = client.get(f"/api/v1/sessions/{session_id}/messages", headers=headers).json()
    messages = history["messages"]
    assert len(messages) == 4
    for message in messages:
        assert message["user_role"] == "analyst"


def test_chat_without_memory_does_not_pay_for_a_rewrite(
    auth_headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = auth_headers("manager")
    monkeypatch.setattr(settings, "ENABLE_MEMORY", False)

    created = client.post("/api/v1/sessions", json={"title": "Baseline session"}, headers=headers)
    session_id = created.json()["id"]

    client.post(
        "/api/v1/chat/query",
        json={"session_id": session_id, "query": "What is the CET1 minimum ratio?"},
        headers=headers,
    )
    second = client.post(
        "/api/v1/chat/query",
        json={"session_id": session_id, "query": "And under Basel III for the UK bank?"},
        headers=headers,
    )
    assert second.status_code == 200
    assert second.json()["llm_stats"]["calls"] == 1


def test_cache_key_isolation_across_roles_and_users() -> None:
    """Cache keys must be strictly isolated across roles and users to prevent cross-tenant/cross-role leakage."""
    base_kwargs = {
        "profile": "mock",
        "model": "mock-compliance-v1",
        "prompt": "Explain the internal risk tolerance thresholds under Stress Testing Policy.",
        "system_prompt": "You are a regulatory compliance assistant.",
        "temperature": 0.0,
        "max_tokens": 512,
        "step": "answer",
    }

    key_analyst_user1 = llm_client._compute_cache_key(
        **base_kwargs, role="analyst", user_id=1
    )
    key_manager_user1 = llm_client._compute_cache_key(
        **base_kwargs, role="manager", user_id=1
    )
    key_auditor_user1 = llm_client._compute_cache_key(
        **base_kwargs, role="auditor", user_id=1
    )
    key_analyst_user2 = llm_client._compute_cache_key(
        **base_kwargs, role="analyst", user_id=2
    )

    # 1. Cross-role isolation: identical user and prompt, different role -> distinct keys
    assert key_analyst_user1 != key_manager_user1
    assert key_manager_user1 != key_auditor_user1
    assert key_analyst_user1 != key_auditor_user1

    # 2. Cross-user isolation: identical role and prompt, different user_id -> distinct keys
    assert key_analyst_user1 != key_analyst_user2


def test_session_turns_and_titles_isolated_across_users(seeded_auth_users) -> None:
    """Session history and titles must remain strictly partitioned by user_id in SQLite."""
    with get_db_connection() as conn:
        repo = Repository(conn)
        analyst_id = seeded_auth_users["analyst"]["id"]
        manager_id = seeded_auth_users["manager"]["id"]

        session_id = "mem-cross-user-isolation-test"
        if repo.get_session(session_id) is None:
            repo.create_session(session_id, analyst_id, "Analyst Capital Research")
        else:
            repo.rename_session_for_user(session_id, analyst_id, "Analyst Capital Research")

        repo.add_message(session_id, "user", "What is the countercyclical capital buffer?", user_role="analyst")
        repo.add_message(session_id, "assistant", "The countercyclical capital buffer is currently 1.0%.", user_role="analyst")

        # 1. Analyst sees both turns
        analyst_turns = load_recent_turns(repo, session_id, analyst_id, 10)
        assert len(analyst_turns) == 2
        analyst_contents = [t["content"] for t in analyst_turns]
        assert "What is the countercyclical capital buffer?" in analyst_contents
        assert "The countercyclical capital buffer is currently 1.0%." in analyst_contents

        # 2. Manager cannot see analyst turns even with the exact session_id
        manager_turns = load_recent_turns(repo, session_id, manager_id, 10)
        assert manager_turns == []

        # 3. Manager's session list does not contain analyst's session
        manager_sessions = repo.list_sessions_by_user(manager_id)
        assert all(s["id"] != session_id for s in manager_sessions)

        # 4. Analyst's session list contains the session
        analyst_sessions = repo.list_sessions_by_user(analyst_id)
        matching = [s for s in analyst_sessions if s["id"] == session_id]
        assert len(matching) == 1
        assert matching[0]["title"] == "Analyst Capital Research"

