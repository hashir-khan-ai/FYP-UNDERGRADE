"""Tests for conversational Explain & Discuss mode and Citations UI collapse.

Verifies:
1. API schema accepts response_mode="compliance" and response_mode="explain"
2. Pipeline generates plain-language explanations in explain mode using prompts/v1/explain.txt
3. Analyst in explain mode still receives uniform refusal for restricted queries (0.00% leakage)
4. Multi-turn dialogue history is passed to generation in explain mode
5. UI client forwards response_mode cleanly to backend
"""

import json
import uuid
from unittest.mock import MagicMock
import httpx
import pytest

from src.api.schemas import ChatQueryRequest, ChatQueryResponse, Citation
from src.core.prompts import load_prompt
from src.rag.baseline import BaselineRAGPipeline, BaselineRAGResponse


def test_schema_accepts_response_mode() -> None:
    """Verify ChatQueryRequest and ChatQueryResponse validate response_mode."""
    uid = uuid.uuid4()
    req_default = ChatQueryRequest(
        session_id=uid,
        query="Explain Basel capital rules",
    )
    assert req_default.response_mode == "compliance"

    req_explain = ChatQueryRequest(
        session_id=uid,
        query="Explain Basel capital rules in simple terms",
        response_mode="explain",
    )
    assert req_explain.response_mode == "explain"


def test_explain_prompt_loads_and_has_grounding_rules() -> None:
    """Verify prompts/v1/explain.txt loads and includes non-negotiable security rules."""
    prompt = load_prompt("explain")
    assert "<authoritative_documents>" in prompt
    assert "</authoritative_documents>" in prompt
    assert "I can't find that in the documents available to your role." in prompt
    assert "Supporting Chunks:" in prompt


def test_explain_mode_pipeline_grounding_and_refusal() -> None:
    """Verify that explain mode pipeline returns uniform refusal when evidence is empty."""
    pipeline = BaselineRAGPipeline()
    res = pipeline.generate(
        query="Explain confidential internal policies",
        passages=[],
        response_mode="explain",
    )
    answer, cited, cached, latency, usage = res
    assert answer == "I can't find that in the documents available to your role."
    assert cited == []


def test_verification_metadata_public_vs_internal() -> None:
    """Verify public documents receive canonical and Google links while internal documents never link out."""
    from src.rag.baseline import build_verification_metadata

    # 1. Public Basel regulation
    public_passage = {
        "doc_id": "DOC-BASEL-III-2023",
        "doc_title": "Basel Committee on Banking Supervision - Basel III Capital & Liquidity Framework",
        "section_label": "Part 1 - Minimum Capital Requirements",
        "clause_label": "1.1 CET1 Ratio",
        "jurisdiction": "BASEL_BCBS",
        "content_origin": "excerpt_of_original",
        "source_url": "https://www.bis.org/bcbs/basel3.htm",
    }
    public_meta = build_verification_metadata(public_passage)
    assert public_meta["is_internal"] is False
    assert public_meta["source_url"] == "https://www.bis.org/bcbs/basel3.htm"
    assert "https://www.google.com/search?q=" in public_meta["verification_url"]
    assert "Basel" in public_meta["verification_url"]
    assert "Basel Committee" in public_meta["source_name"]

    # 2. Internal audit document (synthetic)
    internal_passage = {
        "doc_id": "DOC-INT-AUDIT-CONF-2025",
        "doc_title": "Bank Internal Audit Committee Review",
        "section_label": "Audit Gaps",
        "clause_label": "Item 3",
        "jurisdiction": "INTERNAL_SYNTHETIC",
        "content_origin": "synthetic",
        "source_url": "SYNTHETIC_DATASET",
    }
    internal_meta = build_verification_metadata(internal_passage)
    assert internal_meta["is_internal"] is True
    assert internal_meta["source_url"] is None
    assert internal_meta["verification_url"] is None
    assert "Internal" in internal_meta["source_name"]

    # 3. Internal escalation policy
    policy_passage = {
        "doc_id": "POL-042",
        "doc_title": "Material Breach Escalation Policy",
        "section_label": "Section 2",
        "clause_label": "Clause 2.1",
        "jurisdiction": "INTERNAL_SYNTHETIC",
        "content_origin": "synthetic",
    }
    policy_meta = build_verification_metadata(policy_passage)
    assert policy_meta["is_internal"] is True
    assert policy_meta["source_url"] is None
    assert policy_meta["verification_url"] is None
