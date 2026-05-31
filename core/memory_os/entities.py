"""Entity, concept, and alias registry for Memory OS identity resolution."""
from __future__ import annotations

from typing import Any

from core.memory_os._records import list_records, now_iso, stable_id, upsert_record
from core.memory_os.ledger import MemoryOSLedger

LOW_CONFIDENCE_ALIAS_THRESHOLD = 0.7


class EntityRegistry:
    """Resolve aliases to canonical entities while preserving merge/split history."""

    def __init__(self, ledger: MemoryOSLedger) -> None:
        self.ledger = ledger

    def upsert_entity(
        self,
        canonical_name: str,
        entity_type: str,
        *,
        aliases: list[str | dict[str, Any]] | None = None,
        confidence: float = 1.0,
        review_state: str = "reviewed",
    ) -> dict[str, Any]:
        entity_id = stable_id("entity", {"canonical_name": canonical_name, "entity_type": entity_type})
        existing = self.get_entity(entity_id) or {}
        entity = {
            "entity_id": entity_id,
            "canonical_name": canonical_name,
            "entity_type": entity_type,
            "aliases": _normalize_aliases(aliases or []),
            "source_labels": _dedupe([canonical_name, *existing.get("source_labels", [])]),
            "confidence": float(confidence),
            "review_state": review_state,
            "merge_history": existing.get("merge_history", []),
            "split_history": existing.get("split_history", []),
            "created_at": existing.get("created_at") or now_iso(),
            "updated_at": now_iso(),
        }
        upsert_record(self.ledger, "entities", entity_id, entity)
        self._write_alias(canonical_name, entity_id, 1.0)
        for alias in entity["aliases"]:
            self._write_alias(alias["label"], entity_id, alias["confidence"])
        return entity

    def get_entity(self, entity_id: str) -> dict[str, Any] | None:
        for entity in list_records(self.ledger, "entities"):
            if entity.get("entity_id") == entity_id:
                return entity
        return None

    def resolve(self, label: str) -> dict[str, Any]:
        normalized = _normalize_label(label)
        for alias in list_records(self.ledger, "aliases"):
            if alias.get("normalized_label") != normalized:
                continue
            entity = self.get_entity(str(alias["entity_id"]))
            if entity is None:
                break
            confidence = float(alias.get("confidence", 0.0))
            return {
                "entity_id": entity["entity_id"],
                "canonical_name": entity["canonical_name"],
                "entity_type": entity["entity_type"],
                "matched_label": label,
                "alias_confidence": confidence,
                "low_confidence": confidence < LOW_CONFIDENCE_ALIAS_THRESHOLD,
            }
        return {
            "entity_id": None,
            "canonical_name": None,
            "entity_type": None,
            "matched_label": label,
            "alias_confidence": 0.0,
            "low_confidence": True,
        }

    def merge_entities(self, primary_entity_id: str, merged_entity_id: str, *, created_by: str) -> dict[str, Any]:
        primary = self.get_entity(primary_entity_id)
        merged = self.get_entity(merged_entity_id)
        if primary is None or merged is None:
            raise KeyError("both entities must exist before merge")

        primary["source_labels"] = _dedupe(
            [
                *primary.get("source_labels", []),
                merged["canonical_name"],
                *merged.get("source_labels", []),
            ]
        )
        primary["merge_history"] = [
            *primary.get("merge_history", []),
            {
                "merged_entity_id": merged_entity_id,
                "merged_canonical_name": merged["canonical_name"],
                "created_by": created_by,
                "created_at": now_iso(),
            },
        ]
        primary["updated_at"] = now_iso()
        upsert_record(self.ledger, "entities", primary_entity_id, primary)
        for alias in merged.get("aliases", []):
            self._write_alias(alias["label"], primary_entity_id, alias["confidence"])
        self._write_alias(merged["canonical_name"], primary_entity_id, 0.95)
        return primary

    def split_entity(
        self,
        entity_id: str,
        *,
        alias_label: str,
        new_canonical_name: str,
        created_by: str,
    ) -> dict[str, Any]:
        entity = self.get_entity(entity_id)
        if entity is None:
            raise KeyError(f"entity not found: {entity_id}")
        new_entity = self.upsert_entity(
            new_canonical_name,
            entity.get("entity_type", "concept"),
            aliases=[alias_label],
            confidence=0.9,
        )
        entity["aliases"] = [
            alias for alias in entity.get("aliases", []) if _normalize_label(alias["label"]) != _normalize_label(alias_label)
        ]
        entity["split_history"] = [
            *entity.get("split_history", []),
            {
                "alias_label": alias_label,
                "new_entity_id": new_entity["entity_id"],
                "created_by": created_by,
                "created_at": now_iso(),
            },
        ]
        entity["updated_at"] = now_iso()
        upsert_record(self.ledger, "entities", entity_id, entity)
        self._write_alias(alias_label, new_entity["entity_id"], 0.9)
        return {"entity": new_entity, "source_entity": entity}

    def _write_alias(self, label: str, entity_id: str, confidence: float) -> None:
        normalized = _normalize_label(label)
        alias = {
            "alias_id": stable_id("alias", {"normalized_label": normalized}),
            "label": label,
            "normalized_label": normalized,
            "entity_id": entity_id,
            "confidence": float(confidence),
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        upsert_record(self.ledger, "aliases", alias["alias_id"], alias)


def _normalize_aliases(aliases: list[str | dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for alias in aliases:
        if isinstance(alias, dict):
            label = str(alias.get("label") or "").strip()
            confidence = float(alias.get("confidence", 1.0))
        else:
            label = str(alias).strip()
            confidence = 1.0
        key = _normalize_label(label)
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append({"label": label, "confidence": confidence})
    return normalized


def _normalize_label(label: str) -> str:
    return " ".join(str(label).strip().lower().split())


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
