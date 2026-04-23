from __future__ import annotations

import asyncio
import importlib


def load_server_module():
    import server

    return importlib.reload(server)


def test_memory_protocol_describes_agent_retrieval_contract():
    server = load_server_module()

    payload = asyncio.run(server.memory_protocol())

    assert payload["name"] == "Engram memory protocol"
    assert payload["version"] == 1
    assert [step["tool"] for step in payload["retrieval_ladder"]] == [
        "search_memories",
        "retrieve_chunk",
        "retrieve_memory",
    ]
    assert payload["aliases"]["find_memories"] == "search_memories"
    assert payload["aliases"]["read_chunk"] == "retrieve_chunk"
    assert payload["aliases"]["write_memory"] == "store_memory"
    assert payload["warnings"][0].startswith("Do not call retrieve_memory")


def test_search_memories_uses_structured_path_when_filters_are_supplied(monkeypatch):
    server = load_server_module()
    observed: dict[str, object] = {}

    async def fake_structured_search(query: str, limit: int = 5, **kwargs):
        observed["query"] = query
        observed["limit"] = limit
        observed["kwargs"] = kwargs
        return {
            "query": query,
            "count": 1,
            "results": [
                {
                    "key": "engram-agent-note",
                    "chunk_id": 2,
                    "title": "Engram agent note",
                    "score": 0.97,
                    "snippet": "Filtered snippet",
                    "tags": ["ops"],
                    "project": "engram",
                    "domain": "agent",
                    "canonical": True,
                    "status": "active",
                    "stale_type": None,
                    "explanation": "project=engram; canonical memory",
                }
            ],
        }

    async def fail_if_legacy_search(*args, **kwargs):
        raise AssertionError("filtered searches should use structured search")

    monkeypatch.setattr(server.memory_manager, "search_memories_structured_async", fake_structured_search)
    monkeypatch.setattr(server.memory_manager, "search_memories_async", fail_if_legacy_search)

    payload = asyncio.run(
        server.search_memories(
            "agent memory",
            limit=99,
            project="engram",
            domain="agent",
            tags="ops,tooling",
            include_stale=False,
            canonical_only=True,
        )
    )

    assert observed == {
        "query": "agent memory",
        "limit": 20,
        "kwargs": {
            "project": "engram",
            "domain": "agent",
            "tags": ["ops", "tooling"],
            "include_stale": False,
            "canonical_only": True,
            "pinned_keys": [],
            "pinned_first": False,
        },
    }
    assert payload["error"] is None
    assert payload["results"][0]["project"] == "engram"


def test_list_memories_filters_and_paginates_metadata(monkeypatch):
    server = load_server_module()
    memories = [
        {
            "key": "alpha",
            "title": "Alpha",
            "tags": ["agent"],
            "project": "engram",
            "domain": "memory",
            "status": "active",
            "canonical": False,
            "updated_at": "2026-04-20T10:30:00+00:00",
            "created_at": "2026-04-19T10:30:00+00:00",
            "chars": 100,
            "chunk_count": 1,
        },
        {
            "key": "beta",
            "title": "Beta",
            "tags": ["agent", "protocol"],
            "project": "engram",
            "domain": "memory",
            "status": "active",
            "canonical": True,
            "updated_at": "2026-04-21T10:30:00+00:00",
            "created_at": "2026-04-19T10:30:00+00:00",
            "chars": 200,
            "chunk_count": 2,
        },
        {
            "key": "gamma",
            "title": "Gamma",
            "tags": ["agent"],
            "project": "other",
            "domain": "memory",
            "status": "active",
            "canonical": False,
            "updated_at": "2026-04-22T10:30:00+00:00",
            "created_at": "2026-04-19T10:30:00+00:00",
            "chars": 300,
            "chunk_count": 3,
        },
    ]

    async def fake_list():
        return memories

    monkeypatch.setattr(server.memory_manager, "list_memories_async", fake_list)

    payload = asyncio.run(
        server.list_memories(
            limit=1,
            offset=0,
            project="engram",
            domain="memory",
            tags="protocol",
        )
    )

    assert payload["count"] == 1
    assert payload["total"] == 1
    assert payload["limit"] == 1
    assert payload["offset"] == 0
    assert payload["has_more"] is False
    assert payload["memories"][0]["key"] == "beta"
    assert payload["memories"][0]["canonical"] is True


def test_alias_tools_delegate_to_canonical_tools(monkeypatch):
    server = load_server_module()
    observed: dict[str, object] = {}

    async def fake_search_memories(query: str, **kwargs):
        observed["search"] = {"query": query, **kwargs}
        return {"query": query, "count": 0, "results": [], "error": None}

    async def fake_retrieve_chunk(key: str, chunk_id: int):
        observed["chunk"] = {"key": key, "chunk_id": chunk_id}
        return {"key": key, "chunk_id": chunk_id, "found": True, "chunk": {"text": "chunk"}, "error": None}

    async def fake_store_memory(key: str, content: str, **kwargs):
        observed["store"] = {"key": key, "content": content, **kwargs}
        return "stored"

    monkeypatch.setattr(server, "search_memories", fake_search_memories)
    monkeypatch.setattr(server, "retrieve_chunk", fake_retrieve_chunk)
    monkeypatch.setattr(server, "store_memory", fake_store_memory)

    search_payload = asyncio.run(server.find_memories("agent", project="engram"))
    chunk_payload = asyncio.run(server.read_chunk("alpha", 3))
    store_payload = asyncio.run(server.write_memory("alpha", "body", tags="agent"))

    assert search_payload["query"] == "agent"
    assert chunk_payload["chunk"]["text"] == "chunk"
    assert store_payload == "stored"
    assert observed == {
        "search": {"query": "agent", "project": "engram"},
        "chunk": {"key": "alpha", "chunk_id": 3},
        "store": {"key": "alpha", "content": "body", "tags": "agent"},
    }


def test_read_memory_defaults_to_metadata_and_requires_explicit_full(monkeypatch):
    server = load_server_module()

    async def fake_retrieve_memory(key: str):
        return {
            "key": key,
            "found": True,
            "memory": {
                "key": key,
                "title": "Alpha",
                "tags": ["agent"],
                "updated_at": "2026-04-21T10:30:00+00:00",
                "chars": 123,
                "chunk_count": 2,
                "content": "full body",
            },
            "error": None,
        }

    monkeypatch.setattr(server, "retrieve_memory", fake_retrieve_memory)

    metadata_payload = asyncio.run(server.read_memory("alpha"))
    full_payload = asyncio.run(server.read_memory("alpha", full=True))

    assert metadata_payload["mode"] == "metadata"
    assert metadata_payload["memory"]["key"] == "alpha"
    assert "content" not in metadata_payload["memory"]
    assert metadata_payload["guidance"].startswith("Use read_chunk")
    assert full_payload["mode"] == "full"
    assert full_payload["result"]["memory"]["content"] == "full body"


def test_context_pack_searches_dedupes_and_retrieves_budgeted_chunks(monkeypatch):
    server = load_server_module()
    observed: dict[str, object] = {}

    async def fake_search_memories(query: str, **kwargs):
        observed["search"] = {"query": query, **kwargs}
        return {
            "query": query,
            "count": 3,
            "results": [
                {"key": "alpha", "chunk_id": 0, "title": "Alpha", "score": 0.99, "snippet": "a", "tags": []},
                {"key": "alpha", "chunk_id": 0, "title": "Alpha", "score": 0.98, "snippet": "a2", "tags": []},
                {"key": "beta", "chunk_id": 1, "title": "Beta", "score": 0.88, "snippet": "b", "tags": []},
            ],
            "error": None,
        }

    async def fake_retrieve_chunks(requests: list[dict]):
        observed["requests"] = requests
        return {
            "requested_count": len(requests),
            "found_count": 2,
            "results": [
                {
                    "key": "alpha",
                    "chunk_id": 0,
                    "found": True,
                    "chunk": {
                        "title": "Alpha",
                        "text": "Alpha chunk text",
                        "section_title": "Overview",
                        "heading_path": ["Alpha", "Overview"],
                        "chunk_kind": "section",
                    },
                    "error": None,
                },
                {
                    "key": "beta",
                    "chunk_id": 1,
                    "found": True,
                    "chunk": {
                        "title": "Beta",
                        "text": "Beta chunk text",
                        "section_title": "Details",
                        "heading_path": ["Beta", "Details"],
                        "chunk_kind": "section",
                    },
                    "error": None,
                },
            ],
            "error": None,
        }

    monkeypatch.setattr(server, "search_memories", fake_search_memories)
    monkeypatch.setattr(server, "retrieve_chunks", fake_retrieve_chunks)

    payload = asyncio.run(
        server.context_pack(
            "agent memory",
            project="engram",
            max_chunks=5,
            budget_chars=40,
        )
    )

    assert observed["search"] == {
        "query": "agent memory",
        "limit": 5,
        "project": "engram",
        "domain": None,
        "tags": None,
        "include_stale": False,
        "canonical_only": False,
    }
    assert observed["requests"] == [{"key": "alpha", "chunk_id": 0}, {"key": "beta", "chunk_id": 1}]
    assert payload["count"] == 2
    assert payload["used_chars"] <= 40
    assert [chunk["key"] for chunk in payload["chunks"]] == ["alpha", "beta"]
    assert payload["chunks"][0]["score"] == 0.99
    assert payload["error"] is None
