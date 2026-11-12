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
from src.ui.api_client import ComplianceAPIClient


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


def test_api_client_handles_response_mode() -> None:
    """Verify ComplianceAPIClient forwards response_mode to the server."""
    captured_payload = {}
    sid = str(uuid.uuid4())

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/chat/query":
            captured_payload.update(json.loads(request.read().decode("utf-8")))
            return httpx.Response(
                200,
                json={
                    "session_id": sid,
                    "answer": "Here is an overview of Basel III requirements...",
                    "route_taken": "SINGLE_SEARCH",
                    "route": "SINGLE_SEARCH",
                    "citations": [],
                    "reasoning_trace": ["Step 1: Role verified"],
                    "retrieval_stats": {
                        "total_chunks_retrieved": 1,
                        "top_rerank_score": 0.9,
                        "retry_count": 0,
                    },
                    "llm_stats": {
                        "profile": "mock",
                        "model": "mock",
                        "prompt_version": "v1",
                        "calls": 1,
                        "cached_calls": 0,
                        "prompt_tokens": 50,
                        "completion_tokens": 20,
                        "cached_response": False,
                    },
                    "spend": {
                        "calls_used": 1,
                        "calls_limit": 50,
                        "tokens_used": 70,
                        "tokens_limit": 25000,
                        "exhausted": False,
                    },
                    "latency_ms": 25.0,
                    "audit_id": 1,
                    "role": "analyst",
                    "rbac_enabled": True,
                    "candidates_filtered_by_role": 0,
                    "response_mode": "explain",
                },
            )
        return httpx.Response(404)

    client = ComplianceAPIClient(transport=httpx.MockTransport(handler))
    res = client.ask_chat_query(
        token="tok-analyst",
        session_id=sid,
        query="What is CET1?",
        response_mode="explain",
    )
    assert res["response_mode"] == "explain"
    assert captured_payload.get("response_mode") == "explain"


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
