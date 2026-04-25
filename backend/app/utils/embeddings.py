"""OpenAI embedding client with an in-memory LRU cache."""
from __future__ import annotations

import asyncio
import hashlib
import math
from collections import OrderedDict

from openai import AsyncOpenAI

from app.config import settings
from app.utils.logger import get_logger

log = get_logger(__name__)


class EmbeddingClient:
    """Async wrapper around OpenAI's embeddings API with caching and batching."""

    def __init__(self, model: str | None = None, cache_size: int = 10_000) -> None:
        self.model = model or settings.OPENAI_EMBEDDING_MODEL
        self.dim = settings.OPENAI_EMBEDDING_DIM
        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_size = cache_size
        self._lock = asyncio.Lock()

    @staticmethod
    def _key(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str) -> list[float] | None:
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def _cache_put(self, key: str, value: list[float]) -> None:
        self._cache[key] = value
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)

    async def embed(self, text: str) -> list[float]:
        """Return the embedding vector for a single string."""
        if not text:
            return [0.0] * self.dim
        key = self._key(text)
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        async with self._lock:
            cached = self._cache_get(key)
            if cached is not None:
                return cached
            try:
                resp = await self._client.embeddings.create(model=self.model, input=text)
                vec = resp.data[0].embedding
            except Exception as e:  # noqa: BLE001
                log.error("embedding_failed", error=str(e), text_len=len(text))
                raise
            self._cache_put(key, vec)
            return vec

    async def embed_batch(
        self, texts: list[str], batch_size: int = 100
    ) -> list[list[float]]:
        """Embed a list of texts in chunks of `batch_size`."""
        results: list[list[float] | None] = [None] * len(texts)
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        for i, t in enumerate(texts):
            cached = self._cache_get(self._key(t)) if t else None
            if cached is not None:
                results[i] = cached
            elif not t:
                results[i] = [0.0] * self.dim
            else:
                uncached_indices.append(i)
                uncached_texts.append(t)

        for start in range(0, len(uncached_texts), batch_size):
            batch = uncached_texts[start : start + batch_size]
            try:
                resp = await self._client.embeddings.create(model=self.model, input=batch)
            except Exception as e:  # noqa: BLE001
                log.error("embedding_batch_failed", error=str(e), batch_size=len(batch))
                raise
            for j, item in enumerate(resp.data):
                idx = uncached_indices[start + j]
                vec = item.embedding
                results[idx] = vec
                self._cache_put(self._key(batch[j]), vec)

        return [r if r is not None else [0.0] * self.dim for r in results]

    async def similarity(self, text1: str, text2: str) -> float:
        """Cosine similarity between two texts."""
        v1, v2 = await self.embed(text1), await self.embed(text2)
        return _cosine(v1, v2)


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


_singleton: EmbeddingClient | None = None


def get_embedding_client() -> EmbeddingClient:
    """Return a process-wide embedding client singleton."""
    global _singleton
    if _singleton is None:
        _singleton = EmbeddingClient()
    return _singleton
