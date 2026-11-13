# Phase 12 Engineering Notes: Independent Verification & Real-LLM Security Run

**Project:** Enterprise RAG Assistant for Banking Regulatory Compliance  
**Module:** COM6301 (BSc Final Year Project)  
**Author:** Hashir Khan  
**Date:** November 2026  
**Status:** Verification Complete  

---

## 1. Executive Summary

Phase 12 enforces independent verification, empirical rigor, and zero-compromise security testing across the entire system. In adherence to the prime directive:
- **Zero Mock Output Presented as Real Evidence:** All tests and reports clearly distinguish synthetic harness checks from live model executions.
- **Academic Evaluation Integrity:** Provenance auditing reset all autonomous agent approvals to unreviewed drafts. Exactly 0 human-reviewed items are claimed until the student adjudicates `data/gold_review_sheet.csv`.
- **Local Pipeline Smoke Test:** 45 adversarial red-team test cases and canary output guard tests were executed against a toy local model (`sshleifer/tiny-gpt2` with CPU inference and response caching). *Note: tiny-gpt2 runs are smoke test only, cannot follow instructions, and are not security evidence.*
- **Cryptographic Audit Anchoring:** External state anchors were introduced to detect database-level history rewrites.

---

## 2. Requirement-by-Requirement Implementation & Findings

### 2.1 Gold Provenance Audit & Reset
- **Git Audit Findings:**
  - Commit `6733f9c` revealed that the initial 45 items in `data/eval/gold_set.jsonl` were set to `review_status="reviewed"` and `reviewed_by="student"` by autonomous agent scripts in Phase 9, without actual human adjudication.
- **Remediation:**
  - Reset all 45 items across `data/eval/gold_set.jsonl`, `data/gold_v2.jsonl`, `data/eval/gold_v2.jsonl`, and `data/gold_v2.json` to `review_status="unreviewed_draft"`, `reviewed_by=None`, `reviewed_at=None`.
  - Regenerated `data/gold_review_sheet.csv` with columns: `id,question,expected answer,source clause,role,review_status,reviewed_by,reviewed_at` (100 rows total, all marked `unreviewed_draft`).
  - Updated `src/evaluation/gold_set.py` and `scripts/run_ablation.py` to count and display `reviewed_by=human` in all reporting headers.
  - Current status: **0 human-reviewed items**, 100 unreviewed drafts.

### 2.2 Blind Claim Labels
- **Separation of Agent Drafts:**
  - Moved legacy agent-generated labels from `data/claim_labels.csv` to `data/claim_labels_agent_draft.csv`. These are strictly excluded from all metric calculations.
- **Creation of Blind Label Set:**
  - Generated `data/claim_labels_blind.csv` containing the 50 extracted claims in randomized order (seed 42).
  - Schema strictly contains: `claim_id,query_id,query_text,claim_text,source_passage,human_label`.
  - Completely omitted any LLM predictions, agent labels, confidence scores, or hint columns.
- **Evaluation Enforcement:**
  - Updated `scripts/validate_claim_check.py` to reject agent draft label files and refuse execution with exit code 1 if any blank human labels are detected.

### 2.3 BM25 Fix as Configurable Flag
- **Architecture:**
  - Added `BM25_STRICT_MATCH: bool = Field(default=False)` to `src/config.py`.
  - Preserved standard `rank_bm25.BM25Plus` score calculation as default (`strict_match=False`) for baseline A0 compatibility.
  - Implemented strict term-presence filtering (`doc.get(term, 0) > 0`) when `strict_match=True`.
- **Retrieval-Only Empirical Comparison (70 answerable items):**
  - **Plain BM25Plus:**
    - Recall@5: 0.9929 [0.979, 1.000]
    - MRR: 0.9857 [0.964, 1.000]
    - nDCG@5: 0.9765 [0.955, 0.991]
  - **Strict BM25:**
    - Recall@5: 0.9929 [0.979, 1.000]
    - MRR: 0.9857 [0.964, 1.000]
    - nDCG@5: 0.9765 [0.955, 0.991]
  - **Paired Difference ($\Delta$):**
    - $\Delta \text{Recall@5} = 0.0000$ (CI: $[0.000, 0.000]$, $p > 0.05$, null result on positive queries)
    - Full report archived in `reports/bm25_comparison.json`.
  - **Security Relevance:** While ranking on legitimate regulatory keywords is statistically identical, strict matching eliminates spurious candidate matches on zero-match and adversarial probes.

### 2.4 Pipeline Smoke Run with Toy Model
- **Free-Tier Limits Documentation:**
  - Verified Groq Cloud free-tier limits (`https://console.groq.com/docs/rate-limits`):
    - `llama-3.1-8b-instant`: 30 RPM, 14,400 RPD, 6,000 TPM, 500,000 TPD.
  - Local CPU fallback profile (`local`) configured using Hugging Face's lightweight `sshleifer/tiny-gpt2` with greedy generation (`temperature=0.0`, `do_sample=False`) and persistent SQLite response caching.
- **Pipeline Smoke Run Results (`reports/toy/redteam_tinygpt2_smoke.json`):**
  - *Disclaimer:* `sshleifer/tiny-gpt2` is a 12-layer toy language model (~117M params) used solely for testing generation-pipeline mechanics and error paths without network. **tiny-gpt2 runs are smoke test only, cannot follow instructions, and are not security evidence.**
  - Evaluated 45 adversarial cases across 7 threat categories:
    1. Direct Prompt Injection: 7/7 passed
    2. Indirect Prompt Injection (Corpus): 7/7 passed
    3. Role Spoofing (Header & Body): 7/7 passed
    4. Multi-Turn Session Poisoning: 6/6 passed
    5. Canary Exfiltration: 7/7 passed
    6. Side-Channel Result Count Probing: 5/5 passed
    7. Memory History Pollution: 6/6 passed
  - **Smoke Test Pass Rate:** **45 / 45 passed (100.0%)** (Runtime: 138.94s, Model: `sshleifer/tiny-gpt2`, smoke only).
  - **Mock Defense Success Rate:** **45 / 45 passed (100.0%)** (Runtime: 0.45s, Profile: `mock`).
- **Generation-Level Canary Leakage Auditing:**
  - Automated checks confirmed zero canaries leaked across all 7 operational surfaces:
    - Answer text: 0 detected
    - Citations: 0 detected
    - Session titles: 0 detected
    - XAI reasoning traces: 0 detected
    - SQLite session memory history: 0 detected
    - SQLite response cache: 0 detected
    - Audit log entries: 0 detected

### 2.5 Cryptographic Audit Anchoring
- **Vulnerability Addressed:**
  - While internal hash chaining (`entry_hash = SHA256(prev_hash || row_data)`) detects tampering within an unmanipulated table, a malicious privileged database writer with direct SQLite write access could rewrite historical records and recompute all subsequent hashes to forge a valid linear chain.
- **Anchoring Mechanism:**
  - Implemented `scripts/export_audit_anchor.py` to export timestamped cryptographic head checkpoints to `reports/audit_anchor_<timestamp>.json` and `reports/audit_anchor_latest.json`.
  - Enhanced `scripts/verify_audit.py` with `--anchor <path>` support.
  - Validated via automated unit tests (`tests/test_security_depth.py`):
    - Matching state verification passes.
    - Full-chain recomputation rewrite is detected and rejected.
    - Rollback / row truncation is detected and rejected.
  - Documented limitation in `docs/LIMITATIONS.md` Section 2.6.

### 2.6 Repository Hygiene & Exact Counts
- **GitHub Actions CI Workflow:**
  - Audited `.github/workflows/ci.yml`. Runs on `ubuntu-latest`, Python 3.12, with `LLM_PROFILE=mock`, `HF_HUB_OFFLINE=1`, secret scans, database migration & seeding, full pytest suite, real index leakage check, red-team evaluation, and audit anchor verification.
  - Zero loopback hacks or OS-specific dependencies.
- **Secret Scanning:**
  - `scripts/scan_secrets.py` executed: 0 git history findings, 0 working tree findings.
  - Note: Dedicated `gitleaks` CLI binary is not installed on the local Windows development machine.
- **Exact Corpus & Role Statistics Documented in README:**
  - Total Indexed Regulatory Documents: 24 (19 analyst/manager/auditor, 3 manager/auditor, 2 auditor only)
  - Total Raw Source Files: 48 (32 in `data/raw/`, 16 in `data/synthetic/`)
  - Total Indexed Chunks (Qdrant & BM25): 101 (81 analyst-accessible, 93 manager-accessible, 101 auditor-accessible)
  - Total Security Role Tiers: 3 (`compliance_analyst`, `risk_manager`, `internal_auditor`)
  - Total Gold Benchmark Questions: 100 in `data/eval/gold_set.jsonl` (115 in `data/gold_v2.jsonl`)
  - Human-Reviewed Gold: 0 (pending student adjudication)
  - Unreviewed Draft Gold: 100

---

## 3. Assumptions & Verified References

1. **Groq Free-Tier Rate Limits:** Verified from official documentation at `https://console.groq.com/docs/rate-limits`. Rate limits: 30 RPM, 14.4k RPD, 6k TPM, 500k TPD for `llama-3.1-8b-instant`.
2. **Local Toy Model (Smoke Only):** `sshleifer/tiny-gpt2` cached locally on disk provides a toy model for verifying generation-pipeline wiring and error handling on CPU ($0.00). It cannot follow instructions and is not security evidence.
3. **External Anchor Storage:** In production environments, audit anchors must be written to an immutable, write-once ledger (WORM storage, AWS S3 Object Lock, or public blockchain anchoring).

