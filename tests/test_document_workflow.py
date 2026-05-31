from __future__ import annotations

import subprocess

from core.document_workflow import DOCUMENT_WORKFLOW_STAGE_NAMES, DocumentWorkflow


def _fake_disassembler(**kwargs):
    return {
        "record_type": "document_disassembly_preview",
        "source": {"path": kwargs["source_path"]},
        "document": {"document_id": "doc_book"},
        "error": None,
    }


def test_document_workflow_exposes_explicit_read_only_stage_contract():
    workflow = DocumentWorkflow(document_disassembler=_fake_disassembler)

    contract = workflow.stage_contract()
    stages = contract["stages"]
    by_name = {stage["name"]: stage for stage in stages}

    assert contract["policy"] == {
        "write_behavior": "read_only",
        "active_memory_promoted": False,
        "graph_edges_promoted": False,
    }
    assert [stage["name"] for stage in stages] == list(DOCUMENT_WORKFLOW_STAGE_NAMES)
    assert len(by_name) == len(DOCUMENT_WORKFLOW_STAGE_NAMES)
    assert by_name["list_document_extractors"]["include_payload"] is False
    assert by_name["prepare_document_disassembly"]["result_key"] == "disassembly"
    assert by_name["prepare_document_intake_review"]["uses_document_disassembler"] is True
    assert all(stage["write_behavior"] == "read_only" for stage in stages)


def test_document_workflow_run_stage_wraps_results_with_stage_envelope():
    workflow = DocumentWorkflow(document_disassembler=_fake_disassembler)

    response = workflow.run_stage(
        "prepare_document_disassembly",
        {"source_path": "/tmp/book.pdf", "source_type": "pdf"},
    )

    assert response["disassembly"]["source"]["path"] == "/tmp/book.pdf"
    assert response["error"] is None


def test_document_workflow_run_stage_normalizes_timeout_errors():
    def timeout_disassembler(**_kwargs):
        raise subprocess.TimeoutExpired(cmd="pdftotext", timeout=7)

    workflow = DocumentWorkflow(document_disassembler=timeout_disassembler)

    response = workflow.run_stage(
        "prepare_document_disassembly",
        {"source_path": "/tmp/book.pdf"},
    )

    assert response["disassembly"] is None
    assert response["error"] == {
        "code": "tool_timeout",
        "category": "infrastructure",
        "message": "prepare_document_disassembly timed out after 7 seconds",
    }
