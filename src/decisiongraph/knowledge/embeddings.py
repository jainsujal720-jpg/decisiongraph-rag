from collections.abc import Sequence
from typing import Protocol

from openai import OpenAI


class EmbeddingProvider(Protocol):
    dimensions: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class OpenAIEmbeddingProvider:
    """Thin, testable adapter around the OpenAI embeddings API."""

    def __init__(self, api_key: str, model: str, dimensions: int = 1536, batch_size: int = 128):
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for embedding and hybrid search")
        if batch_size <= 0:
            raise ValueError("Embedding batch size must be positive")
        self.dimensions = dimensions
        self.model = model
        self.batch_size = batch_size
        self.client = OpenAI(api_key=api_key)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            response = self.client.embeddings.create(
                model=self.model,
                input=list(texts[start : start + self.batch_size]),
                dimensions=self.dimensions,
            )
            vectors.extend(
                item.embedding for item in sorted(response.data, key=lambda item: item.index)
            )
        if any(len(vector) != self.dimensions for vector in vectors):
            raise ValueError("Embedding provider returned an unexpected vector dimension")
        return vectors
