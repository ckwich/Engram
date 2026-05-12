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

    async def delete_memory_async(self, key):
        self.deleted.append(key)
        return key == "daemon_memory"


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


def test_unknown_route_returns_structured_not_found_error():
    api = EngramDaemonAPI(memory_manager=FakeMemoryManager())

    response = api.handle("POST", "/v1/missing", {})

    assert response["status"] == 404
    assert response["body"]["error"]["code"] == "not_found"
