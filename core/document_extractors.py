"""No-write local document extractor adapters for document disassembly."""
from __future__ import annotations

import hashlib
import base64
import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from core.document_artifacts import build_document_artifact_manifest
from core.document_intelligence import prepare_document_record, prepare_visual_extraction_request
from core.document_quality import build_document_quality_report


DOCUMENT_DISASSEMBLY_SCHEMA_VERSION = "2026-05-12.document-disassembly.v1"
PDF_MEDIA_TYPE = "application/pdf"
PDF_TOOLS = ("pdfinfo", "pdftotext", "pdfimages")
TEXT_PAGE_THRESHOLD_CHARS = 40


@dataclass(frozen=True)
class ExtractorCommandResult:
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[list[str], int], ExtractorCommandResult]


def prepare_document_disassembly(
    *,
    source_path: str | Path,
    source_type: str | None = None,
    max_pages: int | None = None,
    page_range: str | None = None,
    resume_token: str | None = None,
    tool_paths: dict[str, str | None] | None = None,
    runner: CommandRunner | None = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Prepare a local PDF page/text/image inventory without writing memory."""
    path = Path(source_path).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise ValueError(f"source_path does not exist or is not a file: {source_path}")

    normalized_source_type = _source_type(path, source_type)
    if normalized_source_type != "pdf":
        raise ValueError("prepare_document_disassembly currently supports source_type='pdf' only")

    normalized_timeout = max(1, min(int(timeout_seconds), 600))
    normalized_max_pages = _normalize_max_pages(max_pages)
    source = _source_record(path, normalized_source_type)
    resume_state = _decode_resume_token(resume_token)
    if resume_state and resume_state.get("source_hash") != source["content_hash"]:
        raise ValueError("resume_token source hash does not match source_path")
    capabilities = _resolve_pdf_tools(tool_paths)
    missing = [tool for tool in PDF_TOOLS if not capabilities[tool]["available"]]
    if missing:
        return _base_payload(
            source=source,
            capabilities=capabilities,
            error={
                "code": "missing_extractor",
                "message": f"Missing local PDF tools: {', '.join(missing)}",
            },
        )

    command_runner = runner or _run_command
    receipts: list[dict[str, Any]] = []
    pdfinfo = _run_pdf_tool(command_runner, capabilities["pdfinfo"]["path"], [str(path)], normalized_timeout, receipts)
    if pdfinfo.returncode != 0:
        return _base_payload(
            source=source,
            capabilities=capabilities,
            extraction_receipts=receipts,
            error=_tool_failure("pdfinfo", pdfinfo),
        )

    info = _parse_pdfinfo(pdfinfo.stdout)
    page_count = _parse_int(info.get("pages")) or 0
    page_start, page_end = _page_window(
        page_count=page_count,
        max_pages=normalized_max_pages,
        page_range=page_range,
        resume_state=resume_state,
    )
    page_limit = page_end
    page_batch_count = max(page_end - page_start + 1, 0) if page_count else 0

    text_args = ["-layout", "-enc", "UTF-8"]
    if page_batch_count:
        text_args.extend(["-f", str(page_start), "-l", str(page_end)])
    text_args.extend([str(path), "-"])
    text_result = _run_pdf_tool(command_runner, capabilities["pdftotext"]["path"], text_args, normalized_timeout, receipts)
    if text_result.returncode != 0:
        return _base_payload(
            source=source,
            capabilities=capabilities,
            extraction_receipts=receipts,
            error=_tool_failure("pdftotext", text_result),
        )

    image_args: list[str] = []
    if page_batch_count:
        image_args.extend(["-f", str(page_start), "-l", str(page_end)])
    image_args.extend(["-list", str(path)])
    image_result = _run_pdf_tool(command_runner, capabilities["pdfimages"]["path"], image_args, normalized_timeout, receipts)
    if image_result.returncode != 0:
        return _base_payload(
            source=source,
            capabilities=capabilities,
            extraction_receipts=receipts,
            error=_tool_failure("pdfimages", image_result),
        )

    page_texts = _split_pdf_text_pages(text_result.stdout)
    image_counts = _parse_pdfimages_pages(image_result.stdout)
    pages = _page_records(page_count, page_start, page_end, page_texts, image_counts)
    image_pages = [
        page
        for page, count in sorted(image_counts.items())
        if count > 0 and page_start <= page <= page_end
    ]
    no_text_pages = [page["page_number"] for page in pages if page["text_status"] == "no_text"]
    low_text_pages = [page["page_number"] for page in pages if page["text_status"] == "low_text"]
    text_content = "\f".join(page_texts[:page_batch_count or len(page_texts)])
    title = info.get("title") or path.stem
    document_record = prepare_document_record(
        title=title,
        source_uri=source["source_uri"],
        source_type=normalized_source_type,
        content_hash=source["content_hash"],
        media_type=PDF_MEDIA_TYPE,
    )
    resume = _resume_payload(
        source_hash=source["content_hash"],
        page_count=page_count,
        page_start=page_start,
        page_end=page_end,
    )

    payload = {
        "schema_version": DOCUMENT_DISASSEMBLY_SCHEMA_VERSION,
        "record_type": "document_disassembly_preview",
        "status": "partial" if resume["has_more"] else "ok",
        "write_policy": "preview_only",
        "write_performed": False,
        "active_memory_write_performed": False,
        "source": source,
        "capabilities": capabilities,
        "document": {
            "document_id": document_record["document_id"],
            "title": title,
            "source_type": normalized_source_type,
            "media_type": PDF_MEDIA_TYPE,
            "content_hash": source["content_hash"],
            "page_count": page_count,
            "page_limit": page_limit or None,
            "pages_returned": page_batch_count,
            "page_range": {"start": page_start, "end": page_end} if page_batch_count else None,
            "encrypted": _parse_bool(info.get("encrypted")),
            "page_size": info.get("page size"),
            "extraction_status": "preview",
        },
        "pages": pages,
        "text": {
            "content": text_content,
            "char_count": len(text_content),
            "page_count": len(page_texts[:page_batch_count or len(page_texts)]),
            "page_start": page_start,
            "page_end": page_end,
            "extractor": "pdftotext",
        },
        "image_inventory": {
            "image_count": sum(image_counts.values()),
            "pages_with_images": image_pages,
            "extractor": "pdfimages",
        },
        "quality_seed": {
            "page_count": page_count,
            "pages_reported": len(pages),
            "text_pages": [page["page_number"] for page in pages if page["text_status"] == "text"],
            "low_text_pages": low_text_pages,
            "no_text_pages": no_text_pages,
            "image_pages": image_pages,
            "visual_review_needed_pages": [
                page["page_number"] for page in pages if page["visual_review_needed"]
            ],
        },
        "extraction_receipts": receipts,
        "resume": resume,
        "promotion_guidance": {
            "default_action": "review_disassembly_before_document_draft",
            "auto_promote": False,
            "next_tools": [
                "preview_document_extraction",
                "prepare_visual_extraction_request",
                "prepare_document_draft",
            ],
        },
        "error": None,
    }
    payload["quality_report"] = build_document_quality_report(payload)
    payload["artifact_manifest"] = build_document_artifact_manifest(payload)
    payload["artifact_manifest"]["resume"]["page_range"] = payload["document"]["page_range"]
    payload["artifact_manifest"]["resume"]["merge_strategy"] = "page_range_manifest_merge"
    payload["artifact_manifest"]["resume"]["resume_token"] = resume["resume_token"]
    visual_candidates, visual_request_arguments, visual_request = _visual_evidence_plan(payload)
    payload["visual_artifact_candidates"] = visual_candidates
    payload["visual_extraction_request_arguments"] = visual_request_arguments
    payload["visual_extraction_request"] = visual_request
    return payload


def _run_command(args: list[str], timeout_seconds: int) -> ExtractorCommandResult:
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return ExtractorCommandResult(
            returncode=124,
            stdout=stdout,
            stderr=f"{Path(args[0]).stem.lower()} timed out after {timeout_seconds} seconds",
        )
    return ExtractorCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


def _run_pdf_tool(
    runner: CommandRunner,
    tool_path: str,
    args: list[str],
    timeout_seconds: int,
    receipts: list[dict[str, Any]],
) -> ExtractorCommandResult:
    started = time.perf_counter()
    command = [tool_path, *args]
    try:
        result = runner(command, timeout_seconds)
    except subprocess.TimeoutExpired:
        result = ExtractorCommandResult(
            returncode=124,
            stdout="",
            stderr=f"{Path(tool_path).stem.lower()} timed out after {timeout_seconds} seconds",
        )
    receipts.append(
        {
            "tool": Path(tool_path).stem.lower(),
            "command": [Path(tool_path).name, *args],
            "returncode": result.returncode,
            "stderr": result.stderr,
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        }
    )
    return result


def _resolve_pdf_tools(tool_paths: dict[str, str | None] | None) -> dict[str, dict[str, Any]]:
    configured = tool_paths or {}
    capabilities: dict[str, dict[str, Any]] = {}
    for tool in PDF_TOOLS:
        explicit = configured.get(tool) if tool in configured else shutil.which(tool)
        path = str(explicit) if explicit else None
        capabilities[tool] = {
            "available": path is not None,
            "path": path,
        }
    return capabilities


def _source_type(path: Path, source_type: str | None) -> str:
    if source_type and str(source_type).strip():
        return str(source_type).strip().lower().lstrip(".")
    return path.suffix.lower().lstrip(".")


def _source_record(path: Path, source_type: str) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "source_uri": path.as_uri(),
        "path": str(path),
        "source_type": source_type,
        "media_type": PDF_MEDIA_TYPE,
        "content_hash": "sha256:" + hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
    }


def _base_payload(
    *,
    source: dict[str, Any],
    capabilities: dict[str, Any],
    extraction_receipts: list[dict[str, Any]] | None = None,
    error: dict[str, str],
) -> dict[str, Any]:
    return {
        "schema_version": DOCUMENT_DISASSEMBLY_SCHEMA_VERSION,
        "record_type": "document_disassembly_preview",
        "write_policy": "preview_only",
        "write_performed": False,
        "active_memory_write_performed": False,
        "source": source,
        "capabilities": capabilities,
        "document": None,
        "pages": [],
        "text": None,
        "image_inventory": None,
        "quality_seed": None,
        "extraction_receipts": extraction_receipts or [],
        "promotion_guidance": {
            "default_action": "resolve_extractor_error_before_draft",
            "auto_promote": False,
        },
        "error": error,
    }


def _parse_pdfinfo(stdout: str) -> dict[str, str]:
    info: dict[str, str] = {}
    for line in stdout.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        info[key.strip().lower()] = value.strip()
    return info


def _split_pdf_text_pages(stdout: str) -> list[str]:
    pages = stdout.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages or [stdout]


def _parse_pdfimages_pages(stdout: str) -> dict[int, int]:
    counts: dict[int, int] = {}
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped or not stripped[0].isdigit():
            continue
        parts = re.split(r"\s+", stripped)
        page = _parse_int(parts[0])
        if page is None:
            continue
        counts[page] = counts.get(page, 0) + 1
    return counts


def _page_records(
    page_count: int,
    page_start: int,
    page_end: int,
    page_texts: list[str],
    image_counts: dict[int, int],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if page_count <= 0 or page_end < page_start:
        return []
    for page_number in range(page_start, page_end + 1):
        index = page_number - page_start
        text = page_texts[index] if index < len(page_texts) else ""
        non_whitespace = len(re.sub(r"\s+", "", text))
        if non_whitespace == 0:
            text_status = "no_text"
        elif non_whitespace < TEXT_PAGE_THRESHOLD_CHARS:
            text_status = "low_text"
        else:
            text_status = "text"
        image_count = image_counts.get(page_number, 0)
        records.append(
            {
                "page_number": page_number,
                "text_chars": len(text),
                "non_whitespace_chars": non_whitespace,
                "text_status": text_status,
                "image_count": image_count,
                "visual_review_needed": text_status != "text" or image_count > 0,
            }
        )
    return records


def _visual_evidence_plan(
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any] | None]:
    document = dict(payload.get("document") or {})
    source = dict(payload.get("source") or {})
    artifact_manifest = dict(payload.get("artifact_manifest") or {})
    raw_source = dict((artifact_manifest.get("artifacts") or {}).get("raw_source") or {})
    source_artifact_id = raw_source.get("ref")
    pages = [page for page in payload.get("pages") or [] if page.get("visual_review_needed")]
    if not pages or not source_artifact_id:
        return [], None, None

    candidates: list[dict[str, Any]] = []
    image_refs: list[dict[str, Any]] = []
    for page in pages:
        page_number = int(page.get("page_number"))
        source_ref = {
            "source_uri": source.get("source_uri"),
            "content_hash": source.get("content_hash"),
            "source_artifact_id": source_artifact_id,
            "source_artifact_ref": source_artifact_id,
            "page": page_number,
            "page_number": page_number,
            "artifact_type": "page_crop",
            "text_status": page.get("text_status"),
            "image_count": int(page.get("image_count") or 0),
        }
        candidate_id = _readable_stable_id(
            "vis_candidate",
            f"{document.get('document_id')}|{page_number}|{source_artifact_id}|page_crop",
            document.get("document_id"),
            f"page_{page_number}",
            "page_crop",
        )
        candidates.append(
            {
                "record_type": "visual_artifact_candidate",
                "candidate_id": candidate_id,
                "document_id": document.get("document_id"),
                "artifact_type": "page_crop",
                "page_number": page_number,
                "coordinates": None,
                "source_artifact_id": source_artifact_id,
                "source_ref": source_ref,
                "extractor": {
                    "id": "engram-local-pdf-disassembly",
                    "kind": "pdf",
                    "external_framework_required": False,
                },
                "confidence": None,
                "review_status": "candidate",
                "active_memory_write_performed": False,
                "promotion_required": True,
                "next_tool": "prepare_visual_extraction_request",
            }
        )
        image_refs.append(source_ref)

    document_record = prepare_document_record(
        title=str(document.get("title") or "Untitled Document"),
        source_uri=str(source.get("source_uri") or ""),
        source_type=str(document.get("source_type") or source.get("source_type") or "pdf"),
        content_hash=str(document.get("content_hash") or source.get("content_hash") or ""),
        media_type=str(document.get("media_type") or source.get("media_type") or PDF_MEDIA_TYPE),
        metadata={
            "document_id": document.get("document_id"),
            "extractor_id": "engram-local-pdf-disassembly",
            "page_count": document.get("page_count"),
            "page_limit": document.get("page_limit"),
        },
    )
    request_arguments = {
        "document_record": document_record,
        "image_refs": image_refs,
        "requested_capabilities": [
            "ocr_text",
            "figure_description",
            "table_structure",
            "diagram_description",
            "caption_alt_text",
        ],
        "extractor_id": "engram-visual-request",
        "extractor_kind": "ocr_vision",
        "instructions": (
            "Review low-text, no-text, or image-bearing PDF pages before document draft promotion; "
            "return OCR blocks, figures, tables, captions, diagrams, and page-crop evidence with page "
            "numbers, coordinates when available, confidence, extractor id, and source artifact id."
        ),
    }
    visual_request = prepare_visual_extraction_request(**request_arguments)
    return candidates, request_arguments, visual_request


def _normalize_max_pages(value: int | None) -> int | None:
    if value is None:
        return None
    return max(1, int(value))


def _page_window(
    *,
    page_count: int,
    max_pages: int | None,
    page_range: str | None,
    resume_state: dict[str, Any] | None,
) -> tuple[int, int]:
    if page_range and resume_state:
        raise ValueError("page_range and resume_token cannot be used together")
    if page_count <= 0:
        return 1, 0
    if resume_state:
        start = int(resume_state.get("next_page") or 1)
        if start < 1 or start > page_count + 1:
            raise ValueError("resume_token next_page is outside document bounds")
        if start > page_count:
            return page_count, page_count
        end = page_count
    elif page_range:
        start, end = _parse_page_range(page_range)
        if start > page_count:
            raise ValueError("page_range starts after the document page count")
        end = min(end, page_count)
    else:
        start, end = 1, page_count
    if max_pages is not None:
        end = min(end, start + max_pages - 1)
    if end < start:
        raise ValueError("page_range end must be greater than or equal to start")
    return start, end


def _parse_page_range(value: str) -> tuple[int, int]:
    text = str(value or "").strip()
    if not text:
        raise ValueError("page_range cannot be blank")
    if "-" in text:
        start_text, end_text = text.split("-", 1)
    else:
        start_text, end_text = text, text
    try:
        start = int(start_text.strip())
        end = int(end_text.strip())
    except ValueError as exc:
        raise ValueError("page_range must use positive page numbers such as '1-5'") from exc
    if start <= 0 or end <= 0:
        raise ValueError("page_range pages must be positive")
    if end < start:
        raise ValueError("page_range end must be greater than or equal to start")
    return start, end


def _resume_payload(
    *,
    source_hash: str,
    page_count: int,
    page_start: int,
    page_end: int,
) -> dict[str, Any]:
    has_more = page_count > 0 and page_end < page_count
    next_page = page_end + 1 if has_more else None
    token_payload = {
        "source_hash": source_hash,
        "page_count": page_count,
        "next_page": next_page,
    }
    return {
        "has_more": has_more,
        "page_count": page_count,
        "page_range": {"start": page_start, "end": page_end} if page_count else None,
        "next_page": next_page,
        "resume_token": _encode_resume_token(token_payload) if has_more else None,
        "merge_strategy": "page_range_manifest_merge",
    }


def _encode_resume_token(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_resume_token(value: str | None) -> dict[str, Any] | None:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    padded = text + ("=" * ((4 - len(text) % 4) % 4))
    try:
        decoded = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception as exc:
        raise ValueError("resume_token is invalid") from exc
    if not isinstance(decoded, dict):
        raise ValueError("resume_token is invalid")
    return decoded


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else None


def _parse_bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"yes", "true", "1"}


def _tool_failure(tool: str, result: ExtractorCommandResult) -> dict[str, str]:
    detail = result.stderr.strip() or f"exit code {result.returncode}"
    if result.returncode == 124:
        return {
            "code": "tool_timeout",
            "message": detail or f"{tool} timed out",
        }
    return {
        "code": "extractor_failed",
        "message": f"{tool} failed: {detail}",
    }


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]}"


def _readable_stable_id(prefix: str, seed: str, *readable_parts: Any) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8]
    label = _slugify("_".join(str(part) for part in readable_parts if part not in (None, "")), max_length=96)
    if not label:
        return f"{prefix}_{digest}"
    return f"{prefix}_{label}_{digest}"


def _slugify(value: str, *, max_length: int = 80) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", str(value).strip().lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)
    return slug[:max_length].strip("_")
