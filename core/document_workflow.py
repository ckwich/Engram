"""Daemon document workflow stage boundary."""
from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from typing import Any, Callable

from core.document_coverage_workbench import prepare_document_coverage_workbench
from core.document_extractors import prepare_document_disassembly
from core.document_intake_workflow import prepare_document_intake_review
from core.document_intelligence import (
    list_document_extractors,
    prepare_document_draft,
    prepare_document_extraction_request,
    prepare_document_extraction_result,
    prepare_document_promotion_transaction,
    prepare_document_understanding_packet,
    prepare_visual_extraction_request,
    preview_document_extraction,
    preview_visual_extraction,
)
from core.source_connectors import preview_document_source_connector


DOCUMENT_WORKFLOW_SCHEMA_VERSION = "2026-05-21.document-workflow-stage-contract.v1"
DOCUMENT_WORKFLOW_READ_ONLY_POLICY = {
    "write_behavior": "read_only",
    "active_memory_promoted": False,
    "graph_edges_promoted": False,
}

DocumentDisassembler = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class DocumentWorkflowStage:
    """One daemon document helper stage and its response envelope."""

    name: str
    result_key: str | None
    include_payload: bool = True
    uses_document_disassembler: bool = False
    propagate_result_error: bool = False
    write_behavior: str = "read_only"


DOCUMENT_WORKFLOW_STAGES = (
    DocumentWorkflowStage("list_document_extractors", "catalog", include_payload=False),
    DocumentWorkflowStage("preview_document_source_connector", None),
    DocumentWorkflowStage(
        "prepare_document_disassembly",
        "disassembly",
        uses_document_disassembler=True,
        propagate_result_error=True,
    ),
    DocumentWorkflowStage("prepare_document_coverage_workbench", "workbench"),
    DocumentWorkflowStage(
        "prepare_document_intake_review",
        None,
        uses_document_disassembler=True,
    ),
    DocumentWorkflowStage("prepare_document_extraction_request", "request"),
    DocumentWorkflowStage("prepare_document_extraction_result", "result"),
    DocumentWorkflowStage("preview_document_extraction", "preview"),
    DocumentWorkflowStage("prepare_visual_extraction_request", "request"),
    DocumentWorkflowStage("preview_visual_extraction", "preview"),
    DocumentWorkflowStage("prepare_document_understanding_packet", "packet"),
    DocumentWorkflowStage("prepare_document_draft", "draft"),
    DocumentWorkflowStage("prepare_document_promotion_transaction", "transaction"),
)
DOCUMENT_WORKFLOW_STAGE_NAMES = tuple(stage.name for stage in DOCUMENT_WORKFLOW_STAGES)


class DocumentWorkflow:
    """Orchestrates no-write document helper stages for the daemon API."""

    def __init__(self, document_disassembler: DocumentDisassembler = prepare_document_disassembly):
        self.document_disassembler = document_disassembler
        self._stages = {stage.name: stage for stage in DOCUMENT_WORKFLOW_STAGES}

    def stage_contract(self) -> dict[str, Any]:
        return {
            "schema_version": DOCUMENT_WORKFLOW_SCHEMA_VERSION,
            "policy": dict(DOCUMENT_WORKFLOW_READ_ONLY_POLICY),
            "stages": [asdict(stage) for stage in DOCUMENT_WORKFLOW_STAGES],
            "error": None,
        }

    def run_stage(self, stage_name: str, request: dict[str, Any]) -> dict[str, Any]:
        stage = self._stages.get(stage_name)
        if stage is None:
            return {
                "error": {
                    "code": "unknown_document_workflow_stage",
                    "category": "validation",
                    "message": f"Unknown document workflow stage: {stage_name}",
                }
            }
        try:
            result = self._invoke_stage(stage, request)
        except ValueError as exc:
            return self._error_payload(stage, "invalid_request", None, str(exc))
        except RuntimeError as exc:
            return self._error_payload(stage, "runtime_error", None, str(exc))
        except subprocess.TimeoutExpired as exc:
            return self._error_payload(
                stage,
                "tool_timeout",
                "infrastructure",
                f"{stage.name} timed out after {exc.timeout} seconds",
            )
        return self._success_payload(stage, result)

    def _invoke_stage(
        self,
        stage: DocumentWorkflowStage,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        tool = getattr(self, stage.name)
        if stage.include_payload:
            return tool(**request)
        return tool()

    def _success_payload(
        self,
        stage: DocumentWorkflowStage,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        if stage.result_key is None:
            return result
        payload = {stage.result_key: result, "error": None}
        if (
            stage.propagate_result_error
            and isinstance(result, dict)
            and result.get("error") is not None
        ):
            payload["error"] = result["error"]
        return payload

    @staticmethod
    def _error_payload(
        stage: DocumentWorkflowStage,
        code: str,
        category: str | None,
        message: str,
    ) -> dict[str, Any]:
        error = {
            "code": code,
            "message": message,
        }
        if category is not None:
            error["category"] = category
        payload: dict[str, Any] = {
            "error": error
        }
        if stage.result_key is not None:
            payload[stage.result_key] = None
        return payload

    def list_document_extractors(self) -> dict[str, Any]:
        return list_document_extractors()

    def preview_document_source_connector(self, **kwargs: Any) -> dict[str, Any]:
        return preview_document_source_connector(**kwargs)

    def prepare_document_disassembly(self, **kwargs: Any) -> dict[str, Any]:
        return self.document_disassembler(**kwargs)

    def prepare_document_coverage_workbench(self, **kwargs: Any) -> dict[str, Any]:
        return prepare_document_coverage_workbench(**kwargs)

    def prepare_document_intake_review(self, **kwargs: Any) -> dict[str, Any]:
        return prepare_document_intake_review(
            document_disassembler=self.document_disassembler,
            **kwargs,
        )

    def prepare_document_extraction_request(self, **kwargs: Any) -> dict[str, Any]:
        return prepare_document_extraction_request(**kwargs)

    def prepare_document_extraction_result(self, **kwargs: Any) -> dict[str, Any]:
        return prepare_document_extraction_result(**kwargs)

    def preview_document_extraction(self, **kwargs: Any) -> dict[str, Any]:
        return preview_document_extraction(**kwargs)

    def prepare_visual_extraction_request(self, **kwargs: Any) -> dict[str, Any]:
        return prepare_visual_extraction_request(**kwargs)

    def preview_visual_extraction(self, **kwargs: Any) -> dict[str, Any]:
        return preview_visual_extraction(**kwargs)

    def prepare_document_understanding_packet(self, **kwargs: Any) -> dict[str, Any]:
        return prepare_document_understanding_packet(**kwargs)

    def prepare_document_draft(self, **kwargs: Any) -> dict[str, Any]:
        return prepare_document_draft(**kwargs)

    def prepare_document_promotion_transaction(self, **kwargs: Any) -> dict[str, Any]:
        return prepare_document_promotion_transaction(**kwargs)
