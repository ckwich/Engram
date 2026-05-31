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
import contextlib
import io
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor


MODEL_NAME = "all-MiniLM-L6-v2"
MODEL_NOT_LOADED_MESSAGE = "Model not loaded - call _load() at startup before embedding"

_executor = ThreadPoolExecutor(max_workers=4)


class Embedder:
    def __init__(self):
        self._model = None

    def _load(self):
        if self._model is None:
            print(f"[Engram] Loading embedding model '{MODEL_NAME}'...", file=sys.stderr)
            from sentence_transformers import SentenceTransformer

            # Try cached/local first to avoid network dependency on startup.
            # Falls back to download only on OSError (cache miss / first run).
            # Other errors (corrupt cache, permission denied) propagate immediately
            # so they're diagnosed rather than masked by a slow network fallback.
            try:
                self._model = _load_model_quietly(lambda: SentenceTransformer(MODEL_NAME, local_files_only=True))
            except OSError:
                print(f"[Engram] Model not cached, downloading from HuggingFace...", file=sys.stderr)
                self._model = _load_model_quietly(lambda: SentenceTransformer(MODEL_NAME))

            print(f"[Engram] Model loaded.", file=sys.stderr)

    def _require_model(self):
        if self._model is None:
            raise RuntimeError(MODEL_NOT_LOADED_MESSAGE)
        return self._model

    def embed(self, text: str) -> list[float]:
        """Embed a single string. Returns a list of floats."""
        model = self._require_model()
        return model.encode(text, convert_to_numpy=True).tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of strings. Processes in chunks of 8 to avoid CPU hangs."""
        model = self._require_model()
        BATCH_SIZE = 8
        results = []
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i:i + BATCH_SIZE]
            results.extend(model.encode(batch, convert_to_numpy=True).tolist())
        return results

    async def embed_async(self, text: str) -> list[float]:
        """Async embed a single string. Runs in thread pool to avoid blocking the event loop."""
        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(_executor, self.embed, text),
                timeout=60.0
            )
        except asyncio.TimeoutError:
            raise RuntimeError("Embedding timed out after 60s.")

    async def embed_batch_async(self, texts: list[str]) -> list[list[float]]:
        """Async embed a batch. Runs in thread pool to avoid blocking the event loop."""
        loop = asyncio.get_running_loop()
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


def _load_model_quietly(load_model):
    if os.environ.get("ENGRAM_EMBEDDER_VERBOSE") == "1":
        return load_model()
    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    try:
        with (
            _suppress_transformers_load_warnings(),
            contextlib.redirect_stdout(captured_stdout),
            contextlib.redirect_stderr(captured_stderr),
        ):
            return load_model()
    except Exception:
        stdout_text = captured_stdout.getvalue()
        stderr_text = captured_stderr.getvalue()
        if stdout_text:
            print(stdout_text, file=sys.stderr, end="")
        if stderr_text:
            print(stderr_text, file=sys.stderr, end="")
        raise


@contextlib.contextmanager
def _suppress_transformers_load_warnings():
    target_loggers = [
        logging.getLogger("transformers"),
        logging.getLogger("transformers.utils.loading_report"),
    ]
    previous_levels = [(logger, logger.level) for logger in target_loggers]
    transformers_logging = None
    previous_verbosity = None
    try:
        try:
            from transformers.utils import logging as imported_transformers_logging

            transformers_logging = imported_transformers_logging
            previous_verbosity = transformers_logging.get_verbosity()
            transformers_logging.set_verbosity_error()
        except Exception:
            transformers_logging = None
        for logger in target_loggers:
            logger.setLevel(logging.ERROR)
        yield
    finally:
        for logger, level in previous_levels:
            logger.setLevel(level)
        if transformers_logging is not None and previous_verbosity is not None:
            transformers_logging.set_verbosity(previous_verbosity)
