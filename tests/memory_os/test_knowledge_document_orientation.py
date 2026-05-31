from __future__ import annotations

import hashlib

from core.memory_os.knowledge_contract import validate_knowledge_response
from core.memory_os.runtime import MemoryOSRuntime


def _review_packet(tmp_path):
    source = tmp_path / "book.pdf"
    source_bytes = b"%PDF-1.4 synthetic"
    source.write_bytes(source_bytes)
    content_hash = "sha256:" + hashlib.sha256(source_bytes).hexdigest()
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
                "title": "Evil by Design",
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


def test_query_knowledge_document_orientation_marks_staged_artifacts_partial(tmp_path):
    runtime = MemoryOSRuntime(tmp_path / "memory_os")
    runtime.initialize()
    review = _review_packet(tmp_path)
    prepared = runtime.prepare_document_artifact_store(review)
    runtime.store_document_artifact(prepared["prepared_transaction_id"], accept=True, review_packet=review)

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

    assert response["status"] == "partial"
    assert response["answer"]["document_count"] == 1
    assert response["answer"]["document_evidence_artifact_count"] == 1
    assert response["answer"]["documents"][0]["document_id"] == "doc_book"
    assert response["answer"]["documents"][0]["document_catalog"]["primary_subject"] == "ux_design"
    assert response["answer"]["documents"][0]["document_catalog"]["reading_role"] == "adjacent"
    assert response["answer"]["documents"][0]["document_catalog"]["exclude_from_core_game_design_corpus"] is True
    assert response["answer"]["documents"][0]["usability"]["status"] == "staged"
    assert response["planner"]["omissions"] == [
        {
            "code": "document_not_usable",
            "message": "doc_book has staged evidence but has not completed document ingestion.",
        }
    ]
    assert response["budget_used"]["artifacts_read"] == 1
    assert response["citations"][0]["level"] == "document"
    assert validate_knowledge_response(response)["valid"] is True


def test_query_knowledge_document_orientation_uses_project_aliases(tmp_path):
    runtime = MemoryOSRuntime(tmp_path / "memory_os")
    runtime.initialize()
    review = _review_packet(tmp_path)
    review = {
        **review,
        "disassembly": {
            **review["disassembly"],
            "document": {
                **review["disassembly"]["document"],
                "document_id": "doc_design_skills_book",
                "title": "Design Skills Book",
            },
        },
    }
    prepared = runtime.prepare_document_artifact_store(review)
    runtime.store_document_artifact(
        prepared["prepared_transaction_id"],
        accept=True,
        review_packet=review,
        project="Design Skills",
    )
    runtime.ledger.initialize()

    response = runtime.query_knowledge(
        {
            "request_id": "req-doc-orientation-alias",
            "ask": {
                "goal": "Orient to design skills evidence.",
                "task_type": "document_orientation",
                "project": "/Users/example/Projects/Design Skills",
                "focus": ["Design Skills Book"],
            },
        }
    )

    assert response["status"] == "partial"
    assert response["answer"]["document_count"] == 1
    assert response["answer"]["documents"][0]["document_id"] == "doc_design_skills_book"
