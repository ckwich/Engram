from __future__ import annotations

import asyncio
import importlib


def load_server_module():
    import server

    return importlib.reload(server)


def test_suggest_memory_metadata_uses_heading_and_content_keywords(mm_module):
    suggestion = mm_module.memory_manager.suggest_memory_metadata(
        "# Release Checklist\n\nDocument deployment steps for Engram agents."
    )

    assert suggestion == {
        "title": "Release Checklist",
        "tags": ["release", "checklist", "document", "deployment", "steps"],
        "project": None,
        "domain": None,
        "status": "draft",
        "canonical": False,
        "related_to": [],
    }


def test_validate_memory_reports_oversized_content_relationship_limit_and_status(mm_module):
    validation = mm_module.memory_manager.validate_memory(
        content="x" * (mm_module.MAX_MEMORY_CHARS + 1),
        related_to=[f"memory-{index}" for index in range(11)],
        status="retired",
    )

    assert validation["valid"] is False
    assert validation["normalized"]["content_chars"] == mm_module.MAX_MEMORY_CHARS + 1
    assert {error["code"] for error in validation["errors"]} == {
        "content_too_long",
        "too_many_related_memories",
        "invalid_status",
    }


def test_update_memory_metadata_reindexes_existing_content_json_first(
    mm_module,
    fake_chroma_collection,
    monkeypatch,
):
    manager = mm_module.memory_manager
    manager.store_memory(
        key="release-note",
        content="# Release Note\n\nInitial release guidance for the team.",
        tags=["ops"],
        title="Release Note",
        status="active",
    )

    fake_chroma_collection.operations.clear()
    order: list[str] = []
    original_save_json = manager._save_json
    original_upsert = fake_chroma_collection.upsert

    def wrapped_save_json(data):
        order.append("json")
        return original_save_json(data)

    def wrapped_upsert(ids, embeddings, documents, metadatas):
        order.append("upsert")
        return original_upsert(ids, embeddings, documents, metadatas)

    monkeypatch.setattr(manager, "_save_json", wrapped_save_json)
    monkeypatch.setattr(fake_chroma_collection, "upsert", wrapped_upsert)

    updated = manager.update_memory_metadata(
        "release-note",
        title="Archived Release Note",
        tags=["ops", "release"],
        related_to=["deployment-runbook"],
        status="archived",
        canonical=True,
    )

    stored = manager.retrieve_memory("release-note")
    doc = fake_chroma_collection.docs[next(iter(fake_chroma_collection.docs))]

    assert order == ["json", "upsert"]
    assert fake_chroma_collection.operations == ["delete", "upsert"]
    assert updated["title"] == stored["title"] == "Archived Release Note"
    assert updated["status"] == stored["status"] == "archived"
    assert updated["canonical"] is True
    assert stored["tags"] == ["ops", "release"]
    assert stored["related_to"] == ["deployment-runbook"]
    assert stored["content"] == updated["content"]
    assert "Initial release guidance for the team." in stored["content"]
    assert doc["metadata"]["title"] == "Archived Release Note"
    assert doc["metadata"]["tags"] == "ops,release"
    assert doc["metadata"]["status"] == "archived"
    assert doc["metadata"]["canonical"] is True
    assert doc["metadata"]["related_to"] == "deployment-runbook"


def test_check_duplicate_tool_returns_structured_payload(monkeypatch):
    server = load_server_module()

    async def fake_check_duplicate(key: str, content: str):
        assert key == "release-note"
        assert content == "candidate content"
        return {
            "key": key,
            "duplicate": True,
            "match": {
                "status": "duplicate",
                "existing_key": "release-note-existing",
                "existing_title": "Existing release note",
                "score": 0.981,
            },
        }

    monkeypatch.setattr(server.memory_manager, "check_duplicate_async", fake_check_duplicate)

    payload = asyncio.run(server.check_duplicate("release-note", "candidate content"))

    assert payload == {
        "key": "release-note",
        "duplicate": True,
        "match": {
            "status": "duplicate",
            "existing_key": "release-note-existing",
            "existing_title": "Existing release note",
            "score": 0.981,
        },
        "error": None,
    }


def test_validate_memory_tool_returns_structured_validation_payload(monkeypatch):
    server = load_server_module()

    async def fake_validate_memory(**kwargs):
        assert kwargs["status"] == "retired"
        assert kwargs["related_to"] == ["alpha", "beta"]
        return {
            "valid": False,
            "errors": [
                {
                    "field": "status",
                    "code": "invalid_status",
                    "message": "status must be one of: active, archived, draft, historical, superseded.",
                }
            ],
            "normalized": {
                "title": "Release note",
                "tags": ["release"],
                "related_to": ["alpha", "beta"],
                "project": None,
                "domain": None,
                "status": "retired",
                "canonical": False,
                "content_chars": 17,
            },
        }

    monkeypatch.setattr(server.memory_manager, "validate_memory_async", fake_validate_memory)

    payload = asyncio.run(
        server.validate_memory(
            content="release guidance",
            title="Release note",
            tags=["release"],
            related_to=["alpha", "beta"],
            status="retired",
        )
    )

    assert payload == {
        "valid": False,
        "errors": [
            {
                "field": "status",
                "code": "invalid_status",
                "message": "status must be one of: active, archived, draft, historical, superseded.",
            }
        ],
        "normalized": {
            "title": "Release note",
            "tags": ["release"],
            "related_to": ["alpha", "beta"],
            "project": None,
            "domain": None,
            "status": "retired",
            "canonical": False,
            "content_chars": 17,
        },
        "error": None,
    }


def test_suggest_memory_metadata_tool_returns_structured_suggestion(monkeypatch):
    server = load_server_module()

    async def fake_suggest_memory_metadata(content: str):
        assert content == "# Heading\n\nBody"
        return {
            "title": "Heading",
            "tags": ["heading", "body"],
            "project": None,
            "domain": None,
            "status": "draft",
            "canonical": False,
            "related_to": [],
        }

    monkeypatch.setattr(
        server.memory_manager,
        "suggest_memory_metadata_async",
        fake_suggest_memory_metadata,
    )

    payload = asyncio.run(server.suggest_memory_metadata("# Heading\n\nBody"))

    assert payload == {
        "suggestion": {
            "title": "Heading",
            "tags": ["heading", "body"],
            "project": None,
            "domain": None,
            "status": "draft",
            "canonical": False,
            "related_to": [],
        },
        "error": None,
    }


def test_update_memory_metadata_tool_returns_structured_success(monkeypatch):
    server = load_server_module()

    async def fake_update_memory_metadata(key: str, **changes):
        assert key == "release-note"
        assert changes == {"status": "historical", "canonical": True}
        return {
            "key": "release-note",
            "title": "Release note",
            "tags": ["release"],
            "related_to": [],
            "project": None,
            "domain": None,
            "status": "historical",
            "canonical": True,
            "created_at": "2026-04-20T10:00:00+00:00",
            "updated_at": "2026-04-21T10:00:00+00:00",
            "last_accessed": None,
            "chunk_count": 1,
            "chars": 42,
            "lines": 3,
            "content": "# Release note\n\nBody",
        }

    monkeypatch.setattr(
        server.memory_manager,
        "update_memory_metadata_async",
        fake_update_memory_metadata,
    )

    payload = asyncio.run(
        server.update_memory_metadata(
            "release-note",
            status="historical",
            canonical=True,
        )
    )

    assert payload == {
        "key": "release-note",
        "updated": True,
        "memory": {
            "key": "release-note",
            "title": "Release note",
            "tags": ["release"],
            "related_to": [],
            "project": None,
            "domain": None,
            "status": "historical",
            "canonical": True,
            "created_at": "2026-04-20T10:00:00+00:00",
            "updated_at": "2026-04-21T10:00:00+00:00",
            "last_accessed": None,
            "chunk_count": 1,
            "chars": 42,
            "lines": 3,
            "content": "# Release note\n\nBody",
        },
        "error": None,
    }
