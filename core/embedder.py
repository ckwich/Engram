"""
core/embedder.py — Sentence-transformers wrapper for Engram.

The model MUST be loaded eagerly at server startup via embedder._load() before any
MCP calls arrive. The sync embed/embed_batch methods assert the model is loaded rather
than lazy-loading — this prevents thread-blocking _load() calls inside the executor
where asyncio.wait_for() cannot interrupt them.

Provides both sync (embed, embed_batch) and async (embed_async, embed_batch_async)
interfaces. The async versions run encoding in a thread pool executor so they don't
block the event loop — critical for MCP server responsiveness on large memories.
"""
from __future__ import annotations
import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Union


MODEL_NAME = "all-MiniLM-L6-v2"

_executor = ThreadPoolExecutor(max_workers=1)


class Embedder:
    def __init__(self):
        self._model = None

    def _load(self):
        if self._model is None:
            print(f"[Engram] Loading embedding model '{MODEL_NAME}'... (first run only)", file=sys.stderr)
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(MODEL_NAME)
            print(f"[Engram] Model loaded.", file=sys.stderr)

    def embed(self, text: str) -> list[float]:
        """Embed a single string. Returns a list of floats."""
        assert self._model is not None, "Model not loaded — call _load() at startup before embedding"
        return self._model.encode(text, convert_to_numpy=True).tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of strings. Processes in chunks of 8 to avoid CPU hangs."""
        assert self._model is not None, "Model not loaded — call _load() at startup before embedding"
        BATCH_SIZE = 8
        results = []
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i:i + BATCH_SIZE]
            results.extend(self._model.encode(batch, convert_to_numpy=True).tolist())
        return results

    async def embed_async(self, text: str) -> list[float]:
        """Async embed a single string. Runs in thread pool to avoid blocking the event loop."""
        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(_executor, self.embed, text),
                timeout=60.0
            )
        except asyncio.TimeoutError:
            raise RuntimeError("Embedding timed out after 60s.")

    async def embed_batch_async(self, texts: list[str]) -> list[list[float]]:
        """Async embed a batch. Runs in thread pool to avoid blocking the event loop."""
        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(_executor, self.embed_batch, texts),
                timeout=60.0
            )
        except asyncio.TimeoutError:
            raise RuntimeError(
                "Embedding timed out after 60s. Memory may be too large or the model is hung. "
                "Try splitting into smaller memories under 5,000 chars each."
            )


# Singleton
embedder = Embedder()
