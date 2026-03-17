"""
core/embedder.py — Sentence-transformers wrapper for Engram.
Lazy-loads the model on first use. Singleton instance used across the app.

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
        self._load()
        return self._model.encode(text, convert_to_numpy=True).tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of strings. Processes in chunks of 8 to avoid CPU hangs."""
        self._load()
        BATCH_SIZE = 8
        results = []
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i:i + BATCH_SIZE]
            results.extend(self._model.encode(batch, convert_to_numpy=True).tolist())
        return results

    async def embed_async(self, text: str) -> list[float]:
        """Async embed a single string. Runs in thread pool to avoid blocking the event loop."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, self.embed, text)

    async def embed_batch_async(self, texts: list[str]) -> list[list[float]]:
        """Async embed a batch. Runs in thread pool to avoid blocking the event loop."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, self.embed_batch, texts)


# Singleton
embedder = Embedder()
