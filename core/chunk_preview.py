from __future__ import annotations

from typing import Any

from core.chunker import MAX_CHUNK_SIZE, chunk_content_with_metadata

PREVIEW_SCHEMA_VERSION = "2026-04-30.chunk-preview.v1"
MAX_PREVIEW_CHUNK_SIZE = 5000
MIN_PREVIEW_CHUNK_SIZE = 100
DEFAULT_MAX_PREVIEW_CHUNKS = 50


def _normalize_max_size(max_size: int) -> int:
    try:
        requested = int(max_size)
    except (TypeError, ValueError):
        requested = MAX_CHUNK_SIZE
    return min(max(requested, MIN_PREVIEW_CHUNK_SIZE), MAX_PREVIEW_CHUNK_SIZE)


def preview_memory_chunks(
    content: str,
    *,
    title: str = "",
    max_size: int = MAX_CHUNK_SIZE,
    max_chunks: int = DEFAULT_MAX_PREVIEW_CHUNKS,
) -> dict[str, Any]:
    """Return reviewable chunk boundaries without writing memory or embeddings."""
    normalized_content = content or ""
    normalized_max_size = _normalize_max_size(max_size)
    normalized_max_chunks = min(max(int(max_chunks), 1), 200)
    chunks = chunk_content_with_metadata(normalized_content, max_size=normalized_max_size)
    visible_chunks = chunks[:normalized_max_chunks]
    omitted_chunks = max(len(chunks) - len(visible_chunks), 0)

    preview_chunks: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for chunk in visible_chunks:
        text = chunk.get("text") or ""
        char_count = len(text)
        if char_count > normalized_max_size:
            warnings.append(
                {
                    "chunk_id": chunk.get("chunk_id"),
                    "code": "oversized_chunk",
                    "message": "Chunk exceeds requested max_size.",
                }
            )
        preview_chunks.append(
            {
                "chunk_id": chunk.get("chunk_id", 0),
                "char_count": char_count,
                "section_title": chunk.get("section_title") or "",
                "heading_path": chunk.get("heading_path") or [],
                "chunk_kind": chunk.get("chunk_kind") or "section",
                "text": text,
            }
        )

    return {
        "schema_version": PREVIEW_SCHEMA_VERSION,
        "title": title or "",
        "chunk_count": len(preview_chunks),
        "total_chunk_count": len(chunks),
        "chunks": preview_chunks,
        "warnings": warnings,
        "receipt": {
            "input_chars": len(normalized_content),
            "max_size": normalized_max_size,
            "max_chunks": normalized_max_chunks,
            "omitted_chunks": omitted_chunks,
            "write_performed": False,
        },
    }
