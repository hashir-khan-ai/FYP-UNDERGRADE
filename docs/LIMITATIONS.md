# Limitations and Academic Scope Boundaries

**Project:** Enterprise RAG Assistant for Banking Regulatory Compliance  
**Module:** COM6301 (BSc Final Year Project, Academic Year 2025/2026)  
**Author:** Hashir Khan  
**Classification:** Academic Dissertation Artifact  

---

## 1. Executive Summary

In adherence to academic integrity and rigorous systems engineering principles, this document outlines the fundamental boundaries, synthetic assumptions, and architectural constraints of this final-year undergraduate project. While the system demonstrates production-grade design patterns—including cryptographic audit chaining, server-side vector RBAC filtering, canary output guards, and multi-step retrieval grading—it is built within an academic sandbox and is **not certified for unmonitored production deployment in a regulated financial institution**.

---

## 2. Key Architectural & Operational Limitations

### 2.1 Synthetic Internal Policies
- **Assumption:** All internal Standard Operating Procedures (SOPs), management escalation frameworks, and internal audit committee review records located under `data/synthetic/` are completely synthetic fixtures.
- **Risk & Scope:** While public statutory documents (`FCA-BCOBS`, `FCA-MLR-2017`, `BASEL-III-Capital-Adequacy`) represent verbatim statutory instruments, the internal policies are mock artifacts constructed to test multi-tier access control (Analyst, Manager, Auditor). They do not represent the operational procedures or confidential risk posture of any real-world commercial or investment bank.
- **Mitigation:** Zero confidential, real customer, or proprietary corporate data is present in the repository.

### 2.2 Small Gold Evaluation Benchmark
- **Scale:** The curated gold evaluation set (`data/eval/gold_set.jsonl`) comprises 100 benchmark items across statutory, internal SOP, calculation, and multi-turn categories (`data/gold_v2.jsonl` contains 115 items).
- **Human Review Provenance:** A git provenance audit revealed that the previous 45 "reviewed" marks were set autonomously by agent scripts rather than human adjudication. In accordance with Phase 12 integrity rules, all items have been reset to `unreviewed_draft` (`reviewed_by=human: 0`) until manually verified and signed off by the human researcher via `data/gold_review_sheet.csv`.
- **Implication:** While statistical rigor is enforced via 1,000-sample non-parametric bootstrap 95% confidence intervals and paired difference testing ($\Delta_k = A_k - A_{k-1}$), zero human-reviewed items are currently claimed as experimental evidence. Evaluation scripts strictly refuse to present unreviewed benchmark items as reviewed evidence (`--require-reviewed`).

### 2.3 Single LLM Evaluation & Provider Dependency
- **Model Diversity:** Live evaluation and offline development utilize one primary model family (DeepSeek / Gemini on free tiers via OpenAI-compatible endpoints) alongside deterministic mock fallbacks.
- **Limitations:** System performance (answer correctness, schema adherence, faithfulness) has not been benchmarked across multiple competing frontier foundational models (e.g., GPT-4o, Claude 3.5 Sonnet, Gemini 1.5 Pro) due to undergraduate quota and budget constraints. Results reflect the specific prompting nuances and capabilities of the active model profile.
- **Spend Guard Protection:** Hard caps on requests and token consumption prevent uncontrolled spending or quota exhaustion.

### 2.4 Role Model: Coarse RBAC vs. Dynamic ABAC
- **Current Model:** The access control model implements strict hierarchical Role-Based Access Control (RBAC) across three predefined tiers:
  1. `compliance_analyst` (Hierarchy Level 10): Public regulations and internal operational SOPs.
  2. `risk_manager` (Hierarchy Level 20): All Analyst materials plus internal management escalation frameworks and breach thresholds.
  3. `internal_auditor` (Hierarchy Level 30): All materials plus confidential audit committee reviews and forensic penetration findings.
- **Limitation:** Real enterprise banking compliance architectures require Attribute-Based Access Control (ABAC) or Relationship-Based Access Control (ReBAC), taking into account dynamic attributes such as:
  - Jurisdiction / entity legal boundary (e.g., UK ring-fenced bank vs. international broker-dealer).
  - Business division / desk segregation (e.g., FX trading vs. retail mortgages).
  - Time-limited clearance, conflict-of-interest ethical walls, and deal-specific "need-to-know" access lists.
- **Vector Native Implementation:** RBAC payload filtering occurs strictly server-side within the Qdrant and BM25 query engines before scoring or fusion.

### 2.5 Authentication: Local JWT / Argon2id vs. Enterprise SSO
- **Current Authentication:** User identities, Argon2id-hashed credentials, and session state are managed via local SQLite persistence and signed short-lived HMAC-SHA256 bearer tokens.
- **Production Gap:** In a production enterprise bank, authentication and identity federation are delegated to enterprise Identity Providers (IdPs) via SAML 2.0 or OpenID Connect (OIDC) (e.g., Microsoft Entra ID, Okta, Ping Identity) with hardware token Multi-Factor Authentication (MFA), Mutual TLS (mTLS), and centralized privilege management (PAM).
- **Defensive Safeguards:** Role claims are verified against the authoritative database on every request, preventing token forgery or client-side tampering from elevating permissions.

### 2.6 Cryptographic Audit Log & Unanchored Chain Limitation
- **Mechanism:** The SQLite `audit_log` records an append-only SHA-256 hash chain where each entry includes the previous entry's hash: `entry_hash = SHA256(prev_hash || row_data)`.
- **Limitation:** The audit chain is only tamper-evident when its head hash is published elsewhere. While this chain detects row tampering, out-of-order reordering, or deletion within an untampered database, **an adversary or malicious insider with direct database write access (e.g., SQLite DB file access) could rewrite past rows and recompute all subsequent hash links from scratch**, producing an internally self-consistent chain that passes simple linear verification unless anchored externally.
- **Mitigation & External Anchoring:** To prevent undetected history rewriting, external audit anchors must be periodically exported (`scripts/export_audit_anchor.py`) and stored off-system (e.g. write-once storage, Git commit trees, or timestamping authorities). Verification via `scripts/verify_audit.py --anchor reports/audit_anchor_latest.json` checks the database head against the trusted external anchor, immediately detecting any recomputation or rollback.

### 2.7 Unencrypted On-Disk Cache Storage
- **Mechanism:** The SQLite `llm_cache` table caches completion responses keyed by SHA-256 digests incorporating prompt, model, system prompt, temperature, role, user scope, and corpus ACL manifest version.
- **Limitation:** Cached answers are stored unencrypted on disk within the SQLite database.
- **Production Gap & Threat:** While cached entries are partitioned cryptographically by role and ACL version at the application query layer, an adversary with direct filesystem access to `data/sqlite/app.db` could inspect raw plaintext regulatory answers and synthesized advice. Production enterprise deployments require transparent data encryption at rest (e.g., SQLCipher or OS-level BitLocker/dm-crypt) and envelope encryption for sensitive regulatory cached outputs.

---

## 3. Methodological Integrity & Honest Reporting

1. **No Claims Without Verification:** Any benchmark, third-party performance claim, or external model specification in this repository is explicitly verified from authoritative documentation or labelled as "unverified".
2. **Negative and Null Results:** In the A0–A7 ablation study, configuration enhancements where the 95% confidence interval of the paired difference encompasses zero ($0 \in [CI_{low}, CI_{high}]$) are labelled as null results rather than claiming unsubstantiated improvements.
3. **Mock Transparency:** Mock runs are explicitly watermarked (`MOCK, not evidence — HARNESS CHECK ONLY`) to prevent synthetic harness runs from being mistaken for live experimental evidence.

