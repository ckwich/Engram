"""Local no-write workbench for document visual/OCR/table coverage."""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from core.document_coverage import (
    VISUAL_CAPABILITIES_REQUIRING_DESCRIPTION,
    capabilities_for_image_ref,
    page_number_from_ref,
)


DOCUMENT_COVERAGE_WORKBENCH_SCHEMA_VERSION = "2026-05-17.document-coverage-workbench.v1"
PDF_MEDIA_TYPE = "application/pdf"
WORKBENCH_EXTRACTOR_ID = "engram-local-coverage-workbench"


@dataclass(frozen=True)
class CoverageCommandResult:
    returncode: int
    stdout: str
    stderr: str


CoverageCommandRunner = Callable[[list[str], int], CoverageCommandResult]
TableDetector = Callable[[dict[str, Any]], dict[str, Any] | None]


def prepare_document_coverage_workbench(
    *,
    source_path: str | Path,
    document_record: dict[str, Any] | None = None,
    visual_request: dict[str, Any] | None = None,
    image_refs: list[dict[str, Any]] | None = None,
    output_dir: str | Path | None = None,
    render_pages: bool = True,
    run_ocr: bool = False,
    run_table_detection: bool = False,
    max_pages: int | None = None,
    tool_paths: dict[str, str | None] | None = None,
    runner: CoverageCommandRunner | None = None,
    table_detector: TableDetector | None = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    """Prepare local review work packets without promoting memory or graph data."""
    path = Path(source_path).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise ValueError(f"source_path does not exist or is not a file: {source_path}")
    normalized_timeout = max(1, min(int(timeout_seconds), 600))
    source = _source_record(path)
    normalized_document = _document_record(document_record, source=source)
    normalized_request = _visual_request(
        visual_request,
        image_refs=image_refs,
        document_id=normalized_document["document_id"],
        source_uri=source["source_uri"],
    )
    refs = _limited_refs(normalized_request["image_refs"], max_pages=max_pages)
    workbench_id = _workbench_id(source, normalized_document, normalized_request, refs)
    root = _output_root(output_dir, workbench_id)
    capabilities = _resolve_capabilities(tool_paths, table_detector=table_detector)
    command_runner = runner or _run_command
    unavailable_receipts: list[dict[str, Any]] = []
    skipped_receipts: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    page_tasks: list[dict[str, Any]] = []
    local_artifact_write_performed = False

    for ref in refs:
        page_number = page_number_from_ref(ref)
        required = capabilities_for_image_ref(ref, normalized_request.get("requested_capabilities"))
        task: dict[str, Any] = {
            "page_number": page_number,
            "source_ref": dict(ref),
            "required_capabilities": required,
        }
        render = _render_page(
            path=path,
            output_root=root,
            page_number=page_number,
            enabled=render_pages,
            capabilities=capabilities,
            runner=command_runner,
            timeout_seconds=normalized_timeout,
            unavailable_receipts=unavailable_receipts,
        )
        task["render"] = render
        if render.get("artifact_ref") is not None:
            local_artifact_write_performed = True

        ocr, ocr_observation = _ocr_task(
            ref=ref,
            required_capabilities=required,
            render=render,
            enabled=run_ocr,
            capabilities=capabilities,
            runner=command_runner,
            timeout_seconds=normalized_timeout,
            unavailable_receipts=unavailable_receipts,
            skipped_receipts=skipped_receipts,
        )
        task["ocr"] = ocr
        if ocr_observation is not None:
            observations.append(ocr_observation)

        table, table_observation = _table_task(
            ref=ref,
            required_capabilities=required,
            render=render,
            enabled=run_table_detection,
            detector=table_detector,
            unavailable_receipts=unavailable_receipts,
            skipped_receipts=skipped_receipts,
            page_task=task,
        )
        task["table"] = table
        if table_observation is not None:
            observations.append(table_observation)

        task["visual_review"] = _visual_review_task(required, render)
        task["observation_count"] = int(ocr_observation is not None) + int(table_observation is not None)
        page_tasks.append(task)

    status = "partial" if unavailable_receipts else "ok"
    return {
        "schema_version": DOCUMENT_COVERAGE_WORKBENCH_SCHEMA_VERSION,
        "record_type": "document_coverage_workbench",
        "workbench_id": workbench_id,
        "status": status,
        "write_policy": "local_artifact_preview_only",
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "local_artifact_write_performed": local_artifact_write_performed,
        "source": source,
        "document_record": normalized_document,
        "visual_request": normalized_request,
        "capabilities": capabilities,
        "page_tasks": page_tasks,
        "observations": observations,
        "preview_visual_extraction_arguments": {
            "document_record": normalized_document,
            "observations": observations,
            "extractor_id": WORKBENCH_EXTRACTOR_ID,
            "extractor_kind": "agent_native",
            "visual_request": normalized_request,
        },
        "unavailable_receipts": unavailable_receipts,
        "skipped_receipts": skipped_receipts,
        "receipts": {
            "page_task_count": len(page_tasks),
            "rendered_page_count": sum(1 for task in page_tasks if task["render"]["status"] == "ready"),
            "ocr_observation_count": sum(1 for item in observations if item.get("artifact_type") == "ocr_block"),
            "table_observation_count": sum(1 for item in observations if item.get("artifact_type") == "table"),
            "observation_count": len(observations),
            "unavailable_count": len(unavailable_receipts),
            "skipped_count": len(skipped_receipts),
        },
        "next_actions": _next_actions(unavailable_receipts=unavailable_receipts, observations=observations),
        "error": None,
    }


def _run_command(args: list[str], timeout_seconds: int) -> CoverageCommandResult:
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
        return CoverageCommandResult(
            returncode=124,
            stdout=stdout,
            stderr=f"{Path(args[0]).name} timed out after {timeout_seconds} seconds",
        )
    return CoverageCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


def _render_page(
    *,
    path: Path,
    output_root: Path,
    page_number: int | None,
    enabled: bool,
    capabilities: dict[str, Any],
    runner: CoverageCommandRunner,
    timeout_seconds: int,
    unavailable_receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    if page_number is None:
        return {"status": "unavailable", "reason": "page_number is required", "artifact_ref": None}
    if not enabled:
        return {"status": "skipped", "reason": "render_pages is false", "artifact_ref": None}
    renderer = capabilities["pdftoppm"]
    if not renderer["available"]:
        _add_receipt(
            unavailable_receipts,
            code="page_renderer_unavailable",
            message="pdftoppm is required to render reviewable page images.",
            page_number=page_number,
            tool="pdftoppm",
        )
        return {"status": "unavailable", "reason": "pdftoppm unavailable", "artifact_ref": None}

    page_dir = output_root / "pages"
    page_dir.mkdir(parents=True, exist_ok=True)
    prefix = page_dir / f"page_{page_number:04d}"
    started = time.perf_counter()
    result = runner(
        [
            renderer["path"],
            "-f",
            str(page_number),
            "-l",
            str(page_number),
            "-r",
            "144",
            "-png",
            "-singlefile",
            str(path),
            str(prefix),
        ],
        timeout_seconds,
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    image_path = prefix.with_suffix(".png")
    if result.returncode != 0 or not image_path.exists():
        _add_receipt(
            unavailable_receipts,
            code="page_render_failed",
            message=result.stderr or "pdftoppm did not create a page image.",
            page_number=page_number,
            tool="pdftoppm",
        )
        return {
            "status": "failed",
            "reason": result.stderr or "page image was not created",
            "artifact_ref": None,
            "elapsed_ms": elapsed_ms,
        }
    return {
        "status": "ready",
        "artifact_ref": _render_artifact_ref(image_path, page_number=page_number),
        "elapsed_ms": elapsed_ms,
    }


def _ocr_task(
    *,
    ref: dict[str, Any],
    required_capabilities: list[str],
    render: dict[str, Any],
    enabled: bool,
    capabilities: dict[str, Any],
    runner: CoverageCommandRunner,
    timeout_seconds: int,
    unavailable_receipts: list[dict[str, Any]],
    skipped_receipts: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    page_number = page_number_from_ref(ref)
    if "ocr_text" not in required_capabilities:
        return {"status": "not_required"}, None
    if not enabled:
        _add_receipt(
            skipped_receipts,
            code="ocr_not_requested",
            message="OCR was requested by coverage but run_ocr is false.",
            page_number=page_number,
        )
        return {"status": "skipped", "reason": "run_ocr is false"}, None
    ocr = capabilities["tesseract"]
    if not ocr["available"]:
        _add_receipt(
            unavailable_receipts,
            code="ocr_adapter_unavailable",
            message="tesseract is required for local OCR adapter output.",
            page_number=page_number,
            tool="tesseract",
        )
        return {"status": "unavailable", "reason": "tesseract unavailable"}, None
    artifact_ref = render.get("artifact_ref") if isinstance(render.get("artifact_ref"), dict) else None
    if artifact_ref is None:
        return {"status": "unavailable", "reason": "rendered page image is required"}, None

    result = runner([ocr["path"], artifact_ref["file_path"], "stdout", "--psm", "6"], timeout_seconds)
    text = result.stdout.strip()
    if result.returncode != 0:
        _add_receipt(
            unavailable_receipts,
            code="ocr_adapter_failed",
            message=result.stderr or "tesseract failed.",
            page_number=page_number,
            tool="tesseract",
        )
        return {"status": "failed", "reason": result.stderr or "tesseract failed"}, None
    if not text:
        return {"status": "empty", "reason": "OCR returned no text"}, None
    observation = {
        "artifact_type": "ocr_block",
        "source_ref": dict(ref),
        "page_number": page_number,
        "text": text,
        "confidence": 0.75,
        "metadata": {
            "capabilities_covered": ["ocr_text"],
            "adapter": "tesseract",
            "render_artifact_ref": artifact_ref,
        },
    }
    return {"status": "ready", "observation_index": None}, observation


def _table_task(
    *,
    ref: dict[str, Any],
    required_capabilities: list[str],
    render: dict[str, Any],
    enabled: bool,
    detector: TableDetector | None,
    unavailable_receipts: list[dict[str, Any]],
    skipped_receipts: list[dict[str, Any]],
    page_task: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    page_number = page_number_from_ref(ref)
    if "table_structure" not in required_capabilities:
        return {"status": "not_required"}, None
    if not enabled:
        _add_receipt(
            skipped_receipts,
            code="table_detection_not_requested",
            message="Table coverage was requested but run_table_detection is false.",
            page_number=page_number,
        )
        return {"status": "skipped", "reason": "run_table_detection is false"}, None
    if detector is None:
        _add_receipt(
            unavailable_receipts,
            code="table_adapter_unavailable",
            message="No local table detector adapter was supplied.",
            page_number=page_number,
            tool="table_detector",
        )
        return {"status": "unavailable", "reason": "table detector unavailable"}, None

    detector_input = dict(page_task)
    detector_input["render"] = dict(render)
    result = detector(detector_input)
    if result is None:
        return {"status": "empty", "reason": "table detector returned no result"}, None
    metadata = dict(result.get("metadata") or {})
    metadata["capabilities_covered"] = sorted(
        {*[str(item) for item in metadata.get("capabilities_covered") or []], "table_structure"}
    )
    if "render_artifact_ref" not in metadata and isinstance(render.get("artifact_ref"), dict):
        metadata["render_artifact_ref"] = render["artifact_ref"]
    observation = {
        "artifact_type": "table",
        "source_ref": dict(ref),
        "page_number": page_number,
        "text": result.get("text"),
        "description": result.get("description"),
        "confidence": result.get("confidence", 0.7),
        "metadata": metadata,
    }
    return {"status": "ready", "observation_index": None}, observation


def _visual_review_task(required_capabilities: list[str], render: dict[str, Any]) -> dict[str, Any]:
    needed = sorted(set(required_capabilities) & VISUAL_CAPABILITIES_REQUIRING_DESCRIPTION)
    if not needed:
        return {"status": "not_required", "required_capabilities": []}
    artifact_ref = render.get("artifact_ref") if isinstance(render.get("artifact_ref"), dict) else None
    return {
        "status": "required",
        "required_capabilities": needed,
        "input_artifact_ref": artifact_ref,
        "return_tool": "preview_visual_extraction",
    }


def _source_record(path: Path) -> dict[str, Any]:
    return {
        "source_path": str(path),
        "source_uri": path.as_uri(),
        "source_type": "pdf",
        "media_type": PDF_MEDIA_TYPE,
        "content_hash": _file_hash(path),
    }


def _document_record(document_record: dict[str, Any] | None, *, source: dict[str, Any]) -> dict[str, Any]:
    record = dict(document_record or {})
    if not str(record.get("document_id") or "").strip():
        record["document_id"] = f"doc_{Path(source['source_path']).stem.lower().replace(' ', '_')}"
    record.setdefault("title", Path(source["source_path"]).stem)
    record.setdefault("source_uri", source["source_uri"])
    record.setdefault("source_type", "pdf")
    record.setdefault("content_hash", source["content_hash"])
    record.setdefault("media_type", PDF_MEDIA_TYPE)
    return record


def _visual_request(
    visual_request: dict[str, Any] | None,
    *,
    image_refs: list[dict[str, Any]] | None,
    document_id: str,
    source_uri: str,
) -> dict[str, Any]:
    request = dict(visual_request or {})
    refs = [dict(ref) for ref in request.get("image_refs") or image_refs or [] if isinstance(ref, dict)]
    for ref in refs:
        ref.setdefault("source_uri", source_uri)
    request["document_id"] = str(request.get("document_id") or document_id)
    request["image_refs"] = refs
    capabilities = sorted(
        {
            capability
            for ref in refs
            for capability in capabilities_for_image_ref(ref, request.get("requested_capabilities") or [])
        }
    )
    request["requested_capabilities"] = list(request.get("requested_capabilities") or capabilities)
    request.setdefault("request_id", f"vis_req_{request['document_id']}_coverage_workbench")
    return request


def _limited_refs(refs: list[dict[str, Any]], *, max_pages: int | None) -> list[dict[str, Any]]:
    if max_pages is None:
        return [dict(ref) for ref in refs]
    limit = max(0, int(max_pages))
    return [dict(ref) for ref in refs[:limit]]


def _resolve_capabilities(
    tool_paths: dict[str, str | None] | None,
    *,
    table_detector: TableDetector | None,
) -> dict[str, Any]:
    configured = dict(tool_paths or {})
    pdftoppm = configured.get("pdftoppm") if "pdftoppm" in configured else shutil.which("pdftoppm")
    tesseract = configured.get("tesseract") if "tesseract" in configured else shutil.which("tesseract")
    return {
        "pdftoppm": {
            "available": bool(pdftoppm),
            "path": pdftoppm,
            "role": "page_renderer",
        },
        "tesseract": {
            "available": bool(tesseract),
            "path": tesseract,
            "role": "ocr_text",
        },
        "table_detector": {
            "available": table_detector is not None,
            "path": None,
            "role": "table_structure",
        },
    }


def _output_root(output_dir: str | Path | None, workbench_id: str) -> Path:
    if output_dir is None:
        return Path(".engram") / "document-coverage-workbench" / workbench_id
    return Path(output_dir).expanduser().resolve()


def _workbench_id(
    source: dict[str, Any],
    document_record: dict[str, Any],
    visual_request: dict[str, Any],
    refs: list[dict[str, Any]],
) -> str:
    seed = "|".join(
        [
            str(source.get("content_hash")),
            str(document_record.get("document_id")),
            str(visual_request.get("request_id")),
            repr([(page_number_from_ref(ref), capabilities_for_image_ref(ref, visual_request.get("requested_capabilities"))) for ref in refs]),
        ]
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    document_component = _safe_id_component(str(document_record.get("document_id") or "document"))
    return f"doc_cov_workbench_{document_component}_{digest}"


def _safe_id_component(value: str) -> str:
    text = str(value or "").strip().replace("\\", "_").replace("/", "_")
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("._-")
    return (text or "document")[:80]


def _render_artifact_ref(image_path: Path, *, page_number: int) -> dict[str, Any]:
    return {
        "source_artifact_id": f"rendered_page_{page_number:04d}",
        "source_uri": image_path.resolve().as_uri(),
        "file_path": str(image_path.resolve()),
        "page_number": page_number,
        "media_type": "image/png",
        "content_hash": _file_hash(image_path),
    }


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _add_receipt(
    receipts: list[dict[str, Any]],
    *,
    code: str,
    message: str,
    page_number: int | None,
    tool: str | None = None,
) -> None:
    for receipt in receipts:
        if receipt.get("code") == code and receipt.get("tool") == tool:
            if page_number is not None and page_number not in receipt["affected_pages"]:
                receipt["affected_pages"].append(page_number)
                receipt["affected_pages"].sort()
            return
    receipts.append(
        {
            "code": code,
            "message": message,
            "tool": tool,
            "affected_pages": [page_number] if page_number is not None else [],
        }
    )


def _next_actions(*, unavailable_receipts: list[dict[str, Any]], observations: list[dict[str, Any]]) -> list[str]:
    actions = []
    if observations:
        actions.append("Pass preview_visual_extraction_arguments to preview_visual_extraction for reviewed evidence.")
    if unavailable_receipts:
        actions.append("Install or supply the missing local adapters, or return reviewed agent observations manually.")
    actions.append("Use returned page_tasks to complete figure descriptions, OCR, and table observations before promotion.")
    return actions
