"""Gold-set schema, loader, and corpus-integrity validator for Phase 7."""

from __future__ import annotations

import json
import pickle
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from src.config import settings

QuestionType = Literal[
    "single_fact",
    "multi_part",
    "cross_reference",
    "role_restricted",
    "unanswerable",
]
RoleType = Literal["analyst", "manager", "auditor"]
ExpectedBehaviour = Literal["answer", "refuse"]
ReviewStatus = Literal["draft", "reviewed", "rejected", "unreviewed_draft"]

REQUIRED_QUESTION_TYPES: tuple[str, ...] = (
    "single_fact",
    "multi_part",
    "cross_reference",
    "role_restricted",
    "unanswerable",
)


class GoldQuestionItem(BaseModel):
    """Schema for a single row in ``data/eval/gold_set.jsonl``."""

    id: str = Field(..., min_length=2)
    question: str = Field(..., min_length=5)
    type: QuestionType
    role_asking: RoleType
    gold_chunk_ids: list[str] = Field(default_factory=list)
    gold_doc: str = Field(default="")
    clause: str = Field(default="")
    gold_answer: str = Field(..., min_length=2)
    expected_behaviour: ExpectedBehaviour
    status: ReviewStatus = Field(default="draft")
    review_status: str = Field(default="unreviewed_draft")
    reviewed_by: str | None = Field(default=None)
    reviewed_on: str | None = Field(default=None)
    reviewed_at: str | None = Field(default=None)
    source_chunk_id: str | None = Field(default=None)
    paired_id: str | None = Field(default=None)
    expected_route: str | None = Field(default=None)
    unauthorized_keywords: list[str] = Field(default_factory=list)

    @field_validator("gold_chunk_ids")
    @classmethod
    def _clean_chunk_ids(cls, value: list[str]) -> list[str]:
        return [cid.strip() for cid in value if cid and cid.strip()]


class GoldSetValidationReport(BaseModel):
    """Structured report produced by ``validate_gold_set_file``."""

    valid: bool
    total_count: int
    student_reviewed_count: int = 0
    human_reviewed_count: int = 0
    counts_by_type: dict[str, int]
    counts_by_status: dict[str, int]
    counts_by_role: dict[str, int]
    counts_by_behaviour: dict[str, int]
    missing_chunk_errors: list[str] = Field(default_factory=list)
    schema_errors: list[str] = Field(default_factory=list)
    type_quota_errors: list[str] = Field(default_factory=list)


def load_indexed_chunks(bm25_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Load the indexed chunk metadata list from the persisted BM25 pickle."""
    path = Path(bm25_path or settings.BM25_INDEX_PATH)
    if not path.exists():
        return []
    with open(path, "rb") as handle:
        payload = pickle.load(handle)
    return list(payload.get("chunks", []))


def load_gold_set(path: str | Path = "data/eval/gold_set.jsonl") -> list[GoldQuestionItem]:
    """Read and parse all JSONL rows from ``path`` into ``GoldQuestionItem`` objects."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Gold set file not found: {file_path}")
    items: list[GoldQuestionItem] = []
    with open(file_path, "r", encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                data = json.loads(stripped)
                items.append(GoldQuestionItem.model_validate(data))
            except Exception as exc:
                raise ValueError(f"Line {line_no}: {exc}") from exc
    return items


def validate_gold_set_file(
    gold_set_path: str | Path = "data/eval/gold_set.jsonl",
    known_chunk_ids: set[str] | None = None,
    min_per_type: int = 15,
) -> GoldSetValidationReport:
    """Validate schema, chunk references, and per-type quotas on a JSONL gold set.

    Args:
        gold_set_path: Path to ``gold_set.jsonl``.
        known_chunk_ids: Set of valid chunk IDs in the corpus index. If ``None``,
            loads chunk IDs from ``settings.BM25_INDEX_PATH``.
        min_per_type: Minimum number of questions required for each of the 5 types.

    Returns:
        ``GoldSetValidationReport`` with ``valid=True`` only when zero errors occur.
    """
    path = Path(gold_set_path)
    if known_chunk_ids is None:
        chunks = load_indexed_chunks()
        known_chunk_ids = {str(c.get("chunk_id")) for c in chunks if c.get("chunk_id")}

    schema_errors: list[str] = []
    missing_chunk_errors: list[str] = []
    type_quota_errors: list[str] = []

    if not path.exists():
        return GoldSetValidationReport(
            valid=False,
            total_count=0,
            counts_by_type={},
            counts_by_status={},
            counts_by_role={},
            counts_by_behaviour={},
            schema_errors=[f"File does not exist: {path}"],
        )

    items: list[GoldQuestionItem] = []
    seen_ids: set[str] = set()

    with open(path, "r", encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                schema_errors.append(f"Line {line_no}: invalid JSON ({exc.msg})")
                continue

            try:
                item = GoldQuestionItem.model_validate(payload)
            except Exception as exc:
                schema_errors.append(f"Line {line_no}: schema error ({exc})")
                continue

            if item.id in seen_ids:
                schema_errors.append(f"Line {line_no}: duplicate question id '{item.id}'")
            seen_ids.add(item.id)

            # Answerable questions must specify at least one gold chunk ID or doc+clause
            if item.expected_behaviour == "answer" and not item.gold_chunk_ids:
                schema_errors.append(
                    f"Question '{item.id}' ({item.status}): expected_behaviour='answer' requires non-empty gold_chunk_ids."
                )

            # Verify every referenced chunk ID exists in the corpus
            for cid in item.gold_chunk_ids:
                if cid not in known_chunk_ids:
                    missing_chunk_errors.append(
                        f"Question '{item.id}' (status={item.status}) references missing chunk_id '{cid}'."
                    )

            items.append(item)

    type_counts = Counter(item.type for item in items)
    status_counts = Counter(item.status for item in items)
    role_counts = Counter(item.role_asking for item in items)
    behaviour_counts = Counter(item.expected_behaviour for item in items)
    student_reviewed_n = sum(
        1 for item in items if item.status == "reviewed" and item.reviewed_by in ("student", "human")
    )
    human_reviewed_n = sum(
        1 for item in items if item.status == "reviewed" and item.reviewed_by == "human"
    )

    for item in items:
        if item.status == "reviewed" and item.reviewed_by not in ("student", "human"):
            schema_errors.append(
                f"Question '{item.id}': status='reviewed' requires reviewed_by='student' or 'human' (found {item.reviewed_by!r})."
            )

    for qtype in REQUIRED_QUESTION_TYPES:
        count = type_counts.get(qtype, 0)
        if count < min_per_type:
            type_quota_errors.append(
                f"Type '{qtype}' has {count} questions (minimum required: {min_per_type})."
            )

    valid = not (schema_errors or missing_chunk_errors or type_quota_errors)
    return GoldSetValidationReport(
        valid=valid,
        total_count=len(items),
        student_reviewed_count=student_reviewed_n,
        human_reviewed_count=human_reviewed_n,
        counts_by_type={k: type_counts.get(k, 0) for k in REQUIRED_QUESTION_TYPES},
        counts_by_status=dict(status_counts),
        counts_by_role=dict(role_counts),
        counts_by_behaviour=dict(behaviour_counts),
        missing_chunk_errors=missing_chunk_errors,
        schema_errors=schema_errors,
        type_quota_errors=type_quota_errors,
    )



DEFAULT_MIN_REVIEWED: int = 40


class InsufficientReviewedQuestionsError(RuntimeError):
    """Raised when a final ablation is requested without enough reviewed questions."""


def count_by_status(items: list[GoldQuestionItem]) -> dict[str, int]:
    """Return counts by status including student-reviewed and human-reviewed counts."""
    counts = Counter(item.status for item in items)
    student_reviewed = sum(
        1 for item in items if item.status == "reviewed" and item.reviewed_by in ("student", "human")
    )
    human_reviewed = sum(
        1 for item in items if item.status == "reviewed" and item.reviewed_by == "human"
    )
    return {
        "reviewed": counts.get("reviewed", 0),
        "draft": counts.get("draft", 0) + counts.get("unreviewed_draft", 0),
        "unreviewed_draft": counts.get("unreviewed_draft", 0),
        "rejected": counts.get("rejected", 0),
        "student_reviewed": student_reviewed,
        "human_reviewed": human_reviewed,
    }


def select_reviewed_questions(
    items: list[GoldQuestionItem],
    min_reviewed: int = DEFAULT_MIN_REVIEWED,
) -> list[GoldQuestionItem]:
    """Return only verified reviewed questions, refusing if fewer than ``min_reviewed``.

    Only questions carrying ``status == 'reviewed'`` and ``reviewed_by in ('student', 'human')``
    are accepted for evaluation.

    Raises:
        InsufficientReviewedQuestionsError: if fewer than ``min_reviewed``
            questions carry ``status == "reviewed"`` and ``reviewed_by in ("student", "human")``.
    """
    reviewed = [
        item for item in items if item.status == "reviewed" and item.reviewed_by in ("student", "human")
    ]
    if len(reviewed) < min_reviewed:
        human_count = sum(1 for item in items if item.status == "reviewed" and item.reviewed_by == "human")
        total_marked_reviewed = sum(1 for item in items if item.status == "reviewed")
        raise InsufficientReviewedQuestionsError(
            f"Final ablation refused: {human_count} human-reviewed / student-reviewed question(s) found (total verified: {len(reviewed)}), "
            f"at least {min_reviewed} required. Review gold questions by hand using scripts/review_gold_set.py "
            f"(reviewed_by='human') (currently marked reviewed: {total_marked_reviewed}, draft: {len(items) - len(reviewed)})."
        )
    return reviewed
