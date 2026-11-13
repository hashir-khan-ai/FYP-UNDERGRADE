"""Document loaders for PDF, HTML, Markdown, and plain text files."""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class LoadedPage:
    """Represents a single page or section of a loaded document."""
    page_number: int
    content: str


@dataclass
class LoadedDocument:
    """Standardized representation of a document loaded from disk."""
    file_path: str
    doc_id: str
    title: str
    pages: list[LoadedPage]
    allowed_roles: list[str] = field(default_factory=lambda: ["analyst", "manager", "auditor"])
    doc_type: str = "REGULATION"
    jurisdiction: str = "UK_FCA"
    version: str = "1.0"
    source_url: str | None = None
    content_origin: str = "original_text"


def _extract_header_metadata(text: str) -> dict[str, Any]:
    """Parse key-value metadata headers commonly placed at the top of markdown files."""
    meta: dict[str, Any] = {}

    doc_id_match = re.search(r"\*\*Document ID:\*\*\s*([^\n\r]+)", text, re.IGNORECASE)
    if doc_id_match:
        meta["doc_id"] = doc_id_match.group(1).strip()

    roles_match = re.search(r"\*\*Permitted Roles:\*\*\s*(\[[^\]]+\])", text, re.IGNORECASE)
    if roles_match:
        try:
            meta["allowed_roles"] = json.loads(roles_match.group(1).strip())
        except Exception:
            pass

    jurisdiction_match = re.search(r"\*\*Jurisdiction:\*\*\s*([^\n\r]+)", text, re.IGNORECASE)
    if jurisdiction_match:
        meta["jurisdiction"] = jurisdiction_match.group(1).strip()

    version_match = re.search(r"\*\*Version:\*\*\s*([^\n\r]+)", text, re.IGNORECASE)
    if version_match:
        meta["version"] = version_match.group(1).strip()

    classification_match = re.search(r"\*\*Classification:\*\*\s*([^\n\r]+)", text, re.IGNORECASE)
    if classification_match:
        meta["classification"] = classification_match.group(1).strip()

    title_match = re.search(r"^#\s+([^\n\r]+)", text, re.MULTILINE)
    if title_match:
        meta["title"] = title_match.group(1).strip()

    return meta


def _load_sidecar_metadata(path: Path) -> dict[str, Any]:
    """Load per-document metadata from a sidecar JSON file when present.

    Supported names are ``<file>.meta.json`` and ``<stem>.meta.json``. Sidecar
    values take precedence over inline document headers so roles are explicitly
    controlled per document.
    """
    candidates = [
        path.with_name(path.name + ".meta.json"),
        path.with_suffix(".meta.json"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"Invalid metadata sidecar {candidate.name}: {exc}") from exc
            if not isinstance(data, dict):
                raise ValueError(f"Metadata sidecar {candidate.name} must contain a JSON object.")
            return data
    return {}


def _merge_metadata(inline: dict[str, Any], sidecar: dict[str, Any]) -> dict[str, Any]:
    merged = dict(inline)
    merged.update({key: value for key, value in sidecar.items() if value is not None})
    if "allowed_roles" in merged and not isinstance(merged["allowed_roles"], list):
        raise ValueError("allowed_roles metadata must be a JSON array.")
    return merged


def _doc_type_from_metadata(meta: dict[str, Any]) -> str:
    explicit = meta.get("doc_type")
    if explicit:
        return str(explicit)
    classification = str(meta.get("classification", "")).lower()
    if "audit" in classification:
        return "CONFIDENTIAL_AUDIT_FINDINGS"
    if "management" in classification or "policy" in classification:
        return "INTERNAL_MANAGEMENT_POLICY"
    if "procedure" in classification or "sop" in classification:
        return "INTERNAL_SOP"
    return "PUBLIC_REGULATION"


class DocumentLoader:
    """Dispatches file loading based on extension (.pdf, .html, .htm, .md, .txt)."""

    @classmethod
    def load(cls, file_path: str | Path) -> LoadedDocument:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Document not found at {path}")

        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return cls._load_pdf(path)
        elif suffix in (".html", ".htm"):
            return cls._load_html(path)
        else:
            return cls._load_text(path)

    @classmethod
    def _load_text(cls, path: Path) -> LoadedDocument:
        content = path.read_text(encoding="utf-8", errors="replace")
        meta = _merge_metadata(_extract_header_metadata(content), _load_sidecar_metadata(path))

        doc_id = meta.get("doc_id", f"DOC-{path.stem.upper()}")
        title = meta.get("title", path.stem.replace("-", " ").title())
        allowed_roles = meta.get("allowed_roles", ["analyst", "manager", "auditor"])
        jurisdiction = meta.get("jurisdiction", "UK_FCA")
        version = str(meta.get("version", "1.0"))
        raw_source = meta.get("source") or meta.get("source_url")
        source_url = str(raw_source) if (raw_source and str(raw_source).startswith(("http://", "https://"))) else None
        content_origin = str(meta.get("content_origin", "original_text"))

        return LoadedDocument(
            file_path=str(path),
            doc_id=doc_id,
            title=title,
            pages=[LoadedPage(page_number=1, content=content)],
            allowed_roles=allowed_roles,
            doc_type=_doc_type_from_metadata(meta),
            jurisdiction=jurisdiction,
            version=version,
            source_url=source_url,
            content_origin=content_origin,
        )

    @classmethod
    def _load_pdf(cls, path: Path) -> LoadedDocument:
        try:
            import pypdf
        except ImportError:
            raise ImportError("pypdf is required to load PDF documents. Install via requirements.txt.")

        reader = pypdf.PdfReader(str(path))
        pages: list[LoadedPage] = []
        full_text = ""

        for idx, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            pages.append(LoadedPage(page_number=idx, content=text))
            full_text += text + "\n"

        meta = _merge_metadata(
            _extract_header_metadata(full_text[:2000]),
            _load_sidecar_metadata(path),
        )
        doc_id = meta.get("doc_id", f"DOC-{path.stem.upper()}")
        title = meta.get("title", path.stem.replace("-", " ").title())
        allowed_roles = meta.get("allowed_roles", ["analyst", "manager", "auditor"])
        raw_source = meta.get("source") or meta.get("source_url")
        source_url = str(raw_source) if (raw_source and str(raw_source).startswith(("http://", "https://"))) else None
        content_origin = str(meta.get("content_origin", "original_text"))

        return LoadedDocument(
            file_path=str(path),
            doc_id=doc_id,
            title=title,
            pages=pages,
            allowed_roles=allowed_roles,
            doc_type=_doc_type_from_metadata(meta),
            jurisdiction=meta.get("jurisdiction", "UK_FCA"),
            version=str(meta.get("version", "1.0")),
            source_url=source_url,
            content_origin=content_origin,
        )

    @classmethod
    def _load_html(cls, path: Path) -> LoadedDocument:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            raise ImportError("beautifulsoup4 is required to load HTML documents. Install via requirements.txt.")

        raw_html = path.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(raw_html, "html.parser")

        # Convert HTML tables to clean markdown-like table text
        for table in soup.find_all("table"):
            rows: list[str] = []
            for tr in table.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if cells:
                    rows.append("| " + " | ".join(cells) + " |")
            if rows:
                table.replace_with("\n" + "\n".join(rows) + "\n")

        title_tag = soup.find("title") or soup.find("h1")
        title = title_tag.get_text(strip=True) if title_tag else path.stem.replace("-", " ").title()
        body_text = soup.get_text(separator="\n", strip=True)

        meta = _merge_metadata(
            _extract_header_metadata(body_text[:2000]),
            _load_sidecar_metadata(path),
        )
        doc_id = meta.get("doc_id", f"DOC-{path.stem.upper()}")
        allowed_roles = meta.get("allowed_roles", ["analyst", "manager", "auditor"])
        raw_source = meta.get("source") or meta.get("source_url")
        source_url = str(raw_source) if (raw_source and str(raw_source).startswith(("http://", "https://"))) else None
        content_origin = str(meta.get("content_origin", "original_text"))

        return LoadedDocument(
            file_path=str(path),
            doc_id=doc_id,
            title=meta.get("title", title),
            pages=[LoadedPage(page_number=1, content=body_text)],
            allowed_roles=allowed_roles,
            doc_type=_doc_type_from_metadata(meta),
            jurisdiction=meta.get("jurisdiction", "UK_FCA"),
            version=str(meta.get("version", "1.0")),
            source_url=source_url,
            content_origin=content_origin,
        )

