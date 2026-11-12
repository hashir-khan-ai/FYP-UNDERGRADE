"""Phase 7 ablation runner across configurations A0..A5 (+ optional RBAC_OFF_DEMO).

Features:
- Named configuration matrix: ``A0_baseline``, ``A1_heading_path``, ``A2_memory``,
  ``A3_router``, ``A4_grader``, ``A5_full_xai``, plus ``RBAC_OFF_DEMO`` (enabled
  only via ``--include-rbac-off`` which sets ``BASELINE_ABLATION=True`` for that
  row and labels it ``DEMONSTRATION ONLY — DO NOT USE AS RESULT``).
- Temporary isolated indices for ``ENABLE_HEADING_PATH`` off vs on so the main
  corpus index is never overwritten.
- Per-question JSONL checkpointing and ``--resume`` after quota or spend-guard
  interruptions.
- Refuses to mix ``llm_profile`` or ``llm_model`` inside one run/checkpoint.
- Computes bootstrap 95% confidence intervals and interval-overlap flags.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import settings
from src.core.llm_client import ResilientLLMClient
from src.core.spend_guard import SpendGuardExceededError, spend_guard
from src.evaluation.ablation import (
    ABLATION_MATRIX,
    DEMO_ONLY_BANNER,
    AblationConfigSpec,
    ProfileMismatchError,
    aggregate_ablation_rows,
    append_checkpoint_row,
    apply_ablation_config,
    ensure_same_profile,
    evaluate_single_question,
    load_checkpoint_rows,
)
from src.evaluation.gold_set import GoldQuestionItem, load_gold_set
from src.ingestion.chunker import ClauseAwareChunker, DocumentChunk
from src.ingestion.indexer import BM25Indexer, QdrantIndexer
from src.ingestion.loaders import DocumentLoader
from src.ingestion.run import discover_documents
from src.rag.baseline import BaselineRAGPipeline, CrossEncoderReranker, MockCrossEncoderReranker

DEFAULT_CONFIG_NAMES: tuple[str, ...] = (
    "A0_baseline",
    "A1_heading_path",
    "A2_memory",
    "A3_router",
    "A4_grader",
    "A5_full_xai",
)


def _select_questions(questions: list[GoldQuestionItem], limit: int | None) -> list[GoldQuestionItem]:
    """Select up to ``limit`` questions, preserving balanced sampling across types."""
    if limit is None or limit <= 0 or limit >= len(questions):
        return list(questions)

    by_type: dict[str, list[GoldQuestionItem]] = {}
    for q in questions:
        by_type.setdefault(q.type, []).append(q)

    selected: list[GoldQuestionItem] = []
    round_idx = 0
    type_keys = list(by_type.keys())
    while len(selected) < limit:
        added_in_round = False
        for tkey in type_keys:
            bucket = by_type[tkey]
            if round_idx < len(bucket) and len(selected) < limit:
                selected.append(bucket[round_idx])
                added_in_round = True
        if not added_in_round:
            break
        round_idx += 1
    return selected


def _load_corpus_chunks(data_dir: str | Path = "data") -> tuple[int, list[DocumentChunk], dict[str, dict[str, Any]]]:
    """Load corpus chunks and build a ``chunk_id -> metadata`` lookup dict."""
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

    lookup: dict[str, dict[str, Any]] = {}
    for ch in all_chunks:
        lookup[ch.chunk_id] = {
            "chunk_id": ch.chunk_id,
            "doc_id": ch.doc_id,
            "doc_title": ch.doc_title,
            "heading_path": ch.heading_path,
            "clause_label": ch.clause_label,
            "allowed_roles": list(ch.allowed_roles),
        }
    return doc_count, all_chunks, lookup


def run_ablation_suite(
    profile: str,
    questions: list[GoldQuestionItem],
    config_names: list[str],
    include_rbac_off: bool = False,
    resume: bool = False,
    run_judge: bool = False,
    mock_reranker: bool = False,
    cache_dir: Path = Path("evaluation/cache"),
    out_dir: Path = Path("evaluation/results"),
) -> dict[str, Any]:
    """Execute the configured ablation rows and write checkpointed JSON results."""
    original_profile = settings.LLM_PROFILE
    original_temp = settings.LLM_TEMPERATURE
    settings.LLM_PROFILE = profile  # type: ignore[assignment]
    settings.LLM_TEMPERATURE = 0.0

    try:
        resolved_llm = settings.llm
        active_profile = resolved_llm.profile
        active_model = resolved_llm.model

        # Raise spend guard ceiling for mock harness runs so 100x7 rows complete cleanly
        if active_profile == "mock":
            spend_guard.max_calls = max(spend_guard.max_calls, 10_000)
            spend_guard.max_tokens = max(spend_guard.max_tokens, 5_000_000)
        spend_guard.reset()

        doc_count, all_chunks, chunk_lookup = _load_corpus_chunks("data")
        reranker = MockCrossEncoderReranker() if mock_reranker else CrossEncoderReranker()
        llm = ResilientLLMClient()

        specs_to_run: list[AblationConfigSpec] = []
        for cname in config_names:
            if cname not in ABLATION_MATRIX:
                raise ValueError(f"Unknown ablation config '{cname}'. Valid: {list(ABLATION_MATRIX)}")
            spec = ABLATION_MATRIX[cname]
            if not spec.enable_rbac and not include_rbac_off:
                raise RuntimeError(
                    "RBAC_OFF_DEMO requires --include-rbac-off flag to set BASELINE_ABLATION=True."
                )
            specs_to_run.append(spec)

        if include_rbac_off and all(s.name != "RBAC_OFF_DEMO" for s in specs_to_run):
            specs_to_run.append(ABLATION_MATRIX["RBAC_OFF_DEMO"])

        with tempfile.TemporaryDirectory(prefix="ablation_idx_") as tmp_root:
            tmp_base = Path(tmp_root)
            pipelines: dict[bool, BaselineRAGPipeline] = {}
            qdrant_clients: list[QdrantIndexer] = []

            try:
                for hp_flag in {s.enable_heading_path for s in specs_to_run}:
                    sub = tmp_base / ("hp_on" if hp_flag else "hp_off")
                    q_idx = QdrantIndexer(storage_path=str(sub / "qdrant"))
                    b_idx = BM25Indexer(index_path=str(sub / "bm25.pkl"))
                    qdrant_clients.append(q_idx)
                    prev_hp = settings.ENABLE_HEADING_PATH
                    try:
                        settings.ENABLE_HEADING_PATH = hp_flag
                        q_idx.index_chunks(all_chunks)
                        b_idx.build_and_save(all_chunks)
                    finally:
                        settings.ENABLE_HEADING_PATH = prev_hp
                    pipelines[hp_flag] = BaselineRAGPipeline(
                        qdrant_indexer=q_idx,
                        bm25_indexer=b_idx,
                        reranker=reranker,  # type: ignore[arg-type]
                        llm=llm,
                    )

                config_results: list[dict[str, Any]] = []
                baseline_a0_ci: dict[str, dict[str, Any]] | None = None
                interrupted_by_spend_guard = False

                for spec in specs_to_run:
                    ckpt_path = cache_dir / f"ablation_{active_profile}_{spec.name}.jsonl"
                    if not resume and ckpt_path.exists():
                        ckpt_path.unlink()

                    completed_map = (
                        load_checkpoint_rows(ckpt_path, active_profile, active_model)
                        if resume
                        else {}
                    )
                    rows_for_spec: list[dict[str, Any]] = []
                    pipeline = pipelines[spec.enable_heading_path]

                    with apply_ablation_config(spec, allow_rbac_off=include_rbac_off):
                        for item in questions:
                            if item.id in completed_map:
                                rows_for_spec.append(completed_map[item.id])
                                continue
                            try:
                                row = evaluate_single_question(
                                    item=item,
                                    pipeline=pipeline,
                                    chunk_lookup=chunk_lookup,
                                    run_judge=run_judge,
                                )
                            except SpendGuardExceededError as exc:
                                print(f"[SPEND GUARD] {exc} — stopping cleanly; use --resume to continue.")
                                interrupted_by_spend_guard = True
                                break
                            append_checkpoint_row(ckpt_path, row)
                            rows_for_spec.append(row)

                    ensure_same_profile(rows_for_spec, active_profile, active_model)
                    agg = aggregate_ablation_rows(
                        spec=spec,
                        rows=rows_for_spec,
                        baseline_ci=baseline_a0_ci,
                    )
                    if spec.name == "A0_baseline":
                        baseline_a0_ci = agg["ci_95"]
                    config_results.append(agg)

                    if interrupted_by_spend_guard:
                        break
            finally:
                for q_idx in qdrant_clients:
                    q_idx.close()

        now_utc = datetime.now(timezone.utc)
        harness_banner = (
            "HARNESS CHECK ONLY (mock profile — deterministic offline responses)"
            if active_profile == "mock"
            else f"LIVE EVALUATION ({active_profile} profile)"
        )
        payload = {
            "timestamp_utc": now_utc.isoformat(),
            "date": now_utc.strftime("%Y-%m-%d"),
            "llm_profile": active_profile,
            "llm_model": active_model,
            "temperature": 0.0,
            "harness_mode_banner": harness_banner,
            "judge_enabled": run_judge,
            "interrupted_by_spend_guard": interrupted_by_spend_guard,
            "gold_set_path": "data/eval/gold_set.jsonl",
            "gold_set_status_note": (
                "unreviewed_draft"
                if any(q.status == "draft" for q in questions)
                else "reviewed"
            ),
            "questions_evaluated": len(questions),
            "corpus": {
                "documents_count": doc_count,
                "chunks_count": len(all_chunks),
                "embedding_model": settings.EMBEDDING_MODEL_NAME,
                "reranker_model": "mock_reranker" if mock_reranker else settings.RERANKER_MODEL_NAME,
            },
            "configurations": config_results,
        }

        out_dir.mkdir(parents=True, exist_ok=True)
        ts_slug = now_utc.strftime("%Y%m%d_%H%M%S")
        paths = [
            out_dir / f"ablation_{active_profile}_{ts_slug}.json",
            out_dir / f"ablation_{active_profile}_latest.json",
            out_dir / "ablation_latest.json",
        ]
        for p in paths:
            with open(p, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)

        return payload
    finally:
        settings.LLM_PROFILE = original_profile
        settings.LLM_TEMPERATURE = original_temp


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 7 ablation matrix.")
    parser.add_argument(
        "--profile",
        choices=["mock", "dev", "demo"],
        default=settings.LLM_PROFILE,
        help="LLM profile to run (default: active LLM_PROFILE).",
    )
    parser.add_argument(
        "--gold-set",
        type=str,
        default="data/eval/gold_set.jsonl",
        help="Path to gold_set.jsonl.",
    )
    parser.add_argument(
        "--configs",
        type=str,
        default=",".join(DEFAULT_CONFIG_NAMES),
        help="Comma-separated configuration names to evaluate.",
    )
    parser.add_argument(
        "--include-rbac-off",
        action="store_true",
        help="Include RBAC_OFF_DEMO row (sets BASELINE_ABLATION=True for that row only).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on number of questions to evaluate (balanced across types).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from per-question checkpoint JSONL files in evaluation/cache/.",
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="Enable optional RAGAS-style LLM judge for faithfulness and context precision.",
    )
    parser.add_argument(
        "--mock-reranker",
        action="store_true",
        help="Use deterministic MockCrossEncoderReranker instead of CPU cross-encoder.",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default="evaluation/results",
        help="Output directory for ablation JSON artifacts.",
    )
    args = parser.parse_args()

    questions = load_gold_set(args.gold_set)
    selected = _select_questions(questions, args.limit)
    config_names = [c.strip() for c in args.configs.split(",") if c.strip()]

    payload = run_ablation_suite(
        profile=args.profile,
        questions=selected,
        config_names=config_names,
        include_rbac_off=args.include_rbac_off,
        resume=args.resume,
        run_judge=args.judge,
        mock_reranker=args.mock_reranker,
        out_dir=Path(args.out_dir),
    )

    print("========================================================================================")
    print(f"ABLATION RUN SUMMARY | Profile: {payload['llm_profile']} ({payload['llm_model']})")
    print(f"Mode Banner: {payload['harness_mode_banner']}")
    print(f"Questions per config: {payload['questions_evaluated']} ({payload['gold_set_status_note']})")
    print("========================================================================================")
    header = (
        f"{'Config':<16} {'Rec@5':>7} {'nDCG@5':>7} {'AnsF1':>7} "
        f"{'CitVal':>7} {'CRR':>7} {'Leak':>7} {'Route':>7} {'MedMs':>7} {'Calls':>6}"
    )
    print(header)
    print("-" * len(header))
    for cfg in payload["configurations"]:
        m = cfg["metrics"]
        tag = " [DEMO ONLY]" if cfg.get("is_demonstration_only") else ""
        print(
            f"{cfg['config_name']:<16} "
            f"{m['recall@5']:>7.4f} "
            f"{m['ndcg@5']:>7.4f} "
            f"{m['answer_correctness']:>7.4f} "
            f"{m['citation_validity_rate']:>7.4f} "
            f"{m['correct_refusal_rate']:>7.4f} "
            f"{m['leakage_rate']:>7.4f} "
            f"{m['routing_accuracy']:>7.4f} "
            f"{m['latency_median_ms']:>7.1f} "
            f"{m['llm_calls_per_query']:>6.2f}{tag}"
        )
        if cfg.get("warning_banner"):
            print(f"  *** {cfg['warning_banner']} ***")
    print("========================================================================================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

