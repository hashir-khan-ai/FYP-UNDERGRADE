# Phased Implementation Plan

**Project:** Enterprise RAG Assistant for Banking Regulatory Compliance  
**Module:** COM6301 (BSc Final Year Project)  
**Status:** Step 1 Master Plan (Updated for Profile-Driven LLM Gateway, Spend Guard & Local CPU Models)  

---

## Roadmap Overview

```mermaid
flowchart LR
    P1[Phase 1:<br/>Foundations & Data] --> P2[Phase 2:<br/>Baseline Hybrid RAG]
    P2 --> P3[Phase 3:<br/>Access Control & Memory]
    P3 --> P4[Phase 4:<br/>Adaptive Router]
    P4 --> P5[Phase 5:<br/>Corrective Grader]
    P5 --> P6[Phase 6:<br/>XAI Output & Streamlit]
    P6 --> P7[Phase 7:<br/>Layer-by-Layer Evaluation]
```

---

## Phase 1: Foundations & Data Preparation

### Goal
Establish project dependencies, SQLite database with migrations and seeds, synthetic regulatory documents, synthetic user directory, `.env.example`, `.gitignore`, and the initial 100-question gold benchmark set.

### Concrete Tasks
1. [x] Initialize `.gitignore` (ignoring `.env`, `data/sqlite/*.db`, `data/qdrant/`, `data/cache/`, `.venv/`, `__pycache__/`, `.pytest_cache/`).
2. [x] Create and verify `requirements.txt` with pinned versions and justification comments, plus `requirements-dev.txt`.
3. [x] Create `.env.example` containing the `mock` / `dev` / `demo` profile blocks, base URLs, model names, timeout/retry/rate-limit settings, prompt version, spend-guard caps, and ablation flags.
4. [x] Build `src/config.py` using Pydantic `BaseSettings` to validate environment variables and resolve `LLM_PROFILE` into one `llm` settings object. Unknown or incomplete profiles must fail fast with a sanitized message; `demo` must never borrow `dev` credentials.
5. [x] Implement `src/db/connection.py` and `src/db/migrations.py` to create SQLite schema (roles, users, sessions, messages, audit_log, llm_calls, documents, plus the `llm_cache` response table).
6. [x] Generate synthetic internal bank documents in `/data/synthetic/` with explicit role boundaries (`SOP-KYC-001.md`, `POLICY-SUPERVISORY-002.md`, `AUDIT-LIQUIDITY-2025.md`).
7. [x] Populate public regulatory sample documents in `/data/raw/` (e.g. FCA BCOBS / MLR regulations).
8. [x] Create `scripts/seed_data.py` to insert synthetic roles, users, and documents into SQLite.
9. [x] Author the 100-question benchmark set in `data/gold_set.json` (single-fact, multi-part, role-restricted, unanswerable).
10. [x] Implement mock LLM fixtures in `tests/conftest.py` ensuring all automated tests run under `LLM_PROFILE=mock` with 0 external API calls, and fail fast if a live profile is ever resolved.

### Files Affected
- `.gitignore`
- `requirements.txt`
- `requirements-dev.txt`
- `.env.example`
- `src/config.py`
- `src/db/connection.py`
- `src/db/migrations.py`
- `src/db/repository.py`
- `scripts/seed_data.py`
- `data/synthetic/*`
- `data/raw/*`
- `data/gold_set.json`
- `tests/conftest.py`
- `tests/test_db.py`
- `tests/test_config.py`
- `tests/test_data_validation.py`

### Automated Tests
- `tests/test_db.py`: Verifies foreign key constraints, WAL mode, user seeding, llm_calls metrics, and parameterized queries.
- `tests/test_config.py`: Verifies `dev`/`demo`/`mock` profile resolution, rejection of unknown or incomplete profiles, and that a live profile can never resolve under pytest.
- `tests/test_data_validation.py`: Verifies that `gold_set.json` validates against the schema and contains 100 items with valid clause IDs.

### Completion Criteria
- Running `python scripts/seed_data.py` creates `./data/sqlite/app.db` without errors.
- `python -c "from src.config import settings; print(settings.llm.profile)"` reports the profile from `.env`.
- All unit tests in `tests/test_db.py`, `tests/test_config.py` and `tests/test_data_validation.py` pass.
- Zero API quota consumed during tests.

---

## Phase 2: Ingestion Pipeline & Baseline Hybrid RAG

### Goal
Implement clause-aware document chunking, hybrid retrieval (BM25 + Qdrant embedded dense vectors) with Reciprocal Rank Fusion, cross-encoder re-ranking on CPU, and baseline standard RAG generation through the single profile-driven LLM wrapper (profiles, caching, spend guard, token telemetry).

### Concrete Tasks
1. [x] Build `src/ingestion/loader.py` for reading markdown and PDF files with header preservation.
2. [x] Build `src/ingestion/chunker.py` to split documents hierarchically by clause, article, and section, tagging each chunk with `allowed_roles`.
3. [x] Implement `src/retrieval/bm25.py` for in-memory keyword search.
4. [x] Implement `src/retrieval/vector_store.py` wrapping Qdrant embedded client with `BAAI/bge-small-en-v1.5` embeddings on CPU.
5. [x] Implement `src/retrieval/hybrid.py` for Reciprocal Rank Fusion ($k=60$) combining BM25 and vector scores.
6. [x] Implement `src/retrieval/reranker.py` using `cross-encoder/ms-marco-MiniLM-L-6-v2` on CPU to score top-20 candidates down to top-5.
7. [x] Build `src/core/llm_client.py` as the **only** LLM entry point: resolves `LLM_PROFILE` (`mock` | `dev` | `demo`), applies 15s timeout, exponential backoff with jitter, token-bucket RPM limiting, and optional dev-only failover.
8. [x] Build `src/core/llm_cache.py` as a thin wrapper over the repository's `llm_cache` table (key = SHA-256 of model + prompt + parameters, including profile and prompt version) and `src/core/spend_guard.py` (per-run call and token caps with a clear stop message). Implement the `mock` provider returning deterministic canned outputs.
9. [x] Create the versioned prompt registry: `prompts/answer/v1.md` and `prompts/rewrite/v1.md`, loaded by a small loader that validates `PROMPT_VERSION` and exposes the version for cache keys and audit rows.
10. [x] Implement per-call token telemetry into the `llm_calls` metrics table (step, profile, model, prompt version, tokens, cached, latency, flags).
11. [x] Build `src/core/pipeline.py` implementing baseline generation (single LLM prompt with retrieved chunks).
12. [x] Create `scripts/run_ingestion.py` to parse all raw/synthetic documents and index them into Qdrant and BM25.
13. [x] Create `scripts/smoke_demo.py` with 10 representative questions (extended with role/refusal cases as later layers land), printing pass/fail, latency, tokens, route and cache status; `--profile` overrides `.env` for the run.
14. [x] **Measure Baseline Latency and Tokens per Query:** Record prompt tokens, completion tokens, and latency for baseline queries.

### Files Affected
- `src/ingestion/loader.py`
- `src/ingestion/chunker.py`
- `src/ingestion/indexer.py`
- `src/retrieval/bm25.py`
- `src/retrieval/vector_store.py`
- `src/retrieval/hybrid.py`
- `src/retrieval/reranker.py`
- `src/core/llm_client.py`
- `src/core/llm_cache.py`
- `src/core/spend_guard.py`
- `src/core/prompts.py`
- `src/core/pipeline.py`
- `prompts/answer/v1.md`
- `prompts/rewrite/v1.md`
- `scripts/run_ingestion.py`
- `scripts/smoke_demo.py`

### Automated Tests
- `tests/test_chunker.py`: Verifies clause metadata retention and role tagging.
- `tests/test_retrieval.py`: Tests BM25, vector search, RRF fusion, and cross-encoder ranking.
- `tests/test_llm_client.py`: Tests profile resolution, cache hit/miss keys, spend-guard exhaustion, retry/backoff logic, and token telemetry using the `mock` provider.
- `tests/test_baseline_pipeline.py`: Tests baseline generation with the `mock` provider.

### Completion Criteria
- Ingestion script processes corpus and populates Qdrant and SQLite document catalog.
- Baseline pipeline executes end-to-end on test queries under all three profiles (mock unconditionally; dev/demo via manual smoke).
- Baseline token consumption and latency metrics recorded per call.
- `python scripts/smoke_demo.py --profile mock` passes 10/10 with 0 external tokens.

---

## Phase 3: Access Control & Conversational Memory

### Goal
Enforce server-side role-based access filtering in Qdrant and BM25 at retrieval time, implement session-based conversation memory in SQLite, and track memory-injected token overhead.

### Concrete Tasks
1. [x] Build `src/core/security.py` to resolve role permissions (`analyst`, `manager`, `auditor`) into deterministic Qdrant payload filters and BM25 candidate filters.
2. [x] Integrate security filters directly into `src/retrieval/vector_store.py` and `src/retrieval/bm25.py`.
3. [x] Implement `src/core/memory.py` to fetch recent turns for active `session_id` and append conversation context.
4. [x] Add query condensation logic if conversational context contains pronominal references.
5. [x] Create automated security test suite `tests/test_rbac_security.py` probing unauthorized access boundaries.
6. [x] **Measure Memory Layer Latency & Tokens:** Quantify the incremental token cost of carrying session history into queries.

### Files Affected
- `src/core/security.py`
- `src/core/memory.py`
- `src/retrieval/vector_store.py`
- `src/retrieval/bm25.py`
- `src/core/pipeline.py`
- `tests/test_rbac_security.py`

### Automated Tests
- `tests/test_rbac_security.py`: Simulates `analyst` query for `manager`-only and `auditor`-only documents. Asserts 0 matching chunks retrieved and zero unauthorized terms leaked.
- `tests/test_memory.py`: Verifies multi-turn message persistence in SQLite.

### Completion Criteria
- Security penetration suite passes with exactly **0.00% leakage rate**.
- Multi-turn conversation context preserved in SQLite.

---

## Phase 4: Layer 1 - Adaptive Router

### Goal
Implement the Adaptive Router to classify queries into direct replies, single searches, or sub-question decompositions, avoiding unnecessary retrieval and handling compound questions.

### Concrete Tasks
1. [x] Build `src/core/router.py` with the strict JSON prompt at `prompts/router/v1.md`, defining routes: `DIRECT_REPLY`, `SINGLE_SEARCH`, `MULTI_PART_SPLIT`.
2. [x] Validate router decisions with a strict Pydantic model (`extra="forbid"`), allowing exactly **one repair retry** that feeds the validation error back to the model; on a second failure, fall back deterministically to `SINGLE_SEARCH` and set `fallback_used=true`.
3. [x] Implement query decomposition handler for `MULTI_PART_SPLIT`: generates 2–3 sub-questions, executes parallel searches, and deduplicates retrieved chunk sets.
4. [x] Wire router into `src/core/pipeline.py` behind the `ENABLE_ADAPTIVE_ROUTER` flag.
5. [x] **Measure Router Latency and Tokens:** Quantify token savings on greetings (direct reply) vs extra tokens consumed during decomposition, including repair-retry overhead.

### Files Affected
- `src/core/router.py`
- `src/core/pipeline.py`
- `src/api/schemas.py`
- `prompts/router/v1.md`
- `tests/test_router.py`

### Automated Tests
- `tests/test_router.py`: Tests router accuracy against labelled test queries, one-repair recovery from malformed JSON, and deterministic `SINGLE_SEARCH` fallback after a second failure (mock profile only).

### Completion Criteria
- Router achieves $> 90\%$ classification accuracy on a 30-query validation subset.
- Greetings bypass retrieval, saving ~90% tokens and latency.
- Malformed JSON never escapes the router: repaired or degraded to `SINGLE_SEARCH`, and visible in the reasoning trace.

---

## Phase 5: Layer 2 - Corrective Grader & Single Retry Loop [Completed]

### Goal
Implement passage relevance grading, automated query rewriting upon poor retrieval, and polite refusal when evidence remains insufficient.

### Concrete Tasks
1. [x] Build `src/core/grader.py` with the strict JSON prompt at `prompts/grader/v1.md`, evaluating relevance of retrieved passages against the query.
2. [x] Validate grader output with a strict Pydantic model, allowing exactly **one repair retry**; if the second attempt is still invalid, fall back to "keep all passages" (no passage dropped) and set `fallback_used=true`.
3. [x] Implement query rewriter (using `prompts/rewrite/v1.md`) to reformulate ambiguous search queries if initial relevance score $< \text{threshold}$ (default $0.65$).
4. [x] Implement conditional retry loop in `src/core/pipeline.py` (maximum 1 retry) controlled by `ENABLE_CORRECTIVE_GRADER`.
5. [x] Implement standard polite refusal generator when second-pass retrieval remains irrelevant.
6. [x] **Measure Grader Latency and Tokens:** Record extra tokens consumed by grading calls, repair retries, and query rewrites.

### Files Affected
- `src/core/grader.py`
- `src/core/pipeline.py`
- `prompts/grader/v1.md`
- `prompts/rewrite/v1.md`
- `tests/test_grader.py`

### Automated Tests
- `tests/test_grader.py`: Verifies grading accuracy, one-repair recovery, keep-all-passages fallback, single retry loop termination, and polite refusal on unanswerable queries (mock profile only).

### Completion Criteria
- Correct Refusal Rate on unanswerable queries reaches $\ge 90\%$.
- Query rewrite retry improves retrieval score on ambiguous test queries.
- Malformed grader JSON degrades to keeping passages, never to silently dropping evidence.

---

## Phase 6: Layer 4 - Explainable Output (XAI) & Streamlit Demo UI [Completed]

### Goal
Implement clause-level citation extraction, reasoning trace logging, persistent SQLite audit logging, FastAPI REST endpoints, and a multi-role Streamlit demonstration UI.

### Concrete Tasks
1. [x] Build `src/core/xai.py` to extract clause citations (`[DocName, ClauseID]`), validate cited `chunk_id`s against role-permitted context, and compile safe 6-step reasoning traces.
2. [x] Implement anti-hallucination citation guard ensuring cited clauses exist in retrieved chunks and are permitted for the user's role (`citations_dropped` counter).
3. [x] Implement structure-aware `heading_path` in `src/ingestion/chunker.py` and `src/ingestion/indexer.py` behind `ENABLE_HEADING_PATH` (default `true`), plus additive audit columns (`citation_count`, `citations_dropped`, `heading_path_enabled`).
4. [x] Build FastAPI endpoints in `src/api/` (`/api/v1/chat/query`, `/api/v1/sessions`, `/api/v1/audit/logs`, `/api/v1/admin/health`) and `scripts/eval_citations.py`.
5. [x] Build Streamlit web application (`DESIGN.md`, `.streamlit/config.toml`, `src/ui/api_client.py`, `src/ui/app.py`):
   - Login screen with server-verified role badge (`Analyst`, `Manager`, `Auditor`) and `st.session_state`-only token storage.
   - Chat session interface with message history, new/open/delete session controls, and distinct refusal state.
   - Interactive citation panel displaying `doc_title`, `heading_path`, `clause`, `page`, `chunk_id`, and verbatim `quote_snippet` ($\le 200$ chars).
   - Collapsible safe reasoning trace viewer, settings panel (`mock`/`dev`/`demo` badge), and Auditor-only audit log summary view.
6. [x] **Measure XAI Citations & Support:** Verified 100% citation validity and 100% verbatim snippet support via `scripts/eval_citations.py --profile mock`.
7. [x] Create `tests/test_xai.py`, `tests/test_ui_client.py`, and `docs/UI_TEST_CHECKLIST.md`.

### Files Affected
- `src/core/xai.py`
- `src/db/repository.py`
- `src/api/main.py`
- `src/api/routes.py`
- `src/api/schemas.py`
- `src/ui/app.py`
- `scripts/smoke_demo.py`
- `tests/test_api.py`

### Automated Tests
- `tests/test_xai.py`: Verifies citation parsing and hallucination detection.
- `tests/test_api.py`: Tests all FastAPI endpoints, status codes, input validations, and role restrictions.

### Completion Criteria
- Streamlit UI runs locally on `http://localhost:8501`, connecting cleanly to FastAPI on `http://127.0.0.1:8000`.
- Users can switch roles in UI and immediately experience permission boundaries and citation drawers.
- Every chat turn records a complete audit log entry in SQLite.

---

## Phase 7: Layer-by-Layer Evaluation, Ablation Benchmark & Write-Up [Completed]

### Goal
Execute the 100-question benchmark layer by layer across all configurations (`A0_baseline`..`A5_full_xai` + `RBAC_OFF_DEMO`) with rate-limit handling and result caching, record all metrics (Recall, MRR, nDCG@5, Answer F1, Citation Validity/Support, CRR, FRR, Leakage, Routing Accuracy, Latency, Tokens), and export publication-ready tables with bootstrap 95% confidence intervals.

### Concrete Tasks
1. [x] Build `scripts/build_gold_set.py` (`--template`, `--seed-default`, `--suggest --profile dev|mock`) and `scripts/validate_gold_set.py` over `data/eval/gold_set.jsonl` (100 questions across 5 types: `single_fact`, `multi_part`, `cross_reference`, `role_restricted`, `unanswerable`, $\ge 15$ per type).
2. [x] Build `scripts/eval_retrieval.py` (zero LLM calls) evaluating `bm25_only`, `vector_only`, `hybrid_rrf`, and `hybrid_rerank` with `ENABLE_HEADING_PATH` on/off in isolated temporary indices, including `< 100` chunk warning.
3. [x] Build `scripts/run_ablation.py` supporting configurations `A0_baseline`..`A5_full_xai` + `RBAC_OFF_DEMO` (`DEMONSTRATION ONLY`), `--profile mock|dev|demo`, temperature 0, per-question JSONL checkpointing, `--resume`, `--limit`, `--judge`, `ProfileMismatchError` guard, and `--require-reviewed` review gate.
4. [x] Build `scripts/make_report_tables.py` writing `results/ablation_table.md` and `results/ablation_table.csv` with bootstrap 95% CIs, interval overlap flags vs `A0_baseline`, `routing_accuracy` rendered as `"n/a"` where router is off, separate live/cached/non-LLM refusal counts, and explicit `HARNESS CHECK ONLY (mock)` / `LIVE` banners.
5. [x] Build `scripts/corpus_manifest.py` and `docs/CORPUS_GUIDE.md` to audit document sidecars (`source`, `licence`, `allowed_roles`, chunk counts) and scaffold templates for expansion toward 20–40 documents.
6. [x] Create `tests/test_phase7_eval.py` covering metric fixtures, gold-set validator errors, ablation config isolation, profile recording, checkpoint resume, routing `n/a` rendering, cost separation, review gate, and manifest audits (13 unit tests).
7. [x] Expand corpus to 24 documents (101 chunks), review gold questions (45 verified questions across all 5 types satisfying `--require-reviewed` gate), rebuild main production store, and export publication-ready dissertation tables (`results/dissertation_tables.tex`).
8. [ ] Optional live `--profile dev` / `--profile demo` benchmark execution once external LLM API credentials are configured in `.env`.

### Files Affected
- `scripts/run_evaluation.py`
- `evaluation/results/<run_id>/run_manifest.json`
- `evaluation/results/<run_id>/answers.jsonl`
- `evaluation/results/ablation_matrix.csv`
- `evaluation/results/ablation_summary.json`
- `evaluation/results/dissertation_tables.tex`

### Automated Tests
- `tests/test_evaluation_harness.py`: Verifies resume skips completed IDs, rejects a profile/config mismatch, and writes profile metadata into every result artifact (mock profile only).

### Completion Criteria
- Complete ablation results matrix generated, each file carrying the active `llm_profile`.
- Resume after interruption works without recomputing completed questions or mixing profiles.
- Zero data leakage confirmed.
- Hand-check sample completed and documented.
- LaTeX tables generated and ready for dissertation.
