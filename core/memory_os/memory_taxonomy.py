"""Native memory taxonomy metadata normalization."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.memory_os.schema import (
    MEMORY_SCOPES,
    MEMORY_TYPES,
    RETENTION_POLICIES,
    SYNC_POLICIES,
    TRUST_STATES,
)


@dataclass(frozen=True)
class MemoryClassification:
    memory_type: str
    scope: str
    trust_state: str
    retention_policy: str
    sync_policy: str


def normalize_memory_type(value: str | None) -> str:
    text = _normalize_token(value, default="fact")
    if text not in MEMORY_TYPES:
        raise ValueError(f"unknown memory_type: {value}")
    return text


def normalize_scope(value: str | None) -> str:
    text = _normalize_token(value, default="project")
    if text not in MEMORY_SCOPES:
        raise ValueError(f"unknown memory scope: {value}")
    return text


def normalize_trust_state(value: str | None) -> str:
    text = _normalize_token(value, default="reviewed")
    if text not in TRUST_STATES:
        raise ValueError(f"unknown trust_state: {value}")
    return text


def normalize_retention_policy(value: str | None) -> str:
    text = _normalize_token(value, default="standard")
    if text not in RETENTION_POLICIES:
        raise ValueError(f"unknown retention_policy: {value}")
    return text


def normalize_sync_policy(value: str | None, *, scope: str, retention_policy: str, trust_state: str) -> str:
    if trust_state == "quarantined":
        return "quarantined"
    if scope == "device" or retention_policy in {"ephemeral", "local_only"}:
        return "local_only"
    if value is None:
        return "sync"
    text = _normalize_token(value, default="sync")
    if text not in SYNC_POLICIES:
        raise ValueError(f"unknown sync_policy: {value}")
    return text


def classify_memory_request(request: dict[str, Any]) -> MemoryClassification:
    tags = _tag_set(request.get("tags"))
    requested_type = request.get("memory_type")
    source_document = request.get("source_document") if isinstance(request.get("source_document"), dict) else {}
    document_id = request.get("document_id") or source_document.get("document_id")
    source_id = request.get("source_id") or source_document.get("source_id")
    if requested_type is None:
        if document_id:
            requested_type = "document_claim"
        elif "decision" in tags:
            requested_type = "decision"
        elif "procedure" in tags:
            requested_type = "procedure"
        elif "preference" in tags:
            requested_type = "preference"
        elif "handoff" in tags:
            requested_type = "handoff"
    scope = request.get("scope")
    if scope is None and document_id:
        scope = "document"
    elif scope is None and source_id:
        scope = "source"
    elif scope is None and request.get("project"):
        scope = "project"

    memory_type = normalize_memory_type(_optional_string(requested_type))
    normalized_scope = normalize_scope(_optional_string(scope))
    trust_state = normalize_trust_state(_optional_string(request.get("trust_state")))
    retention_policy = normalize_retention_policy(_optional_string(request.get("retention_policy")))
    sync_policy = normalize_sync_policy(
        _optional_string(request.get("sync_policy")),
        scope=normalized_scope,
        retention_policy=retention_policy,
        trust_state=trust_state,
    )
    return MemoryClassification(
        memory_type=memory_type,
        scope=normalized_scope,
        trust_state=trust_state,
        retention_policy=retention_policy,
        sync_policy=sync_policy,
    )


def normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    classification = classify_memory_request(payload)
    return {
        **payload,
        "memory_type": classification.memory_type,
        "scope": classification.scope,
        "trust_state": classification.trust_state,
        "retention_policy": classification.retention_policy,
        "sync_policy": classification.sync_policy,
    }


def _normalize_token(value: str | None, *, default: str) -> str:
    return str(value or default).strip().lower().replace(" ", "_").replace("-", "_")


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _tag_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        raw_items = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        raw_items = [value]
    return {_normalize_token(str(item), default="") for item in raw_items if str(item).strip()}
