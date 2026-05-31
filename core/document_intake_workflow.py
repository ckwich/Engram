"""End-to-end no-write document intake review workflow."""
from __future__ import annotations

import subprocess
from typing import Any, Callable

from core.document_extractors import prepare_document_disassembly
from core.document_intelligence import preview_document_extraction


DOCUMENT_INTAKE_REVIEW_SCHEMA_VERSION = "2026-05-14.document-intake-review.v1"
READ_ONLY_POLICY = {
    "write_behavior": "read_only",
    "active_memory_promoted": False,
    "graph_edges_promoted": False,
}


DocumentDisassembler = Callable[..., dict[str, Any]]


def prepare_document_intake_review(
    source_path: str,
    extractor_id: str | None = None,
    max_pages: int | None = None,
    require_visual_coverage: bool = True,
    require_table_coverage: bool = True,
    require_ocr_coverage: bool = True,
    source_type: str = "pdf",
    page_range: str | None = None,
    resume_token: str | None = None,
    document_disassembler: DocumentDisassembler = prepare_document_disassembly,
) -> dict[str, Any]:
    """Prepare an end-to-end no-write review packet for a local document."""
    input_payload = {
        "source_path": source_path,
        "source_type": source_type,
        "max_pages": max_pages,
        "extractor_id": extractor_id,
        "require_visual_coverage": bool(require_visual_coverage),
        "require_table_coverage": bool(require_table_coverage),
        "require_ocr_coverage": bool(require_ocr_coverage),
        "page_range": page_range,
        "resume_token": resume_token,
    }
    try:
        disassembly = document_disassembler(
            source_path=source_path,
            source_type=source_type,
            max_pages=max_pages,
            page_range=page_range,
            resume_token=resume_token,
        )
    except ValueError as exc:
        return _failure_packet(
            status="schema_failed",
            source_path=source_path,
            input_payload=input_payload,
            error={
                "code": "invalid_request",
                "category": "validation",
                "message": str(exc),
            },
        )
    except RuntimeError as exc:
        return _failure_packet(
            status="unavailable",
            source_path=source_path,
            input_payload=input_payload,
            error={
                "code": "runtime_error",
                "category": "infrastructure",
                "message": str(exc),
            },
        )
    except subprocess.TimeoutExpired as exc:
        return _failure_packet(
            status="unavailable",
            source_path=source_path,
            input_payload=input_payload,
            error={
                "code": "tool_timeout",
                "category": "infrastructure",
                "message": f"document disassembly timed out after {exc.timeout} seconds",
            },
        )

    disassembly_error = disassembly.get("error") if isinstance(disassembly, dict) else None
    if isinstance(disassembly_error, dict):
        error = _normalize_disassembly_error(disassembly_error)
        return _packet(
            status="unavailable" if error["category"] == "infrastructure" else "schema_failed",
            source=_source_summary(source_path, disassembly),
            disassembly=disassembly,
            document_preview=None,
            extraction_request=None,
            coverage_missing=[],
            input_payload=input_payload,
            error=error,
        )

    document_preview = _build_document_preview(disassembly, extractor_id)
    coverage_missing = _coverage_missing(
        disassembly,
        require_visual_coverage=bool(require_visual_coverage),
        require_table_coverage=bool(require_table_coverage),
        require_ocr_coverage=bool(require_ocr_coverage),
    )
    extraction_request = (
        disassembly.get("visual_extraction_request")
        if coverage_missing
        else None
    )
    return _packet(
        status="partial" if coverage_missing or _has_more(disassembly) else "ok",
        source=_source_summary(source_path, disassembly),
        disassembly=disassembly,
        document_preview=document_preview,
        extraction_request=extraction_request,
        coverage_missing=coverage_missing,
        input_payload=input_payload,
        error=None,
    )


def _build_document_preview(
    disassembly: dict[str, Any],
    extractor_id: str | None,
) -> dict[str, Any] | None:
    document = disassembly.get("document")
    source = disassembly.get("source")
    text = disassembly.get("text")
    content = text.get("content") if isinstance(text, dict) else None
    if not isinstance(document, dict) or not isinstance(source, dict) or not isinstance(content, str) or not content.strip():
        return None

    metadata = {
        "document_id": document.get("document_id"),
        "source_path": source.get("path"),
        "source_content_hash": source.get("content_hash"),
        "page_count": document.get("page_count"),
        "page_limit": document.get("page_limit"),
    }
    preview = preview_document_extraction(
        title=str(document.get("title") or "Untitled Document"),
        source_uri=str(source.get("source_uri") or ""),
        source_type=str(document.get("source_type") or source.get("source_type") or "pdf"),
        content=content,
        media_type=str(document.get("media_type") or source.get("media_type") or "application/pdf"),
        metadata=metadata,
        extractor_id=extractor_id or "engram-document-intake-review",
        extractor_kind="agent_native",
    )
    return {
        "preview": {
            **preview,
            "document": dict(document),
        },
        "error": None,
    }


def _coverage_missing(
    disassembly: dict[str, Any],
    *,
    require_visual_coverage: bool,
    require_table_coverage: bool,
    require_ocr_coverage: bool,
) -> list[str]:
    pages = [page for page in disassembly.get("pages") or [] if isinstance(page, dict)]
    visual_request = disassembly.get("visual_extraction_request")
    requested_capabilities = (
        set(visual_request.get("requested_capabilities") or [])
        if isinstance(visual_request, dict)
        else set()
    )

    missing: list[str] = []
    if require_ocr_coverage and (
        any(page.get("text_status") in {"no_text", "low_text"} for page in pages)
        or "ocr_text" in requested_capabilities
    ):
        missing.append("ocr")
    if require_table_coverage and "table_structure" in requested_capabilities:
        missing.append("table")
    if require_visual_coverage and (
        any(bool(page.get("visual_review_needed")) for page in pages)
        or isinstance(visual_request, dict)
    ):
        missing.append("visual")
    return missing


def _source_summary(source_path: str, disassembly: dict[str, Any] | None = None) -> dict[str, Any]:
    source = dict((disassembly or {}).get("source") or {})
    document = dict((disassembly or {}).get("document") or {})
    return {
        "source_path": source.get("path") or source_path,
        "source_uri": source.get("source_uri"),
        "source_type": source.get("source_type"),
        "media_type": source.get("media_type"),
        "document_id": document.get("document_id"),
        "sha256": source.get("content_hash"),
    }


def _has_more(disassembly: dict[str, Any]) -> bool:
    resume = disassembly.get("resume")
    return bool(isinstance(resume, dict) and resume.get("has_more"))


def _review_completeness(
    *,
    status: str,
    disassembly: dict[str, Any] | None,
    coverage_missing: list[str],
    error: dict[str, str] | None,
) -> dict[str, Any]:
    page_window = _page_window(disassembly)
    open_obligations: list[str] = []
    if page_window.get("has_more"):
        open_obligations.append("resume_remaining_pages")
    if "ocr" in coverage_missing:
        open_obligations.append("resolve_ocr_coverage")
    if "table" in coverage_missing:
        open_obligations.append("resolve_table_coverage")
    if "visual" in coverage_missing:
        open_obligations.append("resolve_visual_coverage")
    if error:
        open_obligations.append(f"resolve_{error.get('category') or 'error'}_error")

    complete_review = bool(
        status == "ok"
        and not open_obligations
        and not coverage_missing
        and not page_window.get("has_more")
        and error is None
    )
    completeness_status = "complete" if complete_review else status
    if completeness_status in {"ok", "partial"}:
        completeness_status = "incomplete"
    return {
        "status": completeness_status,
        "complete_review": complete_review,
        "page_window": page_window,
        "coverage_missing": list(coverage_missing),
        "open_obligations": open_obligations,
        "reviewer_warning": None
        if complete_review
        else "Document review is incomplete until remaining page windows and coverage obligations are resolved.",
        "artifact_store_review_ready": complete_review,
        "active_promotion_allowed": False,
    }


def _page_window(disassembly: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(disassembly, dict):
        return {
            "start": None,
            "end": None,
            "pages_returned": 0,
            "page_count": None,
            "has_more": False,
            "next_page": None,
        }
    pages = [page for page in disassembly.get("pages") or [] if isinstance(page, dict)]
    page_numbers = [
        int(page["page_number"])
        for page in pages
        if isinstance(page.get("page_number"), int)
        or (isinstance(page.get("page_number"), str) and str(page.get("page_number")).isdigit())
    ]
    resume = disassembly.get("resume") if isinstance(disassembly.get("resume"), dict) else {}
    page_range = resume.get("page_range") if isinstance(resume.get("page_range"), dict) else {}
    document = disassembly.get("document") if isinstance(disassembly.get("document"), dict) else {}
    start = page_range.get("start") if page_range.get("start") is not None else (min(page_numbers) if page_numbers else None)
    end = page_range.get("end") if page_range.get("end") is not None else (max(page_numbers) if page_numbers else None)
    return {
        "start": start,
        "end": end,
        "pages_returned": len(pages),
        "page_count": resume.get("page_count") or document.get("page_count"),
        "has_more": bool(resume.get("has_more")),
        "next_page": resume.get("next_page"),
    }


def _normalize_disassembly_error(error: dict[str, Any]) -> dict[str, str]:
    code = str(error.get("code") or "runtime_error")
    category = "infrastructure" if code in {"missing_extractor", "tool_failed", "runtime_error"} else "validation"
    return {
        "code": code,
        "category": category,
        "message": str(error.get("message") or code),
    }


def _failure_packet(
    *,
    status: str,
    source_path: str,
    input_payload: dict[str, Any],
    error: dict[str, str],
) -> dict[str, Any]:
    return _packet(
        status=status,
        source=_source_summary(source_path),
        disassembly=None,
        document_preview=None,
        extraction_request=None,
        coverage_missing=[],
        input_payload=input_payload,
        error=error,
    )


def _packet(
    *,
    status: str,
    source: dict[str, Any],
    disassembly: dict[str, Any] | None,
    document_preview: dict[str, Any] | None,
    extraction_request: dict[str, Any] | None,
    coverage_missing: list[str],
    input_payload: dict[str, Any],
    error: dict[str, str] | None,
) -> dict[str, Any]:
    quality = disassembly.get("quality_report") if isinstance(disassembly, dict) else None
    artifact_manifest = disassembly.get("artifact_manifest") if isinstance(disassembly, dict) else None
    promotion_guidance = (
        disassembly.get("promotion_guidance")
        if isinstance(disassembly, dict)
        else {"default_action": "resolve_document_intake_error_before_review", "auto_promote": False}
    )
    if not isinstance(promotion_guidance, dict):
        promotion_guidance = {"default_action": "review_before_promotion", "auto_promote": False}
    promotion_guidance = {**promotion_guidance, "auto_promote": False}
    documents_consulted = 1 if isinstance(disassembly, dict) and isinstance(disassembly.get("document"), dict) else 0
    resume = disassembly.get("resume") if isinstance(disassembly, dict) else None
    review_completeness = _review_completeness(
        status=status,
        disassembly=disassembly,
        coverage_missing=coverage_missing,
        error=error,
    )
    return {
        "schema_version": DOCUMENT_INTAKE_REVIEW_SCHEMA_VERSION,
        "record_type": "document_intake_review",
        "status": status,
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "source": source,
        "disassembly": disassembly,
        "extraction_request": extraction_request,
        "document_preview": document_preview,
        "quality": quality,
        "artifact_manifest": artifact_manifest,
        "draft_candidates": [],
        "promotion_guidance": promotion_guidance,
        "policy": dict(READ_ONLY_POLICY),
        "resume": resume if isinstance(resume, dict) else None,
        "review_completeness": review_completeness,
        "receipts": {
            "artifacts_built": 1 if isinstance(disassembly, dict) else 0,
            "artifacts_read": 0,
            "documents_consulted": documents_consulted,
            "coverage_missing": coverage_missing,
            "resume": resume if isinstance(resume, dict) else None,
            "input": input_payload,
        },
        "error": error,
    }
