"""Device identity lifecycle for Memory OS bidirectional sync."""
from __future__ import annotations

from typing import Any

from core.memory_os._records import hash_payload, list_records, now_iso, read_record, upsert_record
from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.sync_crypto import load_or_create_local_sync_keys, rotate_local_sync_key_file
from core.memory_os.transactions import MemoryTransactionService


LOCAL_DEVICE_RECORD_ID = "sync_device:local"
SYNC_IDENTITY_SCHEMA_VERSION = "2026-05-26.sync-device.v1"


def ensure_device_identity(ledger: MemoryOSLedger, *, device_name: str) -> dict[str, Any]:
    """Ensure the local device has a stable public sync identity in the ledger."""
    existing = read_record(ledger, "sync_devices", LOCAL_DEVICE_RECORD_ID)
    if existing and existing.get("status") == "active":
        return _public_device_record(existing)
    keys = load_or_create_local_sync_keys(ledger.path.parent / "keys")
    record = _local_device_record(
        device_id=_existing_device_id(existing, keys.signing_public_key),
        device_name=device_name,
        signing_public_key=keys.signing_public_key,
        exchange_public_key=keys.exchange_public_key,
    )
    upsert_record(ledger, "sync_devices", LOCAL_DEVICE_RECORD_ID, record)
    return _public_device_record(record)


def export_local_sync_identity(ledger: MemoryOSLedger) -> dict[str, Any]:
    """Export a public-only identity packet for manual peer registration."""
    local = read_record(ledger, "sync_devices", LOCAL_DEVICE_RECORD_ID)
    if not local:
        local = ensure_device_identity(ledger, device_name="local")
    return {
        "record_type": "sync_public_identity",
        "schema_version": "2026-05-26.sync-public-identity.v1",
        "device_id": local["device_id"],
        "device_name": local.get("device_name"),
        "signing_public_key": local["signing_public_key"],
        "exchange_public_key": local["exchange_public_key"],
        "signing_key_fingerprint": local["signing_key_fingerprint"],
        "exchange_key_fingerprint": local["exchange_key_fingerprint"],
        "status": local.get("status", "active"),
        "exported_at": now_iso(),
    }


def register_sync_peer(
    ledger: MemoryOSLedger,
    peer_packet: dict[str, Any],
    *,
    accept: bool,
    approved_by: str | None,
) -> dict[str, Any]:
    """Register a reviewed peer public identity packet."""
    if _contains_private_material(peer_packet):
        return _policy_denied("private_key_material_rejected")
    if not accept or not _text(approved_by):
        return _policy_denied("acceptance_required")
    error = _validate_peer_packet(ledger, peer_packet)
    if error is not None:
        return _policy_denied(error)
    peer_id = str(peer_packet["device_id"])
    record_id = f"sync_device:peer:{peer_id}"
    existing = read_record(ledger, "sync_devices", record_id)
    if existing and existing.get("status") == "revoked":
        return _policy_denied("peer_revoked")
    timestamp = now_iso()
    record = {
        "record_type": "sync_peer",
        "schema_version": SYNC_IDENTITY_SCHEMA_VERSION,
        "device_record_id": record_id,
        "device_id": peer_id,
        "device_name": _text(peer_packet.get("device_name")) or peer_id,
        "signing_public_key": str(peer_packet["signing_public_key"]),
        "exchange_public_key": str(peer_packet["exchange_public_key"]),
        "signing_key_fingerprint": str(peer_packet["signing_key_fingerprint"]),
        "exchange_key_fingerprint": str(peer_packet["exchange_key_fingerprint"]),
        "status": "active",
        "sync_allowed": True,
        "created_at": existing.get("created_at") if existing else timestamp,
        "updated_at": timestamp,
        "approved_by": _text(approved_by),
    }
    upsert_record(ledger, "sync_devices", record_id, record)
    receipt = MemoryTransactionService(ledger).promote(
        operation_kind="sync_peer_register",
        proposed_writes=[{"table": "sync_devices", "id": record_id}],
        idempotency_key=f"sync_peer_register:{peer_id}",
        affected_refs=[{"table": "sync_devices", "id": record_id}],
    )
    return {
        "status": "registered",
        "write_performed": True,
        "peer": _public_device_record(record),
        "transaction": receipt,
        "error": None,
    }


def rotate_local_sync_keys(
    ledger: MemoryOSLedger,
    *,
    accept: bool,
    approved_by: str | None,
) -> dict[str, Any]:
    """Rotate local public/private key material while preserving device_id."""
    if not accept or not _text(approved_by):
        return _policy_denied("acceptance_required")
    existing = ensure_device_identity(ledger, device_name="local")
    superseded = dict(existing)
    superseded["status"] = "superseded"
    superseded["sync_allowed"] = False
    superseded["superseded_at"] = now_iso()
    superseded_id = f"{LOCAL_DEVICE_RECORD_ID}:superseded:{existing['signing_key_fingerprint'].split(':', 1)[1][:16]}"
    upsert_record(ledger, "sync_devices", superseded_id, superseded)
    keys = rotate_local_sync_key_file(ledger.path.parent / "keys")
    active = _local_device_record(
        device_id=str(existing["device_id"]),
        device_name=str(existing.get("device_name") or "local"),
        signing_public_key=keys.signing_public_key,
        exchange_public_key=keys.exchange_public_key,
    )
    active["rotated_at"] = now_iso()
    active["approved_by"] = _text(approved_by)
    upsert_record(ledger, "sync_devices", LOCAL_DEVICE_RECORD_ID, active)
    receipt = MemoryTransactionService(ledger).promote(
        operation_kind="sync_local_key_rotate",
        proposed_writes=[
            {"table": "sync_devices", "id": LOCAL_DEVICE_RECORD_ID},
            {"table": "sync_devices", "id": superseded_id},
        ],
        idempotency_key=f"sync_local_key_rotate:{active['signing_key_fingerprint']}",
        affected_refs=[{"table": "sync_devices", "id": LOCAL_DEVICE_RECORD_ID}],
    )
    return {
        "status": "rotated",
        "write_performed": True,
        "previous_signing_key_fingerprint": existing["signing_key_fingerprint"],
        "previous_exchange_key_fingerprint": existing["exchange_key_fingerprint"],
        "local_device": _public_device_record(active),
        "transaction": receipt,
        "error": None,
    }


def revoke_sync_peer(
    ledger: MemoryOSLedger,
    *,
    peer_id: str,
    reason: str,
    accept: bool,
    approved_by: str | None,
) -> dict[str, Any]:
    """Mark a peer revoked so later export/apply surfaces can reject it."""
    normalized_peer_id = _text(peer_id)
    normalized_reason = _text(reason)
    if not accept or not _text(approved_by):
        return _policy_denied("acceptance_required")
    if not normalized_peer_id or not normalized_reason:
        return _policy_denied("revoke_reason_required")
    record_id = f"sync_device:peer:{normalized_peer_id}"
    existing = read_record(ledger, "sync_devices", record_id) or {}
    record = {
        **existing,
        "record_type": "sync_peer",
        "schema_version": SYNC_IDENTITY_SCHEMA_VERSION,
        "device_record_id": record_id,
        "device_id": normalized_peer_id,
        "device_name": existing.get("device_name") or normalized_peer_id,
        "status": "revoked",
        "sync_allowed": False,
        "revocation_reason": normalized_reason,
        "revoked_at": now_iso(),
        "approved_by": _text(approved_by),
    }
    upsert_record(ledger, "sync_devices", record_id, record)
    receipt = MemoryTransactionService(ledger).promote(
        operation_kind="sync_peer_revoke",
        proposed_writes=[{"table": "sync_devices", "id": record_id}],
        idempotency_key=f"sync_peer_revoke:{normalized_peer_id}:{normalized_reason}",
        affected_refs=[{"table": "sync_devices", "id": record_id}],
    )
    return {
        "status": "revoked",
        "write_performed": True,
        "peer": _public_device_record(record),
        "transaction": receipt,
        "error": None,
    }


def build_sync_status(ledger: MemoryOSLedger) -> dict[str, Any]:
    """Return compact sync readiness without exposing private keys."""
    records = list_records(ledger, "sync_devices")
    local = read_record(ledger, "sync_devices", LOCAL_DEVICE_RECORD_ID)
    peers = [
        record
        for record in records
        if str(record.get("record_type") or "") == "sync_peer"
        and str(record.get("status") or "") != "superseded"
    ]
    conflicts = [
        record for record in list_records(ledger, "sync_conflicts")
        if str(record.get("status") or "pending_review") not in {"resolved", "dismissed"}
    ]
    cursors = list_records(ledger, "sync_cursors")
    changesets = list_records(ledger, "sync_changesets")
    return {
        "status": "ready" if local else "not_configured",
        "local_device": _public_device_record(local) if local else None,
        "peer_count": len(peers),
        "active_peer_count": len([peer for peer in peers if peer.get("status") == "active"]),
        "revoked_peer_count": len([peer for peer in peers if peer.get("status") == "revoked"]),
        "pending_conflict_count": len(conflicts),
        "last_exported_at": _latest_timestamp(changesets, "exported_at"),
        "last_applied_at": _latest_timestamp(cursors, "applied_at"),
    }


def _local_device_record(
    *,
    device_id: str,
    device_name: str,
    signing_public_key: str,
    exchange_public_key: str,
) -> dict[str, Any]:
    return {
        "record_type": "sync_device",
        "schema_version": SYNC_IDENTITY_SCHEMA_VERSION,
        "device_record_id": LOCAL_DEVICE_RECORD_ID,
        "device_id": device_id,
        "device_name": device_name,
        "signing_public_key": "ed25519:" + signing_public_key,
        "exchange_public_key": "x25519:" + exchange_public_key,
        "signing_key_fingerprint": hash_payload(signing_public_key),
        "exchange_key_fingerprint": hash_payload(exchange_public_key),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "status": "active",
        "sync_allowed": True,
    }


def _existing_device_id(existing: dict[str, Any] | None, signing_public_key: str) -> str:
    if existing and _text(existing.get("device_id")):
        return str(existing["device_id"])
    return "device:" + hash_payload(signing_public_key).split(":", 1)[1][:24]


def _public_device_record(record: dict[str, Any] | None) -> dict[str, Any]:
    if not record:
        return {}
    allowed = {
        "record_type",
        "schema_version",
        "device_record_id",
        "device_id",
        "device_name",
        "signing_public_key",
        "exchange_public_key",
        "signing_key_fingerprint",
        "exchange_key_fingerprint",
        "status",
        "sync_allowed",
        "created_at",
        "updated_at",
        "rotated_at",
        "superseded_at",
        "revoked_at",
        "revocation_reason",
        "approved_by",
    }
    return {key: value for key, value in record.items() if key in allowed}


def _validate_peer_packet(ledger: MemoryOSLedger, packet: dict[str, Any]) -> str | None:
    local = read_record(ledger, "sync_devices", LOCAL_DEVICE_RECORD_ID)
    device_id = _text(packet.get("device_id"))
    signing_public_key = _text(packet.get("signing_public_key"))
    exchange_public_key = _text(packet.get("exchange_public_key"))
    signing_fingerprint = _text(packet.get("signing_key_fingerprint"))
    exchange_fingerprint = _text(packet.get("exchange_key_fingerprint"))
    if not device_id or not device_id.startswith("device:"):
        return "invalid_peer_device_id"
    if local and device_id == local.get("device_id"):
        return "cannot_register_local_device_as_peer"
    if not signing_public_key or not signing_public_key.startswith("ed25519:"):
        return "invalid_peer_signing_public_key"
    if not exchange_public_key or not exchange_public_key.startswith("x25519:"):
        return "invalid_peer_exchange_public_key"
    signing_raw = signing_public_key.split(":", 1)[1]
    exchange_raw = exchange_public_key.split(":", 1)[1]
    if signing_fingerprint != hash_payload(signing_raw):
        return "invalid_peer_signing_fingerprint"
    if exchange_fingerprint != hash_payload(exchange_raw):
        return "invalid_peer_exchange_fingerprint"
    return None


def _contains_private_material(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if "private" in str(key).lower():
                return True
            if _contains_private_material(item):
                return True
    elif isinstance(value, list):
        return any(_contains_private_material(item) for item in value)
    return False


def _policy_denied(code: str) -> dict[str, Any]:
    return {
        "status": "policy_denied",
        "write_performed": False,
        "error": {"code": code},
    }


def _text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _latest_timestamp(records: list[dict[str, Any]], field: str) -> str | None:
    values = sorted(str(record.get(field) or "") for record in records if record.get(field))
    return values[-1] if values else None
