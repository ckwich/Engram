from __future__ import annotations

from core.document_quality import build_document_quality_report


def test_build_document_quality_report_flags_document_risks_without_writes():
    disassembly = {
        "document": {"document_id": "doc_alpha", "page_count": 5, "title": "Sample Book"},
        "source": {"source_uri": "file:///sample.pdf", "content_hash": "sha256:" + "a" * 64},
        "pages": [
            {"page_number": 1, "text_status": "text", "image_count": 0, "visual_review_needed": False},
            {"page_number": 2, "text_status": "no_text", "image_count": 1, "visual_review_needed": True},
            {"page_number": 3, "text_status": "low_text", "image_count": 3, "visual_review_needed": True},
            {"page_number": 4, "text_status": "text", "image_count": 0, "visual_review_needed": False},
            {"page_number": 5, "text_status": "text", "image_count": 2, "visual_review_needed": True},
        ],
        "quality_seed": {
            "page_count": 5,
            "no_text_pages": [2],
            "low_text_pages": [3],
            "image_pages": [2, 3, 5],
            "visual_review_needed_pages": [2, 3, 5],
            "failed_pages": [4],
            "table_candidate_pages": [3],
            "unsupported_capabilities": ["table_structure"],
        },
        "error": None,
    }

    report = build_document_quality_report(disassembly)

    assert report["schema_version"] == "2026-05-12.document-quality.v1"
    assert report["record_type"] == "document_quality_report"
    assert report["write_performed"] is False
    assert report["active_memory_write_performed"] is False
    assert report["document_id"] == "doc_alpha"
    assert report["coverage"] == {
        "page_count": 5,
        "pages_reported": 5,
        "text_page_count": 3,
        "low_text_page_count": 1,
        "no_text_page_count": 1,
        "image_page_count": 3,
        "visual_review_needed_page_count": 3,
        "failed_page_count": 1,
        "text_page_ratio": 0.6,
    }
    warning_codes = {warning["code"] for warning in report["warnings"]}
    assert {
        "no_text_pages",
        "low_text_pages",
        "image_heavy_pages",
        "visual_review_needed",
        "failed_pages",
        "table_candidates",
        "unsupported_capabilities",
    } <= warning_codes
    assert report["recommended_next_tools"] == [
        "prepare_visual_extraction_request",
        "preview_visual_extraction",
        "prepare_document_draft",
    ]


def test_build_document_quality_report_handles_clean_text_documents():
    report = build_document_quality_report(
        {
            "document": {"document_id": "doc_clean", "page_count": 2, "title": "Clean"},
            "source": {"source_uri": "file:///clean.pdf"},
            "pages": [
                {"page_number": 1, "text_status": "text", "image_count": 0, "visual_review_needed": False},
                {"page_number": 2, "text_status": "text", "image_count": 0, "visual_review_needed": False},
            ],
            "quality_seed": {
                "page_count": 2,
                "no_text_pages": [],
                "low_text_pages": [],
                "image_pages": [],
                "visual_review_needed_pages": [],
            },
            "error": None,
        }
    )

    assert report["status"] == "pass"
    assert report["warnings"] == []
    assert report["coverage"]["text_page_ratio"] == 1.0


def test_build_document_quality_report_uses_reported_pages_for_bounded_preview_ratio():
    report = build_document_quality_report(
        {
            "document": {"document_id": "doc_partial", "page_count": 100, "title": "Partial"},
            "source": {"source_uri": "file:///partial.pdf"},
            "pages": [
                {"page_number": 1, "text_status": "no_text", "image_count": 1, "visual_review_needed": True},
                {"page_number": 2, "text_status": "text", "image_count": 0, "visual_review_needed": False},
                {"page_number": 3, "text_status": "text", "image_count": 0, "visual_review_needed": False},
                {"page_number": 4, "text_status": "text", "image_count": 0, "visual_review_needed": False},
                {"page_number": 5, "text_status": "text", "image_count": 0, "visual_review_needed": False},
            ],
            "quality_seed": {
                "page_count": 100,
                "no_text_pages": [1],
                "low_text_pages": [],
                "image_pages": [1],
                "visual_review_needed_pages": [1],
            },
            "error": None,
        }
    )

    assert report["coverage"]["page_count"] == 100
    assert report["coverage"]["pages_reported"] == 5
    assert report["coverage"]["text_page_ratio"] == 0.8
