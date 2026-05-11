from __future__ import annotations

import hashlib

from core.source_connectors import preview_document_source_connector


def test_preview_document_source_connector_prepares_document_extraction_arguments(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    note = docs / "architecture.md"
    note.write_text("# Architecture\n\nDecision: Keep document import review-first.", encoding="utf-8")
    page = docs / "overview.html"
    page.write_text("<h1>Overview</h1><p>Claim: HTML imports are evidence.</p>", encoding="utf-8")

    payload = preview_document_source_connector(
        connector_type="local_path",
        target=str(docs),
        include_globs=["*.md", "*.html"],
        metadata={"project": "Engram", "domain": "memory-os"},
    )

    assert payload["schema_version"] == "2026-05-11.document-source-connectors.v1"
    assert payload["connector_type"] == "local_path"
    assert payload["write_performed"] is False
    assert payload["count"] == 2
    assert payload["omitted"] == []
    markdown = payload["items"][0]
    html = payload["items"][1]
    assert markdown["document_extraction_arguments"] == {
        "title": "architecture",
        "source_uri": note.resolve().as_uri(),
        "source_type": "markdown",
        "content": "# Architecture\n\nDecision: Keep document import review-first.",
        "media_type": "text/markdown",
        "metadata": {"project": "Engram", "domain": "memory-os", "relative_path": "architecture.md"},
    }
    assert html["document_extraction_arguments"]["source_type"] == "html"
    assert html["document_extraction_arguments"]["media_type"] == "text/html"
    assert html["document_extraction_arguments"]["content"].startswith("<h1>Overview</h1>")
    assert payload["receipt"] == {
        "supported_count": 2,
        "omitted_count": 0,
        "max_source_text_chars": 12000,
        "source_text_truncated_count": 0,
    }


def test_preview_document_source_connector_omits_external_extractor_formats(tmp_path):
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4 image-only")
    content_hash = "sha256:" + hashlib.sha256(pdf.read_bytes()).hexdigest()

    payload = preview_document_source_connector(
        connector_type="local_path",
        target=str(pdf),
        include_globs=["*.pdf"],
    )

    assert payload["count"] == 0
    assert payload["write_performed"] is False
    assert payload["omitted"] == [
        {
            "path": str(pdf.resolve()),
            "relative_path": "scan.pdf",
            "reason": "external_extractor_required",
            "media_type": "application/pdf",
            "recommended_next": "use an external PDF/OCR extractor, then preview_document_extraction or preview_visual_extraction",
            "document_extraction_request_arguments": {
                "source_ref": {
                    "source_uri": pdf.resolve().as_uri(),
                    "content_hash": content_hash,
                    "path": str(pdf.resolve()),
                    "relative_path": "scan.pdf",
                },
                "source_type": "pdf",
                "requested_outputs": ["markdown", "metadata", "page_images"],
                "extractor_id": "engram-document-request",
                "extractor_kind": "external_document",
                "instructions": "Extract text and page images as needed, then feed reviewed outputs into preview_document_extraction or preview_visual_extraction.",
            },
        }
    ]
