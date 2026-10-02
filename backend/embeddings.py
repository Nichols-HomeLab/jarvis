from __future__ import annotations

import asyncio


class MemoryEmbedder:
    """Small CPU text model; the same model embeds notes and search queries."""
    def __init__(self, model: str, cache_dir: str):
        self.model_name = model
        self.cache_dir = cache_dir
        self._model = None
        self._lock = asyncio.Lock()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with self._lock:
            return await asyncio.to_thread(self._embed, texts)

    def _embed(self, texts):
        if self._model is None:
            from fastembed import TextEmbedding
            self._model = TextEmbedding(model_name=self.model_name, cache_dir=self.cache_dir, threads=2)
        return [vector.tolist() for vector in self._model.embed(texts)]
