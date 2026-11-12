# Phase 7 Ablation Evaluation Report

- **Execution Mode:** `HARNESS CHECK ONLY (mock profile — deterministic offline responses)`
- **LLM Profile / Model:** `mock` (`mock`)
- **Gold Set Status:** `unreviewed_draft` ($n = 25$ questions)
- **Corpus:** 6 documents, 26 chunks, embeddings `BAAI/bge-small-en-v1.5`, re-ranker `cross-encoder/ms-marco-MiniLM-L-6-v2`
- **Date:** `2026-11-12`

> **IMPORTANT NOTE (HARNESS CHECK ONLY):** All numbers in this table were generated under `LLM_PROFILE=mock` using deterministic offline responses (`0` live API quota spent). They verify end-to-end pipeline wiring, RBAC isolation, routing, grading, and citation validation, and must **not** be cited as live LLM quality benchmarks.

## 1. Main Ablation Matrix

| Config | Mode / Status | $n$ | Recall@1 | Recall@3 | Recall@5 (95% CI) | MRR | nDCG@5 (95% CI) | Answer F1 | Cit. Validity | Cit. Support | CRR (Refusal) | FRR | Leakage Rate | Route Acc. | Latency Med / p95 (ms) | Calls / Query | Tokens / Query |
| :--- | :--- | ---: | ---: | ---: | :--- | ---: | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- | ---: | ---: |
| `A0_baseline` | HARNESS CHECK (mock) | 25 | 0.7222 | 1.0000 | 1.0000 [1.000, 1.000] | 1.0000 | 0.9911 [0.978, 1.000] | 0.4319 | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 | 0.6000 | 651.9 / 788.9 | 1.00 | 488.8 |
| `A1_heading_path` | HARNESS CHECK (mock) | 25 | 0.7222 | 0.9722 | 1.0000 [1.000, 1.000] | 1.0000 | 0.9828 [0.961, 1.000] | 0.4293 | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 | 0.6000 | 783.0 / 936.1 | 1.00 | 528.0 |
| `A2_memory` | HARNESS CHECK (mock) | 25 | 0.7222 | 0.9722 | 1.0000 [1.000, 1.000] | 1.0000 | 0.9828 [0.961, 1.000] | 0.4293 | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 | 0.6000 | 753.9 / 856.3 | 1.00 | 528.0 |
| `A3_router` | HARNESS CHECK (mock) | 25 | 0.6944 | 0.9167 | 0.9444 [0.833, 1.000] | 0.9444 | 0.9272 [0.808, 0.996] | 0.4123 | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 | 0.6000 | 911.0 / 1370.5 | 1.92 | 866.1 |
| `A4_grader` | HARNESS CHECK (mock) | 25 | 0.6944 | 0.9167 | 0.9444 [0.833, 1.000] | 0.9444 | 0.9272 [0.808, 0.996] | 0.4123 | 1.0000 | 1.0000 | 1.0000 | 0.0556 | 0.0000 | 0.6000 | 937.9 / 1679.4 | 1.04 | 446.4 |
| `A5_full_xai` | HARNESS CHECK (mock) | 25 | 0.6944 | 0.9167 | 0.9444 [0.833, 1.000] | 0.9444 | 0.9272 [0.808, 0.996] | 0.4123 | 1.0000 | 1.0000 | 1.0000 | 0.0556 | 0.0000 | 0.6000 | 836.7 / 1039.4 | 0.72 | 360.0 |
| `RBAC_OFF_DEMO` | DEMO ONLY (DEMONSTRATION ONLY — DO NOT USE AS RESULT) | 25 | 0.7222 | 0.9722 | 1.0000 [1.000, 1.000] | 1.0000 | 0.9828 [0.961, 1.000] | 0.4293 | 0.9444 | 1.0000 | 0.0000 | 0.0000 | 0.5000 | 0.6000 | 910.4 / 1049.0 | 1.00 | 523.8 |

## 2. Bootstrap 95% Confidence Interval Overlap vs `A0_baseline`

When two configurations' 95% bootstrap confidence intervals overlap (`Overlaps A0 = True`), no statistically significant improvement is claimed.

| Config | Recall@5 Overlaps A0 | nDCG@5 Overlaps A0 | Answer F1 Overlaps A0 | CRR Overlaps A0 | Route Acc. Overlaps A0 | Leakage Overlaps A0 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `A1_heading_path` | Yes (ns) | Yes (ns) | Yes (ns) | Yes (ns) | Yes (ns) | Yes (ns) |
| `A2_memory` | Yes (ns) | Yes (ns) | Yes (ns) | Yes (ns) | Yes (ns) | Yes (ns) |
| `A3_router` | Yes (ns) | Yes (ns) | Yes (ns) | Yes (ns) | Yes (ns) | Yes (ns) |
| `A4_grader` | Yes (ns) | Yes (ns) | Yes (ns) | **No (sig.)** | Yes (ns) | Yes (ns) |
| `A5_full_xai` | Yes (ns) | Yes (ns) | Yes (ns) | **No (sig.)** | Yes (ns) | Yes (ns) |
| `RBAC_OFF_DEMO` | Yes (ns) | Yes (ns) | Yes (ns) | Yes (ns) | Yes (ns) | **No (sig.)** |
