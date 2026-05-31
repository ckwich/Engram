"""Read-only Memory OS capability discovery packets."""
from __future__ import annotations

import json
from typing import Any

from core.memory_os._records import hash_payload, list_records
from core.mcp.tool_registry import build_memory_protocol_sections

CAPABILITY_DISCOVERY_SCHEMA_VERSION = "2026-05-26.capability-discovery.v1"
MIN_CAPABILITY_DISCOVERY_BUDGET_CHARS = 250


def build_capability_catalog(
    runtime: Any,
    *,
    query: str = "",
    budget_chars: int = 4000,
) -> dict[str, Any]:
    """Return a budgeted, no-write catalog of agent-facing Engram capabilities."""
    budget = max(MIN_CAPABILITY_DISCOVERY_BUDGET_CHARS, int(budget_chars or 4000))
    protocol = build_memory_protocol_sections(include_beta=True)
    tool_groups = protocol.get("tool_groups") or {}
    status = runtime.status() if runtime is not None else {"status": "unavailable"}

    catalog = {
        "schema_version": CAPABILITY_DISCOVERY_SCHEMA_VERSION,
        "query_hash": hash_payload(str(query or "")),
        "write_performed": False,
        "budget": {
            "budget_chars": budget,
            "used_chars": 0,
            "truncated": False,
            "omitted_group_count": 0,
        },
        "capability_groups": _capability_groups(tool_groups),
        "runtime": _runtime_summary(status),
        "warnings": _capability_warnings(runtime),
        "error": None,
    }
    return _fit_budget(catalog, budget)


def _capability_groups(tool_groups: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        "memory": {
            "purpose": "Search, read, prepare, write, and maintain durable memories.",
            "stability": "stable",
            "cost_class": "low-to-write",
            "tools": _tools(
                tool_groups,
                "retrieval",
                "writing",
                "memory_review",
                fallback=["search_memories", "retrieve_chunk", "retrieve_memory", "store_memory"],
            ),
        },
        "document_intelligence": _group(
            tool_groups,
            "document_intelligence",
            fallback_tools=["prepare_document_ingestion_plan", "run_document_ingestion", "inspect_document_ingestion"],
        ),
        "graph": _group(
            tool_groups,
            "graph",
            fallback_tools=["prepare_graph_readiness_report", "prepare_graph_proposal_batch", "apply_graph_proposal_batch"],
        ),
        "knowledge_prs": _group(
            tool_groups,
            "knowledge_prs",
            fallback_tools=["prepare_knowledge_branch", "prepare_knowledge_pr", "run_memory_ci"],
        ),
        "sync": {
            "purpose": "Inspect device sync state and exchange reviewed changesets through the personal hub transport.",
            "stability": "beta",
            "cost_class": "low-to-write",
            "tools": [
                "ensure_sync_device_identity",
                "export_local_sync_identity",
                "register_sync_peer",
                "inspect_sync_state",
                "prepare_sync_changeset",
                "export_sync_changeset",
                "prepare_sync_apply",
                "apply_sync_changeset",
                "inspect_sync_convergence",
                "list_sync_conflicts",
                "resolve_sync_conflict",
                "configure_sync_peer_transport",
                "inspect_sync_peer",
                "push_sync_changeset",
                "list_sync_inbox",
                "prepare_sync_inbox_apply",
                "apply_sync_inbox",
            ],
        },
        "benchmarks": _group(
            tool_groups,
            "benchmarks",
            fallback_tools=["list_memory_benchmark_suites", "run_memory_benchmark", "inspect_benchmark_run"],
        ),
    }


def _group(
    tool_groups: dict[str, Any],
    name: str,
    *,
    fallback_tools: list[str],
) -> dict[str, Any]:
    source = dict(tool_groups.get(name) or {})
    return {
        "purpose": source.get("purpose") or f"{name.replace('_', ' ').title()} capabilities.",
        "stability": source.get("stability") or "beta",
        "cost_class": source.get("cost_class") or "varies",
        "tools": list(source.get("tools") or fallback_tools),
    }


def _tools(
    tool_groups: dict[str, Any],
    *group_names: str,
    fallback: list[str],
) -> list[str]:
    tools: list[str] = []
    seen: set[str] = set()
    for group_name in group_names:
        for tool in (tool_groups.get(group_name) or {}).get("tools") or []:
            if tool not in seen:
                seen.add(str(tool))
                tools.append(str(tool))
    return tools or list(fallback)


def _runtime_summary(status: dict[str, Any]) -> dict[str, Any]:
    components = status.get("components") if isinstance(status.get("components"), dict) else {}
    retrieval = components.get("retrieval") if isinstance(components.get("retrieval"), dict) else {}
    graph = components.get("graph") if isinstance(components.get("graph"), dict) else {}
    return {
        "status": status.get("status"),
        "root": status.get("root"),
        "retrieval": {
            "backend": retrieval.get("backend"),
            "state": retrieval.get("state"),
        },
        "graph": {
            "backend": graph.get("backend"),
            "state": graph.get("state"),
        },
    }


def _capability_warnings(runtime: Any) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    if runtime is None or _sync_device_count(runtime) == 0:
        warnings.append(
            {
                "code": "sync_not_configured",
                "message": "No sync devices are configured yet.",
            }
        )
    return warnings


def _sync_device_count(runtime: Any) -> int:
    ledger = getattr(runtime, "ledger", None)
    if ledger is None:
        return 0
    try:
        return len(list_records(ledger, "sync_devices"))
    except Exception:
        return 0


def _fit_budget(catalog: dict[str, Any], budget: int) -> dict[str, Any]:
    used = _payload_size(catalog)
    if used <= budget:
        catalog["budget"]["used_chars"] = used
        return catalog

    compact = {
        **catalog,
        "budget": {
            **catalog["budget"],
            "truncated": True,
            "omitted_group_count": 0,
        },
        "capability_groups": {
            name: {
                "tools": list(group.get("tools") or [])[:1],
                "omitted_tool_count": max(0, len(group.get("tools") or []) - 1),
            }
            for name, group in catalog["capability_groups"].items()
        },
        "runtime": _compact_runtime(catalog.get("runtime") or {}),
        "warnings": list(catalog.get("warnings") or [])[:2],
    }
    used = _payload_size(compact)
    if used > budget:
        compact["capability_groups"] = {
            name: {"tools": [], "omitted_tool_count": len(group.get("tools") or [])}
            for name, group in catalog["capability_groups"].items()
        }
        compact["warnings"] = []
        compact["runtime"] = {"status": (catalog.get("runtime") or {}).get("status")}
        used = _payload_size(compact)
    if used > budget:
        compact = _minimal_budget_catalog(catalog, budget)
        used = _payload_size(compact)
    compact["budget"]["used_chars"] = used
    return compact


def _minimal_budget_catalog(catalog: dict[str, Any], budget: int) -> dict[str, Any]:
    groups = {
        name: {}
        for name in catalog.get("capability_groups") or {}
    }
    omitted_group_count = len(groups)
    minimal = {
        "schema_version": CAPABILITY_DISCOVERY_SCHEMA_VERSION,
        "query_hash": catalog.get("query_hash"),
        "write_performed": False,
        "budget": {
            "budget_chars": budget,
            "used_chars": 0,
            "truncated": True,
            "omitted_group_count": omitted_group_count,
        },
        "capability_groups": groups,
        "runtime": {"status": (catalog.get("runtime") or {}).get("status")},
        "warnings": [],
        "error": None,
    }
    if _payload_size(minimal) <= budget:
        return minimal
    minimal["capability_groups"] = {}
    minimal["budget"]["omitted_group_count"] = omitted_group_count
    if _payload_size(minimal) <= budget:
        return minimal
    minimal = {
        "schema_version": CAPABILITY_DISCOVERY_SCHEMA_VERSION,
        "write_performed": False,
        "budget": {
            "budget_chars": budget,
            "used_chars": 0,
            "truncated": True,
            "omitted_group_count": omitted_group_count,
        },
        "capability_groups": {},
    }
    return minimal


def _compact_runtime(runtime: dict[str, Any]) -> dict[str, Any]:
    retrieval = runtime.get("retrieval") if isinstance(runtime.get("retrieval"), dict) else {}
    graph = runtime.get("graph") if isinstance(runtime.get("graph"), dict) else {}
    retrieval_state = retrieval.get("state") if isinstance(retrieval.get("state"), dict) else {}
    graph_state = graph.get("state") if isinstance(graph.get("state"), dict) else {}
    return {
        "status": runtime.get("status"),
        "retrieval": {
            "backend": retrieval.get("backend"),
            "ready": retrieval_state.get("ready"),
            "status": retrieval_state.get("status"),
        },
        "graph": {
            "backend": graph.get("backend"),
            "trusted_for_evidence": graph_state.get("trusted_for_evidence"),
            "status": graph_state.get("status"),
        },
    }


def _payload_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, sort_keys=True))
