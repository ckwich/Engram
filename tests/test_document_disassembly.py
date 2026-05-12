from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from core.document_extractors import ExtractorCommandResult, prepare_document_disassembly
from core.reliability_harness import (
    REQUIRED_BOOK_DISMANTLING_FIXTURE_IDS,
    default_book_dismantling_fixture_manifests,
    run_book_dismantling_gate,
)


def _fake_poppler_runner(args: list[str], timeout_seconds: int) -> ExtractorCommandResult:
    command = Path(args[0]).name.lower()
    assert timeout_seconds > 0
    if command == "pdfinfo":
        return ExtractorCommandResult(
            returncode=0,
            stdout="\n".join(
                [
                    "Title:          Sample Book",
                    "Pages:          3",
                    "Encrypted:      no",
                    "Page size:      612 x 792 pts",
                ]
            ),
            stderr="",
        )
    if command == "pdftotext":
        return ExtractorCommandResult(
            returncode=0,
            stdout=(
                "Page one has enough text to be a normal text page with useful content.\n"
                "\f"
                "   \n"
                "\f"
                "Figure page caption only\n"
            ),
            stderr="",
        )
    if command == "pdfimages":
        return ExtractorCommandResult(
            returncode=0,
            stdout="\n".join(
                [
                    "page   num  type   width height color comp bpc  enc interp  object ID x-ppi y-ppi size ratio",
                    "--------------------------------------------------------------------------------------------",
                    "2       0 image     640   480  rgb     3   8  jpeg   no        12  0   144   144 20K  5%",
                    "3       1 image     320   200  gray    1   8  image  no        13  0    72    72 10K  4%",
                ]
            ),
            stderr="",
        )
    raise AssertionError(f"unexpected command: {args}")


def test_prepare_pdf_disassembly_uses_poppler_inventory_without_writes(tmp_path):
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.7\n% sample")

    payload = prepare_document_disassembly(
        source_path=pdf,
        tool_paths={"pdfinfo": "pdfinfo", "pdftotext": "pdftotext", "pdfimages": "pdfimages"},
        runner=_fake_poppler_runner,
    )

    expected_hash = "sha256:" + hashlib.sha256(pdf.read_bytes()).hexdigest()
    assert payload["error"] is None
    assert payload["write_performed"] is False
    assert payload["active_memory_write_performed"] is False
    assert payload["source"]["content_hash"] == expected_hash
    assert payload["source"]["media_type"] == "application/pdf"
    assert payload["document"]["title"] == "Sample Book"
    assert payload["document"]["page_count"] == 3
    assert payload["document"]["encrypted"] is False
    assert payload["text"]["page_count"] == 3
    assert payload["image_inventory"]["image_count"] == 2
    assert payload["image_inventory"]["pages_with_images"] == [2, 3]
    assert [page["page_number"] for page in payload["pages"]] == [1, 2, 3]
    assert payload["pages"][0]["text_status"] == "text"
    assert payload["pages"][1]["text_status"] == "no_text"
    assert payload["pages"][1]["visual_review_needed"] is True
    assert payload["pages"][2]["image_count"] == 1
    assert payload["quality_seed"]["no_text_pages"] == [2]
    assert payload["quality_seed"]["image_pages"] == [2, 3]
    assert payload["quality_report"]["record_type"] == "document_quality_report"
    assert payload["quality_report"]["coverage"]["no_text_page_count"] == 1
    assert "visual_review_needed" in {warning["code"] for warning in payload["quality_report"]["warnings"]}
    assert payload["artifact_manifest"]["record_type"] == "document_artifact_manifest"
    assert payload["artifact_manifest"]["resume"]["states"]["2"] == "visual_needed"
    candidates = payload["visual_artifact_candidates"]
    assert [candidate["page_number"] for candidate in candidates] == [2, 3]
    assert {candidate["artifact_type"] for candidate in candidates} == {"page_crop"}
    assert all(candidate["source_artifact_id"] for candidate in candidates)
    assert all(candidate["extractor"]["id"] == "engram-local-pdf-disassembly" for candidate in candidates)
    assert payload["visual_extraction_request"]["record_type"] == "visual_extraction_request"
    assert [ref["page_number"] for ref in payload["visual_extraction_request"]["image_refs"]] == [2, 3]
    assert set(payload["visual_extraction_request"]["requested_capabilities"]) == {
        "caption_alt_text",
        "diagram_description",
        "figure_description",
        "ocr_text",
        "table_structure",
    }
    assert payload["promotion_guidance"]["auto_promote"] is False
    assert {receipt["tool"] for receipt in payload["extraction_receipts"]} == {
        "pdfinfo",
        "pdftotext",
        "pdfimages",
    }


def test_prepare_pdf_disassembly_reports_missing_local_tools(tmp_path):
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.7\n% sample")

    payload = prepare_document_disassembly(
        source_path=pdf,
        tool_paths={"pdfinfo": None, "pdftotext": None, "pdfimages": None},
        runner=_fake_poppler_runner,
    )

    assert payload["write_performed"] is False
    assert payload["active_memory_write_performed"] is False
    assert payload["error"] == {
        "code": "missing_extractor",
        "message": "Missing local PDF tools: pdfinfo, pdftotext, pdfimages",
    }
    assert payload["capabilities"]["pdfinfo"]["available"] is False
    assert payload["capabilities"]["pdftotext"]["available"] is False
    assert payload["capabilities"]["pdfimages"]["available"] is False


def test_book_dismantling_gate_validates_required_fixture_manifests():
    report = run_book_dismantling_gate(default_book_dismantling_fixture_manifests())

    assert report["schema_version"] == "2026-05-12.book-dismantling-gate.v1"
    assert report["summary"] == {
        "status": "pass",
        "fixture_count": 7,
        "passed": 7,
        "failed": 0,
        "required_fixture_count": 7,
        "missing_required_count": 0,
    }
    assert report["required_fixture_ids"] == REQUIRED_BOOK_DISMANTLING_FIXTURE_IDS
    assert {fixture["fixture_id"] for fixture in report["fixtures"]} == set(REQUIRED_BOOK_DISMANTLING_FIXTURE_IDS)
    image_only = next(fixture for fixture in report["fixtures"] if fixture["fixture_id"] == "image_only_pdf")
    assert image_only["status"] == "pass"
    assert image_only["checks"]["warning_codes"] == ["no_text_pages", "visual_review_needed"]
    table_heavy = next(fixture for fixture in report["fixtures"] if fixture["fixture_id"] == "table_heavy_page")
    assert "table_structure" in table_heavy["checks"]["visual_request_capabilities"]


def test_book_dismantling_fixture_readme_documents_no_copyrighted_pdf_policy():
    readme = Path(__file__).parent / "fixtures" / "document_books" / "README.md"
    text = readme.read_text(encoding="utf-8")

    assert "Do not commit copyrighted PDFs" in text
    for fixture_id in REQUIRED_BOOK_DISMANTLING_FIXTURE_IDS:
        assert fixture_id in text


def test_optional_local_design_book_smoke_is_env_gated():
    fixture_dir = os.environ.get("ENGRAM_DOCUMENT_FIXTURE_DIR")
    if not fixture_dir:
        pytest.skip("Set ENGRAM_DOCUMENT_FIXTURE_DIR to run local PDF smoke tests.")

    directory = Path(fixture_dir)
    if not directory.exists():
        pytest.skip(f"ENGRAM_DOCUMENT_FIXTURE_DIR does not exist: {directory}")
    pdfs = sorted(directory.glob("*.pdf"))
    if not pdfs:
        pytest.skip(f"No PDFs found in ENGRAM_DOCUMENT_FIXTURE_DIR: {directory}")

    payload = prepare_document_disassembly(source_path=pdfs[0], max_pages=5)
    error = payload.get("error")
    if isinstance(error, dict) and error.get("code") == "missing_extractor":
        pytest.skip(error["message"])

    assert error is None
    assert payload["write_performed"] is False
    assert payload["active_memory_write_performed"] is False
    assert payload["document"]["page_count"] >= len(payload["pages"])
    assert payload["artifact_manifest"]["record_type"] == "document_artifact_manifest"
    assert "content" in payload["text"]
