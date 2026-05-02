from __future__ import annotations

from pathlib import Path
from typing import Any

CONNECTOR_SCHEMA_VERSION = "2026-04-30.source-connectors.v1"
DEFAULT_INCLUDE_GLOBS = ["*.md", "*.txt", "*.rst"]
DEFAULT_MAX_FILE_SIZE_KB = 256
DEFAULT_MAX_FILES = 20
DEFAULT_MAX_SOURCE_TEXT_CHARS = 12_000
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
    return globs or list(DEFAULT_INCLUDE_GLOBS)


def _is_skipped(path: Path) -> bool:
    return any(part in SKIP_DIR_NAMES for part in path.parts)


def _candidate_files(root: Path, include_globs: list[str], max_files: int) -> tuple[list[Path], int]:
    if root.is_file():
        return [root], 0

    seen: set[Path] = set()
    matches: list[Path] = []
    for pattern in include_globs:
        for path in root.rglob(pattern):
            if len(matches) >= max_files:
                return sorted(matches), 1
            if not path.is_file() or _is_skipped(path.relative_to(root)):
                continue
            resolved = path.resolve()
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
        "write_performed": False,
        "error": None,
    }
