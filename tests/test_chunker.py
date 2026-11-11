"""Unit tests for the clause-aware hierarchical chunker and loaders."""

from src.ingestion.chunker import ClauseAwareChunker, DocumentChunk
from src.ingestion.loaders import DocumentLoader, LoadedDocument, LoadedPage


def test_chunker_extracts_clauses_and_sections() -> None:
    """Verify that hierarchical headers are detected and mapped to clauses."""
    sample_text = """# FCA Handbook - Conduct of Business
**Document ID:** DOC-TEST-001
**Permitted Roles:** ["analyst", "manager"]

## Section 1: Customer Communications

### Clause BCOBS-1.1 (Fair Treatment)
A firm must pay due regard to the interests of its customers and treat them fairly.

### Clause BCOBS-1.2 (Clarity of Fees)
All charges and interest rates must be clearly presented before contract execution.
"""
    doc = LoadedDocument(
        file_path="dummy/path.md",
        doc_id="DOC-TEST-001",
        title="FCA Handbook",
        pages=[LoadedPage(page_number=1, content=sample_text)],
        allowed_roles=["analyst", "manager"],
    )

    chunker = ClauseAwareChunker()
    chunks = chunker.chunk_document(doc)

    assert len(chunks) == 2
    c1, c2 = chunks[0], chunks[1]

    assert c1.doc_id == "DOC-TEST-001"
    assert "BCOBS-1.1" in c1.chunk_id or "BCOBS-1.1" in c1.clause_label
    assert c1.allowed_roles == ["analyst", "manager"]
    assert "treat them fairly" in c1.text_content

    assert c2.doc_id == "DOC-TEST-001"
    assert "BCOBS-1.2" in c2.chunk_id or "BCOBS-1.2" in c2.clause_label
    assert "charges and interest rates" in c2.text_content


def test_chunker_preserves_tables_intact() -> None:
    """Verify that tabular data is kept within a single contiguous chunk."""
    sample_text = """# Capital Requirements
## Section 2: Capital Thresholds

### Clause BASEL-TAB-1.0 (Capital Table)
The following regulatory ratios apply:

| Capital Tier | Minimum Ratio | Buffer Required |
| --- | --- | --- |
| CET1 | 4.5% | 2.5% |
| Tier 1 | 6.0% | 0.0% |
| Total Capital | 8.0% | 2.5% |

All ratios are measured against total Risk-Weighted Assets.
"""
    doc = LoadedDocument(
        file_path="dummy/table.md",
        doc_id="DOC-TAB-001",
        title="Capital Requirements",
        pages=[LoadedPage(page_number=1, content=sample_text)],
    )

    chunker = ClauseAwareChunker()
    chunks = chunker.chunk_document(doc)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert "| Capital Tier | Minimum Ratio |" in chunk.text_content
    assert "| Total Capital | 8.0% |" in chunk.text_content


def test_chunker_fallback_size_split() -> None:
    """Verify that unstructured long text falls back to size-based windowing."""
    long_text = "This is a continuous unstructured legal passage. " * 80
    doc = LoadedDocument(
        file_path="dummy/plain.txt",
        doc_id="DOC-PLAIN-001",
        title="Unstructured Notice",
        pages=[LoadedPage(page_number=1, content=long_text)],
    )

    chunker = ClauseAwareChunker(target_chunk_size=50, max_chunk_size=100, overlap=10)
    chunks = chunker.chunk_document(doc)

    assert len(chunks) > 1
    for c in chunks:
        assert c.doc_id == "DOC-PLAIN-001"
        assert c.token_count > 0


def test_idempotent_chunk_ids() -> None:
    """Verify that running the chunker repeatedly on identical text produces identical chunk IDs."""
    doc = LoadedDocument(
        file_path="dummy/repeat.md",
        doc_id="DOC-REPEAT",
        title="Repeat Doc",
        pages=[LoadedPage(page_number=1, content="## Section A\n### Clause CLAUSE-99\nContent here.")],
    )

    chunker = ClauseAwareChunker()
    run1 = chunker.chunk_document(doc)
    run2 = chunker.chunk_document(doc)

    assert len(run1) == len(run2)
    assert run1[0].chunk_id == run2[0].chunk_id


def test_chunks_carry_required_metadata() -> None:
    """Verify every chunk exposes doc, section/clause, page, source and role tags."""
    doc = LoadedDocument(
        file_path="data/raw/example.md",
        doc_id="DOC-META-001",
        title="Metadata Fixture",
        pages=[
            LoadedPage(
                page_number=1,
                content=(
                    "## Section 1: Onboarding\n"
                    "### Clause META-1.1 (Identity)\n"
                    "Analysts must verify identity.\n"
                ),
            )
        ],
        allowed_roles=["analyst", "manager"],
    )

    chunks = ClauseAwareChunker().chunk_document(doc)
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.chunk_id
    assert chunk.doc_id == "DOC-META-001"
    assert chunk.doc_title == "Metadata Fixture"
    assert chunk.section_label == "Section 1: Onboarding"
    assert chunk.clause_label == "Clause META-1.1 (Identity)"
    assert chunk.page == 1
    assert chunk.source_path == "data/raw/example.md"
    assert chunk.allowed_roles == ["analyst", "manager"]
    assert chunk.text_content
    assert chunk.token_count > 0


def test_loader_prefers_sidecar_roles(tmp_path) -> None:
    """Verify per-document metadata files override inline role tags."""
    source = tmp_path / "sample.md"
    source.write_text(
        "# Sample\n**Permitted Roles:** [\"analyst\"]\n"
        "## Section 1: Test\n### Clause S-1.1\nSecret text.\n",
        encoding="utf-8",
    )
    sidecar = tmp_path / "sample.meta.json"
    sidecar.write_text(
        '{"doc_id": "DOC-SIDECAR", "title": "Sidecar Doc", "allowed_roles": ["auditor"]}',
        encoding="utf-8",
    )

    doc = DocumentLoader.load(source)
    assert doc.doc_id == "DOC-SIDECAR"
    assert doc.title == "Sidecar Doc"
    assert doc.allowed_roles == ["auditor"]
    chunks = ClauseAwareChunker().chunk_document(doc)
    assert chunks[0].allowed_roles == ["auditor"]


def test_chunker_detects_plain_numbered_sections() -> None:
    """Verify non-markdown numbered headings split into clauses."""
    doc = LoadedDocument(
        file_path="plain.txt",
        doc_id="DOC-PLAIN-NUM",
        title="Plain Regulation",
        pages=[
            LoadedPage(
                page_number=1,
                content=(
                    "Section 1: Scope\n"
                    "1.1 Application\n"
                    "This regulation applies to all banks.\n"
                    "1.2 Exemptions\n"
                    "Credit unions are exempt.\n"
                ),
            )
        ],
    )

    chunks = ClauseAwareChunker().chunk_document(doc)
    assert len(chunks) == 2
    assert chunks[0].clause_label == "1.1 Application"
    assert "all banks" in chunks[0].text_content
    assert chunks[1].clause_label == "1.2 Exemptions"

