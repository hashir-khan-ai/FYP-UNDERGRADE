# Phase 11 Notes: Publication Hardening & Defensive Rigor

**Date:** May 2026 / Academic Year 2025-2026  
**Author:** Hashir Khan  
**Status:** Complete  

---

## 1. Summary of Completed Deliverables

### Section A: Security Depth
1. **Hash-Chained Audit Log (A.1):**
   - Implemented `src/core/audit_chain.py` with canonical tuple hashing and `GENESIS` root.
   - Updated schema migrations in `src/db/migrations.py` to store `prev_hash` and `entry_hash`.
   - Updated `src/db/repository.py` to atomically fetch previous hash, compute SHA-256 over 42 canonical fields, and insert chain records.
   - Built `scripts/verify_audit.py` to traverse the chain and detect row modification or deletion.
   - Verified via unit tests in `tests/test_security_depth.py` (tampering and row deletion detected).

2. **Canary Tokens & Output Guard (A.2):**
   - Planted 5 unique canary tokens in synthetic restricted documents:
     - `CANARY-AUDIT-NEPTUNE-88192` (`AUDIT-CONFIDENTIAL-FINDINGS-2025.md`)
     - `CANARY-AUDIT-VULCAN-44719` (`AUDIT-CYBER-PENETRATION-FINDINGS-2025.md`)
     - `CANARY-MGT-ESCALATION-33918` (`POLICY-SUPERVISORY-ESCALATION-002.md`)
     - `CANARY-MGT-BOREAS-77201` (`POLICY-CYBER-INCIDENT-ESCALATION-003.md`)
     - `CANARY-MGT-KRONOS-55412` (`POLICY-MARKET-ABUSE-SURVEILLANCE-004.md`)
   - Re-indexed Qdrant vector store and BM25 index with canaries.
   - Created `src/core/canary.py` with registry and output guard `enforce_canary_guard`.
   - Integrated into `src/rag/baseline.py` in `ask()` and `generate()`, wiping sources and returning sanitized refusal if an unauthorized canary is detected.
   - Integrated canary stripping into `src/core/session_title.py`.

3. **Result-Count Side Channel Defense (A.3):**
   - Confirmed RBAC filtering occurs strictly before ranking in both Qdrant (payload filter) and BM25.
   - Fixed BM25Okapi/BM25Plus presence matching so documents with zero term occurrences are not scored as positive hits.
   - Automated test verifies that queries matching only restricted content return an identical refusal text, 0 citations, and zero leaked metadata, matching queries with non-existent terms.

4. **Identity Enforcement (A.4):**
   - Verified in `src/api/deps.py` that role claims derive strictly from verified JWT bearer tokens re-checked against SQLite.
   - Forged roles in query bodies, request headers (`X-User-Role`), and tampered JWT tokens are strictly rejected with HTTP 401/403.

5. **Dynamic Document Revocation (A.5):**
   - Tested immediate permission revocation: modifying `allowed_roles` on a chunk and re-indexing immediately causes queries under revoked roles to receive 0 hits and immediate uniform refusal.

6. **Cross-Role Cache & Memory Isolation (A.6):**
   - Scoped LLM response cache keys in `src/core/llm_client.py` by `role` and `user_id`.
   - Verified cross-user session memory isolation in `src/core/memory.py` via `load_recent_turns`.

7. **Adversarial Red Team Evaluation (A.7):**
   - Created `data/redteam.jsonl` with 45 test cases across 5 categories:
     - Prompt injection in queries (10)
     - Prompt injection in documents / boundary escapes (8)
     - Role spoofing & pretexts (10)
     - Exfiltration channels (9)
     - Multi-turn carryover attacks (8)
   - Created `scripts/eval_redteam.py`. Result: 45/45 passed (100.0% defense pass rate).

---

### Section B: Evaluation Rigor
1. **Paired Bootstrap CIs:** Added `paired_bootstrap_ci` in `src/evaluation/metrics.py` computing 95% CIs on paired differences between adjacent configs ($A_k - A_{k-1}$), explicitly flagging null results when 0 falls inside the confidence interval.
2. **Separated Retrieval & Answer Metrics:** `aggregate_ablation_rows` outputs structured dictionaries for `retrieval_metrics`, `answer_metrics`, and `layer_costs_and_latencies`.
3. **Reviewed Item Guard:** Print reviewed vs unreviewed item counts in every report header; output directed to `reports/mock/` with banner or `reports/real/`.
4. **Limitations:** Penned `docs/LIMITATIONS.md` documenting synthetic policies, small benchmark scale, single LLM evaluation, RBAC vs ABAC, and lack of enterprise SSO.

---

### Section C: Repository Quality
- Created `LICENSE` (MIT).
- Created `THIRD_PARTY.md` cataloguing 15 packages, 2 pre-trained models, and regulatory sources with verified URLs.
- Created `DATA.md` documenting provenance of statutory and synthetic documents.
- Created `docs/RELATED_WORK.md` contrasting against 8 open-source RAG repositories.
- Created `Dockerfile`, `docker-compose.yml`, `Makefile`, and `.github/workflows/ci.yml`.
- Created `SECURITY.md`, `CONTRIBUTING.md`, and `CITATION.cff`.
- Created `README.md` with complete documentation, architecture diagram, and quickstart.

---

## 2. Assumptions & Notes
- Tests run exclusively under the `mock` profile with zero live API spend.
- Secret scanning verified zero committed API keys in tracked files or commit history.

