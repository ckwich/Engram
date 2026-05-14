from __future__ import annotations

from core.memory_os.knowledge_contract import validate_knowledge_response
from core.memory_os.runtime import MemoryOSRuntime


def _review_packet(tmp_path):
    source = tmp_path / "book.pdf"
    source.write_bytes(b"%PDF-1.4 synthetic")
    content_hash = "sha256:" + "a" * 64
    return {
        "record_type": "document_intake_review",
        "status": "partial",
        "source": {
            "source_path": str(source),
            "source_uri": source.resolve().as_uri(),
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
                "title": "Design Book",
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
            "text": {"content": "# Design\n\nMotion beats static detail.", "char_count": 37},
            "image_inventory": {"image_count": 1, "pages_with_images": [2]},
            "quality_seed": {
                "text_pages": [1],
                "no_text_pages": [2],
                "visual_review_needed_pages": [2],
            },
            "artifact_manifest": {
                "record_type": "document_artifact_manifest",
                "artifacts": {
                    "raw_source": {
                        "artifact_type": "raw_source",
                        "content_hash": content_hash,
                        "ref": "document_artifacts/sources/aa/book.pdf",
                    }
                },
                "pages": [],
            },
            "error": None,
        },
        "extraction_request": {
            "request_id": "vis_req_book",
            "document_id": "doc_book",
            "requested_capabilities": ["ocr_text", "table_structure"],
        },
        "quality": {"warnings": []},
        "artifact_manifest": {
            "record_type": "document_artifact_manifest",
            "artifacts": {
                "raw_source": {
                    "artifact_type": "raw_source",
                    "content_hash": content_hash,
                    "ref": "document_artifacts/sources/aa/book.pdf",
                }
            },
            "pages": [],
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


def test_query_knowledge_document_orientation_reads_ledgered_document_artifacts(tmp_path):
    runtime = MemoryOSRuntime(tmp_path / "memory_os")
    runtime.initialize()
    prepared = runtime.prepare_document_artifact_store(_review_packet(tmp_path))
    runtime.store_document_artifact(prepared["prepared_transaction_id"], accept=True)

    response = runtime.query_knowledge(
        {
            "request_id": "req-doc-orientation",
            "ask": {
                "goal": "Orient to design book evidence.",
                "task_type": "document_orientation",
                "project": "Engram",
                "focus": ["Design"],
            },
        }
    )

    assert response["status"] == "ok"
    assert response["answer"]["document_count"] == 1
    assert response["answer"]["document_evidence_artifact_count"] == 1
    assert response["answer"]["documents"][0]["document_id"] == "doc_book"
    assert response["budget_used"]["artifacts_read"] == 1
    assert response["citations"][0]["level"] == "document"
    assert validate_knowledge_response(response)["valid"] is True
