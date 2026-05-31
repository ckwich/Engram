"""Read-only completion assessment service for staged document evidence."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from core.memory_os._records import read_record


@dataclass(frozen=True)
class DocumentCompletionAssessmentDependencies:
    """Pure helper callbacks used by the document completion assessment service."""

    required_text: Callable[[Any, str], str]
    normalize_waivers: Callable[[list[dict[str, Any]] | None], list[dict[str, Any]]]
    load_document_artifact_set: Callable[[Any, Any, str, str | None], dict[str, Any]]
    latest_coverage_map: Callable[[Any, str], dict[str, Any] | None]
    completion_visual_request: Callable[..., dict[str, Any] | None]
    visual_coverage_required: Callable[..., bool]
    validate_visual_evidence: Callable[..., list[dict[str, Any]]]
    validate_understanding_packet: Callable[[str, dict[str, Any] | None], list[dict[str, Any]]]
    validate_promotion_transaction: Callable[..., list[dict[str, Any]]]
    visual_artifacts: Callable[[dict[str, Any] | None], list[dict[str, Any]]]
    completion_execution_plan: Callable[..., dict[str, Any]]
    completion_coverage_map: Callable[..., dict[str, Any] | None]
    issue: Callable[..., dict[str, Any]]


class DocumentCompletionAssessmentService:
    """Build no-write usability decisions for staged document evidence."""

    def __init__(
        self,
        *,
        ledger: Any,
        store: Any,
        schema_version: str,
        dependencies: DocumentCompletionAssessmentDependencies,
    ) -> None:
        self.ledger = ledger
        self.store = store
        self.schema_version = schema_version
        self.dependencies = dependencies

    def assess(
        self,
        *,
        document_id: str,
        artifact_id: str | None = None,
        visual_request: dict[str, Any] | None = None,
        visual_preview: dict[str, Any] | None = None,
        understanding_packet: dict[str, Any] | None = None,
        document_promotion_transaction: dict[str, Any] | None = None,
        coverage_waivers: list[dict[str, Any]] | None = None,
        selected_operation_indexes: list[int] | None = None,
    ) -> dict[str, Any]:
        """Return a no-write usability assessment for staged document evidence."""
        deps = self.dependencies
        normalized_document_id = deps.required_text(document_id, "document_id")
        waivers = deps.normalize_waivers(coverage_waivers)
        artifact_set = deps.load_document_artifact_set(
            self.ledger,
            self.store,
            normalized_document_id,
            artifact_id,
        )
        artifacts = artifact_set["artifacts"]
        artifact = artifacts[-1] if artifacts else None
        document = read_record(self.ledger, "documents", normalized_document_id)
        coverage = deps.latest_coverage_map(self.ledger, normalized_document_id)
        artifact_payloads = artifact_set["payloads"]
        disassemblies = artifact_set["disassemblies"]
        blocking_issues: list[dict[str, Any]] = list(artifact_set["blocking_issues"])
        if document is None:
            blocking_issues.append(
                deps.issue("document_record_required", "A materialized document record is required.")
            )

        effective_visual_request = deps.completion_visual_request(
            normalized_document_id,
            visual_request=visual_request,
            artifact_payloads=artifact_payloads,
            disassemblies=disassemblies,
        )
        visual_required = deps.visual_coverage_required(
            artifacts=artifacts,
            coverage=coverage,
            disassemblies=disassemblies,
            visual_request=effective_visual_request,
        )
        blocking_issues.extend(
            deps.validate_visual_evidence(
                normalized_document_id,
                visual_required=visual_required,
                visual_request=effective_visual_request,
                visual_preview=visual_preview,
                waivers=waivers,
            )
        )
        blocking_issues.extend(
            deps.validate_understanding_packet(normalized_document_id, understanding_packet)
        )
        blocking_issues.extend(
            deps.validate_promotion_transaction(
                normalized_document_id,
                document_promotion_transaction,
                selected_operation_indexes=selected_operation_indexes,
            )
        )

        visual_artifacts = deps.visual_artifacts(visual_preview)
        execution_plan = deps.completion_execution_plan(
            document_id=normalized_document_id,
            artifacts=artifacts,
            visual_request=effective_visual_request,
            visual_artifacts=visual_artifacts,
            understanding_packet=understanding_packet,
            document_promotion_transaction=document_promotion_transaction,
            selected_operation_indexes=selected_operation_indexes,
        )
        aggregate_coverage_map = deps.completion_coverage_map(
            disassemblies=disassemblies,
            visual_artifacts=visual_artifacts,
            understanding_packet=understanding_packet,
        )
        usable = not blocking_issues
        status = "ok" if usable else "partial"
        return {
            "schema_version": self.schema_version,
            "status": status,
            "document_id": normalized_document_id,
            "artifact_id": artifact.get("artifact_id") if isinstance(artifact, dict) else artifact_id,
            "artifact_ids": [item.get("artifact_id") for item in artifacts],
            "usable": usable,
            "blocking_issues": blocking_issues,
            "requirements": {
                "ledgered_document_artifact": True,
                "visual_coverage_required": visual_required,
                "visual_request": effective_visual_request,
                "understanding_packet_required": True,
                "graph_promotion_required": True,
            },
            "execution_plan": execution_plan,
            "coverage_map": aggregate_coverage_map,
            "evidence_counts": {
                "visual_artifact_count": len(visual_artifacts),
                "source_artifact_count": len(artifacts),
                "required_visual_ref_count": len((effective_visual_request or {}).get("image_refs") or []),
                "understanding_claim_count": int(
                    ((understanding_packet or {}).get("receipt") or {}).get("claim_candidate_count") or 0
                ),
                "promotion_operation_count": len((document_promotion_transaction or {}).get("operations") or []),
                "coverage_waiver_count": len(waivers),
            },
            "policy": {
                "write_behavior": "read_only",
                "active_memory_promoted": False,
                "graph_edges_promoted": False,
            },
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None if usable else {"code": "completion_requirements_unmet", "category": "validation"},
        }
