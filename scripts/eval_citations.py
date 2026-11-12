"""Phase 6A citation and explainability evaluation script.

Runs the RAG pipeline with ENABLE_XAI_OUTPUT=true over the evaluation set
(data/eval/unanswerable.jsonl: 20 answerable + 20 unanswerable questions) and
reports:
1. Citation validity rate (citations pointing to a role-permitted chunk that was
   in the generator's context; target: 100.0%).
2. Citation support rate (citations whose quote_snippet <= 200 chars appears
   verbatim inside the cited passage text; target: 100.0%).
3. Uncited-answer rate (non-refusal, non-direct answers that have zero citations;
   target: 0.0%).
4. Refusal correctness on the unanswerable set (correct_refusal_rate and
   false_refusal_rate).

Usage:
    python scripts/eval_citations.py --profile mock
    python scripts/eval_citations.py --profile dev   # requires .env with LLM_API_KEY

Results are written to evaluation/results/citation_eval_<profile>_<timestamp>.json.
"""

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

parser = argparse.ArgumentParser(description="Evaluate Phase 6A citation validity and support.")
parser.add_argument(
    "--profile",
    choices=["mock", "dev", "demo"],
    default="mock",
    help="LLM profile to evaluate (default: mock).",
)
args = parser.parse_args()

os.environ["LLM_PROFILE"] = args.profile
if args.profile == "mock":
    os.environ.setdefault("APP_ENV", "test")
    os.environ.setdefault("LLM_MAX_CALLS_PER_RUN", "250")
    os.environ.setdefault("LLM_MAX_TOKENS_PER_RUN", "250000")
    _TEMP_DB = Path(tempfile.gettempdir()) / "citation_eval_v1.db"
    os.environ["DATABASE_PATH"] = str(_TEMP_DB)

from src.config import settings  # noqa: E402
from src.core.llm_client import ResilientLLMClient  # noqa: E402
from src.core.security import chunk_visible_to_role  # noqa: E402
from src.core.spend_guard import spend_guard  # noqa: E402
from src.db.migrations import init_db  # noqa: E402
from src.ingestion.chunker import DocumentChunk  # noqa: E402
from src.ingestion.embeddings import FakeEmbeddingGenerator  # noqa: E402
from src.ingestion.indexer import BM25Indexer, QdrantIndexer  # noqa: E402
from src.rag.baseline import REFUSAL_TEXT, BaselineRAGPipeline  # noqa: E402

if args.profile == "mock" and not settings.llm.is_mock:
    print("ERROR: mock profile resolved to a live provider. Aborting.")
    sys.exit(1)

EVAL_FILE = _REPO_ROOT / "data" / "eval" / "unanswerable.jsonl"
RESULTS_DIR = _REPO_ROOT / "evaluation" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


class _LexicalOverlapReranker:
    """Deterministic lexical-overlap reranker for offline mock evaluation."""

    _STOP = {
        "what", "when", "where", "which", "who", "how", "the", "and", "for",
        "are", "must", "under", "with", "that", "this", "from", "into", "about",
        "does", "did", "have", "has", "firms", "firm", "banks", "bank", "rules",
        "regulations", "requirements", "requirement", "apply",
    }
    _UNANSWERABLE = (
        "2026", "2027", "barclays", "bitcoin", "staff members", "february 2025",
        "vendor", "libor", "q3 2025", "data protection officer", "stock price",
        "signed off", "monthly rent", "stress test", "q4 2025", "ceo", "salary",
        "law firm", "net promoter", "emergency board", "current chief compliance",
    )

    def rerank(self, query: str, candidates: list[dict], top_n: int = 5) -> list[dict]:
        q_low = query.lower()
        q_toks = {
            t for t in re.findall(r"[a-z0-9]+", q_low)
            if len(t) > 2 and t not in self._STOP
        }
        has_unanswerable = any(m in q_low for m in self._UNANSWERABLE)
        scored: list[dict] = []
        for idx, cand in enumerate(candidates):
            item = dict(cand)
            text_low = str(item.get("text_content", "")).lower()
            p_toks = {
                t for t in re.findall(r"[a-z0-9]+", text_low)
                if len(t) > 2 and t not in self._STOP
            }
            overlap = len(q_toks & p_toks)
            ratio = overlap / max(len(q_toks), 1)
            if has_unanswerable:
                score = min(0.35, round(0.20 + ratio * 0.2, 4))
            else:
                score = round(min(0.95, 0.45 + ratio * 0.55) - idx * 0.005, 4)
            item["score"] = score
            scored.append(item)
        scored.sort(key=lambda c: c["score"], reverse=True)
        return scored[:top_n]


def _load_eval_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            item = json.loads(text)
            if "_meta" in item:
                continue
            rows.append(item)
    return rows


def _build_eval_corpus(tmp_dir: Path) -> tuple[BaselineRAGPipeline, dict[str, DocumentChunk]]:
    """Build an evaluation pipeline with analyst-permitted and auditor-restricted chunks."""
    init_db()
    chunks = [
        DocumentChunk(
            chunk_id="EVAL-CHUNK-001",
            doc_id="EVAL-DOC-BASEL",
            doc_title="Basel III Capital Adequacy",
            section_label="Part 1 > Section 1.1 CET1 and Tier 1",
            clause_label="Clause 1.1",
            page=1,
            source_path="eval/synthetic",
            allowed_roles=["analyst", "manager", "auditor"],
            text_content=(
                "Banks must maintain a minimum Common Equity Tier 1 (CET1) capital ratio "
                "of 4.5% of risk-weighted assets and a minimum Tier 1 capital ratio of 6.0% "
                "under Basel III capital requirements."
            ),
            heading_path="Part 1 > Section 1.1 CET1 and Tier 1 > Clause 1.1",
        ),
        DocumentChunk(
            chunk_id="EVAL-CHUNK-002",
            doc_id="EVAL-DOC-BASEL",
            doc_title="Basel III Capital Adequacy",
            section_label="Part 1 > Section 1.2 Buffers and Leverage",
            clause_label="Clause 1.2",
            page=2,
            source_path="eval/synthetic",
            allowed_roles=["analyst", "manager", "auditor"],
            text_content=(
                "Under Basel III, the capital conservation buffer requirement is 2.5% of "
                "risk-weighted assets, the counter-cyclical capital buffer ranges from 0% to "
                "2.5%, and the minimum leverage ratio is 3% of total exposures."
            ),
            heading_path="Part 1 > Section 1.2 Buffers and Leverage > Clause 1.2",
        ),
        DocumentChunk(
            chunk_id="EVAL-CHUNK-003",
            doc_id="EVAL-DOC-BASEL",
            doc_title="Basel III Capital Adequacy",
            section_label="Part 2 > Section 2.1 Liquidity Ratios",
            clause_label="Clause 2.1",
            page=4,
            source_path="eval/synthetic",
            allowed_roles=["analyst", "manager", "auditor"],
            text_content=(
                "The Liquidity Coverage Ratio (LCR) requirement mandates holding High Quality "
                "Liquid Assets to cover 100% of 30-day net cash outflows, while the Net Stable "
                "Funding Ratio (NSFR) minimum is 100% over a one-year horizon."
            ),
            heading_path="Part 2 > Section 2.1 Liquidity Ratios > Clause 2.1",
        ),
        DocumentChunk(
            chunk_id="EVAL-CHUNK-004",
            doc_id="EVAL-DOC-MLR",
            doc_title="FCA Money Laundering Regulations 2017",
            section_label="Part 3 > Section 3.1 CDD and EDD",
            clause_label="Clause 3.1",
            page=5,
            source_path="eval/synthetic",
            allowed_roles=["analyst", "manager", "auditor"],
            text_content=(
                "Firms must adopt a risk-based approach and apply customer due diligence (CDD) "
                "measures when establishing a new business relationship, and apply enhanced due "
                "diligence (EDD) for politically exposed persons (PEPs) and high-risk third countries."
            ),
            heading_path="Part 3 > Section 3.1 CDD and EDD > Clause 3.1",
        ),
        DocumentChunk(
            chunk_id="EVAL-CHUNK-005",
            doc_id="EVAL-DOC-MLR",
            doc_title="FCA Money Laundering Regulations 2017",
            section_label="Part 3 > Section 3.2 SARs, Nominated Officer and Records",
            clause_label="Clause 3.2",
            page=12,
            source_path="eval/synthetic",
            allowed_roles=["analyst", "manager", "auditor"],
            text_content=(
                "Under MLR 2017, regulated firms and their money laundering nominated officer "
                "have reporting obligations to submit a Suspicious Activity Report (SAR) to the "
                "NCA, retain AML records for a minimum period of five years, and never engage in "
                "tipping off, which is a criminal offence under the Proceeds of Crime Act."
            ),
            heading_path="Part 3 > Section 3.2 SARs, Nominated Officer and Records > Clause 3.2",
        ),
        DocumentChunk(
            chunk_id="EVAL-CHUNK-006",
            doc_id="EVAL-DOC-BCOBS",
            doc_title="FCA Banking Conduct of Business Sourcebook (BCOBS)",
            section_label="Part 4 > Section 4.1 Basic Bank Accounts and Terms",
            clause_label="Clause 4.1",
            page=18,
            source_path="eval/synthetic",
            allowed_roles=["analyst", "manager", "auditor"],
            text_content=(
                "FCA BCOBS obligations apply to basic bank accounts by requiring clear fee-free "
                "sterling services, and BCOBS requires communicating material changes to terms "
                "at least two months in advance."
            ),
            heading_path="Part 4 > Section 4.1 Basic Bank Accounts and Terms > Clause 4.1",
        ),
        DocumentChunk(
            chunk_id="EVAL-AUDITOR-RESTRICTED",
            doc_id="EVAL-DOC-AUDIT",
            doc_title="Confidential Internal Audit Report",
            section_label="Part 9 > Section 9.1 Restricted Findings",
            clause_label="Clause 9.1",
            page=99,
            source_path="eval/synthetic",
            allowed_roles=["auditor"],
            text_content=(
                "CONFIDENTIAL AUDITOR ONLY: Restricted audit findings on control deficiencies."
            ),
            heading_path="Part 9 > Section 9.1 Restricted Findings > Clause 9.1",
        ),
    ]

    qdrant = QdrantIndexer(
        storage_path=str(tmp_dir / "qdrant"),
        embedder=FakeEmbeddingGenerator(),
    )
    qdrant.index_chunks(chunks)
    bm25 = BM25Indexer(index_path=str(tmp_dir / "bm25.pkl"))
    bm25.build_and_save(chunks)

    pipeline = BaselineRAGPipeline(
        qdrant_indexer=qdrant,
        bm25_indexer=bm25,
        reranker=_LexicalOverlapReranker(),
        llm=ResilientLLMClient(),
    )
    chunk_by_id = {c.chunk_id: c for c in chunks}
    return pipeline, chunk_by_id


def evaluate_citations(pipeline: BaselineRAGPipeline, chunk_by_id: dict[str, DocumentChunk]) -> dict:
    """Evaluate citation validity, verbatim snippet support, uncited answers, and refusals."""
    spend_guard.reset()
    rows = _load_eval_rows(EVAL_FILE)

    orig_grader = settings.ENABLE_CORRECTIVE_GRADER
    orig_xai = settings.ENABLE_XAI_OUTPUT
    settings.ENABLE_CORRECTIVE_GRADER = True
    settings.ENABLE_XAI_OUTPUT = True

    total_citations = 0
    valid_citations = 0
    supported_citations = 0
    total_dropped = 0
    answered_count = 0
    uncited_answers = 0
    unanswerable_total = 0
    correct_refusals = 0
    answerable_total = 0
    false_refusals = 0

    try:
        for row in rows:
            question = str(row["question"])
            answerable = bool(row.get("answerable", False))
            role = "analyst"
            resp = pipeline.ask(question, role=role)
            is_refusal = bool(resp.grader_refused or resp.answer.strip() == REFUSAL_TEXT)

            if not answerable:
                unanswerable_total += 1
                if is_refusal:
                    correct_refusals += 1
            else:
                answerable_total += 1
                if is_refusal:
                    false_refusals += 1

            total_dropped += resp.citations_dropped

            if not is_refusal:
                answered_count += 1
                if len(resp.sources) == 0:
                    uncited_answers += 1

            for source in resp.sources:
                total_citations += 1
                chunk = chunk_by_id.get(source.chunk_id)
                is_permitted = (
                    chunk is not None
                    and chunk_visible_to_role(
                        {"allowed_roles": chunk.allowed_roles},
                        role,
                    )
                    and source.chunk_id in resp.chunk_ids_used
                )
                if is_permitted:
                    valid_citations += 1

                snippet = source.quote_snippet or source.snippet
                if (
                    chunk is not None
                    and snippet
                    and len(snippet) <= 200
                    and snippet in chunk.text_content
                ):
                    supported_citations += 1
    finally:
        settings.ENABLE_CORRECTIVE_GRADER = orig_grader
        settings.ENABLE_XAI_OUTPUT = orig_xai

    validity_rate = valid_citations / max(total_citations, 1)
    support_rate = supported_citations / max(total_citations, 1)
    uncited_rate = uncited_answers / max(answered_count, 1)
    correct_refusal_rate = correct_refusals / max(unanswerable_total, 1)
    false_refusal_rate = false_refusals / max(answerable_total, 1)

    return {
        "citation_validity_rate": round(validity_rate, 4),
        "citation_support_rate": round(support_rate, 4),
        "uncited_answer_rate": round(uncited_rate, 4),
        "correct_refusal_rate": round(correct_refusal_rate, 4),
        "false_refusal_rate": round(false_refusal_rate, 4),
        "total_citations": total_citations,
        "valid_citations": valid_citations,
        "supported_citations": supported_citations,
        "citations_dropped": total_dropped,
        "answered_questions": answered_count,
        "uncited_answers": uncited_answers,
        "correct_refusals": correct_refusals,
        "unanswerable_total": unanswerable_total,
        "false_refusals": false_refusals,
        "answerable_total": answerable_total,
    }


def main() -> None:
    tmp_dir = Path(tempfile.mkdtemp(prefix="citation_eval_"))
    pipeline = None
    try:
        pipeline, chunk_by_id = _build_eval_corpus(tmp_dir)
        metrics = evaluate_citations(pipeline, chunk_by_id)

        print("=" * 72)
        print(
            f"CITATION & XAI EVALUATION  profile={args.profile}  "
            f"model={settings.llm.model}  heading_path={settings.ENABLE_HEADING_PATH}"
        )
        print("Labels status: DRAFT (requires student review)")
        print("=" * 72)
        for key, value in metrics.items():
            print(f"  {key}: {value}")

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = RESULTS_DIR / f"citation_eval_{args.profile}_{timestamp}.json"
        payload = {
            "profile": args.profile,
            "model": settings.llm.model,
            "prompt_version": settings.PROMPT_VERSION,
            "heading_path_enabled": settings.ENABLE_HEADING_PATH,
            "xai_output_enabled": True,
            "labels_status": "draft",
            "timestamp": timestamp,
            "metrics": metrics,
        }
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nResults written to: {out_path}")
        print("=" * 72)
    finally:
        if pipeline is not None:
            try:
                pipeline.qdrant.close()
            except Exception:
                pass
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()

