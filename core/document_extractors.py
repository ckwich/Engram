"""No-write local document extractor adapters for document disassembly."""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from core.document_artifacts import build_document_artifact_manifest
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
    page_limit = min(page_count, normalized_max_pages) if normalized_max_pages else page_count

    text_args = ["-layout", "-enc", "UTF-8"]
    if page_limit:
        text_args.extend(["-f", "1", "-l", str(page_limit)])
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
    if page_limit:
        image_args.extend(["-f", "1", "-l", str(page_limit)])
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
    pages = _page_records(page_count, page_limit, page_texts, image_counts)
    image_pages = [page for page, count in sorted(image_counts.items()) if count > 0 and (not page_limit or page <= page_limit)]
    no_text_pages = [page["page_number"] for page in pages if page["text_status"] == "no_text"]
    low_text_pages = [page["page_number"] for page in pages if page["text_status"] == "low_text"]
    text_content = "\f".join(page_texts[:page_limit or len(page_texts)])
    title = info.get("title") or path.stem

    payload = {
        "schema_version": DOCUMENT_DISASSEMBLY_SCHEMA_VERSION,
        "record_type": "document_disassembly_preview",
        "write_performed": False,
        "active_memory_write_performed": False,
        "source": source,
        "capabilities": capabilities,
        "document": {
            "document_id": _stable_id("doc", f"{source['source_uri']}|{source['content_hash']}"),
            "title": title,
            "source_type": normalized_source_type,
            "media_type": PDF_MEDIA_TYPE,
            "content_hash": source["content_hash"],
            "page_count": page_count,
            "page_limit": page_limit or None,
            "encrypted": _parse_bool(info.get("encrypted")),
            "page_size": info.get("page size"),
            "extraction_status": "preview",
        },
        "pages": pages,
        "text": {
            "content": text_content,
            "char_count": len(text_content),
            "page_count": len(page_texts[:page_limit or len(page_texts)]),
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
    return payload


def _run_command(args: list[str], timeout_seconds: int) -> ExtractorCommandResult:
    completed = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
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
    result = runner(command, timeout_seconds)
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
    page_limit: int,
    page_texts: list[str],
    image_counts: dict[int, int],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index in range(page_limit):
        page_number = index + 1
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
    if page_count == 0 and not records:
        return []
    return records


def _normalize_max_pages(value: int | None) -> int | None:
    if value is None:
        return None
    return max(1, int(value))


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d+", str(value))
    return int(match.group(0)) if match else None


def _parse_bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"yes", "true", "1"}


def _tool_failure(tool: str, result: ExtractorCommandResult) -> dict[str, str]:
    detail = result.stderr.strip() or f"exit code {result.returncode}"
    return {
        "code": "extractor_failed",
        "message": f"{tool} failed: {detail}",
    }


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]}"
