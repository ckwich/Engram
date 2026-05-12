from __future__ import annotations

from core.engramd_api import EngramDaemonAPI


class FakeMemoryManager:
    def __init__(self):
        self.stored = None
        self.deleted = []
        self.updated = None

    def get_stats(self):
        return {
            "total_memories": 2,
            "total_chunks": 3,
            "storage_size": "12 KB",
        }

    async def search_memories_structured_async(self, query, **kwargs):
        return {
            "query": query,
            "count": 1,
            "results": [
                {
                    "key": "daemon_memory",
                    "chunk_id": 0,
                    "title": "Daemon Memory",
                    "score": 0.9,
                    "snippet": "Daemon-owned search result.",
                    "tags": ["daemon"],
                }
            ],
            "error": None,
            "kwargs": kwargs,
        }

    async def check_duplicate_async(self, key, content):
        return {
            "key": key,
            "duplicate": True,
            "match": {
                "status": "duplicate",
                "existing_key": "daemon_memory",
                "existing_title": "Daemon Memory",
                "score": 0.97,
            },
        }

    async def retrieve_chunks_async(self, requests):
        return [
            {
                "key": request["key"],
                "chunk_id": request["chunk_id"],
                "found": True,
                "text": f"chunk {request['chunk_id']}",
                "title": "Daemon Memory",
                "section_title": "Runtime",
                "heading_path": ["Daemon Memory", "Runtime"],
                "chunk_kind": "paragraph",
                "error": None,
            }
            for request in requests
        ]

    async def retrieve_memory_async(self, key):
        return {
            "key": key,
            "title": "Daemon Memory",
            "content": "Full memory body.",
        }

    async def store_memory_async(self, **kwargs):
        self.stored = kwargs
        return {
            "key": kwargs["key"],
            "title": kwargs["title"],
            "chunk_count": 1,
            "chars": len(kwargs["content"]),
        }

    async def update_memory_metadata_async(self, key, **changes):
        self.updated = {"key": key, "changes": changes}
        return {
            "key": key,
            "title": changes.get("title", "Daemon Memory"),
            "tags": changes.get("tags", []),
            "project": changes.get("project"),
            "domain": changes.get("domain"),
            "status": changes.get("status", "active"),
            "canonical": changes.get("canonical"),
        }

    async def repair_memory_metadata_async(self, keys, dry_run=True):
        return {
            "requested_count": len(keys),
            "repaired_count": 0 if dry_run else len(keys),
            "dry_run": dry_run,
            "repairs": [
                {
                    "key": key,
                    "repaired": not dry_run,
                    "issues": [],
                }
                for key in keys
            ],
        }

    async def delete_memory_async(self, key):
        self.deleted.append(key)
        return key == "daemon_memory"


class FakeSourceIntakeManager:
    def __init__(self, draft=None):
        self.draft = draft or {
            "draft_id": "draft-a",
            "status": "draft",
            "proposed_memories": [
                {
                    "key": "daemon_source_memory",
                    "content": "Promoted source body.",
                    "title": "Daemon Source Memory",
                    "tags": ["source", "daemon"],
                    "related_to": [],
                    "project": "Engram",
                    "domain": "source-intake",
                    "status": "active",
                    "canonical": False,
                }
            ],
        }

    def get_source_draft(self, draft_id):
        if draft_id == self.draft.get("draft_id"):
            return self.draft
        return None


def test_health_reports_daemon_and_storage_stats():
    api = EngramDaemonAPI(memory_manager=FakeMemoryManager())

    response = api.handle("GET", "/health", None)

    assert response["status"] == 200
    assert response["body"]["daemon"] == "engramd"
    assert response["body"]["status"] == "ok"
    assert response["body"]["stats"]["total_memories"] == 2
    assert response["body"]["stats"]["total_chunks"] == 3


def test_search_passes_filters_to_memory_manager():
    api = EngramDaemonAPI(memory_manager=FakeMemoryManager())

    response = api.handle(
        "POST",
        "/v1/search_memories",
        {
            "query": "daemon runtime",
            "limit": 7,
            "project": "C:/Dev/Engram",
            "domain": "runtime",
            "tags": ["daemon"],
            "include_stale": False,
            "canonical_only": True,
            "retrieval_mode": "hybrid",
            "pinned_keys": ["daemon_memory"],
            "pinned_first": True,
        },
    )

    assert response["status"] == 200
    body = response["body"]
    assert body["query"] == "daemon runtime"
    assert body["results"][0]["key"] == "daemon_memory"
    assert body["kwargs"]["project"] == "C:/Dev/Engram"
    assert body["kwargs"]["retrieval_mode"] == "hybrid"
    assert body["kwargs"]["pinned_keys"] == ["daemon_memory"]
    assert body["kwargs"]["pinned_first"] is True


def test_check_duplicate_returns_daemon_duplicate_payload():
    api = EngramDaemonAPI(memory_manager=FakeMemoryManager())

    response = api.handle(
        "POST",
        "/v1/check_duplicate",
        {
            "key": "candidate_memory",
            "content": "Candidate body",
        },
    )

    assert response["status"] == 200
    assert response["body"]["key"] == "candidate_memory"
    assert response["body"]["duplicate"] is True
    assert response["body"]["match"]["existing_key"] == "daemon_memory"
    assert response["body"]["error"] is None


def test_check_duplicate_invalid_request_preserves_tool_payload_shape():
    api = EngramDaemonAPI(memory_manager=FakeMemoryManager())

    response = api.handle(
        "POST",
        "/v1/check_duplicate",
        {
            "key": "",
            "content": "",
        },
    )

    assert response["status"] == 200
    assert response["body"]["duplicate"] is False
    assert response["body"]["match"] is None
    assert response["body"]["error"]["code"] == "invalid_request"


def test_retrieve_chunks_wraps_chunk_payloads():
    api = EngramDaemonAPI(memory_manager=FakeMemoryManager())

    response = api.handle(
        "POST",
        "/v1/retrieve_chunks",
        {"requests": [{"key": "daemon_memory", "chunk_id": 0}]},
    )

    assert response["status"] == 200
    body = response["body"]
    assert body["requested_count"] == 1
    assert body["found_count"] == 1
    assert body["results"][0]["chunk"]["text"] == "chunk 0"


def test_store_memory_preserves_json_first_result_shape():
    manager = FakeMemoryManager()
    api = EngramDaemonAPI(memory_manager=manager)

    response = api.handle(
        "POST",
        "/v1/store_memory",
        {
            "key": "daemon_memory",
            "content": "Daemon memory body.",
            "title": "Daemon Memory",
            "tags": ["daemon", "runtime"],
            "related_to": ["engram_memory_os_rebuild_progress_2026_05_12"],
            "force": True,
            "project": "C:/Dev/Engram",
            "domain": "runtime",
            "status": "active",
            "canonical": True,
        },
    )

    assert response["status"] == 200
    assert response["body"]["stored"] is True
    assert response["body"]["result"]["chunk_count"] == 1
    assert manager.stored["tags"] == ["daemon", "runtime"]
    assert manager.stored["canonical"] is True


def test_update_memory_metadata_preserves_daemon_result_shape():
    manager = FakeMemoryManager()
    api = EngramDaemonAPI(memory_manager=manager)

    response = api.handle(
        "POST",
        "/v1/update_memory_metadata",
        {
            "key": "daemon_memory",
            "title": "Updated Daemon Memory",
            "tags": ["daemon", "metadata"],
            "project": "Engram",
            "domain": "daemon",
            "status": "active",
            "canonical": True,
        },
    )

    assert response["status"] == 200
    assert response["body"]["updated"] is True
    assert response["body"]["memory"]["title"] == "Updated Daemon Memory"
    assert manager.updated["key"] == "daemon_memory"
    assert manager.updated["changes"]["tags"] == ["daemon", "metadata"]


def test_repair_memory_metadata_preserves_daemon_result_shape():
    api = EngramDaemonAPI(memory_manager=FakeMemoryManager())

    response = api.handle(
        "POST",
        "/v1/repair_memory_metadata",
        {
            "keys": ["daemon_memory"],
            "dry_run": False,
        },
    )

    assert response["status"] == 200
    assert response["body"]["requested_count"] == 1
    assert response["body"]["repaired_count"] == 1
    assert response["body"]["dry_run"] is False
    assert response["body"]["error"] is None


def test_store_prepared_memory_promotes_source_draft_via_daemon():
    manager = FakeMemoryManager()
    api = EngramDaemonAPI(
        memory_manager=manager,
        source_intake_manager=FakeSourceIntakeManager(),
    )

    response = api.handle(
        "POST",
        "/v1/store_prepared_memory",
        {
            "draft_id": "draft-a",
            "selected_items": [0],
            "force": True,
        },
    )

    assert response["status"] == 200
    assert response["body"]["stored_count"] == 1
    assert response["body"]["stored"][0]["key"] == "daemon_source_memory"
    assert response["body"]["skipped"] == []
    assert manager.stored["key"] == "daemon_source_memory"
    assert manager.stored["force"] is True
    assert response["body"]["error"] is None


def test_unknown_route_returns_structured_not_found_error():
    api = EngramDaemonAPI(memory_manager=FakeMemoryManager())

    response = api.handle("POST", "/v1/missing", {})

    assert response["status"] == 404
    assert response["body"]["error"]["code"] == "not_found"
