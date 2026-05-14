"""Persisted EKC artifact records for the Memory OS ledger."""
from __future__ import annotations

import json
from typing import Any

from core.memory_os._records import hash_payload, list_records, now_iso, read_record, stable_id, upsert_record
from core.memory_os.content_store import ContentAddressedStore
from core.memory_os.ledger import MemoryOSLedger


class KnowledgeArtifactStore:
    """Store versioned EKC artifacts as ledger records plus immutable JSON blobs."""

    def __init__(self, ledger: MemoryOSLedger, content_store: ContentAddressedStore) -> None:
        self.ledger = ledger
        self.content_store = content_store

    def store_artifact(self, artifact: dict[str, Any], *, request_id: str | None = None) -> dict[str, Any]:
        normalized = _normalize_artifact(artifact)
        payload_hash = hash_payload(normalized)
        artifact_id = stable_id(
            "knowledge_artifact",
            {
                "artifact_type": normalized["artifact_type"],
                "artifact_version": normalized["artifact_version"],
                "project": normalized["project"],
                "payload_hash": payload_hash,
            },
        )
        existing = read_record(self.ledger, "knowledge_artifacts", artifact_id)
        now = now_iso()
        content_artifact_id = self.content_store.put_bytes(_json_bytes(normalized), suffix=".json")
        record = {
            "record_type": "knowledge_artifact",
            "artifact_id": artifact_id,
            "artifact_type": normalized["artifact_type"],
            "artifact_version": normalized["artifact_version"],
            "project": normalized["project"],
            "request_id": str(request_id or ""),
            "content_artifact_id": content_artifact_id,
            "payload_hash": payload_hash,
            "source_refs": list(normalized.get("source_refs") or []),
            "citations": list(normalized.get("citations") or []),
            "staleness": dict(normalized.get("staleness") or {}),
            "source_snapshot_id": normalized.get("source_snapshot_id"),
            "created_at": existing.get("created_at") if existing else now,
            "updated_at": now,
        }
        upsert_record(self.ledger, "knowledge_artifacts", artifact_id, record)
        return {**record, "artifact": normalized}

    def read_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        record = read_record(self.ledger, "knowledge_artifacts", str(artifact_id))
        if record is None:
            return None
        artifact = json.loads(
            self.content_store.read_bytes(str(record["content_artifact_id"])).decode("utf-8")
        )
        return {**record, "artifact": artifact}

    def read_latest_artifact(
        self,
        *,
        project: str,
        artifact_type: str,
        artifact_version: str | None = None,
        require_fresh: bool = True,
    ) -> dict[str, Any] | None:
        candidates = []
        for record in list_records(self.ledger, "knowledge_artifacts"):
            if record.get("project") != project:
                continue
            if record.get("artifact_type") != artifact_type:
                continue
            if artifact_version is not None and record.get("artifact_version") != artifact_version:
                continue
            if require_fresh and (record.get("staleness") or {}).get("state") != "fresh":
                continue
            candidates.append(record)
        if not candidates:
            return None
        latest = max(candidates, key=lambda item: str(item.get("updated_at") or ""))
        return self.read_artifact(str(latest["artifact_id"]))


def _normalize_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(artifact, dict):
        raise ValueError("artifact must be an object")
    required = ("artifact_type", "artifact_version", "project")
    missing = [field for field in required if not str(artifact.get(field) or "").strip()]
    if missing:
        raise ValueError(f"artifact missing required fields: {', '.join(missing)}")
    normalized = dict(artifact)
    normalized["artifact_type"] = str(normalized["artifact_type"]).strip()
    normalized["artifact_version"] = str(normalized["artifact_version"]).strip()
    normalized["project"] = str(normalized["project"]).strip()
    normalized.setdefault("source_refs", [])
    normalized.setdefault("citations", [])
    normalized.setdefault("staleness", {"state": "unknown", "invalidated_by": []})
    return normalized


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
