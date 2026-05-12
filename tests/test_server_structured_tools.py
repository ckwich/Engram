from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

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


def _write_legacy_memory(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_migration_dry_run_tool_returns_compact_no_write_report(tmp_path):
    server = load_server_module()
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    _write_legacy_memory(
        legacy_dir / "alpha.json",
        {
            "key": "alpha",
            "title": "Alpha",
            "content": "Alpha content",
            "related_to": ["beta"],
            "chunk_count": 1,
            "potentially_stale": True,
            "stale_reason": "source files changed",
            "stale_flagged_at": "2026-05-11T17:31:36.231238-07:00",
        },
    )

    payload = asyncio.run(server.migration_dry_run(str(legacy_dir)))

    assert payload["schema_version"] == "2026-05-11.memory_os_migration.v8"
    assert payload["operation"] == "migration_dry_run"
    assert payload["write_performed"] is False
    assert payload["active_memory_write_performed"] is False
    assert payload["source_count"] == 1
    assert payload["valid_count"] == 1
    assert payload["would_import_count"] == 1
    assert payload["derived_chunk_count_total"] == 1
    assert payload["related_to_count"] == 1
    assert payload["unsupported_field_count"] == 0
    assert payload["chunk_count_mismatch_count"] == 0
    assert "key_set" not in payload
    assert "artifact_hashes" not in payload
    assert payload["error"] is None


def test_memory_os_round_trip_check_tool_writes_only_migration_artifacts(tmp_path):
    server = load_server_module()
    legacy_dir = tmp_path / "legacy"
    work_root = tmp_path / "migration-work"
    legacy_dir.mkdir()
    _write_legacy_memory(
        legacy_dir / "alpha.json",
        {"key": "alpha", "title": "Alpha", "content": "Alpha content", "chunk_count": 1},
    )

    payload = asyncio.run(
        server.memory_os_round_trip_check(
            legacy_dir=str(legacy_dir),
            work_root=str(work_root),
        )
    )

    assert payload["schema_version"] == "2026-05-11.memory_os_migration.v8"
    assert payload["operation"] == "memory_os_round_trip_check"
    assert payload["status"] == "pass"
    assert payload["write_performed"] is True
    assert payload["active_memory_write_performed"] is False
    assert payload["source_count"] == 1
    assert payload["restored_count"] == 1
    assert payload["parity"] == {"key_sets_match": True, "count_parity": True}
    assert (work_root / "store" / "ledger.sqlite3").exists()
    assert payload["error"] is None


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


def test_search_memories_chroma_owner_failure_returns_structured_error(monkeypatch):
    server = load_server_module()

    async def fake_embed_async(query: str):
        return [0.1, 0.2, 0.3]

    def unavailable_query(*args, **kwargs):
        raise RuntimeError(
            "ChromaDB is owned by another Engram process; "
            "using JSON-first fallback in this process."
        )

    monkeypatch.setattr(server.embedder, "embed_async", fake_embed_async)
    monkeypatch.setattr(server.memory_manager, "_query_semantic_results", unavailable_query)

    payload = asyncio.run(server.search_memories("alpha"))

    assert payload == {
        "query": "alpha",
        "count": 0,
        "results": [],
        "error": {
            "code": "runtime_error",
            "message": (
                "❌ Engram error: ChromaDB is owned by another Engram process; "
                "using JSON-first fallback in this process."
            ),
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


def test_conflict_scan_mcp_returns_conflict_edges_only(monkeypatch):
    server = load_server_module()

    def fake_conflict_scan(ref=None, status="active"):
        return {
            "schema_version": "2026-04-27.conflict-scan.v1",
            "ref": ref,
            "status": status,
            "count": 1,
            "conflicts": [
                {
                    "edge_id": "sha256:abc",
                    "from_ref": {"kind": "memory", "key": "new_decision"},
                    "to_ref": {"kind": "memory", "key": "old_decision"},
                    "edge_type": "supersedes",
                    "evidence": "New decision supersedes old decision.",
                }
            ],
            "error": None,
        }

    monkeypatch.setattr(server.graph_manager, "conflict_scan", fake_conflict_scan)

    payload = asyncio.run(server.conflict_scan(ref={"kind": "memory", "key": "new_decision"}))

    assert payload["count"] == 1
    assert payload["conflicts"][0]["edge_type"] == "supersedes"
    assert "content" not in payload["conflicts"][0]
    assert payload["error"] is None


def test_conflict_scan_mcp_returns_structured_invalid_request(monkeypatch):
    server = load_server_module()

    def fake_conflict_scan(ref=None, status="active"):
        raise ValueError("ref.kind is required")

    monkeypatch.setattr(server.graph_manager, "conflict_scan", fake_conflict_scan)

    payload = asyncio.run(server.conflict_scan(ref={"key": "missing-kind"}))

    assert payload["count"] == 0
    assert payload["conflicts"] == []
    assert payload["error"]["code"] == "invalid_request"


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


def test_prepare_source_memory_tool_catches_unexpected_intake_failure(monkeypatch):
    server = load_server_module()

    def fake_prepare_source_memory(**kwargs):
        raise TypeError("bad source shape")

    monkeypatch.setattr(server.source_intake_manager, "prepare_source_memory", fake_prepare_source_memory)

    payload = asyncio.run(
        server.prepare_source_memory(
            source_text="Decision: Keep JSON first.",
            source_type="transcript",
            project="C:/Dev/Engram",
        )
    )

    assert payload == {
        "draft": None,
        "error": {
            "code": "runtime_error",
            "message": "Unexpected source intake failure: bad source shape",
        },
    }


def test_prepare_source_memory_tool_returns_structured_invalid_request_for_malformed_agent_args():
    server = load_server_module()

    payload = asyncio.run(
        server.prepare_source_memory(
            source_text={"bad": "shape"},
            source_type="transcript",
            project="C:/Dev/Engram",
        )
    )

    assert payload == {
        "draft": None,
        "error": {
            "code": "invalid_request",
            "message": "source_text is required",
        },
    }


def test_preview_document_extraction_tool_returns_no_write_preview():
    server = load_server_module()

    payload = asyncio.run(
        server.preview_document_extraction(
            title="Architecture Note",
            source_uri="file:///notes/architecture.md",
            source_type="markdown",
            media_type="text/markdown",
            content="# Architecture\n\nDecision: keep visual evidence review-first.",
            metadata={"project": "engram"},
        )
    )

    assert payload["error"] is None
    assert payload["preview"]["write_performed"] is False
    assert payload["preview"]["active_memory_write_performed"] is False
    assert payload["preview"]["document_record"]["title"] == "Architecture Note"
    assert payload["preview"]["receipt"]["chunk_count"] >= 1


def test_preview_document_extraction_tool_returns_structured_invalid_request():
    server = load_server_module()

    payload = asyncio.run(
        server.preview_document_extraction(
            title="Blank",
            source_uri="file:///notes/blank.md",
            source_type="markdown",
            media_type="text/markdown",
            content="   ",
        )
    )

    assert payload == {
        "preview": None,
        "error": {
            "code": "invalid_request",
            "message": "content is required",
        },
    }


def test_preview_document_source_connector_tool_returns_document_arguments(tmp_path):
    server = load_server_module()
    note = tmp_path / "architecture.md"
    note.write_text("# Architecture\n\nDecision: Keep imports reviewable.", encoding="utf-8")

    payload = asyncio.run(
        server.preview_document_source_connector(
            connector_type="local_path",
            target=str(note),
            include_globs=["*.md"],
            metadata={"project": "Engram"},
        )
    )

    assert payload["error"] is None
    assert payload["count"] == 1
    assert payload["write_performed"] is False
    assert payload["items"][0]["document_extraction_arguments"]["source_type"] == "markdown"
    assert payload["items"][0]["document_extraction_arguments"]["metadata"]["project"] == "Engram"


def test_preview_document_source_connector_tool_returns_url_fetch_request():
    server = load_server_module()

    payload = asyncio.run(
        server.preview_document_source_connector(
            connector_type="url",
            target="https://example.com/docs/overview",
        )
    )

    assert payload["error"] is None
    assert payload["connector_type"] == "url"
    assert payload["omitted"][0]["reason"] == "external_fetch_required"
    assert payload["omitted"][0]["document_extraction_request_arguments"]["source_type"] == "url"


def test_preview_document_source_connector_tool_returns_structured_invalid_request():
    server = load_server_module()

    payload = asyncio.run(
        server.preview_document_source_connector(
            connector_type="unsupported",
            target="missing",
        )
    )

    assert payload == {
        "connector_type": "unsupported",
        "target": "missing",
        "count": 0,
        "items": [],
        "omitted": [],
        "write_performed": False,
        "error": {
            "code": "invalid_request",
            "message": "Only connector_type='local_path' or 'url' is currently supported.",
        },
    }


def test_list_document_extractors_tool_returns_no_write_catalog():
    server = load_server_module()

    payload = asyncio.run(server.list_document_extractors())

    assert payload["error"] is None
    assert payload["catalog"]["write_performed"] is False
    assert any(
        extractor["id"] == "external-ocr-vision"
        and extractor["external_framework_required"] is True
        for extractor in payload["catalog"]["extractors"]
    )


def test_prepare_document_extraction_request_tool_returns_no_write_request():
    server = load_server_module()

    payload = asyncio.run(
        server.prepare_document_extraction_request(
            source_ref={"source_uri": "file:///docs/architecture.pdf"},
            source_type="pdf",
            requested_outputs=["markdown", "page_images"],
            extractor_id="local-pdf-extractor",
            extractor_kind="external_document",
            instructions="Extract text and page images.",
        )
    )

    assert payload["error"] is None
    assert payload["request"]["record_type"] == "document_extraction_request"
    assert payload["request"]["write_performed"] is False
    assert payload["request"]["requested_outputs"] == ["markdown", "page_images"]


def test_prepare_document_extraction_request_tool_returns_structured_invalid_request():
    server = load_server_module()

    payload = asyncio.run(
        server.prepare_document_extraction_request(
            source_ref={},
            source_type="pdf",
            requested_outputs=["markdown"],
            extractor_id="local-pdf-extractor",
            extractor_kind="external_document",
        )
    )

    assert payload == {
        "request": None,
        "error": {
            "code": "invalid_request",
            "message": "source_ref is required",
        },
    }


def test_prepare_document_extraction_result_tool_returns_no_write_result():
    server = load_server_module()
    request = asyncio.run(
        server.prepare_document_extraction_request(
            source_ref={"source_uri": "file:///docs/architecture.pdf"},
            source_type="pdf",
            requested_outputs=["markdown", "page_images"],
            extractor_id="local-pdf-extractor",
            extractor_kind="external_document",
        )
    )["request"]

    payload = asyncio.run(
        server.prepare_document_extraction_result(
            extraction_request=request,
            title="Architecture Scan",
            content="# Architecture\n\nDecision: Review extraction output.",
            media_type="text/markdown",
            metadata={"project": "Engram"},
            image_refs=[{"source_uri": "file:///docs/architecture.pdf", "page": 1}],
            requested_visual_capabilities=["ocr_text"],
        )
    )

    assert payload["error"] is None
    assert payload["result"]["record_type"] == "document_extraction_result"
    assert payload["result"]["write_performed"] is False
    assert payload["result"]["requires_visual_review"] is True
    assert payload["result"]["visual_extraction_request_arguments"]["requested_capabilities"] == ["ocr_text"]


def test_prepare_document_extraction_result_tool_returns_structured_invalid_request():
    server = load_server_module()

    payload = asyncio.run(
        server.prepare_document_extraction_result(
            extraction_request={},
            title="Architecture Scan",
            content="# Architecture",
            media_type="text/markdown",
        )
    )

    assert payload == {
        "result": None,
        "error": {
            "code": "invalid_request",
            "message": "extraction_request.request_id is required",
        },
    }


def test_prepare_visual_extraction_request_tool_returns_no_write_request():
    server = load_server_module()
    document = {
        "document_id": "doc_architecture",
        "title": "Architecture Screenshot",
        "source_uri": "file:///notes/architecture.png",
    }

    payload = asyncio.run(
        server.prepare_visual_extraction_request(
            document_record=document,
            image_refs=[{"source_uri": "file:///notes/architecture.png", "page": 1}],
            requested_capabilities=["ocr_text", "diagram_description"],
            extractor_id="local-vision-v1",
            extractor_kind="ocr_vision",
            instructions="Read labels and summarize the diagram.",
        )
    )

    assert payload["error"] is None
    assert payload["request"]["record_type"] == "visual_extraction_request"
    assert payload["request"]["active_memory_write_performed"] is False
    assert payload["request"]["extractor"]["external_framework_required"] is True
    assert payload["request"]["requested_capabilities"] == ["diagram_description", "ocr_text"]


def test_prepare_visual_extraction_request_tool_returns_structured_invalid_request():
    server = load_server_module()

    payload = asyncio.run(
        server.prepare_visual_extraction_request(
            document_record={"document_id": "doc_architecture"},
            image_refs=[],
            requested_capabilities=["ocr_text"],
            extractor_id="local-vision-v1",
            extractor_kind="ocr",
        )
    )

    assert payload == {
        "request": None,
        "error": {
            "code": "invalid_request",
            "message": "image_refs must include at least one item",
        },
    }


def test_prepare_document_draft_tool_returns_no_write_draft():
    server = load_server_module()
    document = {
        "document_id": "doc_architecture",
        "title": "Architecture Note",
        "source_uri": "file:///notes/architecture.md",
        "source_type": "markdown",
        "metadata": {"project": "Engram"},
    }

    payload = asyncio.run(
        server.prepare_document_draft(
            document_record=document,
            analysis={
                "summary": "Architecture note about review-first import.",
                "decisions": ["Keep document drafts reviewable."],
            },
            chunk_refs=[{"document_id": "doc_architecture", "chunk_id": 0}],
            visual_artifacts=[],
            candidate_graph_edges=[],
            created_by="agent",
        )
    )

    assert payload["error"] is None
    assert payload["draft"]["record_type"] == "document_draft"
    assert payload["draft"]["active_memory_write_performed"] is False
    assert payload["draft"]["proposed_memories"][0]["status"] == "draft"
    assert payload["draft"]["receipt"]["proposed_memory_count"] == 1


def test_prepare_document_draft_tool_returns_structured_invalid_request():
    server = load_server_module()

    payload = asyncio.run(
        server.prepare_document_draft(
            document_record={"document_id": "doc_architecture"},
            analysis={},
        )
    )

    assert payload == {
        "draft": None,
        "error": {
            "code": "invalid_request",
            "message": "analysis or candidate_graph_edges must include at least one item",
        },
    }


def test_prepare_document_promotion_transaction_tool_returns_no_write_plan():
    server = load_server_module()
    draft = {
        "draft_id": "doc_draft_architecture",
        "document_id": "doc_architecture",
        "record_type": "document_draft",
        "proposed_memories": [
            {
                "key": "engram_architecture_note",
                "title": "Architecture Note",
                "content": "Reviewed document fact.",
                "tags": ["document-intelligence"],
                "status": "draft",
                "canonical": False,
            }
        ],
        "proposed_edges": [],
        "active_memory_write_performed": False,
    }

    payload = asyncio.run(
        server.prepare_document_promotion_transaction(
            document_draft=draft,
            selected_memory_indexes=[0],
            selected_edge_indexes=[],
            approved_by="agent-review",
        )
    )

    assert payload["error"] is None
    assert payload["transaction"]["record_type"] == "document_promotion_transaction"
    assert payload["transaction"]["write_performed"] is False
    assert payload["transaction"]["operations"][0]["tool"] == "write_memory"
    assert payload["transaction"]["operations"][0]["payload"]["status"] == "active"


def test_prepare_document_promotion_transaction_tool_returns_structured_invalid_request():
    server = load_server_module()

    payload = asyncio.run(
        server.prepare_document_promotion_transaction(
            document_draft={"draft_id": "doc_draft_architecture", "proposed_memories": []},
            approved_by="",
        )
    )

    assert payload == {
        "transaction": None,
        "error": {
            "code": "invalid_request",
            "message": "approved_by is required",
        },
    }


def test_preview_visual_extraction_tool_returns_no_write_preview():
    server = load_server_module()

    payload = asyncio.run(
        server.preview_visual_extraction(
            document_record={
                "document_id": "doc_architecture",
                "title": "Architecture Screenshot",
                "source_uri": "file:///notes/architecture.png",
            },
            observations=[
                {
                    "artifact_type": "diagram",
                    "source_ref": {"source_uri": "file:///notes/architecture.png", "page": 1},
                    "description": "A pipeline diagram showing OCR evidence flowing into reviewed chunks.",
                    "confidence": 0.82,
                }
            ],
            extractor_id="agent-vision-preview",
            extractor_kind="vision",
        )
    )

    assert payload["error"] is None
    assert payload["preview"]["write_performed"] is False
    assert payload["preview"]["active_memory_write_performed"] is False
    assert payload["preview"]["receipt"]["external_framework_required"] is True
    assert payload["preview"]["visual_artifacts"][0]["trusted_memory"] is False


def test_preview_visual_extraction_tool_returns_structured_invalid_request():
    server = load_server_module()

    payload = asyncio.run(
        server.preview_visual_extraction(
            document_record={"document_id": "doc_architecture"},
            observations=[],
            extractor_id="agent-vision-preview",
            extractor_kind="vision",
        )
    )

    assert payload == {
        "preview": None,
        "error": {
            "code": "invalid_request",
            "message": "observations must include at least one item",
        },
    }


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


def test_store_prepared_memory_rejects_rejected_drafts(monkeypatch):
    server = load_server_module()

    def fake_get_source_draft(draft_id):
        return {
            "draft_id": draft_id,
            "status": "rejected",
            "proposed_memories": [
                {
                    "key": "draft_memory",
                    "title": "Draft Memory",
                    "content": "Draft body",
                }
            ],
        }

    async def fail_if_store_memory(**kwargs):
        raise AssertionError("rejected drafts must not be promoted")

    monkeypatch.setattr(server.source_intake_manager, "get_source_draft", fake_get_source_draft)
    monkeypatch.setattr(server.memory_manager, "store_memory_async", fail_if_store_memory)

    payload = asyncio.run(server.store_prepared_memory("draft-a", selected_items=[0]))

    assert payload == {
        "stored_count": 0,
        "stored": [],
        "skipped": [],
        "error": {
            "code": "invalid_state",
            "message": "source draft is rejected and cannot be promoted",
        },
    }


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


def test_context_pack_chroma_owner_failure_returns_structured_error(monkeypatch):
    server = load_server_module()

    async def fake_embed_async(query: str):
        return [0.1, 0.2, 0.3]

    def unavailable_query(*args, **kwargs):
        raise RuntimeError(
            "ChromaDB is owned by another Engram process; "
            "using JSON-first fallback in this process."
        )

    monkeypatch.setattr(server.embedder, "embed_async", fake_embed_async)
    monkeypatch.setattr(server.memory_manager, "_query_structured_semantic_results", unavailable_query)

    payload = asyncio.run(server.context_pack("agent"))

    assert payload["count"] == 0
    assert payload["chunks"] == []
    assert payload["error"] == {
        "code": "runtime_error",
        "message": (
            "❌ Engram error: ChromaDB is owned by another Engram process; "
            "using JSON-first fallback in this process."
        ),
    }
    assert payload["receipt"]["semantic_candidate_count"] == 0


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


def test_list_context_profiles_returns_no_write_catalog():
    server = load_server_module()

    payload = asyncio.run(server.list_context_profiles())

    assert payload["write_performed"] is False
    assert payload["profiles"]["repo_resume"]["use_graph"] is True
    assert payload["profiles"]["document_review"]["retrieval_mode"] == "hybrid"
    assert payload["error"] is None


def test_audit_memory_quality_returns_metadata_only_report(monkeypatch):
    server = load_server_module()

    async def fake_list_memories():
        return [
            {
                "key": "quality_note",
                "title": "Quality note",
                "project": "C:/Dev/Engram",
                "domain": None,
                "tags": [],
                "status": "active",
                "canonical": False,
                "chars": 500,
                "chunk_count": 1,
            },
            {
                "key": "other_project",
                "title": "Other project",
                "project": "Other",
                "domain": None,
                "tags": [],
                "status": "active",
                "canonical": False,
                "chars": 500,
                "chunk_count": 1,
            },
        ]

    monkeypatch.setattr(server.memory_manager, "list_memories_async", fake_list_memories)

    payload = asyncio.run(server.audit_memory_quality(project="C:/Dev/Engram"))

    assert payload["count"] == 1
    assert payload["memories"][0]["key"] == "quality_note"
    assert payload["memories"][0]["issues"][0]["code"] == "missing_domain"
    assert "content" not in payload["memories"][0]
    assert payload["error"] is None


def test_prepare_context_uses_profile_defaults_and_returns_context_packet(monkeypatch):
    server = load_server_module()
    observed: dict[str, object] = {}

    async def fake_context_pack(query: str, **kwargs):
        observed["query"] = query
        observed["kwargs"] = kwargs
        return {
            "query": query,
            "count": 1,
            "chunks": [
                {
                    "key": "engram_rebuild_checkpoint",
                    "chunk_id": 0,
                    "title": "Engram rebuild checkpoint",
                    "text": "Use the context compiler next.",
                    "citation": {"citation_id": "engram:engram_rebuild_checkpoint#0"},
                }
            ],
            "citations": [{"citation_id": "engram:engram_rebuild_checkpoint#0"}],
            "omitted": [],
            "budget_chars": kwargs["budget_chars"],
            "used_chars": 30,
            "receipt": {
                "semantic_candidate_count": 2,
                "graph_candidate_count": 1,
                "selected_chunk_count": 1,
                "omitted_count": 0,
                "stale_policy": "excluded",
            },
            "error": None,
        }

    monkeypatch.setattr(server, "context_pack", fake_context_pack)

    payload = asyncio.run(
        server.prepare_context(
            task="resume Engram rebuild",
            project="C:/Dev/Engram",
            profile="repo_resume",
        )
    )

    assert "resume Engram rebuild" in observed["query"]
    assert "handoff" in observed["query"]
    assert observed["kwargs"]["max_chunks"] == 8
    assert observed["kwargs"]["budget_chars"] == 10000
    assert observed["kwargs"]["use_graph"] is True
    assert payload["packet"]["profile"]["id"] == "repo_resume"
    assert payload["packet"]["context"]["chunks"][0]["key"] == "engram_rebuild_checkpoint"
    assert payload["packet"]["write_performed"] is False
    assert payload["error"] is None


def test_prepare_context_warns_about_graph_conflicts_for_selected_refs(monkeypatch):
    server = load_server_module()
    scanned_refs: list[tuple[dict[str, str], str]] = []

    async def fake_context_pack(query: str, **kwargs):
        return {
            "query": query,
            "count": 1,
            "chunks": [
                {
                    "key": "current_decision",
                    "chunk_id": 0,
                    "title": "Current Decision",
                    "text": "Use the Memory OS workflow packet contract.",
                }
            ],
            "citations": [],
            "omitted": [],
            "budget_chars": kwargs["budget_chars"],
            "used_chars": 43,
            "receipt": {
                "semantic_candidate_count": 1,
                "graph_candidate_count": 0,
                "selected_chunk_count": 1,
                "omitted_count": 0,
                "stale_policy": "included",
            },
            "error": None,
        }

    def fake_conflict_scan(*, ref=None, status="active"):
        scanned_refs.append((ref, status))
        return {
            "schema_version": "2026-04-30.graph.v1.conflict-scan.v1",
            "ref": ref,
            "status": status,
            "edge_types": ["contradicts", "invalidates", "supersedes"],
            "count": 1,
            "conflicts": [{"edge_type": "supersedes"}],
            "error": None,
        }

    monkeypatch.setattr(server, "context_pack", fake_context_pack)
    monkeypatch.setattr(server.graph_manager, "conflict_scan", fake_conflict_scan)

    payload = asyncio.run(
        server.prepare_context(
            task="resume Engram rebuild",
            project="C:/Dev/Engram",
            profile="repo_resume",
        )
    )

    assert scanned_refs == [({"kind": "memory", "key": "current_decision"}, "active")]
    assert payload["packet"]["warnings"] == [
        {
            "code": "conflict_edges_detected",
            "message": "1 active conflict graph edge was found for selected context memories.",
        }
    ]
    assert payload["packet"]["receipt"]["conflict_scans"] == [
        {"key": "current_decision", "count": 1, "edge_types": ["supersedes"], "error": None}
    ]


def test_prepare_context_rejects_unknown_profile_before_retrieval(monkeypatch):
    server = load_server_module()

    async def fail_context_pack(*args, **kwargs):
        raise AssertionError("unknown profiles must not run retrieval")

    monkeypatch.setattr(server, "context_pack", fail_context_pack)

    payload = asyncio.run(server.prepare_context(task="resume work", profile="missing-profile"))

    assert payload["packet"] is None
    assert payload["error"]["code"] == "invalid_profile"


def test_make_handoff_compiles_context_and_returns_no_write_packet(monkeypatch):
    server = load_server_module()
    observed: dict[str, object] = {}

    async def fake_prepare_context(**kwargs):
        observed.update(kwargs)
        return {
            "task": kwargs["task"],
            "profile": kwargs["profile"],
            "packet": {
                "record_type": "context_packet",
                "task": kwargs["task"],
                "project": kwargs["project"],
                "profile": {"id": kwargs["profile"]},
                "context": {
                    "chunks": [
                        {
                            "key": "engram_context_compiler",
                            "chunk_id": 0,
                            "title": "Context compiler",
                        }
                    ],
                    "citations": [{"citation_id": "engram:engram_context_compiler#0"}],
                    "omitted": [],
                },
                "warnings": [],
            },
            "write_performed": False,
            "error": None,
        }

    monkeypatch.setattr(server, "prepare_context", fake_prepare_context)

    payload = asyncio.run(
        server.make_handoff(
            task="continue Engram rebuild",
            project="C:/Dev/Engram",
            branch="codex/memory-os-migration-kernel",
            status="context compiler committed",
            next_steps="add handoff generator\nrun full validation",
            validation="pytest -q",
        )
    )

    assert observed["task"] == "continue Engram rebuild"
    assert observed["profile"] == "repo_resume"
    assert payload["handoff"]["record_type"] == "handoff_packet"
    assert payload["handoff"]["context_refs"] == [{"key": "engram_context_compiler", "chunk_id": 0}]
    assert payload["handoff"]["next_steps"] == ["add handoff generator", "run full validation"]
    assert payload["handoff"]["write_performed"] is False
    assert payload["error"] is None


def test_make_handoff_returns_context_error_without_promoting(monkeypatch):
    server = load_server_module()

    async def fake_prepare_context(**kwargs):
        return {
            "task": kwargs["task"],
            "profile": kwargs["profile"],
            "packet": None,
            "write_performed": False,
            "error": {"code": "runtime_error", "message": "context unavailable"},
        }

    monkeypatch.setattr(server, "prepare_context", fake_prepare_context)

    payload = asyncio.run(server.make_handoff(task="continue", project="C:/Dev/Engram"))

    assert payload["handoff"] is None
    assert payload["write_performed"] is False
    assert payload["error"]["message"] == "context unavailable"


def test_prepare_project_capsule_combines_context_and_quality_without_writes(monkeypatch):
    server = load_server_module()
    observed: dict[str, object] = {}

    async def fake_prepare_context(**kwargs):
        observed["context_kwargs"] = kwargs
        return {
            "task": kwargs["task"],
            "profile": kwargs["profile"],
            "packet": {
                "record_type": "context_packet",
                "task": kwargs["task"],
                "project": kwargs["project"],
                "profile": {"id": kwargs["profile"]},
                "context": {
                    "chunks": [
                        {
                            "key": "engram_rebuild_plan",
                            "chunk_id": 0,
                            "title": "Engram rebuild plan",
                        }
                    ],
                    "citations": [{"citation_id": "engram:engram_rebuild_plan#0"}],
                    "omitted": [],
                },
                "warnings": [],
            },
            "write_performed": False,
            "error": None,
        }

    async def fake_audit_memory_quality(**kwargs):
        observed["quality_kwargs"] = kwargs
        return {
            "summary": {"low_risk_count": 4, "medium_risk_count": 1, "high_risk_count": 0},
            "issue_count": 2,
            "memories": [],
            "write_performed": False,
            "error": None,
        }

    monkeypatch.setattr(server, "prepare_context", fake_prepare_context)
    monkeypatch.setattr(server, "audit_memory_quality", fake_audit_memory_quality)

    payload = asyncio.run(
        server.prepare_project_capsule(
            project="C:/Dev/Engram",
            task="prepare capsule",
            summary="Memory OS rebuild.",
            must_read_keys="engram_rebuild_plan",
        )
    )

    assert observed["context_kwargs"]["profile"] == "repo_resume"
    assert observed["quality_kwargs"]["project"] == "C:/Dev/Engram"
    assert payload["capsule"]["record_type"] == "project_capsule_draft"
    assert payload["capsule"]["must_read"][0]["source"] == "context"
    assert payload["capsule"]["quality_summary"]["medium_risk_count"] == 1
    assert payload["capsule"]["write_performed"] is False
    assert payload["error"] is None


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
