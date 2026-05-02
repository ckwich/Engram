from __future__ import annotations

import importlib
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest


_SUITE_ROOT = Path(tempfile.mkdtemp(prefix="engram-tests-"))
_SUITE_JSON_DIR = _SUITE_ROOT / "memories"
_SUITE_CHROMA_DIR = _SUITE_ROOT / "chroma"

_ORIGINAL_MKDIR = Path.mkdir


def _guarded_mkdir(self, *args, **kwargs):
    return None


Path.mkdir = _guarded_mkdir
try:
    sys.modules.pop("core.memory_manager", None)
    mm = importlib.import_module("core.memory_manager")
finally:
    Path.mkdir = _ORIGINAL_MKDIR

_SUITE_JSON_DIR.mkdir(parents=True, exist_ok=True)
_SUITE_CHROMA_DIR.mkdir(parents=True, exist_ok=True)
mm.JSON_DIR = _SUITE_JSON_DIR
mm.CHROMA_DIR = _SUITE_CHROMA_DIR


class FakeChromaCollection:
    """Tiny in-memory Chroma stub for the storage invariants only.

    It only implements the handful of methods these tests need and does not
    attempt to model full ChromaDB behavior.
    """

    def __init__(self):
        self.docs: dict[str, dict[str, Any]] = {}
        self.fail_delete = False
        self.fail_upsert = False
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
        if self.fail_upsert:
            raise RuntimeError("simulated chroma upsert failure")
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
def mm_module():
    return mm


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


@pytest.fixture
def isolated_graph_storage(tmp_path, monkeypatch):
    import core.graph_manager as graph_manager_module

    graph_dir = tmp_path / "graph"
    graph_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(graph_manager_module, "GRAPH_DIR", graph_dir)
    monkeypatch.setattr(graph_manager_module, "EDGES_PATH", graph_dir / "edges.json")
    graph_manager_module.graph_manager.reset_store()
    yield graph_manager_module
    graph_manager_module.graph_manager.reset_store()


@pytest.fixture
def isolated_source_drafts(tmp_path, monkeypatch):
    import core.source_intake as source_intake_module

    drafts_dir = tmp_path / "source_drafts"
    drafts_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(source_intake_module, "SOURCE_DRAFTS_DIR", drafts_dir)
    source_intake_module.source_intake_manager._draft_cache = None
    yield source_intake_module
    source_intake_module.source_intake_manager._draft_cache = None


@pytest.fixture
def isolated_usage_meter(tmp_path, monkeypatch):
    import core.usage_meter as usage_meter_module

    usage_dir = tmp_path / "usage"
    usage_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(usage_meter_module, "USAGE_DIR", usage_dir)
    monkeypatch.setattr(usage_meter_module, "TOOL_CALLS_PATH", usage_dir / "tool_calls.jsonl")
    monkeypatch.setattr(usage_meter_module, "DAILY_ROLLUPS_PATH", usage_dir / "daily_rollups.json")
    usage_meter_module.usage_meter = usage_meter_module.UsageMeter()
    yield usage_meter_module


@pytest.fixture
def isolated_operation_log(tmp_path, monkeypatch):
    import core.operation_log as operation_log_module

    operations_dir = tmp_path / "operations"
    operations_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(operation_log_module, "OPERATIONS_DIR", operations_dir)
    monkeypatch.setattr(operation_log_module, "JOBS_PATH", operations_dir / "jobs.jsonl")
    monkeypatch.setattr(operation_log_module, "EVENTS_PATH", operations_dir / "events.jsonl")
    operation_log_module.operation_log = operation_log_module.OperationLog()
    yield operation_log_module
