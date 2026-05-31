"""Plain EKC handler helpers for MCP entrypoints."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


def query_knowledge_runtime_error(
    request: dict[str, Any] | None,
    message: str,
    *,
    code: str = "runtime_error",
) -> dict[str, Any]:
    return {
        "contract_version": "engram.knowledge.response.v0",
        "request_id": str((request or {}).get("request_id") or ""),
        "status": "unavailable",
        "answer": None,
        "citations": [],
        "freshness": {"state": "unknown"},
        "policy": {
            "unreviewed_sources_used": False,
            "unsupported_inferences_used": False,
            "review_state_available": False,
            "review_filter_enforced": False,
            "review_state_basis": "not_available_in_current_memory_os_records",
        },
        "budget_used": {
            "artifacts_built": 0,
            "artifacts_read": 0,
            "source_reads": 0,
            "tokens_out_estimate": 0,
        },
        "planner": {
            "strategy": "none",
            "methods_used": [],
            "omissions": [],
            "budget": {
                "requested": {},
                "used": {
                    "artifacts_built": 0,
                    "artifacts_read": 0,
                    "source_reads": 0,
                    "tokens_out_estimate": 0,
                },
            },
            "failure_receipts": [
                {
                    "code": code,
                    "category": "infrastructure",
                    "message": message,
                    "recoverable": True,
                }
            ],
            "response_status": "unavailable",
        },
        "errors": [{"code": code, "category": "infrastructure", "message": message}],
    }


async def query_knowledge_payload(
    request: dict[str, Any],
    *,
    daemon_enabled: bool,
    query_daemon: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    daemon_error_type: type[BaseException],
) -> dict[str, Any]:
    if daemon_enabled:
        try:
            return await query_daemon(request)
        except daemon_error_type as exc:
            return query_knowledge_runtime_error(request, str(exc))
    return query_knowledge_runtime_error(
        request,
        "query_knowledge requires the daemon-owned Memory OS path.",
        code="daemon_required",
    )

