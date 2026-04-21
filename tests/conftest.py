from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import pytest


class FakeChromaCollection:
    def __init__(self):
        self.docs: dict[str, dict[str, Any]] = {}
        self.fail_delete = False
        self.operations: list[str] = []

    def count(self) -> int:
        return len(self.docs)

    def _match_docs(self, ids=None, where=None):
        if ids is not None:
            flat_ids = self._flatten_ids(ids)
            return [self.docs[doc_id] for doc_id in flat_ids if doc_id in self.docs]

        if where is not None:
            parent_key = where.get("parent_key")
            return [
                doc
                for doc in self.docs.values()
                if doc["metadata"].get("parent_key") == parent_key
            ]

        return list(self.docs.values())

    @staticmethod
    def _flatten_ids(ids):
        flat = []
        for item in ids:
            if isinstance(item, list):
                flat.extend(item)
            else:
                flat.append(item)
        return flat

    def get(self, ids=None, where=None, include=None):
        docs = self._match_docs(ids=ids, where=where)
        return {
            "ids": [doc["id"] for doc in docs],
            "documents": [doc["document"] for doc in docs],
            "metadatas": [doc["metadata"] for doc in docs],
        }

    def query(self, query_embeddings=None, n_results=1, include=None):
        docs = list(self.docs.values())[:n_results]
        return {
            "ids": [[doc["id"] for doc in docs]],
            "documents": [[doc["document"] for doc in docs]],
            "metadatas": [[doc["metadata"] for doc in docs]],
            "distances": [[0.0 for _ in docs]],
        }

    def upsert(self, ids, embeddings, documents, metadatas):
        self.operations.append("upsert")
        for index, doc_id in enumerate(ids):
            self.docs[doc_id] = {
                "id": doc_id,
                "embedding": embeddings[index],
                "document": documents[index],
                "metadata": metadatas[index],
            }

    def delete(self, ids=None, where=None):
        self.operations.append("delete")
        if self.fail_delete:
            raise RuntimeError("simulated chroma delete failure")

        for doc in self._match_docs(ids=ids, where=where):
            self.docs.pop(doc["id"], None)


@pytest.fixture
def fake_chroma_collection():
    return FakeChromaCollection()


@pytest.fixture(autouse=True)
def mm_module(tmp_path, monkeypatch):
    json_dir = tmp_path / "memories"
    chroma_dir = tmp_path / "chroma"
    json_dir.mkdir()
    chroma_dir.mkdir()

    original_mkdir = Path.mkdir

    def guarded_mkdir(self, *args, **kwargs):
        return None

    monkeypatch.setattr(Path, "mkdir", guarded_mkdir)
    importlib.invalidate_caches()
    sys.modules.pop("core.memory_manager", None)
    module = importlib.import_module("core.memory_manager")
    monkeypatch.setattr(Path, "mkdir", original_mkdir)
    return module


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch, fake_chroma_collection, mm_module):
    json_dir = tmp_path / "memories"
    chroma_dir = tmp_path / "chroma"
    json_dir.mkdir(exist_ok=True)
    chroma_dir.mkdir(exist_ok=True)

    monkeypatch.setattr(mm_module, "JSON_DIR", json_dir)
    monkeypatch.setattr(mm_module, "CHROMA_DIR", chroma_dir)
    monkeypatch.setattr(mm_module.memory_manager, "_get_collection", lambda: fake_chroma_collection)
    mm_module.memory_manager._collection = fake_chroma_collection
    mm_module.memory_manager._chroma = object()

    monkeypatch.setattr(mm_module.embedder, "embed", lambda text: [0.0, 0.0, 0.0])
    monkeypatch.setattr(
        mm_module.embedder,
        "embed_batch",
        lambda texts: [[0.0, 0.0, 0.0] for _ in texts],
    )

    async def _embed_async(text: str):
        return [0.0, 0.0, 0.0]

    async def _embed_batch_async(texts):
        return [[0.0, 0.0, 0.0] for _ in texts]

    monkeypatch.setattr(mm_module.embedder, "embed_async", _embed_async)
    monkeypatch.setattr(mm_module.embedder, "embed_batch_async", _embed_batch_async)

    yield {
        "json_dir": json_dir,
        "chroma_dir": chroma_dir,
        "collection": fake_chroma_collection,
        "mm": mm_module,
    }

    mm_module.memory_manager._collection = None
    mm_module.memory_manager._chroma = None
