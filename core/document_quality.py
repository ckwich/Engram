"""Deterministic no-write document quality reports."""
from __future__ import annotations

from typing import Any


DOCUMENT_QUALITY_SCHEMA_VERSION = "2026-05-12.document-quality.v1"


def build_document_quality_report(disassembly: dict[str, Any]) -> dict[str, Any]:
    """Build a no-write quality report from document disassembly evidence."""
    document = dict(disassembly.get("document") or {})
    source = dict(disassembly.get("source") or {})
    pages = list(disassembly.get("pages") or [])
    quality_seed = dict(disassembly.get("quality_seed") or {})

    page_count = int(quality_seed.get("page_count") or document.get("page_count") or len(pages))
    text_pages = [
        int(page.get("page_number"))
        for page in pages
        if page.get("text_status") == "text" and page.get("page_number") is not None
    ]
    no_text_pages = _page_list(quality_seed.get("no_text_pages")) or [
        int(page.get("page_number"))
        for page in pages
        if page.get("text_status") == "no_text" and page.get("page_number") is not None
    ]
    low_text_pages = _page_list(quality_seed.get("low_text_pages")) or [
        int(page.get("page_number"))
        for page in pages
        if page.get("text_status") == "low_text" and page.get("page_number") is not None
    ]
    image_pages = _page_list(quality_seed.get("image_pages")) or [
        int(page.get("page_number"))
        for page in pages
        if int(page.get("image_count") or 0) > 0 and page.get("page_number") is not None
    ]
    visual_review_pages = _page_list(quality_seed.get("visual_review_needed_pages")) or [
        int(page.get("page_number"))
        for page in pages
        if page.get("visual_review_needed") and page.get("page_number") is not None
    ]
    failed_pages = _page_list(quality_seed.get("failed_pages"))
    table_candidate_pages = _page_list(quality_seed.get("table_candidate_pages"))
    unsupported_capabilities = [
        str(item) for item in quality_seed.get("unsupported_capabilities") or [] if str(item).strip()
    ]

    ratio_denominator = len(pages) or page_count
    coverage = {
        "page_count": page_count,
        "pages_reported": len(pages),
        "text_page_count": len(text_pages),
        "low_text_page_count": len(low_text_pages),
        "no_text_page_count": len(no_text_pages),
        "image_page_count": len(image_pages),
        "visual_review_needed_page_count": len(visual_review_pages),
        "failed_page_count": len(failed_pages),
        "text_page_ratio": round(len(text_pages) / ratio_denominator, 3) if ratio_denominator else 0.0,
    }
    warnings = _warnings(
        no_text_pages=no_text_pages,
        low_text_pages=low_text_pages,
        image_pages=image_pages,
        visual_review_pages=visual_review_pages,
        failed_pages=failed_pages,
        table_candidate_pages=table_candidate_pages,
        unsupported_capabilities=unsupported_capabilities,
    )
    return {
        "schema_version": DOCUMENT_QUALITY_SCHEMA_VERSION,
        "record_type": "document_quality_report",
        "status": "warn" if warnings else "pass",
        "document_id": document.get("document_id"),
        "document_title": document.get("title"),
        "source_uri": source.get("source_uri"),
        "source_hash": source.get("content_hash"),
        "coverage": coverage,
        "warnings": warnings,
        "recommended_next_tools": _recommended_next_tools(warnings),
        "write_policy": "read_only",
        "write_performed": False,
        "active_memory_write_performed": False,
        "error": None,
    }


def _warnings(
    *,
    no_text_pages: list[int],
    low_text_pages: list[int],
    image_pages: list[int],
    visual_review_pages: list[int],
    failed_pages: list[int],
    table_candidate_pages: list[int],
    unsupported_capabilities: list[str],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    if no_text_pages:
        warnings.append(_page_warning("no_text_pages", "high", no_text_pages, "Pages have no extracted text."))
    if low_text_pages:
        warnings.append(_page_warning("low_text_pages", "medium", low_text_pages, "Pages have little extracted text."))
    if image_pages:
        warnings.append(_page_warning("image_heavy_pages", "medium", image_pages, "Pages contain image artifacts."))
    if visual_review_pages:
        warnings.append(
            _page_warning(
                "visual_review_needed",
                "medium",
                visual_review_pages,
                "Pages need OCR, vision, or human review before claims are trusted.",
            )
        )
    if failed_pages:
        warnings.append(_page_warning("failed_pages", "high", failed_pages, "Pages failed extraction."))
    if table_candidate_pages:
        warnings.append(
            _page_warning(
                "table_candidates",
                "medium",
                table_candidate_pages,
                "Pages may contain tables that need structured extraction.",
            )
        )
    if unsupported_capabilities:
        warnings.append(
            {
                "code": "unsupported_capabilities",
                "severity": "medium",
                "capabilities": unsupported_capabilities,
                "message": "The current extractor did not provide requested capabilities.",
                "recommended_next": "Use an external adapter or agent-native review for the missing capabilities.",
            }
        )
    return warnings


def _page_warning(code: str, severity: str, pages: list[int], message: str) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "page_numbers": pages,
        "message": message,
        "recommended_next": "Review page evidence before promotion.",
    }


def _recommended_next_tools(warnings: list[dict[str, Any]]) -> list[str]:
    if not warnings:
        return ["prepare_document_draft"]
    return [
        "prepare_visual_extraction_request",
        "preview_visual_extraction",
        "prepare_document_draft",
    ]


def _page_list(value: Any) -> list[int]:
    if not value:
        return []
    pages: list[int] = []
    for item in value:
        try:
            page = int(item)
        except (TypeError, ValueError):
            continue
        if page > 0:
            pages.append(page)
    return sorted(set(pages))
