from __future__ import annotations

import asyncio
import importlib


def load_server_module():
    import server

    return importlib.reload(server)


def test_search_memories_v2_returns_structured_payload(monkeypatch):
    server = load_server_module()
    observed: dict[str, object] = {}
    expected_results = [
        {
            "key": "alpha-note",
            "chunk_id": 0,
            "title": "Alpha note",
            "score": 0.987,
            "snippet": "Alpha snippet",
            "tags": ["alpha", "ops"],
        }
    ]

    async def fake_search(query: str, limit: int = 5):
        observed["query"] = query
        observed["limit"] = limit
        return expected_results

    monkeypatch.setattr(server.memory_manager, "search_memories_async", fake_search)

    payload = asyncio.run(server.search_memories_v2("alpha", limit=99))

    assert observed == {"query": "alpha", "limit": 20}
    assert payload == {
        "query": "alpha",
        "count": 1,
        "results": expected_results,
        "error": None,
    }


def test_list_memories_v2_returns_structured_payload(monkeypatch):
    server = load_server_module()
    expected_memories = [
        {
            "key": "alpha-note",
            "title": "Alpha note",
            "tags": ["alpha"],
            "updated_at": "2026-04-20T10:30:00+00:00",
            "created_at": "2026-04-19T10:30:00+00:00",
            "chars": 123,
            "chunk_count": 2,
        }
    ]

    async def fake_list():
        return expected_memories

    monkeypatch.setattr(server.memory_manager, "list_memories_async", fake_list)

    payload = asyncio.run(server.list_memories_v2())

    assert payload == {
        "count": 1,
        "memories": expected_memories,
    }


def test_search_memories_v2_blank_query_returns_structured_error(monkeypatch):
    server = load_server_module()

    async def fail_if_called(query: str, limit: int = 5):
        raise AssertionError("search_memories_async should not run for invalid queries")

    monkeypatch.setattr(server.memory_manager, "search_memories_async", fail_if_called)

    payload = asyncio.run(server.search_memories_v2("   "))

    assert payload == {
        "query": "   ",
        "count": 0,
        "results": [],
        "error": {
            "code": "invalid_query",
            "message": "❌ Query cannot be empty.",
        },
    }


def test_search_memories_v2_runtime_failure_returns_structured_error(monkeypatch):
    server = load_server_module()

    async def fake_search(query: str, limit: int = 5):
        raise RuntimeError("boom")

    monkeypatch.setattr(server.memory_manager, "search_memories_async", fake_search)

    payload = asyncio.run(server.search_memories_v2("alpha"))

    assert payload == {
        "query": "alpha",
        "count": 0,
        "results": [],
        "error": {
            "code": "runtime_error",
            "message": "❌ Engram error: boom",
        },
    }


def test_search_memories_v2_empty_results_returns_structured_payload(monkeypatch):
    server = load_server_module()

    async def fake_search(query: str, limit: int = 5):
        return []

    monkeypatch.setattr(server.memory_manager, "search_memories_async", fake_search)

    payload = asyncio.run(server.search_memories_v2("alpha"))

    assert payload == {
        "query": "alpha",
        "count": 0,
        "results": [],
        "error": None,
    }


def test_search_memories_renders_payload_from_v2(monkeypatch):
    server = load_server_module()

    async def fake_search_v2(query: str, limit: int = 5):
        assert query == "alpha"
        assert limit == 5
        return {
            "query": "alpha",
            "count": 1,
            "results": [
                {
                    "key": "alpha-note",
                    "chunk_id": 0,
                    "title": "Alpha note",
                    "score": 0.987,
                    "snippet": "Alpha snippet",
                    "tags": ["alpha", "ops"],
                }
            ],
            "error": None,
        }

    monkeypatch.setattr(server, "search_memories_v2", fake_search_v2)

    rendered = asyncio.run(server.search_memories("alpha"))

    assert rendered == (
        "🔍 1 results for 'alpha':\n\n"
        "[score: 0.987] Alpha note\n"
        "  key=alpha-note  chunk_id=0  tags=alpha, ops\n"
        "  snippet: Alpha snippet\n"
    )


def test_search_memories_renders_structured_validation_error_from_v2(monkeypatch):
    server = load_server_module()

    async def fake_search_v2(query: str, limit: int = 5):
        return {
            "query": query,
            "count": 0,
            "results": [],
            "error": {
                "code": "invalid_query",
                "message": "❌ Query cannot be empty.",
            },
        }

    monkeypatch.setattr(server, "search_memories_v2", fake_search_v2)

    rendered = asyncio.run(server.search_memories("   "))

    assert rendered == "❌ Query cannot be empty."


def test_search_memories_renders_structured_runtime_error_from_v2(monkeypatch):
    server = load_server_module()

    async def fake_search_v2(query: str, limit: int = 5):
        return {
            "query": query,
            "count": 0,
            "results": [],
            "error": {
                "code": "runtime_error",
                "message": "❌ Engram error: boom",
            },
        }

    monkeypatch.setattr(server, "search_memories_v2", fake_search_v2)

    rendered = asyncio.run(server.search_memories("alpha"))

    assert rendered == "❌ Engram error: boom"


def test_list_all_memories_renders_payload_from_v2(monkeypatch):
    server = load_server_module()

    async def fake_list_v2():
        return {
            "count": 1,
            "memories": [
                {
                    "key": "alpha-note",
                    "title": "Alpha note",
                    "tags": ["alpha"],
                    "updated_at": "2026-04-20T10:30:00+00:00",
                    "created_at": "2026-04-19T10:30:00+00:00",
                    "chars": 123,
                    "chunk_count": 2,
                }
            ],
        }

    monkeypatch.setattr(server, "list_memories_v2", fake_list_v2)

    rendered = asyncio.run(server.list_all_memories())

    assert rendered == (
        "📚 Engram Memory Directory — 1 memories\n"
        "==================================================\n\n"
        "🔑 alpha-note\n"
        "   Title:   Alpha note\n"
        "   Tags:    alpha\n"
        "   Chunks:  2\n"
        "   Updated: 2026-04-20T10:30\n"
    )


def test_retrieve_chunks_v2_returns_structured_batch_payload(monkeypatch):
    server = load_server_module()
    observed: dict[str, object] = {}
    requests = [
        {"key": "alpha-note", "chunk_id": 0},
        {"key": "missing-note", "chunk_id": 3},
    ]

    async def fake_retrieve_chunks(batch_requests: list[dict]):
        observed["requests"] = batch_requests
        return [
            {
                "key": "alpha-note",
                "chunk_id": 0,
                "found": True,
                "title": "Alpha note",
                "text": "Alpha chunk",
                "section_title": "Overview",
                "heading_path": ["Alpha", "Overview"],
                "chunk_kind": "section",
            },
            {
                "key": "missing-note",
                "chunk_id": 3,
                "found": False,
            },
        ]

    monkeypatch.setattr(server.memory_manager, "retrieve_chunks_async", fake_retrieve_chunks)

    payload = asyncio.run(server.retrieve_chunks_v2(requests))

    assert observed == {"requests": requests}
    assert payload == {
        "requested_count": 2,
        "found_count": 1,
        "results": [
            {
                "key": "alpha-note",
                "chunk_id": 0,
                "found": True,
                "chunk": {
                    "title": "Alpha note",
                    "text": "Alpha chunk",
                    "section_title": "Overview",
                    "heading_path": ["Alpha", "Overview"],
                    "chunk_kind": "section",
                },
                "error": None,
            },
            {
                "key": "missing-note",
                "chunk_id": 3,
                "found": False,
                "chunk": None,
                "error": None,
            },
        ],
        "error": None,
    }


def test_retrieve_memory_v2_returns_structured_memory_payload(monkeypatch):
    server = load_server_module()

    async def fake_retrieve_memory(key: str):
        assert key == "alpha-note"
        return {
            "key": "alpha-note",
            "title": "Alpha note",
            "tags": ["alpha", "ops"],
            "related_to": ["beta-note"],
            "project": "alpha",
            "domain": "operations",
            "status": "active",
            "canonical": True,
            "created_at": "2026-04-19T10:30:00+00:00",
            "updated_at": "2026-04-20T10:30:00+00:00",
            "last_accessed": "2026-04-20T11:00:00+00:00",
            "chunk_count": 2,
            "chars": 123,
            "content": "Alpha body",
        }

    monkeypatch.setattr(server.memory_manager, "retrieve_memory_async", fake_retrieve_memory)

    payload = asyncio.run(server.retrieve_memory_v2("alpha-note"))

    assert payload == {
        "key": "alpha-note",
        "found": True,
        "memory": {
            "key": "alpha-note",
            "title": "Alpha note",
            "tags": ["alpha", "ops"],
            "related_to": ["beta-note"],
            "project": "alpha",
            "domain": "operations",
            "status": "active",
            "canonical": True,
            "created_at": "2026-04-19T10:30:00+00:00",
            "updated_at": "2026-04-20T10:30:00+00:00",
            "last_accessed": "2026-04-20T11:00:00+00:00",
            "chunk_count": 2,
            "chars": 123,
            "content": "Alpha body",
        },
        "error": None,
    }


def test_retrieve_chunk_v2_not_found_returns_found_false(monkeypatch):
    server = load_server_module()
    observed: dict[str, object] = {}

    async def fake_retrieve_chunks(batch_requests: list[dict]):
        observed["requests"] = batch_requests
        return [
            {
                "key": "missing-note",
                "chunk_id": 9,
                "found": False,
            }
        ]

    monkeypatch.setattr(server.memory_manager, "retrieve_chunks_async", fake_retrieve_chunks)

    payload = asyncio.run(server.retrieve_chunk_v2("missing-note", 9))

    assert observed == {"requests": [{"key": "missing-note", "chunk_id": 9}]}
    assert payload == {
        "key": "missing-note",
        "chunk_id": 9,
        "found": False,
        "chunk": None,
        "error": None,
    }
