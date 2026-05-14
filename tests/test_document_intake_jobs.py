from __future__ import annotations

from core.document_intake_workflow import prepare_document_intake_review


def test_document_intake_review_passes_page_range_and_reports_resume_receipt():
    def fake_disassembler(**kwargs):
        assert kwargs["page_range"] == "3-3"
        assert kwargs["resume_token"] is None
        return {
            "record_type": "document_disassembly_preview",
            "status": "partial",
            "write_performed": False,
            "active_memory_write_performed": False,
            "source": {
                "source_uri": "file:///docs/book.pdf",
                "path": "C:/docs/book.pdf",
                "source_type": "pdf",
                "media_type": "application/pdf",
                "content_hash": "sha256:" + "a" * 64,
            },
            "document": {
                "document_id": "doc_book",
                "title": "Book",
                "source_type": "pdf",
                "media_type": "application/pdf",
                "content_hash": "sha256:" + "a" * 64,
                "page_count": 10,
                "page_limit": 3,
                "page_range": {"start": 3, "end": 3},
                "pages_returned": 1,
            },
            "pages": [{"page_number": 3, "text_status": "text", "visual_review_needed": False}],
            "text": {"content": "Page three text is enough for a ranged pass.", "char_count": 42, "page_count": 1},
            "image_inventory": {"image_count": 0, "pages_with_images": []},
            "quality_report": {"warnings": [], "coverage": {}},
            "artifact_manifest": {
                "record_type": "document_artifact_manifest",
                "resume": {
                    "page_range": {"start": 3, "end": 3},
                    "merge_strategy": "page_range_manifest_merge",
                    "resume_token": "token-next",
                },
            },
            "visual_extraction_request": None,
            "promotion_guidance": {"auto_promote": False},
            "resume": {
                "has_more": True,
                "next_page": 4,
                "resume_token": "token-next",
                "merge_strategy": "page_range_manifest_merge",
            },
            "error": None,
        }

    packet = prepare_document_intake_review(
        "C:/docs/book.pdf",
        page_range="3-3",
        document_disassembler=fake_disassembler,
    )

    assert packet["status"] == "partial"
    assert packet["receipts"]["resume"]["has_more"] is True
    assert packet["receipts"]["resume"]["next_page"] == 4
    assert packet["receipts"]["coverage_missing"] == []
