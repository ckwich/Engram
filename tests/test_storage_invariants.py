from __future__ import annotations

import json

import pytest


def test_store_writes_json_before_chroma_upsert(fake_chroma_collection, monkeypatch, mm_module):
    key = "overnight-store-order"
    json_path = mm_module._json_path(key)
    order: list[str] = []

    original_save_json = mm_module.MemoryManager._save_json
    original_upsert = fake_chroma_collection.upsert

    def wrapped_save_json(data):
        result = original_save_json(mm_module.memory_manager, data)
        order.append("json")
        return result

    def wrapped_upsert(*args, **kwargs):
        assert json_path.exists(), "JSON must exist before the Chroma upsert runs"
        with json_path.open("r", encoding="utf-8") as handle:
            saved = json.load(handle)
        assert saved["key"] == key
        order.append("chroma")
        return original_upsert(*args, **kwargs)

    monkeypatch.setattr(mm_module.memory_manager, "_save_json", wrapped_save_json)
    monkeypatch.setattr(fake_chroma_collection, "upsert", wrapped_upsert)

    mm_module.memory_manager.store_memory(
        key=key,
        content="short note for storage ordering",
        tags=["safety"],
        title="Storage ordering",
    )

    assert order == ["json", "chroma"]
    assert json_path.exists()


def test_delete_stops_if_chroma_delete_fails(fake_chroma_collection, mm_module):
    key = "overnight-delete-failure"
    mm_module.memory_manager.store_memory(
        key=key,
        content="short note for delete failure",
        tags=["safety"],
        title="Delete failure",
    )

    json_path = mm_module._json_path(key)
    assert json_path.exists()

    fake_chroma_collection.fail_delete = True

    with pytest.raises(RuntimeError, match="Failed to delete"):
        mm_module.memory_manager.delete_memory(key)

    assert json_path.exists(), "JSON must remain intact when Chroma delete fails"
    stored = mm_module.memory_manager.retrieve_memory(key)
    assert stored is not None
    assert stored["key"] == key


def test_old_memory_without_new_fields_is_still_listed(isolated_storage):
    json_dir = isolated_storage["json_dir"]
    mm_module = isolated_storage["mm"]
    legacy_path = json_dir / "legacy-memory.json"

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

    memories = mm_module.memory_manager.list_memories()

    assert len(memories) == 1
    assert memories[0]["key"] == "legacy-memory"
    assert memories[0]["title"] == "legacy-memory"
    assert memories[0]["chunk_count"] == "?"
    assert memories[0]["chars"] == 0
