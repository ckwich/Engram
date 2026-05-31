"""Automatic document image/OCR/table coverage preparation."""
from __future__ import annotations

from typing import Any, Callable

from core.document_coverage import capabilities_for_image_ref
from core.document_coverage_workbench import prepare_document_coverage_workbench
from core.document_intelligence import preview_visual_extraction
from core.memory_os._records import now_iso, stable_id, upsert_record


DOCUMENT_COVERAGE_PASS_SCHEMA_VERSION = "2026-05-19.document-coverage-pass.v1"
COVERAGE_POLICIES = {"manual", "auto_local", "required", "external_bundle"}

Workbench = Callable[..., dict[str, Any]]
VisualPreviewer = Callable[..., dict[str, Any]]


class DocumentCoveragePassService:
    """Run provider-neutral coverage preparation without promoting memory."""

    def __init__(
        self,
        runtime: Any,
        *,
        workbench: Workbench = prepare_document_coverage_workbench,
        visual_previewer: VisualPreviewer = preview_visual_extraction,
    ) -> None:
        self.runtime = runtime
        self.ledger = runtime.ledger
        self.workbench = workbench
        self.visual_previewer = visual_previewer

    def prepare_document_coverage_pass(
        self,
        *,
        ingestion_record: dict[str, Any],
        review_packets: list[dict[str, Any]] | None = None,
        coverage_policy: str = "auto_local",
        coverage_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Prepare OCR/table/visual coverage evidence without promoting memory."""
        policy = _coverage_policy(coverage_policy)
        if policy == "manual":
            return _manual_result(ingestion_record)

        packets = [packet for packet in review_packets or [] if isinstance(packet, dict)]
        visual_request = _merged_visual_request(ingestion_record, packets)
        if not visual_request.get("image_refs"):
            return _noop_result(ingestion_record, policy=policy)

        source_path = str(((ingestion_record.get("source") or {}).get("path") or "")).strip()
        if not source_path:
            return _blocked_result(
                ingestion_record,
                policy=policy,
                code="source_path_missing",
                message="document coverage pass requires source.path",
            )

        options = dict(coverage_options or {})
        document_record = _document_record(ingestion_record, packets, visual_request)
        workbench = self.workbench(
            source_path=source_path,
            document_record=document_record,
            visual_request=visual_request,
            render_pages=bool(options.get("render_pages", True)),
            run_ocr=bool(options.get("run_ocr", True)),
            run_table_detection=bool(options.get("run_table_detection", True)),
            max_pages=options.get("max_pages"),
            tool_paths=options.get("tool_paths"),
            timeout_seconds=int(options.get("timeout_seconds", 60)),
        )
        preview_args = workbench.get("preview_visual_extraction_arguments")
        visual_preview = None
        if isinstance(preview_args, dict) and preview_args.get("observations"):
            visual_preview = self.visual_previewer(**preview_args)

        result = _coverage_result(
            ingestion_record=ingestion_record,
            policy=policy,
            visual_request=visual_request,
            workbench=workbench,
            visual_preview=visual_preview,
        )
        upsert_record(self.ledger, "job_events", result["event_id"], _sanitized_event(result))
        return result


def _coverage_policy(value: str | None) -> str:
    policy = str(value or "auto_local").strip()
    if policy not in COVERAGE_POLICIES:
        raise ValueError(f"coverage_policy must be one of: {', '.join(sorted(COVERAGE_POLICIES))}")
    return policy


def _merged_visual_request(
    ingestion_record: dict[str, Any],
    review_packets: list[dict[str, Any]],
) -> dict[str, Any]:
    image_refs: list[dict[str, Any]] = []
    requested: set[str] = set()
    document_id = str(ingestion_record.get("document_id") or "").strip()
    source_uri = str(((ingestion_record.get("source") or {}).get("source_uri") or "")).strip()
    for packet in review_packets:
        request = packet.get("extraction_request") if isinstance(packet.get("extraction_request"), dict) else {}
        document_id = str(request.get("document_id") or document_id).strip()
        for capability in request.get("requested_capabilities") or []:
            if str(capability).strip():
                requested.add(str(capability).strip())
        for ref in request.get("image_refs") or []:
            if isinstance(ref, dict):
                normalized = dict(ref)
                if "source_uri" not in normalized and source_uri:
                    normalized["source_uri"] = source_uri
                image_refs.append(normalized)
                requested.update(capabilities_for_image_ref(normalized, request.get("requested_capabilities")))
    deduped_refs = _dedupe_image_refs(image_refs)
    return {
        "request_id": stable_id(
            "doc_cov_req",
            {
                "ingestion_id": ingestion_record.get("ingestion_id"),
                "document_id": document_id,
                "image_refs": deduped_refs,
                "requested_capabilities": sorted(requested),
            },
        ),
        "document_id": document_id,
        "image_refs": deduped_refs,
        "requested_capabilities": sorted(requested),
    }


def _document_record(
    ingestion_record: dict[str, Any],
    review_packets: list[dict[str, Any]],
    visual_request: dict[str, Any],
) -> dict[str, Any]:
    source = dict(ingestion_record.get("source") or {})
    document: dict[str, Any] = {}
    for packet in review_packets:
        disassembly = packet.get("disassembly") if isinstance(packet.get("disassembly"), dict) else {}
        candidate = disassembly.get("document") if isinstance(disassembly.get("document"), dict) else {}
        if candidate:
            document = dict(candidate)
            break
    document_id = str(visual_request.get("document_id") or ingestion_record.get("document_id") or document.get("document_id") or "")
    return {
        "document_id": document_id,
        "title": document.get("title") or document_id,
        "source_uri": source.get("source_uri"),
        "source_type": source.get("source_type") or document.get("source_type") or "pdf",
        "media_type": document.get("media_type") or "application/pdf",
        "content_hash": source.get("sha256") or document.get("content_hash"),
        "metadata": {"ingestion_id": ingestion_record.get("ingestion_id")},
    }


def _coverage_result(
    *,
    ingestion_record: dict[str, Any],
    policy: str,
    visual_request: dict[str, Any],
    workbench: dict[str, Any],
    visual_preview: dict[str, Any] | None,
) -> dict[str, Any]:
    blocking_issues = _blocking_issues(workbench, visual_preview, visual_request)
    status = "ok" if not blocking_issues else "partial"
    event_id = stable_id(
        "doc_cov_event",
        {
            "ingestion_id": ingestion_record.get("ingestion_id"),
            "visual_request_id": visual_request.get("request_id"),
            "status": status,
        },
    )
    return {
        "schema_version": DOCUMENT_COVERAGE_PASS_SCHEMA_VERSION,
        "record_type": "document_coverage_pass",
        "event_id": event_id,
        "job_id": ingestion_record.get("ingestion_id"),
        "ingestion_id": ingestion_record.get("ingestion_id"),
        "document_id": visual_request.get("document_id") or ingestion_record.get("document_id"),
        "status": status,
        "coverage_policy": policy,
        "visual_request": visual_request,
        "workbench": workbench,
        "visual_preview": visual_preview,
        "blocking_issues": blocking_issues,
        "next_action": _next_action(status),
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "error": None if status == "ok" else {"code": "coverage_pass_incomplete", "category": "document_coverage"},
    }


def _blocking_issues(
    workbench: dict[str, Any],
    visual_preview: dict[str, Any] | None,
    visual_request: dict[str, Any],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for receipt in workbench.get("unavailable_receipts") or []:
        if isinstance(receipt, dict):
            issues.append({"code": str(receipt.get("code") or "coverage_adapter_unavailable"), "details": receipt})
    for receipt in workbench.get("skipped_receipts") or []:
        if isinstance(receipt, dict):
            issues.append({"code": str(receipt.get("code") or "coverage_adapter_skipped"), "details": receipt})
    if isinstance(visual_preview, dict):
        for warning in visual_preview.get("quality_warnings") or []:
            if isinstance(warning, dict):
                issues.append({"code": str(warning.get("code") or "visual_coverage_warning"), "details": warning})
        coverage = visual_preview.get("visual_coverage") if isinstance(visual_preview.get("visual_coverage"), dict) else {}
        for missing in coverage.get("missing_capabilities") or []:
            if isinstance(missing, dict):
                issues.append({"code": "missing_visual_capability", "details": missing})
    else:
        issues.extend(_missing_visual_request_issues(visual_request))
    if str(workbench.get("status") or "").strip() == "partial" and not issues:
        issues.append({"code": "coverage_workbench_incomplete", "details": {"status": "partial"}})
    return issues


def _missing_visual_request_issues(visual_request: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    fallback = list(visual_request.get("requested_capabilities") or [])
    for image_ref in visual_request.get("image_refs") or []:
        if not isinstance(image_ref, dict):
            continue
        capabilities = capabilities_for_image_ref(image_ref, fallback)
        if not capabilities:
            issues.append({"code": "missing_visual_evidence", "details": {"image_ref": dict(image_ref)}})
            continue
        for capability in capabilities:
            issues.append(
                {
                    "code": "missing_visual_capability",
                    "details": {
                        "page_number": image_ref.get("page_number") or image_ref.get("page"),
                        "capability": capability,
                        "image_ref": dict(image_ref),
                    },
                }
            )
    return issues


def _sanitized_event(result: dict[str, Any]) -> dict[str, Any]:
    workbench = result.get("workbench") if isinstance(result.get("workbench"), dict) else {}
    preview = result.get("visual_preview") if isinstance(result.get("visual_preview"), dict) else {}
    return {
        "schema_version": DOCUMENT_COVERAGE_PASS_SCHEMA_VERSION,
        "record_type": "document_coverage_pass_event",
        "event_id": result["event_id"],
        "job_id": result.get("job_id"),
        "event_type": "document_coverage_pass",
        "status": result.get("status"),
        "coverage_policy": result.get("coverage_policy"),
        "document_id": result.get("document_id"),
        "visual_request_id": (result.get("visual_request") or {}).get("request_id"),
        "receipts": dict(workbench.get("receipts") or {}),
        "visual_preview_receipt": dict(preview.get("receipt") or {}),
        "blocking_issue_count": len(result.get("blocking_issues") or []),
        "blocking_issue_codes": [
            str(issue.get("code") or "")
            for issue in result.get("blocking_issues") or []
            if isinstance(issue, dict)
        ],
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "created_at": now_iso(),
    }


def _manual_result(ingestion_record: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": DOCUMENT_COVERAGE_PASS_SCHEMA_VERSION,
        "record_type": "document_coverage_pass",
        "status": "manual",
        "coverage_policy": "manual",
        "ingestion_id": ingestion_record.get("ingestion_id"),
        "document_id": ingestion_record.get("document_id"),
        "visual_request": {"image_refs": [], "requested_capabilities": []},
        "workbench": None,
        "visual_preview": None,
        "blocking_issues": [],
        "next_action": {"tool": "run_document_ingestion"},
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "error": None,
    }


def _noop_result(ingestion_record: dict[str, Any], *, policy: str) -> dict[str, Any]:
    return {
        "schema_version": DOCUMENT_COVERAGE_PASS_SCHEMA_VERSION,
        "record_type": "document_coverage_pass",
        "status": "ok",
        "coverage_policy": policy,
        "ingestion_id": ingestion_record.get("ingestion_id"),
        "document_id": ingestion_record.get("document_id"),
        "visual_request": {"image_refs": [], "requested_capabilities": []},
        "workbench": None,
        "visual_preview": None,
        "blocking_issues": [],
        "next_action": {"tool": "prepare_document_ingestion_completion"},
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "error": None,
    }


def _blocked_result(
    ingestion_record: dict[str, Any],
    *,
    policy: str,
    code: str,
    message: str,
) -> dict[str, Any]:
    return {
        "schema_version": DOCUMENT_COVERAGE_PASS_SCHEMA_VERSION,
        "record_type": "document_coverage_pass",
        "status": "partial",
        "coverage_policy": policy,
        "ingestion_id": ingestion_record.get("ingestion_id"),
        "document_id": ingestion_record.get("document_id"),
        "visual_request": {"image_refs": [], "requested_capabilities": []},
        "workbench": None,
        "visual_preview": None,
        "blocking_issues": [{"code": code, "message": message}],
        "next_action": {"tool": "prepare_document_coverage_pass"},
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "error": {"code": code, "category": "document_coverage", "message": message},
    }


def _next_action(status: str) -> dict[str, Any]:
    if status == "ok":
        return {"tool": "prepare_document_ingestion_completion"}
    return {"tool": "prepare_document_coverage_pass"}


def _dedupe_image_refs(image_refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for ref in image_refs:
        signature = tuple(sorted((str(key), str(value)) for key, value in ref.items()))
        if signature in seen:
            continue
        seen.add(signature)
        merged.append(ref)
    return merged
