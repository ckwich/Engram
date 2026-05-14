from __future__ import annotations

import asyncio
import inspect

import server
import server_daemon_client


STABLE_DOCUMENT_WORKFLOW = [
    "list_document_extractors",
    "preview_document_source_connector",
    "prepare_document_disassembly",
    "prepare_document_intake_review",
    "prepare_document_extraction_request",
    "prepare_document_extraction_result",
    "preview_document_extraction",
    "prepare_visual_extraction_request",
    "preview_visual_extraction",
    "prepare_document_understanding_packet",
    "prepare_document_draft",
    "prepare_document_promotion_transaction",
    "apply_document_promotion_transaction",
]


class FakeDaemonClient:
    def __init__(self):
        self.calls = []

    def search_memories(self, payload):
        self.calls.append(("search_memories", payload))
        return {
            "query": payload["query"],
            "count": 1,
            "results": [{"key": "daemon_memory", "chunk_id": 0}],
            "error": None,
        }

    def check_duplicate(self, payload):
        self.calls.append(("check_duplicate", payload))
        return {
            "key": payload["key"],
            "duplicate": True,
            "match": {
                "status": "duplicate",
                "existing_key": "daemon_memory",
                "existing_title": "Daemon Memory",
                "score": 0.97,
            },
            "error": None,
        }

    def retrieve_chunk(self, payload):
        self.calls.append(("retrieve_chunk", payload))
        return {
            "key": payload["key"],
            "chunk_id": payload["chunk_id"],
            "found": True,
            "chunk": {"title": "Daemon Memory", "text": "chunk"},
            "error": None,
        }

    def retrieve_chunks(self, payload):
        self.calls.append(("retrieve_chunks", payload))
        return {
            "requested_count": len(payload["requests"]),
            "found_count": 1,
            "results": [
                {
                    "key": payload["requests"][0]["key"],
                    "chunk_id": payload["requests"][0]["chunk_id"],
                    "found": True,
                    "chunk": {"title": "Daemon Memory", "text": "chunk"},
                    "error": None,
                }
            ],
            "error": None,
        }

    def retrieve_memory(self, payload):
        self.calls.append(("retrieve_memory", payload))
        return {
            "key": payload["key"],
            "found": True,
            "memory": {"key": payload["key"], "title": "Daemon Memory", "content": "body"},
            "error": None,
        }

    def store_memory(self, payload):
        self.calls.append(("store_memory", payload))
        return {
            "stored": True,
            "result": {
                "key": payload["key"],
                "title": payload["title"],
                "chunk_count": 1,
                "chars": len(payload["content"]),
            },
            "error": None,
        }

    def update_memory_metadata(self, payload):
        self.calls.append(("update_memory_metadata", payload))
        return {
            "key": payload["key"],
            "updated": True,
            "memory": {
                "key": payload["key"],
                "title": payload["title"],
                "tags": payload["tags"],
            },
            "error": None,
        }

    def repair_memory_metadata(self, payload):
        self.calls.append(("repair_memory_metadata", payload))
        return {
            "requested_count": len(payload["keys"]),
            "repaired_count": 0 if payload.get("dry_run", True) else len(payload["keys"]),
            "dry_run": payload.get("dry_run", True),
            "repairs": [{"key": key, "repaired": not payload.get("dry_run", True)} for key in payload["keys"]],
            "error": None,
        }

    def prepare_source_memory(self, payload):
        self.calls.append(("prepare_source_memory", payload))
        return {
            "draft": {
                "draft_id": "draft-a",
                "proposed_memories": [{"key": "daemon_source_memory"}],
                "proposed_edges": [],
            },
            "error": None,
        }

    def prepare_document_disassembly(self, payload):
        self.calls.append(("prepare_document_disassembly", payload))
        return {
            "disassembly": {
                "record_type": "document_disassembly_preview",
                "source": {"path": payload["source_path"]},
                "document": {"page_limit": payload.get("max_pages")},
                "write_performed": False,
                "active_memory_write_performed": False,
                "error": None,
            },
            "error": None,
        }

    def prepare_document_intake_review(self, payload):
        self.calls.append(("prepare_document_intake_review", payload))
        return {
            "status": "ok",
            "source": {"source_path": payload["source_path"], "document_id": "doc_1"},
            "disassembly": {"record_type": "document_disassembly_preview"},
            "extraction_request": None,
            "document_preview": {"preview": {"document": {"document_id": "doc_1"}}},
            "quality": {},
            "artifact_manifest": {},
            "draft_candidates": [],
            "promotion_guidance": {"auto_promote": False},
            "policy": {
                "write_behavior": "read_only",
                "active_memory_promoted": False,
                "graph_edges_promoted": False,
            },
            "receipts": {"artifacts_built": 1, "artifacts_read": 0, "coverage_missing": []},
            "error": None,
        }

    def list_document_extractors(self, payload):
        self.calls.append(("list_document_extractors", payload))
        return {"catalog": {"extractors": [{"id": "fake"}]}, "error": None}

    def preview_document_source_connector(self, payload):
        self.calls.append(("preview_document_source_connector", payload))
        return {"preview": {"items": []}, "error": None}

    def prepare_document_extraction_request(self, payload):
        self.calls.append(("prepare_document_extraction_request", payload))
        return {"request": {"source_ref": payload["source_ref"]}, "error": None}

    def prepare_document_extraction_result(self, payload):
        self.calls.append(("prepare_document_extraction_result", payload))
        return {"result": {"title": payload["title"]}, "error": None}

    def preview_document_extraction(self, payload):
        self.calls.append(("preview_document_extraction", payload))
        return {"preview": {"document": {"title": payload["title"]}}, "error": None}

    def prepare_visual_extraction_request(self, payload):
        self.calls.append(("prepare_visual_extraction_request", payload))
        return {"request": {"document_id": payload["document_record"]["document_id"]}, "error": None}

    def preview_visual_extraction(self, payload):
        self.calls.append(("preview_visual_extraction", payload))
        return {"preview": {"visual_artifacts": payload["observations"]}, "error": None}

    def prepare_document_understanding_packet(self, payload):
        self.calls.append(("prepare_document_understanding_packet", payload))
        return {"packet": {"document_id": payload["document_record"]["document_id"]}, "error": None}

    def prepare_document_draft(self, payload):
        self.calls.append(("prepare_document_draft", payload))
        return {"draft": {"document_id": payload["document_record"]["document_id"]}, "error": None}

    def prepare_document_promotion_transaction(self, payload):
        self.calls.append(("prepare_document_promotion_transaction", payload))
        return {"transaction": {"approved_by": payload["approved_by"]}, "error": None}

    def apply_document_promotion_transaction(self, payload):
        self.calls.append(("apply_document_promotion_transaction", payload))
        return {
            "status": "ok" if payload.get("accept") else "policy_denied",
            "write_performed": bool(payload.get("accept")),
            "active_memory_write_performed": bool(payload.get("accept")),
            "graph_write_performed": False,
            "error": None,
        }

    def prepare_document_artifact_store(self, payload):
        self.calls.append(("prepare_document_artifact_store", payload))
        return {
            "status": "prepared",
            "prepared_transaction_id": "txn-doc",
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None,
        }

    def store_document_artifact(self, payload):
        self.calls.append(("store_document_artifact", payload))
        return {
            "status": "ok" if payload.get("accept") else "policy_denied",
            "stored": bool(payload.get("accept")),
            "write_performed": bool(payload.get("accept")),
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None,
        }

    def list_source_drafts(self, payload):
        self.calls.append(("list_source_drafts", payload))
        return {
            "count": 1,
            "total": 1,
            "limit": payload["limit"],
            "offset": payload["offset"],
            "has_more": False,
            "drafts": [{"draft_id": "draft-a"}],
            "error": None,
        }

    def discard_source_draft(self, payload):
        self.calls.append(("discard_source_draft", payload))
        return {"discarded": True, "draft_id": payload["draft_id"], "error": None}

    def store_prepared_memory(self, payload):
        self.calls.append(("store_prepared_memory", payload))
        return {
            "stored_count": 1,
            "stored": [
                {
                    "index": 0,
                    "key": "daemon_source_memory",
                    "result": {"key": "daemon_source_memory", "chunk_count": 1},
                }
            ],
            "skipped": [],
            "error": None,
        }

    def delete_memory(self, payload):
        self.calls.append(("delete_memory", payload))
        return {"key": payload["key"], "deleted": True, "error": None}

    def query_knowledge(self, payload):
        self.calls.append(("query_knowledge", payload))
        return {
            "contract_version": "engram.knowledge.response.v0",
            "request_id": payload["request_id"],
            "status": "ok",
            "answer": {"project": payload["ask"]["project"]},
            "citations": [
                {
                    "citation_id": "cit_001",
                    "level": "chunk",
                    "source": "memory_os",
                    "key": "engram_direction",
                    "chunk_id": 0,
                }
            ],
            "freshness": {"state": "fresh"},
            "policy": {
                "unreviewed_sources_used": False,
                "unsupported_inferences_used": False,
                "review_state_available": False,
                "review_filter_enforced": False,
                "review_state_basis": "not_available_in_current_memory_os_records",
            },
            "budget_used": {
                "artifacts_built": 1,
                "artifacts_read": 0,
                "source_reads": 0,
                "tokens_out_estimate": 0,
            },
            "planner": {
                "strategy": "project_capsule",
                "methods_used": ["artifact"],
                "omissions": [],
                "budget": {
                    "requested": {"max_artifacts": 1, "max_source_reads": 12, "max_tokens_out": 2500},
                    "used": {
                        "artifacts_built": 1,
                        "artifacts_read": 0,
                        "source_reads": 0,
                        "tokens_out_estimate": 0,
                    },
                },
                "failure_receipts": [],
                "response_status": "ok",
            },
            "errors": [],
        }


def test_search_memories_uses_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    result = asyncio.run(server.search_memories("daemon check", retrieval_mode="hybrid"))

    assert result["results"][0]["key"] == "daemon_memory"
    assert client.calls[0][0] == "search_memories"
    assert client.calls[0][1]["retrieval_mode"] == "hybrid"


def test_check_duplicate_uses_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    payload = asyncio.run(server.check_duplicate("candidate_memory", "Candidate body"))

    assert payload["duplicate"] is True
    assert payload["match"]["existing_key"] == "daemon_memory"
    assert client.calls == [
        (
            "check_duplicate",
            {"key": "candidate_memory", "content": "Candidate body"},
        )
    ]


def test_read_tools_use_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    chunk = asyncio.run(server.retrieve_chunk("daemon_memory", 0))
    chunks = asyncio.run(server.retrieve_chunks([{"key": "daemon_memory", "chunk_id": 0}]))
    memory = asyncio.run(server.retrieve_memory("daemon_memory"))

    assert chunk["chunk"]["text"] == "chunk"
    assert chunks["found_count"] == 1
    assert memory["memory"]["content"] == "body"
    assert [call[0] for call in client.calls] == [
        "retrieve_chunk",
        "retrieve_chunks",
        "retrieve_memory",
    ]


def test_write_and_delete_tools_use_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    stored = asyncio.run(
        server.store_memory(
            key="daemon_memory",
            content="Daemon body.",
            title="Daemon Memory",
            tags=["daemon"],
            force=True,
        )
    )
    deleted = asyncio.run(server.delete_memory("daemon_memory"))

    assert "Stored: 'Daemon Memory'" in stored
    assert "Deleted memory: 'daemon_memory'" in deleted
    assert [call[0] for call in client.calls] == ["store_memory", "delete_memory"]


def test_query_knowledge_uses_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    payload = asyncio.run(
        server.query_knowledge(
            {
                "request_id": "req-server",
                "ask": {
                    "goal": "Get context.",
                    "task_type": "project_orientation",
                    "project": "Engram",
                },
            }
        )
    )

    assert payload["request_id"] == "req-server"
    assert payload["answer"]["project"] == "Engram"
    assert client.calls[-1][0] == "query_knowledge"


def test_update_memory_metadata_uses_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    payload = asyncio.run(
        server.update_memory_metadata(
            key="daemon_memory",
            title="Updated Daemon Memory",
            tags=["daemon", "metadata"],
        )
    )

    assert payload["updated"] is True
    assert payload["memory"]["title"] == "Updated Daemon Memory"
    assert client.calls == [
        (
            "update_memory_metadata",
            {
                "key": "daemon_memory",
                "title": "Updated Daemon Memory",
                "tags": ["daemon", "metadata"],
            },
        )
    ]


def test_repair_memory_metadata_uses_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    payload = asyncio.run(
        server.repair_memory_metadata(keys="daemon_memory", dry_run=False)
    )

    assert payload["repaired_count"] == 1
    assert payload["dry_run"] is False
    assert client.calls == [
        (
            "repair_memory_metadata",
            {"keys": ["daemon_memory"], "dry_run": False},
        )
    ]


def test_store_prepared_memory_uses_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    payload = asyncio.run(
        server.store_prepared_memory("draft-a", selected_items=[0], force=True)
    )

    assert payload["stored_count"] == 1
    assert payload["stored"][0]["key"] == "daemon_source_memory"
    assert client.calls == [
        (
            "store_prepared_memory",
            {"draft_id": "draft-a", "selected_items": [0], "force": True},
        )
    ]


def test_source_draft_lifecycle_uses_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    prepared = asyncio.run(
        server.prepare_source_memory(
            source_text="Decision: daemon owns source draft lifecycle.",
            source_type="handoff",
            source_uri="file:///handoff.md",
            project="Engram",
            domain="daemon",
            budget_chars=4000,
            pipeline="handoff",
        )
    )
    drafts = asyncio.run(
        server.list_source_drafts(project="Engram", status="draft", limit=10, offset=2)
    )
    discarded = asyncio.run(server.discard_source_draft("draft-a"))

    assert prepared["draft"]["draft_id"] == "draft-a"
    assert drafts["drafts"][0]["draft_id"] == "draft-a"
    assert discarded["discarded"] is True
    assert client.calls == [
        (
            "prepare_source_memory",
            {
                "source_text": "Decision: daemon owns source draft lifecycle.",
                "source_type": "handoff",
                "source_uri": "file:///handoff.md",
                "project": "Engram",
                "domain": "daemon",
                "budget_chars": 4000,
                "pipeline": "handoff",
            },
        ),
        (
            "list_source_drafts",
            {"project": "Engram", "status": "draft", "limit": 10, "offset": 2},
        ),
        ("discard_source_draft", {"draft_id": "draft-a"}),
    ]


def test_prepare_document_disassembly_uses_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    payload = asyncio.run(server.prepare_document_disassembly("C:/docs/book.pdf", max_pages=5))

    assert payload["error"] is None
    assert payload["disassembly"]["record_type"] == "document_disassembly_preview"
    assert client.calls == [
        (
            "prepare_document_disassembly",
            {
                "source_path": "C:/docs/book.pdf",
                "source_type": "pdf",
                "max_pages": 5,
                "page_range": None,
                "resume_token": None,
            },
        )
    ]


def test_document_intelligence_tools_use_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    document_record = {"document_id": "doc_1", "title": "Daemon Doc"}
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    asyncio.run(server.list_document_extractors())
    asyncio.run(server.preview_document_source_connector("local_path", "docs"))
    asyncio.run(server.prepare_document_intake_review("C:/docs/book.pdf"))
    asyncio.run(
        server.prepare_document_extraction_request(
            source_ref={"source_uri": "file:///book.pdf"},
            source_type="pdf",
            requested_outputs=["markdown"],
        )
    )
    asyncio.run(
        server.prepare_document_extraction_result(
            extraction_request={
                "request_id": "doc_req_1",
                "source_ref": {"source_uri": "file:///book.pdf"},
                "source_type": "pdf",
            },
            title="Daemon Book",
            content="Body",
            media_type="text/markdown",
        )
    )
    asyncio.run(
        server.preview_document_extraction(
            title="Daemon Book",
            source_uri="file:///book.pdf",
            source_type="pdf",
            content="Body",
            media_type="text/markdown",
        )
    )
    asyncio.run(
        server.prepare_visual_extraction_request(
            document_record=document_record,
            image_refs=[{"image_ref": "page:1"}],
            requested_capabilities=["ocr_text"],
        )
    )
    asyncio.run(
        server.preview_visual_extraction(
            document_record=document_record,
            observations=[
                {
                    "artifact_type": "ocr_block",
                    "source_ref": {"image_ref": "page:1"},
                    "text": "OCR",
                }
            ],
        )
    )
    asyncio.run(server.prepare_document_understanding_packet(document_record, {"summary": ["Summary"]}))
    asyncio.run(server.prepare_document_draft(document_record, {"summary": ["Summary"]}))
    asyncio.run(
        server.prepare_document_promotion_transaction(
            {"draft_id": "draft_1", "proposed_memories": [{"key": "doc"}], "proposed_edges": []},
            approved_by="reviewer",
            selected_memory_indexes=[0],
        )
    )
    asyncio.run(
        server.apply_document_promotion_transaction(
            {"transaction_id": "doc_promote_1"},
            accept=True,
            approved_by="reviewer",
            selected_operation_indexes=[0],
        )
    )

    assert [call[0] for call in client.calls] == [
        "list_document_extractors",
        "preview_document_source_connector",
        "prepare_document_intake_review",
        "prepare_document_extraction_request",
        "prepare_document_extraction_result",
        "preview_document_extraction",
        "prepare_visual_extraction_request",
        "preview_visual_extraction",
        "prepare_document_understanding_packet",
        "prepare_document_draft",
        "prepare_document_promotion_transaction",
        "apply_document_promotion_transaction",
    ]


def test_document_artifact_tools_use_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    prepared = asyncio.run(server.prepare_document_artifact_store({"status": "ok"}))
    stored = asyncio.run(server.store_document_artifact("txn-doc", accept=True, review_packet={"status": "ok"}))

    assert prepared["prepared_transaction_id"] == "txn-doc"
    assert stored["stored"] is True
    assert client.calls == [
        (
            "prepare_document_artifact_store",
            {"review_packet": {"status": "ok"}, "artifact_family": "document_evidence"},
        ),
        (
            "store_document_artifact",
            {
                "prepared_transaction_id": "txn-doc",
                "accept": True,
                "review_packet": {"status": "ok"},
            },
        ),
    ]


def test_daemon_client_protocol_advertises_stable_document_workflow():
    protocol = server_daemon_client.memory_protocol()

    assert protocol["document_workflow"] == STABLE_DOCUMENT_WORKFLOW
    assert protocol["tool_groups"]["document_intelligence"] == {
        "stability": "stable",
        "cost_class": "low-to-medium",
        "tools": STABLE_DOCUMENT_WORKFLOW,
    }
    assert set(STABLE_DOCUMENT_WORKFLOW).issubset(set(protocol["canonical_tools"]))


def test_daemon_client_document_tool_docstrings_preserve_no_write_contract():
    write_tools = {"apply_document_promotion_transaction"}
    for tool_name in [tool for tool in STABLE_DOCUMENT_WORKFLOW if tool not in write_tools]:
        doc = inspect.getdoc(getattr(server_daemon_client, tool_name))

        assert doc is not None
        normalized = doc.lower()
        assert "no-write" in normalized or "does not write" in normalized
        assert "promot" in normalized

    apply_doc = inspect.getdoc(server_daemon_client.apply_document_promotion_transaction) or ""
    assert "write" in apply_doc.lower()
    assert "accept=True" in apply_doc
    assert "explicit" in apply_doc.lower()
