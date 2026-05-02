from __future__ import annotations

from datetime import datetime, timedelta, timezone


def test_mark_memory_reviewed_clears_stale_state(mm_module):
    manager = mm_module.memory_manager
    manager.store_memory(
        key="review-me",
        content="A stale memory that should become fresh after review.",
        tags=["review"],
        title="Review Me",
    )
    data = manager._load_json("review-me")
    data["last_accessed"] = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    data["potentially_stale"] = True
    data["stale_reason"] = "linked file changed"
    data["stale_flagged_at"] = datetime.now(timezone.utc).isoformat()
    manager._save_json(data)

    result = manager.mark_memory_reviewed("review-me", stale_type="both")

    assert result == {"reviewed": True, "key": "review-me"}
    reviewed = manager._load_json("review-me")
    assert reviewed["potentially_stale"] is False
    assert reviewed["stale_reason"] == ""
    assert reviewed["stale_flagged_at"] is None
    assert reviewed["last_accessed"] != data["last_accessed"]


def test_memory_manager_exposes_code_stale_flag_methods(mm_module):
    manager = mm_module.memory_manager
    manager.store_memory(
        key="stale-api",
        content="A memory that the codebase indexer can flag through a public API.",
        tags=["review"],
        title="Stale API",
    )

    flagged = manager.mark_memory_potentially_stale("stale-api", reason="3 files changed")

    assert flagged == {"stale": True, "key": "stale-api"}
    data = manager._load_json("stale-api")
    assert data["potentially_stale"] is True
    assert data["stale_reason"] == "3 files changed"
    assert data["stale_flagged_at"] is not None

    cleared = manager.clear_memory_stale_flag("stale-api")

    assert cleared == {"stale": False, "key": "stale-api"}
    reviewed = manager._load_json("stale-api")
    assert reviewed["potentially_stale"] is False
    assert reviewed["stale_reason"] == ""
    assert reviewed["stale_flagged_at"] is None


def test_reviewed_api_uses_memory_manager_boundary(monkeypatch):
    import webui

    calls = []

    class FakeMemoryManager:
        def mark_memory_reviewed(self, key, stale_type="both"):
            calls.append({"key": key, "stale_type": stale_type})
            return {"reviewed": True, "key": key}

    monkeypatch.setattr(webui, "memory_manager", FakeMemoryManager())

    response = webui.app.test_client().post(
        "/api/memory/review-me/reviewed",
        json={"stale_type": "code"},
    )

    assert response.status_code == 200
    assert response.get_json() == {"reviewed": True, "key": "review-me"}
    assert calls == [{"key": "review-me", "stale_type": "code"}]


def test_reviewed_api_rejects_form_posts_before_mutation(monkeypatch):
    import webui

    calls = []

    class FakeMemoryManager:
        def mark_memory_reviewed(self, key, stale_type="both"):
            calls.append({"key": key, "stale_type": stale_type})
            return {"reviewed": True, "key": key}

    monkeypatch.setattr(webui, "memory_manager", FakeMemoryManager())

    response = webui.app.test_client().post(
        "/api/memory/review-me/reviewed",
        data={"stale_type": "code"},
    )

    assert response.status_code == 415
    assert response.get_json()["error"] == "application/json required"
    assert calls == []


def test_reviewed_api_rejects_invalid_json_before_mutation(monkeypatch):
    import webui

    calls = []

    class FakeMemoryManager:
        def mark_memory_reviewed(self, key, stale_type="both"):
            calls.append({"key": key, "stale_type": stale_type})
            return {"reviewed": True, "key": key}

    monkeypatch.setattr(webui, "memory_manager", FakeMemoryManager())

    response = webui.app.test_client().post(
        "/api/memory/review-me/reviewed",
        data="{not valid json",
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "valid JSON body required"
    assert calls == []
