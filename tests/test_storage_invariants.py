from __future__ import annotations

import asyncio
import json
import threading

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


def test_store_keeps_json_if_chroma_upsert_fails(fake_chroma_collection, mm_module):
    key = "overnight-upsert-failure"
    json_path = mm_module._json_path(key)
    fake_chroma_collection.fail_upsert = True

    with pytest.raises(RuntimeError, match="simulated chroma upsert failure"):
        mm_module.memory_manager.store_memory(
            key=key,
            content="short note for upsert failure",
            tags=["safety"],
            title="Upsert failure",
        )

    assert json_path.exists(), "JSON must remain when Chroma upsert fails"
    stored = mm_module.memory_manager.retrieve_memory(key)
    assert stored is not None
    assert stored["key"] == key


def test_save_json_replace_is_atomic_for_concurrent_readers(monkeypatch, isolated_storage):
    mm_module = isolated_storage["mm"]
    manager = mm_module.memory_manager
    key = "overnight-atomic-save"
    json_path = mm_module._json_path(key)

    original_payload = {
        "key": key,
        "title": "Original",
        "content": "stable old content",
        "tags": [],
        "created_at": "2026-04-21T00:00:00+00:00",
        "updated_at": "2026-04-21T00:00:00+00:00",
        "chunk_count": 1,
        "chars": 18,
    }
    updated_payload = {
        **original_payload,
        "title": "Updated",
        "content": "fresh new content",
        "updated_at": "2026-04-21T00:05:00+00:00",
        "chars": 17,
    }

    manager._save_json(original_payload)
    observed: dict[str, object] = {}
    original_replace = mm_module.Path.replace

    def wrapped_replace(self, target):
        observed["final_before_replace"] = json.loads(json_path.read_text(encoding="utf-8"))
        observed["temp_exists_before_replace"] = self.exists()
        observed["temp_before_replace"] = json.loads(self.read_text(encoding="utf-8"))
        return original_replace(self, target)

    monkeypatch.setattr(mm_module.Path, "replace", wrapped_replace)

    manager._save_json(updated_payload)

    assert observed["temp_exists_before_replace"] is True
    assert observed["final_before_replace"] == original_payload
    assert observed["temp_before_replace"] == updated_payload
    assert json.loads(json_path.read_text(encoding="utf-8")) == updated_payload
    assert not json_path.with_suffix(f"{json_path.suffix}.tmp").exists()


def test_save_json_require_existing_does_not_recreate_deleted_memory(isolated_storage):
    mm_module = isolated_storage["mm"]
    manager = mm_module.memory_manager
    key = "overnight-last-access-delete-race"
    json_path = mm_module._json_path(key)

    payload = {
        "key": key,
        "title": "Race target",
        "content": "stable content",
        "tags": [],
        "created_at": "2026-04-21T00:00:00+00:00",
        "updated_at": "2026-04-21T00:00:00+00:00",
        "chunk_count": 1,
        "chars": 14,
    }

    manager._save_json(payload)
    stale_reader_copy = manager._load_json(key)
    assert stale_reader_copy is not None

    json_path.unlink()
    stale_reader_copy["last_accessed"] = "2026-04-21T00:05:00+00:00"

    saved = manager._save_json(stale_reader_copy, require_existing=True)

    assert saved is False
    assert not json_path.exists()


def test_delete_waits_for_overlapping_last_access_update_and_memory_stays_deleted(monkeypatch, isolated_storage):
    mm_module = isolated_storage["mm"]
    manager = mm_module.memory_manager
    key = "overnight-access-delete-overlap"
    json_path = mm_module._json_path(key)

    payload = {
        "key": key,
        "title": "Overlap target",
        "content": "stable content",
        "tags": [],
        "created_at": "2026-04-21T00:00:00+00:00",
        "updated_at": "2026-04-21T00:00:00+00:00",
        "chunk_count": 1,
        "chars": 14,
    }

    manager._save_json(payload)
    original_load_json = manager._load_json
    loaded_event = threading.Event()
    continue_event = threading.Event()

    def wrapped_load_json(loaded_key: str):
        data = original_load_json(loaded_key)
        if loaded_key == key and data is not None:
            loaded_event.set()
            continue_event.wait(timeout=2)
        return data

    monkeypatch.setattr(manager, "_load_json", wrapped_load_json)
    monkeypatch.setattr(manager, "_delete_chunks_from_chroma", lambda key: None)

    update_thread = threading.Thread(
        target=lambda: asyncio.run(manager._update_last_accessed_async([key])),
    )
    update_thread.start()

    assert loaded_event.wait(timeout=2), "background access update should load the JSON before delete starts"

    delete_result: dict[str, object] = {}

    def run_delete():
        delete_result["deleted"] = manager.delete_memory(key)

    delete_thread = threading.Thread(target=run_delete)
    delete_thread.start()
    assert delete_thread.is_alive(), "delete should wait for the in-flight access update on the same key"

    continue_event.set()
    update_thread.join(timeout=2)
    delete_thread.join(timeout=2)

    assert delete_result == {"deleted": True}
    assert not json_path.exists()
    assert manager._load_json(key) is None


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
