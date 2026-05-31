"""Completion gate for making staged document evidence usable."""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from core.document_coverage import (
    artifact_covers_capability,
    artifact_matches_image_ref,
    capabilities_for_image_ref,
    page_number_from_ref,
    waiver_covers,
)
from core.memory_os._records import hash_payload, list_records, now_iso, read_record, stable_id, upsert_record
from core.memory_os.content_store import ContentAddressedStore
from core.memory_os.document_completion_assessment import (
    DocumentCompletionAssessmentDependencies,
    DocumentCompletionAssessmentService,
)
from core.memory_os.document_pipeline import DocumentPipeline
from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.transactions import MemoryTransactionService


DOCUMENT_COMPLETION_SCHEMA_VERSION = "2026-05-14.document-ingestion-completion.v1"
DOCUMENT_COMPLETION_PROGRESS_STAGES = (
    "validate",
    "materialize_evidence",
    "promote_graph",
    "mark_usable",
)


class DocumentIngestionCompletionGate:
    """Validate and complete reviewed document ingestion using existing evidence paths."""

    def __init__(self, ledger: MemoryOSLedger, store: ContentAddressedStore, runtime: Any) -> None:
        self.ledger = ledger
        self.store = store
        self.runtime = runtime
        self.pipeline = DocumentPipeline(ledger, store)
        self.assessment = DocumentCompletionAssessmentService(
            ledger=ledger,
            store=store,
            schema_version=DOCUMENT_COMPLETION_SCHEMA_VERSION,
            dependencies=DocumentCompletionAssessmentDependencies(
                required_text=_required_text,
                normalize_waivers=_normalize_waivers,
                load_document_artifact_set=_load_document_artifact_set,
                latest_coverage_map=_latest_coverage_map,
                completion_visual_request=_completion_visual_request,
                visual_coverage_required=_visual_coverage_required,
                validate_visual_evidence=_validate_visual_evidence,
                validate_understanding_packet=_validate_understanding_packet,
                validate_promotion_transaction=_validate_promotion_transaction,
                visual_artifacts=_visual_artifacts,
                completion_execution_plan=_completion_execution_plan,
                completion_coverage_map=_completion_coverage_map,
                issue=_issue,
            ),
        )

    def prepare_document_ingestion_completion(
        self,
        *,
        document_id: str,
        artifact_id: str | None = None,
        visual_request: dict[str, Any] | None = None,
        visual_preview: dict[str, Any] | None = None,
        understanding_packet: dict[str, Any] | None = None,
        document_promotion_transaction: dict[str, Any] | None = None,
        coverage_waivers: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Return a no-write usability decision for staged document evidence."""
        return self.assessment.assess(
            document_id=document_id,
            artifact_id=artifact_id,
            visual_request=visual_request,
            visual_preview=visual_preview,
            understanding_packet=understanding_packet,
            document_promotion_transaction=document_promotion_transaction,
            coverage_waivers=coverage_waivers,
        )

    def complete_document_ingestion(
        self,
        *,
        document_id: str,
        artifact_id: str | None = None,
        visual_request: dict[str, Any] | None = None,
        visual_preview: dict[str, Any] | None = None,
        understanding_packet: dict[str, Any] | None = None,
        document_promotion_transaction: dict[str, Any] | None = None,
        coverage_waivers: list[dict[str, Any]] | None = None,
        accept: bool = False,
        approved_by: str | None = None,
        selected_operation_indexes: list[int] | None = None,
    ) -> dict[str, Any]:
        """Mark a document usable after full reviewed coverage and graph promotion."""
        normalized_document_id = _required_text(document_id, "document_id")
        if not accept:
            return _error_payload(
                status="policy_denied",
                code="accept_required",
                message="complete_document_ingestion requires accept=True.",
                document_id=normalized_document_id,
                category="policy",
            )
        reviewer = str(approved_by or "").strip()
        if not reviewer:
            return _error_payload(
                status="schema_failed",
                code="approved_by_required",
                message="approved_by is required when accept=True.",
                document_id=normalized_document_id,
            )
        selected_validation = _validate_promotion_transaction(
            normalized_document_id,
            document_promotion_transaction,
            selected_operation_indexes=selected_operation_indexes,
        )
        if selected_validation:
            return _error_payload(
                status="schema_failed",
                code=selected_validation[0]["code"],
                message=selected_validation[0]["message"],
                document_id=normalized_document_id,
                blocking_issues=selected_validation,
            )

        prepared = self.prepare_document_ingestion_completion(
            document_id=normalized_document_id,
            artifact_id=artifact_id,
            visual_request=visual_request,
            visual_preview=visual_preview,
            understanding_packet=understanding_packet,
            document_promotion_transaction=document_promotion_transaction,
            coverage_waivers=coverage_waivers,
        )
        if prepared["status"] != "ok":
            return {
                **prepared,
                "status": "partial",
                "write_performed": False,
                "active_memory_write_performed": False,
                "graph_write_performed": False,
            }

        artifact_set = _load_document_artifact_set(
            self.ledger,
            self.store,
            normalized_document_id,
            artifact_id,
        )
        if artifact_set["blocking_issues"]:
            return {
                "schema_version": DOCUMENT_COMPLETION_SCHEMA_VERSION,
                "status": "partial",
                "document_id": normalized_document_id,
                "artifact_id": artifact_id,
                "artifact_ids": [item.get("artifact_id") for item in artifact_set["artifacts"]],
                "usable": False,
                "blocking_issues": artifact_set["blocking_issues"],
                "write_performed": False,
                "active_memory_write_performed": False,
                "graph_write_performed": False,
                "error": {"code": "completion_requirements_unmet", "category": "validation"},
            }
        artifacts = artifact_set["artifacts"]
        artifact = artifacts[-1] if artifacts else None
        disassemblies = artifact_set["disassemblies"]
        effective_visual_request = (prepared.get("requirements") or {}).get("visual_request")
        execution_plan = _completion_execution_plan(
            document_id=normalized_document_id,
            artifacts=artifacts,
            visual_request=effective_visual_request,
            visual_artifacts=_visual_artifacts(visual_preview),
            understanding_packet=understanding_packet,
            document_promotion_transaction=document_promotion_transaction,
            selected_operation_indexes=selected_operation_indexes,
        )
        _record_completion_progress(
            self.ledger,
            document_id=normalized_document_id,
            event_type="document_completion_started",
            payload={
                "stage": "validate",
                "stage_index": 1,
                "stage_count": 4,
                "write_scale": execution_plan["write_scale"],
            },
        )
        disassembly = _merge_disassemblies(disassemblies)
        if disassembly is None:
            return _error_payload(
                status="schema_failed",
                code="document_disassembly_required",
                message="Every staged artifact must contain the reviewed document disassembly.",
                document_id=normalized_document_id,
        )

        visual_artifacts = _visual_artifacts(visual_preview)
        pipeline_result = self.pipeline.materialize_document_job(
            disassembly,
            visual_artifacts=visual_artifacts,
            understanding_packet=understanding_packet,
        )
        execution_plan = _completion_execution_plan(
            document_id=normalized_document_id,
            artifacts=artifacts,
            visual_request=effective_visual_request,
            visual_artifacts=visual_artifacts,
            understanding_packet=understanding_packet,
            document_promotion_transaction=document_promotion_transaction,
            selected_operation_indexes=selected_operation_indexes,
        )
        _record_completion_progress(
            self.ledger,
            document_id=normalized_document_id,
            event_type="document_completion_materialized",
            payload={
                "stage": "materialize_evidence",
                "stage_index": 2,
                "stage_count": 4,
                "write_scale": execution_plan["write_scale"],
                "coverage_map_id": (pipeline_result.get("coverage_map") or {}).get("coverage_map_id"),
            },
        )
        _record_completion_progress(
            self.ledger,
            document_id=normalized_document_id,
            event_type="document_completion_graph_promotion_started",
            payload={
                "stage": "promote_graph",
                "stage_index": 3,
                "stage_count": 4,
                "write_scale": execution_plan["write_scale"],
            },
        )
        promotion_result = self.runtime.apply_document_promotion_transaction(
            document_promotion_transaction or {},
            accept=True,
            approved_by=reviewer,
            selected_operation_indexes=selected_operation_indexes,
        )
        if promotion_result.get("status") != "ok":
            _record_completion_progress(
                self.ledger,
                document_id=normalized_document_id,
                event_type="document_completion_graph_promotion_failed",
                status="failed",
                payload={
                    "stage": "promote_graph",
                    "stage_index": 3,
                    "stage_count": 4,
                    "write_scale": execution_plan["write_scale"],
                    "error": promotion_result.get("error"),
                },
            )
            return {
                "schema_version": DOCUMENT_COMPLETION_SCHEMA_VERSION,
                "status": promotion_result.get("status") or "schema_failed",
                "document_id": normalized_document_id,
                "usable": False,
                "write_performed": False,
                "active_memory_write_performed": False,
                "graph_write_performed": False,
                "promotion_result": promotion_result,
                "error": promotion_result.get("error") or {
                    "code": "promotion_failed",
                    "category": "validation",
                    "message": "Document promotion failed.",
                },
            }
        graph_edges_written = [
            str(edge_id)
            for edge_id in promotion_result.get("graph_edges_written") or []
            if str(edge_id).strip()
        ]
        _record_completion_progress(
            self.ledger,
            document_id=normalized_document_id,
            event_type="document_completion_graph_promotion_completed",
            payload={
                "stage": "promote_graph",
                "stage_index": 3,
                "stage_count": 4,
                "write_scale": {
                    **execution_plan["write_scale"],
                    "graph_edge_count": len(graph_edges_written),
                },
                "graph_edge_count": len(graph_edges_written),
            },
        )
        if not graph_edges_written:
            _record_completion_progress(
                self.ledger,
                document_id=normalized_document_id,
                event_type="document_completion_failed",
                status="failed",
                payload={
                    "stage": "promote_graph",
                    "stage_index": 3,
                    "stage_count": 4,
                    "write_scale": execution_plan["write_scale"],
                    "error": {"code": "graph_edges_required"},
                },
            )
            return _error_payload(
                status="schema_failed",
                code="graph_edges_required",
                message="Document completion requires at least one reviewed graph edge write.",
                document_id=normalized_document_id,
            )

        now = now_iso()
        coverage_map = pipeline_result.get("coverage_map") or {}
        completion_artifact = _completion_artifact_record(
            document_id=normalized_document_id,
            source_artifact=artifact or {},
            source_artifacts=artifacts,
            visual_artifacts=visual_artifacts,
            understanding_packet=understanding_packet or {},
            document_promotion_transaction=document_promotion_transaction or {},
            coverage_map=coverage_map,
            graph_edges_written=graph_edges_written,
            approved_by=reviewer,
            completed_at=now,
            store=self.store,
            coverage_waivers=coverage_waivers or [],
        )
        upsert_record(self.ledger, "knowledge_artifacts", completion_artifact["artifact_id"], completion_artifact)

        document_record = dict(pipeline_result.get("document") or {})
        completion_receipt = _completion_receipt(
            visual_artifacts=visual_artifacts,
            understanding_packet=understanding_packet or {},
            promotion_result=promotion_result,
            coverage_map=coverage_map,
            coverage_waivers=coverage_waivers or [],
        )
        document_record.update(
            {
                "usable": True,
                "ingestion_status": "usable",
                "usable_completed_at": now,
                "completion_artifact_id": completion_artifact["artifact_id"],
                "completion_receipt": completion_receipt,
            }
        )
        upsert_record(self.ledger, "documents", normalized_document_id, document_record)
        for staged_artifact in artifacts:
            staged = dict(staged_artifact)
            staged["usable_status"] = "completed"
            staged["completion_artifact_id"] = completion_artifact["artifact_id"]
            staged["updated_at"] = now
            upsert_record(self.ledger, "knowledge_artifacts", staged["artifact_id"], staged)
        _mark_document_ingestions_usable(
            self.ledger,
            document_id=normalized_document_id,
            coverage_map=coverage_map,
            completion_artifact_id=completion_artifact["artifact_id"],
            graph_edges_written=graph_edges_written,
            updated_at=now,
        )

        transaction_service = getattr(self.runtime, "transactions", None) or MemoryTransactionService(self.ledger)
        transaction_receipt = transaction_service.promote(
            operation_kind="complete_document_ingestion",
            proposed_writes=[
                {"table": "documents", "id": normalized_document_id},
                *[
                    {"table": "knowledge_artifacts", "id": item.get("artifact_id")}
                    for item in artifacts
                    if str(item.get("artifact_id") or "").strip()
                ],
                {"table": "knowledge_artifacts", "id": completion_artifact["artifact_id"]},
                *[
                    {"table": "graph_edges", "id": edge_id}
                    for edge_id in graph_edges_written
                ],
            ],
            idempotency_key=stable_id(
                "complete_document_ingestion",
                {
                "document_id": normalized_document_id,
                "source_artifact_ids": [item.get("artifact_id") for item in artifacts],
                "completion_artifact_id": completion_artifact["artifact_id"],
                "approved_by": reviewer,
                "selected_operation_indexes": selected_operation_indexes,
                },
            ),
            affected_refs=[
                {"kind": "document", "document_id": normalized_document_id},
                *[
                    {"kind": "knowledge_artifact", "artifact_id": item.get("artifact_id")}
                    for item in artifacts
                    if str(item.get("artifact_id") or "").strip()
                ],
                {"kind": "knowledge_artifact", "artifact_id": completion_artifact["artifact_id"]},
            ],
        )
        _record_completion_progress(
            self.ledger,
            document_id=normalized_document_id,
            event_type="document_completion_completed",
            status="succeeded",
            payload={
                "stage": "mark_usable",
                "stage_index": 4,
                "stage_count": 4,
                "write_scale": {
                    **execution_plan["write_scale"],
                    "graph_edge_count": len(graph_edges_written),
                },
                "completion_artifact_id": completion_artifact["artifact_id"],
                "transaction_id": transaction_receipt["transaction_id"],
            },
        )
        return {
            "schema_version": DOCUMENT_COMPLETION_SCHEMA_VERSION,
            "status": "ok",
            "document_id": normalized_document_id,
            "artifact_id": (artifact or {}).get("artifact_id"),
            "usable": True,
            "progress_job_id": execution_plan["progress_job_id"],
            "execution_plan": execution_plan,
            "completion_artifact": completion_artifact,
            "document": document_record,
            "coverage_map": coverage_map,
            "promotion_result": promotion_result,
            "transaction_id": transaction_receipt["transaction_id"],
            "transaction_receipt": transaction_receipt,
            "graph_edges_written": graph_edges_written,
            "memories_written": list(promotion_result.get("memories_written") or []),
            "policy": {
                "write_behavior": "explicit_acceptance",
                "accepted": True,
                "approved_by": reviewer,
            },
            "receipts": {
                "artifacts_built": 1,
                "artifacts_read": len(artifacts),
                **completion_receipt,
            },
            "write_performed": True,
            "active_memory_write_performed": bool(promotion_result.get("active_memory_write_performed")),
            "graph_write_performed": True,
            "error": None,
            "errors": [],
        }


def _find_document_artifact(
    ledger: MemoryOSLedger,
    document_id: str,
    artifact_id: str | None,
) -> dict[str, Any] | None:
    artifacts = _find_document_artifacts(ledger, document_id, artifact_id)
    return artifacts[-1] if artifacts else None


def _find_document_artifacts(
    ledger: MemoryOSLedger,
    document_id: str,
    artifact_id: str | None,
) -> list[dict[str, Any]]:
    matches = [
        artifact
        for artifact in list_records(ledger, "knowledge_artifacts")
        if str(artifact.get("document_id") or "") == document_id
        and str(artifact.get("artifact_type") or "") == "document_evidence"
    ]
    matches = sorted(matches, key=_artifact_sort_key)
    if artifact_id:
        normalized_artifact_id = str(artifact_id).strip()
        if not any(str(artifact.get("artifact_id") or "") == normalized_artifact_id for artifact in matches):
            return []
    return matches


def _load_document_artifact_set(
    ledger: MemoryOSLedger,
    store: ContentAddressedStore,
    document_id: str,
    artifact_id: str | None,
) -> dict[str, Any]:
    artifacts = _find_document_artifacts(ledger, document_id, artifact_id)
    issues: list[dict[str, Any]] = []
    payloads: list[dict[str, Any]] = []
    disassemblies: list[dict[str, Any]] = []

    if not artifacts:
        if artifact_id:
            return {
                "artifacts": [],
                "payloads": [],
                "disassemblies": [],
                "blocking_issues": [
                    _issue(
                        "document_artifact_not_found",
                        "The supplied document artifact id was not found for this document.",
                        artifact_id=artifact_id,
                    )
                ],
            }
        return {
            "artifacts": [],
            "payloads": [],
            "disassemblies": [],
            "blocking_issues": [
                _issue("document_artifact_required", "A ledgered document evidence artifact is required.")
            ],
        }

    source_hashes: dict[str, list[str]] = {}
    source_uris: dict[str, list[str]] = {}
    source_paths: dict[str, list[str]] = {}
    for artifact in artifacts:
        artifact_record_id = str(artifact.get("artifact_id") or "").strip()
        if artifact.get("review_state") != "ledgered_evidence":
            issues.append(
                _issue(
                    "document_artifact_not_ledgered",
                    "The document artifact must be stored as ledgered_evidence before completion.",
                    artifact_id=artifact_record_id,
                )
            )
        try:
            payload = _read_artifact_payload(store, artifact)
        except Exception as exc:
            issues.append(
                _issue(
                    "document_artifact_payload_unreadable",
                    "The staged document artifact payload could not be read.",
                    artifact_id=artifact_record_id,
                    error_type=type(exc).__name__,
                )
            )
            continue
        if not isinstance(payload, dict):
            issues.append(
                _issue(
                    "document_artifact_payload_unreadable",
                    "The staged document artifact payload could not be read.",
                    artifact_id=artifact_record_id,
                )
            )
            continue
        payloads.append(payload)

        disassembly = _artifact_disassembly(payload)
        if not isinstance(disassembly, dict):
            issues.append(
                _issue(
                    "document_disassembly_required",
                    "Every staged document artifact must contain the reviewed document disassembly.",
                    artifact_id=artifact_record_id,
                )
            )
            continue
        artifact_document_id = _disassembly_document_id(disassembly)
        if artifact_document_id != document_id:
            issues.append(
                _issue(
                    "document_artifact_document_mismatch",
                    "A staged document artifact belongs to a different document.",
                    artifact_id=artifact_record_id,
                    artifact_document_id=artifact_document_id,
                )
            )
            continue
        disassemblies.append(disassembly)
        source_hash = _artifact_source_hash(artifact, disassembly)
        if source_hash:
            source_hashes.setdefault(source_hash, []).append(artifact_record_id)
        source_uri = _artifact_source_uri(disassembly)
        if source_uri:
            source_uris.setdefault(source_uri, []).append(artifact_record_id)
        source_path = _artifact_source_path(disassembly)
        if source_path:
            source_paths.setdefault(source_path, []).append(artifact_record_id)

    if len(source_hashes) > 1:
        issues.append(
            _issue(
                "document_source_mismatch",
                "All staged document artifacts for completion must come from the same source content hash.",
                source_hashes=sorted(source_hashes),
            )
        )
    if len(source_uris) > 1:
        issues.append(
            _issue(
                "document_source_mismatch",
                "All staged document artifacts for completion must come from the same source URI.",
                source_uris=sorted(source_uris),
            )
        )
    if len(source_paths) > 1:
        issues.append(
            _issue(
                "document_source_mismatch",
                "All staged document artifacts for completion must come from the same source path.",
                source_paths=sorted(source_paths),
            )
        )

    return {
        "artifacts": artifacts,
        "payloads": payloads,
        "disassemblies": disassemblies,
        "blocking_issues": issues,
    }


def _artifact_sort_key(artifact: dict[str, Any]) -> tuple[int, str, str]:
    page = _artifact_min_page(artifact)
    return (
        page if page is not None else 10**9,
        str(artifact.get("created_at") or ""),
        str(artifact.get("artifact_id") or ""),
    )


def _artifact_min_page(artifact: dict[str, Any]) -> int | None:
    pages = [
        page_number_from_ref(ref)
        for ref in artifact.get("page_refs") or []
        if isinstance(ref, dict)
    ]
    pages = [page for page in pages if page is not None]
    return min(pages) if pages else None


def _disassembly_document_id(disassembly: dict[str, Any]) -> str:
    document = disassembly.get("document") if isinstance(disassembly.get("document"), dict) else {}
    return str(document.get("document_id") or "").strip()


def _artifact_source_hash(artifact: dict[str, Any], disassembly: dict[str, Any]) -> str:
    source = disassembly.get("source") if isinstance(disassembly.get("source"), dict) else {}
    document = disassembly.get("document") if isinstance(disassembly.get("document"), dict) else {}
    return str(
        source.get("content_hash")
        or document.get("content_hash")
        or artifact.get("source_sha256")
        or ""
    ).strip()


def _artifact_source_uri(disassembly: dict[str, Any]) -> str:
    source = disassembly.get("source") if isinstance(disassembly.get("source"), dict) else {}
    return str(source.get("source_uri") or "").strip()


def _artifact_source_path(disassembly: dict[str, Any]) -> str:
    source = disassembly.get("source") if isinstance(disassembly.get("source"), dict) else {}
    return str(source.get("path") or source.get("source_path") or "").strip()


def _latest_coverage_map(ledger: MemoryOSLedger, document_id: str) -> dict[str, Any] | None:
    matches = [
        receipt
        for receipt in list_records(ledger, "retrieval_receipts")
        if str(receipt.get("document_id") or "") == document_id
    ]
    return matches[-1] if matches else None


def _read_artifact_payload(
    store: ContentAddressedStore,
    artifact: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(artifact, dict):
        return None
    content_ref = str(artifact.get("content_ref") or "").strip()
    if not content_ref:
        return None
    decoded = json.loads(store.read_bytes(content_ref).decode("utf-8"))
    return decoded if isinstance(decoded, dict) else None


def _artifact_disassembly(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    disassembly = payload.get("disassembly")
    if isinstance(disassembly, dict):
        return disassembly
    review_packet = payload.get("review_packet")
    if isinstance(review_packet, dict) and isinstance(review_packet.get("disassembly"), dict):
        return review_packet["disassembly"]
    return None


def _merge_disassemblies(disassemblies: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not disassemblies:
        return None
    merged = deepcopy(disassemblies[0])
    pages_by_number: dict[int, dict[str, Any]] = {}
    text_parts: list[str] = []
    image_pages: set[int] = set()
    image_count = 0
    page_count = 0
    page_ranges: list[dict[str, Any]] = []
    quality_pages: dict[str, set[int]] = {
        "text_pages": set(),
        "low_text_pages": set(),
        "no_text_pages": set(),
        "image_pages": set(),
        "table_candidate_pages": set(),
        "visual_review_needed_pages": set(),
    }
    for disassembly in disassemblies:
        document = disassembly.get("document") if isinstance(disassembly.get("document"), dict) else {}
        try:
            page_count = max(page_count, int(document.get("page_count") or 0))
        except (TypeError, ValueError):
            pass
        page_range = document.get("page_range") if isinstance(document.get("page_range"), dict) else None
        if page_range:
            page_ranges.append(dict(page_range))
        for page in disassembly.get("pages") or []:
            if not isinstance(page, dict):
                continue
            page_number = page_number_from_ref(page)
            if page_number is not None:
                pages_by_number[page_number] = dict(page)
        text = disassembly.get("text") if isinstance(disassembly.get("text"), dict) else {}
        content = str(text.get("content") or "")
        if content:
            text_parts.append(content)
        inventory = disassembly.get("image_inventory") if isinstance(disassembly.get("image_inventory"), dict) else {}
        image_count += int(inventory.get("image_count") or 0)
        image_pages.update(int(page) for page in inventory.get("pages_with_images") or [] if _positive_int(page))
        seed = disassembly.get("quality_seed") if isinstance(disassembly.get("quality_seed"), dict) else {}
        for key in quality_pages:
            quality_pages[key].update(
                int(page) for page in seed.get(key) or [] if _positive_int(page)
            )

    pages = [pages_by_number[number] for number in sorted(pages_by_number)]
    merged_document = dict(merged.get("document") if isinstance(merged.get("document"), dict) else {})
    if page_count:
        merged_document["page_count"] = page_count
        merged_document["page_limit"] = page_count
    merged_document["pages_returned"] = len(pages)
    merged_document["page_range"] = _merged_page_range(page_ranges, pages)
    merged["document"] = merged_document
    merged["pages"] = pages
    merged["text"] = {
        **dict(merged.get("text") if isinstance(merged.get("text"), dict) else {}),
        "content": "\f".join(text_parts),
        "char_count": sum(len(part) for part in text_parts),
        "page_count": len(pages),
    }
    merged["image_inventory"] = {
        **dict(merged.get("image_inventory") if isinstance(merged.get("image_inventory"), dict) else {}),
        "image_count": image_count,
        "pages_with_images": sorted(image_pages),
    }
    merged["quality_seed"] = {
        **dict(merged.get("quality_seed") if isinstance(merged.get("quality_seed"), dict) else {}),
        "page_count": merged_document.get("page_count"),
        "pages_reported": len(pages),
        **{key: sorted(values) for key, values in quality_pages.items()},
    }
    return merged


def _merged_page_range(page_ranges: list[dict[str, Any]], pages: list[dict[str, Any]]) -> dict[str, Any] | None:
    starts = [_positive_int(item.get("start")) for item in page_ranges]
    ends = [_positive_int(item.get("end")) for item in page_ranges]
    starts = [item for item in starts if item is not None]
    ends = [item for item in ends if item is not None]
    if starts and ends:
        return {"start": min(starts), "end": max(ends)}
    page_numbers = [page_number_from_ref(page) for page in pages]
    page_numbers = [page for page in page_numbers if page is not None]
    if not page_numbers:
        return None
    return {"start": min(page_numbers), "end": max(page_numbers)}


def _completion_visual_request(
    document_id: str,
    *,
    visual_request: dict[str, Any] | None,
    artifact_payloads: list[dict[str, Any]],
    disassemblies: list[dict[str, Any]],
) -> dict[str, Any] | None:
    required_refs = _merge_visual_refs(
        [
            *_staged_visual_refs(artifact_payloads),
            *_required_visual_refs(disassemblies),
        ],
        fallback=[],
    )
    if not isinstance(visual_request, dict):
        if not required_refs:
            return None
        return {
            "request_id": f"vis_req_{document_id}_completion",
            "document_id": document_id,
            "image_refs": required_refs,
            "requested_capabilities": _capability_union(required_refs, []),
        }
    merged = dict(visual_request)
    existing_refs = [dict(ref) for ref in merged.get("image_refs") or [] if isinstance(ref, dict)]
    existing_refs = _merge_visual_refs(existing_refs, fallback=merged.get("requested_capabilities") or [])
    by_key = {_visual_ref_key(ref): ref for ref in existing_refs}
    for required in required_refs:
        key = _visual_ref_key(required)
        if key is None:
            continue
        existing = by_key.get(key)
        if existing is None:
            existing_refs.append(required)
            by_key[key] = required
            continue
        existing["requested_capabilities"] = sorted(
            {
                *capabilities_for_image_ref(existing, merged.get("requested_capabilities") or []),
                *capabilities_for_image_ref(required, []),
            }
        )
    merged["image_refs"] = existing_refs
    merged["requested_capabilities"] = _capability_union(existing_refs, merged.get("requested_capabilities") or [])
    return merged


def _staged_visual_refs(artifact_payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for payload in artifact_payloads:
        review_packet = payload.get("review_packet") if isinstance(payload.get("review_packet"), dict) else {}
        request = (
            review_packet.get("extraction_request")
            if isinstance(review_packet.get("extraction_request"), dict)
            else {}
        )
        for image_ref in request.get("image_refs") or []:
            if not isinstance(image_ref, dict):
                continue
            ref = dict(image_ref)
            ref["requested_capabilities"] = capabilities_for_image_ref(ref, [])
            refs.append(ref)
    return refs


def _required_visual_refs(disassemblies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs_by_page: dict[int, dict[str, Any]] = {}
    for disassembly in disassemblies:
        source = disassembly.get("source") if isinstance(disassembly.get("source"), dict) else {}
        source_uri = str(source.get("source_uri") or "").strip()
        seed = disassembly.get("quality_seed") if isinstance(disassembly.get("quality_seed"), dict) else {}
        ocr_pages = _page_set(seed.get("no_text_pages")) | _page_set(seed.get("low_text_pages"))
        table_pages = _page_set(seed.get("table_candidate_pages"))
        image_pages = _page_set(seed.get("image_pages"))
        visual_pages = _page_set(seed.get("visual_review_needed_pages"))
        for page in disassembly.get("pages") or []:
            if not isinstance(page, dict):
                continue
            page_number = page_number_from_ref(page)
            if page_number is None:
                continue
            capabilities: set[str] = set()
            if page_number in ocr_pages:
                capabilities.add("ocr_text")
            if page_number in table_pages:
                capabilities.add("table_structure")
            if page_number in image_pages or page_number in visual_pages or page.get("visual_review_needed"):
                capabilities.add("figure_description")
            if not capabilities:
                continue
            ref = refs_by_page.setdefault(
                page_number,
                {
                    "source_uri": source_uri,
                    "page_number": page_number,
                    "requested_capabilities": [],
                },
            )
            ref["requested_capabilities"] = sorted({*ref["requested_capabilities"], *capabilities})
    return [refs_by_page[page] for page in sorted(refs_by_page)]


def _merge_visual_refs(refs: list[dict[str, Any]], *, fallback: list[str]) -> list[dict[str, Any]]:
    merged: dict[tuple[Any, ...], dict[str, Any]] = {}
    order: list[tuple[Any, ...]] = []
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        key = _visual_ref_key(ref)
        if key is None:
            continue
        target_key = next(
            (
                existing_key
                for existing_key in order
                if _visual_refs_can_merge(merged[existing_key], ref)
            ),
            None,
        )
        capabilities = capabilities_for_image_ref(ref, fallback)
        existing = merged.get(target_key) if target_key is not None else None
        if existing is None:
            existing = dict(ref)
            existing["requested_capabilities"] = capabilities
            merged[key] = existing
            order.append(key)
            continue
        existing["requested_capabilities"] = sorted(
            {*capabilities_for_image_ref(existing, fallback), *capabilities}
        )
        for field in (
            "source_artifact_id",
            "source_artifact_ref",
            "artifact_id",
            "ref",
            "image_hash",
            "source_uri",
            "bounding_box",
            "bbox",
            "coordinates",
        ):
            if existing.get(field) is None and ref.get(field) is not None:
                existing[field] = ref[field]
    return [merged[key] for key in order]


def _visual_ref_key(ref: dict[str, Any]) -> tuple[Any, ...] | None:
    page_number = page_number_from_ref(ref)
    artifact_id = _visual_ref_artifact_token(ref)
    if artifact_id:
        return ("artifact", artifact_id, page_number)
    source_uri = str(ref.get("source_uri") or "").strip()
    if source_uri or page_number is not None:
        return ("source", source_uri, page_number)
    return None


def _visual_refs_can_merge(existing: dict[str, Any], candidate: dict[str, Any]) -> bool:
    existing_page = page_number_from_ref(existing)
    candidate_page = page_number_from_ref(candidate)
    if existing_page != candidate_page:
        return False
    existing_artifact = _visual_ref_artifact_token(existing)
    candidate_artifact = _visual_ref_artifact_token(candidate)
    if existing_artifact and candidate_artifact and existing_artifact != candidate_artifact:
        return False
    existing_source = str(existing.get("source_uri") or "").strip()
    candidate_source = str(candidate.get("source_uri") or "").strip()
    return not (existing_source and candidate_source and existing_source != candidate_source)


def _visual_ref_artifact_token(ref: dict[str, Any]) -> str:
    return str(
        ref.get("source_artifact_id")
        or ref.get("source_artifact_ref")
        or ref.get("artifact_id")
        or ref.get("ref")
        or ref.get("image_hash")
        or ""
    ).strip()


def _capability_union(refs: list[dict[str, Any]], fallback: list[str]) -> list[str]:
    capabilities = {str(item) for item in fallback or [] if str(item).strip()}
    for ref in refs:
        capabilities.update(capabilities_for_image_ref(ref, []))
    return sorted(capabilities)


def _page_set(value: Any) -> set[int]:
    return {int(item) for item in value or [] if _positive_int(item)}


def _positive_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _completion_coverage_map(
    *,
    disassemblies: list[dict[str, Any]],
    visual_artifacts: list[dict[str, Any]],
    understanding_packet: dict[str, Any] | None,
) -> dict[str, Any] | None:
    disassembly = _merge_disassemblies(disassemblies)
    if disassembly is None:
        return None
    return DocumentPipeline._coverage_map(
        disassembly,
        chunks=[],
        visual_artifacts=visual_artifacts,
        understanding_packet=understanding_packet or {},
        licensing={},
    )


def _mark_document_ingestions_usable(
    ledger: MemoryOSLedger,
    *,
    document_id: str,
    coverage_map: dict[str, Any],
    completion_artifact_id: str,
    graph_edges_written: list[str],
    updated_at: str,
) -> None:
    for record in list_records(ledger, "jobs"):
        if record.get("record_type") != "document_ingestion":
            continue
        if str(record.get("document_id") or "") != document_id:
            continue
        readiness = dict(record.get("readiness") or {})
        readiness.update(
            {
                "ocr_covered": not list(coverage_map.get("missing_ocr_pages") or []),
                "visual_covered": not list(coverage_map.get("missing_visual_pages") or []),
                "table_covered": not list(coverage_map.get("missing_table_pages") or []),
                "semantic_graph_covered": bool(graph_edges_written),
                "usable": True,
            }
        )
        updated = {
            **record,
            "status": "completed",
            "readiness": readiness,
            "completion_artifact_id": completion_artifact_id,
            "updated_at": updated_at,
        }
        upsert_record(ledger, "jobs", str(record.get("ingestion_id") or record.get("job_id")), updated)


def _visual_coverage_required(
    *,
    artifacts: list[dict[str, Any]],
    coverage: dict[str, Any] | None,
    disassemblies: list[dict[str, Any]],
    visual_request: dict[str, Any] | None,
) -> bool:
    if isinstance(visual_request, dict):
        return True
    for artifact in artifacts:
        coverage_missing = set(((artifact or {}).get("coverage_receipt") or {}).get("coverage_missing") or [])
        if coverage_missing & {"ocr", "table", "visual"}:
            return True
    if isinstance(coverage, dict) and int(coverage.get("skipped_region_count") or 0) > 0:
        return True
    for disassembly in disassemblies:
        for page in (disassembly or {}).get("pages") or []:
            if isinstance(page, dict) and page.get("visual_review_needed"):
                return True
    return False


def _validate_visual_evidence(
    document_id: str,
    *,
    visual_required: bool,
    visual_request: dict[str, Any] | None,
    visual_preview: dict[str, Any] | None,
    waivers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not visual_required:
        return []
    if not isinstance(visual_preview, dict):
        return [_issue("visual_coverage_required", "Visual, OCR, or table coverage is required before completion.")]
    issues: list[dict[str, Any]] = []
    if str(visual_preview.get("document_id") or document_id) != document_id:
        issues.append(_issue("visual_document_mismatch", "Visual preview document_id does not match document_id."))
    if visual_preview.get("status") != "ok":
        issues.append(
            _issue(
                "visual_preview_not_complete",
                "Visual preview must be ok before document completion.",
                preview_status=visual_preview.get("status"),
            )
        )
    coverage = visual_preview.get("visual_coverage")
    if isinstance(coverage, dict) and coverage.get("coverage_complete") is not True:
        issues.append(
            _issue(
                "visual_image_ref_coverage_incomplete",
                "Every requested image ref must have reviewed visual evidence.",
                missing_image_refs=coverage.get("missing_image_refs") or [],
            )
        )
    warnings = [
        warning
        for warning in visual_preview.get("quality_warnings") or []
        if isinstance(warning, dict) and warning.get("severity") in {"high", "medium"}
    ]
    if warnings:
        issues.append(
            _issue(
                "visual_quality_warnings",
                "Visual preview contains blocking quality warnings.",
                warning_codes=[warning.get("code") for warning in warnings],
            )
        )

    artifacts = _visual_artifacts(visual_preview)
    if not artifacts:
        issues.append(_issue("visual_artifacts_required", "Visual preview must include reviewed artifacts."))
    if isinstance(visual_request, dict):
        issues.extend(_validate_visual_capability_coverage(visual_request, artifacts, waivers))
    return issues


def _validate_visual_capability_coverage(
    visual_request: dict[str, Any],
    artifacts: list[dict[str, Any]],
    waivers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    fallback_capabilities = [
        str(item)
        for item in visual_request.get("requested_capabilities") or []
        if str(item).strip()
    ]
    for image_ref in visual_request.get("image_refs") or []:
        page_number = page_number_from_ref(image_ref)
        matching_artifacts = [
            artifact for artifact in artifacts if artifact_matches_image_ref(artifact, image_ref)
        ]
        for capability in capabilities_for_image_ref(image_ref, fallback_capabilities):
            if any(artifact_covers_capability(artifact, capability) for artifact in matching_artifacts):
                continue
            if waiver_covers(waivers, page_number=page_number, capability=capability):
                continue
            issues.append(
                _issue(
                    "missing_visual_capability",
                    "A requested visual capability is not covered by reviewed evidence.",
                    page_number=page_number,
                    capability=capability,
                )
            )
    return issues


def _validate_understanding_packet(
    document_id: str,
    packet: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(packet, dict):
        return [_issue("understanding_packet_required", "A reviewed document understanding packet is required.")]
    issues: list[dict[str, Any]] = []
    if packet.get("record_type") != "document_understanding_packet":
        issues.append(_issue("invalid_understanding_packet", "record_type must be document_understanding_packet."))
    if str(packet.get("document_id") or "") != document_id:
        issues.append(_issue("understanding_document_mismatch", "Understanding packet document_id does not match."))
    receipt = packet.get("receipt") if isinstance(packet.get("receipt"), dict) else {}
    required_counts = {
        "summary_slot_count": "summary_required",
        "claim_candidate_count": "claims_required",
        "concept_candidate_count": "concepts_required",
        "candidate_graph_edge_count": "graph_proposals_required",
        "chunk_ref_count": "chunk_refs_required",
    }
    for field, code in required_counts.items():
        if int(receipt.get(field) or 0) <= 0:
            issues.append(_issue(code, f"Understanding packet requires {field} > 0."))
    if int(receipt.get("low_confidence_warning_count") or 0) > 0:
        issues.append(_issue("low_confidence_understanding", "Low-confidence understanding warnings must be reviewed."))
    for claim in packet.get("claim_candidates") or []:
        if isinstance(claim, dict) and not claim.get("evidence_refs"):
            issues.append(
                _issue(
                    "claim_evidence_required",
                    "Every claim candidate must have explicit evidence refs.",
                    claim_id=claim.get("claim_id"),
                )
            )
    if not isinstance(packet.get("document_draft"), dict):
        issues.append(_issue("document_draft_required", "Understanding packet must include a document draft."))
    return issues


def _validate_promotion_transaction(
    document_id: str,
    transaction: dict[str, Any] | None,
    *,
    selected_operation_indexes: list[int] | None,
) -> list[dict[str, Any]]:
    if not isinstance(transaction, dict):
        return [_issue("promotion_transaction_required", "A reviewed document promotion transaction is required.")]
    issues: list[dict[str, Any]] = []
    if transaction.get("record_type") != "document_promotion_transaction":
        issues.append(_issue("invalid_promotion_transaction", "record_type must be document_promotion_transaction."))
    if str(transaction.get("document_id") or "") != document_id:
        issues.append(_issue("promotion_document_mismatch", "Promotion transaction document_id does not match."))
    operations = transaction.get("operations")
    if not isinstance(operations, list) or not operations:
        issues.append(_issue("promotion_operations_required", "Promotion transaction requires operations."))
        return issues
    selected = _selected_operations(operations, selected_operation_indexes)
    if isinstance(selected, dict):
        issues.append(selected)
        return issues
    if not any(operation.get("kind") == "graph_edge" for operation in selected):
        issues.append(_issue("graph_edges_required", "Document completion requires at least one selected graph edge."))
    return issues


def _selected_operations(
    operations: list[dict[str, Any]],
    selected_operation_indexes: list[int] | None,
) -> list[dict[str, Any]] | dict[str, Any]:
    if selected_operation_indexes is None:
        return operations
    if not isinstance(selected_operation_indexes, list):
        return _issue("selected_operation_indexes_invalid", "selected_operation_indexes must be a list.")
    selected: list[dict[str, Any]] = []
    for item in selected_operation_indexes:
        if isinstance(item, bool) or not isinstance(item, int):
            return _issue("selected_operation_index_invalid", "selected operation indexes must be integers.")
        if item < 0 or item >= len(operations):
            return _issue("selected_operation_index_out_of_range", "selected operation index out of range.")
        selected.append(operations[item])
    if not selected:
        return _issue("selected_operations_required", "at least one operation must be selected.")
    return selected


def _completion_artifact_record(
    *,
    document_id: str,
    source_artifact: dict[str, Any],
    source_artifacts: list[dict[str, Any]],
    visual_artifacts: list[dict[str, Any]],
    understanding_packet: dict[str, Any],
    document_promotion_transaction: dict[str, Any],
    coverage_map: dict[str, Any],
    graph_edges_written: list[str],
    approved_by: str,
    completed_at: str,
    store: ContentAddressedStore,
    coverage_waivers: list[dict[str, Any]],
) -> dict[str, Any]:
    source_artifact_ids = [
        str(artifact.get("artifact_id"))
        for artifact in source_artifacts
        if str(artifact.get("artifact_id") or "").strip()
    ]
    payload = {
        "schema_version": DOCUMENT_COMPLETION_SCHEMA_VERSION,
        "document_id": document_id,
        "source_artifact_id": source_artifact.get("artifact_id"),
        "source_artifact_ids": source_artifact_ids,
        "visual_artifact_ids": [artifact.get("artifact_id") for artifact in visual_artifacts],
        "understanding_packet_id": understanding_packet.get("packet_id"),
        "promotion_transaction_id": document_promotion_transaction.get("transaction_id"),
        "coverage_map_id": coverage_map.get("coverage_map_id"),
        "graph_edges_written": graph_edges_written,
        "coverage_waivers": coverage_waivers,
        "approved_by": approved_by,
        "completed_at": completed_at,
    }
    content_ref = store.put_bytes(_json_bytes(payload), suffix=".json")
    artifact_id = _readable_record_id(
        "doc_completion",
        document_id,
        {
            "document_id": document_id,
            "source_artifact_ids": source_artifact_ids,
            "visual_artifact_ids": payload["visual_artifact_ids"],
            "understanding_packet_id": understanding_packet.get("packet_id"),
            "promotion_transaction_id": document_promotion_transaction.get("transaction_id"),
            "graph_edges_written": graph_edges_written,
        },
    )
    source_ref = None
    citations = source_artifact.get("citations") if isinstance(source_artifact.get("citations"), list) else []
    if citations and isinstance(citations[0], dict):
        source_ref = citations[0].get("source_ref")
    return {
        "schema_version": DOCUMENT_COMPLETION_SCHEMA_VERSION,
        "artifact_id": artifact_id,
        "artifact_type": "document_completion",
        "document_id": document_id,
        "content_ref": content_ref,
        "source_artifact_id": source_artifact.get("artifact_id"),
        "source_artifact_ids": source_artifact_ids,
        "visual_artifact_ids": payload["visual_artifact_ids"],
        "understanding_packet_id": understanding_packet.get("packet_id"),
        "promotion_transaction_id": document_promotion_transaction.get("transaction_id"),
        "coverage_map_id": coverage_map.get("coverage_map_id"),
        "graph_edge_ids": graph_edges_written,
        "review_state": "usable",
        "created_by_tool": "complete_document_ingestion",
        "approved_by": approved_by,
        "created_at": completed_at,
        "active_memory_write_performed": False,
        "graph_write_performed": True,
        "completion_receipt": _completion_receipt(
            visual_artifacts=visual_artifacts,
            understanding_packet=understanding_packet,
            promotion_result={"graph_edges_written": graph_edges_written, "memories_written": []},
            coverage_map=coverage_map,
            coverage_waivers=coverage_waivers,
        ),
        "citations": [
            {
                "citation_id": f"doc_completion:{_slugify(document_id)}:document",
                "level": "document",
                "source": "memory_os",
                "document_id": document_id,
                "source_ref": source_ref,
            }
        ],
    }


def _completion_receipt(
    *,
    visual_artifacts: list[dict[str, Any]],
    understanding_packet: dict[str, Any],
    promotion_result: dict[str, Any],
    coverage_map: dict[str, Any],
    coverage_waivers: list[dict[str, Any]],
) -> dict[str, Any]:
    receipt = understanding_packet.get("receipt") if isinstance(understanding_packet.get("receipt"), dict) else {}
    return {
        "visual_artifact_count": len(visual_artifacts),
        "claim_count": int(receipt.get("claim_candidate_count") or coverage_map.get("claim_count") or 0),
        "concept_count": int(receipt.get("concept_candidate_count") or coverage_map.get("concept_count") or 0),
        "graph_proposal_count": int(receipt.get("candidate_graph_edge_count") or coverage_map.get("graph_proposal_count") or 0),
        "graph_edge_count": len(promotion_result.get("graph_edges_written") or []),
        "memory_count": len(promotion_result.get("memories_written") or []),
        "coverage_waiver_count": len(coverage_waivers),
        "coverage_map_id": coverage_map.get("coverage_map_id"),
        "skipped_region_count": int(coverage_map.get("skipped_region_count") or 0),
        "coverage_complete": bool(coverage_map.get("coverage_complete")),
    }


def _visual_artifacts(visual_preview: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(visual_preview, dict):
        return []
    return [dict(artifact) for artifact in visual_preview.get("visual_artifacts") or [] if isinstance(artifact, dict)]


def _normalize_waivers(value: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    waivers: list[dict[str, Any]] = []
    for item in value or []:
        if not isinstance(item, dict):
            continue
        capability = str(item.get("capability") or "").strip()
        reason = str(item.get("reason") or "").strip()
        approved_by = str(item.get("approved_by") or "").strip()
        if not capability or not reason or not approved_by:
            continue
        waivers.append({**item, "capability": capability, "approved_by": approved_by, "reason": reason})
    return waivers


def _page_number(value: dict[str, Any]) -> int | None:
    page = value.get("page_number") or value.get("page")
    if isinstance(page, bool):
        return None
    try:
        page_int = int(page)
    except (TypeError, ValueError):
        return None
    return page_int if page_int > 0 else None


def _completion_progress_job_id(document_id: str) -> str:
    return f"document_completion:{document_id}"


def _completion_execution_plan(
    *,
    document_id: str,
    artifacts: list[dict[str, Any]],
    visual_request: dict[str, Any] | None,
    visual_artifacts: list[dict[str, Any]],
    understanding_packet: dict[str, Any] | None,
    document_promotion_transaction: dict[str, Any] | None,
    selected_operation_indexes: list[int] | None = None,
) -> dict[str, Any]:
    operations = [
        operation
        for operation in (document_promotion_transaction or {}).get("operations") or []
        if isinstance(operation, dict)
    ]
    if selected_operation_indexes is not None:
        selected: set[int] = set()
        for index in selected_operation_indexes:
            if isinstance(index, bool):
                continue
            try:
                normalized_index = int(index)
            except (TypeError, ValueError):
                continue
            if 0 <= normalized_index < len(operations):
                selected.add(normalized_index)
        operations = [operation for index, operation in enumerate(operations) if index in selected]
    write_scale = {
        "source_artifact_count": len(artifacts),
        "visual_artifact_count": len(visual_artifacts),
        "required_visual_ref_count": len((visual_request or {}).get("image_refs") or []),
        "understanding_claim_count": int(
            ((understanding_packet or {}).get("receipt") or {}).get("claim_candidate_count") or 0
        ),
        "promotion_operation_count": len(operations),
        "graph_operation_count": sum(1 for operation in operations if operation.get("kind") == "graph_edge"),
        "memory_operation_count": sum(1 for operation in operations if operation.get("kind") == "memory"),
    }
    return {
        "progress_job_id": _completion_progress_job_id(document_id),
        "write_scale": write_scale,
        "progress_event_types": [
            "document_completion_started",
            "document_completion_materialized",
            "document_completion_graph_promotion_started",
            "document_completion_graph_promotion_completed",
            "document_completion_completed",
        ],
        "stages": [
            {
                "stage": stage,
                "stage_index": index,
                "stage_count": len(DOCUMENT_COMPLETION_PROGRESS_STAGES),
            }
            for index, stage in enumerate(DOCUMENT_COMPLETION_PROGRESS_STAGES, start=1)
        ],
    }


def _record_completion_progress(
    ledger: MemoryOSLedger,
    *,
    document_id: str,
    event_type: str,
    payload: dict[str, Any],
    status: str = "running",
) -> dict[str, Any]:
    timestamp = now_iso()
    job_id = _completion_progress_job_id(document_id)
    existing = read_record(ledger, "jobs", job_id) or {}
    job = {
        **existing,
        "job_id": job_id,
        "job_kind": "document_ingestion_completion",
        "document_id": document_id,
        "status": status,
        "payload": {"document_id": document_id},
        "progress": dict(payload),
        "created_at": existing.get("created_at") or timestamp,
        "updated_at": timestamp,
    }
    upsert_record(ledger, "jobs", job_id, job)
    event = {
        "event_id": stable_id(
            "job_event",
            {
                "job_id": job_id,
                "event_type": event_type,
                "payload": payload,
                "created_at": timestamp,
            },
        ),
        "job_id": job_id,
        "event_type": event_type,
        "payload": dict(payload),
        "created_at": timestamp,
    }
    upsert_record(ledger, "job_events", event["event_id"], event)
    return event


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _issue(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **extra}


def _error_payload(
    *,
    status: str,
    code: str,
    message: str,
    document_id: str,
    category: str = "validation",
    blocking_issues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": DOCUMENT_COMPLETION_SCHEMA_VERSION,
        "status": status,
        "document_id": document_id,
        "usable": False,
        "blocking_issues": blocking_issues or [{"code": code, "message": message}],
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "error": {"code": code, "category": category, "message": message},
    }


def _readable_record_id(prefix: str, readable_label: Any, payload: Any) -> str:
    digest = hash_payload(payload).removeprefix("sha256:")[:12]
    label = _slugify(str(readable_label or "document"), max_length=96)
    return f"{prefix}:{label}:{digest}" if label else f"{prefix}:{digest}"


def _slugify(value: str, *, max_length: int = 80) -> str:
    slug = "".join(char.lower() if char.isalnum() else "_" for char in str(value).strip())
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_")[:max_length].strip("_")


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
