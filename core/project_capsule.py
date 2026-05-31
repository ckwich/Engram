"""No-write project capsule draft helpers."""
from __future__ import annotations

from typing import Any

PROJECT_CAPSULE_SCHEMA_VERSION = "2026-05-11.project-capsule.v1"


def build_project_capsule_draft(
    *,
    project: str,
    task: str,
    summary: str | None,
    must_read_keys: str | list[str] | None,
    context_packet: dict[str, Any],
    quality_payload: dict[str, Any],
) -> dict[str, Any]:
    """Create a reviewable project capsule draft without storing it."""
    context = dict(context_packet.get("context") or {})
    context_chunks = list(context.get("chunks") or [])
    context_refs = [
        {"key": chunk.get("key"), "chunk_id": chunk.get("chunk_id"), "source": "context"}
        for chunk in context_chunks
        if chunk.get("key") is not None and chunk.get("chunk_id") is not None
    ]
    explicit_refs = [
        {"key": key, "source": "explicit"}
        for key in _normalize_text_list(must_read_keys)
    ]
    warnings = list(context_packet.get("warnings") or [])
    quality_summary = dict(quality_payload.get("summary") or {})
    if int(quality_summary.get("high_risk_count") or 0) > 0:
        warnings.append(
            {
                "code": "high_risk_memories",
                "message": "The project has high-risk memory quality findings; review audit_memory_quality before relying on the capsule.",
            }
        )

    return {
        "schema_version": PROJECT_CAPSULE_SCHEMA_VERSION,
        "record_type": "project_capsule_draft",
        "project": project,
        "task": str(task).strip(),
        "summary": str(summary).strip() if summary else "",
        "profile": (context_packet.get("profile") or {}).get("id"),
        "must_read": context_refs + explicit_refs,
        "citations": list(context.get("citations") or []),
        "quality_summary": quality_summary,
        "quality_issue_count": int(quality_payload.get("issue_count") or 0),
        "warnings": warnings,
        "next_actions": [
            {
                "tool": "prepare_context",
                "reason": "Refresh the capsule context before a long new work session.",
            },
            {
                "tool": "audit_memory_quality",
                "reason": "Review memory quality risks before treating capsule context as current.",
            },
            {
                "tool": "write_memory",
                "reason": "Only explicitly store a reviewed capsule if it should become durable memory.",
            },
        ],
        "write_policy": "draft_only",
        "write_performed": False,
        "active_memory_write_performed": False,
        "promotion_required": True,
    }


def _normalize_text_list(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    raw_items = value if isinstance(value, list) else [value]
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        for part in str(item).replace("\r\n", "\n").replace(",", "\n").split("\n"):
            text = part.strip()
            if not text or text in seen:
                continue
            seen.add(text)
            normalized.append(text)
    return normalized
