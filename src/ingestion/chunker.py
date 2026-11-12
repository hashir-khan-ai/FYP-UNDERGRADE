"""Clause-aware hierarchical chunker preserving sections, clauses, and tables.

The chunker deliberately recognises only structural headings: markdown headings
and explicit legal labels such as ``Regulation 27(1)`` or ``Section 4.2``. It
does not treat arbitrary capitalised sentences as headings, which keeps prose
and numbered lists inside their parent clause.
"""

import re
from dataclasses import dataclass

from src.ingestion.loaders import LoadedDocument


@dataclass
class DocumentChunk:
    """A single granular unit of text indexed into vector and BM25 search."""

    chunk_id: str
    doc_id: str
    doc_title: str
    section_label: str
    clause_label: str
    page: int | None
    source_path: str
    allowed_roles: list[str]
    text_content: str
    token_count: int = 0
    heading_path: str = ""

    def __post_init__(self) -> None:
        if not self.heading_path:
            parts: list[str] = []
            if self.section_label:
                parts.append(self.section_label)
            if self.clause_label and self.clause_label != self.section_label:
                parts.append(self.clause_label)
            self.heading_path = " > ".join(parts) if parts else self.doc_title


_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_LEGAL_HEADING = re.compile(
    r"^(?P<label>"
    r"(?:Clause|Regulation|Article|Section|Chapter|Part|Rule)\s+[A-Za-z0-9][^\n]{0,100}"
    r"|\d+(?:\.\d+)*\.?\s+[A-Z(][^\n]{0,100}"
    r")\s*$"
)
_FRONT_MATTER = re.compile(
    r"^(?:\*\*[^*]+\*\*:?.*|[-=]{3,}|#\s+.*|\s*)$"
)


def _classify_heading(text: str) -> str:
    """Return ``clause``, ``section``, ``title`` or ``other`` for a heading."""
    lowered = text.lower()
    if re.match(r"^(clause|regulation|article|rule)\b", lowered):
        return "clause"
    if re.match(r"^(section|chapter|part)\b", lowered):
        return "section"
    if re.match(r"^\d+(?:\.\d+)*\.?\s", lowered):
        return "clause"
    return "other"


def _slug(text: str, fallback_idx: int) -> str:
    """Build a stable, short identifier from a clause or section label."""
    legal = re.search(
        r"\b(?:Clause|Regulation|Article|Section|Chapter|Part|Rule)\s+"
        r"([A-Za-z0-9][A-Za-z0-9.\-/()]*)",
        text,
        re.IGNORECASE,
    )
    if legal:
        clean = re.sub(r"[^A-Za-z0-9.\-]", "", legal.group(1))
        if len(clean) >= 3:
            return clean

    match = re.search(r"[A-Za-z0-9][A-Za-z0-9.\-]*(?:\([0-9A-Za-z]+\))?", text)
    if match:
        clean = re.sub(r"[^A-Za-z0-9.\-]", "", match.group(0))
        if len(clean) >= 3:
            return clean
    clean = re.sub(r"[^A-Za-z0-9]", "_", text)[:30].strip("_")
    return clean or f"chunk_{fallback_idx}"


class ClauseAwareChunker:
    """Split regulatory text by headings and clauses.

    Args:
        target_chunk_size: Target words per chunk when an oversized clause is
            split by paragraph boundaries.
        max_chunk_size: Maximum words kept in one chunk before splitting.
        overlap: Word overlap used when a single oversized passage must be cut.
    """

    def __init__(
        self,
        target_chunk_size: int = 350,
        max_chunk_size: int = 600,
        overlap: int = 50,
    ) -> None:
        self.target_chunk_size = target_chunk_size
        self.max_chunk_size = max_chunk_size
        self.overlap = overlap

    def chunk_document(self, doc: LoadedDocument) -> list[DocumentChunk]:
        """Chunk every page while preserving section, clause, page and roles."""
        chunks: list[DocumentChunk] = []
        used_ids: dict[str, int] = {}

        for page in doc.pages:
            page_chunks = self._chunk_page(doc, page.content, page.page_number, used_ids)
            chunks.extend(page_chunks)

        if not chunks and doc.pages:
            combined = "\n\n".join(p.content for p in doc.pages if p.content.strip())
            if combined.strip() and not self._is_structural_only(combined):
                chunks = self._fallback_size_split(doc, combined, used_ids)

        return chunks

    def _chunk_page(
        self,
        doc: LoadedDocument,
        page_text: str,
        page_number: int,
        used_ids: dict[str, int],
    ) -> list[DocumentChunk]:
        lines = page_text.replace("\r\n", "\n").split("\n")
        chunks: list[DocumentChunk] = []

        current_section = "General Overview"
        current_clause = ""
        heading_levels: dict[int, str] = {}
        buffer: list[str] = []

        def flush() -> None:
            nonlocal buffer
            text = "\n".join(buffer).strip()
            if not text:
                buffer = []
                return
            if self._is_structural_only(text):
                buffer = []
                return
            label = current_clause or current_section
            path_items = [heading_levels[k] for k in sorted(heading_levels)]
            if path_items:
                heading_path = " > ".join(path_items)
            elif current_clause and current_clause != current_section:
                heading_path = f"{current_section} > {current_clause}"
            else:
                heading_path = current_section
            chunks.extend(
                self._create_chunks(
                    doc=doc,
                    page=page_number,
                    section=current_section,
                    clause=current_clause,
                    text=text,
                    used_ids=used_ids,
                    label=label,
                    heading_path=heading_path,
                )
            )
            buffer = []

        index = 0
        while index < len(lines):
            line = lines[index]
            stripped = line.strip()
            is_table_line = stripped.startswith("|") and stripped.endswith("|")

            if is_table_line and not self._is_heading(stripped):
                # Keep the whole contiguous table with the current clause.
                table_rows: list[str] = []
                while index < len(lines):
                    row = lines[index].strip()
                    if row.startswith("|") and row.endswith("|"):
                        table_rows.append(row)
                        index += 1
                    else:
                        break
                buffer.extend(table_rows)
                continue

            heading = self._parse_heading(stripped)
            if heading is not None:
                level, heading_text = heading
                flush()
                if level == 1:
                    # A document title is not a clause boundary.
                    buffer.append(line)
                else:
                    for deeper in [k for k in heading_levels if k >= level]:
                        del heading_levels[deeper]
                    heading_levels[level] = heading_text
                    kind = _classify_heading(heading_text)
                    if kind == "clause":
                        current_clause = heading_text
                    elif kind == "section":
                        current_section = heading_text
                        current_clause = ""
                    else:
                        current_section = heading_text
                        current_clause = ""
                    buffer.append(line)
            else:
                buffer.append(line)
            index += 1

        flush()
        return chunks

    @staticmethod
    def _is_heading(text: str) -> bool:
        return _MARKDOWN_HEADING.match(text) is not None or _LEGAL_HEADING.match(text) is not None

    @staticmethod
    def _parse_heading(text: str) -> tuple[int, str] | None:
        md = _MARKDOWN_HEADING.match(text)
        if md:
            return len(md.group(1)), md.group(2).strip()
        legal = _LEGAL_HEADING.match(text)
        if legal:
            label = legal.group("label").strip()
            lowered = label.lower()
            if re.match(r"^(part|chapter)\b", lowered):
                return 2, label
            if re.match(r"^section\b", lowered):
                return 3, label
            num_match = re.match(r"^(\d+(?:\.\d+)*)\.?\s", label)
            if num_match:
                dots = num_match.group(1).count(".")
                return min(2 + dots, 6), label
            return 4, label
        return None

    @staticmethod
    def _is_front_matter_only(text: str) -> bool:
        """True when a preamble contains only title/metadata lines."""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return True
        return all(_FRONT_MATTER.match(line) for line in lines)

    @staticmethod
    def _is_structural_only(text: str) -> bool:
        """True when text contains only headings, metadata, or separators."""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return True
        return all(
            _MARKDOWN_HEADING.match(line)
            or _LEGAL_HEADING.match(line)
            or _FRONT_MATTER.match(line)
            for line in lines
        )

    def _create_chunks(
        self,
        doc: LoadedDocument,
        page: int,
        section: str,
        clause: str,
        text: str,
        used_ids: dict[str, int],
        label: str,
        heading_path: str = "",
    ) -> list[DocumentChunk]:
        words = text.split()
        if not words:
            return []

        parts = [text] if len(words) <= self.max_chunk_size else self._split_preserving_tables(text)
        chunks: list[DocumentChunk] = []
        for part in parts:
            part_words = part.split()
            if not part_words:
                continue
            slug = _slug(label, len(used_ids) + 1)
            count = used_ids.get(slug, 0) + 1
            used_ids[slug] = count
            suffix = "" if count == 1 else f"_{count}"
            chunks.append(
                DocumentChunk(
                    chunk_id=f"{doc.doc_id}_{slug}{suffix}",
                    doc_id=doc.doc_id,
                    doc_title=doc.title,
                    section_label=section,
                    clause_label=clause or section,
                    page=page,
                    source_path=doc.file_path,
                    allowed_roles=list(doc.allowed_roles),
                    text_content=part.strip(),
                    token_count=len(part_words),
                    heading_path=heading_path,
                )
            )
        return chunks

    def _split_preserving_tables(self, text: str) -> list[str]:
        """Split oversized text on paragraph boundaries without cutting tables."""
        blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
        parts: list[str] = []
        current: list[str] = []
        current_words = 0

        def emit() -> None:
            nonlocal current, current_words
            if current:
                parts.append("\n\n".join(current))
                current = []
                current_words = 0

        for block in blocks:
            block_words = len(block.split())
            is_table = all(
                line.strip().startswith("|") and line.strip().endswith("|")
                for line in block.splitlines()
                if line.strip()
            )
            if is_table and current and current_words + block_words > self.target_chunk_size:
                emit()
            if not is_table and block_words > self.max_chunk_size:
                emit()
                parts.extend(self._window_words(block))
                continue
            if current and current_words + block_words > self.target_chunk_size:
                emit()
            current.append(block)
            current_words += block_words

        emit()
        return parts or [text]

    def _window_words(self, text: str) -> list[str]:
        words = text.split()
        parts: list[str] = []
        start = 0
        while start < len(words):
            end = min(start + self.target_chunk_size, len(words))
            parts.append(" ".join(words[start:end]))
            if end >= len(words):
                break
            start += max(self.target_chunk_size - self.overlap, 1)
        return parts

    def _fallback_size_split(
        self,
        doc: LoadedDocument,
        text: str,
        used_ids: dict[str, int],
    ) -> list[DocumentChunk]:
        """Size-based fallback for documents with no structural headings."""
        chunks: list[DocumentChunk] = []
        words = text.split()
        start = 0
        part = 1
        while start < len(words):
            end = min(start + self.target_chunk_size, len(words))
            sub_text = " ".join(words[start:end])
            chunks.append(
                DocumentChunk(
                    chunk_id=f"{doc.doc_id}_page1_chunk{part}",
                    doc_id=doc.doc_id,
                    doc_title=doc.title,
                    section_label="General Section",
                    clause_label="General Passage",
                    page=doc.pages[0].page_number if doc.pages else None,
                    source_path=doc.file_path,
                    allowed_roles=list(doc.allowed_roles),
                    text_content=sub_text,
                    token_count=len(words[start:end]),
                )
            )
            if end >= len(words):
                break
            start += max(self.target_chunk_size - self.overlap, 1)
            part += 1
        return chunks
