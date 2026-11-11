"""Idempotent vector and BM25 indexers for regulatory document chunks."""

import atexit
import logging
import pickle
import re
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Plus

from src.config import settings
from src.core.security import chunk_visible_to_role, get_role_filter, normalize_role
from src.ingestion.chunker import DocumentChunk
from src.ingestion.embeddings import EmbeddingGenerator, embeddings

logger = logging.getLogger(__name__)
COLLECTION_NAME = "compliance_chunks"


@dataclass(frozen=True)
class SearchResult:
    """Hits returned by one index plus role-filter counters for the audit log.

    ``considered`` is the number of candidates the index examined and
    ``filtered`` the number dropped by the role rule in this index. Qdrant
    applies the role filter natively before scoring, so nothing is dropped
    afterwards and its ``filtered`` value is always zero.
    """

    hits: list[dict[str, Any]] = field(default_factory=list)
    considered: int = 0
    filtered: int = 0



def tokenize_for_bm25(text: str) -> list[str]:
    """Simple lowercase punctuation-stripped tokenizer for BM25."""
    return re.findall(r"\b[a-zA-Z0-9_\-.]{2,}\b", text.lower())


def _close_qdrant_quietly(client: Any) -> None:
    """Close an embedded Qdrant client without raising during teardown."""
    try:
        client.close()
    except Exception as exc:  # pragma: no cover - interpreter shutdown path
        logger.debug("Qdrant client close failed (%s).", type(exc).__name__)



class QdrantIndexer:
    """Manage dense vector storage in local embedded Qdrant."""

    def __init__(
        self,
        storage_path: str | None = None,
        embedder: EmbeddingGenerator | None = None,
    ) -> None:
        self.storage_path = storage_path or settings.QDRANT_STORAGE_PATH
        self.embedder = embedder or embeddings
        self._client = None
        self._atexit_registered = False

    def __enter__(self) -> "QdrantIndexer":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _get_client(self):
        if self._client is None:
            from qdrant_client import QdrantClient

            Path(self.storage_path).mkdir(parents=True, exist_ok=True)
            self._client = QdrantClient(path=self.storage_path)
            if not self._atexit_registered:
                # Safety net for scripts and tests that forget an explicit close.
                atexit.register(_close_qdrant_quietly, self._client)
                self._atexit_registered = True
        return self._client

    def close(self) -> None:
        """Release the embedded Qdrant file lock."""
        if self._client is not None:
            client, self._client = self._client, None
            _close_qdrant_quietly(client)


    def ensure_collection(self, vector_dim: int = 384) -> None:
        """Create the collection if it does not exist."""
        from qdrant_client.http import models

        client = self._get_client()
        if not any(c.name == COLLECTION_NAME for c in client.get_collections().collections):
            logger.info("Creating Qdrant collection '%s' (dim=%s, cosine).", COLLECTION_NAME, vector_dim)
            client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=models.VectorParams(
                    size=vector_dim,
                    distance=models.Distance.COSINE,
                ),
            )

    def reset(self) -> None:
        """Delete the collection so ``--rebuild`` starts from a clean index.

        Embedded Qdrant can retain old segments after ``delete_collection`` on
        Windows, so the local storage directory is removed while the client is
        closed. This method is only used by an explicit ``--rebuild``.
        """
        self.close()
        storage = Path(self.storage_path)
        if storage.exists():
            shutil.rmtree(storage)
            logger.info("Removed local Qdrant storage at '%s'.", storage)
        storage.mkdir(parents=True, exist_ok=True)

    def count(self) -> int:
        """Return the number of indexed points, or 0 if no collection exists."""
        client = self._get_client()
        try:
            if not any(c.name == COLLECTION_NAME for c in client.get_collections().collections):
                return 0
            return int(client.count(collection_name=COLLECTION_NAME, exact=True).count)
        except Exception:
            return 0

    def index_chunks(self, chunks: list[DocumentChunk]) -> int:
        """Idempotently upsert chunks using deterministic UUIDv5 point IDs."""
        if not chunks:
            return 0

        from qdrant_client.http import models

        client = self._get_client()
        texts = [chunk.text_content for chunk in chunks]
        vectors = self.embedder.embed_texts(texts)
        self.ensure_collection(vector_dim=len(vectors[0]))

        points: list[models.PointStruct] = []
        for chunk, vector in zip(chunks, vectors):
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, chunk.chunk_id))
            payload = {
                "chunk_id": chunk.chunk_id,
                "doc_id": chunk.doc_id,
                "doc_title": chunk.doc_title,
                "section_label": chunk.section_label,
                "clause_label": chunk.clause_label,
                "page": chunk.page,
                "source_path": chunk.source_path,
                "allowed_roles": chunk.allowed_roles,
                "text_content": chunk.text_content,
                "token_count": chunk.token_count,
            }
            points.append(models.PointStruct(id=point_id, vector=vector, payload=payload))

        # Upsert in modest batches so local embedded mode stays responsive.
        batch_size = 64
        for start in range(0, len(points), batch_size):
            client.upsert(
                collection_name=COLLECTION_NAME,
                points=points[start : start + batch_size],
                wait=True,
            )
        return len(points)

    def search(self, query: str, top_k: int, role: str | None) -> SearchResult:
        """Dense similarity search restricted to the caller's role.

        The role filter is passed to Qdrant as a native payload filter, so
        restricted vectors are excluded before distance scoring and their
        payloads are never loaded. ``role=None`` is only valid for a labelled
        baseline ablation and must never be passed by an authenticated route.

        Args:
            query: User query text.
            top_k: Maximum number of hits.
            role: Authenticated user role.

        Raises:
            InvalidRoleError: if a non-None role is not in the frozen role model.
        """
        role_filter = get_role_filter(role) if role is not None else None
        client = self._get_client()
        try:
            if not any(c.name == COLLECTION_NAME for c in client.get_collections().collections):
                return SearchResult()
            query_vector = self.embedder.embed_query(query)
            response = client.query_points(
                collection_name=COLLECTION_NAME,
                query=query_vector,
                query_filter=role_filter,
                limit=top_k,
                with_payload=True,
            )
            results = response.points
        except Exception as exc:
            logger.warning("Vector search unavailable (%s); returning no vector hits.", type(exc).__name__)
            return SearchResult()

        hits: list[dict[str, Any]] = []
        for result in results:
            payload = result.payload or {}
            hits.append(
                {
                    "chunk_id": payload.get("chunk_id"),
                    "doc_id": payload.get("doc_id"),
                    "doc_title": payload.get("doc_title"),
                    "section_label": payload.get("section_label"),
                    "clause_label": payload.get("clause_label"),
                    "page": payload.get("page"),
                    "source_path": payload.get("source_path"),
                    "allowed_roles": payload.get("allowed_roles", []),
                    "text_content": payload.get("text_content", ""),
                    "score": float(result.score),
                }
            )
        return SearchResult(hits=hits, considered=len(hits), filtered=0)



class BM25Indexer:
    """Manage a lexical BM25 index persisted to disk."""

    def __init__(self, index_path: str | None = None) -> None:
        self.index_path = Path(index_path or settings.BM25_INDEX_PATH)
        self.bm25: BM25Plus | None = None
        self.chunks: list[dict[str, Any]] = []

    def build_and_save(self, chunks: list[DocumentChunk]) -> int:
        """Fit BM25 over all chunks and atomically replace the persisted index."""
        tokenized_corpus = [tokenize_for_bm25(chunk.text_content) for chunk in chunks]
        if not tokenized_corpus:
            self.bm25 = None
            self.chunks = []
        else:
            # BM25Plus avoids zero-IDF collapse on tiny fixture corpora.
            self.bm25 = BM25Plus(tokenized_corpus)
            self.chunks = [
                {
                    "chunk_id": chunk.chunk_id,
                    "doc_id": chunk.doc_id,
                    "doc_title": chunk.doc_title,
                    "section_label": chunk.section_label,
                    "clause_label": chunk.clause_label,
                    "page": chunk.page,
                    "source_path": chunk.source_path,
                    "allowed_roles": chunk.allowed_roles,
                    "text_content": chunk.text_content,
                    "token_count": chunk.token_count,
                }
                for chunk in chunks
            ]

        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.index_path.with_suffix(self.index_path.suffix + ".tmp")
        with open(temp_path, "wb") as handle:
            pickle.dump({"bm25": self.bm25, "chunks": self.chunks}, handle)
        temp_path.replace(self.index_path)
        return len(self.chunks)

    def load(self) -> bool:
        """Load the persisted index, returning False when it is absent."""
        if not self.index_path.exists():
            return False
        try:
            with open(self.index_path, "rb") as handle:
                data = pickle.load(handle)
        except Exception as exc:
            logger.warning("Could not load BM25 index (%s).", type(exc).__name__)
            return False
        self.bm25 = data.get("bm25")
        self.chunks = data.get("chunks", [])
        return self.bm25 is not None

    def search(self, query: str, top_k: int, role: str | None) -> SearchResult:
        """Return the top-k positively scored chunks visible to ``role``.

        Role filtering happens on candidate metadata before fusion, so a
        restricted clause can never enter the RRF candidate set. ``role=None``
        is only valid for a labelled baseline ablation.

        Args:
            query: User query text.
            top_k: Maximum number of hits.
            role: Authenticated user role.

        Raises:
            InvalidRoleError: if a non-None role is not in the frozen role model.
        """
        if role is not None:
            normalize_role(role)
        if self.bm25 is None and not self.load():
            return SearchResult()

        tokenized_query = tokenize_for_bm25(query)
        if not tokenized_query:
            return SearchResult()

        scores = self.bm25.get_scores(tokenized_query)
        positive = [index for index in range(len(scores)) if float(scores[index]) > 0.0]
        if role is None:
            eligible = positive
        else:
            eligible = [
                index
                for index in positive
                if index < len(self.chunks) and chunk_visible_to_role(self.chunks[index], role)
            ]
        filtered = len(positive) - len(eligible)
        ranked = sorted(
            eligible,
            key=lambda index: (-float(scores[index]), index),
        )[:top_k]

        results: list[dict[str, Any]] = []
        for index in ranked:
            score = float(scores[index])
            if score <= 0.0:
                continue
            item = dict(self.chunks[index])
            item["score"] = score
            results.append(item)
        return SearchResult(hits=results, considered=len(positive), filtered=filtered)

