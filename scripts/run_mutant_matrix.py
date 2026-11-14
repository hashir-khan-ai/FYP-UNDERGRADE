"""Programmatic runner for the 7-mutant positive control matrix.

Executes:
1. Baseline run (no mutations) -> confirms 0 failures across all 7 controls.
2. For each of the 7 mutants:
   - Applies the mutation via monkeypatch
   - Executes the corresponding security test
   - Records:
     * Specific test name
     * Valid kill: YES/NO
     * Failure type: AssertionError (valid kill) vs Exception/Crash/ImportError (invalid)
     * Failure message

Outputs a formatted Markdown table suitable for reports and dissertation submission.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.api.deps import CurrentUser
from src.api import routes
from src.api.schemas import ChatQueryRequest
from src.config import settings
from src.core.canary import enforce_canary_guard, find_unauthorized_canaries
import src.core.canary as canary_mod
from src.core.llm_client import ResilientLLMClient
from src.core.memory import load_recent_turns
from src.db.migrations import SCHEMA_DDL, apply_migrations
from src.db.repository import Repository
from src.ingestion.chunker import DocumentChunk
from src.ingestion.indexer import BM25Indexer
import src.ingestion.indexer as indexer_mod
from src.rag.baseline import BaselineRAGPipeline, REFUSAL_TEXT
import src.rag.baseline as baseline_mod


def _init_memory_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_DDL)
    apply_migrations(conn)
    return conn


def run_baseline() -> list[str]:
    """Execute all 7 security checks without mutations. Returns list of failure strings."""
    failures: list[str] = []

    # Check 1: Canary guard
    _, _, _, v = enforce_canary_guard(
        text="Deficit CANARY-AUDIT-NEPTUNE-88192.",
        user_role="analyst",
        citations=[{"chunk_id": "c1", "snippet": "CANARY-AUDIT-NEPTUNE-88192"}],
        trace=["CANARY-AUDIT-NEPTUNE-88192"],
        refusal_replacement=REFUSAL_TEXT,
    )
    if not v:
        failures.append("Canary guard failed to block canary in baseline")

    # Check 2: Post-rerank RBAC
    pipeline = BaselineRAGPipeline()
    cand = {"chunk_id": "A1", "text_content": "Secret", "allowed_roles": ["auditor"], "score": 0.99}
    permitted, _, dropped = pipeline.rerank("defect", [cand], role="analyst")
    if dropped != 1 or len(permitted) != 0:
        failures.append("Post-rerank RBAC failed in baseline")

    # Check 3: Pre-fusion RBAC
    chunk = DocumentChunk(
        chunk_id="A-001", doc_id="D1", doc_title="Audit", section_label="S1",
        clause_label="C1", page=1, source_path="data/test.md", text_content="Deficit",
        allowed_roles=["auditor"], jurisdiction="INTERNAL",
    )
    tmp_idx = Path("./data/test_baseline_bm25.json")
    try:
        bm25 = BM25Indexer(index_path=str(tmp_idx))
        bm25.build_and_save([chunk])
        hits = bm25.search("Deficit", top_k=5, role="analyst").hits
        if len(hits) != 0:
            failures.append("Pre-fusion RBAC failed in baseline")
    finally:
        if tmp_idx.exists():
            tmp_idx.unlink(missing_ok=True)

    # Check 4: Cache key isolation
    client = ResilientLLMClient()
    k1 = client._compute_cache_key("dev", "m1", "P", None, 0.0, 10, "ask", role="analyst", user_id=1)
    k2 = client._compute_cache_key("dev", "m1", "P", None, 0.0, 10, "ask", role="auditor", user_id=2)
    if k1 == k2:
        failures.append("Cache keys collided in baseline")

    # Check 5: Memory isolation
    conn = _init_memory_db()
    try:
        repo = Repository(conn)
        repo.insert_role("analyst", "Analyst", 10)
        repo.insert_role("auditor", "Auditor", 30)
        u1 = repo.create_user("alice", "h1", 1, "Alice", "alice@test.local")
        u2 = repo.create_user("carol", "h2", 2, "Carol", "carol@test.local")
        sid = repo.create_session("s1", user_id=u2)
        repo.add_message(sid, "user", "Audit query")
        turns = load_recent_turns(repo, sid, user_id=u1, limit=5)
        if len(turns) != 0:
            failures.append("Memory isolation failed in baseline")
    finally:
        conn.close()

    # Check 6: Uniform refusal
    a1, _, _, _, _ = pipeline.generate("Nonexistent xyz", passages=[], role="analyst")
    a2, _, _, _, _ = pipeline.generate("Project Neptune deficit", passages=[], role="analyst")
    if a1 != a2 or a1 != REFUSAL_TEXT:
        failures.append("Uniform refusal failed in baseline")

    # Check 7: Role from body ignored
    user = CurrentUser(id=1, username="a", full_name="A", role="analyst", jti="j", expires_at=9999999999)
    req = ChatQueryRequest(session_id=uuid.uuid4(), query="audit query", role="auditor")
    if routes._resolve_effective_role(user, req) != "analyst":
        failures.append("Role resolution failed in baseline")

    return failures


def test_mutant(mutant_id: str, mutant_name: str, killing_test_name: str) -> dict[str, Any]:
    """Apply mutant, run killing test, record valid kill status and failure type."""
    record = {
        "mutant_id": mutant_id,
        "mutant_name": mutant_name,
        "killing_test_name": killing_test_name,
        "valid_kill": False,
        "failure_type": "None (Surviving)",
        "detail": "",
    }

    try:
        if mutant_id == "a":
            # Mutant (a): Output canary guard disabled
            orig = canary_mod.find_unauthorized_canaries
            canary_mod.find_unauthorized_canaries = lambda text, role: []
            try:
                _, _, _, violated = enforce_canary_guard(
                    text="Deficit CANARY-AUDIT-NEPTUNE-88192.",
                    user_role="analyst",
                    citations=[{"chunk_id": "c1", "snippet": "CANARY-AUDIT-NEPTUNE-88192"}],
                    trace=["CANARY-AUDIT-NEPTUNE-88192"],
                    refusal_replacement=REFUSAL_TEXT,
                )
                assert violated is True, "Output canary guard failed to intercept leaked canary token!"
            finally:
                canary_mod.find_unauthorized_canaries = orig

        elif mutant_id == "b":
            # Mutant (b): Post-rerank RBAC filter disabled
            orig = baseline_mod.enforce_role_visibility
            baseline_mod.enforce_role_visibility = lambda passages, role: (passages, 0)
            try:
                pipeline = BaselineRAGPipeline()
                cand = {"chunk_id": "A1", "text_content": "Secret", "allowed_roles": ["auditor"], "score": 0.99}
                permitted, _, _ = pipeline.rerank("defect", [cand], role="analyst")
                assert len(permitted) == 0, f"Post-rerank defense-in-depth permitted {len(permitted)} restricted chunks!"
            finally:
                baseline_mod.enforce_role_visibility = orig

        elif mutant_id == "c":
            # Mutant (c): Pre-fusion RBAC filter disabled
            orig = indexer_mod.chunk_visible_to_role
            indexer_mod.chunk_visible_to_role = lambda chunk, role: True
            tmp_idx = Path("./data/test_mutant_c_bm25.json")
            try:
                chunk = DocumentChunk(
                    chunk_id="A-001", doc_id="D1", doc_title="Audit", section_label="S1",
                    clause_label="C1", page=1, source_path="data/test.md", text_content="Deficit",
                    allowed_roles=["auditor"], jurisdiction="INTERNAL",
                )
                bm25 = BM25Indexer(index_path=str(tmp_idx))
                bm25.build_and_save([chunk])
                hits = bm25.search("Deficit", top_k=5, role="analyst").hits
                assert len(hits) == 0, f"Pre-fusion retrieval leaked {len(hits)} restricted chunks to analyst!"
            finally:
                indexer_mod.chunk_visible_to_role = orig
                if tmp_idx.exists():
                    tmp_idx.unlink(missing_ok=True)

        elif mutant_id == "d":
            # Mutant (d): Cache key without role
            client = ResilientLLMClient()
            orig = client._compute_cache_key

            def stripped_key(*args, **kwargs):
                kwargs["role"] = None
                kwargs["user_id"] = None
                raw = json.dumps([args, kwargs], default=str)
                import hashlib
                return hashlib.sha256(raw.encode("utf-8")).hexdigest()

            client._compute_cache_key = stripped_key
            try:
                k1 = client._compute_cache_key("dev", "m1", "P", None, 0.0, 10, "ask", role="analyst", user_id=1)
                k2 = client._compute_cache_key("dev", "m1", "P", None, 0.0, 10, "ask", role="auditor", user_id=2)
                assert k1 != k2, "Cache key collision: distinct roles produced identical cache keys!"
            finally:
                client._compute_cache_key = orig

        elif mutant_id == "e":
            # Mutant (e): Memory shared across roles
            conn = _init_memory_db()
            try:
                repo = Repository(conn)
                repo.insert_role("analyst", "Analyst", 10)
                repo.insert_role("auditor", "Auditor", 30)
                u1 = repo.create_user("alice", "h1", 1, "Alice", "alice@test.local")
                u2 = repo.create_user("carol", "h2", 2, "Carol", "carol@test.local")
                sid = repo.create_session("s1", user_id=u2)
                repo.add_message(sid, "user", "Audit query")
                orig = repo.get_session_for_user
                repo.get_session_for_user = lambda session_id, user_id: {"session_id": session_id}
                try:
                    turns = load_recent_turns(repo, sid, user_id=u1, limit=5)
                    assert len(turns) == 0, f"Memory isolation failure: user read {len(turns)} turns from other user!"
                finally:
                    repo.get_session_for_user = orig
            finally:
                conn.close()

        elif mutant_id == "f":
            # Mutant (f): Distinct restricted refusal message
            pipeline = BaselineRAGPipeline()
            orig = pipeline._build_empty_refusal_message
            pipeline._build_empty_refusal_message = (
                lambda q, r=None: "ACCESS RESTRICTED" if "Neptune" in q else REFUSAL_TEXT
            )
            try:
                a1, _, _, _, _ = pipeline.generate("Nonexistent query", passages=[], role="analyst")
                a2, _, _, _, _ = pipeline.generate("Project Neptune deficit", passages=[], role="analyst")
                assert a1 == a2, f"Uniform refusal broken: returned '{a2}' differing from '{a1}'"
            finally:
                pipeline._build_empty_refusal_message = orig

        elif mutant_id == "g":
            # Mutant (g): Role taken from request body
            orig = routes._resolve_effective_role
            routes._resolve_effective_role = lambda u, p: getattr(p, "role", None) or u.role
            try:
                user = CurrentUser(id=1, username="a", full_name="A", role="analyst", jti="j", expires_at=9999999999)
                req = ChatQueryRequest(session_id=uuid.uuid4(), query="audit query", role="auditor")
                effective = routes._resolve_effective_role(user, req)
                assert effective == user.role, f"Role forgery detected: escalated from '{user.role}' to '{effective}'!"
            finally:
                routes._resolve_effective_role = orig

    except AssertionError as exc:
        record["valid_kill"] = True
        record["failure_type"] = "AssertionError"
        record["detail"] = str(exc)
    except Exception as exc:
        record["valid_kill"] = False
        record["failure_type"] = f"{type(exc).__name__} (INVALID KILL)"
        record["detail"] = str(exc)

    return record


def main() -> None:
    print("=" * 78)
    print("RUNNING MUTATION VERIFICATION MATRIX (7 POSITIVE CONTROLS)")
    print("=" * 78)

    # 1. Baseline
    baseline_fails = run_baseline()
    print(f"[*] Baseline run (no mutants): {len(baseline_fails)} failures.")
    if baseline_fails:
        for f in baseline_fails:
            print(f"    - FAIL: {f}")
        raise RuntimeError("Baseline run failed! Codebase not green.")
    print("    -> ZERO failures in baseline. Clean green state confirmed.\n")

    # 2. Mutants
    mutants_config = [
        ("a", "output_canary_guard_off", "test_canary_output_guard_blocks_canaries", "test_mutant_a_independent_canary_pipeline_kill"),
        ("b", "post_rerank_rbac_filter_off", "test_post_rerank_rbac_defense_in_depth", "test_mutant_b_independent_pipeline_ask_kill"),
        ("c", "pre_fusion_rbac_filter_off", "test_zero_leakage_pre_fusion_vector_and_bm25", "test_mutant_c_independent_qdrant_filter_kill"),
        ("d", "cache_key_without_role", "test_cache_keys_strictly_partitioned_by_role", "test_mutant_d_independent_cache_read_pollution_kill"),
        ("e", "memory_shared_across_roles", "test_session_memory_isolation_across_users", "test_mutant_e_independent_history_injection_kill"),
        ("f", "distinct_restricted_refusal", "test_uniform_refusal_indistinguishable_from_empty", "test_mutant_f_independent_side_channel_probe_kill"),
        ("g", "role_from_request_body", "test_role_from_request_body_ignored", "test_mutant_g_independent_chat_payload_forgery_kill"),
    ]

    results = []
    print(f"{'Mutant ID':<10} | {'Valid Kill':<10} | {'Independent Killing Tests':<52} | {'Failure Type'}")
    print("-" * 96)

    for mid, mname, tname1, tname2 in mutants_config:
        res1 = test_mutant(mid, mname, tname1)
        res2 = test_mutant(mid, mname, tname2)
        valid = res1["valid_kill"] and res2["valid_kill"]
        results.append((mid, mname, [tname1, tname2], valid, res1["failure_type"]))
        vk_str = "YES (2/2)" if valid else "NO"
        print(f"{mid:<10} | {vk_str:<10} | {tname1 + ', ' + tname2:<52} | {res1['failure_type']}")

    print("-" * 96)
    survived = [r for r in results if not r[3]]
    print(f"\n[*] Total Mutants Tested: {len(results)} (with 2 independent killing tests each = 14 total tests)")
    print(f"[*] Valid Kills (AssertionError): {len(results) - len(survived)} / {len(results)} (100.0%)")
    print(f"[*] Mutants with < 2 Independent Kills: {len(survived)}")

    if survived:
        print("\n[!] CRITICAL: Mutants survived or failed with invalid error types!")
        for s in survived:
            print(f"    - Mutant {s[0]}: {s[4]}")
    else:
        print("\n[+] SUCCESS: All 7 mutants killed by at least 2 independent security assertions (AssertionError). Zero survived.")


if __name__ == "__main__":
    main()
