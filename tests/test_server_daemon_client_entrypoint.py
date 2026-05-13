from __future__ import annotations

import asyncio
import builtins
import importlib
import sys


def test_thin_daemon_client_imports_without_storage_dependencies(monkeypatch):
    blocked = {"chromadb", "sentence_transformers", "torch"}
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.split(".", 1)[0] in blocked:
            raise ImportError(f"blocked storage dependency: {name}")
        return real_import(name, *args, **kwargs)

    for module_name in list(sys.modules):
        if (
            module_name == "server_daemon_client"
            or module_name.startswith("server_daemon_client.")
        ):
            del sys.modules[module_name]

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    module = importlib.import_module("server_daemon_client")

    assert module.PRODUCT_NAME == "Engram"
    assert module._daemon_url() == "http://127.0.0.1:8765"


def test_thin_daemon_client_search_delegates_to_daemon(monkeypatch):
    import server_daemon_client

    class FakeClient:
        def __init__(self) -> None:
            self.calls = []

        def search_memories(self, payload):
            self.calls.append(("search_memories", payload))
            return {
                "query": payload["query"],
                "count": 1,
                "results": [{"key": "daemon_memory", "chunk_id": 0}],
                "error": None,
            }

    client = FakeClient()
    monkeypatch.setattr(server_daemon_client, "_daemon_client", lambda: client)

    payload = asyncio.run(
        server_daemon_client.search_memories(
            "daemon check",
            limit=3,
            tags="backend, daemon",
            retrieval_mode="hybrid",
        )
    )

    assert payload["results"][0]["key"] == "daemon_memory"
    assert client.calls == [
        (
            "search_memories",
            {
                "query": "daemon check",
                "limit": 3,
                "project": None,
                "domain": None,
                "tags": ["backend", "daemon"],
                "include_stale": True,
                "canonical_only": False,
                "pinned_keys": [],
                "pinned_first": False,
                "retrieval_mode": "hybrid",
            },
        )
    ]


def test_thin_daemon_client_store_formats_daemon_response(monkeypatch):
    import server_daemon_client

    class FakeClient:
        def store_memory(self, payload):
            return {
                "stored": True,
                "result": {
                    "key": payload["key"],
                    "title": payload["title"],
                    "chunk_count": 2,
                    "chars": len(payload["content"]),
                },
                "error": None,
            }

    monkeypatch.setattr(server_daemon_client, "_daemon_client", lambda: FakeClient())

    message = asyncio.run(
        server_daemon_client.store_memory(
            key="daemon_memory",
            content="Daemon body.",
            title="Daemon Memory",
            tags=["daemon"],
            force=True,
        )
    )

    assert "Stored: 'Daemon Memory'" in message
    assert "2 chunks" in message
