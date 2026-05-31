"""Plain backend-readiness handler helpers for MCP entrypoints."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


async def retrieval_backend_status_payload(
    input_payload: dict[str, Any],
    *,
    repo_path: Callable[[str, str], Any],
    run_in_thread: Callable[..., Awaitable[dict[str, Any]]],
    build_status: Callable[..., dict[str, Any]],
    tool_error: Callable[[str, str], dict[str, str]],
) -> dict[str, Any]:
    store_root = input_payload.get("store_root")
    include_rebuild_probe = bool(input_payload.get("include_rebuild_probe", False))
    rebuild_batch_size = int(input_payload.get("rebuild_batch_size", 128))
    try:
        resolved_store_root = None
        if store_root is not None:
            resolved_store_root = repo_path(store_root, store_root)
        return await run_in_thread(
            build_status,
            store_root=resolved_store_root,
            include_rebuild_probe=include_rebuild_probe,
            rebuild_batch_size=rebuild_batch_size,
        )
    except ValueError as exc:
        return {
            "schema_version": None,
            "operation": "retrieval_backend_status",
            "store_root": store_root,
            "write_performed": False,
            "active_memory_write_performed": False,
            "live_retrieval_changed": False,
            "error": tool_error("invalid_request", str(exc)),
        }
    except Exception as exc:
        return {
            "schema_version": None,
            "operation": "retrieval_backend_status",
            "store_root": store_root,
            "write_performed": False,
            "active_memory_write_performed": False,
            "live_retrieval_changed": False,
            "error": tool_error("runtime_error", f"Unexpected retrieval backend status failure: {exc}"),
        }


async def graph_backend_status_payload(
    input_payload: dict[str, Any],
    *,
    repo_path: Callable[[str, str], Any],
    run_in_thread: Callable[..., Awaitable[dict[str, Any]]],
    build_status: Callable[..., dict[str, Any]],
    tool_error: Callable[[str, str], dict[str, str]],
) -> dict[str, Any]:
    store_root = input_payload.get("store_root")
    graph_path = input_payload.get("graph_path")
    try:
        resolved_store_root = None
        resolved_graph_path = None
        if store_root is not None:
            resolved_store_root = repo_path(store_root, store_root)
        if graph_path is not None:
            resolved_graph_path = repo_path(graph_path, graph_path)
        return await run_in_thread(
            build_status,
            store_root=resolved_store_root,
            graph_path=resolved_graph_path,
        )
    except Exception as exc:
        return {
            "schema_version": None,
            "operation": "graph_backend_status",
            "store_root": store_root,
            "graph_path": graph_path,
            "write_performed": False,
            "active_memory_write_performed": False,
            "live_graph_backend_changed": False,
            "error": tool_error("runtime_error", f"Unexpected graph backend status failure: {exc}"),
        }

