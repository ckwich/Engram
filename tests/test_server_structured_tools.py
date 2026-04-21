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
        }

    monkeypatch.setattr(server, "search_memories_v2", fake_search_v2)

    rendered = asyncio.run(server.search_memories("alpha"))

    assert rendered == (
        "🔍 1 results for 'alpha':\n\n"
        "[score: 0.987] Alpha note\n"
        "  key=alpha-note  chunk_id=0  tags=alpha, ops\n"
        "  snippet: Alpha snippet\n"
    )


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
