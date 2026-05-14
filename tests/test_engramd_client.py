from __future__ import annotations

import json
import subprocess
import sys

from core.engramd_client import EngramDaemonClient


class FakeTransport:
    def __init__(self):
        self.calls = []

    def request_json(self, method, url, payload=None, timeout=10.0):
        self.calls.append((method, url, payload, timeout))
        return {"ok": True, "url": url, "payload": payload}


def test_client_posts_search_to_v1_endpoint():
    transport = FakeTransport()
    client = EngramDaemonClient("http://127.0.0.1:8765/", transport=transport)

    result = client.search_memories({"query": "agent memory"})

    assert result["ok"] is True
    assert transport.calls == [
        (
            "POST",
            "http://127.0.0.1:8765/v1/search_memories",
            {"query": "agent memory"},
            10.0,
        )
    ]


def test_client_gets_health_endpoint():
    transport = FakeTransport()
    client = EngramDaemonClient("http://127.0.0.1:8765", timeout=3.5, transport=transport)

    client.health()

    assert transport.calls == [
        ("GET", "http://127.0.0.1:8765/health", None, 3.5)
    ]


def test_client_methods_map_to_daemon_routes():
    transport = FakeTransport()
    client = EngramDaemonClient("http://127.0.0.1:8765", transport=transport)

    client.retrieve_chunk({"key": "k", "chunk_id": 0})
    client.retrieve_chunks({"requests": [{"key": "k", "chunk_id": 0}]})
    client.retrieve_memory({"key": "k"})
    client.store_memory({"key": "k", "content": "body"})
    client.check_duplicate({"key": "k", "content": "body"})
    client.update_memory_metadata({"key": "k", "title": "Updated"})
    client.repair_memory_metadata({"keys": ["k"], "dry_run": False})
    client.prepare_source_memory({"source_text": "body", "source_type": "note"})
    client.prepare_document_disassembly({"source_path": "C:/docs/book.pdf", "source_type": "pdf", "max_pages": 5})
    client.memory_os_status()
    client.memory_os_inspector()
    client.memory_os_source_import_job({"source_ref": {"source_uri": "file:///book.pdf"}})
    client.list_source_drafts(
        {"project": "Engram", "status": "draft", "limit": 10, "offset": 0}
    )
    client.discard_source_draft({"draft_id": "draft-a"})
    client.store_prepared_memory({"draft_id": "draft-a", "selected_items": [0], "force": True})
    client.delete_memory({"key": "k"})

    assert [call[1].rsplit("/", 1)[-1] for call in transport.calls] == [
        "retrieve_chunk",
        "retrieve_chunks",
        "retrieve_memory",
        "store_memory",
        "check_duplicate",
        "update_memory_metadata",
        "repair_memory_metadata",
        "prepare_source_memory",
        "prepare_document_disassembly",
        "status",
        "inspector",
        "source_import_job",
        "list_source_drafts",
        "discard_source_draft",
        "store_prepared_memory",
        "delete_memory",
    ]


def test_client_document_methods_map_to_stable_daemon_routes():
    transport = FakeTransport()
    client = EngramDaemonClient("http://127.0.0.1:8765", transport=transport)

    client.list_document_extractors({})
    client.preview_document_source_connector({"connector_type": "local_path", "target": "docs"})
    client.prepare_document_disassembly({"source_path": "C:/docs/book.pdf"})
    client.prepare_document_intake_review({"source_path": "C:/docs/book.pdf"})
    client.prepare_document_extraction_request({"source_ref": {"source_uri": "file:///book.pdf"}})
    client.prepare_document_extraction_result({"title": "Book", "content": "body"})
    client.preview_document_extraction({"title": "Book", "content": "body"})
    client.prepare_visual_extraction_request({"document_record": {}, "image_refs": []})
    client.preview_visual_extraction({"document_record": {}, "observations": []})
    client.prepare_document_understanding_packet({"document_record": {}, "analysis": {}})
    client.prepare_document_draft({"document_record": {}, "analysis": {}})
    client.prepare_document_promotion_transaction({"document_draft": {}, "approved_by": "reviewer"})
    client.prepare_document_artifact_store({"review_packet": {}})
    client.store_document_artifact({"prepared_transaction_id": "txn", "accept": True})

    assert [call[1].rsplit("/", 1)[-1] for call in transport.calls] == [
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
        "prepare_document_artifact_store",
        "store_document_artifact",
    ]


def test_engramd_help_exposes_daemon_options():
    result = subprocess.run(
        [sys.executable, "engramd.py", "--help"],
        cwd=".",
        capture_output=True,
        text=True,
        check=True,
    )

    assert "--host" in result.stdout
    assert "--port" in result.stdout
    assert "--health" in result.stdout
    assert "--smoke-test" in result.stdout
    assert "--doctor" in result.stdout
    assert "--stop-server-pid" in result.stdout


def test_engramd_client_query_knowledge_posts_contract_request():
    calls = []

    class FakeTransport:
        def request_json(self, method, url, payload=None, timeout=10.0):
            calls.append((method, url, payload, timeout))
            return {"status": "ok", "request_id": payload["request_id"]}

    client = EngramDaemonClient(
        "http://127.0.0.1:8765",
        transport=FakeTransport(),
    )

    response = client.query_knowledge(
        {
            "request_id": "req-client",
            "ask": {"project": "Engram", "task_type": "project_orientation"},
        }
    )

    assert response["request_id"] == "req-client"
    assert calls == [
        (
            "POST",
            "http://127.0.0.1:8765/v1/query_knowledge",
            {
                "request_id": "req-client",
                "ask": {"project": "Engram", "task_type": "project_orientation"},
            },
            10.0,
        )
    ]
