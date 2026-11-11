"""Smoke demo: run 10 representative questions end to end.

Reports pass/fail, latency, token use and cache status for the chosen profile.
Live providers are only used when this script is invoked explicitly.
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings
from src.core.spend_guard import SpendGuardExceededError, spend_guard
from src.db.connection import get_db_connection
from src.db.migrations import init_db
from src.db.repository import Repository
from src.rag.baseline import REFUSAL_TEXT, baseline_pipeline

logging.basicConfig(level=logging.WARNING)

REPRESENTATIVE_QUESTIONS = [
    ("DEMO-01", "What is the core communication standard for retail banking customers under BCOBS?"),
    ("DEMO-02", "How must deposit interest rates be presented to retail customers according to BCOBS guidance?"),
    ("DEMO-03", "What is the advance notification timeline required when a deposit interest rate is reduced by 0.60%?"),
    ("DEMO-04", "What is the monetary threshold for occasional transactions requiring Customer Due Diligence under MLR 2017?"),
    ("DEMO-05", "What is the percentage threshold for identifying beneficial ownership in corporate entities?"),
    ("DEMO-06", "Under what circumstances must enhanced customer due diligence (EDD) be applied?"),
    ("DEMO-07", "What is the minimum Common Equity Tier 1 (CET1) capital ratio required under Basel III?"),
    ("DEMO-08", "What is the required percentage for the Basel III Capital Conservation Buffer?"),
    ("DEMO-09", "What identity documents are acceptable for retail applicant onboarding under internal SOP?"),
    ("DEMO-10", "What are the Japanese FSA regulations for retail mortgage lending in Tokyo?"),
]


def run_smoke_demo(profile: str | None = None) -> int:
    """Run the smoke suite and return the number of failed questions."""
    if profile:
        os.environ["LLM_PROFILE"] = profile
        settings.LLM_PROFILE = profile

    try:
        active = settings.llm
    except (ValueError, RuntimeError) as exc:
        print(f"ERROR: cannot resolve LLM profile '{settings.LLM_PROFILE}': {exc}")
        return len(REPRESENTATIVE_QUESTIONS)

    init_db()

    print("=" * 80)
    print(f"SMOKE DEMO: 10 Representative Questions (Profile: {active.profile})")
    print(f"Model: {active.model} | Embeddings: {settings.EMBEDDING_MODEL_NAME}")
    print("=" * 80)

    results: list[dict] = []
    total_tokens_start = spend_guard.tokens_count
    total_calls_start = spend_guard.calls_count
    total_time_start = time.perf_counter()

    for index, (question_id, query) in enumerate(REPRESENTATIVE_QUESTIONS, start=1):
        print(f"\n[{index}/10] Query ({question_id}): {query}")
        tokens_before = spend_guard.tokens_count
        question_start = time.perf_counter()
        try:
            response = baseline_pipeline.ask(query)
            elapsed_ms = (time.perf_counter() - question_start) * 1000.0
            tokens_used = spend_guard.tokens_count - tokens_before

            answered = len(response.answer.strip()) > 10
            refusal_ok = REFUSAL_TEXT.lower() in response.answer.lower()
            passed = answered and (bool(response.sources) or refusal_ok)
            status = "PASS" if passed else "FAIL"

            print(f"  Status   : {status}")
            print(
                f"  Latency  : {response.timings.total_ms:.1f} ms "
                f"(retrieval {response.timings.retrieval_ms:.1f}, "
                f"rerank {response.timings.rerank_ms:.1f}, "
                f"generation {response.timings.generation_ms:.1f})"
            )
            print(f"  Tokens   : {tokens_used} | Cached: {response.cached}")
            print(f"  Sources  : {len(response.sources)} | Cited: {', '.join(response.chunk_ids_used) or 'none'}")
            print(f"  Answer   : {response.answer[:180]}...")

            results.append(
                {
                    "id": question_id,
                    "passed": passed,
                    "latency_ms": response.timings.total_ms,
                    "tokens": tokens_used,
                    "cached": response.cached,
                    "sources": len(response.sources),
                }
            )
        except SpendGuardExceededError as exc:
            print(f"  Status   : STOPPED ({exc})")
            break
        except Exception as exc:
            print(f"  Status   : ERROR ({type(exc).__name__}: {exc})")
            results.append(
                {
                    "id": question_id,
                    "passed": False,
                    "latency_ms": (time.perf_counter() - question_start) * 1000.0,
                    "tokens": spend_guard.tokens_count - tokens_before,
                    "cached": False,
                    "sources": 0,
                }
            )

    total_wall_time = time.perf_counter() - total_time_start
    total_tokens = spend_guard.tokens_count - total_tokens_start
    total_calls = spend_guard.calls_count - total_calls_start
    passed_count = sum(1 for result in results if result["passed"])
    average_latency = (
        sum(result["latency_ms"] for result in results) / len(results) if results else 0.0
    )

    print("\n" + "=" * 80)
    print("SMOKE DEMO SUMMARY")
    print("=" * 80)
    print(f"Questions run  : {len(results)}/{len(REPRESENTATIVE_QUESTIONS)}")
    print(f"Passed         : {passed_count}/{len(results) if results else 0}")
    print(f"Average latency: {average_latency:.1f} ms")
    print(f"Wall time      : {total_wall_time:.2f} s")
    print(f"Tokens used    : {total_tokens}")
    print(f"LLM calls      : {total_calls}")
    print(f"Failed         : {len(results) - passed_count}")

    with get_db_connection() as conn:
        stats = Repository(conn).get_spend_totals()
        print(
            f"DB telemetry   : {stats['total_calls']} calls "
            f"(cache hits {stats['cache_hits']}, tokens {stats['total_tokens']})"
        )
    print("=" * 80 + "\n")
    baseline_pipeline.close()
    return len(results) - passed_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Run 10 representative smoke demo queries.")
    parser.add_argument(
        "--profile",
        default=None,
        choices=["mock", "dev", "demo"],
        help="Override the LLM profile for this run only",
    )
    args = parser.parse_args()
    failures = run_smoke_demo(profile=args.profile)
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
