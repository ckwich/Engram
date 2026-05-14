"""Plain document handler helpers for MCP entrypoints."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


def _document_intake_unavailable_payload(
    *,
    source_path: str,
    error: dict[str, str],
) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "source": {"source_path": source_path},
        "disassembly": None,
        "extraction_request": None,
        "document_preview": None,
        "quality": None,
        "artifact_manifest": None,
        "draft_candidates": [],
        "promotion_guidance": {"auto_promote": False},
        "policy": {
            "write_behavior": "read_only",
            "active_memory_promoted": False,
            "graph_edges_promoted": False,
        },
        "resume": None,
        "receipts": {"artifacts_built": 0, "artifacts_read": 0, "coverage_missing": []},
        "error": error,
    }


async def prepare_document_intake_review_payload(
    input_payload: dict[str, Any],
    *,
    daemon_enabled: bool,
    call_daemon: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
    build_document_intake_review: Callable[..., dict[str, Any]],
    daemon_error_type: type[BaseException],
    tool_error: Callable[[str, str], dict[str, str]],
) -> dict[str, Any]:
    source_path = str(input_payload.get("source_path") or "")
    if daemon_enabled:
        try:
            return await call_daemon("prepare_document_intake_review", input_payload)
        except daemon_error_type as exc:
            return _document_intake_unavailable_payload(
                source_path=source_path,
                error=tool_error("runtime_error", f"❌ Engram daemon error: {exc}"),
            )
    try:
        return build_document_intake_review(**input_payload)
    except Exception as exc:
        return _document_intake_unavailable_payload(
            source_path=source_path,
            error=tool_error("runtime_error", f"Unexpected document intake review failure: {exc}"),
        )


async def prepare_document_artifact_store_payload(
    input_payload: dict[str, Any],
    *,
    daemon_enabled: bool,
    call_daemon: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
    daemon_error_type: type[BaseException],
    tool_error: Callable[[str, str], dict[str, str]],
) -> dict[str, Any]:
    if daemon_enabled:
        try:
            return await call_daemon("prepare_document_artifact_store", input_payload)
        except daemon_error_type as exc:
            return {
                "status": "unavailable",
                "write_performed": False,
                "active_memory_write_performed": False,
                "graph_write_performed": False,
                "error": tool_error("runtime_error", f"❌ Engram daemon error: {exc}"),
            }
    return {
        "status": "unavailable",
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "error": tool_error(
            "daemon_required",
            "prepare_document_artifact_store requires the daemon-owned Memory OS path.",
        ),
    }
