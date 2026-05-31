"""Project identity and alias resolution for Memory OS filters."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from core.memory_os._records import list_records, now_iso, stable_id, upsert_record
from core.memory_os.ledger import MemoryOSLedger

PROJECT_ALIAS_SCOPE = "project"


def upsert_project_aliases(
    ledger: MemoryOSLedger,
    *,
    canonical_project_id: str,
    canonical_label: str,
    aliases: list[str],
    created_by: str,
) -> dict[str, Any]:
    """Store reviewed project aliases without rewriting source labels."""
    normalized_aliases = _dedupe([*aliases, canonical_label])
    now = now_iso()
    existing = _read_entity_by_project_id(ledger, canonical_project_id) or {}
    entity_id = existing.get("entity_id") or stable_id(
        "entity",
        {"entity_type": PROJECT_ALIAS_SCOPE, "canonical_project_id": canonical_project_id},
    )
    entity = {
        "entity_id": entity_id,
        "entity_type": PROJECT_ALIAS_SCOPE,
        "canonical_project_id": canonical_project_id,
        "canonical_label": canonical_label,
        "aliases": normalized_aliases,
        "source_labels": _dedupe([*existing.get("source_labels", []), *normalized_aliases]),
        "review_state": "reviewed",
        "created_by": existing.get("created_by") or created_by,
        "created_at": existing.get("created_at") or now,
        "updated_at": now,
    }
    upsert_record(ledger, "entities", entity_id, entity)
    for label in normalized_aliases:
        alias = {
            "alias_id": stable_id(
                "alias",
                {
                    "alias_scope": PROJECT_ALIAS_SCOPE,
                    "canonical_project_id": canonical_project_id,
                    "label": label,
                },
            ),
            "alias_scope": PROJECT_ALIAS_SCOPE,
            "label": label,
            "normalized_project_label": canonical_project_label(label),
            "canonical_project_id": canonical_project_id,
            "entity_id": entity_id,
            "confidence": 1.0,
            "review_state": "reviewed",
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
        }
        upsert_record(ledger, "aliases", alias["alias_id"], alias)
    return entity


def resolve_project_filter_values(
    ledger: MemoryOSLedger,
    project: str | None,
    *,
    exact: bool = False,
) -> list[str]:
    """Return label values that should match a project filter."""
    project_label = _optional_text(project)
    if project_label is None:
        return []
    if exact:
        return [project_label]

    normalized = canonical_project_label(project_label)
    registered = _registered_alias_values(ledger, normalized)
    if registered:
        return registered

    inferred = _infer_alias_values_from_records(ledger, normalized)
    if inferred:
        return inferred
    return [project_label]


def canonical_project_label(label: str) -> str:
    """Return a path-tolerant project label used only for alias matching."""
    normalized = str(label or "").replace("\\", "/").strip().strip("/")
    if "/" in normalized:
        normalized = normalized.rsplit("/", 1)[-1]
    normalized = normalized.lower()
    return re.sub(r"[^a-z0-9]+", "", normalized)


def _registered_alias_values(ledger: MemoryOSLedger, normalized: str) -> list[str]:
    matching_project_ids = {
        str(alias.get("canonical_project_id"))
        for alias in list_records(ledger, "aliases")
        if alias.get("alias_scope") == PROJECT_ALIAS_SCOPE
        and alias.get("normalized_project_label") == normalized
        and alias.get("canonical_project_id")
    }
    if not matching_project_ids:
        return []
    labels = {
        str(alias.get("label"))
        for alias in list_records(ledger, "aliases")
        if alias.get("alias_scope") == PROJECT_ALIAS_SCOPE
        and alias.get("canonical_project_id") in matching_project_ids
        and _optional_text(alias.get("label"))
    }
    return sorted(labels)


def _infer_alias_values_from_records(ledger: MemoryOSLedger, normalized: str) -> list[str]:
    labels_by_canonical: dict[str, set[str]] = defaultdict(set)
    for table in (
        "memories",
        "documents",
        "chunks",
        "sources",
        "knowledge_artifacts",
        "drafts",
        "jobs",
        "graph_edges",
    ):
        for record in list_records(ledger, table):
            label = _optional_text(record.get("project"))
            if label is None:
                continue
            labels_by_canonical[canonical_project_label(label)].add(label)
    labels = labels_by_canonical.get(normalized) or set()
    return sorted(labels)


def _read_entity_by_project_id(ledger: MemoryOSLedger, canonical_project_id: str) -> dict[str, Any] | None:
    for entity in list_records(ledger, "entities"):
        if entity.get("entity_type") == PROJECT_ALIAS_SCOPE and entity.get("canonical_project_id") == canonical_project_id:
            return entity
    return None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
