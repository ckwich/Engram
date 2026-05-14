"""Reusable PDF intake smoke runner with content-safe summaries."""
from __future__ import annotations

from typing import Any, Callable

from core.document_intake_workflow import prepare_document_intake_review
from core.engramd_client import EngramDaemonClient


ReviewBuilder = Callable[..., dict[str, Any]]


def run_pdf_smoke(
    source_path: str,
    *,
    full: bool = False,
    max_pages: int | None = 10,
    store_artifact: bool = False,
    accept: bool = False,
    daemon_url: str = "http://127.0.0.1:8765",
    timeout: float = 300.0,
    require_visual_coverage: bool = True,
    require_table_coverage: bool = True,
    require_ocr_coverage: bool = True,
    page_range: str | None = None,
    resume_token: str | None = None,
    daemon_client: Any | None = None,
    review_builder: ReviewBuilder = prepare_document_intake_review,
) -> dict[str, Any]:
    """Run local PDF review and optionally store ledgered document evidence.

    The returned payload intentionally summarizes metadata, receipts, and ids
    only. It never echoes extracted page/chunk text.
    """
    review_packet = review_builder(
        source_path=source_path,
        max_pages=None if full else max_pages,
        require_visual_coverage=require_visual_coverage,
        require_table_coverage=require_table_coverage,
        require_ocr_coverage=require_ocr_coverage,
        page_range=page_range,
        resume_token=resume_token,
    )
    summary = summarize_review_packet(review_packet)
    summary["smoke"] = {
        "source_path": source_path,
        "full": bool(full),
        "max_pages": None if full else max_pages,
        "store_artifact_requested": bool(store_artifact),
        "accept_requested": bool(accept),
    }
    if not store_artifact:
        return summary

    client = daemon_client or EngramDaemonClient(daemon_url, timeout=timeout)
    prepare_response = client.prepare_document_artifact_store({"review_packet": review_packet})
    artifact_store = _summarize_prepare_response(prepare_response)
    summary["artifact_store"] = artifact_store
    prepared_transaction_id = artifact_store.get("prepared_transaction_id")
    if accept and prepared_transaction_id:
        store_response = client.store_document_artifact(
            {
                "prepared_transaction_id": prepared_transaction_id,
                "accept": True,
                "review_packet": review_packet,
            }
        )
        artifact_store.update(_summarize_store_response(store_response))
        document_id = artifact_store.get("document_id") or summary.get("document", {}).get("document_id")
        if document_id:
            summary["knowledge_probe"] = _probe_document_orientation(client, document_id)
    return summary


def summarize_review_packet(review_packet: dict[str, Any]) -> dict[str, Any]:
    disassembly = review_packet.get("disassembly") if isinstance(review_packet, dict) else None
    document = disassembly.get("document") if isinstance(disassembly, dict) and isinstance(disassembly.get("document"), dict) else {}
    source = review_packet.get("source") if isinstance(review_packet.get("source"), dict) else {}
    disassembly_source = disassembly.get("source") if isinstance(disassembly, dict) and isinstance(disassembly.get("source"), dict) else {}
    text = disassembly.get("text") if isinstance(disassembly, dict) and isinstance(disassembly.get("text"), dict) else {}
    pages = [page for page in (disassembly or {}).get("pages") or [] if isinstance(page, dict)] if isinstance(disassembly, dict) else []
    image_inventory = (
        disassembly.get("image_inventory")
        if isinstance(disassembly, dict) and isinstance(disassembly.get("image_inventory"), dict)
        else {}
    )
    document_preview = review_packet.get("document_preview") if isinstance(review_packet.get("document_preview"), dict) else {}
    preview = document_preview.get("preview") if isinstance(document_preview.get("preview"), dict) else {}
    chunks = preview.get("chunks") if isinstance(preview.get("chunks"), list) else []
    citations = preview.get("citations") if isinstance(preview.get("citations"), list) else []
    extraction_request = (
        review_packet.get("extraction_request")
        if isinstance(review_packet.get("extraction_request"), dict)
        else None
    )
    review_completeness = (
        review_packet.get("review_completeness")
        if isinstance(review_packet.get("review_completeness"), dict)
        else {}
    )
    page_window = review_completeness.get("page_window") if isinstance(review_completeness.get("page_window"), dict) else {}
    return {
        "status": review_packet.get("status"),
        "schema_version": review_packet.get("schema_version"),
        "source": {
            "source_path": source.get("source_path") or disassembly_source.get("path"),
            "source_uri": source.get("source_uri") or disassembly_source.get("source_uri"),
            "source_type": source.get("source_type") or disassembly_source.get("source_type"),
            "media_type": source.get("media_type") or disassembly_source.get("media_type"),
            "sha256": source.get("sha256") or disassembly_source.get("content_hash"),
        },
        "document": {
            "document_id": document.get("document_id") or source.get("document_id"),
            "title": document.get("title"),
            "page_count": document.get("page_count"),
            "page_limit": document.get("page_limit"),
            "media_type": document.get("media_type"),
            "source_type": document.get("source_type"),
        },
        "text_inventory": {
            "char_count": text.get("char_count"),
            "page_count": text.get("page_count"),
            "content_in_summary": False,
        },
        "page_window": page_window or _page_window_from_pages(pages, document),
        "page_status_counts": _page_status_counts(pages),
        "image_inventory": {
            "image_count": image_inventory.get("image_count"),
            "pages_with_images": list(image_inventory.get("pages_with_images") or []),
        },
        "document_preview": {
            "status": document_preview.get("status"),
            "chunk_count": len(chunks),
            "citation_count": len(citations),
            "content_in_summary": False,
        },
        "review_completeness": review_completeness,
        "coverage_missing": list(review_packet.get("coverage_missing") or (review_packet.get("receipts") or {}).get("coverage_missing") or []),
        "extraction_request": _summarize_extraction_request(extraction_request),
        "quality": _summarize_quality(review_packet.get("quality")),
        "policy": review_packet.get("policy"),
        "receipts": review_packet.get("receipts"),
        "write_performed": bool(review_packet.get("write_performed")),
        "active_memory_write_performed": bool(review_packet.get("active_memory_write_performed")),
        "graph_write_performed": bool(review_packet.get("graph_write_performed")),
        "error": review_packet.get("error"),
    }


def _summarize_prepare_response(response: dict[str, Any]) -> dict[str, Any]:
    artifact_preview = response.get("artifact_preview") if isinstance(response.get("artifact_preview"), dict) else {}
    transaction = response.get("transaction") if isinstance(response.get("transaction"), dict) else {}
    return {
        "prepare_status": response.get("status"),
        "prepared_transaction_id": response.get("prepared_transaction_id") or response.get("transaction_id") or transaction.get("transaction_id"),
        "artifact_id": response.get("artifact_id") or artifact_preview.get("artifact_id"),
        "document_id": response.get("document_id") or artifact_preview.get("document_id"),
        "write_performed": bool(response.get("write_performed")),
        "active_memory_write_performed": bool(response.get("active_memory_write_performed")),
        "graph_write_performed": bool(response.get("graph_write_performed")),
        "error": response.get("error"),
    }


def _summarize_store_response(response: dict[str, Any]) -> dict[str, Any]:
    artifact = response.get("artifact") if isinstance(response.get("artifact"), dict) else {}
    document = response.get("document") if isinstance(response.get("document"), dict) else {}
    coverage_map = response.get("coverage_map") if isinstance(response.get("coverage_map"), dict) else {}
    receipts = response.get("receipts") if isinstance(response.get("receipts"), dict) else {}
    return {
        "store_status": response.get("status"),
        "stored": bool(response.get("stored")),
        "transaction_id": response.get("transaction_id"),
        "artifact_id": response.get("artifact_id") or artifact.get("artifact_id"),
        "document_id": response.get("document_id") or artifact.get("document_id") or document.get("document_id"),
        "coverage_map_id": coverage_map.get("receipt_id") or coverage_map.get("coverage_map_id"),
        "stored_artifact_count": receipts.get("stored_artifact_count"),
        "coverage_missing": list(receipts.get("coverage_missing") or []),
        "write_performed": bool(response.get("write_performed")),
        "active_memory_write_performed": bool(response.get("active_memory_write_performed")),
        "graph_write_performed": bool(response.get("graph_write_performed")),
        "error": response.get("error"),
    }


def _probe_document_orientation(client: Any, document_id: str) -> dict[str, Any]:
    try:
        response = client.query_knowledge(
            {
                "request_id": f"req-document-smoke-{document_id}",
                "ask": {
                    "goal": f"Orient to ledgered document evidence for {document_id}.",
                    "task_type": "document_orientation",
                    "project": "Engram",
                    "focus": [document_id],
                },
            }
        )
    except Exception as exc:
        return {
            "status": "unavailable",
            "error": {"code": "runtime_error", "category": "infrastructure", "message": str(exc)},
        }
    return {
        "status": response.get("status"),
        "document_count": (response.get("answer") or {}).get("document_count")
        if isinstance(response.get("answer"), dict)
        else None,
        "citation_count": len(response.get("citations") or []),
        "budget_used": response.get("budget_used"),
        "error": response.get("error"),
    }


def _page_status_counts(pages: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"text": 0, "low_text": 0, "no_text": 0, "visual_review_needed": 0}
    for page in pages:
        status = page.get("text_status")
        if status in {"text", "low_text", "no_text"}:
            counts[status] += 1
        if page.get("visual_review_needed"):
            counts["visual_review_needed"] += 1
    return counts


def _page_window_from_pages(pages: list[dict[str, Any]], document: dict[str, Any]) -> dict[str, Any]:
    page_numbers = [
        int(page["page_number"])
        for page in pages
        if isinstance(page.get("page_number"), int)
        or (isinstance(page.get("page_number"), str) and str(page.get("page_number")).isdigit())
    ]
    return {
        "start": min(page_numbers) if page_numbers else None,
        "end": max(page_numbers) if page_numbers else None,
        "pages_returned": len(pages),
        "page_count": document.get("page_count"),
        "has_more": False,
        "next_page": None,
    }


def _summarize_extraction_request(request: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(request, dict):
        return None
    image_refs = request.get("image_refs") if isinstance(request.get("image_refs"), list) else []
    return {
        "request_id": request.get("request_id"),
        "document_id": request.get("document_id"),
        "requested_capabilities": list(request.get("requested_capabilities") or []),
        "image_ref_count": len(image_refs),
    }


def _summarize_quality(quality: Any) -> dict[str, Any] | None:
    if not isinstance(quality, dict):
        return None
    warnings = [warning for warning in quality.get("warnings") or [] if isinstance(warning, dict)]
    return {
        "warning_count": len(warnings),
        "warning_codes": [warning.get("code") for warning in warnings],
        "coverage": quality.get("coverage"),
    }
