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
