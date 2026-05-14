from __future__ import annotations

import json

from core.document_pdf_smoke import run_pdf_smoke, summarize_review_packet


def _review_packet(secret_text: str = "DO NOT ECHO THIS BOOK TEXT") -> dict:
    return {
        "status": "ok",
        "source": {"source_path": "C:/tmp/book.pdf", "source_type": "pdf"},
        "disassembly": {
            "status": "ok",
            "source": {"source_path": "C:/tmp/book.pdf", "source_type": "pdf"},
            "document": {
                "document_id": "doc_book",
                "title": "Book",
                "page_count": 2,
                "page_limit": None,
                "media_type": "application/pdf",
                "source_type": "pdf",
                "source_sha256": "abc123",
            },
            "pages": [
                {"page_number": 1, "text": secret_text},
                {"page_number": 2, "text": secret_text},
            ],
            "text": {"content": secret_text, "char_count": len(secret_text)},
            "resume": {"has_more": False},
        },
        "document_preview": {
            "status": "ok",
            "preview": {
                "candidate": {"content": secret_text},
                "chunks": [{"chunk_id": "chunk-1", "text": secret_text}],
                "citations": [{"ref": "document:doc_book:page:1"}],
            },
        },
        "review_completeness": {
            "status": "complete",
            "complete_review": True,
            "open_obligations": [],
            "coverage_missing": [],
            "page_window": {
                "start": 1,
                "end": 2,
                "pages_returned": 2,
                "page_count": 2,
                "has_more": False,
                "next_page": None,
            },
        },
        "coverage_missing": [],
        "receipts": {"artifacts_built": 1, "artifacts_read": 0, "documents_consulted": 1},
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
    }


class FakeDaemonClient:
    def __init__(self) -> None:
        self.prepare_payload = None
        self.store_payload = None

    def prepare_document_artifact_store(self, payload: dict) -> dict:
        self.prepare_payload = payload
        return {
            "status": "ok",
            "artifact_id": "artifact-book",
            "transaction": {"transaction_id": "txn-book", "operation": "document_artifact_store"},
        }

    def store_document_artifact(self, payload: dict) -> dict:
        self.store_payload = payload
        return {
            "status": "ok",
            "artifact_id": "artifact-book",
            "document_id": "doc_book",
            "transaction_id": "txn-book",
            "stored": True,
        }

    def query_knowledge(self, payload: dict) -> dict:
        return {"status": "ok", "citations": [{"ref": "document:doc_book"}], "answer": "summarized"}


def test_summarize_review_packet_excludes_extracted_text() -> None:
    summary = summarize_review_packet(_review_packet())

    encoded = json.dumps(summary)
    assert "DO NOT ECHO THIS BOOK TEXT" not in encoded
    assert summary["document"]["document_id"] == "doc_book"
    assert summary["page_window"]["page_count"] == 2
    assert summary["document_preview"]["chunk_count"] == 1
    assert summary["document_preview"]["citation_count"] == 1


def test_run_pdf_smoke_can_store_artifact_without_echoing_content() -> None:
    client = FakeDaemonClient()

    summary = run_pdf_smoke(
        "C:/tmp/book.pdf",
        full=True,
        store_artifact=True,
        accept=True,
        daemon_client=client,
        review_builder=lambda **_kwargs: _review_packet(),
    )

    assert client.prepare_payload["review_packet"]["disassembly"]["text"]["content"] == "DO NOT ECHO THIS BOOK TEXT"
    assert client.store_payload["accept"] is True
    assert summary["artifact_store"]["prepare_status"] == "ok"
    assert summary["artifact_store"]["store_status"] == "ok"
    assert summary["knowledge_probe"]["status"] == "ok"
    assert "DO NOT ECHO THIS BOOK TEXT" not in json.dumps(summary)
