from __future__ import annotations

import asyncio
import importlib

from core.session_pins import SessionPinStore


def load_server_module():
    import server

    return importlib.reload(server)


def load_memory_manager_module():
    import core.memory_manager as memory_manager_module

    return importlib.reload(memory_manager_module)


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


def test_search_memories_v2_keeps_bounded_search_when_session_has_no_pins(monkeypatch):
    server = load_server_module()
    observed: dict[str, object] = {}
    expected_results = [
        {
            "key": "alpha-note",
            "chunk_id": 0,
            "title": "Alpha note",
            "score": 0.98,
            "snippet": "Alpha snippet",
            "tags": ["alpha"],
        }
    ]

    class FakePinStore:
        def list_pins(self, session_id: str) -> list[str]:
            observed["session_id"] = session_id
            return []

    async def fake_search(query: str, limit: int = 5):
        observed["query"] = query
        observed["limit"] = limit
        return expected_results

    async def fail_if_structured(*args, **kwargs):
        raise AssertionError("structured search path should not run when the session has no pins")

    monkeypatch.setattr(server, "session_pin_store", FakePinStore())
    monkeypatch.setattr(server.memory_manager, "search_memories_async", fake_search)
    monkeypatch.setattr(server.memory_manager, "search_memories_structured_async", fail_if_structured)

    payload = asyncio.run(server.search_memories_v2("alpha", limit=7, session_id="session-a"))

    assert observed == {
        "session_id": "session-a",
        "query": "alpha",
        "limit": 7,
    }
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
        "error": None,
    }


def test_list_memories_v2_runtime_failure_returns_structured_error(monkeypatch):
    server = load_server_module()

    async def fake_list():
        raise RuntimeError("boom")

    monkeypatch.setattr(server.memory_manager, "list_memories_async", fake_list)

    payload = asyncio.run(server.list_memories_v2())

    assert payload == {
        "count": 0,
        "memories": [],
        "error": {
            "code": "runtime_error",
            "message": "❌ Engram error: boom",
        },
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
            "error": None,
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


def test_list_all_memories_renders_structured_runtime_error_from_v2(monkeypatch):
    server = load_server_module()

    async def fake_list_v2():
        return {
            "count": 0,
            "memories": [],
            "error": {
                "code": "runtime_error",
                "message": "❌ Engram error: boom",
            },
        }

    monkeypatch.setattr(server, "list_memories_v2", fake_list_v2)

    rendered = asyncio.run(server.list_all_memories())

    assert rendered == "❌ Engram error: boom"


def test_retrieve_chunk_renders_payload_from_v2(monkeypatch):
    server = load_server_module()

    async def fake_retrieve_chunk_v2(key: str, chunk_id: int):
        assert key == "alpha-note"
        assert chunk_id == 0
        return {
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
        }

    monkeypatch.setattr(server, "retrieve_chunk_v2", fake_retrieve_chunk_v2)

    rendered = asyncio.run(server.retrieve_chunk("alpha-note", 0))

    assert rendered == (
        "📄 Chunk 0 from 'Alpha note'\n"
        "🔑 Key: alpha-note\n\n"
        "Alpha chunk"
    )


def test_retrieve_chunk_renders_not_found_from_v2(monkeypatch):
    server = load_server_module()

    async def fake_retrieve_chunk_v2(key: str, chunk_id: int):
        return {
            "key": key,
            "chunk_id": chunk_id,
            "found": False,
            "chunk": None,
            "error": None,
        }

    monkeypatch.setattr(server, "retrieve_chunk_v2", fake_retrieve_chunk_v2)

    rendered = asyncio.run(server.retrieve_chunk("missing-note", 9))

    assert rendered == "❌ Chunk not found: key='missing-note' chunk_id=9"


def test_retrieve_chunk_renders_runtime_error_from_v2(monkeypatch):
    server = load_server_module()

    async def fake_retrieve_chunk_v2(key: str, chunk_id: int):
        return {
            "key": key,
            "chunk_id": chunk_id,
            "found": False,
            "chunk": None,
            "error": {
                "code": "runtime_error",
                "message": "❌ Engram error: boom",
            },
        }

    monkeypatch.setattr(server, "retrieve_chunk_v2", fake_retrieve_chunk_v2)

    rendered = asyncio.run(server.retrieve_chunk("alpha-note", 0))

    assert rendered == "❌ Engram error: boom"


def test_retrieve_memory_renders_payload_from_v2(monkeypatch):
    server = load_server_module()

    async def fake_retrieve_memory_v2(key: str):
        assert key == "alpha-note"
        return {
            "key": "alpha-note",
            "found": True,
            "memory": {
                "key": "alpha-note",
                "title": "Alpha note",
                "tags": ["alpha", "ops"],
                "updated_at": "2026-04-20T10:30:00+00:00",
                "chunk_count": 2,
                "chars": 123,
                "content": "Alpha body",
            },
            "error": None,
        }

    monkeypatch.setattr(server, "retrieve_memory_v2", fake_retrieve_memory_v2)

    rendered = asyncio.run(server.retrieve_memory("alpha-note"))

    assert rendered == (
        "📦 Alpha note\n"
        "🔑 Key: alpha-note\n"
        "🏷  Tags: alpha, ops\n"
        "📅 Updated: 2026-04-20T10:30\n"
        "📊 123 chars | 2 chunks\n\n"
        "Alpha body"
    )


def test_retrieve_memory_renders_not_found_from_v2(monkeypatch):
    server = load_server_module()

    async def fake_retrieve_memory_v2(key: str):
        return {
            "key": key,
            "found": False,
            "memory": None,
            "error": None,
        }

    monkeypatch.setattr(server, "retrieve_memory_v2", fake_retrieve_memory_v2)

    rendered = asyncio.run(server.retrieve_memory("missing-note"))

    assert rendered == "❌ Memory not found: 'missing-note'"


def test_retrieve_memory_renders_runtime_error_from_v2(monkeypatch):
    server = load_server_module()

    async def fake_retrieve_memory_v2(key: str):
        return {
            "key": key,
            "found": False,
            "memory": None,
            "error": {
                "code": "runtime_error",
                "message": "❌ Engram error: boom",
            },
        }

    monkeypatch.setattr(server, "retrieve_memory_v2", fake_retrieve_memory_v2)

    rendered = asyncio.run(server.retrieve_memory("alpha-note"))

    assert rendered == "❌ Engram error: boom"


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


def test_memory_manager_retrieve_chunks_preserves_order_and_duplicates(monkeypatch):
    memory_manager_module = load_memory_manager_module()
    manager = memory_manager_module.MemoryManager()

    class FakeCollection:
        def __init__(self):
            self.observed_ids = None
            self.observed_include = None

        def get(self, ids, include):
            self.observed_ids = ids
            self.observed_include = include
            return {
                "ids": ids,
                "documents": ["Alpha chunk", "Beta chunk"],
                "metadatas": [
                    {
                        "title": "Alpha note",
                        "section_title": "Overview",
                        "heading_path": "Alpha > Overview",
                        "chunk_kind": "section",
                    },
                    {
                        "title": "Beta note",
                        "section_title": "Details",
                        "heading_path": "Beta > Details",
                        "chunk_kind": "section",
                    },
                ],
            }

    fake_collection = FakeCollection()
    monkeypatch.setattr(manager, "_get_collection", lambda: fake_collection)

    requests = [
        {"key": "alpha-note", "chunk_id": 0},
        {"key": "alpha-note", "chunk_id": 0},
        {"key": "beta-note", "chunk_id": 2},
    ]

    results = manager.retrieve_chunks(requests)

    assert fake_collection.observed_ids == [
        memory_manager_module._chunk_doc_id("alpha-note", 0),
        memory_manager_module._chunk_doc_id("beta-note", 2),
    ]
    assert fake_collection.observed_include == ["documents", "metadatas"]
    assert results == [
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
            "key": "beta-note",
            "chunk_id": 2,
            "found": True,
            "title": "Beta note",
            "text": "Beta chunk",
            "section_title": "Details",
            "heading_path": ["Beta", "Details"],
            "chunk_kind": "section",
        },
    ]


def test_memory_manager_retrieve_chunks_reports_per_item_validation_errors(monkeypatch):
    memory_manager_module = load_memory_manager_module()
    manager = memory_manager_module.MemoryManager()

    class FakeCollection:
        def __init__(self):
            self.observed_ids = None

        def get(self, ids, include):
            self.observed_ids = ids
            return {
                "ids": ids,
                "documents": ["Gamma chunk"],
                "metadatas": [
                    {
                        "title": "Gamma note",
                        "section_title": "Summary",
                        "heading_path": "Gamma > Summary",
                        "chunk_kind": "section",
                    }
                ],
            }

    fake_collection = FakeCollection()
    monkeypatch.setattr(manager, "_get_collection", lambda: fake_collection)

    requests = [
        {"key": "alpha-note", "chunk_id": True},
        {"key": "beta-note", "chunk_id": 1.9},
        {"key": "", "chunk_id": 1},
        "not-a-dict",
        {"key": "gamma-note", "chunk_id": 2},
    ]

    results = manager.retrieve_chunks(requests)

    assert fake_collection.observed_ids == [
        memory_manager_module._chunk_doc_id("gamma-note", 2)
    ]
    assert results == [
        {
            "key": "alpha-note",
            "chunk_id": True,
            "found": False,
            "title": "alpha-note",
            "text": None,
            "section_title": None,
            "heading_path": [],
            "chunk_kind": None,
            "error": {
                "code": "invalid_request",
                "message": "chunk_id must be an integer",
            },
        },
        {
            "key": "beta-note",
            "chunk_id": 1.9,
            "found": False,
            "title": "beta-note",
            "text": None,
            "section_title": None,
            "heading_path": [],
            "chunk_kind": None,
            "error": {
                "code": "invalid_request",
                "message": "chunk_id must be an integer",
            },
        },
        {
            "key": "",
            "chunk_id": -1,
            "found": False,
            "title": "",
            "text": None,
            "section_title": None,
            "heading_path": [],
            "chunk_kind": None,
            "error": {
                "code": "invalid_request",
                "message": "key is required",
            },
        },
        {
            "key": "",
            "chunk_id": -1,
            "found": False,
            "title": "",
            "text": None,
            "section_title": None,
            "heading_path": [],
            "chunk_kind": None,
            "error": {
                "code": "invalid_request",
                "message": "request must be an object with key and chunk_id",
            },
        },
        {
            "key": "gamma-note",
            "chunk_id": 2,
            "found": True,
            "title": "Gamma note",
            "text": "Gamma chunk",
            "section_title": "Summary",
            "heading_path": ["Gamma", "Summary"],
            "chunk_kind": "section",
        },
    ]


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


def test_retrieve_chunks_v2_preserves_per_item_error_objects(monkeypatch):
    server = load_server_module()

    async def fake_retrieve_chunks(batch_requests: list[dict]):
        assert batch_requests == [{"key": "alpha-note", "chunk_id": True}]
        return [
            {
                "key": "alpha-note",
                "chunk_id": True,
                "found": False,
                "error": {
                    "code": "invalid_request",
                    "message": "chunk_id must be an integer",
                },
            }
        ]

    monkeypatch.setattr(server.memory_manager, "retrieve_chunks_async", fake_retrieve_chunks)

    payload = asyncio.run(server.retrieve_chunks_v2([{"key": "alpha-note", "chunk_id": True}]))

    assert payload == {
        "requested_count": 1,
        "found_count": 0,
        "results": [
            {
                "key": "alpha-note",
                "chunk_id": True,
                "found": False,
                "chunk": None,
                "error": {
                    "code": "invalid_request",
                    "message": "chunk_id must be an integer",
                },
            }
        ],
        "error": None,
    }


def test_delete_memory_clears_deleted_key_from_session_pins(monkeypatch):
    server = load_server_module()
    observed: dict[str, object] = {}

    async def fake_delete(key: str) -> bool:
        observed["deleted_key"] = key
        return True

    class FakePinStore:
        def remove_key(self, key: str) -> int:
            observed["removed_key"] = key
            return 2

    monkeypatch.setattr(server.memory_manager, "delete_memory_async", fake_delete)
    monkeypatch.setattr(server, "session_pin_store", FakePinStore())

    rendered = asyncio.run(server.delete_memory("alpha-note"))

    assert observed == {
        "deleted_key": "alpha-note",
        "removed_key": "alpha-note",
    }
    assert rendered == "🗑  Deleted memory: 'alpha-note'"


def test_session_pin_store_remove_key_clears_stale_pins_across_sessions(tmp_path):
    store = SessionPinStore(tmp_path / "session_pins.json")
    store.pin("session-a", "alpha-note")
    store.pin("session-a", "beta-note")
    store.pin("session-b", "alpha-note")

    removed = store.remove_key("alpha-note")

    assert removed == 2
    assert store.list_pins("session-a") == ["beta-note"]
    assert store.list_pins("session-b") == []
