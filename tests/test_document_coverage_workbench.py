from __future__ import annotations

from pathlib import Path

from core.document_coverage_workbench import (
    CoverageCommandResult,
    prepare_document_coverage_workbench,
)


def _pdf(path: Path) -> Path:
    path.write_bytes(b"%PDF-1.4\n% synthetic\n")
    return path


def _document_record(source: Path) -> dict[str, object]:
    return {
        "document_id": "doc_design_test",
        "title": "Design Test",
        "source_uri": source.resolve().as_uri(),
        "source_type": "pdf",
        "content_hash": "sha256:" + "a" * 64,
        "media_type": "application/pdf",
    }


def _visual_request(source: Path) -> dict[str, object]:
    source_uri = source.resolve().as_uri()
    return {
        "request_id": "vis_req_design_test",
        "document_id": "doc_design_test",
        "requested_capabilities": ["figure_description", "ocr_text", "table_structure"],
        "image_refs": [
            {
                "source_uri": source_uri,
                "page_number": 2,
                "requested_capabilities": ["ocr_text", "table_structure"],
            },
            {
                "source_uri": source_uri,
                "page_number": 3,
                "requested_capabilities": ["figure_description"],
            },
        ],
    }


def test_coverage_workbench_renders_page_packets_without_memory_writes(tmp_path):
    source = _pdf(tmp_path / "design.pdf")
    output_dir = tmp_path / "coverage-work"

    def runner(args: list[str], timeout_seconds: int) -> CoverageCommandResult:
        assert timeout_seconds == 60
        prefix = Path(args[-1])
        (prefix.parent).mkdir(parents=True, exist_ok=True)
        (prefix.with_suffix(".png")).write_bytes(b"png")
        return CoverageCommandResult(returncode=0, stdout="", stderr="")

    payload = prepare_document_coverage_workbench(
        source_path=source,
        document_record=_document_record(source),
        visual_request=_visual_request(source),
        output_dir=output_dir,
        render_pages=True,
        run_ocr=False,
        run_table_detection=False,
        tool_paths={"pdftoppm": "/usr/local/bin/pdftoppm", "tesseract": None},
        runner=runner,
    )

    assert payload["status"] == "ok"
    assert payload["write_performed"] is False
    assert payload["active_memory_write_performed"] is False
    assert payload["local_artifact_write_performed"] is True
    assert payload["receipts"]["page_task_count"] == 2
    assert payload["receipts"]["rendered_page_count"] == 2
    assert payload["receipts"]["observation_count"] == 0
    assert payload["skipped_receipts"][0]["code"] == "ocr_not_requested"
    assert payload["skipped_receipts"][1]["code"] == "table_detection_not_requested"

    page_two = payload["page_tasks"][0]
    assert page_two["page_number"] == 2
    assert page_two["required_capabilities"] == ["ocr_text", "table_structure"]
    assert page_two["render"]["status"] == "ready"
    assert page_two["render"]["artifact_ref"]["media_type"] == "image/png"
    assert page_two["ocr"]["status"] == "skipped"
    assert page_two["table"]["status"] == "skipped"
    assert page_two["visual_review"]["status"] == "not_required"

    page_three = payload["page_tasks"][1]
    assert page_three["required_capabilities"] == ["figure_description"]
    assert page_three["visual_review"]["status"] == "required"
    assert page_three["visual_review"]["input_artifact_ref"] == page_three["render"]["artifact_ref"]
    assert payload["preview_visual_extraction_arguments"]["observations"] == []


def test_coverage_workbench_reports_missing_adapters_per_capability(tmp_path):
    source = _pdf(tmp_path / "design.pdf")

    payload = prepare_document_coverage_workbench(
        source_path=source,
        document_record=_document_record(source),
        visual_request=_visual_request(source),
        output_dir=tmp_path / "coverage-work",
        render_pages=True,
        run_ocr=True,
        run_table_detection=True,
        tool_paths={"pdftoppm": None, "tesseract": None},
    )

    assert payload["status"] == "partial"
    codes = {receipt["code"] for receipt in payload["unavailable_receipts"]}
    assert "page_renderer_unavailable" in codes
    assert "ocr_adapter_unavailable" in codes
    assert "table_adapter_unavailable" in codes
    assert payload["page_tasks"][0]["render"]["status"] == "unavailable"
    assert payload["page_tasks"][0]["ocr"]["status"] == "unavailable"
    assert payload["page_tasks"][0]["table"]["status"] == "unavailable"
    assert payload["page_tasks"][1]["visual_review"]["status"] == "required"
    assert payload["page_tasks"][1]["visual_review"]["input_artifact_ref"] is None


def test_coverage_workbench_returns_adapter_observations_for_preview(tmp_path):
    source = _pdf(tmp_path / "design.pdf")
    output_dir = tmp_path / "coverage-work"

    def runner(args: list[str], timeout_seconds: int) -> CoverageCommandResult:
        command = Path(args[0]).name
        if command == "pdftoppm":
            prefix = Path(args[-1])
            (prefix.parent).mkdir(parents=True, exist_ok=True)
            (prefix.with_suffix(".png")).write_bytes(b"png")
            return CoverageCommandResult(returncode=0, stdout="", stderr="")
        if command == "tesseract":
            return CoverageCommandResult(returncode=0, stdout="OCR text from page two.\n", stderr="")
        raise AssertionError(args)

    def table_detector(page_task: dict[str, object]) -> dict[str, object]:
        assert page_task["page_number"] == 2
        return {
            "description": "No table is present after local review.",
            "confidence": 0.87,
            "metadata": {"table_present": False},
        }

    payload = prepare_document_coverage_workbench(
        source_path=source,
        document_record=_document_record(source),
        visual_request=_visual_request(source),
        output_dir=output_dir,
        render_pages=True,
        run_ocr=True,
        run_table_detection=True,
        tool_paths={"pdftoppm": "/usr/local/bin/pdftoppm", "tesseract": "/usr/local/bin/tesseract"},
        runner=runner,
        table_detector=table_detector,
    )

    assert payload["status"] == "ok"
    assert payload["receipts"]["observation_count"] == 2
    observations = payload["observations"]
    assert observations[0]["artifact_type"] == "ocr_block"
    assert observations[0]["text"] == "OCR text from page two."
    assert observations[0]["metadata"]["capabilities_covered"] == ["ocr_text"]
    assert observations[1]["artifact_type"] == "table"
    assert observations[1]["description"] == "No table is present after local review."
    assert observations[1]["metadata"]["capabilities_covered"] == ["table_structure"]
    assert observations[1]["metadata"]["table_present"] is False
    assert payload["preview_visual_extraction_arguments"]["visual_request"]["request_id"] == "vis_req_design_test"


def test_coverage_workbench_sanitizes_document_id_in_local_output_id(tmp_path):
    source = _pdf(tmp_path / "design.pdf")
    document = _document_record(source)
    document["document_id"] = r"..\private\doc"
    visual_request = _visual_request(source)
    visual_request["document_id"] = document["document_id"]

    payload = prepare_document_coverage_workbench(
        source_path=source,
        document_record=document,
        visual_request=visual_request,
        render_pages=False,
        tool_paths={"pdftoppm": None, "tesseract": None},
    )

    assert payload["document_record"]["document_id"] == r"..\private\doc"
    assert ".." not in payload["workbench_id"]
    assert "\\" not in payload["workbench_id"]
    assert "/" not in payload["workbench_id"]
