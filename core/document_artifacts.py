"""Portable content-addressed document artifact manifests."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from core.memory_os.runtime_paths import resolve_data_root


DOCUMENT_ARTIFACT_SCHEMA_VERSION = "2026-05-12.document-artifacts.v1"
DEFAULT_ARTIFACT_ROOT_NAME = "document_artifacts"


def build_document_artifact_manifest(
    disassembly: dict[str, Any],
    *,
    data_root: str | Path | None = None,
) -> dict[str, Any]:
    """Build a no-write artifact manifest from document disassembly evidence."""
    source = dict(disassembly.get("source") or {})
    document = dict(disassembly.get("document") or {})
    pages = list(disassembly.get("pages") or [])
    text = disassembly.get("text") if isinstance(disassembly.get("text"), dict) else {}
    text_page_start = int(text.get("page_start") or 1)
    text_pages = _split_text_pages(text.get("content") or "")
    failed_pages = _page_set((disassembly.get("quality_seed") or {}).get("failed_pages"))
    root = _data_root(data_root)
    source_hash = _require_hash(source.get("content_hash") or document.get("content_hash"))
    raw_source = _artifact_record(
        artifact_type="raw_source",
        content_hash=source_hash,
        suffix=_suffix_for_media(source.get("media_type"), source.get("source_type")),
        metadata={
            "source_uri": source.get("source_uri"),
            "size_bytes": source.get("size_bytes"),
        },
    )
    page_records: list[dict[str, Any]] = []
    states: dict[str, str] = {}
    for page in pages:
        page_number = int(page.get("page_number"))
        text_index = page_number - text_page_start
        text = text_pages[text_index] if 0 <= text_index < len(text_pages) else ""
        text_artifact = None
        if text.strip():
            text_artifact = _artifact_record(
                artifact_type="page_text",
                content_hash=_hash_text(text),
                suffix=".txt",
                metadata={"page_number": page_number},
            )
        state = _page_state(page, failed_pages, text_artifact)
        states[str(page_number)] = state
        page_records.append(
            {
                "page_number": page_number,
                "state": state,
                "text_artifact": text_artifact,
                "visual_artifacts_expected": bool(page.get("visual_review_needed")),
                "image_count": int(page.get("image_count") or 0),
            }
        )
    return {
        "schema_version": DOCUMENT_ARTIFACT_SCHEMA_VERSION,
        "record_type": "document_artifact_manifest",
        "manifest_id": _manifest_id(source_hash, document.get("document_id")),
        "document_id": document.get("document_id"),
        "artifact_root": str((root / DEFAULT_ARTIFACT_ROOT_NAME).resolve()),
        "portable_refs_only": True,
        "artifacts": {
            "raw_source": raw_source,
        },
        "pages": page_records,
        "resume": {
            "page_count": int(document.get("page_count") or len(page_records)),
            "pages_recorded": len(page_records),
            "states": states,
        },
        "write_policy": "preview_only",
        "write_performed": False,
        "active_memory_write_performed": False,
        "error": None,
    }


def artifact_path_from_ref(ref: str, *, data_root: str | Path | None = None) -> Path:
    """Resolve a portable artifact ref under a data root without allowing escape."""
    ref_text = str(ref or "").strip().replace("\\", "/")
    if not ref_text:
        raise ValueError("artifact ref is required")
    ref_path = Path(ref_text)
    if ref_path.is_absolute() or (len(ref_text) >= 2 and ref_text[1] == ":"):
        raise ValueError("artifact ref must be relative")
    if ".." in ref_path.parts:
        raise ValueError("artifact ref cannot contain parent traversal")
    root = _data_root(data_root).resolve()
    resolved = (root / ref_path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("artifact ref resolved outside data root") from exc
    return resolved


def _artifact_record(
    *,
    artifact_type: str,
    content_hash: str,
    suffix: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    digest = content_hash.split(":", 1)[1]
    safe_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    collection = {
        "raw_source": "sources",
        "page_text": "page_texts",
    }.get(artifact_type, f"{artifact_type}s")
    return {
        "artifact_type": artifact_type,
        "content_hash": content_hash,
        "ref": f"{DEFAULT_ARTIFACT_ROOT_NAME}/{collection}/{digest[:2]}/{digest}{safe_suffix}",
        "metadata": {key: value for key, value in metadata.items() if value is not None},
    }


def _page_state(page: dict[str, Any], failed_pages: set[int], text_artifact: dict[str, Any] | None) -> str:
    page_number = int(page.get("page_number"))
    if page_number in failed_pages:
        return "failed"
    if page.get("visual_review_needed"):
        return "visual_needed"
    if text_artifact is not None:
        return "text_extracted"
    return "pending"


def _data_root(value: str | Path | None = None) -> Path:
    if value is not None:
        return Path(value).expanduser().resolve()
    return resolve_data_root()


def _split_text_pages(content: str) -> list[str]:
    if not content:
        return []
    pages = content.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    return pages


def _hash_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_hash(value: Any) -> str:
    text = str(value or "")
    if not text.startswith("sha256:") or len(text) != len("sha256:") + 64:
        raise ValueError("content_hash must be a sha256: hex digest")
    return text


def _manifest_id(content_hash: str, document_id: Any) -> str:
    digest = hashlib.sha256(content_hash.encode("utf-8")).hexdigest()[:8]
    label = _slugify(str(document_id or "document"), max_length=96)
    return f"doc_manifest_{label}_{digest}" if label else f"doc_manifest_{digest}"


def _slugify(value: str, *, max_length: int = 80) -> str:
    slug = "".join(char.lower() if char.isalnum() else "_" for char in str(value).strip())
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_")[:max_length].strip("_")


def _page_set(value: Any) -> set[int]:
    pages: set[int] = set()
    for item in value or []:
        try:
            page = int(item)
        except (TypeError, ValueError):
            continue
        if page > 0:
            pages.add(page)
    return pages


def _suffix_for_media(media_type: Any, source_type: Any) -> str:
    if media_type == "application/pdf" or source_type == "pdf":
        return ".pdf"
    if media_type == "text/markdown" or source_type in {"markdown", "md"}:
        return ".md"
    if media_type == "text/plain" or source_type in {"text", "txt", "transcript"}:
        return ".txt"
    return ".bin"
