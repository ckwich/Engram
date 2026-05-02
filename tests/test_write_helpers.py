from __future__ import annotations

import asyncio
import importlib
import json

import pytest


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


def test_update_memory_metadata_keeps_json_update_if_chunk_cleanup_fails(
    mm_module,
    fake_chroma_collection,
):
    manager = mm_module.memory_manager
    manager.store_memory(
        key="cleanup-failure-note",
        content="# Cleanup Failure\n\nExisting note body.",
        tags=["ops"],
        title="Cleanup Failure",
        status="active",
    )

    fake_chroma_collection.fail_delete = True

    updated = manager.update_memory_metadata(
        "cleanup-failure-note",
        status="historical",
        canonical=True,
    )

    stored = manager.retrieve_memory("cleanup-failure-note")

    assert updated["status"] == "historical"
    assert updated["canonical"] is True
    assert stored["status"] == "historical"
    assert stored["canonical"] is True
    assert "index_cleanup_warning" in updated
    assert "cleanup-failure-note" in updated["index_cleanup_warning"]
    assert fake_chroma_collection.operations[-2:] == ["delete", "upsert"]


def test_update_memory_metadata_keeps_json_if_upsert_fails_after_save(
    mm_module,
    fake_chroma_collection,
):
    manager = mm_module.memory_manager
    manager.store_memory(
        key="upsert-failure-note",
        content="# Upsert Failure\n\nExisting note body.",
        tags=["ops"],
        title="Upsert Failure",
        status="active",
    )

    fake_chroma_collection.fail_upsert = True

    with pytest.raises(RuntimeError, match="simulated chroma upsert failure"):
        manager.update_memory_metadata(
            "upsert-failure-note",
            status="historical",
            canonical=True,
        )

    stored = manager.retrieve_memory("upsert-failure-note")

    assert stored["status"] == "historical"
    assert stored["canonical"] is True


def test_store_memory_rejects_invalid_status(mm_module):
    with pytest.raises(ValueError, match="status must be one of"):
        mm_module.memory_manager.store_memory(
            key="invalid-status-note",
            content="# Invalid Status\n\nBody",
            tags=["ops"],
            title="Invalid Status",
            status="retired",
        )


def test_legacy_invalid_status_is_coerced_for_compatibility(mm_module):
    legacy_path = mm_module._json_path("legacy-invalid-status")
    legacy_path.write_text(
        json.dumps(
            {
                "key": "legacy-invalid-status",
                "title": "Legacy invalid status",
                "content": "Legacy body",
                "tags": ["legacy"],
                "related_to": [],
                "status": "retired",
                "canonical": False,
                "created_at": "2026-04-20T00:00:00+00:00",
                "updated_at": "2026-04-20T00:00:00+00:00",
                "chars": 11,
                "lines": 1,
            }
        ),
        encoding="utf-8",
    )

    memory = mm_module.memory_manager.retrieve_memory("legacy-invalid-status")
    updated = mm_module.memory_manager.update_memory_metadata(
        "legacy-invalid-status",
        tags=["legacy", "normalized"],
    )

    assert memory["status"] == "active"
    assert updated["status"] == "active"
    assert updated["tags"] == ["legacy", "normalized"]


def test_memory_manager_check_duplicate_and_store_enforce_dedup(mm_module, monkeypatch):
    manager = mm_module.memory_manager
    content = (
        "# Release duplicate\n\n"
        "This is a long release note body intended to exercise duplicate detection for the "
        "memory manager. It contains enough repeated text to exceed the short-content bypass "
        "and should be treated as a true duplicate candidate during semantic checks."
    )

    manager.store_memory(
        key="existing-duplicate",
        content=content,
        tags=["release"],
        title="Existing duplicate",
        status="active",
    )

    collection = manager._get_collection()
    original_query = collection.query

    def duplicate_query(query_embeddings=None, n_results=1, include=None):
        result = original_query(query_embeddings=query_embeddings, n_results=n_results, include=include)
        result["distances"] = [[0.0 for _ in result["ids"][0]]]
        return result

    monkeypatch.setattr(collection, "query", duplicate_query)

    duplicate = manager.check_duplicate("new-duplicate", content)

    assert duplicate["duplicate"] is True
    assert duplicate["match"]["existing_key"] == "existing-duplicate"

    with pytest.raises(mm_module.DuplicateMemoryError):
        manager.store_memory(
            key="new-duplicate",
            content=content,
            tags=["release"],
            title="New duplicate",
            status="active",
        )


def test_check_duplicate_ignores_chroma_rows_without_metadata(mm_module, fake_chroma_collection, monkeypatch):
    manager = mm_module.memory_manager
    content = (
        "# Orphan Metadata\n\n"
        "This is a long memory body that intentionally exceeds the short-content bypass so "
        "duplicate detection has to inspect the Chroma query result. Some historical Chroma "
        "rows can lack metadata, and those rows should not crash the write path."
    )

    manager.store_memory(
        key="existing-orphan-metadata",
        content=content,
        tags=["release"],
        title="Existing orphan metadata",
        status="active",
    )

    def orphan_metadata_query(query_embeddings=None, n_results=1, include=None):
        return {
            "ids": [["orphan-doc"]],
            "metadatas": [[None]],
            "distances": [[0.0]],
        }

    monkeypatch.setattr(fake_chroma_collection, "query", orphan_metadata_query)

    duplicate = manager.check_duplicate("candidate-orphan-metadata", content)
    stored = manager.store_memory(
        key="candidate-orphan-metadata",
        content=content,
        tags=["release"],
        title="Candidate orphan metadata",
        status="active",
    )

    assert duplicate == {"key": "candidate-orphan-metadata", "duplicate": False, "match": None}
    assert stored["key"] == "candidate-orphan-metadata"


def test_search_result_parsing_skips_rows_without_metadata(mm_module):
    payload = mm_module.MemoryManager._parse_search_results(
        {
            "ids": [["orphan-doc"]],
            "documents": [["orphan body"]],
            "metadatas": [[None]],
            "distances": [[0.0]],
        }
    )

    assert payload == []


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


def test_store_memory_tool_forwards_extended_metadata(monkeypatch):
    server = load_server_module()
    observed: dict[str, object] = {}

    async def fake_store_memory_async(**kwargs):
        observed.update(kwargs)
        return {
            "title": kwargs["title"],
            "chars": len(kwargs["content"]),
            "chunk_count": 1,
        }

    monkeypatch.setattr(server.memory_manager, "store_memory_async", fake_store_memory_async)

    rendered = asyncio.run(
        server.store_memory(
            key="agent-protocol",
            content="# Agent Protocol\n\nBody",
            title="Agent Protocol",
            tags="agent,protocol",
            related_to="engram-core",
            project="engram",
            domain="memory",
            status="active",
            canonical=True,
        )
    )

    assert observed == {
        "key": "agent-protocol",
        "content": "# Agent Protocol\n\nBody",
        "tags": ["agent", "protocol"],
        "title": "Agent Protocol",
        "related_to": ["engram-core"],
        "force": False,
        "project": "engram",
        "domain": "memory",
        "status": "active",
        "canonical": True,
    }
    assert "Stored: 'Agent Protocol'" in rendered


def test_prepare_memory_tool_builds_ready_draft(monkeypatch):
    server = load_server_module()

    async def fake_suggest(content: str):
        assert content == "# Agent Protocol\n\nBody"
        return {
            "title": "Suggested Title",
            "tags": ["suggested", "agent"],
            "project": None,
            "domain": None,
            "status": "draft",
            "canonical": False,
            "related_to": [],
        }

    async def fake_validate(**kwargs):
        assert kwargs == {
            "content": "# Agent Protocol\n\nBody",
            "title": "Agent Protocol",
            "tags": ["agent", "protocol"],
            "related_to": ["engram-core"],
            "project": "engram",
            "domain": "memory",
            "status": "active",
            "canonical": True,
        }
        return {
            "valid": True,
            "errors": [],
            "normalized": {
                "title": "Agent Protocol",
                "tags": ["agent", "protocol"],
                "related_to": ["engram-core"],
                "project": "engram",
                "domain": "memory",
                "status": "active",
                "canonical": True,
                "content_chars": 23,
            },
        }

    async def fake_check_duplicate(key: str, content: str):
        assert key == "agent_protocol"
        assert content == "# Agent Protocol\n\nBody"
        return {"key": key, "duplicate": False, "match": None}

    monkeypatch.setattr(server.memory_manager, "suggest_memory_metadata_async", fake_suggest)
    monkeypatch.setattr(server.memory_manager, "validate_memory_async", fake_validate)
    monkeypatch.setattr(server.memory_manager, "check_duplicate_async", fake_check_duplicate)

    payload = asyncio.run(
        server.prepare_memory(
            content="# Agent Protocol\n\nBody",
            title="Agent Protocol",
            tags="agent,protocol",
            related_to="engram-core",
            project="engram",
            domain="memory",
            status="active",
            canonical=True,
        )
    )

    assert payload["ready"] is True
    assert payload["draft"] == {
        "key": "agent_protocol",
        "content": "# Agent Protocol\n\nBody",
        "title": "Agent Protocol",
        "tags": ["agent", "protocol"],
        "related_to": ["engram-core"],
        "project": "engram",
        "domain": "memory",
        "status": "active",
        "canonical": True,
    }
    assert payload["duplicate"]["duplicate"] is False
    assert payload["validation"]["valid"] is True
    assert payload["error"] is None


def test_memory_manager_audits_and_repairs_metadata_drift(mm_module):
    key = "legacy-drift"
    mm_module._json_path(key).write_text(
        json.dumps(
            {
                "key": key,
                "title": "",
                "content": "# Legacy Drift\n\nBody",
                "tags": "alpha,beta,alpha",
                "related_to": "one,two",
                "status": "retired",
                "canonical": "yes",
                "project": "engram",
                "domain": "memory",
                "created_at": "2026-04-20T00:00:00+00:00",
                "updated_at": "2026-04-20T00:00:00+00:00",
                "chars": 1,
                "lines": 99,
                "chunk_count": 99,
            }
        ),
        encoding="utf-8",
    )

    audit = mm_module.memory_manager.audit_memory_metadata()

    assert audit["total"] == 1
    assert audit["issue_count"] >= 1
    issue_codes = {issue["code"] for issue in audit["memories"][0]["issues"]}
    assert {
        "missing_title",
        "tags_not_list",
        "duplicate_tags",
        "related_to_not_list",
        "invalid_status",
        "chars_mismatch",
        "lines_mismatch",
        "chunk_count_mismatch",
    }.issubset(issue_codes)

    dry_run = mm_module.memory_manager.repair_memory_metadata([key], dry_run=True)
    assert dry_run["repaired_count"] == 0
    assert dry_run["repairs"][0]["would_change"] is True

    repaired = mm_module.memory_manager.repair_memory_metadata([key], dry_run=False)
    stored = mm_module.memory_manager.retrieve_memory(key)

    assert repaired["repaired_count"] == 1
    assert stored["title"] == key
    assert stored["tags"] == ["alpha", "beta"]
    assert stored["related_to"] == ["one", "two"]
    assert stored["status"] == "active"
    assert stored["canonical"] is True
    assert stored["chars"] == len(stored["content"])
    assert stored["lines"] == len(stored["content"].splitlines())
    assert stored["chunk_count"] == 1


def test_memory_manager_repair_decodes_encoded_tag_list_fragments(mm_module):
    key = "encoded-tag-drift"
    mm_module._json_path(key).write_text(
        json.dumps(
            {
                "key": key,
                "title": "Encoded Tag Drift",
                "content": "# Encoded Tag Drift\n\nBody",
                "tags": ['["engram"', '"cli"', '"architecture"]'],
                "related_to": [],
                "status": "active",
                "canonical": False,
                "created_at": "2026-04-20T00:00:00+00:00",
                "updated_at": "2026-04-20T00:00:00+00:00",
                "chars": len("# Encoded Tag Drift\n\nBody"),
                "lines": 3,
                "chunk_count": 1,
            }
        ),
        encoding="utf-8",
    )

    audit = mm_module.memory_manager.audit_memory_metadata()
    issue_codes = {
        issue["code"]
        for memory in audit["memories"]
        if memory["key"] == key
        for issue in memory["issues"]
    }
    assert "encoded_tag" in issue_codes

    repaired = mm_module.memory_manager.repair_memory_metadata([key], dry_run=False)
    stored = mm_module.memory_manager.retrieve_memory(key)

    assert repaired["repaired_count"] == 1
    assert stored["tags"] == ["engram", "cli", "architecture"]


def test_audit_and_repair_metadata_tools_return_structured_payloads(monkeypatch):
    server = load_server_module()

    async def fake_audit_memory_metadata(**kwargs):
        assert kwargs == {"limit": 25, "offset": 5, "project": "engram"}
        return {
            "count": 1,
            "total": 1,
            "issue_count": 2,
            "repairable_count": 1,
            "memories": [{"key": "legacy-drift", "issues": []}],
        }

    async def fake_repair_memory_metadata(keys, dry_run=True):
        assert keys == ["legacy-drift"]
        assert dry_run is False
        return {
            "requested_count": 1,
            "repaired_count": 1,
            "repairs": [{"key": "legacy-drift", "repaired": True}],
        }

    monkeypatch.setattr(server.memory_manager, "audit_memory_metadata_async", fake_audit_memory_metadata)
    monkeypatch.setattr(server.memory_manager, "repair_memory_metadata_async", fake_repair_memory_metadata)

    audit_payload = asyncio.run(
        server.audit_memory_metadata(limit=25, offset=5, project="engram")
    )
    repair_payload = asyncio.run(
        server.repair_memory_metadata(keys="legacy-drift", dry_run=False)
    )

    assert audit_payload["issue_count"] == 2
    assert audit_payload["error"] is None
    assert repair_payload["repaired_count"] == 1
    assert repair_payload["error"] is None
