"""Offline retrieval evaluation script (zero LLM calls).

For each gold question in ``data/eval/gold_set.jsonl`` that expects an answer
(``expected_behaviour == "answer"``), runs retrieval as ``role_asking`` and
computes Recall@k (k=1,3,5), MRR, and nDCG@5 against ``gold_chunk_ids`` across
four retrieval modes:
  1. ``bm25_only``
  2. ``vector_only``
  3. ``hybrid_rrf``
  4. ``hybrid_rerank`` (hybrid RRF + local CPU cross-encoder re-ranker)

Supports ``ENABLE_HEADING_PATH`` on/off by building temporary isolated Qdrant
and BM25 indices in ``tempfile.TemporaryDirectory`` so the main production
index in ``./data`` is never overwritten.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import settings
from src.core.security import enforce_role_visibility, normalize_role
from src.evaluation.gold_set import GoldQuestionItem, load_gold_set
from src.evaluation.metrics import bootstrap_ci, ndcg_at_k, recall_at_k, reciprocal_rank
from src.ingestion.chunker import ClauseAwareChunker, DocumentChunk
from src.ingestion.indexer import BM25Indexer, QdrantIndexer
from src.ingestion.loaders import DocumentLoader
from src.ingestion.run import discover_documents
from src.rag.baseline import CrossEncoderReranker, MockCrossEncoderReranker, reciprocal_rank_fusion

RETRIEVAL_MODES: tuple[str, ...] = (
    "bm25_only",
    "vector_only",
    "hybrid_rrf",
    "hybrid_rerank",
)


def load_corpus_chunks(data_dir: str | Path = "data") -> tuple[int, list[DocumentChunk]]:
    """Parse and chunk all corpus documents without writing to the main index."""
    file_paths = discover_documents(data_dir)
    chunker = ClauseAwareChunker()
    all_chunks: list[DocumentChunk] = []
    doc_count = 0
    for path in file_paths:
        doc = DocumentLoader.load(path)
        chunks = chunker.chunk_document(doc)
        if chunks:
            all_chunks.extend(chunks)
            doc_count += 1
    return doc_count, all_chunks


def _aggregate_metric_rows(rows: list[dict[str, float]]) -> dict[str, Any]:
    """Compute mean and bootstrap 95% CI across a list of per-question metric dicts."""
    if not rows:
        return {
            "count": 0,
            "recall@1": 0.0,
            "recall@3": 0.0,
            "recall@5": 0.0,
            "mrr": 0.0,
            "ndcg@5": 0.0,
            "ci_95": {},
        }
    metrics = ("recall@1", "recall@3", "recall@5", "mrr", "ndcg@5")
    summary: dict[str, Any] = {"count": len(rows), "ci_95": {}}
    for m in metrics:
        vals = [float(r[m]) for r in rows]
        ci = bootstrap_ci(vals, n_boot=1000, seed=42)
        summary[m] = ci["mean"]
        summary["ci_95"][m] = {"ci_low": ci["ci_low"], "ci_high": ci["ci_high"]}
    return summary


def evaluate_for_heading_setting(
    heading_path_enabled: bool,
    chunks: list[DocumentChunk],
    questions: list[GoldQuestionItem],
    reranker: CrossEncoderReranker | MockCrossEncoderReranker,
) -> dict[str, Any]:
    """Build a temporary isolated index for ``heading_path_enabled`` and evaluate all 4 modes."""
    original_heading_flag = settings.ENABLE_HEADING_PATH
    settings.ENABLE_HEADING_PATH = heading_path_enabled
    top_k = settings.RETRIEVAL_TOP_K_HYBRID
    top_n = settings.RERANKER_TOP_N

    try:
        with tempfile.TemporaryDirectory(prefix="eval_retr_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            qdrant = QdrantIndexer(storage_path=str(tmp_path / "qdrant"))
            bm25 = BM25Indexer(index_path=str(tmp_path / "bm25_index.pkl"))
            try:
                t0 = time.perf_counter()
                qdrant.index_chunks(chunks)
                bm25.build_and_save(chunks)
                index_build_ms = round((time.perf_counter() - t0) * 1000.0, 2)

                per_mode_rows: dict[str, list[dict[str, Any]]] = {m: [] for m in RETRIEVAL_MODES}
                per_mode_by_type: dict[str, dict[str, list[dict[str, float]]]] = {
                    m: defaultdict(list) for m in RETRIEVAL_MODES
                }

                for item in questions:
                    if item.expected_behaviour != "answer" or not item.gold_chunk_ids:
                        continue
                    role = normalize_role(item.role_asking)
                    query = item.question
                    gold_ids = item.gold_chunk_ids

                    bm25_hits = bm25.search(query, top_k=top_k, role=role).hits
                    vec_hits = qdrant.search(query, top_k=top_k, role=role).hits
                    rrf_hits = reciprocal_rank_fusion(
                        bm25_hits,
                        vec_hits,
                        k=settings.RETRIEVAL_RRF_K,
                        top_k=top_k,
                    )
                    reranked_raw = reranker.rerank(query, rrf_hits, top_n=top_n)
                    reranked_hits, _ = enforce_role_visibility(reranked_raw, role)

                    mode_lists: dict[str, list[str]] = {
                        "bm25_only": [str(h.get("chunk_id", "")) for h in bm25_hits],
                        "vector_only": [str(h.get("chunk_id", "")) for h in vec_hits],
                        "hybrid_rrf": [str(h.get("chunk_id", "")) for h in rrf_hits],
                        "hybrid_rerank": [str(h.get("chunk_id", "")) for h in reranked_hits],
                    }

                    for mode_name, retrieved_ids in mode_lists.items():
                        score_row = {
                            "id": item.id,
                            "type": item.type,
                            "role_asking": role,
                            "recall@1": recall_at_k(retrieved_ids, gold_ids, 1),
                            "recall@3": recall_at_k(retrieved_ids, gold_ids, 3),
                            "recall@5": recall_at_k(retrieved_ids, gold_ids, 5),
                            "mrr": reciprocal_rank(retrieved_ids, gold_ids),
                            "ndcg@5": ndcg_at_k(retrieved_ids, gold_ids, 5),
                        }
                        per_mode_rows[mode_name].append(score_row)
                        per_mode_by_type[mode_name][item.type].append(score_row)

                modes_summary: dict[str, Any] = {}
                for mode_name in RETRIEVAL_MODES:
                    overall = _aggregate_metric_rows(per_mode_rows[mode_name])
                    by_type = {
                        qtype: _aggregate_metric_rows(rows)
                        for qtype, rows in sorted(per_mode_by_type[mode_name].items())
                    }
                    modes_summary[mode_name] = {
                        "overall": overall,
                        "by_question_type": by_type,
                    }

                return {
                    "enable_heading_path": heading_path_enabled,
                    "index_build_ms": index_build_ms,
                    "questions_evaluated": len(per_mode_rows["bm25_only"]),
                    "modes": modes_summary,
                }
            finally:
                qdrant.close()
    finally:
        settings.ENABLE_HEADING_PATH = original_heading_flag


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate retrieval modes (no LLM calls).")
    parser.add_argument(
        "--gold-set",
        type=str,
        default="data/eval/gold_set.jsonl",
        help="Path to gold_set.jsonl (default: data/eval/gold_set.jsonl).",
    )
    parser.add_argument(
        "--heading-path",
        choices=["on", "off", "both"],
        default="both",
        help="Evaluate with ENABLE_HEADING_PATH on, off, or both (default: both).",
    )
    parser.add_argument(
        "--mock-reranker",
        action="store_true",
        help="Use deterministic MockCrossEncoderReranker instead of local CPU cross-encoder.",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default="evaluation/results",
        help="Directory for JSON output artifacts (default: evaluation/results).",
    )
    args = parser.parse_args()

    questions = load_gold_set(args.gold_set)
    answerable = [q for q in questions if q.expected_behaviour == "answer"]
    doc_count, chunks = load_corpus_chunks("data")

    reranker: CrossEncoderReranker | MockCrossEncoderReranker = (
        MockCrossEncoderReranker() if args.mock_reranker else CrossEncoderReranker()
    )

    settings_to_run: list[bool]
    if args.heading_path == "on":
        settings_to_run = [True]
    elif args.heading_path == "off":
        settings_to_run = [False]
    else:
        settings_to_run = [False, True]

    runs: dict[str, Any] = {}
    for hp_flag in settings_to_run:
        key = "heading_path_on" if hp_flag else "heading_path_off"
        runs[key] = evaluate_for_heading_setting(
            heading_path_enabled=hp_flag,
            chunks=chunks,
            questions=answerable,
            reranker=reranker,
        )

    now_utc = datetime.now(timezone.utc)
    payload = {
        "timestamp_utc": now_utc.isoformat(),
        "date": now_utc.strftime("%Y-%m-%d"),
        "gold_set_path": args.gold_set,
        "gold_set_status_note": (
            "unreviewed_draft"
            if any(q.status == "draft" for q in questions)
            else "reviewed"
        ),
        "total_gold_questions": len(questions),
        "answerable_questions_evaluated": len(answerable),
        "corpus": {
            "documents_count": doc_count,
            "chunks_count": len(chunks),
            "embedding_model": settings.EMBEDDING_MODEL_NAME,
            "reranker_model": (
                "mock_reranker" if args.mock_reranker else settings.RERANKER_MODEL_NAME
            ),
        },
        "index_settings": {
            "retrieval_top_k_hybrid": settings.RETRIEVAL_TOP_K_HYBRID,
            "retrieval_rrf_k": settings.RETRIEVAL_RRF_K,
            "reranker_top_n": settings.RERANKER_TOP_N,
            "rbac_enabled": True,
        },
        "runs": runs,
    }

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts_slug = now_utc.strftime("%Y%m%d_%H%M%S")
    timestamped_path = out_dir / f"retrieval_eval_{ts_slug}.json"
    latest_path = out_dir / "retrieval_eval_latest.json"

    for path in (timestamped_path, latest_path):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)

    print("==============================================================================")
    print("RETRIEVAL EVALUATION SUMMARY (ZERO LLM CALLS, RBAC=ON)")
    print(f"Corpus Scope      : {doc_count} documents, {len(chunks)} chunks")
    print(f"Answerable Queries: {len(answerable)} evaluated across 4 modes")
    if len(chunks) < 100:
        print("WARNING           : corpus too small for meaningful retrieval comparison (< 100 chunks)")
    print("==============================================================================")
    for run_key, run_data in runs.items():
        hp_str = "ON" if run_data["enable_heading_path"] else "OFF"
        print(f"\n--- ENABLE_HEADING_PATH = {hp_str} (temp index build: {run_data['index_build_ms']:.0f} ms) ---")
        print(f"{'Mode':<16} {'Recall@1':>9} {'Recall@3':>9} {'Recall@5':>9} {'MRR':>9} {'nDCG@5':>9}")
        print("-" * 66)
        for mode_name in RETRIEVAL_MODES:
            ov = run_data["modes"][mode_name]["overall"]
            print(
                f"{mode_name:<16} "
                f"{ov['recall@1']:>9.4f} "
                f"{ov['recall@3']:>9.4f} "
                f"{ov['recall@5']:>9.4f} "
                f"{ov['mrr']:>9.4f} "
                f"{ov['ndcg@5']:>9.4f}"
            )
            for qtype, tmetrics in run_data["modes"][mode_name]["by_question_type"].items():
                print(
                    f"  .{qtype:<13} "
                    f"{tmetrics['recall@1']:>9.4f} "
                    f"{tmetrics['recall@3']:>9.4f} "
                    f"{tmetrics['recall@5']:>9.4f} "
                    f"{tmetrics['mrr']:>9.4f} "
                    f"{tmetrics['ndcg@5']:>9.4f}"
                )
    print("==============================================================================")
    print(f"Saved results to: {timestamped_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

