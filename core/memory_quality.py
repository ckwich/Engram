"""Metadata-only memory quality audit helpers."""
from __future__ import annotations

from typing import Any

MEMORY_QUALITY_SCHEMA_VERSION = "2026-05-11.memory-quality.v1"
DEFAULT_LARGE_MEMORY_CHARS = 12000


def audit_memory_quality(
    memories: list[dict[str, Any]],
    *,
    limit: int = 100,
    offset: int = 0,
    max_memory_chars: int = DEFAULT_LARGE_MEMORY_CHARS,
) -> dict[str, Any]:
    """Return read-only quality signals from memory metadata only."""
    entries = [_quality_entry(memory, max_memory_chars=max_memory_chars) for memory in memories]
    total = len(entries)
    normalized_limit = max(int(limit), 0)
    normalized_offset = max(int(offset), 0)
    page = entries[normalized_offset:] if normalized_limit == 0 else entries[normalized_offset: normalized_offset + normalized_limit]

    return {
        "schema_version": MEMORY_QUALITY_SCHEMA_VERSION,
        "count": len(page),
        "total": total,
        "issue_count": sum(len(entry["issues"]) for entry in entries),
        "limit": normalized_limit,
        "offset": normalized_offset,
        "has_more": normalized_offset + len(page) < total,
        "summary": _summary(entries),
        "memories": page,
        "write_performed": False,
    }


def _quality_entry(memory: dict[str, Any], *, max_memory_chars: int) -> dict[str, Any]:
    issues = _quality_issues(memory, max_memory_chars=max_memory_chars)
    penalty = sum(int(issue["penalty"]) for issue in issues)
    score = max(0, 100 - penalty)
    return {
        "key": memory.get("key"),
        "title": memory.get("title") or memory.get("key"),
        "project": memory.get("project"),
        "domain": memory.get("domain"),
        "status": memory.get("status"),
        "canonical": bool(memory.get("canonical", False)),
        "tags": list(memory.get("tags") or []),
        "chars": int(memory.get("chars") or 0),
        "chunk_count": memory.get("chunk_count"),
        "quality_score": score,
        "risk": _risk_for_score(score),
        "issues": issues,
    }


def _quality_issues(memory: dict[str, Any], *, max_memory_chars: int) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not memory.get("project"):
        issues.append(_issue("missing_project", "medium", 15, "Memory is not scoped to a project."))
    if not memory.get("domain"):
        issues.append(_issue("missing_domain", "medium", 10, "Memory is not scoped to a domain."))
    if not memory.get("tags"):
        issues.append(_issue("missing_tags", "medium", 10, "Memory has no browse/search tags."))

    status = str(memory.get("status") or "active")
    if status != "active":
        issues.append(
            _issue(
                "inactive_status",
                "high",
                20,
                f"Memory status is '{status}', so agents should not treat it as current active context.",
            )
        )

    chars = int(memory.get("chars") or 0)
    chunk_count = memory.get("chunk_count")
    if chars > max_memory_chars:
        issues.append(
            _issue(
                "large_memory",
                "medium",
                10,
                "Memory is large enough to prefer source/document review or narrower chunks.",
            )
        )
    elif not isinstance(chunk_count, int) or chunk_count < 1:
        issues.append(_issue("unknown_chunk_count", "medium", 20, "Memory chunk count is missing or invalid."))

    return issues


def _issue(code: str, severity: str, penalty: int, message: str) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "penalty": penalty,
        "message": message,
    }


def _risk_for_score(score: int) -> str:
    if score < 60:
        return "high"
    if score < 90:
        return "medium"
    return "low"


def _summary(entries: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "low_risk_count": sum(1 for entry in entries if entry["risk"] == "low"),
        "medium_risk_count": sum(1 for entry in entries if entry["risk"] == "medium"),
        "high_risk_count": sum(1 for entry in entries if entry["risk"] == "high"),
    }
