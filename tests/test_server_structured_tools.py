from __future__ import annotations

import asyncio
import importlib
import json

from core.session_pins import SessionPinStore


def load_server_module():
    import server

    return importlib.reload(server)


def load_memory_manager_module():
    import core.memory_manager as memory_manager_module

    return importlib.reload(memory_manager_module)


def test_search_memories_returns_structured_payload(monkeypatch):
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

    payload = asyncio.run(server.search_memories("alpha", limit=99))

    assert observed == {"query": "alpha", "limit": 20}
    assert payload == {
        "query": "alpha",
        "count": 1,
        "results": expected_results,
        "error": None,
    }


def test_memory_protocol_advertises_agent_native_codebase_mapping():
    server = load_server_module()

    payload = asyncio.run(server.memory_protocol())

    assert payload["stability"]["codebase_mapping"] == "beta"
    assert payload["tool_groups"]["codebase_mapping"] == {
        "purpose": "Map codebases through the connected agent without provider-specific model subprocesses.",
        "stability": "beta",
        "cost_class": "agent-mediated",
        "tools": [
            "read_codebase_mapping_config",
            "draft_codebase_mapping_config",
            "store_codebase_mapping_config",
            "preview_codebase_mapping",
            "prepare_codebase_mapping",
            "read_codebase_mapping_context",
            "store_codebase_mapping_result",
            "install_codebase_mapping_hook",
        ],
    }
    assert payload["progressive_discovery"]["load_next"]["codebase mapping"] == "prepare_codebase_mapping"
    assert payload["progressive_discovery"]["load_next"]["codebase mapping setup"] == "draft_codebase_mapping_config"


def test_prepare_codebase_mapping_tool_returns_manager_payload(monkeypatch):
    server = load_server_module()
    observed = {}
    expected = {"job": {"job_id": "job-1"}, "error": None}

    def fake_prepare_mapping(**kwargs):
        observed.update(kwargs)
        return expected

    monkeypatch.setattr(server.codebase_mapping_manager, "prepare_mapping", fake_prepare_mapping)

    payload = asyncio.run(
        server.prepare_codebase_mapping(
            project_root="C:/Projects/example_game_0",
            mode="bootstrap",
            domain="gameplay",
            budget_chars=1234,
        )
    )

    assert payload == expected
    assert observed == {
        "project_root": "C:/Projects/example_game_0",
        "mode": "bootstrap",
        "domain": "gameplay",
        "budget_chars": 1234,
    }


def test_read_codebase_mapping_config_tool_returns_manager_payload(monkeypatch):
    server = load_server_module()
    observed = {}
    expected = {"exists": True, "config": {"project_name": "example_game_0"}, "error": None}

    def fake_read_config(**kwargs):
        observed.update(kwargs)
        return expected

    monkeypatch.setattr(server.codebase_mapping_manager, "read_config", fake_read_config)

    payload = asyncio.run(server.read_codebase_mapping_config("C:/Projects/example_game_0"))

    assert payload == expected
    assert observed == {"project_root": "C:/Projects/example_game_0"}


def test_draft_codebase_mapping_config_tool_returns_manager_payload(monkeypatch):
    server = load_server_module()
    observed = {}
    expected = {"config": {"project_name": "example_game_0"}, "receipt": {}, "error": None}

    def fake_draft_config(**kwargs):
        observed.update(kwargs)
        return expected

    monkeypatch.setattr(server.codebase_mapping_manager, "draft_config", fake_draft_config)

    payload = asyncio.run(server.draft_codebase_mapping_config("C:/Projects/example_game_0", project_name="ExampleGame"))

    assert payload == expected
    assert observed == {"project_root": "C:/Projects/example_game_0", "project_name": "ExampleGame"}


def test_store_codebase_mapping_config_tool_returns_manager_payload(monkeypatch):
    server = load_server_module()
    observed = {}
    expected = {"stored": {"config_path": "C:/Projects/example_game_0/.engram/config.json"}, "error": None}
    config = {"project_name": "example_game_0", "domains": {"gameplay": {"file_globs": ["src/**/*.py"]}}}

    def fake_store_config(**kwargs):
        observed.update(kwargs)
        return expected

    monkeypatch.setattr(server.codebase_mapping_manager, "store_config", fake_store_config)

    payload = asyncio.run(server.store_codebase_mapping_config("C:/Projects/example_game_0", config, overwrite=True))

    assert payload == expected
    assert observed == {
        "project_root": "C:/Projects/example_game_0",
        "config": config,
        "overwrite": True,
    }


def test_preview_codebase_mapping_tool_returns_manager_payload(monkeypatch):
    server = load_server_module()
    observed = {}
    expected = {"preview": {"domain_count": 1}, "error": None}

    def fake_preview_mapping(**kwargs):
        observed.update(kwargs)
        return expected

    monkeypatch.setattr(server.codebase_mapping_manager, "preview_mapping", fake_preview_mapping)

    payload = asyncio.run(
        server.preview_codebase_mapping(
            "C:/Projects/example_game_0",
            mode="full",
            domain="gameplay",
            budget_chars=987,
        )
    )

    assert payload == expected
    assert observed == {
        "project_root": "C:/Projects/example_game_0",
        "mode": "full",
        "domain": "gameplay",
        "budget_chars": 987,
    }


def test_install_codebase_mapping_hook_tool_returns_manager_payload(monkeypatch):
    server = load_server_module()
    observed = {}
    expected = {"hook": {"installed": True}, "error": None}

    def fake_install_hook(**kwargs):
        observed.update(kwargs)
        return expected

    monkeypatch.setattr(server.codebase_mapping_manager, "install_hook", fake_install_hook)

    payload = asyncio.run(server.install_codebase_mapping_hook("C:/Projects/example_game_0", overwrite=True))

    assert payload == expected
    assert observed == {"project_root": "C:/Projects/example_game_0", "overwrite": True}


def test_read_codebase_mapping_context_tool_returns_manager_payload(monkeypatch):
    server = load_server_module()
    observed = {}
    expected = {"context": "bounded", "error": None}

    def fake_read_context(job_id, domain, part_index):
        observed["job_id"] = job_id
        observed["domain"] = domain
        observed["part_index"] = part_index
        return expected

    monkeypatch.setattr(server.codebase_mapping_manager, "read_context", fake_read_context)

    payload = asyncio.run(server.read_codebase_mapping_context("job-1", "gameplay", part_index=2))

    assert payload == expected
    assert observed == {"job_id": "job-1", "domain": "gameplay", "part_index": 2}


def test_store_codebase_mapping_result_tool_uses_connected_memory_manager(monkeypatch):
    server = load_server_module()
    observed = {}
    expected = {"stored": {"key": "codebase_example_game_gameplay_architecture"}, "error": None}

    def fake_store_result(**kwargs):
        observed.update(kwargs)
        return expected

    monkeypatch.setattr(server.codebase_mapping_manager, "store_result", fake_store_result)

    payload = asyncio.run(
        server.store_codebase_mapping_result(
            job_id="job-1",
            domain="gameplay",
            content="## Architecture\n\nAgent-authored mapping.",
            force=True,
        )
    )

    assert payload == expected
    assert observed == {
        "job_id": "job-1",
        "domain": "gameplay",
        "content": "## Architecture\n\nAgent-authored mapping.",
        "memory_manager": server.memory_manager,
        "force": True,
    }


def test_search_memories_keeps_bounded_search_when_session_has_no_pins(monkeypatch):
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

    payload = asyncio.run(server.search_memories("alpha", limit=7, session_id="session-a"))

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


def test_list_memories_returns_structured_payload(monkeypatch):
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

    payload = asyncio.run(server.list_memories())

    assert payload == {
        "count": 1,
        "total": 1,
        "limit": 50,
        "offset": 0,
        "has_more": False,
        "memories": expected_memories,
        "error": None,
    }


def test_list_memories_runtime_failure_returns_structured_error(monkeypatch):
    server = load_server_module()

    async def fake_list():
        raise RuntimeError("boom")

    monkeypatch.setattr(server.memory_manager, "list_memories_async", fake_list)

    payload = asyncio.run(server.list_memories())

    assert payload == {
        "count": 0,
        "memories": [],
        "error": {
            "code": "runtime_error",
            "message": "❌ Engram error: boom",
        },
    }


def test_search_memories_blank_query_returns_structured_error(monkeypatch):
    server = load_server_module()

    async def fail_if_called(query: str, limit: int = 5):
        raise AssertionError("search_memories_async should not run for invalid queries")

    monkeypatch.setattr(server.memory_manager, "search_memories_async", fail_if_called)

    payload = asyncio.run(server.search_memories("   "))

    assert payload == {
        "query": "   ",
        "count": 0,
        "results": [],
        "error": {
            "code": "invalid_query",
            "message": "❌ Query cannot be empty.",
        },
    }


def test_search_memories_runtime_failure_returns_structured_error(monkeypatch):
    server = load_server_module()

    async def fake_search(query: str, limit: int = 5):
        raise RuntimeError("boom")

    monkeypatch.setattr(server.memory_manager, "search_memories_async", fake_search)

    payload = asyncio.run(server.search_memories("alpha"))

    assert payload == {
        "query": "alpha",
        "count": 0,
        "results": [],
        "error": {
            "code": "runtime_error",
            "message": "❌ Engram error: boom",
        },
    }


def test_search_memories_empty_results_returns_structured_payload(monkeypatch):
    server = load_server_module()

    async def fake_search(query: str, limit: int = 5):
        return []

    monkeypatch.setattr(server.memory_manager, "search_memories_async", fake_search)

    payload = asyncio.run(server.search_memories("alpha"))

    assert payload == {
        "query": "alpha",
        "count": 0,
        "results": [],
        "error": None,
    }


def test_search_memories_text_renders_payload_from_structured_search(monkeypatch):
    server = load_server_module()

    async def fake_search(query: str, limit: int = 5, session_id=None, pinned_first: bool = False):
        assert query == "alpha"
        assert limit == 5
        assert session_id is None
        assert pinned_first is False
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

    monkeypatch.setattr(server, "search_memories", fake_search)

    rendered = asyncio.run(server.search_memories_text("alpha"))

    assert rendered == (
        "🔍 1 results for 'alpha':\n\n"
        "[score: 0.987] Alpha note\n"
        "  key=alpha-note  chunk_id=0  tags=alpha, ops\n"
        "  snippet: Alpha snippet\n"
    )


def test_search_memories_text_renders_structured_validation_error(monkeypatch):
    server = load_server_module()

    async def fake_search(query: str, limit: int = 5, session_id=None, pinned_first: bool = False):
        return {
            "query": query,
            "count": 0,
            "results": [],
            "error": {
                "code": "invalid_query",
                "message": "❌ Query cannot be empty.",
            },
        }

    monkeypatch.setattr(server, "search_memories", fake_search)

    rendered = asyncio.run(server.search_memories_text("   "))

    assert rendered == "❌ Query cannot be empty."


def test_search_memories_text_renders_structured_runtime_error(monkeypatch):
    server = load_server_module()

    async def fake_search(query: str, limit: int = 5, session_id=None, pinned_first: bool = False):
        return {
            "query": query,
            "count": 0,
            "results": [],
            "error": {
                "code": "runtime_error",
                "message": "❌ Engram error: boom",
            },
        }

    monkeypatch.setattr(server, "search_memories", fake_search)

    rendered = asyncio.run(server.search_memories_text("alpha"))

    assert rendered == "❌ Engram error: boom"


def test_list_all_memories_renders_payload_from_structured_list(monkeypatch):
    server = load_server_module()

    async def fake_list(limit: int = 50, **kwargs):
        assert limit == 0
        return {
            "count": 1,
            "total": 1,
            "limit": 0,
            "offset": 0,
            "has_more": False,
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

    monkeypatch.setattr(server, "list_memories", fake_list)

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


def test_list_all_memories_renders_structured_runtime_error(monkeypatch):
    server = load_server_module()

    async def fake_list(limit: int = 50, **kwargs):
        assert limit == 0
        return {
            "count": 0,
            "total": 0,
            "limit": 0,
            "offset": 0,
            "has_more": False,
            "memories": [],
            "error": {
                "code": "runtime_error",
                "message": "❌ Engram error: boom",
            },
        }

    monkeypatch.setattr(server, "list_memories", fake_list)

    rendered = asyncio.run(server.list_all_memories())

    assert rendered == "❌ Engram error: boom"


def test_retrieve_chunk_text_renders_payload_from_structured_retrieve(monkeypatch):
    server = load_server_module()

    async def fake_retrieve_chunk(key: str, chunk_id: int):
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

    monkeypatch.setattr(server, "retrieve_chunk", fake_retrieve_chunk)

    rendered = asyncio.run(server.retrieve_chunk_text("alpha-note", 0))

    assert rendered == (
        "📄 Chunk 0 from 'Alpha note'\n"
        "🔑 Key: alpha-note\n\n"
        "Alpha chunk"
    )


def test_retrieve_chunk_text_renders_not_found(monkeypatch):
    server = load_server_module()

    async def fake_retrieve_chunk(key: str, chunk_id: int):
        return {
            "key": key,
            "chunk_id": chunk_id,
            "found": False,
            "chunk": None,
            "error": None,
        }

    monkeypatch.setattr(server, "retrieve_chunk", fake_retrieve_chunk)

    rendered = asyncio.run(server.retrieve_chunk_text("missing-note", 9))

    assert rendered == "❌ Chunk not found: key='missing-note' chunk_id=9"


def test_retrieve_chunk_text_renders_runtime_error(monkeypatch):
    server = load_server_module()

    async def fake_retrieve_chunk(key: str, chunk_id: int):
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

    monkeypatch.setattr(server, "retrieve_chunk", fake_retrieve_chunk)

    rendered = asyncio.run(server.retrieve_chunk_text("alpha-note", 0))

    assert rendered == "❌ Engram error: boom"


def test_retrieve_memory_text_renders_payload_from_structured_retrieve(monkeypatch):
    server = load_server_module()

    async def fake_retrieve_memory(key: str):
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

    monkeypatch.setattr(server, "retrieve_memory", fake_retrieve_memory)

    rendered = asyncio.run(server.retrieve_memory_text("alpha-note"))

    assert rendered == (
        "📦 Alpha note\n"
        "🔑 Key: alpha-note\n"
        "🏷  Tags: alpha, ops\n"
        "📅 Updated: 2026-04-20T10:30\n"
        "📊 123 chars | 2 chunks\n\n"
        "Alpha body"
    )


def test_retrieve_memory_text_renders_not_found(monkeypatch):
    server = load_server_module()

    async def fake_retrieve_memory(key: str):
        return {
            "key": key,
            "found": False,
            "memory": None,
            "error": None,
        }

    monkeypatch.setattr(server, "retrieve_memory", fake_retrieve_memory)

    rendered = asyncio.run(server.retrieve_memory_text("missing-note"))

    assert rendered == "❌ Memory not found: 'missing-note'"


def test_retrieve_memory_text_renders_runtime_error(monkeypatch):
    server = load_server_module()

    async def fake_retrieve_memory(key: str):
        return {
            "key": key,
            "found": False,
            "memory": None,
            "error": {
                "code": "runtime_error",
                "message": "❌ Engram error: boom",
            },
        }

    monkeypatch.setattr(server, "retrieve_memory", fake_retrieve_memory)

    rendered = asyncio.run(server.retrieve_memory_text("alpha-note"))

    assert rendered == "❌ Engram error: boom"


def test_retrieve_chunks_returns_structured_batch_payload(monkeypatch):
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

    payload = asyncio.run(server.retrieve_chunks(requests))

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


def test_retrieve_memory_returns_structured_memory_payload(monkeypatch):
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

    payload = asyncio.run(server.retrieve_memory("alpha-note"))

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


def test_retrieve_chunk_not_found_returns_found_false(monkeypatch):
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

    payload = asyncio.run(server.retrieve_chunk("missing-note", 9))

    assert observed == {"requests": [{"key": "missing-note", "chunk_id": 9}]}
    assert payload == {
        "key": "missing-note",
        "chunk_id": 9,
        "found": False,
        "chunk": None,
        "error": None,
    }


def test_retrieve_chunks_preserves_per_item_error_objects(monkeypatch):
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

    payload = asyncio.run(server.retrieve_chunks([{"key": "alpha-note", "chunk_id": True}]))

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


def test_add_graph_edge_returns_structured_payload(monkeypatch):
    server = load_server_module()

    def fake_add_edge(**kwargs):
        return {
            "edge_id": "sha256:abc",
            "from_ref": kwargs["from_ref"],
            "to_ref": kwargs["to_ref"],
            "edge_type": kwargs["edge_type"],
            "confidence": kwargs.get("confidence", 1.0),
            "evidence": kwargs.get("evidence", ""),
            "source": kwargs.get("source", "manual"),
            "status": "active",
            "created_by": kwargs.get("created_by", "agent"),
            "created_at": "2026-04-27T00:00:00-07:00",
            "updated_at": "2026-04-27T00:00:00-07:00",
        }

    monkeypatch.setattr(server.graph_manager, "add_edge", fake_add_edge)

    payload = asyncio.run(
        server.add_graph_edge(
            from_ref={"kind": "memory", "key": "alpha"},
            to_ref={"kind": "memory", "key": "beta"},
            edge_type="supports",
            evidence="Alpha supports beta.",
        )
    )

    assert payload["edge"]["edge_id"] == "sha256:abc"
    assert payload["error"] is None


def test_impact_scan_mcp_never_returns_memory_content(monkeypatch):
    server = load_server_module()

    def fake_impact_scan(root_ref, max_hops=1, edge_types=None):
        return {
            "root_ref": root_ref,
            "count": 1,
            "edges": [
                {
                    "edge_id": "sha256:abc",
                    "from_ref": root_ref,
                    "to_ref": {"kind": "memory", "key": "beta"},
                    "edge_type": "depends_on",
                    "evidence": "Relationship only.",
                }
            ],
            "error": None,
        }

    monkeypatch.setattr(server.graph_manager, "impact_scan", fake_impact_scan)

    payload = asyncio.run(server.impact_scan({"kind": "memory", "key": "alpha"}))

    assert payload["count"] == 1
    assert "content" not in payload["edges"][0]


def test_prepare_source_memory_tool_returns_draft(monkeypatch):
    server = load_server_module()

    def fake_prepare_source_memory(**kwargs):
        return {
            "draft_id": "sha256:abc",
            "status": "draft",
            "source_type": kwargs["source_type"],
            "proposed_memories": [{"key": "source_draft", "content": "body"}],
            "proposed_edges": [],
            "receipt": {"input_chars": len(kwargs["source_text"]), "proposed_memory_count": 1},
        }

    monkeypatch.setattr(server.source_intake_manager, "prepare_source_memory", fake_prepare_source_memory)

    payload = asyncio.run(
        server.prepare_source_memory(
            source_text="Decision: Keep JSON first.",
            source_type="transcript",
            project="C:/Dev/Engram",
        )
    )

    assert payload["draft"]["draft_id"] == "sha256:abc"
    assert payload["error"] is None


def test_review_helper_tools_return_agent_facing_payloads(tmp_path):
    server = load_server_module()
    source = tmp_path / "note.md"
    source.write_text("# Note\n\nDecision: Keep connector previews no-write.", encoding="utf-8")

    pipelines = asyncio.run(server.list_ingestion_pipelines())
    chunk_preview = asyncio.run(server.preview_memory_chunks("# A\n\nBody", title="A"))
    connector_preview = asyncio.run(
        server.preview_source_connector(
            connector_type="local_path",
            target=str(source),
            include_globs=["*.md"],
            max_files=5,
        )
    )
    workflows = asyncio.run(server.list_workflow_templates())

    assert "transcript" in pipelines["pipelines"]
    assert chunk_preview["receipt"]["write_performed"] is False
    assert connector_preview["write_performed"] is False
    assert connector_preview["items"][0]["draft_arguments"]["source_type"] == "local_path"
    assert any(template["id"] == "resume_repo" for template in workflows["templates"])


def test_retrieval_eval_tool_delegates_to_eval_runner(monkeypatch):
    server = load_server_module()
    observed = {}

    def fake_run_retrieval_eval(manager):
        observed["manager"] = manager
        return {"summary": {"passed": True}, "error": None}

    monkeypatch.setattr(server, "run_retrieval_eval", fake_run_retrieval_eval)

    payload = asyncio.run(server.retrieval_eval())

    assert observed["manager"] is server.memory_manager
    assert payload == {"summary": {"passed": True}, "error": None}


def test_store_prepared_memory_uses_explicit_selected_items(monkeypatch):
    server = load_server_module()
    observed: dict[str, object] = {}

    def fake_get_source_draft(draft_id):
        return {
            "draft_id": draft_id,
            "status": "draft",
            "proposed_memories": [
                {
                    "key": "draft_memory",
                    "title": "Draft Memory",
                    "content": "Draft body",
                    "tags": ["source"],
                    "project": "C:/Dev/Engram",
                    "domain": "product-roadmap",
                    "status": "draft",
                    "canonical": False,
                }
            ],
        }

    async def fake_store_memory(**kwargs):
        observed.update(kwargs)
        return {"title": kwargs["title"], "chars": len(kwargs["content"]), "chunk_count": 1}

    monkeypatch.setattr(server.source_intake_manager, "get_source_draft", fake_get_source_draft)
    monkeypatch.setattr(server.memory_manager, "store_memory_async", fake_store_memory)

    payload = asyncio.run(server.store_prepared_memory("draft-a", selected_items=[0]))

    assert payload["stored_count"] == 1
    assert observed["key"] == "draft_memory"
    assert observed["force"] is False


def test_context_pack_returns_receipt_and_citations(monkeypatch):
    server = load_server_module()
    observed_search_kwargs = {}

    async def fake_search_memories(*args, **kwargs):
        observed_search_kwargs.update(kwargs)
        return {
            "query": "agent",
            "count": 1,
            "results": [
                {
                    "key": "alpha",
                    "chunk_id": 0,
                    "title": "Alpha",
                    "score": 0.9,
                    "snippet": "snippet",
                    "tags": [],
                    "explanation": "semantic score 0.9",
                    "retrieval_mode": "hybrid",
                    "semantic_score": 0.8,
                    "lexical_score": 0.2,
                }
            ],
            "error": None,
        }

    async def fake_retrieve_chunks(requests):
        return {
            "requested_count": len(requests),
            "found_count": 1,
            "results": [
                {
                    "key": "alpha",
                    "chunk_id": 0,
                    "found": True,
                    "chunk": {
                        "title": "Alpha",
                        "text": "alpha body",
                        "section_title": "Alpha",
                        "heading_path": ["Alpha"],
                        "chunk_kind": "section",
                    },
                    "error": None,
                }
            ],
            "error": None,
        }

    monkeypatch.setattr(server, "search_memories", fake_search_memories)
    monkeypatch.setattr(server, "retrieve_chunks", fake_retrieve_chunks)

    payload = asyncio.run(server.context_pack("agent", project="C:/Dev/Engram", retrieval_mode="hybrid"))

    assert observed_search_kwargs["retrieval_mode"] == "hybrid"
    assert payload["receipt"]["semantic_candidate_count"] == 1
    assert payload["receipt"]["selected_chunk_count"] == 1
    assert payload["receipt"]["budget_chars"] == 6000
    assert payload["receipt"]["citation_count"] == 1
    assert payload["citations"] == [
        {
            "citation_id": "engram:alpha#0",
            "source": "memory",
            "key": "alpha",
            "chunk_id": 0,
            "title": "Alpha",
            "section_title": "Alpha",
            "retrieval_mode": "hybrid",
            "score": 0.9,
            "semantic_score": 0.8,
            "lexical_score": 0.2,
            "snippet": "snippet",
        }
    ]
    assert payload["chunks"][0]["citation"]["citation_id"] == "engram:alpha#0"


def test_context_pack_records_privacy_safe_usage(isolated_usage_meter, monkeypatch):
    server = load_server_module()
    monkeypatch.setattr(server, "usage_meter", isolated_usage_meter.usage_meter)

    async def fake_search_memories(*args, **kwargs):
        return {
            "query": "agent",
            "count": 1,
            "results": [
                {
                    "key": "alpha",
                    "chunk_id": 0,
                    "title": "Alpha",
                    "score": 0.9,
                    "snippet": "short",
                    "tags": [],
                }
            ],
            "error": None,
        }

    async def fake_retrieve_chunks(requests):
        return {
            "requested_count": len(requests),
            "found_count": 1,
            "results": [
                {
                    "key": "alpha",
                    "chunk_id": 0,
                    "found": True,
                    "chunk": {
                        "title": "Alpha",
                        "text": "full retrieved context body",
                        "section_title": None,
                        "heading_path": [],
                        "chunk_kind": "body",
                    },
                    "error": None,
                }
            ],
            "error": None,
        }

    monkeypatch.setattr(server, "search_memories", fake_search_memories)
    monkeypatch.setattr(server, "retrieve_chunks", fake_retrieve_chunks)

    payload = asyncio.run(server.context_pack("agent", project="C:/Dev/Engram"))
    calls = isolated_usage_meter.usage_meter.list_calls(limit=10)["calls"]
    serialized = json.dumps(calls)

    assert payload["count"] == 1
    assert calls[0]["tool"] == "context_pack"
    assert calls[0]["memory_refs"] == [{"key": "alpha", "chunk_id": 0}]
    assert "full retrieved context body" not in serialized


def test_usage_tools_delegate_to_usage_meter(isolated_usage_meter, monkeypatch):
    server = load_server_module()
    monkeypatch.setattr(server, "usage_meter", isolated_usage_meter.usage_meter)
    isolated_usage_meter.usage_meter.record_tool_call(
        tool="search_memories",
        input_payload={"query": "agent"},
        output_payload=[{"key": "alpha", "snippet": "short"}],
        status="ok",
        duration_ms=3,
    )

    summary = asyncio.run(server.usage_summary(days=99))
    calls = asyncio.run(server.list_usage_calls(limit=5))

    assert summary["days"] == 90
    assert summary["total_calls"] == 1
    assert calls["count"] == 1
    assert calls["calls"][0]["tool"] == "search_memories"


def test_prepare_source_memory_records_operation_job_and_event(monkeypatch):
    server = load_server_module()
    observed: dict[str, list[dict]] = {"jobs": [], "events": []}

    class FakeOperationLog:
        def record_job(self, **kwargs):
            observed["jobs"].append(kwargs)
            return {"job_id": "sha256:job", **kwargs}

        def record_event(self, **kwargs):
            observed["events"].append(kwargs)
            return {"event_id": "sha256:event", **kwargs}

    def fake_prepare_source_memory(**kwargs):
        return {
            "draft_id": "sha256:abc",
            "status": "draft",
            "source_type": kwargs["source_type"],
            "proposed_memories": [{"key": "source_draft", "content": "body"}],
            "proposed_edges": [],
        }

    monkeypatch.setattr(server, "operation_log", FakeOperationLog())
    monkeypatch.setattr(server.source_intake_manager, "prepare_source_memory", fake_prepare_source_memory)

    payload = asyncio.run(
        server.prepare_source_memory(
            source_text="Decision: Keep JSON first.",
            source_type="transcript",
            project="C:/Dev/Engram",
        )
    )

    assert payload["draft"]["draft_id"] == "sha256:abc"
    assert observed["jobs"][0]["operation_type"] == "source_intake"
    assert observed["jobs"][0]["status"] == "completed"
    assert observed["events"][0]["event_type"] == "source_draft_ready"
    assert observed["events"][0]["subject"] == {"kind": "source_draft", "draft_id": "sha256:abc"}


def test_audit_graph_records_operation_job_and_event(monkeypatch):
    server = load_server_module()
    observed: dict[str, list[dict]] = {"jobs": [], "events": []}

    class FakeOperationLog:
        def record_job(self, **kwargs):
            observed["jobs"].append(kwargs)
            return {"job_id": "sha256:job", **kwargs}

        def record_event(self, **kwargs):
            observed["events"].append(kwargs)
            return {"event_id": "sha256:event", **kwargs}

    monkeypatch.setattr(server, "operation_log", FakeOperationLog())
    monkeypatch.setattr(server.graph_manager, "audit_graph", lambda: {"issue_count": 0, "issues": [], "error": None})

    payload = asyncio.run(server.audit_graph())

    assert payload["issue_count"] == 0
    assert observed["jobs"][0]["operation_type"] == "graph_audit"
    assert observed["jobs"][0]["status"] == "completed"
    assert observed["events"][0]["event_type"] == "graph_audit_completed"


def test_operation_tools_delegate_and_record_usage(
    isolated_operation_log,
    isolated_usage_meter,
    monkeypatch,
):
    server = load_server_module()
    monkeypatch.setattr(server, "operation_log", isolated_operation_log.operation_log)
    monkeypatch.setattr(server, "usage_meter", isolated_usage_meter.usage_meter)
    isolated_operation_log.operation_log.record_event(
        event_type="source_draft_ready",
        subject={"kind": "source_draft", "draft_id": "sha256:abc"},
        summary="Ready.",
    )

    jobs = asyncio.run(server.list_operation_jobs(limit=5))
    events = asyncio.run(server.list_operation_events(event_type="source_draft_ready", limit=5))
    calls = isolated_usage_meter.usage_meter.list_calls(limit=5)["calls"]

    assert jobs["count"] == 0
    assert events["count"] == 1
    assert [call["tool"] for call in calls] == ["list_operation_events", "list_operation_jobs"]


def test_session_pin_store_remove_key_clears_stale_pins_across_sessions(tmp_path):
    store = SessionPinStore(tmp_path / "session_pins.json")
    store.pin("session-a", "alpha-note")
    store.pin("session-a", "beta-note")
    store.pin("session-b", "alpha-note")

    removed = store.remove_key("alpha-note")

    assert removed == 2
    assert store.list_pins("session-a") == ["beta-note"]
    assert store.list_pins("session-b") == []
