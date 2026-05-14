from __future__ import annotations

import subprocess

from core.document_extractors import prepare_document_disassembly
from core.document_intake_workflow import prepare_document_intake_review
from core.document_intelligence import prepare_document_record, preview_document_extraction


def _base_disassembly(*, pages, text="Useful extracted text.", image_pages=None, visual_request=None, error=None):
    return {
        "record_type": "document_disassembly_preview",
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
            "page_count": len(pages),
            "page_limit": len(pages),
        },
        "pages": pages,
        "text": {"content": text, "char_count": len(text), "page_count": len(pages)} if text is not None else None,
        "image_inventory": {
            "image_count": len(image_pages or []),
            "pages_with_images": image_pages or [],
        },
        "quality_report": {
            "record_type": "document_quality_report",
            "warnings": [],
            "coverage": {},
        },
        "artifact_manifest": {"record_type": "document_artifact_manifest"},
        "visual_extraction_request": visual_request,
        "visual_artifact_candidates": [],
        "promotion_guidance": {"auto_promote": False},
        "error": error,
    }


def test_prepare_document_intake_review_returns_ok_for_text_complete_pdf():
    def fake_disassembler(**kwargs):
        return _base_disassembly(
            pages=[{"page_number": 1, "text_status": "text", "visual_review_needed": False}],
            text="# Notes\n\nEnough text to review.",
        )

    packet = prepare_document_intake_review(
        "C:/docs/book.pdf",
        document_disassembler=fake_disassembler,
    )

    assert packet["status"] == "ok"
    assert packet["source"]["document_id"] == "doc_book"
    assert packet["policy"] == {
        "write_behavior": "read_only",
        "active_memory_promoted": False,
        "graph_edges_promoted": False,
    }
    assert packet["disassembly"]["document"]["title"] == "Book"
    assert packet["document_preview"]["preview"]["document"]["document_id"] == "doc_book"
    assert packet["document_preview"]["preview"]["document_record"]["document_id"] == "doc_book"
    assert packet["document_preview"]["preview"]["extractor_receipt"]["document_id"] == "doc_book"
    assert {
        chunk["provenance"]["document_id"]
        for chunk in packet["document_preview"]["preview"]["chunks"]
    } == {"doc_book"}
    assert packet["extraction_request"] is None
    assert packet["receipts"]["artifacts_built"] == 1
    assert packet["receipts"]["artifacts_read"] == 0
    assert packet["error"] is None


def test_document_record_uses_human_readable_document_id():
    record = prepare_document_record(
        title="Architecture Notes",
        source_uri="file:///docs/architecture-notes.md",
        source_type="markdown",
        content_hash="sha256:" + "a" * 64,
        media_type="text/markdown",
    )

    assert record["document_id"] == "doc_architecture_notes"


def test_preview_document_extraction_uses_human_readable_document_id():
    preview = preview_document_extraction(
        title="Architecture Notes",
        source_uri="file:///docs/architecture-notes.md",
        source_type="markdown",
        content="# Architecture\n\nReadable ids help humans review records.",
        media_type="text/markdown",
    )

    assert preview["document_record"]["document_id"] == "doc_architecture_notes"
    assert {
        chunk["provenance"]["document_id"]
        for chunk in preview["chunks"]
    } == {"doc_architecture_notes"}


def test_prepare_document_intake_review_returns_partial_when_visual_coverage_is_required():
    visual_request = {
        "record_type": "visual_extraction_request",
        "image_refs": [{"page_number": 2, "image_ref": "page:2"}],
        "requested_capabilities": ["ocr_text", "figure_description", "table_structure"],
    }

    def fake_disassembler(**kwargs):
        return _base_disassembly(
            pages=[
                {"page_number": 1, "text_status": "text", "visual_review_needed": False},
                {"page_number": 2, "text_status": "no_text", "visual_review_needed": True},
            ],
            text="Page one text.",
            image_pages=[2],
            visual_request=visual_request,
        )

    packet = prepare_document_intake_review(
        "C:/docs/book.pdf",
        document_disassembler=fake_disassembler,
    )

    assert packet["status"] == "partial"
    assert packet["extraction_request"] == visual_request
    assert packet["receipts"]["coverage_missing"] == ["ocr", "table", "visual"]
    assert packet["promotion_guidance"]["auto_promote"] is False
    assert packet["error"] is None


def test_prepare_document_intake_review_reports_missing_poppler_as_infrastructure_unavailable():
    def fake_disassembler(**kwargs):
        return _base_disassembly(
            pages=[],
            text=None,
            error={
                "code": "missing_extractor",
                "message": "Missing local PDF tools: pdfinfo, pdftotext, pdfimages",
            },
        )

    packet = prepare_document_intake_review(
        "C:/docs/book.pdf",
        document_disassembler=fake_disassembler,
    )

    assert packet["status"] == "unavailable"
    assert packet["error"] == {
        "code": "missing_extractor",
        "category": "infrastructure",
        "message": "Missing local PDF tools: pdfinfo, pdftotext, pdfimages",
    }
    assert packet["document_preview"] is None


def test_prepare_document_intake_review_reports_missing_source_as_schema_failed():
    def fake_disassembler(**kwargs):
        raise ValueError("source_path does not exist or is not a file: C:/docs/missing.pdf")

    packet = prepare_document_intake_review(
        "C:/docs/missing.pdf",
        document_disassembler=fake_disassembler,
    )

    assert packet["status"] == "schema_failed"
    assert packet["error"] == {
        "code": "invalid_request",
        "category": "validation",
        "message": "source_path does not exist or is not a file: C:/docs/missing.pdf",
    }
    assert packet["policy"]["write_behavior"] == "read_only"


def test_prepare_document_disassembly_reports_timeout_as_infrastructure_error(tmp_path):
    source = tmp_path / "book.pdf"
    source.write_bytes(b"%PDF-1.4 synthetic")

    def timeout_runner(args, timeout_seconds):
        raise subprocess.TimeoutExpired(cmd=args, timeout=timeout_seconds)

    packet = prepare_document_disassembly(
        source_path=source,
        tool_paths={"pdfinfo": "pdfinfo", "pdftotext": "pdftotext", "pdfimages": "pdfimages"},
        runner=timeout_runner,
        timeout_seconds=1,
    )

    assert packet["error"]["code"] == "tool_timeout"
    assert "timed out" in packet["error"]["message"]
