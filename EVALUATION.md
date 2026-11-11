# Evaluation Framework & Benchmark Methodology

**Project:** Enterprise RAG Assistant for Banking Regulatory Compliance  
**Module:** COM6301 (BSc Final Year Project)  
**Status:** Frozen Scope Baseline (Updated with Profile-Selected API Judge, Caching & Resume)  

---

## 1. Research Objectives & Evaluation Hypotheses

The core empirical contribution is a systematic, layer-by-layer ablation study measuring the incremental performance, security, and efficiency delta introduced by each architectural layer over a standard RAG baseline.

### Primary Hypotheses
1. **$H_1$ (Accuracy):** Adding the Corrective Grader significantly reduces hallucinations and improves RAGAS Faithfulness on ambiguous and unanswerable queries.
2. **$H_2$ (Efficiency):** The Adaptive Router reduces mean latency and token spend by short-circuiting conversational and out-of-scope queries without invoking retrieval.
3. **$H_3$ (Security):** Retrieval-time RBAC achieves an absolute $0.00\%$ information leakage rate across organizational roles.
4. **$H_4$ (Trust):** Clause-level XAI citations provide verifiable attribution without sacrificing context precision.

---

## 2. API-Based Evaluation & Judge Reliability Strategy

### 2.1 Online API Judge with Profile Selection
Evaluation does NOT run offline. It executes against the cloud API model via the OpenAI-compatible endpoint, through the same LLM wrapper as the application. The profile is chosen per run by the researcher; nothing else changes:
1. **Profile Selection:** `--profile mock|dev|demo` (defaults to `LLM_PROFILE` from `.env`). `dev` uses the free provider, `demo` the paid provider, and `mock` is a deterministic offline dry run of the harness. The resolved profile and model are written into every result file.
2. **Deterministic Judge:** Fixed `temperature = 0.0` for all scoring prompts.
3. **Layer-by-Layer Sequential Evaluation:** Run evaluations layer by layer (Run 0, then Run 1, etc.) rather than all at once, preventing quota exhaustion and isolating bugs.
4. **Batching & Rate-Limit Throttling:** Requests are submitted in batches of 5 with an explicit delay between batches to respect provider RPM limits.
5. **Persistent On-Disk Result Caching (`evaluation/cache/`):** Every individual evaluation score is cached to disk as it is computed. If an evaluation run is interrupted by an HTTP 429 quota error, **the run resumes from the exact query where it stopped without repeating completed evaluations**.

### 2.2 Small Judge Model Caveat & Manual Validation
> [!WARNING] Small Judge Model Reliability Caveat
> Small free-tier 7B/8B parameter models (e.g., Llama-3.1-8B-Instant under the `dev` profile) acting as RAGAS judges can exhibit scoring noise, length bias, or lenient faithfulness grading compared to proprietary frontier models. Final reported numbers should therefore be produced under the `demo` profile.
> 
> **Mitigation Protocol:**
> - To ensure academic validity for COM6301, **a stratified sample of 20% of evaluated answers (20 items across all categories) will be independently hand-checked and scored manually**.
> - The correlation between human scores and LLM-judge scores will be documented and discussed in the dissertation methodology and limitations sections.

### 2.3 Resume Semantics & Result Metadata
The requirement is that any evaluation run is reproducible and identifiable after the fact. Every artifact therefore carries its provenance:

- **Per-row metadata:** `llm_profile`, `llm_model`, `prompt_version`, `temperature` (always `0.0`), `config_hash` (ablation flags plus retrieval hyperparameters), `run_id`, and per-question `latency_ms` / token counts.
- **Run-level manifest:** `evaluation/results/<run_id>/run_manifest.json` records the same fields once, alongside the command line, start/end timestamps, and completion status (`completed`, `aborted_spend_limit`, `interrupted`).
- **Artifacts:** `answers.jsonl`, `scores.jsonl`, `ablation_matrix.csv`, `ablation_summary.json` and the LaTeX tables all expose the profile column — no result file can be read without knowing which profile produced it.
- **Resume rule:** `--resume` skips only question IDs already scored with the *same* profile + model + config hash. A mismatch aborts with a clear message rather than silently mixing results from different models or ablation configurations.
- **Crash safety:** completed rows are flushed as they finish; partial in-flight rows are discarded and recomputed on resume. Resume is safe after HTTP 429, a spend-guard stop, or manual interruption.

---

## 3. Gold Question Dataset Specification

A dedicated benchmark dataset of **100 curated regulatory questions** (`data/gold_set.json`) is constructed against the public and synthetic corpus.

### 3.1 Dataset Composition

| Category | Count | Primary Objective | Example Query |
| :--- | :--- | :--- | :--- |
| **Single-Fact** | 30 | Measure baseline Recall@k, MRR, and citation accuracy on discrete facts. | "What is the minimum Common Equity Tier 1 (CET1) capital ratio required under Basel III?" |
| **Multi-Part / Cross-Clause** | 30 | Evaluate Adaptive Router decomposition and multi-context synthesis. | "What are the notification deadlines for a change in Senior Management functions, and how do they interact with operational incident reporting?" |
| **Role-Restricted** | 25 | Verify zero data leakage across Analyst (10), Manager (10), and Auditor (5) permission boundaries. | "What remediation actions were agreed in the 2025 internal liquidity audit report?" *(Submitted by Analyst)* |
| **Unanswerable / Adversarial** | 15 | Test Corrective Grader refusal behavior and prompt-injection resilience. | "What are the FCA regulations regarding retail mortgage lending in Tokyo?" *(Out of jurisdiction/corpus)* |

### 3.2 Gold Dataset Item Schema (`data/gold_set.json`)

```json
{
  "id": "GOLD-042",
  "category": "role_restricted",
  "query": "What remediation actions were agreed in the 2025 internal liquidity audit report?",
  "submitted_by_role": "analyst",
  "required_min_role": "manager",
  "is_answerable": true,
  "expected_route": "SINGLE_SEARCH",
  "expected_behavior": "SAFE_REFUSAL_OR_REDACTION",
  "gold_clause_ids": [
    "INTERNAL-AUDIT-2025_SEC3_REC1"
  ],
  "unauthorized_keywords": [
    "Project Neptune",
    "liquidity buffer deficit 14%",
    "Chief Risk Officer escalation"
  ],
  "ground_truth_answer": "Under role-based access restrictions, this internal audit report is restricted to Manager and Auditor roles. An Analyst query must return no results and state that no authorized evidence was found."
}
```

---

## 4. Evaluation Metrics & Formulations

### 4.1 Retrieval Quality Metrics
- **Recall@k:** $\frac{|\text{RetrievedChunks}_{1..k} \cap \text{GoldClauses}|}{|\text{GoldClauses}|}$
- **Mean Reciprocal Rank (MRR):** $\frac{1}{|Q|} \sum_{i=1}^{|Q|} \frac{1}{\text{rank}_i}$

### 4.2 Answer Quality Metrics (RAGAS & Semantic Correctness)
- **Faithfulness:** Proportion of generated claims verified against context.
- **Answer Relevance:** Semantic alignment of generated answer to query.
- **Context Precision:** Signal-to-noise ratio of retrieved passages.

### 4.3 Security & Access Control Metric
- **Information Leakage Rate:** Percentage of role-restricted queries where unauthorized content or chunk IDs appear in retrieved context or response. **Target: strictly 0.00%**.

### 4.4 Trust & Explainability (XAI) Metrics
- **Citation Precision & Recall:** Precision and recall of cited clauses against gold annotations.
- **Correct Refusal Rate (CRR):** Percentage of unanswerable queries correctly refused.

### 4.5 Operational Efficiency Metrics
- **Latency per Query:** Mean, median, and p95 latency (ms).
- **Tokens per Query per Layer:** Prompt tokens, completion tokens, and total tokens tracked per layer to evaluate free-tier viability.

---

## 5. Ablation Matrix & Protocol (Layer by Layer)

| Run ID | Configuration Name | Router | Grader | Memory & RBAC | XAI Output | Research Question Addressed |
| :---: | :--- | :---: | :---: | :---: | :---: | :--- |
| **Run 0** | **Baseline (Standard RAG)** | ❌ | ❌ | ❌ | ❌ | Raw performance of Hybrid Search + Cross-Encoder on CPU. |
| **Run 1** | **+ Adaptive Router** | ✅ | ❌ | ❌ | ❌ | Does routing reduce latency on greetings and improve multi-part recall? |
| **Run 2** | **+ Corrective Grader** | ✅ | ✅ | ❌ | ❌ | Does passage grading eliminate unanswerable hallucinations? |
| **Run 3** | **+ Memory & RBAC** | ✅ | ✅ | ✅ | ❌ | Does retrieval-time filtering achieve 0% leakage without degrading authorized recall? |
| **Run 4** | **Full System (+ XAI Output)** | ✅ | ✅ | ✅ | ✅ | Impact of clause citations and audit logging on attribution, latency, and token cost. |

---

## 6. Execution Command
```bash
# Free provider during development
python scripts/run_evaluation.py --run 0 --profile dev --batch-size 5 --output-dir ./evaluation/results

# Paid provider for final reported numbers (temperature 0, caching on)
python scripts/run_evaluation.py --run 0 --profile demo --batch-size 5 --output-dir ./evaluation/results

# Resume an interrupted run (same profile and config hash required)
python scripts/run_evaluation.py --run 0 --profile demo --resume --output-dir ./evaluation/results
```

Every result file produced above contains `llm_profile` and `llm_model`; a run cannot be resumed under a different profile without an explicit mismatch error.
