from __future__ import annotations

from copy import deepcopy
from typing import Any

PIPELINE_SCHEMA_VERSION = "2026-04-30.ingestion-pipelines.v1"

_PIPELINES: dict[str, dict[str, Any]] = {
    "generic": {
        "id": "generic",
        "label": "Generic source",
        "description": "Safe default for notes, logs, and mixed source material.",
        "memory_status": "draft",
        "extract_prefixes": ["decision", "action", "risk", "note"],
        "tags": ["source-intake"],
        "stages": [
            "normalize_source_text",
            "extract_prefixed_lines",
            "compose_reviewable_draft",
        ],
    },
    "transcript": {
        "id": "transcript",
        "label": "Transcript",
        "description": "Condense meeting or video transcripts into decisions, actions, risks, questions, and insights.",
        "memory_status": "draft",
        "extract_prefixes": ["decision", "action", "risk", "question", "insight"],
        "tags": ["source-intake", "transcript"],
        "stages": [
            "normalize_source_text",
            "extract_prefixed_lines",
            "preserve_open_questions",
            "compose_reviewable_draft",
        ],
    },
    "code_scan": {
        "id": "code_scan",
        "label": "Code scan",
        "description": "Capture architecture findings from repo scans without importing every file as memory.",
        "memory_status": "draft",
        "extract_prefixes": ["decision", "action", "risk", "architecture", "invariant"],
        "tags": ["source-intake", "code-scan"],
        "stages": [
            "normalize_source_text",
            "extract_architecture_signals",
            "compose_reviewable_draft",
        ],
    },
    "design_doc": {
        "id": "design_doc",
        "label": "Design document",
        "description": "Extract durable design intent, constraints, and follow-ups from planning docs.",
        "memory_status": "draft",
        "extract_prefixes": ["decision", "constraint", "action", "risk", "open_question"],
        "tags": ["source-intake", "design-doc"],
        "stages": [
            "normalize_source_text",
            "extract_design_signals",
            "compose_reviewable_draft",
        ],
    },
    "handoff": {
        "id": "handoff",
        "label": "Handoff",
        "description": "Prepare session closeouts and next-step packets for durable memory review.",
        "memory_status": "draft",
        "extract_prefixes": ["decision", "action", "risk", "next", "validation"],
        "tags": ["source-intake", "handoff"],
        "stages": [
            "normalize_source_text",
            "extract_resume_points",
            "compose_reviewable_draft",
        ],
    },
}


def list_ingestion_pipelines() -> dict[str, Any]:
    """Return the no-write ingestion pipeline catalog for agent discovery."""
    return {
        "schema_version": PIPELINE_SCHEMA_VERSION,
        "default_pipeline": "generic",
        "pipelines": deepcopy(_PIPELINES),
    }


def resolve_ingestion_pipeline(pipeline: str | None) -> dict[str, Any]:
    """Resolve a pipeline id to a copy of its config."""
    pipeline_id = (pipeline or "generic").strip().lower().replace("-", "_")
    if not pipeline_id:
        pipeline_id = "generic"
    if pipeline_id not in _PIPELINES:
        valid = ", ".join(sorted(_PIPELINES))
        raise ValueError(f"Unknown ingestion pipeline '{pipeline}'. Valid pipelines: {valid}")
    return deepcopy(_PIPELINES[pipeline_id])
