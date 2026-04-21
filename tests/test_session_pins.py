from __future__ import annotations

import asyncio
import importlib

from core.session_pins import SessionPinStore


def load_server_module():
    import server

    return importlib.reload(server)


def test_session_pin_store_round_trip(tmp_path):
    store = SessionPinStore(tmp_path / "session_pins.json")

    assert store.pin("session-a", "memory-one") == ["memory-one"]
    assert store.pin("session-a", "memory-two") == ["memory-one", "memory-two"]
    assert store.pin("session-a", "memory-one") == ["memory-one", "memory-two"]
    assert store.list_pins("session-a") == ["memory-one", "memory-two"]

    reloaded = SessionPinStore(tmp_path / "session_pins.json")
    assert reloaded.list_pins("session-a") == ["memory-one", "memory-two"]
    assert reloaded.unpin("session-a", "memory-one") == ["memory-two"]
    assert reloaded.list_pins("session-a") == ["memory-two"]
    assert reloaded.clear("session-a") == []
    assert reloaded.list_pins("session-a") == []


def test_structured_search_prioritizes_pinned_results(mm_module):
    mm_module.memory_manager.store_memory(
        key="alpha-unpinned",
        content="Shared query phrase with useful unpinned context.",
        tags=["search"],
        title="Alpha unpinned",
    )
    mm_module.memory_manager.store_memory(
        key="zeta-pinned",
        content="Shared query phrase with useful pinned context.",
        tags=["search"],
        title="Zeta pinned",
    )

    default_payload = mm_module.memory_manager.search_memories_structured(
        "shared query phrase",
        limit=10,
        pinned_keys=["zeta-pinned"],
        pinned_first=False,
    )

    assert [result["key"] for result in default_payload["results"]] == [
        "alpha-unpinned",
        "zeta-pinned",
    ]
    assert default_payload["results"][1]["pinned"] is True
    assert "session-pinned" in default_payload["results"][1]["explanation"]
    assert "promoted ahead of unpinned results" not in default_payload["results"][1]["explanation"]

    pinned_first_payload = mm_module.memory_manager.search_memories_structured(
        "shared query phrase",
        limit=10,
        pinned_keys=["zeta-pinned"],
        pinned_first=True,
    )

    assert [result["key"] for result in pinned_first_payload["results"]] == [
        "zeta-pinned",
        "alpha-unpinned",
    ]
    assert pinned_first_payload["results"][0]["pinned"] is True
    assert "session-pinned" in pinned_first_payload["results"][0]["explanation"]
    assert "promoted ahead of unpinned results" in pinned_first_payload["results"][0]["explanation"]
    assert pinned_first_payload["results"][1]["pinned"] is False


def test_search_memories_v2_loads_session_pins_for_pinned_first(monkeypatch):
    server = load_server_module()
    observed: dict[str, object] = {}

    class FakePinStore:
        def list_pins(self, session_id: str) -> list[str]:
            observed["session_id"] = session_id
            return ["zeta-pinned"]

    async def fake_structured_search(query: str, limit: int = 5, **kwargs):
        observed["query"] = query
        observed["limit"] = limit
        observed["kwargs"] = kwargs
        return {
            "query": query,
            "count": 1,
            "results": [
                {
                    "key": "zeta-pinned",
                    "chunk_id": 0,
                    "title": "Zeta pinned",
                    "score": 1.0,
                    "snippet": "Pinned snippet",
                    "tags": ["search"],
                    "pinned": True,
                    "explanation": "session-pinned; promoted ahead of unpinned results; semantic score 1.000",
                }
            ],
        }

    monkeypatch.setattr(server, "session_pin_store", FakePinStore())
    monkeypatch.setattr(server.memory_manager, "search_memories_structured_async", fake_structured_search)

    payload = asyncio.run(
        server.search_memories_v2(
            "shared query phrase",
            limit=7,
            session_id="session-a",
            pinned_first=True,
        )
    )

    assert observed == {
        "session_id": "session-a",
        "query": "shared query phrase",
        "limit": 7,
        "kwargs": {
            "pinned_keys": ["zeta-pinned"],
            "pinned_first": True,
        },
    }
    assert payload["error"] is None
    assert payload["results"][0]["pinned"] is True
