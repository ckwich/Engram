"""Shared MCP tool metadata for protocol generation.

This module is intentionally data-first: MCP entrypoints should import these
sections instead of hand-maintaining parallel protocol lists.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.memory_os.knowledge_eval import STABLE_EKC_TASK_TYPES


@dataclass(frozen=True)
class ToolMetadata:
    name: str
    description: str
    stability: str
    cost_class: str = "varies"
    write_behavior: str = "read_only"
    requires_acceptance: bool = False


STABLE_DOCUMENT_WORKFLOW = [
    "list_document_extractors",
    "preview_document_source_connector",
    "prepare_document_disassembly",
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
]

DOCUMENT_ARTIFACT_WORKFLOW = [
    "prepare_document_artifact_store",
    "store_document_artifact",
]

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
    "review_helpers": "beta",
    "retrieval_quality": "beta",
    "retrieval_backend": "beta",
    "usage": "beta",
    "operations": "beta",
    "migration": "beta",
    "daemon_status": "beta",
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
        "purpose": "Prepare and store explicit ledgered document evidence artifacts without active memory or graph promotion.",
        "stability": "beta",
        "cost_class": "medium-write",
        "tools": DOCUMENT_ARTIFACT_WORKFLOW,
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
    "migration": {
        "purpose": "Validate Memory OS migration readiness without touching active memories.",
        "stability": "beta",
        "cost_class": "medium",
        "tools": ["migration_dry_run", "memory_os_round_trip_check"],
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

THIN_CLIENT_TOOL_GROUPS: dict[str, dict[str, Any]] = {
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
}

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
        "source ingestion": "prepare_source_memory",
        "source ingestion setup": "list_ingestion_pipelines",
        "chunk boundary review": "preview_memory_chunks",
        "document extraction": "preview_document_extraction",
        "document extractor discovery": "list_document_extractors",
        "document disassembly": "prepare_document_disassembly",
        "document intake review": "prepare_document_intake_review",
        "document extraction request": "prepare_document_extraction_request",
        "document extraction result": "prepare_document_extraction_result",
        "document source connector": "preview_document_source_connector",
        "document draft": "prepare_document_draft",
        "document understanding": "prepare_document_understanding_packet",
        "document promotion": "prepare_document_promotion_transaction",
        "document promotion acceptance": "apply_document_promotion_transaction",
        "document artifact store": "prepare_document_artifact_store",
        "document artifact acceptance": "store_document_artifact",
        "visual extraction request": "prepare_visual_extraction_request",
        "visual extraction": "preview_visual_extraction",
        "retrieval quality": "retrieval_eval",
        "codebase mapping": "prepare_codebase_mapping",
        "codebase mapping setup": "draft_codebase_mapping_config",
        "usage review": "usage_summary",
        "memory quality": "audit_memory_quality",
        "migration dry run": "migration_dry_run",
        "migration round trip": "memory_os_round_trip_check",
        "retrieval backend status": "retrieval_backend_status",
        "daemon status": "daemon_status",
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
    "audit_memory_quality": _metadata("audit_memory_quality", "Read-only metadata quality audit for scope, lifecycle, chunking, and retrieval risk signals."),
    "list_ingestion_pipelines": _metadata("list_ingestion_pipelines", "List no-write source-intake presets such as transcript, code_scan, design_doc, and handoff."),
    "conflict_scan": _metadata("conflict_scan", "List active contradiction, invalidation, and supersession graph edges without loading memory bodies."),
    "preview_memory_chunks": _metadata("preview_memory_chunks", "Show reviewable chunk boundaries before storing or promoting source material."),
    "preview_source_connector": _metadata("preview_source_connector", "Preview local-path source items and draft arguments without writing memory."),
    "list_document_extractors": _metadata("list_document_extractors", "List bundled and external document extraction capabilities without running providers."),
    "prepare_document_disassembly": _metadata("prepare_document_disassembly", "Prepare a no-write local PDF page/text/image inventory, quality report, artifact manifest, visual candidates, and visual extraction request using local tools when available."),
    "prepare_document_intake_review": _metadata("prepare_document_intake_review", "Prepare a no-write end-to-end document intake review packet from local disassembly, text preview, quality, coverage receipts, and follow-up extraction requests."),
    "preview_document_source_connector": _metadata("preview_document_source_connector", "Preview local Markdown/text/HTML extraction arguments plus URL/external parser request arguments without writing memory."),
    "prepare_document_extraction_request": _metadata("prepare_document_extraction_request", "Prepare a no-write external document parsing request for PDF/DOCX/image-bearing sources."),
    "prepare_document_extraction_result": _metadata("prepare_document_extraction_result", "Normalize external parser output into no-write preview arguments and provenance."),
    "preview_document_extraction": _metadata("preview_document_extraction", "Preview text/markdown document evidence and chunks without writing memory."),
    "prepare_document_draft": _metadata("prepare_document_draft", "Prepare a no-write document draft with proposed memories and graph edges."),
    "prepare_document_understanding_packet": _metadata("prepare_document_understanding_packet", "Normalize agent-supplied document understanding into reviewable summary slots, claim/concept/entity candidates, high-value sections, low-confidence warnings, draft memory proposals, and supplied plus auto-generated coverage graph edge proposals."),
    "prepare_document_promotion_transaction": _metadata("prepare_document_promotion_transaction", "Prepare a no-write operation plan for reviewed document draft promotion."),
    "apply_document_promotion_transaction": _metadata("apply_document_promotion_transaction", "Apply reviewed document promotion memory or graph writes only after explicit accept=True.", stability="stable", cost_class="write", write_behavior="explicit_acceptance", requires_acceptance=True),
    "prepare_document_artifact_store": _metadata("prepare_document_artifact_store", "Prepare an explicit reviewed document evidence artifact-store transaction; no active memory or graph edges are promoted.", cost_class="medium-write"),
    "store_document_artifact": _metadata("store_document_artifact", "Store ledgered document evidence artifacts only when accept=True and the matching reviewed packet is supplied again; active memories and graph edges remain untouched.", cost_class="medium-write", write_behavior="explicit_acceptance", requires_acceptance=True),
    "prepare_visual_extraction_request": _metadata("prepare_visual_extraction_request", "Prepare a no-write OCR/vision work request for image-bearing documents; visual interpretation and per-image-ref coverage are required before draft promotion."),
    "preview_visual_extraction": _metadata("preview_visual_extraction", "Preview caller-supplied OCR or vision observations as visual evidence without writing memory; pass visual_request to enforce requested image-ref coverage."),
    "retrieval_eval": _metadata("retrieval_eval", "Run deterministic retrieval quality checks and report pass/fail scenarios."),
    "list_workflow_templates": _metadata("list_workflow_templates", "List agent workflow recipes for common Engram usage patterns."),
    "list_memories": _metadata("list_memories", "Paginated structured directory metadata; no content.", stability="stable", cost_class="low"),
    "retrieve_chunk": _metadata("retrieve_chunk", "Structured single-chunk retrieval.", stability="stable", cost_class="low"),
    "retrieve_chunks": _metadata("retrieve_chunks", "Structured batch chunk retrieval.", stability="stable", cost_class="low-to-medium"),
    "retrieve_memory": _metadata("retrieve_memory", "Structured full-memory retrieval; token-expensive.", stability="stable", cost_class="high"),
    "store_memory": _metadata("store_memory", "Write or update a memory.", stability="stable", cost_class="write", write_behavior="write"),
    "prepare_memory": _metadata("prepare_memory", "Draft key/metadata/validation before storing.", stability="stable", cost_class="low"),
    "check_duplicate": _metadata("check_duplicate", "Preview semantic duplicate risk without writing.", stability="stable", cost_class="low-to-medium"),
    "suggest_memory_metadata": _metadata("suggest_memory_metadata", "Suggest key, title, tags, and metadata from content.", stability="stable", cost_class="low"),
    "validate_memory": _metadata("validate_memory", "Validate a proposed memory payload before storing.", stability="stable", cost_class="low"),
    "update_memory_metadata": _metadata("update_memory_metadata", "Update memory metadata without rewriting content.", stability="stable", cost_class="write", write_behavior="write"),
    "get_related_memories": _metadata("get_related_memories", "Traverse explicit related_to links without loading unrelated bodies.", stability="stable", cost_class="low-to-medium"),
    "get_stale_memories": _metadata("get_stale_memories", "Surface stale or potentially stale memories.", stability="stable", cost_class="low"),
    "delete_memory": _metadata("delete_memory", "Delete a memory intentionally by key.", stability="stable", cost_class="write", write_behavior="write"),
    "graph_backend_status": _metadata("graph_backend_status", "Report JSON graph, optional Kuzu, backend config intent, migrated graph-edge, graph-parity, and daemon-readiness gates without changing live graph storage."),
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
    "retrieval_backend_status": _metadata("retrieval_backend_status", "Report legacy Chroma, optional LanceDB, backend config intent, migrated-store, rebuild-probe, and golden-comparison readiness without changing live retrieval."),
}

THIN_CLIENT_CANONICAL_TOOLS = [
    "memory_protocol",
    "daemon_status",
    "memory_os_status",
    "query_knowledge",
    "search_memories",
    "retrieve_chunk",
    "retrieve_chunks",
    "retrieve_memory",
    "store_memory",
    "prepare_source_memory",
    *STABLE_DOCUMENT_WORKFLOW,
    *DOCUMENT_ARTIFACT_WORKFLOW,
]


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
    if thin_client:
        return {
            "tool_groups": _clone_groups(THIN_CLIENT_TOOL_GROUPS, include_beta=include_beta),
            "document_workflow": list(STABLE_DOCUMENT_WORKFLOW),
            "document_artifact_workflow": list(DOCUMENT_ARTIFACT_WORKFLOW),
            "canonical_tools": list(THIN_CLIENT_CANONICAL_TOOLS),
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
        required_names = set(STABLE_DOCUMENT_WORKFLOW) | set(DOCUMENT_ARTIFACT_WORKFLOW) | {"query_knowledge"}
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
    return errors

