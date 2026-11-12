# Phase 7 Ablation Evaluation Report

- **Execution Mode:** `HARNESS CHECK ONLY (mock profile — deterministic offline responses)`
- **LLM Profile / Model:** `mock` (`mock`)
- **Gold Set Status:** `reviewed` ($n = 45$ questions)
- **Corpus:** 24 documents, 101 chunks, embeddings `BAAI/bge-small-en-v1.5`, re-ranker `cross-encoder/ms-marco-MiniLM-L-6-v2`
- **Date:** `2026-11-12`

> **IMPORTANT NOTE (HARNESS CHECK ONLY):** All numbers in this table were generated under `LLM_PROFILE=mock` using deterministic offline responses (`0` live API quota spent). They verify end-to-end pipeline wiring, RBAC isolation, routing, grading, and citation validation, and must **not** be cited as live LLM quality benchmarks.

## 1. Main Ablation Matrix

Routing accuracy is `n/a` where the router is off or no routing labels apply. Cost columns separate **live** (uncached, quota-consuming) calls, **cached** calls, and refusals that made **no LLM call**; tokens are counted from live calls only. Uncached latency uses only queries with zero cache hits.

| Config | Mode / Status | $n$ | Recall@1 | Recall@3 | Recall@5 (95% CI) | MRR | nDCG@5 (95% CI) | Answer F1 | Cit. Validity | Cit. Support | CRR (Refusal) | FRR | Leakage Rate | Route Acc. | Latency Med / p95 (ms) | Uncached Latency Med (ms, n) | Live Calls / Query | Cached Calls / Query | Refusals w/o LLM | Live Tokens / Query |
| :--- | :--- | ---: | ---: | ---: | :--- | ---: | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- | :--- | ---: | ---: | ---: | ---: |
| `A0_baseline` | HARNESS CHECK (mock) | 45 | 0.7143 | 0.9286 | 0.9429 [0.886, 0.986] | 1.0000 | 0.9477 [0.902, 0.983] | 0.3756 | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 | n/a | 884.4 / 1182.4 | 876.4 (n=34) | 0.76 | 0.24 | 0 | 381.6 |
| `A1_heading_path` | HARNESS CHECK (mock) | 45 | 0.7143 | 0.9286 | 0.9429 [0.886, 0.986] | 1.0000 | 0.9446 [0.900, 0.980] | 0.3750 | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 | n/a | 1073.0 / 1335.1 | 1088.7 (n=32) | 0.71 | 0.29 | 0 | 383.8 |
| `A2_memory` | HARNESS CHECK (mock) | 45 | 0.7143 | 0.9286 | 0.9429 [0.886, 0.986] | 1.0000 | 0.9446 [0.900, 0.980] | 0.3750 | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 | n/a | 970.8 / 1373.1 | n/a (n=0) | 0.00 | 1.00 | 0 | 0.0 |
| `A3_router` | HARNESS CHECK (mock) | 45 | 0.7000 | 0.9000 | 0.9143 [0.843, 0.971] | 0.9714 | 0.9161 [0.841, 0.971] | 0.3655 | 1.0000 | 1.0000 | 0.0000 | 0.0000 | 0.0000 | 0.5556 | 959.3 / 1231.4 | n/a (n=0) | 0.40 | 1.60 | 0 | 150.9 |
| `A4_grader` | HARNESS CHECK (mock) | 45 | 0.7000 | 0.9000 | 0.9143 [0.843, 0.971] | 0.9714 | 0.9161 [0.841, 0.971] | 0.3655 | 1.0000 | 1.0000 | 0.9000 | 0.0286 | 0.0000 | 0.5556 | 955.2 / 1291.3 | n/a (n=0) | 0.07 | 1.96 | 0 | 12.5 |
| `A5_full_xai` | HARNESS CHECK (mock) | 45 | 0.7000 | 0.9000 | 0.9143 [0.843, 0.971] | 0.9714 | 0.9161 [0.841, 0.971] | 0.3655 | 1.0000 | 1.0000 | 0.9000 | 0.0286 | 0.0000 | 0.5556 | 903.8 / 1268.2 | n/a (n=0) | 0.00 | 2.02 | 0 | 0.0 |
| `RBAC_OFF_DEMO` | DEMO ONLY (DEMONSTRATION ONLY — DO NOT USE AS RESULT) | 45 | 0.7143 | 0.9286 | 0.9429 [0.886, 0.986] | 1.0000 | 0.9446 [0.900, 0.980] | 0.3742 | 0.9829 | 1.0000 | 0.0000 | 0.0000 | 0.5333 | n/a | 843.6 / 1106.7 | 1128.2 (n=4) | 0.09 | 0.91 | 0 | 48.0 |

## 2. Bootstrap 95% Confidence Interval Overlap vs `A0_baseline`

When two configurations' 95% bootstrap confidence intervals overlap (`Overlaps A0 = True`), no statistically significant improvement is claimed.

| Config | Recall@5 Overlaps A0 | nDCG@5 Overlaps A0 | Answer F1 Overlaps A0 | CRR Overlaps A0 | Route Acc. Overlaps A0 | Leakage Overlaps A0 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `A1_heading_path` | Yes (ns) | Yes (ns) | Yes (ns) | Yes (ns) | - | Yes (ns) |
| `A2_memory` | Yes (ns) | Yes (ns) | Yes (ns) | Yes (ns) | - | Yes (ns) |
| `A3_router` | Yes (ns) | Yes (ns) | Yes (ns) | Yes (ns) | - | Yes (ns) |
| `A4_grader` | Yes (ns) | Yes (ns) | Yes (ns) | **No (sig.)** | - | Yes (ns) |
| `A5_full_xai` | Yes (ns) | Yes (ns) | Yes (ns) | **No (sig.)** | - | Yes (ns) |
| `RBAC_OFF_DEMO` | Yes (ns) | Yes (ns) | Yes (ns) | Yes (ns) | - | **No (sig.)** |
