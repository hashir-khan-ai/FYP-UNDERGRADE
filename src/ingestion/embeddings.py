"""Local CPU embedding model loader and vector generator."""

import logging
from typing import Protocol
from src.config import settings

logger = logging.getLogger(__name__)


class EmbeddingGenerator(Protocol):
    """Protocol for embedding generators."""
    def embed_texts(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, query: str) -> list[float]: ...


class LocalCPUEmbeddings:
    """
    Lazy loader for SentenceTransformers embeddings running locally on CPU.
    Downloads the model once upon first invocation, never at module import time.
    """

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or settings.EMBEDDING_MODEL_NAME
        self._model = None

    def _get_model(self):
        if self._model is None:
            logger.info(f"Loading local embedding model '{self.model_name}' on CPU...")
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError:
                raise ImportError(
                    "sentence-transformers is required for local embeddings. "
                    "Ensure requirements.txt is installed."
                )
            self._model = SentenceTransformer(self.model_name, device="cpu")
        return self._model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate dense embeddings for a batch of chunk texts."""
        if not texts:
            return []
        model = self._get_model()
        vectors = model.encode(texts, batch_size=32, show_progress_bar=False, normalize_embeddings=True)
        return [v.tolist() for v in vectors]

    def embed_query(self, query: str) -> list[float]:
        """Generate dense embedding for a single user query."""
        model = self._get_model()
        vector = model.encode(query, show_progress_bar=False, normalize_embeddings=True)
        return vector.tolist()


class FakeEmbeddingGenerator:
    """Deterministic, zero-download fake embedder for ultra-fast unit testing."""

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(t) for t in texts]

    def embed_query(self, query: str) -> list[float]:
        # Generate deterministic floats based on query hash
        import hashlib
        seed = int(hashlib.md5(query.encode("utf-8")).hexdigest()[:8], 16)
        vec = [((seed + i) % 100) / 100.0 for i in range(self.dim)]
        # Normalize
        norm = sum(x * x for x in vec) ** 0.5 or 1.0
        return [x / norm for x in vec]


# Global lazy instance
embeddings = LocalCPUEmbeddings()

