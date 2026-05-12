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
        self.prepared = None
        self.listed = None
        self.discarded = None
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

    def prepare_source_memory(self, **kwargs):
        self.prepared = kwargs
        return self.draft

    def list_source_drafts(self, **kwargs):
        self.listed = kwargs
        return {
            "count": 1,
            "total": 1,
            "limit": kwargs["limit"],
            "offset": kwargs["offset"],
            "has_more": False,
            "drafts": [self.draft],
            "error": None,
        }

    def discard_source_draft(self, draft_id):
        self.discarded = draft_id
        return {"discarded": True, "draft_id": draft_id, "error": None}

    def get_source_draft(self, draft_id):
        if draft_id == self.draft.get("draft_id"):
            return self.draft
        return None


def fake_document_disassembler(**kwargs):
    if not kwargs.get("source_path"):
        raise ValueError("source_path is required")
    return {
        "record_type": "document_disassembly_preview",
        "source": {"path": kwargs["source_path"]},
        "document": {"source_type": kwargs.get("source_type"), "page_limit": kwargs.get("max_pages")},
        "write_performed": False,
        "active_memory_write_performed": False,
        "error": None,
    }


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


def test_prepare_source_memory_creates_source_draft_via_daemon():
    source_intake = FakeSourceIntakeManager()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        source_intake_manager=source_intake,
    )

    response = api.handle(
        "POST",
        "/v1/prepare_source_memory",
        {
            "source_text": "Decision: route source drafts through daemon.",
            "source_type": "handoff",
            "source_uri": "file:///handoff.md",
            "project": "Engram",
            "domain": "daemon",
            "budget_chars": 4000,
            "pipeline": "handoff",
        },
    )

    assert response["status"] == 200
    assert response["body"]["draft"]["draft_id"] == "draft-a"
    assert response["body"]["error"] is None
    assert source_intake.prepared["source_type"] == "handoff"
    assert source_intake.prepared["pipeline"] == "handoff"


def test_prepare_document_disassembly_routes_to_document_disassembler():
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        document_disassembler=fake_document_disassembler,
    )

    response = api.handle(
        "POST",
        "/v1/prepare_document_disassembly",
        {
            "source_path": "C:/docs/book.pdf",
            "source_type": "pdf",
            "max_pages": 5,
        },
    )

    assert response["status"] == 200
    assert response["body"]["error"] is None
    assert response["body"]["disassembly"]["record_type"] == "document_disassembly_preview"
    assert response["body"]["disassembly"]["source"]["path"] == "C:/docs/book.pdf"
    assert response["body"]["disassembly"]["document"]["page_limit"] == 5


def test_prepare_document_disassembly_returns_structured_invalid_request():
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        document_disassembler=fake_document_disassembler,
    )

    response = api.handle("POST", "/v1/prepare_document_disassembly", {"source_path": ""})

    assert response["status"] == 200
    assert response["body"] == {
        "disassembly": None,
        "error": {
            "code": "invalid_request",
            "message": "source_path is required",
        },
    }


def test_list_source_drafts_reads_daemon_owned_drafts():
    source_intake = FakeSourceIntakeManager()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        source_intake_manager=source_intake,
    )

    response = api.handle(
        "POST",
        "/v1/list_source_drafts",
        {
            "project": "Engram",
            "status": "draft",
            "limit": 10,
            "offset": 2,
        },
    )

    assert response["status"] == 200
    assert response["body"]["count"] == 1
    assert response["body"]["drafts"][0]["draft_id"] == "draft-a"
    assert source_intake.listed == {
        "project": "Engram",
        "status": "draft",
        "limit": 10,
        "offset": 2,
    }


def test_discard_source_draft_marks_daemon_owned_draft_rejected():
    source_intake = FakeSourceIntakeManager()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        source_intake_manager=source_intake,
    )

    response = api.handle(
        "POST",
        "/v1/discard_source_draft",
        {"draft_id": "draft-a"},
    )

    assert response["status"] == 200
    assert response["body"]["discarded"] is True
    assert response["body"]["draft_id"] == "draft-a"
    assert source_intake.discarded == "draft-a"


def test_unknown_route_returns_structured_not_found_error():
    api = EngramDaemonAPI(memory_manager=FakeMemoryManager())

    response = api.handle("POST", "/v1/missing", {})

    assert response["status"] == 404
    assert response["body"]["error"]["code"] == "not_found"
