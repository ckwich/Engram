"""Document Intelligence Ingestion orchestration for Memory OS."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from core.document_intelligence import (
    prepare_document_promotion_transaction,
    prepare_document_understanding_packet,
)
from core.document_intake_workflow import prepare_document_intake_review
from core.memory_os._records import hash_payload, list_records, now_iso, read_record, stable_id, upsert_record
from core.memory_os.document_catalog import (
    enrich_document_chunk_metadata,
    enrich_document_identity_metadata,
    enrich_document_record,
    merge_catalog_into_chunk_metadata,
)
from core.memory_os.document_coverage_pass import COVERAGE_POLICIES
from core.memory_os.document_ingestion_stages import build_document_ingestion_stage_report
from core.memory_os.document_staged_evidence import load_staged_document_evidence
from core.memory_os.ledger import MemoryOSLedger


DOCUMENT_INGESTION_SCHEMA_VERSION = "2026-05-16.document-ingestion.v1"
DOCUMENT_INGESTION_EXECUTION_JOB_KIND = "document_ingestion_execution"
INGESTION_PROFILES = {"searchable", "graph_coverage", "full"}
ANALYSIS_POLICIES = {"defer", "connected_agent", "external_adapter"}
APPROVAL_MODES = {"plan_only", "agent_authorized"}


class DocumentIngestionOrchestrator:
    """Coordinate document evidence ingestion without owning extractors directly."""

    def __init__(self, runtime: Any, *, document_intake_reviewer: Any = prepare_document_intake_review) -> None:
        self.runtime = runtime
        self.ledger: MemoryOSLedger = runtime.ledger
        self.document_intake_reviewer = document_intake_reviewer

    def prepare_document_ingestion_plan(
        self,
        *,
        source_path: str,
        project: str | None = None,
        domain: str | None = None,
        profile: str = "graph_coverage",
        page_window_size: int = 25,
        analysis_policy: str = "defer",
        approval_mode: str = "agent_authorized",
        coverage_policy: str = "auto_local",
        coverage_options: dict[str, Any] | None = None,
        budget: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source = _source_summary(source_path)
        normalized_profile = _choice(profile, INGESTION_PROFILES, "profile")
        normalized_analysis_policy = _choice(analysis_policy, ANALYSIS_POLICIES, "analysis_policy")
        normalized_approval_mode = _choice(approval_mode, APPROVAL_MODES, "approval_mode")
        normalized_coverage_policy = _choice(coverage_policy, COVERAGE_POLICIES, "coverage_policy")
        normalized_window_size = _page_window_size(page_window_size)
        ingestion_id = _ingestion_id(
            source=source,
            profile=normalized_profile,
            project=project,
            domain=domain,
        )
        existing = read_record(self.ledger, "jobs", ingestion_id)
        if isinstance(existing, dict) and existing.get("record_type") == "document_ingestion":
            return self.inspect_document_ingestion(ingestion_id=ingestion_id)

        now = now_iso()
        record = {
            "schema_version": DOCUMENT_INGESTION_SCHEMA_VERSION,
            "record_type": "document_ingestion",
            "job_id": ingestion_id,
            "ingestion_id": ingestion_id,
            "status": "planned",
            "source": source,
            "project": project,
            "domain": domain,
            "profile": normalized_profile,
            "page_window_size": normalized_window_size,
            "analysis_policy": normalized_analysis_policy,
            "approval_mode": normalized_approval_mode,
            "coverage_policy": normalized_coverage_policy,
            "coverage_options": dict(coverage_options or {}),
            "budget": dict(budget or {}),
            "windows": [],
            "artifacts": [],
            "graph_edges_written": [],
            "understanding_packet": None,
            "document_promotion_transaction": None,
            "semantic_graph_edges_written": [],
            "memories_written": [],
            "coverage_maps": [],
            "coverage_pass": None,
            "visual_preview": None,
            "readiness": _empty_readiness(),
            "errors": [],
            "created_at": now,
            "updated_at": now,
        }
        upsert_record(self.ledger, "jobs", ingestion_id, record)
        return {
            **record,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "next_action": {"tool": "run_document_ingestion", "ingestion_id": ingestion_id},
            "error": None,
        }

    def run_document_ingestion(
        self,
        *,
        ingestion_id: str,
        accept: bool = False,
        approved_by: str | None = None,
        review_packets: list[dict[str, Any]] | None = None,
        understanding_analysis: dict[str, Any] | None = None,
        visual_preview: dict[str, Any] | None = None,
        coverage_policy: str | None = None,
        coverage_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_ingestion_id = str(ingestion_id or "").strip()
        record = _find_ingestion(self.ledger, ingestion_id=normalized_ingestion_id, document_id=None)
        if record is None:
            return _ingestion_error(
                "not_found",
                "not_found",
                "document ingestion was not found",
                ingestion_id=normalized_ingestion_id,
                category="not_found",
            )
        if not accept:
            return _ingestion_error(
                "policy_denied",
                "accept_required",
                "run_document_ingestion requires accept=True.",
                ingestion_id=normalized_ingestion_id,
                category="policy",
            )
        reviewer = str(approved_by or "").strip()
        if not reviewer:
            return _ingestion_error(
                "schema_failed",
                "approved_by_required",
                "approved_by is required when accept=True.",
                ingestion_id=normalized_ingestion_id,
            )

        packets_result = self._review_packets_for_run(record, review_packets=review_packets)
        if packets_result.get("status") != "ok":
            error = dict(packets_result.get("error") or {})
            return _ingestion_error(
                "partial",
                str(error.get("code") or "document_review_failed"),
                str(error.get("message") or "document review failed"),
                ingestion_id=normalized_ingestion_id,
                category=str(error.get("category") or "document_review"),
                details=packets_result,
            )
        packets = list(packets_result["review_packets"])

        artifacts = _merge_artifacts(list(record.get("artifacts") or []))
        document_id = str(record.get("document_id") or "")
        write_performed_this_run = False
        skipped_window_count = 0
        for window_index, packet in enumerate(packets):
            digest = _window_digest(packet)
            existing_windows = {
                str(window.get("window_digest") or ""): window
                for window in list(record.get("windows") or [])
                if isinstance(window, dict)
                and str(window.get("window_digest") or "").strip()
                and window.get("status") == "stored"
            }
            if digest in existing_windows:
                skipped_window_count += 1
                continue

            prepared = self.runtime.prepare_document_artifact_store(packet)
            if prepared.get("status") != "prepared":
                return self._checkpoint_error(
                    record,
                    ingestion_id=normalized_ingestion_id,
                    document_id=document_id,
                    artifacts=artifacts,
                    write_performed=write_performed_this_run,
                    code="artifact_prepare_failed",
                    message="document artifact preparation failed.",
                    details=prepared,
                )
            stored = self.runtime.store_document_artifact(
                prepared["prepared_transaction_id"],
                accept=True,
                review_packet=packet,
                ingestion_id=normalized_ingestion_id,
                window_index=window_index,
                project=record.get("project"),
                domain=record.get("domain"),
            )
            if stored.get("status") != "ok":
                return self._checkpoint_error(
                    record,
                    ingestion_id=normalized_ingestion_id,
                    document_id=document_id,
                    artifacts=artifacts,
                    write_performed=write_performed_this_run,
                    code="artifact_store_failed",
                    message="document artifact storage failed.",
                    details=stored,
                )
            write_performed_this_run = write_performed_this_run or bool(stored.get("write_performed"))
            artifact = stored.get("artifact")
            if isinstance(artifact, dict):
                artifacts = _merge_artifacts([*artifacts, artifact])
                document_id = str(artifact.get("document_id") or document_id)
            checkpoint_error = self._checkpoint_successful_window(
                record,
                ingestion_id=normalized_ingestion_id,
                document_id=document_id,
                artifacts=artifacts,
                window_index=window_index,
                packet=packet,
                artifact=artifact if isinstance(artifact, dict) else None,
                write_performed=write_performed_this_run,
            )
            if checkpoint_error is not None:
                return checkpoint_error

        _refresh_document_catalog(
            self.ledger,
            document_id,
            project=record.get("project"),
            domain=record.get("domain"),
        )
        try:
            self.runtime.retrieval.upsert_chunk_records(
                document_id,
                _chunk_records_for_retrieval(self.ledger, document_id, record=record),
            )
        except Exception as exc:
            return self._checkpoint_retrieval_index_error(
                record,
                ingestion_id=normalized_ingestion_id,
                document_id=document_id,
                artifacts=artifacts,
                write_performed=write_performed_this_run,
                exc=exc,
            )
        chunks = _chunks_for_document(self.ledger, document_id)
        proposed_structural_edges = _structural_edges(
            normalized_ingestion_id,
            document_id,
            dict(record.get("source") or {}),
            chunks,
            reviewer,
        )
        structural_edges, missing_edges = _existing_or_new_edges(self.ledger, proposed_structural_edges)
        existing_graph_edge_ids = [
            str(edge_id)
            for edge_id in list(record.get("graph_edges_written") or [])
            if str(edge_id or "").strip()
        ]
        graph_edge_ids = [edge["edge_id"] for edge in structural_edges] or existing_graph_edge_ids
        if missing_edges:
            self.runtime.graph.import_edges(missing_edges)
        readiness = _readiness_from_records(self.ledger, document_id=document_id)
        readiness["structural_graph_covered"] = _structural_graph_covered(self.ledger, document_id, chunks)
        effective_coverage_policy = _choice(
            coverage_policy or str(record.get("coverage_policy") or "auto_local"),
            COVERAGE_POLICIES,
            "coverage_policy",
        )
        effective_coverage_options = {
            **(record.get("coverage_options") if isinstance(record.get("coverage_options"), dict) else {}),
            **dict(coverage_options or {}),
        }
        coverage_pass = record.get("coverage_pass") if isinstance(record.get("coverage_pass"), dict) else None
        effective_visual_preview = visual_preview
        if _should_run_coverage_pass(effective_coverage_policy, packets, visual_preview):
            try:
                coverage_pass = self.runtime.prepare_document_coverage_pass(
                    ingestion_record={
                        **record,
                        "ingestion_id": normalized_ingestion_id,
                        "document_id": document_id,
                        "artifacts": artifacts,
                        "readiness": readiness,
                    },
                    review_packets=packets,
                    coverage_policy=effective_coverage_policy,
                    coverage_options=effective_coverage_options,
                )
            except Exception as exc:
                failure_record = {
                    **record,
                    "graph_edges_written": graph_edge_ids,
                    "coverage_policy": effective_coverage_policy,
                    "coverage_options": effective_coverage_options,
                    "readiness": readiness,
                }
                return self._checkpoint_error(
                    failure_record,
                    ingestion_id=normalized_ingestion_id,
                    document_id=document_id,
                    artifacts=artifacts,
                    write_performed=write_performed_this_run,
                    progress_exists=_has_ingestion_progress(
                        failure_record,
                        document_id=document_id,
                        artifacts=artifacts,
                    ),
                    graph_write_performed=bool(missing_edges),
                    code="document_coverage_pass_failed",
                    message="document coverage pass failed after ingestion progress was stored.",
                    details={
                        "exception_type": type(exc).__name__,
                        "message": str(exc),
                    },
                    category="document_coverage",
                )
            if visual_preview is None and isinstance(coverage_pass.get("visual_preview"), dict):
                effective_visual_preview = coverage_pass["visual_preview"]
            readiness = _readiness_with_coverage_pass(readiness, coverage_pass)
        understanding_packet = record.get("understanding_packet") if isinstance(record.get("understanding_packet"), dict) else None
        promotion_transaction = (
            record.get("document_promotion_transaction")
            if isinstance(record.get("document_promotion_transaction"), dict)
            else None
        )
        semantic_graph_edges_written = [
            str(edge_id)
            for edge_id in list(record.get("semantic_graph_edges_written") or [])
            if _active_semantic_promotion_edge_id(self.ledger, edge_id)
        ]
        existing_semantic_edge_ids = set(semantic_graph_edges_written)
        semantic_graph_write_performed = False
        if understanding_analysis:
            document_record = _document_record_for_ingestion(self.ledger, document_id)
            understanding_packet = prepare_document_understanding_packet(
                document_record=document_record,
                analysis=understanding_analysis,
                chunk_refs=_analysis_chunk_refs(understanding_analysis, chunks),
                visual_artifacts=_visual_artifacts_from_preview(effective_visual_preview),
                created_by=reviewer,
            )
            document_draft = understanding_packet.get("document_draft")
            if isinstance(document_draft, dict):
                edge_indexes = list(range(len(document_draft.get("proposed_edges") or [])))
                if edge_indexes:
                    promotion_transaction = prepare_document_promotion_transaction(
                        document_draft=document_draft,
                        selected_memory_indexes=[],
                        selected_edge_indexes=edge_indexes,
                        approved_by=reviewer,
                    )
                    (
                        existing_promoted_edge_ids,
                        missing_operation_indexes,
                    ) = _existing_or_missing_semantic_promotion_edges(
                        self.ledger,
                        promotion_transaction,
                    )
                    if missing_operation_indexes:
                        promotion_result = self.runtime.apply_document_promotion_transaction(
                            promotion_transaction,
                            accept=True,
                            approved_by=reviewer,
                            selected_operation_indexes=missing_operation_indexes,
                        )
                        if promotion_result.get("status") != "ok" or promotion_result.get("error"):
                            failure_record = {
                                **record,
                                "graph_edges_written": graph_edge_ids,
                                "understanding_packet": understanding_packet,
                                "document_promotion_transaction": promotion_transaction,
                                "semantic_graph_edges_written": semantic_graph_edges_written,
                                "readiness": readiness,
                            }
                            return self._checkpoint_error(
                                failure_record,
                                ingestion_id=normalized_ingestion_id,
                                document_id=document_id,
                                artifacts=artifacts,
                                write_performed=write_performed_this_run,
                                progress_exists=_has_ingestion_progress(
                                    failure_record,
                                    document_id=document_id,
                                    artifacts=artifacts,
                                ),
                                graph_write_performed=bool(missing_edges),
                                code="semantic_promotion_failed",
                                message="document semantic graph promotion failed.",
                                details=promotion_result,
                            )
                    else:
                        promotion_result = {
                            "status": "ok",
                            "graph_edges_written": existing_promoted_edge_ids,
                            "write_performed": False,
                            "active_memory_write_performed": False,
                            "graph_write_performed": False,
                            "idempotent_replay": True,
                            "error": None,
                            "errors": [],
                        }
                    reported_promoted_edge_ids = _merge_ids(
                        [
                            *existing_promoted_edge_ids,
                            *list(promotion_result.get("graph_edges_written") or []),
                        ]
                    )
                    promoted_edge_ids = _active_semantic_promotion_edge_ids(
                        self.ledger,
                        reported_promoted_edge_ids,
                    )
                    semantic_graph_write_performed = bool(
                        (
                            promotion_result.get("graph_write_performed")
                            and not promotion_result.get("idempotent_replay")
                            and promoted_edge_ids
                        )
                        or any(edge_id not in existing_semantic_edge_ids for edge_id in promoted_edge_ids)
                    )
                    semantic_graph_edges_written = _merge_ids(
                        [*semantic_graph_edges_written, *promoted_edge_ids]
                    )
        readiness["semantic_graph_covered"] = bool(semantic_graph_edges_written)
        idempotent_replay = (
            bool(packets)
            and skipped_window_count == len(packets)
            and not write_performed_this_run
            and not missing_edges
            and not semantic_graph_write_performed
        )
        updated = {
            **record,
            "status": "partial",
            "document_id": document_id,
            "artifacts": artifacts,
            "graph_edges_written": graph_edge_ids,
            "coverage_policy": effective_coverage_policy,
            "coverage_options": effective_coverage_options,
            "coverage_pass": _compact_coverage_pass(coverage_pass),
            "visual_preview": _compact_visual_preview(effective_visual_preview),
            "understanding_packet": understanding_packet,
            "document_promotion_transaction": promotion_transaction,
            "semantic_graph_edges_written": semantic_graph_edges_written,
            "readiness": readiness,
            "updated_at": now_iso(),
        }
        upsert_record(self.ledger, "jobs", normalized_ingestion_id, updated)
        inspected = self.inspect_document_ingestion(ingestion_id=normalized_ingestion_id)
        return {
            **inspected,
            "coverage_pass": coverage_pass,
            "visual_preview": effective_visual_preview,
            "write_performed": write_performed_this_run,
            "idempotent_replay": idempotent_replay,
            "active_memory_write_performed": False,
            "graph_write_performed": bool(missing_edges) or semantic_graph_write_performed,
        }

    def _checkpoint_successful_window(
        self,
        record: dict[str, Any],
        *,
        ingestion_id: str,
        document_id: str,
        artifacts: list[dict[str, Any]],
        window_index: int,
        packet: dict[str, Any],
        artifact: dict[str, Any] | None,
        write_performed: bool,
    ) -> dict[str, Any] | None:
        readiness = _readiness_from_records(self.ledger, document_id=document_id) if document_id else _empty_readiness()
        updated = {
            **record,
            "status": "partial",
            "document_id": document_id or record.get("document_id"),
            "artifacts": artifacts,
            "readiness": readiness,
            "windows": _merge_windows(
                list(record.get("windows") or []),
                _window_checkpoint(
                    window_index=window_index,
                    packet=packet,
                    artifact=artifact,
                    document_id=document_id,
                ),
            ),
            "updated_at": now_iso(),
        }
        upsert_record(self.ledger, "jobs", ingestion_id, updated)
        record.clear()
        record.update(updated)
        if document_id:
            _refresh_document_catalog(
                self.ledger,
                document_id,
                project=updated.get("project"),
                domain=updated.get("domain"),
            )
            try:
                self.runtime.retrieval.upsert_chunk_records(
                    document_id,
                    _chunk_records_for_retrieval(self.ledger, document_id, record=record),
                )
            except Exception as exc:
                return self._checkpoint_retrieval_index_error(
                    record,
                    ingestion_id=ingestion_id,
                    document_id=document_id,
                    artifacts=artifacts,
                    write_performed=write_performed,
                    exc=exc,
                )
        return None

    def _checkpoint_retrieval_index_error(
        self,
        record: dict[str, Any],
        *,
        ingestion_id: str,
        document_id: str,
        artifacts: list[dict[str, Any]],
        write_performed: bool,
        exc: Exception,
    ) -> dict[str, Any]:
        readiness = dict(record.get("readiness") or {})
        readiness["searchable"] = False
        failed_record = {**record, "readiness": readiness}
        return self._checkpoint_error(
            failed_record,
            ingestion_id=ingestion_id,
            document_id=document_id,
            artifacts=artifacts,
            write_performed=write_performed,
            progress_exists=True,
            index_retrieval=False,
            code="retrieval_index_checkpoint_failed",
            message="document ingestion progress was stored, but retrieval indexing failed.",
            details={
                "exception_type": type(exc).__name__,
                "message": str(exc),
            },
            category="retrieval",
        )

    def _checkpoint_error(
        self,
        record: dict[str, Any],
        *,
        ingestion_id: str,
        document_id: str,
        artifacts: list[dict[str, Any]],
        write_performed: bool,
        code: str,
        message: str,
        details: dict[str, Any],
        progress_exists: bool = False,
        graph_write_performed: bool = False,
        index_retrieval: bool = True,
        category: str = "validation",
    ) -> dict[str, Any]:
        error = {"code": code, "category": category, "message": message, "details": details}
        if index_retrieval and write_performed and document_id:
            try:
                self.runtime.retrieval.upsert_chunk_records(
                    document_id,
                    _chunk_records_for_retrieval(self.ledger, document_id, record=record),
                )
            except Exception as exc:
                error = _with_checkpoint_retrieval_index_error(error, exc)
        base_readiness = dict(record.get("readiness") or {})
        readiness = _readiness_from_records(self.ledger, document_id=document_id) if document_id else _empty_readiness()
        readiness.update(base_readiness)
        updated = {
            **record,
            "status": "partial" if write_performed or progress_exists else "schema_failed",
            "document_id": document_id or record.get("document_id"),
            "artifacts": artifacts,
            "readiness": readiness,
            "errors": [*list(record.get("errors") or []), error],
            "updated_at": now_iso(),
        }
        upsert_record(self.ledger, "jobs", ingestion_id, updated)
        inspected = self.inspect_document_ingestion(ingestion_id=ingestion_id)
        return {
            **inspected,
            "status": updated["status"],
            "error": error,
            "errors": updated["errors"],
            "write_performed": write_performed,
            "active_memory_write_performed": False,
            "graph_write_performed": graph_write_performed,
        }

    def resume_document_ingestion(self, **kwargs: Any) -> dict[str, Any]:
        return self.run_document_ingestion(**kwargs)

    def enqueue_document_ingestion_run(
        self,
        *,
        ingestion_id: str,
        accept: bool = False,
        approved_by: str | None = None,
        review_packets: list[dict[str, Any]] | None = None,
        understanding_analysis: dict[str, Any] | None = None,
        visual_preview: dict[str, Any] | None = None,
        coverage_policy: str | None = None,
        coverage_options: dict[str, Any] | None = None,
        resume: bool = False,
    ) -> dict[str, Any]:
        """Queue accepted document ingestion work for daemon-local background execution."""
        normalized_ingestion_id = str(ingestion_id or "").strip()
        record = _find_ingestion(self.ledger, ingestion_id=normalized_ingestion_id, document_id=None)
        if record is None:
            return _ingestion_error(
                "not_found",
                "not_found",
                "document ingestion was not found",
                ingestion_id=normalized_ingestion_id,
                category="not_found",
            )
        if not accept:
            return _ingestion_error(
                "policy_denied",
                "accept_required",
                "run_document_ingestion requires accept=True.",
                ingestion_id=normalized_ingestion_id,
                category="policy",
            )
        reviewer = str(approved_by or "").strip()
        if not reviewer:
            return _ingestion_error(
                "schema_failed",
                "approved_by_required",
                "approved_by is required when accept=True.",
                ingestion_id=normalized_ingestion_id,
            )
        active_job = _active_execution_job(self.ledger, normalized_ingestion_id)
        if active_job is not None:
            return self._queued_response(
                record,
                job=active_job,
                queued=active_job.get("status") == "queued",
            )
        payload = {
            "ingestion_id": normalized_ingestion_id,
            "accept": True,
            "approved_by": reviewer,
            "review_packets": list(review_packets or []),
            "understanding_analysis": understanding_analysis,
            "visual_preview": visual_preview,
            "coverage_policy": coverage_policy,
            "coverage_options": dict(coverage_options or {}),
            "resume": bool(resume),
        }
        action = "resume" if resume else "run"
        job = self.runtime.job_runner.enqueue(
            DOCUMENT_INGESTION_EXECUTION_JOB_KIND,
            payload,
            idempotency_key=f"document_ingestion:{action}:{normalized_ingestion_id}:{hash_payload(payload)}",
            max_attempts=3,
        )
        return self._queued_response(record, job=job, queued=job.get("status") == "queued")

    def run_queued_document_ingestion(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 300,
    ) -> dict[str, Any]:
        """Acquire and process one queued document ingestion execution job."""
        job = self.runtime.job_runner.acquire(
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            job_kind=DOCUMENT_INGESTION_EXECUTION_JOB_KIND,
        )
        if job is None:
            return {
                "status": "idle",
                "worker_id": worker_id,
                "processed": False,
                "error": None,
            }
        payload = dict(job.get("payload") or {})
        ingestion_id = str(payload.get("ingestion_id") or "")
        self._mark_execution_running(ingestion_id, job=job)
        try:
            run_payload = {key: value for key, value in payload.items() if key != "resume"}
            result = self.run_document_ingestion(**run_payload)
        except Exception as exc:
            failed = self.runtime.job_runner.fail(job["job_id"], worker_id=worker_id, error=str(exc))
            self._mark_execution_failed(ingestion_id, job=failed, exc=exc)
            return {
                "status": failed.get("status"),
                "worker_id": worker_id,
                "processed": False,
                "background_job": _execution_job_summary(failed),
                "error": {
                    "code": "document_ingestion_worker_failed",
                    "category": "runtime",
                    "message": str(exc),
                    "exception_type": type(exc).__name__,
                },
            }
        if _worker_result_failed(result):
            error = result.get("error") if isinstance(result.get("error"), dict) else {}
            failed = self.runtime.job_runner.fail(
                job["job_id"],
                worker_id=worker_id,
                error=str(error.get("message") or result.get("status") or "document ingestion failed"),
            )
            if failed.get("status") == "dead_lettered":
                self._mark_execution_dead_lettered(ingestion_id, job=failed, result=result)
            else:
                self._mark_execution_retry(ingestion_id, job=failed, result=result)
            return {
                **result,
                "status": failed.get("status"),
                "worker_id": worker_id,
                "processed": False,
                "background_job": _execution_job_summary(failed),
            }
        completed = self.runtime.job_runner.complete(
            job["job_id"],
            worker_id=worker_id,
            result=_compact_worker_result(result),
        )
        self._mark_execution_completed(ingestion_id, job=completed)
        return {
            **result,
            "worker_id": worker_id,
            "processed": True,
            "background_job": _execution_job_summary(completed),
        }

    def _queued_response(
        self,
        record: dict[str, Any],
        *,
        job: dict[str, Any],
        queued: bool,
    ) -> dict[str, Any]:
        payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
        ingestion_id = str(record.get("ingestion_id") or payload.get("ingestion_id") or "")
        current = _find_ingestion(self.ledger, ingestion_id=ingestion_id, document_id=None) or record
        job_status = str(job.get("status") or "")
        status = "running" if job_status == "running" else "queued" if job_status == "queued" else current.get("status")
        queued_record = {
            **current,
            "status": status,
            "execution_job_id": job["job_id"],
            "execution_status": job.get("status"),
            "queued_at": current.get("queued_at") or now_iso(),
            "updated_at": now_iso(),
        }
        upsert_record(self.ledger, "jobs", ingestion_id, queued_record)
        inspected = self.inspect_document_ingestion(ingestion_id=ingestion_id)
        return {
            **inspected,
            "status": status,
            "queued": bool(queued),
            "background_job": _execution_job_summary(job),
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "next_action": {"tool": "inspect_document_ingestion", "ingestion_id": ingestion_id},
        }

    def inspect_document_ingestion(
        self,
        *,
        ingestion_id: str | None = None,
        document_id: str | None = None,
    ) -> dict[str, Any]:
        record = _find_ingestion(self.ledger, ingestion_id=ingestion_id, document_id=document_id)
        if record is None:
            return {
                "schema_version": DOCUMENT_INGESTION_SCHEMA_VERSION,
                "status": "not_found",
                "ingestion_id": ingestion_id,
                "document_id": document_id,
                "readiness": _empty_readiness(),
                "chunk_count": 0,
                "indexed_count": 0,
                "terminal": True,
                "resumable": False,
                "write_performed": False,
                "active_memory_write_performed": False,
                "graph_write_performed": False,
                "error": {
                    "code": "not_found",
                    "category": "not_found",
                    "message": "document ingestion was not found",
                },
            }
        chunk_count = len(_chunks_for_document(self.ledger, str(record.get("document_id") or "")))
        readiness = dict(record.get("readiness") or _empty_readiness())
        completion_progress = _completion_progress_for_document(
            self.ledger,
            str(record.get("document_id") or ""),
        )
        execution_job = _latest_execution_job(self.ledger, str(record.get("ingestion_id") or ""))
        progress = _ingestion_progress(record)
        stage_report = build_document_ingestion_stage_report(self.ledger, record)
        return {
            **record,
            "readiness": readiness,
            "chunk_count": chunk_count,
            "indexed_count": chunk_count if readiness.get("searchable") else 0,
            "terminal": record.get("status") in {"failed", "cancelled", "completed"},
            "resumable": record.get("status") in {"planned", "partial", "running"},
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "completion_progress": completion_progress,
            "progress": progress,
            "background_job": _execution_job_summary(execution_job),
            "retry": _execution_retry_summary(execution_job),
            "dead_letter": _execution_dead_letter_summary(execution_job),
            "last_successful_checkpoint": progress.get("last_successful_checkpoint"),
            "stage_report": stage_report,
            "retryable_stages": stage_report["retryable_stages"],
            "next_action": _next_action(record),
            "error": None if not record.get("errors") else record["errors"][-1],
        }

    def _mark_execution_running(self, ingestion_id: str, *, job: dict[str, Any]) -> None:
        record = _find_ingestion(self.ledger, ingestion_id=ingestion_id, document_id=None)
        if record is None:
            return
        updated = {
            **record,
            "status": "running",
            "execution_job_id": job.get("job_id"),
            "execution_status": job.get("status"),
            "lease_owner": job.get("lease_owner"),
            "lease_expires_at": job.get("lease_expires_at"),
            "updated_at": now_iso(),
        }
        upsert_record(self.ledger, "jobs", ingestion_id, updated)

    def _mark_execution_completed(self, ingestion_id: str, *, job: dict[str, Any]) -> None:
        record = _find_ingestion(self.ledger, ingestion_id=ingestion_id, document_id=None)
        if record is None:
            return
        updated = {
            **record,
            "execution_job_id": job.get("job_id"),
            "execution_status": job.get("status"),
            "lease_owner": None,
            "lease_expires_at": None,
            "last_execution_completed_at": job.get("updated_at") or now_iso(),
            "updated_at": now_iso(),
        }
        upsert_record(self.ledger, "jobs", ingestion_id, updated)

    def _mark_execution_retry(
        self,
        ingestion_id: str,
        *,
        job: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        record = _find_ingestion(self.ledger, ingestion_id=ingestion_id, document_id=None)
        if record is None:
            return
        errors = list(record.get("errors") or [])
        if isinstance(result.get("error"), dict):
            errors.append(result["error"])
        updated = {
            **record,
            "status": "queued",
            "execution_job_id": job.get("job_id"),
            "execution_status": job.get("status"),
            "lease_owner": None,
            "lease_expires_at": None,
            "errors": errors,
            "updated_at": now_iso(),
        }
        upsert_record(self.ledger, "jobs", ingestion_id, updated)

    def _mark_execution_failed(self, ingestion_id: str, *, job: dict[str, Any], exc: Exception) -> None:
        record = _find_ingestion(self.ledger, ingestion_id=ingestion_id, document_id=None)
        if record is None:
            return
        status = "failed" if job.get("status") == "dead_lettered" else "queued"
        error = {
            "code": "document_ingestion_worker_failed",
            "category": "runtime",
            "message": str(exc),
            "exception_type": type(exc).__name__,
        }
        updated = {
            **record,
            "status": status,
            "execution_job_id": job.get("job_id"),
            "execution_status": job.get("status"),
            "lease_owner": None,
            "lease_expires_at": None,
            "errors": [*list(record.get("errors") or []), error],
            "updated_at": now_iso(),
        }
        upsert_record(self.ledger, "jobs", ingestion_id, updated)

    def _mark_execution_dead_lettered(
        self,
        ingestion_id: str,
        *,
        job: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        record = _find_ingestion(self.ledger, ingestion_id=ingestion_id, document_id=None)
        if record is None:
            return
        errors = list(record.get("errors") or [])
        if isinstance(result.get("error"), dict):
            errors.append(result["error"])
        updated = {
            **record,
            "status": "failed",
            "execution_job_id": job.get("job_id"),
            "execution_status": job.get("status"),
            "lease_owner": None,
            "lease_expires_at": None,
            "errors": errors,
            "updated_at": now_iso(),
        }
        upsert_record(self.ledger, "jobs", ingestion_id, updated)

    def _review_packets_for_run(
        self,
        record: dict[str, Any],
        *,
        review_packets: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        supplied = [packet for packet in review_packets or [] if isinstance(packet, dict)]
        if supplied:
            return {"status": "ok", "review_packets": supplied, "source": "supplied"}

        document_id = str(record.get("document_id") or "").strip()
        if document_id:
            staged = load_staged_document_evidence(
                self.ledger,
                self.runtime.content_store,
                document_id,
            )
            if staged.get("complete"):
                return {
                    "status": "ok",
                    "review_packets": list(staged.get("review_packets") or []),
                    "source": "staged_document_artifacts",
                    "staged_evidence": staged,
                }

        source = dict(record.get("source") or {})
        source_path = str(source.get("path") or "").strip()
        if not source_path:
            return _packet_collection_error("source_path_missing", "planned ingestion is missing source.path")

        packets: list[dict[str, Any]] = []
        resume_token: str | None = None
        max_pages = max(1, int(record.get("page_window_size") or 25))
        source_type = str(source.get("source_type") or "pdf")
        while True:
            packet = self.document_intake_reviewer(
                source_path=source_path,
                source_type=source_type,
                max_pages=max_pages,
                resume_token=resume_token,
                require_visual_coverage=True,
                require_table_coverage=True,
                require_ocr_coverage=True,
            )
            if packet.get("status") in {"schema_failed", "unavailable"}:
                return _packet_collection_error("document_review_failed", "document intake review failed", details=packet)
            packets.append(packet)
            resume = dict((packet.get("disassembly") or {}).get("resume") or {})
            if not resume.get("has_more"):
                break
            next_token = str(resume.get("resume_token") or "").strip()
            if not next_token or next_token == str(resume_token or ""):
                return _packet_collection_error(
                    "resume_token_missing",
                    "document review reported more pages without a new resume token",
                    details=packet,
                )
            resume_token = next_token

        return {"status": "ok", "review_packets": packets, "source": "local_pdf_review"}


def _should_run_coverage_pass(
    coverage_policy: str,
    packets: list[dict[str, Any]],
    visual_preview: dict[str, Any] | None,
) -> bool:
    if coverage_policy in {"manual", "external_bundle"}:
        return False
    if isinstance(visual_preview, dict):
        return False
    return any(
        isinstance(packet.get("extraction_request"), dict)
        and bool((packet["extraction_request"].get("image_refs") or []))
        for packet in packets
    )


def _latest_execution_job(ledger: MemoryOSLedger, ingestion_id: str) -> dict[str, Any] | None:
    if not ingestion_id:
        return None
    matches = []
    for job in list_records(ledger, "jobs"):
        if job.get("job_kind") != DOCUMENT_INGESTION_EXECUTION_JOB_KIND:
            continue
        payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
        if str(payload.get("ingestion_id") or "") == ingestion_id:
            matches.append(job)
    if not matches:
        return None
    matches.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""))
    return matches[-1]


def _active_execution_job(ledger: MemoryOSLedger, ingestion_id: str) -> dict[str, Any] | None:
    if not ingestion_id:
        return None
    active = []
    for job in list_records(ledger, "jobs"):
        if job.get("job_kind") != DOCUMENT_INGESTION_EXECUTION_JOB_KIND:
            continue
        if job.get("status") not in {"queued", "running"}:
            continue
        payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
        if str(payload.get("ingestion_id") or "") == ingestion_id:
            active.append(job)
    if not active:
        return None
    active.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""))
    return active[-1]


def _execution_job_summary(job: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(job, dict):
        return None
    return {
        "job_id": job.get("job_id"),
        "job_kind": job.get("job_kind"),
        "status": job.get("status"),
        "attempt": int(job.get("attempt") or 0),
        "max_attempts": int(job.get("max_attempts") or 1),
        "lease_owner": job.get("lease_owner"),
        "lease_expires_at": job.get("lease_expires_at"),
        "heartbeat_at": job.get("heartbeat_at"),
        "cancel_requested": bool(job.get("cancel_requested")),
        "dead_lettered_at": job.get("dead_lettered_at"),
        "last_error": job.get("last_error"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
    }


def _execution_retry_summary(job: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(job, dict):
        return {"attempt": 0, "max_attempts": 0, "remaining_attempts": 0}
    attempt = int(job.get("attempt") or 0)
    max_attempts = max(int(job.get("max_attempts") or 1), 1)
    return {
        "attempt": attempt,
        "max_attempts": max_attempts,
        "remaining_attempts": max(max_attempts - attempt, 0),
        "last_error": job.get("last_error"),
    }


def _execution_dead_letter_summary(job: dict[str, Any] | None) -> dict[str, Any]:
    dead = isinstance(job, dict) and job.get("status") == "dead_lettered"
    return {
        "dead_lettered": bool(dead),
        "dead_lettered_at": job.get("dead_lettered_at") if isinstance(job, dict) else None,
        "last_error": job.get("last_error") if isinstance(job, dict) else None,
    }


def _ingestion_progress(record: dict[str, Any]) -> dict[str, Any]:
    windows = [window for window in list(record.get("windows") or []) if isinstance(window, dict)]
    stored = [window for window in windows if window.get("status") == "stored"]
    last = None
    if stored:
        last = sorted(stored, key=lambda item: str(item.get("updated_at") or ""))[-1]
    return {
        "window_count": len(windows),
        "stored_window_count": len(stored),
        "last_successful_checkpoint": (
            {
                "window_id": last.get("window_id"),
                "window_index": last.get("window_index"),
                "page_range": last.get("page_range"),
                "artifact_id": last.get("artifact_id"),
                "updated_at": last.get("updated_at"),
            }
            if isinstance(last, dict)
            else None
        ),
    }


def _compact_worker_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": result.get("status"),
        "ingestion_id": result.get("ingestion_id"),
        "document_id": result.get("document_id"),
        "readiness": result.get("readiness"),
        "chunk_count": result.get("chunk_count"),
        "indexed_count": result.get("indexed_count"),
        "write_performed": bool(result.get("write_performed")),
        "graph_write_performed": bool(result.get("graph_write_performed")),
        "error": result.get("error"),
    }


def _worker_result_failed(result: dict[str, Any]) -> bool:
    status = str(result.get("status") or "")
    if status in {"schema_failed", "policy_denied", "not_found", "failed", "unavailable"}:
        return True
    return bool(result.get("error")) and status not in {"partial", "completed", "ok"}


def _readiness_with_coverage_pass(
    readiness: dict[str, bool],
    coverage_pass: dict[str, Any] | None,
) -> dict[str, bool]:
    if not isinstance(coverage_pass, dict):
        return readiness
    visual_preview = coverage_pass.get("visual_preview")
    if not isinstance(visual_preview, dict):
        return readiness
    visual_coverage = visual_preview.get("visual_coverage")
    if not isinstance(visual_coverage, dict):
        return readiness
    missing = [
        item
        for item in visual_coverage.get("missing_capabilities") or []
        if isinstance(item, dict)
    ]
    required = _required_capability_lanes(coverage_pass.get("visual_request"))
    updated = dict(readiness)
    if "visual" in required:
        updated["visual_covered"] = not _lane_missing(missing, "visual")
    if "ocr" in required:
        updated["ocr_covered"] = not _lane_missing(missing, "ocr")
    if "table" in required:
        updated["table_covered"] = not _lane_missing(missing, "table")
    updated["usable"] = bool(readiness.get("usable"))
    return updated


def _required_capability_lanes(visual_request: Any) -> set[str]:
    if not isinstance(visual_request, dict):
        return set()
    capabilities: set[str] = set()
    for capability in visual_request.get("requested_capabilities") or []:
        capabilities.add(str(capability or "").strip())
    for ref in visual_request.get("image_refs") or []:
        if isinstance(ref, dict):
            capabilities.update(str(item or "").strip() for item in ref.get("requested_capabilities") or [])
    lanes: set[str] = set()
    for capability in capabilities:
        if capability == "ocr_text":
            lanes.add("ocr")
        elif capability == "table_structure":
            lanes.add("table")
        elif capability:
            lanes.add("visual")
    return lanes


def _lane_missing(missing_capabilities: list[dict[str, Any]], lane: str) -> bool:
    for missing in missing_capabilities:
        capability = str(missing.get("capability") or "").strip()
        if lane == "ocr" and capability == "ocr_text":
            return True
        if lane == "table" and capability == "table_structure":
            return True
        if lane == "visual" and capability not in {"ocr_text", "table_structure"}:
            return True
    return False


def _compact_coverage_pass(coverage_pass: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(coverage_pass, dict):
        return None
    workbench = coverage_pass.get("workbench") if isinstance(coverage_pass.get("workbench"), dict) else {}
    visual_preview = coverage_pass.get("visual_preview") if isinstance(coverage_pass.get("visual_preview"), dict) else {}
    return {
        "schema_version": coverage_pass.get("schema_version"),
        "record_type": coverage_pass.get("record_type"),
        "event_id": coverage_pass.get("event_id"),
        "status": coverage_pass.get("status"),
        "coverage_policy": coverage_pass.get("coverage_policy"),
        "visual_request": coverage_pass.get("visual_request"),
        "receipts": dict(workbench.get("receipts") or {}),
        "visual_coverage": visual_preview.get("visual_coverage"),
        "blocking_issues": list(coverage_pass.get("blocking_issues") or []),
        "next_action": coverage_pass.get("next_action"),
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
    }


def _compact_visual_preview(visual_preview: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(visual_preview, dict):
        return None
    return {
        "schema_version": visual_preview.get("schema_version"),
        "status": visual_preview.get("status"),
        "document_id": visual_preview.get("document_id"),
        "visual_coverage": visual_preview.get("visual_coverage"),
        "receipt": visual_preview.get("receipt"),
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
    }


def _packet_collection_error(code: str, message: str, *, details: dict[str, Any] | None = None) -> dict[str, Any]:
    error = {"code": code, "category": "document_review", "message": message}
    if details is not None:
        error["details"] = details
    return {"status": "partial", "review_packets": [], "error": error}


def _has_ingestion_progress(
    record: dict[str, Any],
    *,
    document_id: str,
    artifacts: list[dict[str, Any]],
) -> bool:
    if str(document_id or record.get("document_id") or "").strip():
        return True
    if artifacts or list(record.get("artifacts") or []):
        return True
    if list(record.get("windows") or []):
        return True
    if list(record.get("graph_edges_written") or []):
        return True
    if list(record.get("semantic_graph_edges_written") or []):
        return True
    readiness = record.get("readiness") if isinstance(record.get("readiness"), dict) else {}
    return any(bool(readiness.get(key)) for key in ("searchable", "structural_graph_covered", "semantic_graph_covered"))


def _chunks_for_document(ledger: MemoryOSLedger, document_id: str) -> list[dict[str, Any]]:
    return [
        chunk
        for chunk in list_records(ledger, "chunks")
        if str(chunk.get("document_id") or "") == document_id
    ]


def _completion_progress_for_document(ledger: MemoryOSLedger, document_id: str) -> dict[str, Any] | None:
    if not document_id:
        return None
    job_id = f"document_completion:{document_id}"
    job = read_record(ledger, "jobs", job_id)
    events = [
        event
        for event in list_records(ledger, "job_events")
        if str(event.get("job_id") or "") == job_id
    ]
    if not job and not events:
        return None
    return {
        "job": job,
        "events": events,
        "event_count": len(events),
        "latest_event_type": events[-1].get("event_type") if events else None,
    }


def _document_record_for_ingestion(ledger: MemoryOSLedger, document_id: str) -> dict[str, Any]:
    document = read_record(ledger, "documents", document_id)
    if not isinstance(document, dict):
        raise ValueError(f"document record not found: {document_id}")
    document = enrich_document_record(document)
    raw_document = document.get("document") if isinstance(document.get("document"), dict) else {}
    source_ref = document.get("source_ref") if isinstance(document.get("source_ref"), dict) else {}
    metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
    return {
        "document_id": document_id,
        "title": raw_document.get("title") or document.get("title") or document_id,
        "source_uri": source_ref.get("source_uri"),
        "source_type": raw_document.get("source_type") or source_ref.get("source_type") or "pdf",
        "media_type": raw_document.get("media_type") or source_ref.get("media_type") or "application/pdf",
        "content_hash": raw_document.get("content_hash") or source_ref.get("content_hash"),
        "metadata": {**metadata, "document_id": document_id, "document_catalog": document.get("document_catalog")},
    }


def _refresh_document_catalog(
    ledger: MemoryOSLedger,
    document_id: str,
    *,
    project: str | None = None,
    domain: str | None = None,
) -> dict[str, Any]:
    if not document_id:
        return {}
    document = read_record(ledger, "documents", document_id)
    if not isinstance(document, dict):
        return {}
    enriched = enrich_document_identity_metadata(document, project=project, domain=domain)
    if enriched != document:
        upsert_record(ledger, "documents", document_id, enriched)
    _refresh_document_chunk_catalog(
        ledger,
        document_id,
        enriched,
        project=project,
        domain=domain,
    )
    return enriched


def _refresh_document_chunk_catalog(
    ledger: MemoryOSLedger,
    document_id: str,
    document: dict[str, Any],
    *,
    project: str | None = None,
    domain: str | None = None,
) -> None:
    for chunk in _chunks_for_document(ledger, document_id):
        enriched_chunk = enrich_document_chunk_metadata(
            chunk,
            document,
            project=project,
            domain=domain,
        )
        if enriched_chunk != chunk:
            upsert_record(ledger, "chunks", str(enriched_chunk["chunk_record_id"]), enriched_chunk)


def _chunk_refs(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "document_id": chunk["document_id"],
            "chunk_id": chunk["chunk_id"],
            "chunk_record_id": chunk["chunk_record_id"],
        }
        for chunk in chunks
    ]


def _analysis_chunk_refs(
    analysis: dict[str, Any],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(analysis, dict):
        return []
    chunk_lookup = {}
    for chunk in _chunk_refs(chunks):
        chunk_lookup[_chunk_ref_signature(chunk)] = chunk
    refs: list[dict[str, Any]] = []
    for candidate in _iter_analysis_evidence_refs(analysis):
        if not isinstance(candidate, dict):
            continue
        signature = _chunk_ref_signature(candidate)
        if signature and signature in chunk_lookup:
            refs.append(chunk_lookup[signature])
            continue
        if _chunk_ref_signature(candidate):
            refs.append(dict(candidate))
    return _dedupe_chunk_refs(refs)


def _iter_analysis_evidence_refs(value: Any):
    if isinstance(value, dict):
        evidence_refs = value.get("evidence_refs")
        if isinstance(evidence_refs, list):
            yield from evidence_refs
        chunk_ref = value.get("chunk_ref")
        if isinstance(chunk_ref, dict):
            yield chunk_ref
        for child in value.values():
            yield from _iter_analysis_evidence_refs(child)
        return
    if isinstance(value, list):
        for item in value:
            yield from _iter_analysis_evidence_refs(item)


def _chunk_ref_signature(ref: dict[str, Any]) -> tuple[str, str] | None:
    key = str(ref.get("key") or "").strip()
    if key:
        return ("key", key)
    record_id = str(ref.get("chunk_record_id") or "").strip()
    if record_id:
        return ("chunk_record_id", record_id)
    if ref.get("chunk_id") is None:
        return None
    document_id = str(ref.get("document_id") or "").strip()
    return ("chunk_id", f"{document_id}:{ref['chunk_id']}")


def _dedupe_chunk_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for ref in refs:
        signature = _chunk_ref_signature(ref)
        if signature is None or signature in seen:
            continue
        seen.add(signature)
        deduped.append(ref)
    return deduped


def _visual_artifacts_from_preview(visual_preview: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(visual_preview, dict):
        return []
    return [
        item
        for item in visual_preview.get("visual_artifacts") or []
        if isinstance(item, dict)
    ]


def _structural_edges(
    ingestion_id: str,
    document_id: str,
    source: dict[str, Any],
    chunks: list[dict[str, Any]],
    approved_by: str,
) -> list[dict[str, Any]]:
    if not document_id:
        return []
    source_uri = str(source.get("source_uri") or source.get("path") or "").strip()
    source_sha256 = str(source.get("sha256") or source.get("content_hash") or "").strip()
    if not source_uri and not source_sha256:
        return []
    document_ref = {"kind": "document", "key": document_id, "document_id": document_id}
    source_ref = {
        "kind": "source",
        "key": source_uri or source_sha256 or None,
        "source_uri": source_uri or None,
        "sha256": source_sha256 or None,
    }
    edges = [
        _edge(
            ingestion_id=ingestion_id,
            from_ref=document_ref,
            edge_type="cites",
            to_ref=source_ref,
            evidence=f"Document ingestion {ingestion_id} linked document {document_id} to its source.",
            approved_by=approved_by,
        )
    ]
    for chunk in chunks:
        chunk_id = chunk.get("chunk_id")
        chunk_record_id = str(chunk.get("chunk_record_id") or "").strip()
        if chunk_id is None or not chunk_record_id:
            continue
        edges.append(
            _edge(
                ingestion_id=ingestion_id,
                from_ref=document_ref,
                edge_type="contains",
                to_ref={
                    "kind": "chunk",
                    "key": chunk_record_id,
                    "document_id": document_id,
                    "chunk_id": chunk_id,
                    "chunk_record_id": chunk_record_id,
                },
                evidence=(
                    f"Document ingestion {ingestion_id} materialized chunk "
                    f"{chunk_record_id} for document {document_id}."
                ),
                approved_by=approved_by,
            )
        )
    return edges


def _edge(
    *,
    ingestion_id: str,
    from_ref: dict[str, Any],
    edge_type: str,
    to_ref: dict[str, Any],
    evidence: str,
    approved_by: str,
) -> dict[str, Any]:
    timestamp = now_iso()
    edge = {
        "from_ref": dict(from_ref),
        "to_ref": dict(to_ref),
        "edge_type": edge_type,
        "confidence": 1.0,
        "evidence": evidence,
        "source": "document_ingestion.structural",
        "status": "active",
        "created_by": approved_by,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    edge["edge_id"] = stable_id(
        "edge",
        {
            "ingestion_id": ingestion_id,
            "from_ref": _edge_id_ref(edge["from_ref"]),
            "edge_type": edge["edge_type"],
            "to_ref": _edge_id_ref(edge["to_ref"]),
            "source": edge["source"],
        },
    )
    return edge


def _existing_or_new_edges(
    ledger: MemoryOSLedger,
    edges: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    resolved = []
    changed = []
    for edge in edges:
        existing = read_record(ledger, "graph_edges", str(edge.get("edge_id") or ""))
        if isinstance(existing, dict):
            enriched = _enrich_existing_edge_refs(existing, edge)
            resolved.append(enriched)
            if enriched != existing:
                changed.append(enriched)
            continue
        resolved.append(edge)
        changed.append(edge)
    return resolved, changed


def _existing_or_missing_semantic_promotion_edges(
    ledger: MemoryOSLedger,
    promotion_transaction: dict[str, Any],
) -> tuple[list[str], list[int]]:
    existing_by_signature = {
        signature: str(edge.get("edge_id") or "").strip()
        for edge in list_records(ledger, "graph_edges")
        for signature in [_semantic_edge_signature(edge)]
        if signature is not None
        and str(edge.get("edge_id") or "").strip()
        and _is_active_semantic_promotion_edge(edge)
    }
    existing_edge_ids: list[str] = []
    missing_operation_indexes: list[int] = []
    for operation_index, operation in enumerate(list(promotion_transaction.get("operations") or [])):
        if not isinstance(operation, dict) or operation.get("kind") != "graph_edge":
            missing_operation_indexes.append(operation_index)
            continue
        payload = operation.get("payload") if isinstance(operation.get("payload"), dict) else {}
        signature = _semantic_edge_signature(payload)
        if signature is not None and signature in existing_by_signature:
            existing_edge_ids.append(existing_by_signature[signature])
            continue
        missing_operation_indexes.append(operation_index)
    return _merge_ids(existing_edge_ids), missing_operation_indexes


def _active_semantic_promotion_edge_id(ledger: MemoryOSLedger, edge_id: Any) -> bool:
    normalized = str(edge_id or "").strip()
    if not normalized:
        return False
    edge = read_record(ledger, "graph_edges", normalized)
    return _is_active_semantic_promotion_edge(edge)


def _active_semantic_promotion_edge_ids(ledger: MemoryOSLedger, edge_ids: list[Any]) -> list[str]:
    return [
        normalized
        for edge_id in edge_ids
        if (normalized := str(edge_id or "").strip())
        and _active_semantic_promotion_edge_id(ledger, normalized)
    ]


def _is_active_semantic_promotion_edge(edge: Any) -> bool:
    return (
        isinstance(edge, dict)
        and str(edge.get("edge_id") or "").strip()
        and edge.get("status") == "active"
        and _semantic_edge_signature(edge) is not None
    )


def _semantic_edge_signature(edge: dict[str, Any]) -> str | None:
    if not isinstance(edge, dict):
        return None
    source = str(edge.get("source") or "document_intelligence").strip()
    if source != "document_intelligence" and not source.startswith("document_intelligence."):
        return None
    from_ref = edge.get("from_ref")
    to_ref = edge.get("to_ref")
    edge_type = str(edge.get("edge_type") or "").strip()
    evidence = str(edge.get("evidence") or "").strip()
    if not isinstance(from_ref, dict) or not isinstance(to_ref, dict) or not edge_type or not evidence:
        return None
    return stable_id(
        "semantic_edge",
        {
            "from_ref": from_ref,
            "to_ref": to_ref,
            "edge_type": edge_type,
            "evidence": evidence,
            "source": source,
        },
    )


def _merge_ids(values: list[Any]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        merged.append(normalized)
    return merged


def _structural_graph_covered(
    ledger: MemoryOSLedger,
    document_id: str,
    chunks: list[dict[str, Any]],
) -> bool:
    if not document_id or not chunks:
        return False
    edges = [
        edge
        for edge in list_records(ledger, "graph_edges")
        if isinstance(edge, dict)
        and edge.get("source") == "document_ingestion.structural"
        and edge.get("status") == "active"
        and _ref_matches_document(edge.get("from_ref"), document_id)
    ]
    has_source_edge = any(
        edge.get("edge_type") == "cites"
        and isinstance(edge.get("to_ref"), dict)
        and edge["to_ref"].get("kind") == "source"
        for edge in edges
    )
    if not has_source_edge:
        return False

    contains_refs = {
        (
            ref.get("document_id"),
            ref.get("chunk_id"),
            ref.get("chunk_record_id"),
        )
        for edge in edges
        if edge.get("edge_type") == "contains" and isinstance(edge.get("to_ref"), dict)
        for ref in [edge["to_ref"]]
        if ref.get("kind") == "chunk"
    }
    for chunk in chunks:
        chunk_id = chunk.get("chunk_id")
        chunk_record_id = str(chunk.get("chunk_record_id") or "").strip()
        if chunk_id is None or not chunk_record_id:
            return False
        if (document_id, chunk_id, chunk_record_id) not in contains_refs:
            return False
    return True


def _edge_id_ref(ref: dict[str, Any]) -> dict[str, Any]:
    """Return the stable structural-edge identity, excluding derived aliases."""
    identity = dict(ref)
    identity.pop("key", None)
    return identity


def _enrich_existing_edge_refs(existing: dict[str, Any], proposed: dict[str, Any]) -> dict[str, Any]:
    updated = dict(existing)
    changed = False
    for field in ("from_ref", "to_ref"):
        current_ref = existing.get(field)
        proposed_ref = proposed.get(field)
        if isinstance(current_ref, dict) and isinstance(proposed_ref, dict):
            merged_ref = {**current_ref, **{key: value for key, value in proposed_ref.items() if value is not None}}
            if merged_ref != current_ref:
                updated[field] = merged_ref
                changed = True
    if changed:
        updated["updated_at"] = now_iso()
    return updated


def _ref_matches_document(ref: Any, document_id: str) -> bool:
    return (
        isinstance(ref, dict)
        and ref.get("kind") == "document"
        and (ref.get("document_id") == document_id or ref.get("key") == document_id)
    )


def _readiness_from_records(ledger: MemoryOSLedger, *, document_id: str) -> dict[str, bool]:
    chunks = _chunks_for_document(ledger, document_id)
    documents = [
        document
        for document in list_records(ledger, "documents")
        if str(document.get("document_id") or "") == document_id
    ]
    coverage_maps = [
        receipt
        for receipt in list_records(ledger, "retrieval_receipts")
        if isinstance(receipt, dict) and str(receipt.get("document_id") or "") == document_id
    ]
    usable = any(document.get("usable") is True for document in documents)
    all_pages_observed = _all_document_pages_observed(
        ledger,
        document_id=document_id,
        documents=documents,
        coverage_maps=coverage_maps,
    )
    readiness = _empty_readiness()
    readiness["searchable"] = bool(chunks)
    readiness["usable"] = usable
    readiness["ocr_covered"] = _coverage_lane_complete(
        coverage_maps,
        missing_field="missing_ocr_pages",
        all_pages_observed=all_pages_observed,
    )
    readiness["visual_covered"] = _coverage_lane_complete(
        coverage_maps,
        missing_field="missing_visual_pages",
        all_pages_observed=all_pages_observed,
    )
    readiness["table_covered"] = _coverage_lane_complete(
        coverage_maps,
        missing_field="missing_table_pages",
        all_pages_observed=all_pages_observed,
    )
    return readiness


def _coverage_lane_complete(
    coverage_maps: list[dict[str, Any]],
    *,
    missing_field: str,
    all_pages_observed: bool,
) -> bool:
    if not coverage_maps or not all_pages_observed:
        return False
    return all(not list(map_record.get(missing_field) or []) for map_record in coverage_maps)


def _all_document_pages_observed(
    ledger: MemoryOSLedger,
    *,
    document_id: str,
    documents: list[dict[str, Any]],
    coverage_maps: list[dict[str, Any]],
) -> bool:
    page_count = 0
    for document in documents:
        document_payload = document.get("document") if isinstance(document.get("document"), dict) else {}
        try:
            page_count = max(page_count, int(document_payload.get("page_count") or 0))
        except (TypeError, ValueError):
            continue
    if page_count <= 0:
        for coverage_map in coverage_maps:
            try:
                page_count = max(page_count, int(coverage_map.get("page_count") or 0))
            except (TypeError, ValueError):
                continue
    if page_count <= 0:
        return bool(coverage_maps)
    observed_pages = {
        int(section.get("page_number"))
        for section in list_records(ledger, "sections")
        if isinstance(section, dict)
        and str(section.get("document_id") or "") == document_id
        and _safe_positive_int(section.get("page_number")) is not None
    }
    return len(observed_pages) >= page_count


def _safe_positive_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _ingestion_error(
    status: str,
    code: str,
    message: str,
    *,
    ingestion_id: str | None,
    category: str = "validation",
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error = {"code": code, "category": category, "message": message}
    if details is not None:
        error["details"] = details
    return {
        "schema_version": DOCUMENT_INGESTION_SCHEMA_VERSION,
        "status": status,
        "ingestion_id": ingestion_id,
        "readiness": _empty_readiness(),
        "chunk_count": 0,
        "indexed_count": 0,
        "terminal": status in {"failed", "cancelled", "completed", "not_found"},
        "resumable": status in {"planned", "partial", "running"},
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "error": error,
        "errors": [error],
    }


def _with_checkpoint_retrieval_index_error(error: dict[str, Any], exc: Exception) -> dict[str, Any]:
    details = error.get("details")
    merged_details = dict(details) if isinstance(details, dict) else {"original_details": details}
    merged_details["checkpoint_retrieval_index_error"] = {
        "code": "checkpoint_retrieval_index_failed",
        "category": "retrieval",
        "message": "document ingestion error was recorded, but retrieval reindexing failed.",
        "details": {
            "exception_type": type(exc).__name__,
            "message": str(exc),
        },
    }
    return {**error, "details": merged_details}


def _chunk_records_for_retrieval(
    ledger: MemoryOSLedger,
    document_id: str,
    *,
    record: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    records = []
    plan = dict(record or {})
    document = read_record(ledger, "documents", document_id)
    document = enrich_document_record(document) if isinstance(document, dict) else {}
    raw_document = document.get("document") if isinstance(document.get("document"), dict) else {}
    title = document.get("title") or raw_document.get("title") or document_id
    for chunk in _chunks_for_document(ledger, document_id):
        chunk_record_id = str(chunk["chunk_record_id"])
        metadata = {
            "document_id": document_id,
            "chunk_record_id": chunk_record_id,
            "title": title,
            "tags": ["document-ingestion"],
            "project": plan.get("project"),
            "domain": plan.get("domain"),
            "status": "active",
            "source": "document_ingestion",
        }
        merge_catalog_into_chunk_metadata(metadata, document)
        records.append(
            {
                "document_id": chunk_record_id,
                "parent_key": document_id,
                "key": document_id,
                "chunk_id": int(chunk["chunk_id"]),
                "text": str(chunk["text"]),
                "metadata": metadata,
            }
        )
    return records


def _merge_artifacts(artifacts: list[Any]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        artifact_id = str(artifact.get("artifact_id") or "").strip()
        if not artifact_id:
            continue
        if artifact_id not in merged:
            order.append(artifact_id)
        merged[artifact_id] = artifact
    return [merged[artifact_id] for artifact_id in order]


def _merge_windows(windows: list[Any], checkpoint: dict[str, Any]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for window in [*windows, checkpoint]:
        if not isinstance(window, dict):
            continue
        window_id = str(window.get("window_digest") or window.get("window_id") or "").strip()
        if not window_id:
            continue
        if window_id not in merged:
            order.append(window_id)
        merged[window_id] = window
    return [merged[window_id] for window_id in order]


def _window_checkpoint(
    *,
    window_index: int,
    packet: dict[str, Any],
    artifact: dict[str, Any] | None,
    document_id: str,
) -> dict[str, Any]:
    artifact = dict(artifact or {})
    page_range = _packet_page_range(packet)
    return {
        "window_id": f"window:{window_index:04d}",
        "window_digest": _window_digest(packet),
        "window_index": window_index,
        "status": "stored",
        "document_id": document_id,
        "page_range": page_range,
        "artifact_id": artifact.get("artifact_id"),
        "page_refs": list(artifact.get("page_refs") or []),
        "updated_at": now_iso(),
    }


def _window_digest(packet: dict[str, Any]) -> str:
    disassembly = packet.get("disassembly") if isinstance(packet.get("disassembly"), dict) else {}
    document = disassembly.get("document") if isinstance(disassembly.get("document"), dict) else {}
    source = disassembly.get("source") if isinstance(disassembly.get("source"), dict) else {}
    review_source = packet.get("source") if isinstance(packet.get("source"), dict) else {}
    text = disassembly.get("text") if isinstance(disassembly.get("text"), dict) else {}
    text_content = str(text.get("content") or "")
    return stable_id(
        "doc_window",
        {
            "document_id": document.get("document_id") or review_source.get("document_id"),
            "content_hash": (
                document.get("content_hash")
                or source.get("content_hash")
                or review_source.get("sha256")
            ),
            "page_range": _packet_page_range(packet),
            "text_sha256": "sha256:" + hashlib.sha256(text_content.encode("utf-8")).hexdigest(),
        },
    )


def _packet_page_range(packet: dict[str, Any]) -> dict[str, Any]:
    disassembly = packet.get("disassembly") if isinstance(packet.get("disassembly"), dict) else {}
    document = disassembly.get("document") if isinstance(disassembly.get("document"), dict) else {}
    page_range = document.get("page_range") if isinstance(document.get("page_range"), dict) else {}
    return {
        "start": page_range.get("start"),
        "end": page_range.get("end"),
    }


def _source_summary(source_path: str) -> dict[str, Any]:
    path = Path(source_path).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise ValueError(f"source_path does not exist or is not a file: {source_path}")
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": str(path),
        "source_uri": path.as_uri(),
        "sha256": f"sha256:{digest.hexdigest()}",
        "size_bytes": path.stat().st_size,
        "source_type": "pdf" if path.suffix.lower() == ".pdf" else path.suffix.lower().removeprefix("."),
    }


def _choice(value: str, allowed: set[str], field_name: str) -> str:
    normalized = str(value or "").strip()
    if normalized not in allowed:
        raise ValueError(f"{field_name} must be one of: {', '.join(sorted(allowed))}")
    return normalized


def _page_window_size(value: Any) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("page_window_size must be an integer") from exc
    return max(1, normalized)


def _ingestion_id(*, source: dict[str, Any], profile: str, project: str | None, domain: str | None) -> str:
    return stable_id(
        "doc_ingest",
        {
            "source_path": source["path"],
            "source_sha256": source["sha256"],
            "profile": profile,
            "project": project,
            "domain": domain,
        },
    ).replace(":", "_")


def _empty_readiness() -> dict[str, bool]:
    return {
        "searchable": False,
        "structural_graph_covered": False,
        "semantic_graph_covered": False,
        "ocr_covered": False,
        "visual_covered": False,
        "table_covered": False,
        "usable": False,
    }


def _find_ingestion(
    ledger: MemoryOSLedger,
    *,
    ingestion_id: str | None,
    document_id: str | None,
) -> dict[str, Any] | None:
    if ingestion_id:
        record = read_record(ledger, "jobs", ingestion_id)
        if isinstance(record, dict) and record.get("record_type") == "document_ingestion":
            return record
    if document_id:
        for record in list_records(ledger, "jobs"):
            if record.get("record_type") == "document_ingestion" and record.get("document_id") == document_id:
                return record
    return None


def _next_action(record: dict[str, Any]) -> dict[str, Any]:
    if record.get("status") in {"queued", "running"}:
        return {"tool": "inspect_document_ingestion", "ingestion_id": record["ingestion_id"]}
    coverage_pass = record.get("coverage_pass") if isinstance(record.get("coverage_pass"), dict) else {}
    if coverage_pass.get("status") == "partial":
        return {"tool": "prepare_document_coverage_pass", "ingestion_id": record["ingestion_id"]}
    readiness = record.get("readiness") if isinstance(record.get("readiness"), dict) else {}
    if readiness.get("searchable") and not readiness.get("usable") and not record.get("errors"):
        return {"tool": "prepare_document_ingestion_completion", "ingestion_id": record["ingestion_id"]}
    if record.get("status") in {"planned", "partial", "running"}:
        return {"tool": "run_document_ingestion", "ingestion_id": record["ingestion_id"]}
    return {"tool": "inspect_document_ingestion", "ingestion_id": record["ingestion_id"]}
