from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone


def test_structured_search_filters_by_project_and_canonical_only(mm_module, fake_chroma_collection):
    mm_module.memory_manager.store_memory(
        key="engram-canonical",
        content="# Canonical\nUseful note about structured search filters.",
        tags=["search", "ops"],
        title="Canonical search note",
        project="engram",
        domain="agent",
        canonical=True,
    )
    mm_module.memory_manager.store_memory(
        key="engram-draft",
        content="# Draft\nThis note should be excluded by canonical_only.",
        tags=["search", "draft"],
        title="Draft search note",
        project="engram",
        domain="agent",
        canonical=False,
    )
    mm_module.memory_manager.store_memory(
        key="other-project",
        content="# Other\nThis note should be excluded by project filtering.",
        tags=["search", "ops"],
        title="Other project note",
        project="other",
        domain="agent",
        canonical=True,
    )

    payload = mm_module.memory_manager.search_memories_structured(
        "structured search",
        limit=10,
        project="engram",
        canonical_only=True,
    )

    assert payload["query"] == "structured search"
    assert payload["count"] == 1
    assert [result["key"] for result in payload["results"]] == ["engram-canonical"]

    result = payload["results"][0]
    assert result["project"] == "engram"
    assert result["domain"] == "agent"
    assert result["canonical"] is True
    assert result["status"] == "active"
    assert result["stale_type"] is None
    assert "project=engram" in result["explanation"]
    assert "canonical memory" in result["explanation"]

    stored = mm_module.memory_manager.retrieve_memory("engram-canonical")
    assert stored["project"] == "engram"
    assert stored["domain"] == "agent"
    assert stored["status"] == "active"
    assert stored["canonical"] is True

    chunk_metadata = fake_chroma_collection.docs[next(iter(fake_chroma_collection.docs))]["metadata"]
    assert chunk_metadata["project"] == "engram"
    assert chunk_metadata["domain"] == "agent"
    assert chunk_metadata["status"] == "active"
    assert chunk_metadata["canonical"] is True
    assert chunk_metadata["chunk_kind"] == "section"


def test_structured_search_exposes_status_and_stale_type(mm_module):
    mm_module.memory_manager.store_memory(
        key="stale-memory",
        content="This memory should surface its status and stale classification.",
        tags=["search", "stale"],
        title="Stale memory",
        project="engram",
        domain="maintenance",
        status="archived",
    )

    json_path = mm_module._json_path("stale-memory")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    payload["potentially_stale"] = True
    payload["stale_reason"] = "linked file changed"
    payload["last_accessed"] = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    structured = mm_module.memory_manager.search_memories_structured(
        "stale classification",
        limit=10,
        include_stale=True,
    )

    assert structured["count"] == 1
    result = structured["results"][0]
    assert result["key"] == "stale-memory"
    assert result["status"] == "archived"
    assert result["stale_type"] == "both"
    assert "status=archived" in result["explanation"]
    assert "stale=both" in result["explanation"]

    filtered = mm_module.memory_manager.search_memories_structured(
        "stale classification",
        limit=10,
        include_stale=False,
    )

    assert filtered == {
        "query": "stale classification",
        "count": 0,
        "results": [],
    }


def test_legacy_memory_defaults_are_available_for_new_metadata(mm_module, isolated_storage):
    legacy_path = mm_module._json_path("legacy-memory")
    legacy_path.write_text(
        json.dumps(
            {
                "key": "legacy-memory",
                "content": "legacy content",
                "created_at": "2026-04-20T00:00:00+00:00",
                "updated_at": "2026-04-20T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    memory = mm_module.memory_manager.retrieve_memory("legacy-memory")

    assert memory["project"] is None
    assert memory["domain"] is None
    assert memory["status"] == "active"
    assert memory["canonical"] is False
    assert memory["tags"] == []
    assert memory["related_to"] == []
