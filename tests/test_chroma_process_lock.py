from __future__ import annotations

import asyncio
import threading
import time

import pytest

import core.memory_manager as mm_module


def test_chroma_process_lock_serializes_competing_workers(tmp_path, monkeypatch):
    lock_path = tmp_path / "chroma.lock"
    monkeypatch.setattr(mm_module, "CHROMA_PROCESS_LOCK_PATH", lock_path)
    monkeypatch.setattr(mm_module, "CHROMA_PROCESS_LOCK_TIMEOUT", 1.0)
    monkeypatch.setattr(mm_module, "CHROMA_PROCESS_LOCK_POLL_SECONDS", 0.01)
    monkeypatch.setattr(mm_module, "CHROMA_PROCESS_LOCK_STALE_SECONDS", 30.0)

    worker_entered = threading.Event()
    release_outer = threading.Event()

    def worker():
        with mm_module._chroma_process_lock("worker"):
            worker_entered.set()

    with mm_module._chroma_process_lock("outer"):
        thread = threading.Thread(target=worker)
        thread.start()
        release_outer.wait(timeout=0.05)
        assert not worker_entered.is_set()

    thread.join(timeout=1.0)
    assert worker_entered.is_set()
    assert lock_path.exists()


def test_chroma_process_lock_times_out_when_lock_is_held(tmp_path, monkeypatch):
    lock_path = tmp_path / "chroma.lock"
    monkeypatch.setattr(mm_module, "CHROMA_PROCESS_LOCK_PATH", lock_path)
    monkeypatch.setattr(mm_module, "CHROMA_PROCESS_LOCK_TIMEOUT", 0.02)
    monkeypatch.setattr(mm_module, "CHROMA_PROCESS_LOCK_POLL_SECONDS", 0.005)
    monkeypatch.setattr(mm_module, "CHROMA_PROCESS_LOCK_STALE_SECONDS", 30.0)

    with mm_module._chroma_process_lock("outer"):
        started = time.monotonic()
        with pytest.raises(RuntimeError, match="Timed out waiting for ChromaDB process lock"):
            with mm_module._chroma_process_lock("contender"):
                pass
        assert time.monotonic() - started >= 0.02


def test_chroma_owner_lock_reports_secondary_process_fallback(tmp_path, monkeypatch):
    owner_path = tmp_path / "chroma.owner.lock"
    mm_module._release_chroma_owner()
    monkeypatch.setattr(mm_module, "CHROMA_OWNER_LOCK_PATH", owner_path)
    monkeypatch.setattr(mm_module, "_chroma_owner_handle", None)
    monkeypatch.setattr(mm_module, "_chroma_disabled_reason", None)

    external_owner = mm_module._prepare_lock_file(owner_path)
    mm_module._try_lock_handle(external_owner)
    try:
        assert mm_module._ensure_chroma_owner() is False
        assert "JSON-first fallback" in mm_module._chroma_disabled_reason
    finally:
        mm_module._unlock_handle(external_owner)
        external_owner.close()
        mm_module._release_chroma_owner()


def test_semantic_search_raises_when_chroma_owner_is_unavailable(monkeypatch):
    async def fake_embed_async(query: str):
        return [0.1, 0.2, 0.3]

    def unavailable_query(*args, **kwargs):
        raise RuntimeError(
            "ChromaDB is owned by another Engram process; "
            "using JSON-first fallback in this process."
        )

    monkeypatch.setattr(mm_module.embedder, "embed_async", fake_embed_async)
    monkeypatch.setattr(mm_module.memory_manager, "_query_semantic_results", unavailable_query)

    with pytest.raises(RuntimeError, match="ChromaDB is owned by another Engram process"):
        asyncio.run(mm_module.memory_manager.search_memories_async("agent memory", limit=3))


def test_structured_search_raises_when_chroma_owner_is_unavailable(monkeypatch):
    async def fake_embed_async(query: str):
        return [0.1, 0.2, 0.3]

    def unavailable_query(*args, **kwargs):
        raise RuntimeError(
            "ChromaDB is owned by another Engram process; "
            "using JSON-first fallback in this process."
        )

    monkeypatch.setattr(mm_module.embedder, "embed_async", fake_embed_async)
    monkeypatch.setattr(mm_module.memory_manager, "_query_structured_semantic_results", unavailable_query)

    with pytest.raises(RuntimeError, match="ChromaDB is owned by another Engram process"):
        asyncio.run(
            mm_module.memory_manager.search_memories_structured_async(
                "agent memory",
                limit=3,
                include_stale=False,
            )
        )
