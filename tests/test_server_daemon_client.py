from __future__ import annotations

import asyncio

import server


class FakeDaemonClient:
    def __init__(self):
        self.calls = []

    def search_memories(self, payload):
        self.calls.append(("search_memories", payload))
        return {
            "query": payload["query"],
            "count": 1,
            "results": [{"key": "daemon_memory", "chunk_id": 0}],
            "error": None,
        }

    def retrieve_chunk(self, payload):
        self.calls.append(("retrieve_chunk", payload))
        return {
            "key": payload["key"],
            "chunk_id": payload["chunk_id"],
            "found": True,
            "chunk": {"title": "Daemon Memory", "text": "chunk"},
            "error": None,
        }

    def retrieve_chunks(self, payload):
        self.calls.append(("retrieve_chunks", payload))
        return {
            "requested_count": len(payload["requests"]),
            "found_count": 1,
            "results": [
                {
                    "key": payload["requests"][0]["key"],
                    "chunk_id": payload["requests"][0]["chunk_id"],
                    "found": True,
                    "chunk": {"title": "Daemon Memory", "text": "chunk"},
                    "error": None,
                }
            ],
            "error": None,
        }

    def retrieve_memory(self, payload):
        self.calls.append(("retrieve_memory", payload))
        return {
            "key": payload["key"],
            "found": True,
            "memory": {"key": payload["key"], "title": "Daemon Memory", "content": "body"},
            "error": None,
        }

    def store_memory(self, payload):
        self.calls.append(("store_memory", payload))
        return {
            "stored": True,
            "result": {
                "key": payload["key"],
                "title": payload["title"],
                "chunk_count": 1,
                "chars": len(payload["content"]),
            },
            "error": None,
        }

    def delete_memory(self, payload):
        self.calls.append(("delete_memory", payload))
        return {"key": payload["key"], "deleted": True, "error": None}


def test_search_memories_uses_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    result = asyncio.run(server.search_memories("daemon check", retrieval_mode="hybrid"))

    assert result["results"][0]["key"] == "daemon_memory"
    assert client.calls[0][0] == "search_memories"
    assert client.calls[0][1]["retrieval_mode"] == "hybrid"


def test_read_tools_use_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    chunk = asyncio.run(server.retrieve_chunk("daemon_memory", 0))
    chunks = asyncio.run(server.retrieve_chunks([{"key": "daemon_memory", "chunk_id": 0}]))
    memory = asyncio.run(server.retrieve_memory("daemon_memory"))

    assert chunk["chunk"]["text"] == "chunk"
    assert chunks["found_count"] == 1
    assert memory["memory"]["content"] == "body"
    assert [call[0] for call in client.calls] == [
        "retrieve_chunk",
        "retrieve_chunks",
        "retrieve_memory",
    ]


def test_write_and_delete_tools_use_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    stored = asyncio.run(
        server.store_memory(
            key="daemon_memory",
            content="Daemon body.",
            title="Daemon Memory",
            tags=["daemon"],
            force=True,
        )
    )
    deleted = asyncio.run(server.delete_memory("daemon_memory"))

    assert "Stored: 'Daemon Memory'" in stored
    assert "Deleted memory: 'daemon_memory'" in deleted
    assert [call[0] for call in client.calls] == ["store_memory", "delete_memory"]
