"""Generate Markdown and CSV report tables from Phase 7 ablation result files.

Writes:
- ``results/ablation_table.md`` and ``results/ablation_table.csv``
- ``evaluation/results/ablation_table.md`` and ``evaluation/results/ablation_table.csv``
- Optional bar chart in ``results/ablation_chart.png`` if ``matplotlib`` is installed.

Enforces ``ProfileMismatchError`` if multiple input result files come from
different ``llm_profile`` or ``llm_model`` settings, and prominently marks
``mock`` numbers as ``HARNESS CHECK ONLY`` and ``RBAC_OFF_DEMO`` as
``DEMONSTRATION ONLY — DO NOT USE AS RESULT``.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.ablation import DEMO_ONLY_BANNER, ProfileMismatchError


def load_and_validate_ablation_files(paths: list[Path]) -> dict[str, Any]:
    """Load one or more ablation JSON artifacts and verify identical profile/model."""
    if not paths:
        raise FileNotFoundError("No ablation result files provided.")

    loaded: list[dict[str, Any]] = []
    for p in paths:
        if not p.exists():
            raise FileNotFoundError(f"Ablation result file not found: {p}")
        with open(p, "r", encoding="utf-8") as handle:
            loaded.append(json.load(handle))

    expected_profile = str(loaded[0].get("llm_profile", ""))
    expected_model = str(loaded[0].get("llm_model", ""))

    merged_configs: dict[str, dict[str, Any]] = {}
    for payload in loaded:
        prof = str(payload.get("llm_profile", ""))
        mod = str(payload.get("llm_model", ""))
        if prof != expected_profile or mod != expected_model:
            raise ProfileMismatchError(
                f"Cannot combine ablation results across different profiles/models: "
                f"'{expected_profile}/{expected_model}' vs '{prof}/{mod}'."
            )
        for cfg in payload.get("configurations", []):
            merged_configs[str(cfg["config_name"])] = cfg

    base = dict(loaded[-1])
    base["configurations"] = list(merged_configs.values())
    return base


def _fmt_ci(ci_dict: dict[str, Any] | None) -> str:
    if not ci_dict:
        return "-"
    return f"[{ci_dict.get('ci_low', 0.0):.3f}, {ci_dict.get('ci_high', 0.0):.3f}]"


def generate_markdown_table(payload: dict[str, Any]) -> str:
    """Format the ablation result payload as a dissertation-ready Markdown report."""
    profile = str(payload.get("llm_profile", "unknown"))
    model = str(payload.get("llm_model", "unknown"))
    banner = str(payload.get("harness_mode_banner", ""))
    date_str = str(payload.get("date", ""))
    q_count = int(payload.get("questions_evaluated", 0))
    status_note = str(payload.get("gold_set_status_note", "unreviewed_draft"))
    corpus = payload.get("corpus", {})

    lines: list[str] = [
        "# Phase 7 Ablation Evaluation Report",
        "",
        f"- **Execution Mode:** `{banner}`",
        f"- **LLM Profile / Model:** `{profile}` (`{model}`)",
        f"- **Gold Set Status:** `{status_note}` ($n = {q_count}$ questions)",
        f"- **Corpus:** {corpus.get('documents_count', 0)} documents, {corpus.get('chunks_count', 0)} chunks, "
        f"embeddings `{corpus.get('embedding_model', '')}`, re-ranker `{corpus.get('reranker_model', '')}`",
        f"- **Date:** `{date_str}`",
        "",
    ]

    if profile == "mock":
        lines.extend(
            [
                "> **IMPORTANT NOTE (HARNESS CHECK ONLY):** All numbers in this table were generated "
                "under `LLM_PROFILE=mock` using deterministic offline responses (`0` live API quota spent). "
                "They verify end-to-end pipeline wiring, RBAC isolation, routing, grading, and citation "
                "validation, and must **not** be cited as live LLM quality benchmarks.",
                "",
            ]
        )

    lines.extend(
        [
            "## 1. Main Ablation Matrix",
            "",
            "| Config | Mode / Status | $n$ | Recall@1 | Recall@3 | Recall@5 (95% CI) | MRR | nDCG@5 (95% CI) | Answer F1 | Cit. Validity | Cit. Support | CRR (Refusal) | FRR | Leakage Rate | Route Acc. | Latency Med / p95 (ms) | Calls / Query | Tokens / Query |",
            "| :--- | :--- | ---: | ---: | ---: | :--- | ---: | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- | ---: | ---: |",
        ]
    )

    for cfg in payload.get("configurations", []):
        m = cfg["metrics"]
        ci = cfg.get("ci_95", {})
        mode_tag = (
            f"DEMO ONLY ({DEMO_ONLY_BANNER})"
            if cfg.get("is_demonstration_only")
            else ("HARNESS CHECK (mock)" if profile == "mock" else f"LIVE ({profile})")
        )
        rec5_str = f"{m['recall@5']:.4f} {_fmt_ci(ci.get('recall@5'))}"
        ndcg5_str = f"{m['ndcg@5']:.4f} {_fmt_ci(ci.get('ndcg@5'))}"
        lat_str = f"{m['latency_median_ms']:.1f} / {m['latency_p95_ms']:.1f}"

        lines.append(
            f"| `{cfg['config_name']}` | {mode_tag} | {cfg['n_total']} | "
            f"{m['recall@1']:.4f} | {m['recall@3']:.4f} | {rec5_str} | "
            f"{m['mrr']:.4f} | {ndcg5_str} | {m['answer_correctness']:.4f} | "
            f"{m['citation_validity_rate']:.4f} | {m['citation_support_rate']:.4f} | "
            f"{m['correct_refusal_rate']:.4f} | {m['false_refusal_rate']:.4f} | "
            f"{m['leakage_rate']:.4f} | {m['routing_accuracy']:.4f} | "
            f"{lat_str} | {m['llm_calls_per_query']:.2f} | {m['tokens_per_query']:.1f} |"
        )

    lines.extend(
        [
            "",
            "## 2. Bootstrap 95% Confidence Interval Overlap vs `A0_baseline`",
            "",
            "When two configurations' 95% bootstrap confidence intervals overlap (`Overlaps A0 = True`), "
            "no statistically significant improvement is claimed.",
            "",
            "| Config | Recall@5 Overlaps A0 | nDCG@5 Overlaps A0 | Answer F1 Overlaps A0 | CRR Overlaps A0 | Route Acc. Overlaps A0 | Leakage Overlaps A0 |",
            "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |",
        ]
    )

    for cfg in payload.get("configurations", []):
        if cfg["config_name"] == "A0_baseline":
            continue
        vs = cfg.get("vs_baseline_A0", {})

        def _ov(key: str) -> str:
            entry = vs.get(key)
            if not entry:
                return "-"
            return "Yes (ns)" if entry.get("ci_overlaps_baseline") else "**No (sig.)**"

        lines.append(
            f"| `{cfg['config_name']}` | {_ov('recall@5')} | {_ov('ndcg@5')} | "
            f"{_ov('answer_correctness')} | {_ov('correct_refusal_rate')} | "
            f"{_ov('routing_accuracy')} | {_ov('leakage_rate')} |"
        )

    lines.append("")
    return "\n".join(lines)


def write_csv_table(payload: dict[str, Any], csv_path: Path) -> None:
    """Write the flat CSV version of the ablation matrix."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    profile = str(payload.get("llm_profile", "unknown"))
    model = str(payload.get("llm_model", "unknown"))
    status_note = str(payload.get("gold_set_status_note", "unreviewed_draft"))

    fieldnames = [
        "config_name",
        "llm_profile",
        "llm_model",
        "run_type",
        "gold_set_status",
        "is_demonstration_only",
        "warning_banner",
        "n_total",
        "n_answerable",
        "n_refusal",
        "recall@1",
        "recall@3",
        "recall@5",
        "recall@5_ci_low",
        "recall@5_ci_high",
        "mrr",
        "ndcg@5",
        "ndcg@5_ci_low",
        "ndcg@5_ci_high",
        "answer_correctness",
        "faithfulness",
        "context_precision",
        "citation_validity_rate",
        "citation_support_rate",
        "correct_refusal_rate",
        "false_refusal_rate",
        "leakage_rate",
        "routing_accuracy",
        "latency_median_ms",
        "latency_p95_ms",
        "llm_calls_per_query",
        "tokens_per_query",
    ]

    with open(csv_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for cfg in payload.get("configurations", []):
            m = cfg["metrics"]
            ci = cfg.get("ci_95", {})
            rec5_ci = ci.get("recall@5", {})
            ndcg5_ci = ci.get("ndcg@5", {})
            run_type = "HARNESS_CHECK_ONLY" if profile == "mock" else f"LIVE_{profile.upper()}"
            writer.writerow(
                {
                    "config_name": cfg["config_name"],
                    "llm_profile": profile,
                    "llm_model": model,
                    "run_type": run_type,
                    "gold_set_status": status_note,
                    "is_demonstration_only": cfg.get("is_demonstration_only", False),
                    "warning_banner": cfg.get("warning_banner", ""),
                    "n_total": cfg["n_total"],
                    "n_answerable": cfg["n_answerable"],
                    "n_refusal": cfg["n_refusal"],
                    "recall@1": m["recall@1"],
                    "recall@3": m["recall@3"],
                    "recall@5": m["recall@5"],
                    "recall@5_ci_low": rec5_ci.get("ci_low", 0.0),
                    "recall@5_ci_high": rec5_ci.get("ci_high", 0.0),
                    "mrr": m["mrr"],
                    "ndcg@5": m["ndcg@5"],
                    "ndcg@5_ci_low": ndcg5_ci.get("ci_low", 0.0),
                    "ndcg@5_ci_high": ndcg5_ci.get("ci_high", 0.0),
                    "answer_correctness": m["answer_correctness"],
                    "faithfulness": m["faithfulness"] if m["faithfulness"] is not None else "",
                    "context_precision": (
                        m["context_precision"] if m["context_precision"] is not None else ""
                    ),
                    "citation_validity_rate": m["citation_validity_rate"],
                    "citation_support_rate": m["citation_support_rate"],
                    "correct_refusal_rate": m["correct_refusal_rate"],
                    "false_refusal_rate": m["false_refusal_rate"],
                    "leakage_rate": m["leakage_rate"],
                    "routing_accuracy": m["routing_accuracy"],
                    "latency_median_ms": m["latency_median_ms"],
                    "latency_p95_ms": m["latency_p95_ms"],
                    "llm_calls_per_query": m["llm_calls_per_query"],
                    "tokens_per_query": m["tokens_per_query"],
                }
            )


def maybe_write_chart(payload: dict[str, Any], chart_path: Path) -> bool:
    """Write a simple summary bar chart if matplotlib is installed."""
    try:
        import matplotlib.pyplot as plt  # type: ignore[import-not-found]
    except ImportError:
        return False

    configs = [c["config_name"] for c in payload.get("configurations", [])]
    rec5 = [float(c["metrics"]["recall@5"]) for c in payload.get("configurations", [])]
    crr = [float(c["metrics"]["correct_refusal_rate"]) for c in payload.get("configurations", [])]
    leak = [float(c["metrics"]["leakage_rate"]) for c in payload.get("configurations", [])]

    fig, ax = plt.subplots(figsize=(10, 5))
    x = range(len(configs))
    width = 0.25
    ax.bar([i - width for i in x], rec5, width=width, label="Recall@5")
    ax.bar(list(x), crr, width=width, label="Correct Refusal Rate")
    ax.bar([i + width for i in x], leak, width=width, label="Leakage Rate")
    ax.set_xticks(list(x))
    ax.set_xticklabels(configs, rotation=25, ha="right")
    ax.set_ylim(0.0, 1.05)
    ax.set_title(f"Ablation Summary ({payload.get('llm_profile', '')} profile)")
    ax.legend()
    fig.tight_layout()
    chart_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(chart_path, dpi=150)
    plt.close(fig)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Markdown and CSV ablation tables.")
    parser.add_argument(
        "--input",
        nargs="+",
        default=["evaluation/results/ablation_latest.json"],
        help="One or more ablation JSON result files to render.",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default="results",
        help="Primary output directory (default: results).",
    )
    args = parser.parse_args()

    input_paths = [Path(p) for p in args.input]
    payload = load_and_validate_ablation_files(input_paths)

    md_text = generate_markdown_table(payload)
    primary_dir = Path(args.out_dir)
    secondary_dir = Path("evaluation/results")

    for target_dir in (primary_dir, secondary_dir):
        target_dir.mkdir(parents=True, exist_ok=True)
        md_file = target_dir / "ablation_table.md"
        csv_file = target_dir / "ablation_table.csv"
        md_file.write_text(md_text, encoding="utf-8")
        write_csv_table(payload, csv_file)

    chart_written = maybe_write_chart(payload, primary_dir / "ablation_chart.png")
    print(f"[REPORT] Wrote {primary_dir / 'ablation_table.md'} and {primary_dir / 'ablation_table.csv'}")
    print(f"[REPORT] Wrote {secondary_dir / 'ablation_table.md'} and {secondary_dir / 'ablation_table.csv'}")
    if chart_written:
        print(f"[REPORT] Wrote chart {primary_dir / 'ablation_chart.png'}")
    else:
        print("[REPORT] matplotlib not installed; skipped optional PNG chart.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

