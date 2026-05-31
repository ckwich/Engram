from __future__ import annotations

import hashlib
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.parse import urlparse

CONNECTOR_SCHEMA_VERSION = "2026-04-30.source-connectors.v1"
DOCUMENT_CONNECTOR_SCHEMA_VERSION = "2026-05-11.document-source-connectors.v1"
DEFAULT_INCLUDE_GLOBS = ["*.md", "*.txt", "*.rst"]
DEFAULT_DOCUMENT_INCLUDE_GLOBS = ["*.md", "*.markdown", "*.txt", "*.html", "*.htm"]
DEFAULT_MAX_FILE_SIZE_KB = 256
DEFAULT_MAX_FILES = 20
DEFAULT_MAX_SOURCE_TEXT_CHARS = 12_000
DOCUMENT_MEDIA_TYPES = {
    ".md": ("markdown", "text/markdown"),
    ".markdown": ("markdown", "text/markdown"),
    ".txt": ("text", "text/plain"),
    ".html": ("html", "text/html"),
    ".htm": ("html", "text/html"),
}
EXTERNAL_EXTRACTOR_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
EXTERNAL_EXTRACTOR_SOURCE_TYPES = {
    ".pdf": "pdf",
    ".docx": "docx",
}
EXTERNAL_EXTRACTOR_OUTPUTS = {
    ".pdf": ["markdown", "metadata", "page_images"],
    ".docx": ["markdown", "metadata"],
}
SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
}


def _normalize_globs(include_globs: list[str] | None) -> list[str]:
    globs = [item.strip() for item in include_globs or [] if item and item.strip()]
    normalized = globs or list(DEFAULT_INCLUDE_GLOBS)
    for pattern in normalized:
        if _unsafe_glob_pattern(pattern):
            raise ValueError("unsafe include_globs pattern")
    return normalized


def _unsafe_glob_pattern(pattern: str) -> bool:
    text = str(pattern or "").strip()
    if not text or "\x00" in text:
        return True
    normalized = text.replace("\\", "/")
    if normalized.startswith("/") or Path(text).is_absolute() or PureWindowsPath(text).is_absolute():
        return True
    return any(part == ".." for part in normalized.split("/"))


def _is_skipped(path: Path) -> bool:
    return any(part in SKIP_DIR_NAMES for part in path.parts)


def _candidate_files(root: Path, include_globs: list[str], max_files: int) -> tuple[list[Path], int]:
    if root.is_file():
        return [root], 0

    resolved_root = root.resolve()
    seen: set[Path] = set()
    matches: list[Path] = []
    for pattern in include_globs:
        for path in root.rglob(pattern):
            if len(matches) >= max_files:
                return sorted(matches), 1
            if path.is_symlink() or not path.is_file() or _is_skipped(path.relative_to(root)):
                continue
            resolved = path.resolve()
            try:
                resolved.relative_to(resolved_root)
            except ValueError:
                continue
            if resolved in seen:
                continue
            seen.add(resolved)
            matches.append(path)
    return sorted(matches), 0


def _file_uri(path: Path) -> str:
    try:
        return path.resolve().as_uri()
    except ValueError:
        return "file:" + str(path)


def preview_source_connector(
    *,
    connector_type: str,
    target: str,
    include_globs: list[str] | None = None,
    max_files: int = DEFAULT_MAX_FILES,
    max_file_size_kb: int = DEFAULT_MAX_FILE_SIZE_KB,
    max_source_text_chars: int = DEFAULT_MAX_SOURCE_TEXT_CHARS,
) -> dict[str, Any]:
    """Preview source items and draft arguments without storing memory."""
    normalized_type = (connector_type or "").strip().lower()
    if normalized_type != "local_path":
        raise ValueError("Only connector_type='local_path' is currently supported.")
    if not target or not str(target).strip():
        raise ValueError("target is required")

    root = Path(target).expanduser().resolve()
    if not root.exists():
        raise ValueError(f"target does not exist: {target}")

    normalized_max_files = min(max(int(max_files), 1), 200)
    normalized_size_kb = min(max(int(max_file_size_kb), 1), 4096)
    normalized_text_chars = min(max(int(max_source_text_chars), 100), 50_000)
    include_patterns = _normalize_globs(include_globs)
    candidates, fanout_omitted = _candidate_files(root, include_patterns, normalized_max_files)

    items: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    max_bytes = normalized_size_kb * 1024
    for path in candidates:
        size_bytes = path.stat().st_size
        relative_path = str(path.relative_to(root)) if root.is_dir() else path.name
        if size_bytes > max_bytes:
            omitted.append(
                {
                    "path": str(path),
                    "relative_path": relative_path,
                    "reason": "file_too_large",
                    "size_bytes": size_bytes,
                }
            )
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        draft_text = text[:normalized_text_chars]
        source_uri = _file_uri(path)
        title = path.stem.replace("_", " ").replace("-", " ").strip() or path.name
        items.append(
            {
                "path": str(path),
                "relative_path": relative_path,
                "source_uri": source_uri,
                "title": title,
                "chars": len(text),
                "truncated": len(draft_text) < len(text),
                "preview": text[:500],
                "draft_arguments": {
                    "source_text": draft_text,
                    "source_type": "local_path",
                    "source_uri": source_uri,
                },
            }
        )

    if fanout_omitted:
        omitted.append(
            {
                "path": str(root),
                "reason": "max_files_reached",
                "max_files": normalized_max_files,
            }
        )

    return {
        "schema_version": CONNECTOR_SCHEMA_VERSION,
        "connector_type": normalized_type,
        "target": str(root),
        "include_globs": include_patterns,
        "max_files": normalized_max_files,
        "max_file_size_kb": normalized_size_kb,
        "receipt": {
            "max_source_text_chars": normalized_text_chars,
            "source_text_truncated_count": sum(1 for item in items if item.get("truncated")),
        },
        "count": len(items),
        "items": items,
        "omitted": omitted,
        "write_policy": "preview_only",
        "write_performed": False,
        "active_memory_write_performed": False,
        "error": None,
    }


def preview_document_source_connector(
    *,
    connector_type: str,
    target: str,
    include_globs: list[str] | None = None,
    max_files: int = DEFAULT_MAX_FILES,
    max_file_size_kb: int = DEFAULT_MAX_FILE_SIZE_KB,
    max_source_text_chars: int = DEFAULT_MAX_SOURCE_TEXT_CHARS,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Preview local document files or URL fetch requests for no-write extraction."""
    normalized_type = (connector_type or "").strip().lower()
    if normalized_type not in {"local_path", "url"}:
        raise ValueError("Only connector_type='local_path' or 'url' is currently supported.")
    if not target or not str(target).strip():
        raise ValueError("target is required")
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    if normalized_type == "url":
        return _preview_document_url(target)

    root = Path(target).expanduser().resolve()
    if not root.exists():
        raise ValueError(f"target does not exist: {target}")

    normalized_max_files = min(max(int(max_files), 1), 200)
    normalized_size_kb = min(max(int(max_file_size_kb), 1), 4096)
    normalized_text_chars = min(max(int(max_source_text_chars), 100), 50_000)
    include_patterns = _normalize_globs(include_globs or DEFAULT_DOCUMENT_INCLUDE_GLOBS)
    candidates, fanout_omitted = _candidate_files(root, include_patterns, normalized_max_files)

    items: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    max_bytes = normalized_size_kb * 1024
    for path in candidates:
        relative_path = str(path.relative_to(root)) if root.is_dir() else path.name
        suffix = path.suffix.lower()
        if suffix in EXTERNAL_EXTRACTOR_MEDIA_TYPES:
            omitted.append(_external_extractor_omission(path, relative_path, EXTERNAL_EXTRACTOR_MEDIA_TYPES[suffix]))
            continue
        if suffix not in DOCUMENT_MEDIA_TYPES:
            omitted.append(
                {
                    "path": str(path),
                    "relative_path": relative_path,
                    "reason": "unsupported_media_type",
                    "extension": suffix,
                }
            )
            continue
        size_bytes = path.stat().st_size
        if size_bytes > max_bytes:
            omitted.append(
                {
                    "path": str(path),
                    "relative_path": relative_path,
                    "reason": "file_too_large",
                    "size_bytes": size_bytes,
                }
            )
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        source_text = text[:normalized_text_chars]
        source_type, media_type = DOCUMENT_MEDIA_TYPES[suffix]
        document_metadata = dict(metadata or {})
        document_metadata["relative_path"] = relative_path
        source_uri = _file_uri(path)
        title = path.stem.replace("_", " ").replace("-", " ").strip() or path.name
        items.append(
            {
                "path": str(path),
                "relative_path": relative_path,
                "source_uri": source_uri,
                "title": title,
                "chars": len(text),
                "truncated": len(source_text) < len(text),
                "media_type": media_type,
                "source_type": source_type,
                "document_extraction_arguments": {
                    "title": title,
                    "source_uri": source_uri,
                    "source_type": source_type,
                    "content": source_text,
                    "media_type": media_type,
                    "metadata": document_metadata,
                },
            }
        )

    if fanout_omitted:
        omitted.append(
            {
                "path": str(root),
                "reason": "max_files_reached",
                "max_files": normalized_max_files,
            }
        )

    return {
        "schema_version": DOCUMENT_CONNECTOR_SCHEMA_VERSION,
        "connector_type": normalized_type,
        "target": str(root),
        "include_globs": include_patterns,
        "max_files": normalized_max_files,
        "max_file_size_kb": normalized_size_kb,
        "count": len(items),
        "items": items,
        "omitted": omitted,
        "receipt": {
            "supported_count": len(items),
            "omitted_count": len(omitted),
            "max_source_text_chars": normalized_text_chars,
            "source_text_truncated_count": sum(1 for item in items if item.get("truncated")),
        },
        "write_policy": "preview_only",
        "write_performed": False,
        "active_memory_write_performed": False,
        "error": None,
    }


def _external_extractor_omission(path: Path, relative_path: str, media_type: str) -> dict[str, Any]:
    suffix = path.suffix.lower()
    source_uri = _file_uri(path)
    content_hash = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    local_pdf_arguments = (
        {
            "source_path": str(path),
            "source_type": "pdf",
        }
        if suffix == ".pdf"
        else None
    )
    recommended_next = (
        "use prepare_document_disassembly for local PDF inventory, or an external PDF/OCR extractor when local tools are unavailable"
        if suffix == ".pdf"
        else "use an external document extractor, then preview_document_extraction or preview_visual_extraction"
    )
    payload = {
        "path": str(path),
        "relative_path": relative_path,
        "reason": "external_extractor_required",
        "media_type": media_type,
        "recommended_next": recommended_next,
        "document_extraction_request_arguments": {
            "source_ref": {
                "source_uri": source_uri,
                "content_hash": content_hash,
                "path": str(path),
                "relative_path": relative_path,
            },
            "source_type": EXTERNAL_EXTRACTOR_SOURCE_TYPES[suffix],
            "requested_outputs": list(EXTERNAL_EXTRACTOR_OUTPUTS[suffix]),
            "extractor_id": "engram-document-request",
            "extractor_kind": "external_document",
            "instructions": "Extract text and page images as needed, then feed reviewed outputs into preview_document_extraction or preview_visual_extraction.",
        },
    }
    if local_pdf_arguments is not None:
        payload["document_disassembly_arguments"] = local_pdf_arguments
    return payload


def _preview_document_url(target: str) -> dict[str, Any]:
    source_uri = target.strip()
    parsed = urlparse(source_uri)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("target must be an http or https URL")
    return {
        "schema_version": DOCUMENT_CONNECTOR_SCHEMA_VERSION,
        "connector_type": "url",
        "target": source_uri,
        "include_globs": [],
        "max_files": 1,
        "max_file_size_kb": DEFAULT_MAX_FILE_SIZE_KB,
        "count": 0,
        "items": [],
        "omitted": [
            {
                "source_uri": source_uri,
                "reason": "external_fetch_required",
                "media_type": "text/html",
                "recommended_next": "fetch and normalize the URL externally, then prepare_document_extraction_result or preview_document_extraction",
                "document_extraction_request_arguments": {
                    "source_ref": {
                        "source_uri": source_uri,
                    },
                    "source_type": "url",
                    "requested_outputs": ["markdown", "metadata"],
                    "extractor_id": "engram-document-request",
                    "extractor_kind": "external_document",
                    "instructions": "Fetch the URL, preserve source_uri provenance, normalize readable content to markdown, then feed reviewed output into prepare_document_extraction_result.",
                },
            }
        ],
        "receipt": {
            "supported_count": 0,
            "omitted_count": 1,
            "max_source_text_chars": DEFAULT_MAX_SOURCE_TEXT_CHARS,
            "source_text_truncated_count": 0,
        },
        "write_policy": "preview_only",
        "write_performed": False,
        "active_memory_write_performed": False,
        "error": None,
    }
