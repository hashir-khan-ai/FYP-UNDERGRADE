"""Data integrity and validation tests for documents and gold question dataset."""

import json
from pathlib import Path


def test_gold_dataset_integrity() -> None:
    """Verify that gold_set.json contains exactly 100 well-formed questions."""
    gold_path = Path("data/gold_set.json")
    assert gold_path.exists(), "data/gold_set.json must exist"

    with open(gold_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert isinstance(data, list)
    assert len(data) == 100, f"Expected 100 gold items, found {len(data)}"

    categories: dict[str, int] = {}
    valid_roles = {"analyst", "manager", "auditor"}
    valid_routes = {"DIRECT_REPLY", "SINGLE_SEARCH", "MULTI_PART_SPLIT"}

    for idx, item in enumerate(data, start=1):
        expected_id = f"GOLD-{idx:03d}"
        assert item["id"] == expected_id, f"Item {idx} has mismatched ID: {item['id']}"
        assert item["query"].strip(), f"Item {item['id']} has empty query"
        assert item["submitted_by_role"] in valid_roles
        assert item["required_min_role"] in valid_roles
        assert item["expected_route"] in valid_routes
        assert isinstance(item["is_answerable"], bool)
        assert item["ground_truth_answer"].strip(), f"Item {item['id']} has empty ground truth"

        cat = item["category"]
        categories[cat] = categories.get(cat, 0) + 1

    # Assert exact distribution
    assert categories["single_fact"] == 30
    assert categories["multi_part"] == 30
    assert categories["role_restricted"] == 25
    assert categories["unanswerable"] == 15


def test_corpus_documents_exist() -> None:
    """Verify that raw and synthetic regulatory documents exist and contain clauses."""
    expected_docs = [
        "data/raw/FCA-BCOBS-Banking-Conduct.md",
        "data/raw/FCA-MLR-2017-Money-Laundering.md",
        "data/raw/BASEL-III-Capital-Adequacy.md",
        "data/synthetic/SOP-KYC-CDD-001.md",
        "data/synthetic/POLICY-SUPERVISORY-ESCALATION-002.md",
        "data/synthetic/AUDIT-CONFIDENTIAL-FINDINGS-2025.md",
    ]

    for doc_path_str in expected_docs:
        path = Path(doc_path_str)
        assert path.exists(), f"Document missing: {doc_path_str}"
        content = path.read_text(encoding="utf-8")
        assert len(content) > 200, f"Document content too short: {doc_path_str}"
        assert "Clause" in content, f"Document missing formal 'Clause' identifiers: {doc_path_str}"
        assert "Permitted Roles:" in content or "Classification:" in content

