from __future__ import annotations

from copy import deepcopy
from typing import Any

WORKFLOW_TEMPLATE_SCHEMA_VERSION = "2026-04-30.workflow-templates.v1"

_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "resume_repo",
        "label": "Resume a brownfield repo",
        "purpose": "Load just enough durable context to continue a repo without overwriting its habits.",
        "recommended_tools": [
            "memory_protocol",
            "context_pack",
            "read_codebase_mapping_config",
            "prepare_codebase_mapping",
        ],
        "steps": [
            "Call memory_protocol to refresh the current retrieval ladder and token-safety rules.",
            "Call context_pack with the repo path or project name, use_graph=False by default.",
            "Read the codebase mapping config; draft one if the repo is not configured.",
            "Prepare a codebase mapping only when live source context is needed beyond memory.",
            "Store a concise memory after the work session with validation and next steps.",
        ],
    },
    {
        "id": "compile_task_context",
        "label": "Compile task context",
        "purpose": "Build a no-write, cited working packet for a specific agent task.",
        "recommended_tools": [
            "memory_protocol",
            "list_context_profiles",
            "prepare_context",
            "retrieve_chunk",
        ],
        "steps": [
            "Call memory_protocol to refresh retrieval rules before choosing a profile.",
            "List context profiles and choose the smallest profile that fits the task.",
            "Call prepare_context with task, profile, and project or domain filters when available.",
            "Use retrieve_chunk only for cited refs that need more text than the packet returned.",
            "Treat warnings as review prompts; prepare_context is no-write and does not resolve stale or conflicting memory.",
        ],
    },
    {
        "id": "prepare_session_handoff",
        "label": "Prepare session handoff",
        "purpose": "Create a no-write resume packet before ending or transferring an agent session.",
        "recommended_tools": [
            "memory_protocol",
            "prepare_context",
            "make_handoff",
            "write_memory",
        ],
        "steps": [
            "Call prepare_context first if the next session needs fresh cited working context.",
            "Call make_handoff with concrete next steps, validation, blockers, and project filters.",
            "Review the handoff packet and resume prompt before storing or sharing it.",
            "Use write_memory only after an explicit closeout decision; make_handoff itself is no-write.",
        ],
    },
    {
        "id": "prepare_project_capsule_review",
        "label": "Prepare project capsule review",
        "purpose": "Draft a project capsule from context refs and quality signals without promoting it to memory.",
        "recommended_tools": [
            "memory_protocol",
            "prepare_context",
            "audit_memory_quality",
            "prepare_project_capsule",
        ],
        "steps": [
            "Call prepare_context for the current project question before asking for a capsule.",
            "Run audit_memory_quality to expose scope, lifecycle, and chunking risks.",
            "Call prepare_project_capsule to combine cited refs with quality signals.",
            "Review capsule warnings before using it as a project summary; the capsule draft is no-write.",
        ],
    },
    {
        "id": "review_memory_health",
        "label": "Review memory health",
        "purpose": "Inspect quality, conflicts, and eval health before changing retrieval or storage behavior.",
        "recommended_tools": [
            "memory_protocol",
            "audit_memory_quality",
            "conflict_scan",
            "retrieval_eval",
            "list_usage_calls",
        ],
        "steps": [
            "Run audit_memory_quality with project or domain filters before loading memory bodies.",
            "Call conflict_scan for contradiction, invalidation, and supersession edges relevant to the task.",
            "Run retrieval_eval when changing agent workflow, retrieval, storage, or graph behavior.",
            "Keep findings explicit and review-first; these tools inspect state but do not repair or promote memory.",
        ],
    },
    {
        "id": "extract_decisions_from_source",
        "label": "Extract decisions from source",
        "purpose": "Turn transcripts, meetings, and logs into reviewable draft memories.",
        "recommended_tools": [
            "list_ingestion_pipelines",
            "preview_memory_chunks",
            "prepare_source_memory",
            "store_prepared_memory",
        ],
        "steps": [
            "List ingestion pipelines and choose transcript, design_doc, handoff, code_scan, or generic.",
            "Preview memory chunks before storing so boundaries and token shape are visible.",
            "Prepare source memory with the chosen pipeline; review proposed memories and edges.",
            "Promote only selected draft items with store_prepared_memory after explicit review.",
        ],
    },
    {
        "id": "map_brownfield_repo",
        "label": "Map a brownfield repo",
        "purpose": "Create an agent-authored architecture map without provider-specific subprocesses.",
        "recommended_tools": [
            "draft_codebase_mapping_config",
            "preview_codebase_mapping",
            "prepare_codebase_mapping",
            "store_codebase_mapping_result",
        ],
        "steps": [
            "Draft or read the repo mapping config and inspect fanout-pruned domains.",
            "Preview mapping scope before preparing bounded context.",
            "Prepare mapping context and synthesize the map in the connected agent.",
            "Store the result only if source hashes are still current, or force with explicit reason.",
        ],
    },
    {
        "id": "measure_retrieval_quality",
        "label": "Measure retrieval quality",
        "purpose": "Check whether Engram retrieval is still useful before adding heavier storage layers.",
        "recommended_tools": [
            "retrieval_eval",
            "usage_summary",
            "list_usage_calls",
        ],
        "steps": [
            "Run retrieval_eval for deterministic memory retrieval quality checks.",
            "Review usage_summary to see Engram-attributed token estimates and outliers.",
            "Use list_usage_calls to find expensive call shapes before changing retrieval defaults.",
        ],
    },
]


def list_workflow_templates() -> dict[str, Any]:
    """Return static agent workflow recipes for common Engram jobs."""
    return {
        "schema_version": WORKFLOW_TEMPLATE_SCHEMA_VERSION,
        "templates": deepcopy(_TEMPLATES),
    }
