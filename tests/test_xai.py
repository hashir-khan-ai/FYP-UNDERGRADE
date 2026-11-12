"""Phase 6A tests: structure-aware heading_path, citation validation, verbatim snippets,
safe reasoning trace, audit columns, leakage across XAI fields, and flag-off parity.

All tests run under LLM_PROFILE=mock with zero external network calls.
"""

import json
from typing import Any

import pytest

from src.api.deps import CurrentUser
from src.api.routes import audit_logs, chat_query, create_session
from src.api.schemas import ChatQueryRequest, SessionCreateRequest
from src.config import settings
from src.core.llm_client import LLMResponse, ResilientLLMClient
from src.core.xai import (
    MAX_QUOTE_SNIPPET_CHARS,
    build_heading_path,
    build_safe_reasoning_trace,
    extract_candidate_chunk_ids,
    extract_verbatim_snippet,
    filter_passages_for_citations,
    validate_cited_chunks,
)
from src.ingestion.chunker import ClauseAwareChunker, DocumentChunk
from src.ingestion.embeddings import FakeEmbeddingGenerator
from src.ingestion.indexer import BM25Indexer, QdrantIndexer, build_indexable_text
from src.ingestion.loaders import LoadedDocument, LoadedPage
from src.rag.baseline import BaselineRAGPipeline, MockCrossEncoderReranker

PUBLIC_MARKER = "PUBLIC-XAI-ALPHA-101"
MANAGER_MARKER = "MANAGER-XAI-BRAVO-202"
AUDITOR_MARKER = "AUDITOR-XAI-CHARLIE-303"


# ---------------------------------------------------------------------------
# B1: Structure-aware heading_path & idempotent re-ingestion
# ---------------------------------------------------------------------------


def test_chunker_builds_hierarchical_heading_path() -> None:
    """ClauseAwareChunker builds 'Part > Section > Subsection' heading paths."""
    raw_text = (
        "Part 4 Governance\n"
        "4.2 Board Voting\n"
        "4.2.3 Plurality rule\n"
        "Decisions of the committee require a simple plurality of voting members present "
        "at a quorate meeting of the board compliance committee.\n"
    )
    doc = LoadedDocument(
        file_path="synthetic/gov.md",
        doc_id="DOC-GOV",
        title="Governance Handbook",
        allowed_roles=["analyst", "manager", "auditor"],
        pages=[LoadedPage(page_number=3, content=raw_text)],
    )
    chunker = ClauseAwareChunker()
    chunks = chunker.chunk_document(doc)

    assert len(chunks) == 1
    assert chunks[0].heading_path == "Part 4 Governance > 4.2 Board Voting > 4.2.3 Plurality rule"
    assert chunks[0].clause_label == "4.2.3 Plurality rule"


def test_enable_heading_path_controls_indexable_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_indexable_text includes heading_path when ENABLE_HEADING_PATH=True and omits when False."""
    chunk = DocumentChunk(
        chunk_id="CH-HP-001",
        doc_id="DOC-HP",
        doc_title="Basel III",
        section_label="Section 1",
        clause_label="1.1",
        page=1,
        source_path="synthetic/basel.md",
        allowed_roles=["analyst"],
        text_content="Banks must hold 4.5% CET1.",
        heading_path="Part 1 > Section 1 > 1.1 Minimum CET1",
    )

    monkeypatch.setattr(settings, "ENABLE_HEADING_PATH", True)
    with_hp = build_indexable_text(chunk)
    assert with_hp.startswith("Part 1 > Section 1 > 1.1 Minimum CET1\n")
    assert "Banks must hold 4.5% CET1." in with_hp

    monkeypatch.setattr(settings, "ENABLE_HEADING_PATH", False)
    without_hp = build_indexable_text(chunk)
    assert without_hp == "Banks must hold 4.5% CET1."


def test_heading_path_idempotent_reingestion(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-ingesting the same chunks with heading_path keeps Qdrant and BM25 counts identical."""
    monkeypatch.setattr(settings, "ENABLE_HEADING_PATH", True)
    chunks = [
        DocumentChunk(
            chunk_id="CH-IDEMP-001",
            doc_id="DOC-IDEMP",
            doc_title="Capital Rules",
            section_label="Part 2 > 2.1",
            clause_label="2.1.1",
            page=2,
            source_path="synthetic/cap.md",
            allowed_roles=["analyst", "manager", "auditor"],
            text_content="Minimum Tier 1 capital ratio is 6.0%.",
            heading_path="Part 2 > 2.1 > 2.1.1 Tier 1 Ratio",
        )
    ]

    qdrant = QdrantIndexer(str(tmp_path / "qdrant"), embedder=FakeEmbeddingGenerator())
    bm25 = BM25Indexer(str(tmp_path / "bm25.pkl"))
    try:
        qdrant.index_chunks(chunks)
        bm25.build_and_save(chunks)
        first_count = qdrant.count()

        # Re-ingest identical chunk set
        qdrant.index_chunks(chunks)
        bm25.build_and_save(chunks)
        second_count = qdrant.count()

        assert first_count == 1
        assert second_count == 1
        search_res = qdrant.search("Tier 1 capital ratio", role="analyst", top_k=5)
        assert len(search_res.hits) == 1
        assert search_res.hits[0]["heading_path"] == "Part 2 > 2.1 > 2.1.1 Tier 1 Ratio"
    finally:
        qdrant.close()


# ---------------------------------------------------------------------------
# B2: Citation validation, invalid chunk_id dropping, verbatim quote_snippet
# ---------------------------------------------------------------------------


def test_validate_cited_chunks_drops_unknown_and_restricted_ids() -> None:
    """Server-side citation validator drops hallucinated or role-restricted chunk IDs."""
    context_passages = [
        {
            "chunk_id": "CH-ALLOWED-1",
            "allowed_roles": ["analyst", "manager", "auditor"],
            "text_content": "Permitted passage text.",
        },
        {
            "chunk_id": "CH-RESTRICTED-MGR",
            "allowed_roles": ["manager", "auditor"],
            "text_content": "Manager-only passage that should never be cited by analyst.",
        },
    ]
    candidate_ids = ["CH-ALLOWED-1", "CH-HALLUCINATED-999", "CH-RESTRICTED-MGR"]

    valid_ids, dropped = validate_cited_chunks(
        candidate_ids=candidate_ids,
        context_passages=context_passages,
        role="analyst",
    )

    assert valid_ids == ["CH-ALLOWED-1"]
    assert dropped == 2

    kept = filter_passages_for_citations(context_passages, valid_ids, role="analyst")
    assert len(kept) == 1
    assert kept[0]["chunk_id"] == "CH-ALLOWED-1"


def test_verbatim_quote_snippet_is_bounded_and_exact_substring() -> None:
    """quote_snippet is at most 200 characters and appears verbatim in the passage."""
    long_passage = (
        "Regulated banking institutions must maintain a Common Equity Tier 1 capital ratio "
        "of at least 4.5 percent of risk-weighted assets at all times, supplemented by a "
        "capital conservation buffer of 2.5 percent and counter-cyclical buffers as set "
        "by the Financial Policy Committee."
    )
    assert len(long_passage) > MAX_QUOTE_SNIPPET_CHARS

    snippet = extract_verbatim_snippet(long_passage)
    assert len(snippet) <= MAX_QUOTE_SNIPPET_CHARS
    assert snippet in long_passage


def test_pipeline_drops_invalid_citations_and_filters_sources_when_xai_enabled(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ENABLE_XAI_OUTPUT=True, hallucinated chunk_ids are dropped and counted."""
    monkeypatch.setattr(settings, "ENABLE_XAI_OUTPUT", True)

    class HallucinatingCitationLLM(ResilientLLMClient):
        def complete(self, prompt: str, **kwargs: Any) -> LLMResponse:
            return LLMResponse(
                content=(
                    "The minimum CET1 ratio is 4.5%.\n"
                    "Supporting Chunks: CH-REAL-001, CH-FAKE-999, CH-AUDITOR-SECRET"
                ),
                prompt_tokens=20,
                completion_tokens=15,
                cached=False,
                latency_ms=1.0,
                model="mock",
                profile="mock",
            )

    chunks = [
        DocumentChunk(
            chunk_id="CH-REAL-001",
            doc_id="DOC-BASEL",
            doc_title="Basel III",
            section_label="Part 1",
            clause_label="1.1",
            page=1,
            source_path="synthetic/basel.md",
            allowed_roles=["analyst", "manager", "auditor"],
            text_content="The minimum CET1 ratio is 4.5% of risk-weighted assets.",
            heading_path="Part 1 > 1.1 Minimum CET1",
        ),
        DocumentChunk(
            chunk_id="CH-REAL-002",
            doc_id="DOC-BASEL",
            doc_title="Basel III",
            section_label="Part 1",
            clause_label="1.2",
            page=2,
            source_path="synthetic/basel.md",
            allowed_roles=["analyst", "manager", "auditor"],
            text_content="The Tier 1 capital ratio is 6.0%.",
            heading_path="Part 1 > 1.2 Minimum Tier 1",
        ),
    ]
    qdrant = QdrantIndexer(str(tmp_path / "qdrant"), embedder=FakeEmbeddingGenerator())
    qdrant.index_chunks(chunks)
    bm25 = BM25Indexer(str(tmp_path / "bm25.pkl"))
    bm25.build_and_save(chunks)

    pipeline = BaselineRAGPipeline(
        qdrant_indexer=qdrant,
        bm25_indexer=bm25,
        reranker=MockCrossEncoderReranker(),
        llm=HallucinatingCitationLLM(),
    )
    try:
        res = pipeline.ask("What is the minimum CET1 ratio?", role="analyst")
        assert res.chunk_ids_used == ["CH-REAL-001"]
        assert res.citations_dropped == 2
        # Only cited kept passage is included in sources when ENABLE_XAI_OUTPUT=True
        assert [s.chunk_id for s in res.sources] == ["CH-REAL-001"]
        assert res.sources[0].heading_path == "Part 1 > 1.1 Minimum CET1"
        assert res.sources[0].quote_snippet in chunks[0].text_content
    finally:
        qdrant.close()


# ---------------------------------------------------------------------------
# B3: Safe user-facing reasoning trace
# ---------------------------------------------------------------------------


def test_safe_reasoning_trace_contains_ordered_steps_and_no_sensitive_data() -> None:
    """build_safe_reasoning_trace emits 6 ordered steps without prompts, passages, or restricted counts."""
    trace = build_safe_reasoning_trace(
        question_rewritten=True,
        route="SINGLE_SEARCH",
        passages_retrieved=5,
        passages_kept=3,
        grader_path="llm_grade",
        retry_used=False,
        limits_hit=False,
    )
    assert len(trace) == 6
    assert trace[0] == "Step 1: Question rewritten: yes."
    assert trace[1] == "Step 2: Route: SINGLE_SEARCH."
    assert trace[2] == "Step 3: Passages retrieved: 5; kept: 3."
    assert trace[3] == "Step 4: Grader path: llm_grade."
    assert trace[4] == "Step 5: Retry used: no."
    assert trace[5] == "Step 6: Self-limits hit: no."

    joined = " ".join(trace).lower()
    assert "excluded by role" not in joined
    assert "authoritative_documents" not in joined


# ---------------------------------------------------------------------------
# B4 & B6: API response, audit columns, flag-off parity, and XAI leakage matrix
# ---------------------------------------------------------------------------


def test_api_xai_output_and_audit_columns(
    monkeypatch: pytest.MonkeyPatch,
    seeded_auth_users,
) -> None:
    """API returns structured XAI fields and records citation_count, citations_dropped, heading_path_enabled in audit_log."""
    monkeypatch.setattr(settings, "ENABLE_XAI_OUTPUT", True)
    monkeypatch.setattr(settings, "ENABLE_HEADING_PATH", True)

    analyst_info = seeded_auth_users["analyst"]
    analyst = CurrentUser(
        id=analyst_info["id"],
        username=analyst_info["username"],
        full_name=analyst_info["full_name"],
        role="analyst",
        jti="jti-analyst-xai",
        expires_at=9999999999,
    )
    auditor_info = seeded_auth_users["auditor"]
    auditor = CurrentUser(
        id=auditor_info["id"],
        username=auditor_info["username"],
        full_name=auditor_info["full_name"],
        role="auditor",
        jti="jti-auditor-xai",
        expires_at=9999999999,
    )

    session = create_session(SessionCreateRequest(title="XAI Audit Test"), analyst)
    res = chat_query(
        ChatQueryRequest(session_id=session.id, query="What is the minimum capital ratio?"),
        analyst,
    )

    assert res.route == "SINGLE_SEARCH"
    assert res.heading_path_enabled is True
    assert isinstance(res.citations_dropped, int)
    assert "total_ms" in res.timings
    assert len(res.reasoning_trace) == 6
    assert res.reasoning_trace[0].startswith("Step 1: Question rewritten:")

    for cite in res.citations:
        assert cite.chunk_id != ""
        assert cite.doc_title != ""
        assert cite.heading_path != ""
        assert len(cite.quote_snippet) <= MAX_QUOTE_SNIPPET_CHARS

    logs = audit_logs(limit=10, user_id=analyst.id, start_date=None, user=auditor)
    matching = [entry for entry in logs if entry.audit_id == res.audit_id]
    assert len(matching) == 1
    entry = matching[0]
    assert entry.citation_count == len(res.citations)
    assert entry.citations_dropped == res.citations_dropped
    assert entry.heading_path_enabled is True
    # Audit summary must never expose raw query_text or response_text
    dumped = entry.model_dump()
    assert "query_text" not in dumped
    assert "response_text" not in dumped


def test_xai_flag_off_preserves_phase5_behaviour(
    monkeypatch: pytest.MonkeyPatch,
    seeded_auth_users,
) -> None:
    """When ENABLE_XAI_OUTPUT=False, reasoning_trace matches the Phase 3/4/5 format."""
    monkeypatch.setattr(settings, "ENABLE_XAI_OUTPUT", False)
    monkeypatch.setattr(settings, "ENABLE_ADAPTIVE_ROUTER", False)

    analyst_info = seeded_auth_users["analyst"]
    analyst = CurrentUser(
        id=analyst_info["id"],
        username=analyst_info["username"],
        full_name=analyst_info["full_name"],
        role="analyst",
        jti="jti-analyst-off",
        expires_at=9999999999,
    )
    session = create_session(SessionCreateRequest(title="Flag off test"), analyst)
    res = chat_query(
        ChatQueryRequest(session_id=session.id, query="What is the minimum capital ratio?"),
        analyst,
    )

    assert res.reasoning_trace[0] == "Step 1: Authenticated as role 'analyst'."
    assert any("excluded by role" in step for step in res.reasoning_trace)


def test_xai_leakage_across_all_new_fields_and_roles(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    seeded_auth_users,
) -> None:
    """Leakage across answer, citations (doc_title, heading_path, quote_snippet), and reasoning_trace is 0.00%."""
    import src.api.routes as routes

    monkeypatch.setattr(settings, "ENABLE_XAI_OUTPUT", True)
    monkeypatch.setattr(settings, "ENABLE_CORRECTIVE_GRADER", True)
    monkeypatch.setattr(settings, "ENABLE_HEADING_PATH", True)

    chunks = [
        DocumentChunk(
            chunk_id="CH-PUB",
            doc_id="DOC-PUB",
            doc_title="Public Banking Rule",
            section_label="Part 1",
            clause_label="1.1",
            page=1,
            source_path="synthetic/pub.md",
            allowed_roles=["analyst", "manager", "auditor"],
            text_content=f"{PUBLIC_MARKER} Standard customer due diligence applies.",
            heading_path=f"Part 1 > 1.1 {PUBLIC_MARKER}",
        ),
        DocumentChunk(
            chunk_id="CH-MGR",
            doc_id="DOC-MGR",
            doc_title=f"Manager Policy {MANAGER_MARKER}",
            section_label="Part 2",
            clause_label="2.1",
            page=2,
            source_path="synthetic/mgr.md",
            allowed_roles=["manager", "auditor"],
            text_content=f"{MANAGER_MARKER} Escalate material breaches to committee.",
            heading_path=f"Part 2 > 2.1 {MANAGER_MARKER}",
        ),
        DocumentChunk(
            chunk_id="CH-AUD",
            doc_id="DOC-AUD",
            doc_title=f"Audit Report {AUDITOR_MARKER}",
            section_label="Part 3",
            clause_label="3.1",
            page=3,
            source_path="synthetic/aud.md",
            allowed_roles=["auditor"],
            text_content=f"{AUDITOR_MARKER} Internal audit remediation findings.",
            heading_path=f"Part 3 > 3.1 {AUDITOR_MARKER}",
        ),
    ]

    qdrant = QdrantIndexer(str(tmp_path / "qdrant"), embedder=FakeEmbeddingGenerator())
    qdrant.index_chunks(chunks)
    bm25 = BM25Indexer(str(tmp_path / "bm25.pkl"))
    bm25.build_and_save(chunks)
    pipeline = BaselineRAGPipeline(
        qdrant_indexer=qdrant,
        bm25_indexer=bm25,
        reranker=MockCrossEncoderReranker(),
        llm=ResilientLLMClient(),
    )
    monkeypatch.setattr(routes, "baseline_pipeline", pipeline)

    forbidden_by_role = {
        "analyst": {MANAGER_MARKER, AUDITOR_MARKER},
        "manager": {AUDITOR_MARKER},
        "auditor": set(),
    }
    probes = [
        "What customer due diligence applies?",
        "How do we escalate material breaches to the committee?",
        "What are the internal audit remediation findings?",
    ]

    leaked_cells = 0
    total_cells = 0
    try:
        for role in ("analyst", "manager", "auditor"):
            u_info = seeded_auth_users[role]
            user = CurrentUser(
                id=u_info["id"],
                username=u_info["username"],
                full_name=u_info["full_name"],
                role=role,
                jti=f"jti-{role}",
                expires_at=9999999999,
            )
            session = create_session(SessionCreateRequest(title=f"XAI leak {role}"), user)
            for q in probes:
                total_cells += 1
                res = chat_query(ChatQueryRequest(session_id=session.id, query=q), user)
                payload_str = res.model_dump_json()
                if any(marker in payload_str for marker in forbidden_by_role[role]):
                    leaked_cells += 1
        assert total_cells == 9
        assert leaked_cells == 0
    finally:
        qdrant.close()
