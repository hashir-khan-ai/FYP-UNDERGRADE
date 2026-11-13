# Related Work & Comparative Analysis

**Project:** Enterprise RAG Assistant for Banking Regulatory Compliance  
**Author:** Hashir Khan (BSc COM6301 Final Year Project)  

This document provides a comparative evaluation against eight open-source and published RAG architectures, based strictly on the public descriptions and documented capabilities in their respective repository READMEs. For each project, we identify architectural differences and explicitly state areas where that project is stronger than this dissertation implementation.

---

## Comparative Matrix

| Repository | Primary Focus | Access Control Mechanism | Retrieval & Ranking | Observability & Audit | Where It Is Stronger Than This Project |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **enterprise-rag-rbac** *(mustafaabdullahai-dev)* | Enterprise RAG with Role-Based Access Control | Application-layer & vector-level user group filtering | Vector retrieval with metadata filtering | Application logging | **Stronger:** Native integration with enterprise Active Directory / LDAP groups and wider enterprise multi-tenant configuration out of the box. |
| **vaultrag** *(royalpinto007)* | Cryptographically secured confidential document QA | Hardware-backed or KMS envelope encryption | Vector search over encrypted indexes | Audit trail of access requests | **Stronger:** Implements cryptographic document-at-rest envelope encryption with KMS key rotation, whereas this project relies on filesystem permissions and database-level hashes. |
| **regulatory-guidance-assistant** *(changezakram)* | Conversational compliance guidance for financial rules | Prompt-based user role conditioning | Dense semantic search across regulatory rulebooks | Standard conversation logging | **Stronger:** Broader multi-jurisdiction corpus coverage spanning wider non-UK regulatory regimes and specialized cross-border compliance mapping. |
| **RegIntel** *(arbabc-ai)* | Regulatory intelligence, change tracking, and summarization | Platform user tier permissions | Semantic chunking and cross-document comparison | Workflow audit logs | **Stronger:** Automated regulatory horizon scanning and real-time diffing of regulatory circulars as new updates are published by supervisory bodies. |
| **hybrid-search-rag** *(Guilherme-pxt)* | Hybrid lexical and semantic retrieval optimization | Generic user scoping | BM25 + Dense vector search with Reciprocal Rank Fusion | Retrieval benchmarking | **Stronger:** Deeper tuning of sparse-dense fusion hyperparameters ($\alpha$, $k$) across multiple diverse evaluation domains beyond compliance texts. |
| **rag-ablation-bench** *(Ggil22)* | Systematic ablation benchmarking for RAG pipelines | Evaluation-focused harness | Multi-model vector indices and chunking strategies | Metric tracking tables | **Stronger:** Supports automated grid search across multiple competing frontier LLM backends (GPT-4, Claude, Llama-3) in parallel benchmark runs. |
| **Retrieval-ablation** *(Tarek-yagami)* | Modular retrieval ablation (dense, sparse, re-rankers) | None (pure retrieval research) | Extensive re-ranking model comparisons | Information retrieval benchmark metrics | **Stronger:** Benchmarks a broader family of Cross-Encoder, ColBERT, and late-interaction re-ranking architectures on standardized IR datasets (BEIR, MS MARCO). |
| **York-Rag-System** *(baybars-a)* | Institutional knowledge retrieval and conversational QA | Institutional user authentication | Multi-index dense semantic search | User interaction telemetry | **Stronger:** Tailored production institutional deployment with student/staff institutional workflows and conversational interface optimizations. |

---

## Detailed Analyses

### 1. `enterprise-rag-rbac` (mustafaabdullahai-dev)
- **Architecture:** Focuses on enterprise role-based authorization for generative search, filtering retrieved context based on user authorization groups.
- **Comparison:** Our project enforces RBAC strictly at the vector payload filter level before scoring and includes canary tokens and cryptographic hash-chaining of audit logs.
- **Where It Is Stronger:** `enterprise-rag-rbac` features broader enterprise group directory integrations and pre-built templates for multi-tenant enterprise user pools.

### 2. `vaultrag` (royalpinto007)
- **Architecture:** Centers on secure, zero-trust document handling and safe retrieval from encrypted vaults.
- **Comparison:** Our project features multi-tier grading, adaptive routing, and automated adversarial red-teaming.
- **Where It Is Stronger:** `vaultrag` implements cryptographic envelope encryption for document storage with external Key Management Services (KMS), providing stronger protection against offline disk compromise.

### 3. `regulatory-guidance-assistant` (changezakram)
- **Architecture:** Specializes in financial regulatory guidance, question answering, and interpreting supervisory expectations.
- **Comparison:** Our project enforces strict zero unauthorized leakage with automated penetration testing and quantitative ablation across 8 configurations.
- **Where It Is Stronger:** Offers broader coverage of international regulatory rulebooks and multi-regime mapping across diverse compliance jurisdictions.

### 4. `RegIntel` (arbabc-ai)
- **Architecture:** Focuses on regulatory intelligence, continuous policy monitoring, and change impact assessment.
- **Comparison:** Our project focuses on high-precision query answering with clause-level verification, heading paths, and cryptographic auditability.
- **Where It Is Stronger:** Features automated regulatory horizon scanning, alert generation, and circular delta comparison as supervisory rules evolve.

### 5. `hybrid-search-rag` (Guilherme-pxt)
- **Architecture:** Examines lexical and dense hybrid search fusion to maximize recall on specialized terminology.
- **Comparison:** Our project integrates hybrid search with native role filtering, adaptive query routing, and cross-encoder re-ranking.
- **Where It Is Stronger:** Provides broader hyperparameter optimization tooling for fusion weights and rank thresholds across diverse generic domain benchmarks.

### 6. `rag-ablation-bench` (Ggil22)
- **Architecture:** A generic benchmarking framework designed to isolate and quantify the impact of chunking size, embedding models, and prompt strategies.
- **Comparison:** Our ablation focuses on an 8-layer enterprise stack (A0 to A7) evaluated on regulatory questions with paired bootstrap confidence intervals.
- **Where It Is Stronger:** Supports concurrent automated multi-model provider benchmarking across dozens of commercial and open-weight model endpoints.

### 7. `Retrieval-ablation` (Tarek-yagami)
- **Architecture:** Investigates deep information retrieval tradeoffs between sparse, dense, and neural re-ranking architectures.
- **Comparison:** Our project evaluates the end-to-end impact of retrieval changes on generative accuracy, citation validity, and regulatory refusal rates.
- **Where It Is Stronger:** Explores a wider spectrum of neural ranking models, including multi-vector and late-interaction (ColBERT) models.

### 8. `York-Rag-System` (baybars-a)
- **Architecture:** Institutional knowledge retrieval and conversational assistant built for educational and organizational QA.
- **Comparison:** Our project provides banking-specific statutory compliance verification, claim checking, and anti-leakage guards.
- **Where It Is Stronger:** Offers a mature, production-tested institutional user experience designed for diverse non-technical campus users.

