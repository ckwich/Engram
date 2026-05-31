"""Shared MCP tool metadata for protocol generation.

This module is intentionally data-first: MCP entrypoints should import these
sections instead of hand-maintaining parallel protocol lists.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.memory_os.knowledge_eval import STABLE_EKC_TASK_TYPES
from core.memory_os.schema import (
    MEMORY_SCOPES,
    MEMORY_TYPES,
    RETENTION_POLICIES,
    SYNC_POLICIES,
    TRUST_STATES,
)


@dataclass(frozen=True)
class ToolMetadata:
    name: str
    description: str
    stability: str
    cost_class: str = "varies"
    write_behavior: str = "read_only"
    requires_acceptance: bool = False


@dataclass(frozen=True)
class DaemonRouteMetadata:
    name: str
    method: str
    path: str
    concurrent: bool = False


STABLE_DOCUMENT_WORKFLOW = [
    "list_document_extractors",
    "preview_document_source_connector",
    "prepare_document_disassembly",
    "prepare_document_coverage_workbench",
    "prepare_document_coverage_pass",
    "prepare_document_intake_review",
    "prepare_document_extraction_request",
    "prepare_document_extraction_result",
    "preview_document_extraction",
    "prepare_visual_extraction_request",
    "preview_visual_extraction",
    "prepare_document_understanding_packet",
    "prepare_document_draft",
    "prepare_document_promotion_transaction",
    "apply_document_promotion_transaction",
    "prepare_document_ingestion_plan",
    "run_document_ingestion",
    "resume_document_ingestion",
    "inspect_document_ingestion",
]

DOCUMENT_ARTIFACT_WORKFLOW = [
    "prepare_document_artifact_store",
    "store_document_artifact",
    "prepare_document_ingestion_completion",
    "complete_document_ingestion",
]

GRAPH_PIPELINE_WORKFLOW = [
    "prepare_graph_readiness_report",
    "prepare_graph_proposal_batch",
    "apply_graph_proposal_batch",
    "repair_graph_edge_refs",
    "repair_graph_store_reconciliation",
]

KNOWLEDGE_PR_WORKFLOW = [
    "prepare_knowledge_branch",
    "prepare_knowledge_pr",
    "run_memory_ci",
    "inspect_knowledge_pr",
    "merge_knowledge_pr",
]

BENCHMARK_WORKFLOW = [
    "list_memory_benchmark_suites",
    "run_memory_benchmark",
    "inspect_benchmark_run",
]

SYNC_IDENTITY_WORKFLOW = [
    "ensure_sync_device_identity",
    "export_local_sync_identity",
    "register_sync_peer",
]

SYNC_CHANGESET_WORKFLOW = [
    "inspect_sync_state",
    "prepare_sync_changeset",
    "export_sync_changeset",
    "prepare_sync_apply",
    "apply_sync_changeset",
    "inspect_sync_convergence",
    "list_sync_conflicts",
    "resolve_sync_conflict",
]

SYNC_TRANSPORT_WORKFLOW = [
    "configure_sync_peer_transport",
    "inspect_sync_peer",
    "push_sync_changeset",
    "list_sync_inbox",
    "prepare_sync_inbox_apply",
    "apply_sync_inbox",
]

LEGACY_MIGRATION_WORKFLOW = [
    "migration_dry_run",
    "memory_os_round_trip_check",
    "prepare_legacy_memory_os_migration",
    "apply_legacy_memory_os_migration",
    "prepare_legacy_related_to_graph_migration",
    "apply_legacy_related_to_graph_migration",
]

THIN_LEGACY_MIGRATION_WORKFLOW = [
    "prepare_legacy_memory_os_migration",
    "apply_legacy_memory_os_migration",
    "prepare_legacy_related_to_graph_migration",
    "apply_legacy_related_to_graph_migration",
]

THIN_CLIENT_BASE_TOOLS = [
    "memory_protocol",
    "daemon_status",
    "memory_os_status",
    "discover_memory_capabilities",
    "query_knowledge",
    "search_memories",
    "retrieve_chunk",
    "retrieve_chunks",
    "retrieve_memory",
    "store_memory",
    "prepare_source_memory",
]


def _route(
    name: str,
    path: str,
    *,
    method: str = "POST",
    concurrent: bool = False,
) -> DaemonRouteMetadata:
    return DaemonRouteMetadata(
        name=name,
        method=method,
        path=path,
        concurrent=concurrent,
    )


DAEMON_ROUTES: dict[str, DaemonRouteMetadata] = {
    "health": _route("health", "/health", method="GET", concurrent=True),
    "memory_os_status": _route("memory_os_status", "/v1/memory_os/status", method="GET", concurrent=True),
    "memory_os_inspector": _route("memory_os_inspector", "/v1/memory_os/inspector", method="GET", concurrent=True),
    "memory_os_source_import_job": _route("memory_os_source_import_job", "/v1/memory_os/source_import_job"),
    "discover_memory_capabilities": _route("discover_memory_capabilities", "/v1/discover_memory_capabilities", concurrent=True),
    "prepare_legacy_memory_os_migration": _route("prepare_legacy_memory_os_migration", "/v1/prepare_legacy_memory_os_migration"),
    "apply_legacy_memory_os_migration": _route("apply_legacy_memory_os_migration", "/v1/apply_legacy_memory_os_migration"),
    "prepare_legacy_related_to_graph_migration": _route("prepare_legacy_related_to_graph_migration", "/v1/prepare_legacy_related_to_graph_migration"),
    "apply_legacy_related_to_graph_migration": _route("apply_legacy_related_to_graph_migration", "/v1/apply_legacy_related_to_graph_migration"),
    "query_knowledge": _route("query_knowledge", "/v1/query_knowledge", concurrent=True),
    "search_memories": _route("search_memories", "/v1/search_memories", concurrent=True),
    "retrieve_chunk": _route("retrieve_chunk", "/v1/retrieve_chunk", concurrent=True),
    "retrieve_chunks": _route("retrieve_chunks", "/v1/retrieve_chunks", concurrent=True),
    "retrieve_memory": _route("retrieve_memory", "/v1/retrieve_memory", concurrent=True),
    "store_memory": _route("store_memory", "/v1/store_memory"),
    "prepare_source_memory": _route("prepare_source_memory", "/v1/prepare_source_memory"),
    "list_document_extractors": _route("list_document_extractors", "/v1/list_document_extractors"),
    "preview_document_source_connector": _route("preview_document_source_connector", "/v1/preview_document_source_connector"),
    "prepare_document_disassembly": _route("prepare_document_disassembly", "/v1/prepare_document_disassembly"),
    "prepare_document_coverage_workbench": _route("prepare_document_coverage_workbench", "/v1/prepare_document_coverage_workbench"),
    "prepare_document_coverage_pass": _route("prepare_document_coverage_pass", "/v1/prepare_document_coverage_pass"),
    "prepare_document_intake_review": _route("prepare_document_intake_review", "/v1/prepare_document_intake_review"),
    "prepare_document_extraction_request": _route("prepare_document_extraction_request", "/v1/prepare_document_extraction_request"),
    "prepare_document_extraction_result": _route("prepare_document_extraction_result", "/v1/prepare_document_extraction_result"),
    "preview_document_extraction": _route("preview_document_extraction", "/v1/preview_document_extraction"),
    "prepare_visual_extraction_request": _route("prepare_visual_extraction_request", "/v1/prepare_visual_extraction_request"),
    "preview_visual_extraction": _route("preview_visual_extraction", "/v1/preview_visual_extraction"),
    "prepare_document_understanding_packet": _route("prepare_document_understanding_packet", "/v1/prepare_document_understanding_packet"),
    "prepare_document_draft": _route("prepare_document_draft", "/v1/prepare_document_draft"),
    "prepare_document_promotion_transaction": _route("prepare_document_promotion_transaction", "/v1/prepare_document_promotion_transaction"),
    "apply_document_promotion_transaction": _route("apply_document_promotion_transaction", "/v1/apply_document_promotion_transaction"),
    "prepare_document_artifact_store": _route("prepare_document_artifact_store", "/v1/prepare_document_artifact_store"),
    "store_document_artifact": _route("store_document_artifact", "/v1/store_document_artifact"),
    "prepare_document_ingestion_plan": _route("prepare_document_ingestion_plan", "/v1/prepare_document_ingestion_plan"),
    "run_document_ingestion": _route("run_document_ingestion", "/v1/run_document_ingestion"),
    "resume_document_ingestion": _route("resume_document_ingestion", "/v1/resume_document_ingestion"),
    "inspect_document_ingestion": _route("inspect_document_ingestion", "/v1/inspect_document_ingestion", concurrent=True),
    "prepare_document_ingestion_completion": _route("prepare_document_ingestion_completion", "/v1/prepare_document_ingestion_completion"),
    "complete_document_ingestion": _route("complete_document_ingestion", "/v1/complete_document_ingestion"),
    "prepare_knowledge_branch": _route("prepare_knowledge_branch", "/v1/prepare_knowledge_branch"),
    "prepare_knowledge_pr": _route("prepare_knowledge_pr", "/v1/prepare_knowledge_pr"),
    "run_memory_ci": _route("run_memory_ci", "/v1/run_memory_ci"),
    "inspect_knowledge_pr": _route("inspect_knowledge_pr", "/v1/inspect_knowledge_pr", concurrent=True),
    "merge_knowledge_pr": _route("merge_knowledge_pr", "/v1/merge_knowledge_pr"),
    "list_memory_benchmark_suites": _route("list_memory_benchmark_suites", "/v1/list_memory_benchmark_suites", concurrent=True),
    "run_memory_benchmark": _route("run_memory_benchmark", "/v1/run_memory_benchmark"),
    "inspect_benchmark_run": _route("inspect_benchmark_run", "/v1/inspect_benchmark_run", concurrent=True),
    "ensure_sync_device_identity": _route("ensure_sync_device_identity", "/v1/ensure_sync_device_identity"),
    "export_local_sync_identity": _route("export_local_sync_identity", "/v1/export_local_sync_identity", concurrent=True),
    "register_sync_peer": _route("register_sync_peer", "/v1/register_sync_peer"),
    "inspect_sync_state": _route("inspect_sync_state", "/v1/inspect_sync_state", concurrent=True),
    "prepare_sync_changeset": _route("prepare_sync_changeset", "/v1/prepare_sync_changeset"),
    "export_sync_changeset": _route("export_sync_changeset", "/v1/export_sync_changeset"),
    "prepare_sync_apply": _route("prepare_sync_apply", "/v1/prepare_sync_apply"),
    "apply_sync_changeset": _route("apply_sync_changeset", "/v1/apply_sync_changeset"),
    "inspect_sync_convergence": _route("inspect_sync_convergence", "/v1/inspect_sync_convergence", concurrent=True),
    "list_sync_conflicts": _route("list_sync_conflicts", "/v1/list_sync_conflicts", concurrent=True),
    "resolve_sync_conflict": _route("resolve_sync_conflict", "/v1/resolve_sync_conflict"),
    "configure_sync_peer_transport": _route("configure_sync_peer_transport", "/v1/configure_sync_peer_transport"),
    "inspect_sync_peer": _route("inspect_sync_peer", "/v1/inspect_sync_peer", concurrent=True),
    "push_sync_changeset": _route("push_sync_changeset", "/v1/push_sync_changeset"),
    "list_sync_inbox": _route("list_sync_inbox", "/v1/list_sync_inbox", concurrent=True),
    "prepare_sync_inbox_apply": _route("prepare_sync_inbox_apply", "/v1/prepare_sync_inbox_apply"),
    "apply_sync_inbox": _route("apply_sync_inbox", "/v1/apply_sync_inbox"),
    "prune_applied_sync_inbox_artifacts": _route(
        "prune_applied_sync_inbox_artifacts",
        "/v1/prune_applied_sync_inbox_artifacts",
    ),
    "prepare_graph_readiness_report": _route("prepare_graph_readiness_report", "/v1/prepare_graph_readiness_report"),
    "prepare_graph_proposal_batch": _route("prepare_graph_proposal_batch", "/v1/prepare_graph_proposal_batch"),
    "apply_graph_proposal_batch": _route("apply_graph_proposal_batch", "/v1/apply_graph_proposal_batch"),
    "repair_graph_edge_refs": _route("repair_graph_edge_refs", "/v1/repair_graph_edge_refs"),
    "repair_graph_store_reconciliation": _route("repair_graph_store_reconciliation", "/v1/repair_graph_store_reconciliation"),
    "list_source_drafts": _route("list_source_drafts", "/v1/list_source_drafts", concurrent=True),
    "discard_source_draft": _route("discard_source_draft", "/v1/discard_source_draft"),
    "store_prepared_memory": _route("store_prepared_memory", "/v1/store_prepared_memory"),
    "check_duplicate": _route("check_duplicate", "/v1/check_duplicate"),
    "update_memory_metadata": _route("update_memory_metadata", "/v1/update_memory_metadata"),
    "repair_memory_metadata": _route("repair_memory_metadata", "/v1/repair_memory_metadata"),
    "repair_document_metadata": _route("repair_document_metadata", "/v1/repair_document_metadata"),
    "delete_memory": _route("delete_memory", "/v1/delete_memory"),
}

PROTOCOL_STABILITY = {
    "memory_protocol": "stable",
    "search_memories": "stable",
    "context_pack": "stable",
    "list_memories": "stable",
    "retrieve_chunk": "stable",
    "retrieve_chunks": "stable",
    "retrieve_memory": "stable",
    "prepare_memory": "stable",
    "store_memory": "stable",
    "write_memory": "stable",
    "codebase_mapping": "beta",
    "graph": "beta",
    "source_intake": "beta",
    "document_intelligence": "beta",
    "agent_workflows": "beta",
    "knowledge_contract": "stable",
    "knowledge_prs": "beta",
    "review_helpers": "beta",
    "retrieval_quality": "beta",
    "retrieval_backend": "beta",
    "usage": "beta",
    "operations": "beta",
    "migration": "beta",
    "daemon_status": "beta",
    "capability_discovery": "beta",
    "sync": "beta",
}

TOOL_GROUPS: dict[str, dict[str, Any]] = {
    "retrieval": {
        "purpose": "Find and read bounded memory context.",
        "stability": "stable",
        "cost_class": "low-to-medium",
        "tools": ["search_memories", "retrieve_chunk", "retrieve_chunks", "context_pack"],
    },
    "writing": {
        "purpose": "Draft, validate, and store explicit memories.",
        "stability": "stable",
        "cost_class": "write",
        "tools": ["prepare_memory", "store_memory", "write_memory"],
    },
    "memory_review": {
        "purpose": "Inspect duplicate risk, metadata suggestions, validation, related memories, and stale memories.",
        "stability": "stable",
        "cost_class": "low",
        "tools": [
            "check_duplicate",
            "suggest_memory_metadata",
            "validate_memory",
            "update_memory_metadata",
            "audit_memory_quality",
            "get_related_memories",
            "get_stale_memories",
            "delete_memory",
        ],
    },
    "session_pins": {
        "purpose": "Temporarily promote known memory keys within a client session.",
        "stability": "beta",
        "cost_class": "low",
        "tools": ["pin_memory", "unpin_memory", "list_pins", "clear_pins"],
    },
    "metadata_governance": {
        "purpose": "Audit and dry-run-first repair memory metadata without loading full memory bodies.",
        "stability": "beta",
        "cost_class": "low-to-write",
        "tools": ["audit_memory_metadata", "repair_memory_metadata"],
    },
    "graph": {
        "purpose": "Inspect typed relationships without loading neighbor bodies.",
        "stability": "beta",
        "cost_class": "low",
        "tools": [
            "add_graph_edge",
            "list_graph_edges",
            "impact_scan",
            "conflict_scan",
            "audit_graph",
            "graph_backend_status",
            *GRAPH_PIPELINE_WORKFLOW,
        ],
    },
    "source_intake": {
        "purpose": "Prepare source drafts without promoting durable memories.",
        "stability": "beta",
        "cost_class": "medium",
        "tools": [
            "list_ingestion_pipelines",
            "preview_memory_chunks",
            "preview_source_connector",
            "prepare_source_memory",
            "list_source_drafts",
            "discard_source_draft",
            "store_prepared_memory",
        ],
    },
    "document_intelligence": {
        "purpose": "Preview document and visual extraction evidence without writing memory.",
        "stability": "beta",
        "cost_class": "medium",
        "tools": STABLE_DOCUMENT_WORKFLOW,
    },
    "document_artifacts": {
        "purpose": "Stage ledgered document evidence, then explicitly complete usable graph-backed document ingestion.",
        "stability": "beta",
        "cost_class": "medium-write",
        "tools": DOCUMENT_ARTIFACT_WORKFLOW,
    },
    "knowledge_prs": {
        "purpose": "Prepare, test, inspect, and explicitly merge reviewed memory change packets.",
        "stability": "beta",
        "cost_class": "medium-write",
        "tools": KNOWLEDGE_PR_WORKFLOW,
    },
    "benchmarks": {
        "purpose": "Run reproducible Memory CI benchmark suites and inspect persisted evidence artifacts.",
        "stability": "beta",
        "cost_class": "medium-write",
        "tools": BENCHMARK_WORKFLOW,
    },
    "sync_identity": {
        "purpose": "Pair trusted devices for reviewed offline sync without exposing private key material.",
        "stability": "beta",
        "cost_class": "medium-write",
        "tools": SYNC_IDENTITY_WORKFLOW,
    },
    "sync_changesets": {
        "purpose": "Inspect sync state and export reviewed signed/encrypted changesets for offline divergence.",
        "stability": "beta",
        "cost_class": "medium-write",
        "tools": SYNC_CHANGESET_WORKFLOW,
    },
    "sync_transport": {
        "purpose": "Configure signed LAN/Tailscale or file-bundle transport without exposing generic memory routes.",
        "stability": "beta",
        "cost_class": "medium-write",
        "tools": SYNC_TRANSPORT_WORKFLOW,
    },
    "agent_workflows": {
        "purpose": "Compile task-focused, cited context packets without writing memory.",
        "stability": "beta",
        "cost_class": "medium",
        "tools": ["list_context_profiles", "prepare_context", "make_handoff", "prepare_project_capsule"],
    },
    "knowledge_contract": {
        "stability": "stable",
        "cost_class": "low-to-medium",
        "tools": ["query_knowledge"],
        "task_types": list(STABLE_EKC_TASK_TYPES),
    },
    "retrieval_quality": {
        "purpose": "Inspect retrieval cost, quality, citations, and workflow recipes before scaling memory.",
        "stability": "beta",
        "cost_class": "low-to-medium",
        "tools": [
            "retrieval_eval",
            "usage_summary",
            "list_usage_calls",
            "list_workflow_templates",
        ],
    },
    "retrieval_backend": {
        "purpose": "Inspect Memory OS retrieval backend readiness, backend config intent, and golden-comparison gates before switching away from legacy Chroma.",
        "stability": "beta",
        "cost_class": "low-to-medium",
        "tools": ["retrieval_backend_status"],
    },
    "codebase_mapping": {
        "purpose": "Map codebases through the connected agent without provider-specific model subprocesses.",
        "stability": "beta",
        "cost_class": "agent-mediated",
        "tools": [
            "read_codebase_mapping_config",
            "draft_codebase_mapping_config",
            "store_codebase_mapping_config",
            "preview_codebase_mapping",
            "prepare_codebase_mapping",
            "read_codebase_mapping_context",
            "store_codebase_mapping_result",
            "install_codebase_mapping_hook",
        ],
    },
    "usage": {
        "purpose": "Review Engram-attributed token estimates, call costs, and outliers.",
        "stability": "beta",
        "cost_class": "low",
        "tools": ["usage_summary", "list_usage_calls"],
    },
    "operations": {
        "purpose": "Review local operation receipts and event records.",
        "stability": "beta",
        "cost_class": "low",
        "tools": ["list_operation_jobs", "list_operation_events"],
    },
    "daemon_runtime": {
        "purpose": "Inspect whether this MCP server is using direct in-process storage or an opt-in local engramd daemon, including daemon-client autostart eligibility. For the thinnest multi-session client, use server_daemon_client.py.",
        "stability": "beta",
        "cost_class": "low",
        "tools": ["daemon_status"],
    },
    "capability_discovery": {
        "purpose": "Discover budgeted Memory OS capabilities, runtime readiness, sync/benchmark affordances, and next tools without loading memory bodies.",
        "stability": "beta",
        "cost_class": "low",
        "tools": ["discover_memory_capabilities"],
    },
    "migration": {
        "purpose": "Validate and apply reviewed Memory OS migration through daemon-owned services.",
        "stability": "beta",
        "cost_class": "medium",
        "tools": LEGACY_MIGRATION_WORKFLOW,
    },
    "compatibility_text": {
        "purpose": "Legacy text-returning wrappers for older MCP clients; prefer structured tools for new integrations.",
        "stability": "legacy",
        "cost_class": "varies",
        "tools": [
            "search_memories_text",
            "retrieve_chunk_text",
            "retrieve_memory_text",
            "list_all_memories",
            "get_related_memories_text",
            "get_stale_memories_text",
        ],
    },
}


def _unique_tool_list(names: list[str]) -> list[str]:
    tools: list[str] = []
    seen: set[str] = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        tools.append(name)
    return tools

THIN_CLIENT_TOOL_GROUPS: dict[str, dict[str, Any]] = {
    "memory_maintenance": {
        "stability": "stable",
        "cost_class": "low-to-write",
        "tools": [
            "check_duplicate",
            "list_source_drafts",
            "discard_source_draft",
            "store_prepared_memory",
            "update_memory_metadata",
            "repair_memory_metadata",
            "delete_memory",
        ],
    },
    "document_intelligence": {
        "stability": "stable",
        "cost_class": "low-to-medium",
        "tools": STABLE_DOCUMENT_WORKFLOW,
    },
    "document_artifacts": {
        "stability": "stable",
        "cost_class": "medium-write",
        "tools": DOCUMENT_ARTIFACT_WORKFLOW,
    },
    "graph_pipeline": {
        "stability": "stable",
        "cost_class": "medium-write",
        "tools": GRAPH_PIPELINE_WORKFLOW,
    },
    "knowledge_prs": {
        "stability": "beta",
        "cost_class": "medium-write",
        "tools": KNOWLEDGE_PR_WORKFLOW,
    },
    "benchmarks": {
        "stability": "beta",
        "cost_class": "medium-write",
        "tools": BENCHMARK_WORKFLOW,
    },
    "sync_identity": {
        "stability": "beta",
        "cost_class": "medium-write",
        "tools": SYNC_IDENTITY_WORKFLOW,
    },
    "sync_changesets": {
        "stability": "beta",
        "cost_class": "medium-write",
        "tools": SYNC_CHANGESET_WORKFLOW,
    },
    "sync_transport": {
        "stability": "beta",
        "cost_class": "medium-write",
        "tools": SYNC_TRANSPORT_WORKFLOW,
    },
    "capability_discovery": {
        "stability": "beta",
        "cost_class": "low",
        "tools": ["discover_memory_capabilities"],
    },
    "migration": {
        "stability": "beta",
        "cost_class": "medium-write",
        "tools": THIN_LEGACY_MIGRATION_WORKFLOW,
    },
}

THIN_CLIENT_CANONICAL_TOOLS = _unique_tool_list(
    THIN_CLIENT_BASE_TOOLS
    + STABLE_DOCUMENT_WORKFLOW
    + DOCUMENT_ARTIFACT_WORKFLOW
    + KNOWLEDGE_PR_WORKFLOW
    + BENCHMARK_WORKFLOW
    + SYNC_IDENTITY_WORKFLOW
    + SYNC_CHANGESET_WORKFLOW
    + SYNC_TRANSPORT_WORKFLOW
    + GRAPH_PIPELINE_WORKFLOW
    + THIN_LEGACY_MIGRATION_WORKFLOW
)

PROGRESSIVE_DISCOVERY = {
    "start_here": "memory_protocol",
    "load_next": {
        "topic lookup": "search_memories",
        "compact working set": "context_pack",
        "context compiler": "prepare_context",
        "retrieval profiles": "list_context_profiles",
        "handoff generator": "make_handoff",
        "project capsule": "prepare_project_capsule",
        "knowledge contract": "query_knowledge",
        "relationship inspection": "impact_scan",
        "conflict inspection": "conflict_scan",
        "graph backend status": "graph_backend_status",
        "graph readiness": "prepare_graph_readiness_report",
        "graph proposal batch": "prepare_graph_proposal_batch",
        "graph proposal acceptance": "apply_graph_proposal_batch",
        "graph edge ref repair": "repair_graph_edge_refs",
        "graph store reconciliation repair": "repair_graph_store_reconciliation",
        "source ingestion": "prepare_source_memory",
        "source ingestion setup": "list_ingestion_pipelines",
        "chunk boundary review": "preview_memory_chunks",
        "document extraction": "preview_document_extraction",
        "document extractor discovery": "list_document_extractors",
        "document disassembly": "prepare_document_disassembly",
        "document coverage workbench": "prepare_document_coverage_workbench",
        "document coverage pass": "prepare_document_coverage_pass",
        "document intake review": "prepare_document_intake_review",
        "document extraction request": "prepare_document_extraction_request",
        "document extraction result": "prepare_document_extraction_result",
        "document source connector": "preview_document_source_connector",
        "document draft": "prepare_document_draft",
        "document understanding": "prepare_document_understanding_packet",
        "document promotion": "prepare_document_promotion_transaction",
        "document promotion acceptance": "apply_document_promotion_transaction",
        "document ingestion": "prepare_document_ingestion_plan",
        "document artifact store": "prepare_document_artifact_store",
        "document artifact acceptance": "store_document_artifact",
        "document ingestion completion": "prepare_document_ingestion_completion",
        "document usable acceptance": "complete_document_ingestion",
        "visual extraction request": "prepare_visual_extraction_request",
        "visual extraction": "preview_visual_extraction",
        "retrieval quality": "retrieval_eval",
        "codebase mapping": "prepare_codebase_mapping",
        "codebase mapping setup": "draft_codebase_mapping_config",
        "usage review": "usage_summary",
        "memory quality": "audit_memory_quality",
        "knowledge branch": "prepare_knowledge_branch",
        "knowledge pr": "prepare_knowledge_pr",
        "memory ci": "run_memory_ci",
        "knowledge pr inspection": "inspect_knowledge_pr",
        "knowledge pr merge": "merge_knowledge_pr",
        "benchmark suites": "list_memory_benchmark_suites",
        "memory benchmark": "run_memory_benchmark",
        "benchmark run inspection": "inspect_benchmark_run",
        "sync identity": "ensure_sync_device_identity",
        "sync peer pairing": "register_sync_peer",
        "sync state": "inspect_sync_state",
        "sync changeset": "prepare_sync_changeset",
        "sync changeset export": "export_sync_changeset",
        "sync changeset apply": "prepare_sync_apply",
        "sync conflict review": "list_sync_conflicts",
        "sync convergence": "inspect_sync_convergence",
        "sync peer transport": "configure_sync_peer_transport",
        "sync peer inspection": "inspect_sync_peer",
        "sync changeset push": "push_sync_changeset",
        "sync inbox": "list_sync_inbox",
        "migration dry run": "migration_dry_run",
        "migration round trip": "memory_os_round_trip_check",
        "legacy related_to graph migration": "prepare_legacy_related_to_graph_migration",
        "retrieval backend status": "retrieval_backend_status",
        "daemon status": "daemon_status",
        "capability discovery": "discover_memory_capabilities",
        "metadata browsing": "list_memories",
        "memory writing": "prepare_memory",
    },
}


def _metadata(
    name: str,
    description: str,
    *,
    stability: str = "beta",
    cost_class: str = "varies",
    write_behavior: str = "read_only",
    requires_acceptance: bool = False,
) -> ToolMetadata:
    return ToolMetadata(
        name=name,
        description=description,
        stability=stability,
        cost_class=cost_class,
        write_behavior=write_behavior,
        requires_acceptance=requires_acceptance,
    )


CANONICAL_TOOLS: dict[str, ToolMetadata] = {
    "search_memories": _metadata("search_memories", "Structured semantic search with optional project/domain/tag/staleness filters.", stability="stable", cost_class="low-to-medium"),
    "context_pack": _metadata("context_pack", "Search, dedupe, and retrieve a bounded set of chunks in one call.", stability="stable", cost_class="low-to-medium"),
    "list_context_profiles": _metadata("list_context_profiles", "List no-write retrieval profiles for context compilation."),
    "prepare_context": _metadata("prepare_context", "Compile a no-write, cited context packet for a task using retrieval profiles."),
    "make_handoff": _metadata("make_handoff", "Generate a no-write handoff packet with context refs, citations, next steps, and validation notes."),
    "prepare_project_capsule": _metadata("prepare_project_capsule", "Prepare a no-write project capsule draft from context refs and quality signals."),
    "query_knowledge": _metadata("query_knowledge", "Return an EKC 1.0 project capsule, source/document orientation, review-preparation, evidence-audit, graph-evidence, or evidence-gated artifact-family response with citations, freshness, policy, budget, planner, and typed errors. The envelope remains engram.knowledge.*.v0 for compatibility.", stability="stable", cost_class="low-to-medium"),
    "discover_memory_capabilities": _metadata("discover_memory_capabilities", "Return a budgeted, no-write Memory OS capability catalog with runtime readiness and sync/benchmark affordances.", stability="stable", cost_class="low", write_behavior="read_only"),
    "audit_memory_quality": _metadata("audit_memory_quality", "Read-only metadata quality audit for scope, lifecycle, chunking, and retrieval risk signals."),
    "list_ingestion_pipelines": _metadata("list_ingestion_pipelines", "List no-write source-intake presets such as transcript, code_scan, design_doc, and handoff."),
    "conflict_scan": _metadata("conflict_scan", "List active contradiction, invalidation, and supersession graph edges without loading memory bodies."),
    "preview_memory_chunks": _metadata("preview_memory_chunks", "Show reviewable chunk boundaries before storing or promoting source material."),
    "preview_source_connector": _metadata("preview_source_connector", "Preview local-path source items and draft arguments without writing memory."),
    "list_document_extractors": _metadata("list_document_extractors", "List bundled and external document extraction capabilities without running providers."),
    "prepare_document_disassembly": _metadata("prepare_document_disassembly", "Prepare a no-write local PDF page/text/image inventory, quality report, artifact manifest, visual candidates, and visual extraction request using local tools when available."),
    "prepare_document_coverage_workbench": _metadata("prepare_document_coverage_workbench", "Prepare a no-write page-render/OCR/table coverage workbench packet with local page image refs, optional adapter observations, and explicit unavailable/skipped receipts."),
    "prepare_document_coverage_pass": _metadata("prepare_document_coverage_pass", "Prepare automatic image/OCR/table coverage evidence for a document ingestion record and write only a sanitized job-event receipt; active memories and graph edges remain untouched.", cost_class="medium-write", write_behavior="review_record"),
    "prepare_document_intake_review": _metadata("prepare_document_intake_review", "Prepare a no-write end-to-end document intake review packet from local disassembly, text preview, quality, coverage receipts, and follow-up extraction requests."),
    "preview_document_source_connector": _metadata("preview_document_source_connector", "Preview local Markdown/text/HTML extraction arguments plus URL/external parser request arguments without writing memory."),
    "prepare_document_extraction_request": _metadata("prepare_document_extraction_request", "Prepare a no-write external document parsing request for PDF/DOCX/image-bearing sources."),
    "prepare_document_extraction_result": _metadata("prepare_document_extraction_result", "Normalize external parser output into no-write preview arguments and provenance."),
    "preview_document_extraction": _metadata("preview_document_extraction", "Preview text/markdown document evidence and chunks without writing memory."),
    "prepare_document_draft": _metadata("prepare_document_draft", "Prepare a no-write document draft with proposed memories and graph edges."),
    "prepare_document_understanding_packet": _metadata("prepare_document_understanding_packet", "Normalize agent-supplied document understanding into reviewable summary slots, claim/concept/entity candidates, high-value sections, low-confidence warnings, draft memory proposals, and supplied plus auto-generated coverage graph edge proposals."),
    "prepare_document_promotion_transaction": _metadata("prepare_document_promotion_transaction", "Prepare a no-write operation plan for reviewed document draft promotion."),
    "apply_document_promotion_transaction": _metadata("apply_document_promotion_transaction", "Apply reviewed document promotion memory or graph writes only after explicit accept=True.", stability="stable", cost_class="write", write_behavior="explicit_acceptance", requires_acceptance=True),
    "prepare_document_ingestion_plan": _metadata("prepare_document_ingestion_plan", "Prepare a resumable no-write Document Intelligence Ingestion plan for a local document.", cost_class="medium", write_behavior="read_only"),
    "run_document_ingestion": _metadata("run_document_ingestion", "Run or continue an accepted Document Intelligence Ingestion job, storing evidence and promoting selected graph or memory operations.", cost_class="medium-write", write_behavior="explicit_acceptance", requires_acceptance=True),
    "resume_document_ingestion": _metadata("resume_document_ingestion", "Resume an accepted Document Intelligence Ingestion job from durable checkpoints.", cost_class="medium-write", write_behavior="explicit_acceptance", requires_acceptance=True),
    "inspect_document_ingestion": _metadata("inspect_document_ingestion", "Inspect searchable, graph, OCR, visual, table, semantic, and usable states for a document ingestion job.", cost_class="low", write_behavior="read_only"),
    "prepare_document_artifact_store": _metadata("prepare_document_artifact_store", "Prepare an explicit reviewed document evidence artifact-store transaction; no active memory or graph edges are promoted.", cost_class="medium-write"),
    "store_document_artifact": _metadata("store_document_artifact", "Store ledgered document evidence artifacts only when accept=True and the matching reviewed packet is supplied again; active memories and graph edges remain untouched.", cost_class="medium-write", write_behavior="explicit_acceptance", requires_acceptance=True),
    "prepare_document_ingestion_completion": _metadata("prepare_document_ingestion_completion", "Validate that staged document evidence has complete visual/OCR/table coverage, cited understanding, and reviewed graph promotion before it can be marked usable.", cost_class="medium", write_behavior="read_only"),
    "complete_document_ingestion": _metadata("complete_document_ingestion", "Mark a staged document usable only after full reviewed coverage and selected graph evidence are applied with accept=True.", stability="stable", cost_class="write", write_behavior="explicit_acceptance", requires_acceptance=True),
    "prepare_visual_extraction_request": _metadata("prepare_visual_extraction_request", "Prepare a no-write OCR/vision work request for image-bearing documents; visual interpretation and per-image-ref coverage are required before draft promotion."),
    "preview_visual_extraction": _metadata("preview_visual_extraction", "Preview caller-supplied OCR or vision observations as visual evidence without writing memory; pass visual_request to enforce requested image-ref coverage."),
    "retrieval_eval": _metadata("retrieval_eval", "Run deterministic retrieval quality checks and report pass/fail scenarios."),
    "list_workflow_templates": _metadata("list_workflow_templates", "List agent workflow recipes for common Engram usage patterns."),
    "list_memories": _metadata("list_memories", "Paginated structured directory metadata; no content.", stability="stable", cost_class="low"),
    "retrieve_chunk": _metadata("retrieve_chunk", "Structured single-chunk retrieval.", stability="stable", cost_class="low"),
    "retrieve_chunks": _metadata("retrieve_chunks", "Structured batch chunk retrieval.", stability="stable", cost_class="low-to-medium"),
    "retrieve_memory": _metadata("retrieve_memory", "Structured full-memory retrieval; token-expensive.", stability="stable", cost_class="high"),
    "store_memory": _metadata("store_memory", "Write or update a memory and return deterministic graph treatment for stored metadata.", stability="stable", cost_class="write", write_behavior="write"),
    "prepare_knowledge_branch": _metadata("prepare_knowledge_branch", "Prepare a Knowledge Branch review record for staged memory changes without promoting active memory or graph edges.", cost_class="medium-write", write_behavior="review_record"),
    "prepare_knowledge_pr": _metadata("prepare_knowledge_pr", "Prepare a Knowledge PR review packet with proposed operations, source refs, and document refs without promoting active memory or graph edges.", cost_class="medium-write", write_behavior="review_record"),
    "run_memory_ci": _metadata("run_memory_ci", "Run deterministic Memory CI gates for a Knowledge PR and record the CI receipt without promoting active memory or graph edges.", cost_class="medium-write", write_behavior="review_record"),
    "inspect_knowledge_pr": _metadata("inspect_knowledge_pr", "Inspect a Knowledge PR, its latest CI status, and mergeability without writing.", cost_class="low", write_behavior="read_only"),
    "merge_knowledge_pr": _metadata("merge_knowledge_pr", "Merge selected reviewed Knowledge PR operations through daemon-owned write services only after explicit accept=True and approved_by.", stability="stable", cost_class="write", write_behavior="explicit_acceptance", requires_acceptance=True),
    "list_memory_benchmark_suites": _metadata("list_memory_benchmark_suites", "List deterministic Memory CI benchmark suites without running them.", stability="stable", cost_class="low", write_behavior="read_only"),
    "run_memory_benchmark": _metadata("run_memory_benchmark", "Run a deterministic Memory CI benchmark suite and optionally persist a benchmark_runs receipt plus content-addressed artifact without promoting active memory.", stability="stable", cost_class="medium-write", write_behavior="review_record"),
    "inspect_benchmark_run": _metadata("inspect_benchmark_run", "Inspect one persisted Memory CI benchmark run receipt without loading active memory bodies.", stability="stable", cost_class="low", write_behavior="read_only"),
    "ensure_sync_device_identity": _metadata("ensure_sync_device_identity", "Ensure this Memory OS runtime has a public sync device identity without exposing private keys.", stability="stable", cost_class="low-write", write_behavior="review_record"),
    "export_local_sync_identity": _metadata("export_local_sync_identity", "Export the local public sync identity packet for reviewed peer pairing.", stability="stable", cost_class="low", write_behavior="read_only"),
    "register_sync_peer": _metadata("register_sync_peer", "Register a reviewed peer public sync identity packet after explicit accept=True and approved_by.", stability="stable", cost_class="medium-write", write_behavior="explicit_acceptance", requires_acceptance=True),
    "inspect_sync_state": _metadata("inspect_sync_state", "Inspect local sync identity, peer, cursor, changeset, and conflict state without writing.", stability="stable", cost_class="low", write_behavior="read_only"),
    "prepare_sync_changeset": _metadata("prepare_sync_changeset", "Prepare a no-write reviewed row/object plan for a signed encrypted peer changeset.", stability="stable", cost_class="medium", write_behavior="read_only"),
    "export_sync_changeset": _metadata("export_sync_changeset", "Export a reviewed sync changeset as a signed encrypted content-addressed bundle only after explicit accept=True and approved_by.", stability="stable", cost_class="medium-write", write_behavior="explicit_acceptance", requires_acceptance=True),
    "prepare_sync_apply": _metadata("prepare_sync_apply", "Decrypt, verify, and classify an encrypted sync bundle without writing; returns apply, idempotent, and conflict counts for review.", stability="stable", cost_class="medium", write_behavior="read_only"),
    "apply_sync_changeset": _metadata("apply_sync_changeset", "Re-verify and apply a reviewed sync bundle only after explicit accept=True and approved_by, creating a restore-grade snapshot first.", stability="stable", cost_class="medium-write", write_behavior="explicit_acceptance", requires_acceptance=True),
    "inspect_sync_convergence": _metadata("inspect_sync_convergence", "Inspect unresolved conflicts for a registered sync peer without writing.", stability="stable", cost_class="low", write_behavior="read_only"),
    "list_sync_conflicts": _metadata("list_sync_conflicts", "List sync conflict review records without exposing full remote payload bodies.", stability="stable", cost_class="low", write_behavior="read_only"),
    "resolve_sync_conflict": _metadata("resolve_sync_conflict", "Mark a sync conflict reviewed only after explicit accept=True and approved_by; memory overwrites remain Knowledge PR mediated.", stability="stable", cost_class="medium-write", write_behavior="explicit_acceptance", requires_acceptance=True),
    "configure_sync_peer_transport": _metadata("configure_sync_peer_transport", "Attach reviewed LAN/Tailscale sync listener coordinates to a registered peer only after explicit accept=True and approved_by.", stability="stable", cost_class="medium-write", write_behavior="explicit_acceptance", requires_acceptance=True),
    "inspect_sync_peer": _metadata("inspect_sync_peer", "Inspect one registered sync peer and its reviewed transport coordinates without exposing private keys.", stability="stable", cost_class="low", write_behavior="read_only"),
    "push_sync_changeset": _metadata("push_sync_changeset", "Prepare, export, and push a reviewed signed encrypted changeset to a configured sync-only peer listener only after explicit accept=True and approved_by.", stability="stable", cost_class="medium-write", write_behavior="explicit_acceptance", requires_acceptance=True),
    "list_sync_inbox": _metadata("list_sync_inbox", "List encrypted inbound sync bundles staged in the local inbox without applying them or returning bundle bytes.", stability="stable", cost_class="low", write_behavior="read_only"),
    "prepare_sync_inbox_apply": _metadata("prepare_sync_inbox_apply", "Prepare a compact no-write plan for applying already staged sync inbox bundles without returning bundle bytes.", stability="stable", cost_class="medium", write_behavior="read_only"),
    "apply_sync_inbox": _metadata("apply_sync_inbox", "Apply already staged signed sync inbox bundles only after explicit accept=True and approved_by, without accepting arbitrary bundle bytes over the hub.", stability="stable", cost_class="medium-write", write_behavior="explicit_acceptance", requires_acceptance=True),
    "prepare_memory": _metadata("prepare_memory", "Draft key/metadata/validation before storing.", stability="stable", cost_class="low"),
    "check_duplicate": _metadata("check_duplicate", "Preview semantic duplicate risk without writing.", stability="stable", cost_class="low-to-medium"),
    "suggest_memory_metadata": _metadata("suggest_memory_metadata", "Suggest key, title, tags, and metadata from content.", stability="stable", cost_class="low"),
    "validate_memory": _metadata("validate_memory", "Validate a proposed memory payload before storing.", stability="stable", cost_class="low"),
    "update_memory_metadata": _metadata("update_memory_metadata", "Update memory metadata without rewriting content.", stability="stable", cost_class="write", write_behavior="write"),
    "get_related_memories": _metadata("get_related_memories", "Traverse explicit related_to links without loading unrelated bodies.", stability="stable", cost_class="low-to-medium"),
    "get_stale_memories": _metadata("get_stale_memories", "Surface stale or potentially stale memories.", stability="stable", cost_class="low"),
    "delete_memory": _metadata("delete_memory", "Delete a memory intentionally by key.", stability="stable", cost_class="write", write_behavior="write"),
    "graph_backend_status": _metadata("graph_backend_status", "Report JSON graph, optional Kuzu, backend config intent, migrated graph-edge, graph-parity, and daemon-readiness gates without changing live graph storage."),
    "prepare_graph_readiness_report": _metadata("prepare_graph_readiness_report", "Inventory graphable Memory OS memories and usable documents without reading full bodies or writing graph edges.", stability="stable", cost_class="low", write_behavior="read_only"),
    "prepare_graph_proposal_batch": _metadata("prepare_graph_proposal_batch", "Prepare bounded cited source context and validate agent-supplied candidate graph edges without writing them.", stability="stable", cost_class="medium", write_behavior="read_only"),
    "apply_graph_proposal_batch": _metadata("apply_graph_proposal_batch", "Promote reviewed graph proposal edges and concept/entity refs only after explicit accept=True and approved_by.", stability="stable", cost_class="write", write_behavior="explicit_acceptance", requires_acceptance=True),
    "repair_graph_edge_refs": _metadata("repair_graph_edge_refs", "Add compact key/id identities to graph edge refs after explicit accept=True and approved_by; dry-run by default.", stability="stable", cost_class="medium-write", write_behavior="explicit_acceptance", requires_acceptance=True),
    "repair_graph_store_reconciliation": _metadata("repair_graph_store_reconciliation", "Replay exact ledger graph-edge records into the graph store after explicit accept=True and approved_by; dry-run by default.", stability="stable", cost_class="medium-write", write_behavior="explicit_acceptance", requires_acceptance=True),
    "read_codebase_mapping_config": _metadata("read_codebase_mapping_config", "Read a repo .engram/config.json when present."),
    "draft_codebase_mapping_config": _metadata("draft_codebase_mapping_config", "Draft a safe .engram/config.json for a repo without writing it."),
    "store_codebase_mapping_config": _metadata("store_codebase_mapping_config", "Validate and write a repo .engram/config.json with overwrite protection.", cost_class="write", write_behavior="write"),
    "preview_codebase_mapping": _metadata("preview_codebase_mapping", "Dry-run configured mapping domains without writing a mapping job."),
    "prepare_codebase_mapping": _metadata("prepare_codebase_mapping", "Scan a configured repo and prepare source-hashed, bounded context jobs for the connected agent to synthesize."),
    "read_codebase_mapping_context": _metadata("read_codebase_mapping_context", "Read a prepared mapping job context part for agent synthesis."),
    "store_codebase_mapping_result": _metadata("store_codebase_mapping_result", "Store an agent-authored mapping result after source-drift checks.", cost_class="write", write_behavior="write"),
    "install_codebase_mapping_hook": _metadata("install_codebase_mapping_hook", "Install the optional post-commit mapping hook after explicit intent.", cost_class="write", write_behavior="write"),
    "usage_summary": _metadata("usage_summary", "Engram-attributed token estimate rollups; not billed model usage."),
    "list_operation_jobs": _metadata("list_operation_jobs", "List recent local operation/job receipts."),
    "list_operation_events": _metadata("list_operation_events", "List recent local operation event records."),
    "daemon_status": _metadata("daemon_status", "Report whether stable memory tools will run direct in-process or through a configured ENGRAM_DAEMON_URL daemon, plus autostart eligibility."),
    "migration_dry_run": _metadata("migration_dry_run", "Validate legacy JSON memories against the Memory OS ledger schema without writing."),
    "memory_os_round_trip_check": _metadata("memory_os_round_trip_check", "Run legacy import/export/restore parity checks in a migration work directory without active memory writes."),
    "prepare_legacy_memory_os_migration": _metadata("prepare_legacy_memory_os_migration", "Prepare a no-write reviewed legacy JSON to daemon-owned Memory OS migration transaction."),
    "apply_legacy_memory_os_migration": _metadata("apply_legacy_memory_os_migration", "Apply reviewed legacy JSON migration writes through daemon-owned Memory OS only after accept=True and approved_by.", cost_class="write", write_behavior="explicit_acceptance", requires_acceptance=True),
    "prepare_legacy_related_to_graph_migration": _metadata("prepare_legacy_related_to_graph_migration", "Prepare a no-write migration transaction for legacy related_to graph evidence with lifecycle skips and missing-ref counts."),
    "apply_legacy_related_to_graph_migration": _metadata("apply_legacy_related_to_graph_migration", "Apply reviewed legacy related_to graph edges through daemon-owned Memory OS only after accept=True and approved_by.", cost_class="write", write_behavior="explicit_acceptance", requires_acceptance=True),
    "retrieval_backend_status": _metadata("retrieval_backend_status", "Report legacy Chroma, optional LanceDB, backend config intent, migrated-store, rebuild-probe, and golden-comparison readiness without changing live retrieval."),
}

THIN_CLIENT_LOCAL_TOOLS = frozenset({"memory_protocol", "daemon_status"})
TOOL_ALIASES = {
    "find_memories": "search_memories",
    "read_chunk": "retrieve_chunk",
    "read_memory": "retrieve_memory",
    "write_memory": "store_memory",
}
DAEMON_STATUS_ROUTE_EXCLUSIONS = frozenset(
    {
        "health",
        "memory_os_status",
        "memory_os_inspector",
        "memory_os_source_import_job",
        "repair_document_metadata",
    }
)


def daemon_route(name: str) -> DaemonRouteMetadata:
    try:
        return DAEMON_ROUTES[name]
    except KeyError as exc:
        raise KeyError(f"unknown daemon route: {name}") from exc


def daemon_route_path(name: str) -> str:
    return daemon_route(name).path


def daemon_route_method(name: str) -> str:
    return daemon_route(name).method


def concurrent_daemon_route_paths() -> set[str]:
    return {route.path for route in DAEMON_ROUTES.values() if route.concurrent}


def daemon_route_backed_thin_tools() -> set[str]:
    return set(THIN_CLIENT_CANONICAL_TOOLS) - set(THIN_CLIENT_LOCAL_TOOLS)


def full_server_daemon_routed_tools() -> list[str]:
    """Return full-server MCP tools that route through engramd when configured."""
    full_tools = expected_full_mcp_tools()
    routed = [
        name
        for name in DAEMON_ROUTES
        if name in full_tools and name not in DAEMON_STATUS_ROUTE_EXCLUSIONS
    ]
    routed.extend(
        alias
        for alias, target in TOOL_ALIASES.items()
        if alias in full_tools and target in routed
    )
    return _unique_tool_list(routed)


def expected_daemon_client_methods() -> set[str]:
    return set(DAEMON_ROUTES)


def expected_thin_mcp_tools() -> set[str]:
    expected = set(THIN_CLIENT_CANONICAL_TOOLS)
    expected.update(TOOL_ALIASES)
    for group in THIN_CLIENT_TOOL_GROUPS.values():
        expected.update(group.get("tools", []))
    return expected


def expected_full_mcp_tools() -> set[str]:
    expected = {"memory_protocol"}
    expected.update(CANONICAL_TOOLS)
    expected.update(TOOL_ALIASES)
    for group in TOOL_GROUPS.values():
        expected.update(group.get("tools", []))
    return expected


def validate_mcp_tool_surface(
    actual_tools: set[str],
    *,
    thin_client: bool = False,
) -> list[str]:
    expected = expected_thin_mcp_tools() if thin_client else expected_full_mcp_tools()
    missing = sorted(expected - actual_tools)
    extra = sorted(actual_tools - expected)
    errors: list[str] = []
    if missing:
        errors.append(f"MCP tool surface missing registered tools: {', '.join(missing)}")
    if extra:
        errors.append(f"MCP tool surface has unregistered tools: {', '.join(extra)}")
    return errors


def validate_daemon_route_registry(
    *,
    api_paths: set[str] | None = None,
    client_methods: set[str] | None = None,
    thin_client_tools: set[str] | None = None,
) -> list[str]:
    """Return drift errors between daemon routes, clients, and advertised tools."""
    errors: list[str] = []
    route_names = set(DAEMON_ROUTES)
    route_paths = {route.path for route in DAEMON_ROUTES.values()}

    if api_paths is not None:
        missing_paths = sorted(route_paths - api_paths)
        extra_paths = sorted(api_paths - route_paths)
        if missing_paths:
            errors.append(f"daemon API missing registered paths: {', '.join(missing_paths)}")
        if extra_paths:
            errors.append(f"daemon API has unregistered paths: {', '.join(extra_paths)}")

    if client_methods is not None:
        ignored_methods = {"_request", "_tool_request"}
        public_methods = {name for name in client_methods if not name.startswith("_")}
        public_methods -= ignored_methods
        expected_methods = expected_daemon_client_methods()
        missing_methods = sorted(expected_methods - public_methods)
        extra_methods = sorted(public_methods - expected_methods)
        if missing_methods:
            errors.append(f"daemon client missing registered methods: {', '.join(missing_methods)}")
        if extra_methods:
            errors.append(f"daemon client has unregistered methods: {', '.join(extra_methods)}")

    if thin_client_tools is not None:
        required_route_tools = daemon_route_backed_thin_tools()
        missing_tool_routes = sorted(required_route_tools - route_names)
        missing_advertised = sorted(required_route_tools - thin_client_tools)
        if missing_tool_routes:
            errors.append(f"thin canonical tools lack daemon routes: {', '.join(missing_tool_routes)}")
        if missing_advertised:
            errors.append(f"thin canonical route tools not advertised: {', '.join(missing_advertised)}")

    return errors


def _clone_group(group: dict[str, Any]) -> dict[str, Any]:
    cloned = dict(group)
    for key in ("tools", "task_types"):
        if key in cloned:
            cloned[key] = list(cloned[key])
    return cloned


def _clone_groups(groups: dict[str, dict[str, Any]], *, include_beta: bool = True) -> dict[str, dict[str, Any]]:
    cloned: dict[str, dict[str, Any]] = {}
    for name, group in groups.items():
        if not include_beta and group.get("stability") == "beta":
            continue
        cloned[name] = _clone_group(group)
    return cloned


def build_memory_protocol_sections(*, include_beta: bool = True, thin_client: bool = False) -> dict[str, Any]:
    """Build shared protocol metadata sections for MCP entrypoints."""
    memory_taxonomy = {
        "memory_types": list(MEMORY_TYPES),
        "memory_scopes": list(MEMORY_SCOPES),
        "trust_states": list(TRUST_STATES),
        "retention_policies": list(RETENTION_POLICIES),
        "sync_policies": list(SYNC_POLICIES),
    }
    if thin_client:
        return {
            "tool_groups": _clone_groups(THIN_CLIENT_TOOL_GROUPS, include_beta=include_beta),
            "aliases": dict(TOOL_ALIASES),
            "knowledge_contract": {
                "tool": "query_knowledge",
                "contract_version": "engram.knowledge.request.v0",
                "response_version": "engram.knowledge.response.v0",
                "release_track": "1.0",
                "stability": "stable",
                "task_types": list(STABLE_EKC_TASK_TYPES),
                "scope": ", ".join(STABLE_EKC_TASK_TYPES),
            },
            "document_workflow": list(STABLE_DOCUMENT_WORKFLOW),
            "document_artifact_workflow": list(DOCUMENT_ARTIFACT_WORKFLOW),
            "knowledge_pr_workflow": list(KNOWLEDGE_PR_WORKFLOW),
            "benchmark_workflow": list(BENCHMARK_WORKFLOW),
            "sync_identity_workflow": list(SYNC_IDENTITY_WORKFLOW),
            "sync_changeset_workflow": list(SYNC_CHANGESET_WORKFLOW),
            "sync_transport_workflow": list(SYNC_TRANSPORT_WORKFLOW),
            "canonical_tools": list(THIN_CLIENT_CANONICAL_TOOLS),
            "memory_taxonomy": memory_taxonomy,
        }
    return {
        "stability": dict(PROTOCOL_STABILITY),
        "tool_groups": _clone_groups(TOOL_GROUPS, include_beta=include_beta),
        "progressive_discovery": {
            "start_here": PROGRESSIVE_DISCOVERY["start_here"],
            "load_next": dict(PROGRESSIVE_DISCOVERY["load_next"]),
        },
        "canonical_tools": {
            name: metadata.description for name, metadata in CANONICAL_TOOLS.items()
        },
        "memory_taxonomy": memory_taxonomy,
    }


def validate_protocol_sections(protocol_payload: dict[str, Any], *, thin_client: bool = False) -> list[str]:
    """Return registry drift errors for an MCP memory_protocol payload."""
    expected = build_memory_protocol_sections(thin_client=thin_client)
    errors: list[str] = []
    for section, expected_value in expected.items():
        if protocol_payload.get(section) != expected_value:
            errors.append(f"{section} does not match core.mcp.tool_registry")

    if thin_client:
        canonical_names = set(protocol_payload.get("canonical_tools") or [])
        errors.extend(validate_daemon_route_registry(thin_client_tools=canonical_names))
        required_names = (
            set(STABLE_DOCUMENT_WORKFLOW)
            | set(DOCUMENT_ARTIFACT_WORKFLOW)
            | set(KNOWLEDGE_PR_WORKFLOW)
            | set(BENCHMARK_WORKFLOW)
            | set(SYNC_IDENTITY_WORKFLOW)
            | set(SYNC_CHANGESET_WORKFLOW)
            | set(SYNC_TRANSPORT_WORKFLOW)
            | set(GRAPH_PIPELINE_WORKFLOW)
            | {"query_knowledge"}
        )
        missing = sorted(required_names - canonical_names)
        if missing:
            errors.append(f"thin canonical_tools missing: {', '.join(missing)}")
    else:
        canonical = protocol_payload.get("canonical_tools") or {}
        for name, metadata in CANONICAL_TOOLS.items():
            if canonical.get(name) != metadata.description:
                errors.append(f"canonical tool drift: {name}")
        groups = protocol_payload.get("tool_groups") or {}
        for name in TOOL_GROUPS:
            if name not in groups:
                errors.append(f"tool group missing: {name}")

    promotion = CANONICAL_TOOLS["apply_document_promotion_transaction"]
    if promotion.write_behavior != "explicit_acceptance" or not promotion.requires_acceptance:
        errors.append("apply_document_promotion_transaction must require explicit acceptance")
    for ingestion_tool_name in ("run_document_ingestion", "resume_document_ingestion"):
        ingestion_tool = CANONICAL_TOOLS[ingestion_tool_name]
        if ingestion_tool.write_behavior != "explicit_acceptance" or not ingestion_tool.requires_acceptance:
            errors.append(f"{ingestion_tool_name} must require explicit acceptance")
    completion = CANONICAL_TOOLS["complete_document_ingestion"]
    if completion.write_behavior != "explicit_acceptance" or not completion.requires_acceptance:
        errors.append("complete_document_ingestion must require explicit acceptance")
    graph_apply = CANONICAL_TOOLS["apply_graph_proposal_batch"]
    if graph_apply.write_behavior != "explicit_acceptance" or not graph_apply.requires_acceptance:
        errors.append("apply_graph_proposal_batch must require explicit acceptance")
    graph_repair = CANONICAL_TOOLS["repair_graph_edge_refs"]
    if graph_repair.write_behavior != "explicit_acceptance" or not graph_repair.requires_acceptance:
        errors.append("repair_graph_edge_refs must require explicit acceptance")
    graph_store_repair = CANONICAL_TOOLS["repair_graph_store_reconciliation"]
    if graph_store_repair.write_behavior != "explicit_acceptance" or not graph_store_repair.requires_acceptance:
        errors.append("repair_graph_store_reconciliation must require explicit acceptance")
    knowledge_merge = CANONICAL_TOOLS["merge_knowledge_pr"]
    if knowledge_merge.write_behavior != "explicit_acceptance" or not knowledge_merge.requires_acceptance:
        errors.append("merge_knowledge_pr must require explicit acceptance")
    legacy_apply = CANONICAL_TOOLS["apply_legacy_memory_os_migration"]
    if legacy_apply.write_behavior != "explicit_acceptance" or not legacy_apply.requires_acceptance:
        errors.append("apply_legacy_memory_os_migration must require explicit acceptance")
    legacy_graph_apply = CANONICAL_TOOLS["apply_legacy_related_to_graph_migration"]
    if legacy_graph_apply.write_behavior != "explicit_acceptance" or not legacy_graph_apply.requires_acceptance:
        errors.append("apply_legacy_related_to_graph_migration must require explicit acceptance")
    sync_export = CANONICAL_TOOLS["export_sync_changeset"]
    if sync_export.write_behavior != "explicit_acceptance" or not sync_export.requires_acceptance:
        errors.append("export_sync_changeset must require explicit acceptance")
    sync_apply = CANONICAL_TOOLS["apply_sync_changeset"]
    if sync_apply.write_behavior != "explicit_acceptance" or not sync_apply.requires_acceptance:
        errors.append("apply_sync_changeset must require explicit acceptance")
    sync_resolve = CANONICAL_TOOLS["resolve_sync_conflict"]
    if sync_resolve.write_behavior != "explicit_acceptance" or not sync_resolve.requires_acceptance:
        errors.append("resolve_sync_conflict must require explicit acceptance")
    sync_configure = CANONICAL_TOOLS["configure_sync_peer_transport"]
    if sync_configure.write_behavior != "explicit_acceptance" or not sync_configure.requires_acceptance:
        errors.append("configure_sync_peer_transport must require explicit acceptance")
    sync_push = CANONICAL_TOOLS["push_sync_changeset"]
    if sync_push.write_behavior != "explicit_acceptance" or not sync_push.requires_acceptance:
        errors.append("push_sync_changeset must require explicit acceptance")
    sync_inbox_apply = CANONICAL_TOOLS["apply_sync_inbox"]
    if sync_inbox_apply.write_behavior != "explicit_acceptance" or not sync_inbox_apply.requires_acceptance:
        errors.append("apply_sync_inbox must require explicit acceptance")
    return errors
