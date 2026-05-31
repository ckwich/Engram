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
    assert candidates[0]["candidate_id"].startswith("vis_candidate_doc_sample_book_page_2_page_crop_")
    assert all(candidate["source_artifact_id"] for candidate in candidates)
    assert all(candidate["extractor"]["id"] == "engram-local-pdf-disassembly" for candidate in candidates)
    assert payload["visual_extraction_request"]["record_type"] == "visual_extraction_request"
    assert [ref["page_number"] for ref in payload["visual_extraction_request"]["image_refs"]] == [2, 3]
    assert set(payload["visual_extraction_request"]["requested_capabilities"]) == {
        "figure_description",
        "ocr_text",
    }
    assert payload["visual_extraction_request"]["image_refs"][0]["requested_capabilities"] == [
        "figure_description",
        "ocr_text",
    ]
    assert payload["visual_extraction_request"]["image_refs"][1]["requested_capabilities"] == [
        "figure_description",
        "ocr_text",
    ]
    assert payload["promotion_guidance"]["auto_promote"] is False
    assert {receipt["tool"] for receipt in payload["extraction_receipts"]} == {
        "pdfinfo",
        "pdftotext",
        "pdfimages",
    }


def test_prepare_markdown_disassembly_uses_text_inventory_without_pdf_tools(tmp_path):
    transcript = tmp_path / "001 - Making Hitman 3's Best Level.md"
    transcript.write_text(
        "# Making Hitman 3's Best Level\n\n"
        "Transcript source: https://www.youtube.com/watch?v=lfJ-vGXX9ag\n\n"
        "This level design transcript discusses social stealth, spatial loops, and mission planning.\n",
        encoding="utf-8",
    )

    payload = prepare_document_disassembly(source_path=transcript, source_type="markdown")

    expected_hash = "sha256:" + hashlib.sha256(transcript.read_bytes()).hexdigest()
    assert payload["error"] is None
    assert payload["write_performed"] is False
    assert payload["active_memory_write_performed"] is False
    assert payload["source"]["content_hash"] == expected_hash
    assert payload["source"]["source_type"] == "markdown"
    assert payload["source"]["media_type"] == "text/markdown"
    assert payload["document"]["title"] == "Making Hitman 3's Best Level"
    assert payload["document"]["source_type"] == "markdown"
    assert payload["document"]["media_type"] == "text/markdown"
    assert payload["document"]["page_count"] == 1
    assert payload["pages"] == [
        {
            "page_number": 1,
            "text_chars": len(payload["text"]["content"]),
            "non_whitespace_chars": len("".join(payload["text"]["content"].split())),
            "text_status": "text",
            "image_count": 0,
            "table_candidate": False,
            "visual_review_needed": False,
        }
    ]
    assert payload["image_inventory"]["image_count"] == 0
    assert payload["quality_seed"]["text_pages"] == [1]
    assert payload["quality_seed"]["visual_review_needed_pages"] == []
    assert payload["visual_artifact_candidates"] == []
    assert payload["visual_extraction_request"] is None
    assert payload["artifact_manifest"]["artifacts"]["raw_source"]["ref"].endswith(".md")
    assert payload["promotion_guidance"]["auto_promote"] is False
    assert payload["extraction_receipts"][0]["tool"] == "text-disassembly"


def test_prepare_pdf_disassembly_requests_table_structure_only_for_table_candidates(tmp_path):
    pdf = tmp_path / "table.pdf"
    pdf.write_bytes(b"%PDF-1.7\n% table")

    def table_runner(args: list[str], timeout_seconds: int) -> ExtractorCommandResult:
        command = Path(args[0]).name.lower()
        if command == "pdfinfo":
            return ExtractorCommandResult(
                returncode=0,
                stdout="Title: Table Book\nPages: 1\nEncrypted: no\n",
                stderr="",
            )
        if command == "pdftotext":
            return ExtractorCommandResult(
                returncode=0,
                stdout=(
                    "Metric        Before        After\n"
                    "Attention     Low           High\n"
                    "Retention     Weak          Strong\n"
                ),
                stderr="",
            )
        if command == "pdfimages":
            return ExtractorCommandResult(
                returncode=0,
                stdout="\n".join(
                    [
                        "page   num  type   width height color comp bpc  enc interp  object ID x-ppi y-ppi size ratio",
                        "1       0 image     640   480  rgb     3   8  jpeg   no        12  0   144   144 20K  5%",
                    ]
                ),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {args}")

    payload = prepare_document_disassembly(
        source_path=pdf,
        tool_paths={"pdfinfo": "pdfinfo", "pdftotext": "pdftotext", "pdfimages": "pdfimages"},
        runner=table_runner,
    )

    assert payload["pages"][0]["table_candidate"] is True
    assert payload["quality_seed"]["table_candidate_pages"] == [1]
    assert payload["visual_extraction_request"]["image_refs"][0]["requested_capabilities"] == [
        "figure_description",
        "table_structure",
    ]
    assert set(payload["visual_extraction_request"]["requested_capabilities"]) == {
        "figure_description",
        "table_structure",
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


def test_prepare_pdf_disassembly_supports_page_ranges_and_resume_tokens(tmp_path):
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.7\n% sample")
    calls: list[list[str]] = []

    def range_runner(args: list[str], timeout_seconds: int) -> ExtractorCommandResult:
        calls.append(args)
        command = Path(args[0]).name.lower()
        if command == "pdfinfo":
            return ExtractorCommandResult(
                returncode=0,
                stdout="Title: Range Book\nPages: 4\nEncrypted: no\n",
                stderr="",
            )
        if command == "pdftotext":
            assert args[1:6] == ["-layout", "-enc", "UTF-8", "-f", "2"]
            assert args[6:8] == ["-l", "2"]
            return ExtractorCommandResult(
                returncode=0,
                stdout="Range page two has enough text for a focused pass.",
                stderr="",
            )
        if command == "pdfimages":
            assert args[1:5] == ["-f", "2", "-l", "2"]
            return ExtractorCommandResult(
                returncode=0,
                stdout="\n".join(
                    [
                        "page   num  type   width height color comp bpc  enc interp  object ID x-ppi y-ppi size ratio",
                        "2       0 image     640   480  rgb     3   8  jpeg   no        12  0   144   144 20K  5%",
                    ]
                ),
                stderr="",
            )
        raise AssertionError(f"unexpected command: {args}")

    payload = prepare_document_disassembly(
        source_path=pdf,
        page_range="2-2",
        tool_paths={"pdfinfo": "pdfinfo", "pdftotext": "pdftotext", "pdfimages": "pdfimages"},
        runner=range_runner,
    )

    assert payload["status"] == "partial"
    assert payload["document"]["page_count"] == 4
    assert payload["document"]["page_range"] == {"start": 2, "end": 2}
    assert [page["page_number"] for page in payload["pages"]] == [2]
    assert payload["resume"]["has_more"] is True
    assert payload["resume"]["next_page"] == 3
    assert payload["resume"]["resume_token"]
    assert payload["artifact_manifest"]["resume"]["page_range"] == {"start": 2, "end": 2}
    assert payload["artifact_manifest"]["resume"]["merge_strategy"] == "page_range_manifest_merge"
    assert any(Path(call[0]).name.lower() == "pdftotext" for call in calls)


def test_prepare_pdf_disassembly_resume_token_rejects_stale_source_hash(tmp_path):
    first_pdf = tmp_path / "first.pdf"
    second_pdf = tmp_path / "second.pdf"
    first_pdf.write_bytes(b"%PDF first")
    second_pdf.write_bytes(b"%PDF second")

    def first_page_runner(args: list[str], timeout_seconds: int) -> ExtractorCommandResult:
        command = Path(args[0]).name.lower()
        if command == "pdfinfo":
            return ExtractorCommandResult(returncode=0, stdout="Title: Book\nPages: 2\n", stderr="")
        if command == "pdftotext":
            return ExtractorCommandResult(returncode=0, stdout="First page text.", stderr="")
        if command == "pdfimages":
            return ExtractorCommandResult(returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected command: {args}")

    first = prepare_document_disassembly(
        source_path=first_pdf,
        page_range="1-1",
        tool_paths={"pdfinfo": "pdfinfo", "pdftotext": "pdftotext", "pdfimages": "pdfimages"},
        runner=first_page_runner,
    )

    with pytest.raises(ValueError, match="resume_token source hash does not match"):
        prepare_document_disassembly(
            source_path=second_pdf,
            resume_token=first["resume"]["resume_token"],
            tool_paths={"pdfinfo": "pdfinfo", "pdftotext": "pdftotext", "pdfimages": "pdfimages"},
            runner=first_page_runner,
        )


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
