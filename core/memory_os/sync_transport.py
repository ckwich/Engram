"""Transport receipts and encrypted bundle staging for Memory OS sync."""
from __future__ import annotations

import os
from typing import Any

from core.memory_limits import DAEMON_MAX_CONTENT_LENGTH_ENV, DEFAULT_DAEMON_MAX_CONTENT_LENGTH
from core.memory_os._records import hash_payload, list_records, now_iso, stable_id, upsert_record


SYNC_TRANSPORT_SCHEMA_VERSION = "2026-05-26.sync-transport.v1"
SYNC_INBOX_SCHEMA_VERSION = "2026-05-26.sync-inbox.v1"


class SyncTransportError(ValueError):
    """Raised when sync transport data violates the staging contract."""


def register_sync_transport_receipt(runtime: Any, receipt: dict[str, Any]) -> dict[str, Any]:
    """Record transport delivery state without claiming changeset apply success."""
    if not isinstance(receipt, dict):
        return _policy_denied("invalid_transport_receipt")
    if receipt.get("apply_performed") is True or str(receipt.get("status") or "") == "applied":
        return _policy_denied("transport_must_not_claim_apply")
    timestamp = now_iso()
    record = {
        "schema_version": SYNC_TRANSPORT_SCHEMA_VERSION,
        "record_type": "sync_transport_receipt",
        "transport_type": _text(receipt.get("transport_type")) or "unknown",
        "peer_id": _text(receipt.get("peer_id")),
        "artifact_id": _text(receipt.get("artifact_id")),
        "inbox_id": _text(receipt.get("inbox_id")),
        "direction": _text(receipt.get("direction")) or "unknown",
        "status": _text(receipt.get("status")) or "recorded",
        "apply_performed": False,
        "metadata": receipt.get("metadata") if isinstance(receipt.get("metadata"), dict) else {},
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    receipt_id = stable_id(
        "sync_transport",
        {
            "transport_type": record["transport_type"],
            "peer_id": record["peer_id"],
            "artifact_id": record["artifact_id"],
            "inbox_id": record["inbox_id"],
            "direction": record["direction"],
            "status": record["status"],
            "metadata": record["metadata"],
        },
    )
    record["receipt_id"] = receipt_id
    upsert_record(runtime.ledger, "sync_transport_receipts", receipt_id, record)
    return {
        **record,
        "status": record["status"],
        "write_performed": True,
        "error": None,
    }


def store_inbound_sync_bundle(
    runtime: Any,
    bundle_bytes: bytes,
    transport_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Store encrypted sync bundle bytes and a transport receipt; never apply them."""
    if not isinstance(bundle_bytes, bytes) or not bundle_bytes:
        return _policy_denied("invalid_bundle_bytes")
    if len(bundle_bytes) > sync_bundle_max_bytes():
        return _policy_denied("sync_bundle_too_large")
    metadata = dict(transport_metadata or {})
    artifact_id = runtime.content_store.put_bytes(bundle_bytes, suffix=".engram-sync")
    timestamp = now_iso()
    inbox_id = stable_id(
        "sync_inbox",
        {
            "artifact_id": artifact_id,
            "peer_id": _text(metadata.get("peer_id")),
            "transport_type": _text(metadata.get("transport_type")) or "unknown",
            "bundle_hash": hash_payload(bundle_bytes.decode("utf-8", errors="replace")),
        },
    )
    inbox_record = {
        "schema_version": SYNC_INBOX_SCHEMA_VERSION,
        "record_type": "sync_bundle",
        "inbox_id": inbox_id,
        "artifact_id": artifact_id,
        "size_bytes": len(bundle_bytes),
        "bundle_hash": hash_payload(bundle_bytes.decode("utf-8", errors="replace")),
        "peer_id": _text(metadata.get("peer_id")),
        "transport": metadata,
        "status": "received",
        "apply_performed": False,
        "received_at": timestamp,
        "updated_at": timestamp,
        "sync_policy": "local_only",
    }
    upsert_record(runtime.ledger, "sync_inbox", inbox_id, inbox_record)
    receipt = register_sync_transport_receipt(
        runtime,
        {
            "transport_type": metadata.get("transport_type") or "unknown",
            "peer_id": metadata.get("peer_id"),
            "artifact_id": artifact_id,
            "inbox_id": inbox_id,
            "direction": "inbound",
            "status": "received",
            "metadata": metadata,
        },
    )
    return {
        "schema_version": SYNC_INBOX_SCHEMA_VERSION,
        "status": "received",
        "write_performed": True,
        "apply_performed": False,
        "inbox_id": inbox_id,
        "artifact_id": artifact_id,
        "size_bytes": len(bundle_bytes),
        "transport_receipt": receipt,
        "error": None,
    }


def list_sync_inbox(runtime: Any, *, peer_id: str | None = None) -> dict[str, Any]:
    """List locally staged encrypted sync bundles without returning bundle bytes."""
    normalized_peer_id = _text(peer_id)
    records = []
    for record in list_records(runtime.ledger, "sync_inbox"):
        if record.get("record_type") != "sync_bundle":
            continue
        if normalized_peer_id and record.get("peer_id") != normalized_peer_id:
            continue
        transport = record.get("transport") if isinstance(record.get("transport"), dict) else {}
        records.append(
            {
                "inbox_id": record.get("inbox_id"),
                "artifact_id": record.get("artifact_id"),
                "peer_id": record.get("peer_id"),
                "transport_type": transport.get("transport_type"),
                "status": record.get("status"),
                "apply_performed": bool(record.get("apply_performed", False)),
                "size_bytes": record.get("size_bytes"),
                "received_at": record.get("received_at"),
                "updated_at": record.get("updated_at"),
            }
        )
    records.sort(key=lambda item: str(item.get("received_at") or ""), reverse=True)
    return {
        "schema_version": SYNC_INBOX_SCHEMA_VERSION,
        "status": "ok",
        "write_performed": False,
        "peer_id": normalized_peer_id,
        "inbox_count": len(records),
        "inbox": records,
        "error": None,
    }


def _policy_denied(code: str) -> dict[str, Any]:
    return {
        "schema_version": SYNC_TRANSPORT_SCHEMA_VERSION,
        "status": "policy_denied",
        "write_performed": False,
        "apply_performed": False,
        "error": {"code": code},
    }


def _text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def sync_bundle_max_bytes() -> int:
    """Return the configured sync bundle byte ceiling."""
    raw_value = os.environ.get(DAEMON_MAX_CONTENT_LENGTH_ENV, "").strip()
    if not raw_value:
        return DEFAULT_DAEMON_MAX_CONTENT_LENGTH
    try:
        return max(int(raw_value), 1024)
    except ValueError:
        return DEFAULT_DAEMON_MAX_CONTENT_LENGTH
