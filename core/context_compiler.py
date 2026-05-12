"""No-write context compiler primitives for agent workflow packets."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

CONTEXT_PROFILE_CATALOG_SCHEMA_VERSION = "2026-05-11.context-profiles.v1"
CONTEXT_PACKET_SCHEMA_VERSION = "2026-05-11.context-packet.v1"
HANDOFF_PACKET_SCHEMA_VERSION = "2026-05-11.handoff-packet.v1"

_CONTEXT_PROFILES: dict[str, dict[str, Any]] = {
    "repo_resume": {
        "id": "repo_resume",
        "label": "Repository Resume",
        "purpose": "Resume coding work with prior decisions, handoffs, branch state, and validation context.",
        "retrieval_mode": "semantic",
        "max_chunks": 8,
        "budget_chars": 10000,
        "include_stale": False,
        "canonical_only": False,
        "use_graph": True,
        "max_hops": 1,
        "query_terms": ["handoff", "next step", "branch", "validation", "decision"],
    },
    "debugging": {
        "id": "debugging",
        "label": "Debugging",
        "purpose": "Gather symptom, failing-gate, runtime, and prior-fix context.",
        "retrieval_mode": "hybrid",
        "max_chunks": 6,
        "budget_chars": 8000,
        "include_stale": False,
        "canonical_only": False,
        "use_graph": True,
        "max_hops": 1,
        "query_terms": ["symptom", "runtime", "failing gate", "validation", "fix"],
    },
    "document_review": {
        "id": "document_review",
        "label": "Document Review",
        "purpose": "Gather source, draft, citation, and promotion context for review-first document work.",
        "retrieval_mode": "hybrid",
        "max_chunks": 6,
        "budget_chars": 8000,
        "include_stale": False,
        "canonical_only": False,
        "use_graph": False,
        "max_hops": 0,
        "query_terms": ["document", "source", "draft", "citation", "promotion"],
    },
    "release_audit": {
        "id": "release_audit",
        "label": "Release Audit",
        "purpose": "Gather checklist, contract, validation, and migration-readiness context.",
        "retrieval_mode": "hybrid",
        "max_chunks": 10,
        "budget_chars": 12000,
        "include_stale": False,
        "canonical_only": False,
        "use_graph": True,
        "max_hops": 1,
        "query_terms": ["release", "checklist", "contract", "migration", "validation"],
    },
}


def list_context_profiles() -> dict[str, Any]:
    """Return static retrieval profiles for no-write context compilation."""
    profiles = deepcopy(_CONTEXT_PROFILES)
    return {
        "schema_version": CONTEXT_PROFILE_CATALOG_SCHEMA_VERSION,
        "count": len(profiles),
        "profiles": profiles,
        "write_performed": False,
    }


def get_context_profile(profile_id: str) -> dict[str, Any]:
    """Return one context profile or raise ValueError for unknown ids."""
    normalized = str(profile_id or "").strip() or "repo_resume"
    profile = _CONTEXT_PROFILES.get(normalized)
    if profile is None:
        available = ", ".join(sorted(_CONTEXT_PROFILES))
        raise ValueError(f"Unknown context profile '{normalized}'. Available profiles: {available}.")
    return deepcopy(profile)


def build_context_query(task: str, profile: dict[str, Any], project: str | None = None) -> str:
    """Blend the task with profile terms so retrieval can target workflow context."""
    parts = [str(task).strip()]
    if project:
        parts.append(str(project).strip())
    parts.extend(str(term).strip() for term in profile.get("query_terms", []) if str(term).strip())
    seen: set[str] = set()
    unique_parts: list[str] = []
    for part in parts:
        key = part.lower()
        if not part or key in seen:
            continue
        seen.add(key)
        unique_parts.append(part)
    return " ".join(unique_parts)


def compile_context_packet(
    *,
    task: str,
    profile_id: str,
    profile: dict[str, Any],
    context_payload: dict[str, Any],
    project: str | None,
    query: str,
    domain: str | None = None,
    tags: list[str] | None = None,
    conflict_scans: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compile a no-write agent context packet from a context_pack payload."""
    chunks = list(context_payload.get("chunks") or [])
    citations = list(context_payload.get("citations") or [])
    omitted = list(context_payload.get("omitted") or [])
    context_receipt = dict(context_payload.get("receipt") or {})
    conflict_scan_receipts = _summarize_conflict_scans(conflict_scans or [])
    warnings = _build_context_warnings(
        context_payload,
        context_receipt,
        omitted,
        conflict_scan_receipts,
    )

    return {
        "schema_version": CONTEXT_PACKET_SCHEMA_VERSION,
        "record_type": "context_packet",
        "task": str(task).strip(),
        "query": query,
        "project": project,
        "domain": domain,
        "tags": tags or [],
        "profile": {
            "id": profile_id,
            "label": profile.get("label"),
            "retrieval_mode": profile.get("retrieval_mode"),
            "max_chunks": profile.get("max_chunks"),
            "budget_chars": profile.get("budget_chars"),
            "include_stale": profile.get("include_stale"),
            "use_graph": profile.get("use_graph"),
        },
        "context": {
            "count": len(chunks),
            "chunks": chunks,
            "citations": citations,
            "omitted": omitted,
            "budget_chars": context_payload.get("budget_chars", profile.get("budget_chars")),
            "used_chars": context_payload.get("used_chars", 0),
        },
        "warnings": warnings,
        "next_actions": _build_next_actions(chunks, omitted),
        "receipt": {
            "profile_id": profile_id,
            "context_pack": context_receipt,
            "conflict_scans": conflict_scan_receipts,
            "source": "context_pack",
            "write_policy": "no_write",
        },
        "write_performed": False,
    }


def build_handoff_packet(
    *,
    task: str,
    project: str | None,
    branch: str | None,
    status: str | None,
    next_steps: str | list[str] | None,
    validation: str | list[str] | None,
    blockers: str | list[str] | None,
    context_packet: dict[str, Any],
) -> dict[str, Any]:
    """Turn a context packet plus operator notes into a no-write handoff."""
    normalized_next_steps = _normalize_text_list(next_steps)
    normalized_validation = _normalize_text_list(validation)
    normalized_blockers = _normalize_text_list(blockers)
    context = dict(context_packet.get("context") or {})
    context_chunks = list(context.get("chunks") or [])
    context_refs = [
        {
            "key": chunk.get("key"),
            "chunk_id": chunk.get("chunk_id"),
        }
        for chunk in context_chunks
        if chunk.get("key") is not None and chunk.get("chunk_id") is not None
    ]

    return {
        "schema_version": HANDOFF_PACKET_SCHEMA_VERSION,
        "record_type": "handoff_packet",
        "task": str(task).strip(),
        "project": project,
        "branch": _normalize_optional_text(branch),
        "status": _normalize_optional_text(status),
        "next_steps": normalized_next_steps,
        "validation": normalized_validation,
        "blockers": normalized_blockers,
        "context_profile": (context_packet.get("profile") or {}).get("id"),
        "context_refs": context_refs,
        "citations": list(context.get("citations") or context_packet.get("citations") or []),
        "warnings": list(context_packet.get("warnings") or []),
        "resume_prompt": _build_resume_prompt(
            task=task,
            project=project,
            branch=branch,
            status=status,
            next_steps=normalized_next_steps,
            validation=normalized_validation,
            blockers=normalized_blockers,
        ),
        "write_performed": False,
    }


def _build_context_warnings(
    context_payload: dict[str, Any],
    context_receipt: dict[str, Any],
    omitted: list[dict[str, Any]],
    conflict_scan_receipts: list[dict[str, Any]],
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    error = context_payload.get("error")
    if error:
        message = error.get("message") if isinstance(error, dict) else str(error)
        warnings.append({"code": "context_pack_error", "message": message})
    elif int(context_payload.get("count") or 0) == 0:
        warnings.append({"code": "empty_context", "message": "No matching context chunks were found."})

    if context_receipt.get("stale_policy") == "excluded":
        warnings.append(
            {
                "code": "stale_excluded",
                "message": "Stale or superseded memories were excluded by default.",
            }
        )
    if omitted:
        warnings.append(
            {
                "code": "context_omitted",
                "message": "Some candidate chunks were omitted by budget, validation, or retrieval errors.",
            }
        )
    conflict_count = sum(int(receipt.get("count") or 0) for receipt in conflict_scan_receipts)
    if conflict_count:
        edge_word = "edge was" if conflict_count == 1 else "edges were"
        warnings.append(
            {
                "code": "conflict_edges_detected",
                "message": f"{conflict_count} active conflict graph {edge_word} "
                "found for selected context memories.",
            }
        )
    if any(receipt.get("error") for receipt in conflict_scan_receipts):
        warnings.append(
            {
                "code": "conflict_scan_error",
                "message": "One or more selected context memories could not be checked for graph conflicts.",
            }
        )
    return warnings


def _summarize_conflict_scans(conflict_scans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for scan in conflict_scans:
        ref = scan.get("ref") or {}
        conflicts = list(scan.get("conflicts") or [])
        edge_types = sorted(
            {
                str(conflict.get("edge_type"))
                for conflict in conflicts
                if conflict.get("edge_type")
            }
        )
        error = scan.get("error")
        if isinstance(error, dict):
            error_code: str | None = str(error.get("code") or "runtime_error")
        elif error:
            error_code = str(error)
        else:
            error_code = None
        summaries.append(
            {
                "key": ref.get("key"),
                "count": int(scan.get("count") or len(conflicts)),
                "edge_types": edge_types,
                "error": error_code,
            }
        )
    return summaries


def _build_next_actions(chunks: list[dict[str, Any]], omitted: list[dict[str, Any]]) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    if chunks:
        first = chunks[0]
        actions.append(
            {
                "tool": "retrieve_chunk",
                "reason": f"Read the strongest cited chunk if the packet text is insufficient: {first.get('key')}#{first.get('chunk_id')}.",
            }
        )
    if omitted:
        actions.append(
            {
                "tool": "context_pack",
                "reason": "Increase budget_chars or narrow filters if omitted candidates matter.",
            }
        )
    actions.append(
        {
            "tool": "search_memories",
            "reason": "Run a narrower search before escalating to full memory bodies.",
        }
    )
    return actions


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_text_list(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    raw_items = value if isinstance(value, list) else [value]
    normalized: list[str] = []
    for item in raw_items:
        for part in str(item).replace("\r\n", "\n").split("\n"):
            text = part.strip()
            if text:
                normalized.append(text)
    return normalized


def _build_resume_prompt(
    *,
    task: str,
    project: str | None,
    branch: str | None,
    status: str | None,
    next_steps: list[str],
    validation: list[str],
    blockers: list[str],
) -> str:
    lines = [f"Resume task: {str(task).strip()}"]
    if project:
        lines.append(f"Project: {project}")
    if branch:
        lines.append(f"Branch: {branch}")
    if status:
        lines.append(f"Status: {status}")
    if next_steps:
        lines.append("Next steps:")
        lines.extend(f"- {step}" for step in next_steps)
    if validation:
        lines.append("Validation:")
        lines.extend(f"- {command}" for command in validation)
    if blockers:
        lines.append("Blockers:")
        lines.extend(f"- {blocker}" for blocker in blockers)
    return "\n".join(lines)
