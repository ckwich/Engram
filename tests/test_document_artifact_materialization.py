from __future__ import annotations

import hashlib
import json

from core.memory_os._records import list_records, read_record
from core.memory_os.runtime import MemoryOSRuntime


def _review_packet(tmp_path):
    source = tmp_path / "book.pdf"
    source_bytes = b"%PDF-1.4 synthetic document"
    source.write_bytes(source_bytes)
    content_hash = "sha256:" + hashlib.sha256(source_bytes).hexdigest()
    return {
        "record_type": "document_intake_review",
        "status": "partial",
        "source": {
            "source_path": str(source),
            "source_uri": source.resolve().as_uri(),
            "source_type": "pdf",
            "media_type": "application/pdf",
            "document_id": "doc_book",
            "sha256": content_hash,
        },
        "disassembly": {
            "record_type": "document_disassembly_preview",
            "write_performed": False,
            "active_memory_write_performed": False,
            "source": {
                "source_uri": source.resolve().as_uri(),
                "path": str(source),
                "source_type": "pdf",
                "media_type": "application/pdf",
                "content_hash": content_hash,
            },
            "document": {
                "document_id": "doc_book",
                "title": "Book",
                "source_type": "pdf",
                "media_type": "application/pdf",
                "content_hash": content_hash,
                "page_count": 2,
                "page_limit": 2,
            },
            "pages": [
                {"page_number": 1, "text_status": "text", "visual_review_needed": False},
                {"page_number": 2, "text_status": "no_text", "visual_review_needed": True},
            ],
            "text": {
                "content": "# Book\n\nUseful text.",
                "char_count": 20,
                "page_count": 1,
            },
            "image_inventory": {"image_count": 1, "pages_with_images": [2]},
            "quality_seed": {
                "text_pages": [1],
                "no_text_pages": [2],
                "image_pages": [2],
                "visual_review_needed_pages": [2],
            },
            "quality_report": {
                "record_type": "document_quality_report",
                "warnings": [{"code": "missing_ocr", "page_number": 2}],
            },
            "artifact_manifest": {
                "record_type": "document_artifact_manifest",
                "manifest_id": "doc_manifest_book",
                "document_id": "doc_book",
                "portable_refs_only": True,
                "artifacts": {
                    "raw_source": {
                        "artifact_type": "raw_source",
                        "content_hash": content_hash,
                        "ref": "document_artifacts/sources/aa/book.pdf",
                    }
                },
                "pages": [
                    {
                        "page_number": 1,
                        "state": "text_extracted",
                        "text_artifact": {
                            "artifact_type": "page_text",
                            "content_hash": "sha256:" + "b" * 64,
                            "ref": "document_artifacts/page_texts/bb/page.txt",
                        },
                    }
                ],
            },
            "visual_extraction_request": {
                "record_type": "visual_extraction_request",
                "request_id": "vis_req_book",
                "document_id": "doc_book",
                "image_refs": [{"page_number": 2, "image_ref": "page:2"}],
                "requested_capabilities": ["ocr_text", "table_structure"],
            },
            "promotion_guidance": {"auto_promote": False},
            "error": None,
        },
        "extraction_request": {
            "record_type": "visual_extraction_request",
            "request_id": "vis_req_book",
            "document_id": "doc_book",
            "image_refs": [{"page_number": 2, "image_ref": "page:2"}],
            "requested_capabilities": ["ocr_text", "table_structure"],
        },
        "quality": {"warnings": [{"code": "missing_ocr", "page_number": 2}]},
        "artifact_manifest": {
            "record_type": "document_artifact_manifest",
            "manifest_id": "doc_manifest_book",
            "document_id": "doc_book",
            "portable_refs_only": True,
            "artifacts": {
                "raw_source": {
                    "artifact_type": "raw_source",
                    "content_hash": content_hash,
                    "ref": "document_artifacts/sources/aa/book.pdf",
                }
            },
            "pages": [
                {
                    "page_number": 1,
                    "state": "text_extracted",
                    "text_artifact": {
                        "artifact_type": "page_text",
                        "content_hash": "sha256:" + "b" * 64,
                        "ref": "document_artifacts/page_texts/bb/page.txt",
                    },
                }
            ],
        },
        "draft_candidates": [],
        "promotion_guidance": {"auto_promote": False},
        "policy": {
            "write_behavior": "read_only",
            "active_memory_promoted": False,
            "graph_edges_promoted": False,
        },
        "receipts": {
            "artifacts_built": 1,
            "artifacts_read": 0,
            "coverage_missing": ["ocr", "table", "visual"],
        },
        "error": None,
    }


def test_prepare_document_artifact_store_records_reviewable_transaction_without_artifact_writes(tmp_path):
    runtime = MemoryOSRuntime(tmp_path / "memory_os")
    runtime.initialize()

    prepared = runtime.prepare_document_artifact_store(_review_packet(tmp_path))

    assert prepared["status"] == "prepared"
    assert prepared["write_performed"] is False
    assert prepared["active_memory_write_performed"] is False
    assert prepared["graph_write_performed"] is False
    assert prepared["receipts"]["artifacts_built"] == 1
    assert prepared["receipts"]["artifacts_read"] == 0
    assert prepared["prepared_transaction_id"].startswith("doc_artifact_txn:doc_book:")
    assert prepared["artifact_preview"]["document_id"] == "doc_book"
    assert prepared["artifact_preview"]["artifact_id"].startswith("doc_artifact:doc_book:")
    assert prepared["artifact_preview"]["coverage_receipt"]["coverage_missing"] == ["ocr", "table", "visual"]
    assert list_records(runtime.ledger, "knowledge_artifacts") == []
    assert list_records(runtime.ledger, "memories") == []
    assert list_records(runtime.ledger, "graph_edges") == []

    transaction = read_record(runtime.ledger, "transactions", prepared["prepared_transaction_id"])
    assert transaction is not None
    assert transaction["status"] == "prepared"
    assert transaction["operation_kind"] == "document_artifact_store"
    assert "review_packet" not in transaction
    assert transaction["review_context"]["document"]["document_id"] == "doc_book"
    assert transaction["review_context"]["text"]["char_count"] == 20
    assert transaction["review_packet_sha256"] == prepared["review_packet_sha256"]
    transaction_json = json.dumps(transaction, sort_keys=True)
    assert "# Book" not in transaction_json
    assert "Useful text." not in transaction_json


def test_store_document_artifact_requires_accept_and_keeps_memory_and_graph_unchanged(tmp_path):
    runtime = MemoryOSRuntime(tmp_path / "memory_os")
    runtime.initialize()
    prepared = runtime.prepare_document_artifact_store(_review_packet(tmp_path))

    denied = runtime.store_document_artifact(prepared["prepared_transaction_id"], accept=False)

    assert denied["status"] == "policy_denied"
    assert denied["write_performed"] is False
    assert list_records(runtime.ledger, "knowledge_artifacts") == []

    review_packet = _review_packet(tmp_path)
    stored = runtime.store_document_artifact(
        prepared["prepared_transaction_id"],
        accept=True,
        review_packet=review_packet,
    )

    assert stored["status"] == "ok"
    assert stored["write_performed"] is True
    assert stored["active_memory_write_performed"] is False
    assert stored["graph_write_performed"] is False
    assert stored["receipts"]["artifacts_read"] == 1
    assert read_record(runtime.ledger, "documents", "doc_book") is not None
    assert list_records(runtime.ledger, "chunks")
    assert list_records(runtime.ledger, "retrieval_receipts")
    assert list_records(runtime.ledger, "knowledge_artifacts")
    assert list_records(runtime.ledger, "memories") == []
    assert list_records(runtime.ledger, "graph_edges") == []

    artifact = list_records(runtime.ledger, "knowledge_artifacts")[0]
    assert artifact["document_id"] == "doc_book"
    assert artifact["artifact_id"].startswith("doc_artifact:doc_book:")
    assert artifact["artifact_type"] == "document_evidence"
    assert artifact["source_sha256"] == review_packet["source"]["sha256"]
    assert artifact["review_state"] == "ledgered_evidence"
    assert artifact["coverage_receipt"]["coverage_missing"] == ["ocr", "table", "visual"]


def test_store_document_artifact_requires_review_packet_for_compact_transaction(tmp_path):
    runtime = MemoryOSRuntime(tmp_path / "memory_os")
    runtime.initialize()
    prepared = runtime.prepare_document_artifact_store(_review_packet(tmp_path))

    stored = runtime.store_document_artifact(prepared["prepared_transaction_id"], accept=True)

    assert stored["status"] == "schema_failed"
    assert stored["error"]["code"] == "review_packet_required"
    assert list_records(runtime.ledger, "knowledge_artifacts") == []


def test_store_document_artifact_rejects_changed_source_bytes(tmp_path):
    runtime = MemoryOSRuntime(tmp_path / "memory_os")
    runtime.initialize()
    review = _review_packet(tmp_path)
    prepared = runtime.prepare_document_artifact_store(review)
    source_path = review["source"]["source_path"]
    with open(source_path, "wb") as handle:
        handle.write(b"%PDF-1.4 edited after review")

    stored = runtime.store_document_artifact(
        prepared["prepared_transaction_id"],
        accept=True,
        review_packet=review,
    )

    assert stored["status"] == "schema_failed"
    assert stored["error"]["code"] == "source_hash_mismatch"
    assert list_records(runtime.ledger, "knowledge_artifacts") == []


def test_prepare_document_artifact_store_returns_stable_policy_error_codes(tmp_path):
    runtime = MemoryOSRuntime(tmp_path / "memory_os")
    runtime.initialize()
    review = _review_packet(tmp_path)
    review["policy"]["write_behavior"] = "write"

    prepared = runtime.prepare_document_artifact_store(review)

    assert prepared["status"] == "schema_failed"
    assert prepared["error"]["code"] == "policy_write_behavior_not_read_only"
    assert prepared["error"]["category"] == "validation"


def test_store_document_artifact_accept_is_idempotent(tmp_path):
    runtime = MemoryOSRuntime(tmp_path / "memory_os")
    runtime.initialize()
    review = _review_packet(tmp_path)
    prepared = runtime.prepare_document_artifact_store(review)

    first = runtime.store_document_artifact(
        prepared["prepared_transaction_id"],
        accept=True,
        review_packet=review,
    )
    job_count = len(list_records(runtime.ledger, "jobs"))
    event_count = len(list_records(runtime.ledger, "job_events"))
    second = runtime.store_document_artifact(
        prepared["prepared_transaction_id"],
        accept=True,
        review_packet=review,
    )

    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert second["idempotent_replay"] is True
    assert second["artifact"]["artifact_id"] == first["artifact"]["artifact_id"]
    assert len(list_records(runtime.ledger, "jobs")) == job_count
    assert len(list_records(runtime.ledger, "job_events")) == event_count


def test_prepare_document_artifact_store_rejects_manifest_path_escape(tmp_path):
    runtime = MemoryOSRuntime(tmp_path / "memory_os")
    runtime.initialize()
    review = _review_packet(tmp_path)
    review["artifact_manifest"]["pages"][0]["text_artifact"]["ref"] = "../../escape.txt"

    prepared = runtime.prepare_document_artifact_store(review)

    assert prepared["status"] == "schema_failed"
    assert prepared["error"]["code"] == "invalid_artifact_ref"
    assert prepared["error"]["category"] == "validation"
    assert list_records(runtime.ledger, "transactions") == []
