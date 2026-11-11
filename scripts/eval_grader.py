"""Phase 5 corrective grader evaluation script.

Runs the grader against labelled passage data and unanswerable questions.
Prints: grading precision/recall, correct-refusal rate, false-refusal rate,
rewrite rate, shortcut rate, average tokens and latency per path.

Usage:
    python scripts/eval_grader.py --profile mock
    python scripts/eval_grader.py --profile dev   # requires .env with LLM_API_KEY

Results are written to evaluation/results/grader_eval_<profile>_<timestamp>.json.
Reruns on the same profile hit the response cache (zero extra cost).
"""

import argparse
import json
import os
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Configure environment BEFORE importing application modules.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

parser = argparse.ArgumentParser(description="Evaluate the corrective grader.")
parser.add_argument(
    "--profile",
    choices=["mock", "dev"],
    default="mock",
    help="LLM profile to use (default: mock).",
)
args = parser.parse_args()

os.environ["LLM_PROFILE"] = args.profile
if args.profile == "mock":
    os.environ.setdefault("APP_ENV", "test")
    # Use a temp DB so the eval does not pollute the main database.
    _TEMP_DB = Path(tempfile.gettempdir()) / "grader_eval.db"
    os.environ["DATABASE_PATH"] = str(_TEMP_DB)

# ---------------------------------------------------------------------------
# Application imports (after env setup)
# ---------------------------------------------------------------------------
from src.config import settings  # noqa: E402
from src.core.grader import grade, GraderDecision  # noqa: E402
from src.core.llm_client import ResilientLLMClient, LLMResponse  # noqa: E402
from src.db.migrations import init_db  # noqa: E402
from src.ingestion.chunker import DocumentChunk  # noqa: E402
from src.ingestion.embeddings import FakeEmbeddingGenerator  # noqa: E402
from src.ingestion.indexer import BM25Indexer, QdrantIndexer  # noqa: E402
from src.rag.baseline import BaselineRAGPipeline, MockCrossEncoderReranker  # noqa: E402

# ---------------------------------------------------------------------------
# Safety guard: fail fast if the profile could reach a live API in test mode.
# ---------------------------------------------------------------------------
if args.profile == "mock":
    resolved = settings.llm
    if not resolved.is_mock:
        print("ERROR: mock profile resolved to a live provider. Aborting.")
        sys.exit(1)

# ---------------------------------------------------------------------------
# Data paths
# ---------------------------------------------------------------------------
EVAL_DIR = _REPO_ROOT / "data" / "eval"
RESULTS_DIR = _REPO_ROOT / "evaluation" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
GRADER_LABELS_FILE = EVAL_DIR / "grader_labels.jsonl"
UNANSWERABLE_FILE = EVAL_DIR / "unanswerable.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                if "_meta" in row:
                    continue
                rows.append(row)
            except json.JSONDecodeError:
                continue
    return rows


# ---------------------------------------------------------------------------
# Build a small in-memory corpus for the unanswerable evaluation.
# ---------------------------------------------------------------------------
def _build_corpus_pipeline(tmp_dir: Path) -> BaselineRAGPipeline:
    """Build a pipeline over synthetic corpus chunks for refusal evaluation."""
    init_db()
    chunks = [
        DocumentChunk(
            chunk_id="EVAL-CHUNK-001",
            doc_id="EVAL-DOC-BASEL",
            doc_title="Basel III Capital Adequacy",
            section_label="Section 1: CET1",
            clause_label="Clause 1.1",
            page=1,
            source_path="eval/synthetic",
            allowed_roles=["analyst", "manager", "auditor"],
            text_content=(
                "Banks must maintain a minimum Common Equity Tier 1 (CET1) capital ratio "
                "of 4.5% of risk-weighted assets under Basel III."
            ),
        ),
        DocumentChunk(
            chunk_id="EVAL-CHUNK-002",
            doc_id="EVAL-DOC-MLR",
            doc_title="FCA Money Laundering Regulations 2017",
            section_label="Section 2: CDD",
            clause_label="Clause 2.1",
            page=5,
            source_path="eval/synthetic",
            allowed_roles=["analyst", "manager", "auditor"],
            text_content=(
                "Firms must apply customer due diligence (CDD) measures when establishing "
                "a new business relationship, including verifying the customer's identity."
            ),
        ),
        DocumentChunk(
            chunk_id="EVAL-CHUNK-003",
            doc_id="EVAL-DOC-MLR",
            doc_title="FCA Money Laundering Regulations 2017",
            section_label="Section 5: SARs",
            clause_label="Clause 5.1",
            page=12,
            source_path="eval/synthetic",
            allowed_roles=["analyst", "manager", "auditor"],
            text_content=(
                "Regulated firms must submit a Suspicious Activity Report to the NCA when "
                "they know, suspect or have reasonable grounds for suspecting money laundering."
            ),
        ),
    ]

    qdrant = QdrantIndexer(
        storage_path=str(tmp_dir / "qdrant"),
        embedder=FakeEmbeddingGenerator(),
    )
    qdrant.index_chunks(chunks)
    bm25 = BM25Indexer(index_path=str(tmp_dir / "bm25.pkl"))
    bm25.build_and_save(chunks)

    return BaselineRAGPipeline(
        qdrant_indexer=qdrant,
        bm25_indexer=bm25,
        reranker=MockCrossEncoderReranker(),
        llm=ResilientLLMClient(),
    )


# ---------------------------------------------------------------------------
# Grader label evaluation (passage relevance precision/recall)
# ---------------------------------------------------------------------------
def evaluate_labels(llm: ResilientLLMClient) -> dict:
    """Evaluate grader precision/recall against grader_labels.jsonl."""
    rows = load_jsonl(GRADER_LABELS_FILE)
    if not rows:
        return {"error": "No labelled rows found in grader_labels.jsonl"}

    # Group passages by question.
    question_groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        question_groups[row["question"]].append(row)

    tp = fp = fn = tn = 0
    path_counts: dict[str, int] = defaultdict(int)
    path_tokens: dict[str, list[int]] = defaultdict(list)
    path_latency: dict[str, list[float]] = defaultdict(list)

    for question, group in question_groups.items():
        passages = []
        gold_labels = {}
        for i, row in enumerate(group):
            chunk_id = f"EVAL-{i:03d}"
            passages.append({
                "chunk_id": chunk_id,
                "text_content": row["passage_text"],
                "doc_title": "Eval Corpus",
                "section_label": "",
                "score": 0.7 - (i * 0.05),
                "allowed_roles": ["analyst", "manager", "auditor"],
            })
            gold_labels[chunk_id] = row["label"]

        def _noop_retrieval(q: str) -> list[dict]:
            return []

        dec: GraderDecision = grade(
            llm=llm,
            question=question,
            passages=passages,
            retrieval_fn=_noop_retrieval,
            role="analyst",
            session_id=None,
        )

        path_counts[dec.path] += 1
        path_tokens[dec.path].append(dec.total_tokens)
        path_latency[dec.path].append(dec.total_latency_ms)

        # Map grader decisions back to gold labels.
        kept_ids = {p["chunk_id"] for p in dec.kept_passages}
        for chunk_id, gold in gold_labels.items():
            predicted_relevant = chunk_id in kept_ids
            gold_relevant = gold == "relevant"
            if gold_relevant and predicted_relevant:
                tp += 1
            elif not gold_relevant and predicted_relevant:
                fp += 1
            elif gold_relevant and not predicted_relevant:
                fn += 1
            else:
                tn += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    shortcut_rate = (
        (path_counts.get("shortcut_keep", 0) + path_counts.get("shortcut_reject", 0))
        / max(sum(path_counts.values()), 1)
    )

    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "shortcut_rate": round(shortcut_rate, 4),
        "path_counts": dict(path_counts),
        "avg_tokens_by_path": {
            path: round(sum(toks) / len(toks), 1) if toks else 0
            for path, toks in path_tokens.items()
        },
        "avg_latency_ms_by_path": {
            path: round(sum(lats) / len(lats), 2) if lats else 0
            for path, lats in path_latency.items()
        },
    }


# ---------------------------------------------------------------------------
# Refusal evaluation (unanswerable / answerable questions)
# ---------------------------------------------------------------------------
def evaluate_refusals(pipeline: BaselineRAGPipeline) -> dict:
    """Evaluate correct-refusal and false-refusal rates using the full pipeline."""
    rows = load_jsonl(UNANSWERABLE_FILE)
    if not rows:
        return {"error": "No rows found in unanswerable.jsonl"}

    # Temporarily enable the grader for this evaluation.
    import src.config as _cfg
    orig = _cfg.settings.ENABLE_CORRECTIVE_GRADER
    _cfg.settings.ENABLE_CORRECTIVE_GRADER = True

    try:
        correct_refusals = 0
        false_refusals = 0
        rewrite_count = 0
        unanswerable_total = 0
        answerable_total = 0

        for row in rows:
            question = row["question"]
            answerable = bool(row.get("answerable", False))
            response = pipeline.ask(question, role="analyst")
            refused = response.grader_refused or response.answer == "I can't find that in the documents available to your role."

            if not answerable:
                unanswerable_total += 1
                if refused:
                    correct_refusals += 1
            else:
                answerable_total += 1
                if refused:
                    false_refusals += 1

            if response.grader_rewrite_used:
                rewrite_count += 1
    finally:
        _cfg.settings.ENABLE_CORRECTIVE_GRADER = orig

    correct_refusal_rate = correct_refusals / max(unanswerable_total, 1)
    false_refusal_rate = false_refusals / max(answerable_total, 1)
    rewrite_rate = rewrite_count / max(len(rows), 1)

    return {
        "correct_refusal_rate": round(correct_refusal_rate, 4),
        "false_refusal_rate": round(false_refusal_rate, 4),
        "rewrite_rate": round(rewrite_rate, 4),
        "correct_refusals": correct_refusals,
        "unanswerable_total": unanswerable_total,
        "false_refusals": false_refusals,
        "answerable_total": answerable_total,
        "total_rewrites": rewrite_count,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    import shutil
    import tempfile
    from datetime import datetime, timezone

    tmp_dir = Path(tempfile.mkdtemp(prefix="grader_eval_"))
    try:
        pipeline = _build_corpus_pipeline(tmp_dir)
        llm = pipeline.llm

        print("=" * 72)
        print(f"GRADER EVALUATION  profile={args.profile}  model={settings.llm.model}")
        print(f"Labels status: DRAFT (requires student review)")
        print("=" * 72)

        # 1. Label precision/recall
        print("\n--- Passage Grading Precision/Recall ---")
        label_results = evaluate_labels(llm)
        for k, v in label_results.items():
            print(f"  {k}: {v}")

        # 2. Refusal evaluation
        print("\n--- Refusal / False-Refusal Rate ---")
        refusal_results = evaluate_refusals(pipeline)
        for k, v in refusal_results.items():
            print(f"  {k}: {v}")

        # 3. Write results file
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        result_path = RESULTS_DIR / f"grader_eval_{args.profile}_{timestamp}.json"
        result_data = {
            "profile": args.profile,
            "model": settings.llm.model,
            "prompt_version": settings.PROMPT_VERSION,
            "labels_status": "draft",
            "timestamp": timestamp,
            "label_evaluation": label_results,
            "refusal_evaluation": refusal_results,
        }
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result_data, f, indent=2)
        print(f"\nResults written to: {result_path}")
        print("=" * 72)

    finally:
        try:
            pipeline.qdrant.close()
        except Exception:
            pass
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
