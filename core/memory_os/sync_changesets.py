"""Signed and encrypted Memory OS sync changeset export."""
from __future__ import annotations

import base64
import hashlib
import json
import re
from collections import Counter
from typing import Any

from core.memory_os._records import hash_payload, list_records, now_iso, read_record, stable_id, upsert_record
from core.memory_os.schema import SYNC_CONDITIONAL_TABLES, SYNC_ELIGIBLE_TABLES, TABLES
from core.memory_os.sync_crypto import encrypt_for_peer, load_or_create_local_sync_keys, sign_payload
from core.memory_os.sync_eligibility import classify_sync_row
from core.memory_os.sync_identity import LOCAL_DEVICE_RECORD_ID


SYNC_PREPARE_SCHEMA_VERSION = "2026-05-26.sync-prepare.v1"
SYNC_CHANGESET_SCHEMA_VERSION = "2026-05-26.sync-changeset.v1"
SYNC_BUNDLE_SCHEMA_VERSION = "2026-05-26.sync-bundle.v1"
MAX_SYNC_OBJECT_COUNT = 256
MAX_SYNC_OBJECT_BYTES = 25 * 1024 * 1024
_ARTIFACT_ID_RE = re.compile(r"^sha256:[a-f0-9]{64}(?:[.][A-Za-z0-9._-]+)?$")
_ARTIFACT_FIELD_NAMES = {
    "artifact_id",
    "content_artifact_id",
    "raw_artifact_id",
    "source_artifact_id",
    "manifest_artifact_id",
    "evidence_ref",
    "content_ref",
    "source_content_ref",
}
_INDEXED_JSON_LOOKUP_FIELDS = {
    ("chunks", "memory_key"),
    ("chunks", "document_id"),
}


def inspect_sync_state(runtime: Any) -> dict[str, Any]:
    """Return compact read-only sync state for operators and agents."""
    return {
        "schema_version": "2026-05-26.sync-state.v1",
        "status": runtime.sync_status(),
        "changesets": {
            "count": len(list_records(runtime.ledger, "sync_changesets")),
            "latest": list(reversed(list_records(runtime.ledger, "sync_changesets")))[:10],
        },
        "cursors": {
            "count": len(list_records(runtime.ledger, "sync_cursors")),
            "latest": list(reversed(list_records(runtime.ledger, "sync_cursors")))[:10],
        },
        "conflicts": {
            "count": len(list_records(runtime.ledger, "sync_conflicts")),
            "latest": [
                _public_conflict_record(record)
                for record in list(reversed(list_records(runtime.ledger, "sync_conflicts")))[:10]
            ],
        },
        "write_performed": False,
        "error": None,
    }


def inspect_sync_convergence(runtime: Any, *, peer_id: str) -> dict[str, Any]:
    """Inspect unresolved sync conflicts for one peer as the current convergence gate."""
    normalized_peer_id = str(peer_id or "").strip()
    conflicts = [
        _public_conflict_record(record)
        for record in list_records(runtime.ledger, "sync_conflicts")
        if str(record.get("source_device_id") or "") == normalized_peer_id
        and str(record.get("status") or "pending_review") not in {"resolved", "dismissed"}
    ]
    return {
        "schema_version": "2026-05-26.sync-convergence.v1",
        "status": "ok",
        "write_performed": False,
        "peer_id": normalized_peer_id,
        "converged": not conflicts,
        "unresolved_conflict_count": len(conflicts),
        "conflicts": conflicts[:20],
        "error": None,
    }


def prepare_sync_changeset(runtime: Any, *, peer_id: str) -> dict[str, Any]:
    """Prepare a no-write changeset review packet for one registered peer."""
    normalized_peer_id = str(peer_id or "").strip()
    local = read_record(runtime.ledger, "sync_devices", LOCAL_DEVICE_RECORD_ID)
    if not local or local.get("status") != "active":
        return _policy_denied("local_sync_identity_not_configured")
    peer = _active_peer_record(runtime, normalized_peer_id)
    if peer is None:
        return _policy_denied("peer_not_registered")

    transaction_records = _transactions_after_cursor(runtime, peer_id=normalized_peer_id)
    transaction_ids = [
        str(record.get("transaction_id") or "")
        for record in transaction_records
        if record.get("transaction_id")
    ]
    base_cursor = _base_cursor(runtime, peer_id=normalized_peer_id)
    excluded_rows: Counter[str] = Counter()
    row_refs: list[dict[str, Any]] = []
    object_ids: set[str] = set()
    table_counts: Counter[str] = Counter()
    candidate_refs = _candidate_write_refs(transaction_records)
    queued_refs = list(candidate_refs)
    seen_refs: set[tuple[str, str]] = {
        (str(ref.get("table") or ""), str(ref.get("id") or "")) for ref in queued_refs
    }
    runtime.ledger.initialize()
    sync_inbox_records = list_records(runtime.ledger, "sync_inbox")

    with runtime.ledger.connect() as conn:
        while queued_refs:
            ref = queued_refs.pop(0)
            table = str(ref.get("table") or "")
            row_id = str(ref.get("id") or "")
            if not table or not row_id:
                excluded_rows["invalid_transaction_ref"] += 1
                continue
            row = _read_ledger_row_from_conn(conn, table, row_id)
            if row is None:
                excluded_rows["missing_row"] += 1
                continue
            if _remote_origin_is_target(
                runtime,
                table=table,
                row_id=row_id,
                payload=row["payload"],
                peer_id=normalized_peer_id,
                sync_inbox_records=sync_inbox_records,
            ):
                excluded_rows["remote_origin_echo"] += 1
                continue
            classification = classify_sync_row(table, row["payload"])
            if classification.get("eligible") is not True:
                excluded_rows[str(classification.get("reason") or "unknown")] += 1
                continue
            payload_hash = hash_payload(row["payload"])
            row_refs.append(
                {
                    "table": table,
                    "id": row["id"],
                    "payload_hash": payload_hash,
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
            table_counts[table] += 1
            object_ids.update(_artifact_ids(row["payload"]))
            for dependency in _dependent_refs_for_row(
                runtime,
                table=table,
                payload=row["payload"],
                conn=conn,
            ):
                identity = (dependency["table"], dependency["id"])
                if identity in seen_refs:
                    continue
                seen_refs.add(identity)
                queued_refs.append(dependency)

    row_refs = _dedupe_row_refs(row_refs)
    sorted_object_ids = sorted(object_ids)
    prepared_at = now_iso()
    plan_id = stable_id(
        "sync_plan",
        {
            "source_device_id": local["device_id"],
            "target_device_id": normalized_peer_id,
            "base_cursor": base_cursor,
            "transaction_ids": transaction_ids,
            "row_refs": row_refs,
            "object_ids": sorted_object_ids,
        },
    )
    estimated_bundle_bytes = len(
        _canonical_json_bytes(
            {
                "row_refs": row_refs,
                "object_ids": sorted_object_ids,
                "transaction_ids": transaction_ids,
            }
        )
    )
    return {
        "schema_version": SYNC_PREPARE_SCHEMA_VERSION,
        "status": "ready",
        "write_performed": False,
        "plan_id": plan_id,
        "peer_id": normalized_peer_id,
        "prepared_at": prepared_at,
        "row_refs": row_refs,
        "object_ids": sorted_object_ids,
        "transaction_ids": transaction_ids,
        "changeset": {
            "source_device_id": local["device_id"],
            "target_device_id": normalized_peer_id,
            "base_cursor": base_cursor,
            "transaction_count": len(transaction_ids),
            "table_count": len(table_counts),
            "row_count": len(row_refs),
            "object_count": len(sorted_object_ids),
            "excluded_rows": dict(sorted(excluded_rows.items())),
            "estimated_bundle_bytes": estimated_bundle_bytes,
        },
        "error": None,
    }


def export_sync_changeset(
    runtime: Any,
    plan: dict[str, Any],
    *,
    accept: bool,
    approved_by: str | None,
) -> dict[str, Any]:
    """Write a reviewed, signed, encrypted sync changeset bundle."""
    if not accept or not str(approved_by or "").strip():
        return _policy_denied("acceptance_required")
    if not isinstance(plan, dict) or plan.get("status") != "ready":
        return _policy_denied("ready_plan_required")

    local = read_record(runtime.ledger, "sync_devices", LOCAL_DEVICE_RECORD_ID)
    if not local or local.get("status") != "active":
        return _policy_denied("local_sync_identity_not_configured")
    peer_id = str(plan.get("peer_id") or plan.get("changeset", {}).get("target_device_id") or "").strip()
    peer = _active_peer_record(runtime, peer_id)
    if peer is None:
        return _policy_denied("peer_not_registered")
    if str(plan.get("changeset", {}).get("source_device_id") or "") != str(local.get("device_id")):
        return _policy_denied("plan_source_mismatch")

    rows = _materialize_plan_rows(runtime, plan)
    if rows.get("error") is not None:
        return _policy_denied(str(rows["error"]["code"]))
    objects = _materialize_plan_objects(runtime, plan)
    if objects.get("error") is not None:
        return _policy_denied(str(objects["error"]["code"]))
    prepared_at = str(plan.get("prepared_at") or now_iso())
    changeset_id = stable_id(
        "sync_changeset",
        {
            "plan_id": plan.get("plan_id"),
            "source_device_id": local["device_id"],
            "target_device_id": peer_id,
            "row_refs": plan.get("row_refs") or [],
            "object_ids": plan.get("object_ids") or [],
            "transaction_ids": plan.get("transaction_ids") or [],
        },
    )
    payload = {
        "schema_version": SYNC_CHANGESET_SCHEMA_VERSION,
        "changeset_id": changeset_id,
        "plan_id": plan.get("plan_id"),
        "source_device_id": local["device_id"],
        "target_device_id": peer_id,
        "base_cursor": plan.get("changeset", {}).get("base_cursor"),
        "transaction_ids": list(plan.get("transaction_ids") or []),
        "rows": rows["rows"],
        "objects": objects["objects"],
        "created_at": prepared_at,
        "approved_by": str(approved_by or "").strip(),
    }
    plaintext_bytes = _canonical_json_bytes(payload)
    local_keys = load_or_create_local_sync_keys(runtime.root / "keys")
    signature = sign_payload(plaintext_bytes, local_keys.signing_private_key)
    signed_payload = {
        "payload": payload,
        "signature": signature,
        "source_signing_public_key": local["signing_public_key"],
        "source_signing_key_fingerprint": local["signing_key_fingerprint"],
    }
    aad = {
        "schema_version": SYNC_BUNDLE_SCHEMA_VERSION,
        "source_device_id": local["device_id"],
        "target_device_id": peer_id,
        "source_signing_public_key": local["signing_public_key"],
        "source_exchange_public_key": local["exchange_public_key"],
        "source_signing_key_fingerprint": local["signing_key_fingerprint"],
        "source_exchange_key_fingerprint": local["exchange_key_fingerprint"],
        "target_exchange_key_fingerprint": peer["exchange_key_fingerprint"],
        "signature": signature,
    }
    encrypted = encrypt_for_peer(
        _canonical_json_bytes(signed_payload),
        local_keys.exchange_private_key,
        str(peer["exchange_public_key"]),
        aad=_canonical_json_bytes(aad),
    )
    envelope = {
        **aad,
        "encrypted": True,
        "algorithm": encrypted["algorithm"],
        "nonce": encrypted["nonce"],
        "ciphertext": encrypted["ciphertext"],
    }
    bundle = {"schema_version": SYNC_BUNDLE_SCHEMA_VERSION, "envelope": envelope}
    bundle_bytes = _canonical_json_bytes(bundle)
    artifact_id = runtime.content_store.put_bytes(bundle_bytes, suffix=".sync.json")
    record = {
        "record_type": "sync_changeset",
        "schema_version": SYNC_CHANGESET_SCHEMA_VERSION,
        "changeset_id": changeset_id,
        "plan_id": plan.get("plan_id"),
        "artifact_id": artifact_id,
        "plaintext_hash": _hash_bytes(plaintext_bytes),
        "ciphertext_hash": _hash_bytes(str(encrypted["ciphertext"]).encode("utf-8")),
        "bundle_hash": _hash_bytes(bundle_bytes),
        "signature": signature,
        "source_device_id": local["device_id"],
        "target_device_id": peer_id,
        "source_signing_key_fingerprint": local["signing_key_fingerprint"],
        "source_exchange_key_fingerprint": local["exchange_key_fingerprint"],
        "target_exchange_key_fingerprint": peer["exchange_key_fingerprint"],
        "base_cursor": plan.get("changeset", {}).get("base_cursor"),
        "transaction_ids": list(plan.get("transaction_ids") or []),
        "row_count": len(rows["rows"]),
        "table_count": len({row["table"] for row in rows["rows"]}),
        "object_count": len(objects["objects"]),
        "status": "exported",
        "exported_at": now_iso(),
        "approved_by": str(approved_by or "").strip(),
    }
    upsert_record(runtime.ledger, "sync_changesets", changeset_id, record)
    transaction = runtime.transactions.promote(
        operation_kind="sync_changeset_export",
        proposed_writes=[{"table": "sync_changesets", "id": changeset_id}],
        idempotency_key=f"sync_changeset_export:{changeset_id}",
        affected_refs=[{"table": "sync_changesets", "id": changeset_id}, {"artifact_id": artifact_id}],
    )
    return {
        "schema_version": "2026-05-26.sync-export.v1",
        "status": "exported",
        "write_performed": True,
        "changeset_id": changeset_id,
        "artifact_id": artifact_id,
        "source_device_id": local["device_id"],
        "target_device_id": peer_id,
        "row_count": record["row_count"],
        "table_count": record["table_count"],
        "object_count": record["object_count"],
        "plaintext_hash": record["plaintext_hash"],
        "ciphertext_hash": record["ciphertext_hash"],
        "envelope": {
            "schema_version": envelope["schema_version"],
            "encrypted": True,
            "algorithm": envelope["algorithm"],
            "signature": signature,
            "source_signing_key_fingerprint": envelope["source_signing_key_fingerprint"],
            "source_exchange_key_fingerprint": envelope["source_exchange_key_fingerprint"],
            "target_exchange_key_fingerprint": envelope["target_exchange_key_fingerprint"],
        },
        "transaction": transaction,
        "error": None,
    }


def _active_peer_record(runtime: Any, peer_id: str) -> dict[str, Any] | None:
    if not peer_id:
        return None
    record = read_record(runtime.ledger, "sync_devices", f"sync_device:peer:{peer_id}")
    if not record or record.get("status") != "active" or record.get("sync_allowed") is not True:
        return None
    if not str(record.get("signing_public_key") or "").startswith("ed25519:"):
        return None
    if not str(record.get("exchange_public_key") or "").startswith("x25519:"):
        return None
    return record


def _transactions_after_cursor(runtime: Any, *, peer_id: str) -> list[dict[str, Any]]:
    base_cursor = _base_cursor(runtime, peer_id=peer_id)
    transactions = [
        record for record in list_records(runtime.ledger, "transactions")
        if record.get("transaction_id") and record.get("status") == "promoted"
    ]
    if not base_cursor:
        return transactions
    try:
        index = [str(record.get("transaction_id") or "") for record in transactions].index(base_cursor)
    except ValueError:
        return transactions
    return transactions[index + 1 :]


def _candidate_write_refs(transactions: list[dict[str, Any]]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for transaction in transactions:
        for write in transaction.get("proposed_writes") or []:
            if not isinstance(write, dict) or write.get("delete") is True:
                continue
            table = str(write.get("table") or "")
            row_id = str(write.get("id") or "")
            if not table or not row_id:
                continue
            identity = (table, row_id)
            if identity in seen:
                continue
            seen.add(identity)
            refs.append({"table": table, "id": row_id})
    return refs


def _dependent_refs_for_row(
    runtime: Any,
    *,
    table: str,
    payload: dict[str, Any],
    conn: Any | None = None,
) -> list[dict[str, str]]:
    if table != "memories":
        return []
    memory_key = str(payload.get("key") or payload.get("memory_key") or "").strip()
    refs: list[dict[str, str]] = []
    if memory_key:
        refs.extend(
            _rows_matching_json_field(
                runtime,
                "chunks",
                "memory_key",
                memory_key,
                conn=conn,
            )
        )
    refs.extend({"table": "graph_edges", "id": edge_id} for edge_id in _string_items(payload.get("metadata_graph_edge_ids")))
    refs.extend({"table": "graph_edges", "id": edge_id} for edge_id in _string_items(payload.get("semantic_graph_edge_ids")))
    refs.extend({"table": "concepts", "id": concept_id} for concept_id in _string_items(payload.get("metadata_graph_concept_ids")))
    refs.extend({"table": "concepts", "id": concept_id} for concept_id in _string_items(payload.get("semantic_graph_concept_ids")))
    refs.extend({"table": "entities", "id": entity_id} for entity_id in _string_items(payload.get("metadata_graph_entity_ids")))
    return refs


def _rows_matching_json_field(
    runtime: Any,
    table: str,
    field: str,
    value: str,
    *,
    conn: Any | None = None,
) -> list[dict[str, str]]:
    if table not in TABLES:
        return []
    if (table, field) not in _INDEXED_JSON_LOOKUP_FIELDS:
        return []
    # Keep the JSON path literal so SQLite can use the matching expression index.
    json_path = f"$.{field}"
    if conn is not None:
        rows = conn.execute(
            f"SELECT id FROM {table} WHERE json_extract(payload_json, '{json_path}') = ? ORDER BY id",  # nosec B608
            (value,),
        ).fetchall()
    else:
        runtime.ledger.initialize()
        with runtime.ledger.connect() as active_conn:
            rows = active_conn.execute(
                f"SELECT id FROM {table} WHERE json_extract(payload_json, '{json_path}') = ? ORDER BY id",  # nosec B608
                (value,),
            ).fetchall()
    return [{"table": table, "id": str(row["id"])} for row in rows]


def _string_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _dedupe_row_refs(row_refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for ref in row_refs:
        deduped[(str(ref["table"]), str(ref["id"]))] = ref
    return [deduped[key] for key in sorted(deduped)]


def _base_cursor(runtime: Any, *, peer_id: str) -> str | None:
    cursors = [
        record for record in list_records(runtime.ledger, "sync_cursors")
        if str(record.get("peer_device_id") or "") == peer_id
        and str(record.get("table") or "*") in {"*", "export"}
    ]
    if not cursors:
        return None
    latest = cursors[-1]
    return str(latest.get("last_seen_transaction_id") or "") or None


def _materialize_plan_rows(runtime: Any, plan: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    runtime.ledger.initialize()
    sync_inbox_records = list_records(runtime.ledger, "sync_inbox")
    with runtime.ledger.connect() as conn:
        for ref in plan.get("row_refs") or []:
            table = str(ref.get("table") or "")
            row_id = str(ref.get("id") or "")
            if table not in set(SYNC_ELIGIBLE_TABLES) | set(SYNC_CONDITIONAL_TABLES):
                return {"error": {"code": "plan_contains_non_sync_table"}}
            row = _read_ledger_row_from_conn(conn, table, row_id)
            if row is None:
                return {"error": {"code": "plan_row_missing"}}
            if _remote_origin_is_target(
                runtime,
                table=table,
                row_id=row_id,
                payload=row["payload"],
                peer_id=str(plan.get("peer_id") or ""),
                sync_inbox_records=sync_inbox_records,
            ):
                return {"error": {"code": "plan_row_would_echo_to_source"}}
            if classify_sync_row(table, row["payload"]).get("eligible") is not True:
                return {"error": {"code": "plan_row_no_longer_eligible"}}
            if hash_payload(row["payload"]) != ref.get("payload_hash"):
                return {"error": {"code": "plan_stale"}}
            rows.append(
                {
                    "table": table,
                    "id": row_id,
                    "payload_hash": ref.get("payload_hash"),
                    "payload": row["payload"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
    return {"rows": rows}


def _read_ledger_row(ledger: Any, table: str, row_id: str) -> dict[str, Any] | None:
    if table not in TABLES:
        return None
    ledger.initialize()
    with ledger.connect() as conn:
        return _read_ledger_row_from_conn(conn, table, row_id)


def _read_ledger_row_from_conn(conn: Any, table: str, row_id: str) -> dict[str, Any] | None:
    if table not in TABLES:
        return None
    row = conn.execute(
        f"SELECT id, payload_json, created_at, updated_at FROM {table} WHERE id = ?",  # nosec B608
        (row_id,),
    ).fetchone()
    if row is None:
        return None
    payload = json.loads(row["payload_json"])
    if not isinstance(payload, dict):
        return None
    return {
        "id": str(row["id"]),
        "payload": payload,
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def _materialize_plan_objects(runtime: Any, plan: dict[str, Any]) -> dict[str, Any]:
    objects: list[dict[str, Any]] = []
    object_ids = sorted(str(item) for item in plan.get("object_ids") or [])
    if len(object_ids) > MAX_SYNC_OBJECT_COUNT:
        return {"error": {"code": "object_count_limit_exceeded"}}
    total_bytes = 0
    for artifact_id in object_ids:
        if not _is_artifact_id(artifact_id):
            return {"error": {"code": "invalid_artifact_id"}}
        data = runtime.content_store.read_bytes(artifact_id)
        if _artifact_payload_hash(artifact_id) != _hash_bytes(data):
            return {"error": {"code": "artifact_hash_mismatch"}}
        total_bytes += len(data)
        if total_bytes > MAX_SYNC_OBJECT_BYTES:
            return {"error": {"code": "object_bytes_limit_exceeded"}}
        objects.append(
            {
                "artifact_id": artifact_id,
                "sha256": _hash_bytes(data),
                "size_bytes": len(data),
                "content_b64": base64.urlsafe_b64encode(data).decode("ascii"),
            }
        )
    return {"objects": objects}


def _artifact_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key or "")
            if _is_artifact_field(key_text) and isinstance(item, str) and _is_artifact_id(item):
                found.add(item)
            found.update(_artifact_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_artifact_ids(item))
    return found


def _remote_origin_is_target(
    runtime: Any,
    *,
    table: str,
    row_id: str,
    payload: dict[str, Any],
    peer_id: str,
    sync_inbox_records: list[dict[str, Any]] | None = None,
) -> bool:
    provenance = payload.get("sync_provenance") if isinstance(payload.get("sync_provenance"), dict) else {}
    if bool(peer_id) and provenance.get("source_device_id") == peer_id:
        return True
    if not peer_id:
        return False
    payload_hash = hash_payload(payload)
    records = sync_inbox_records if sync_inbox_records is not None else list_records(runtime.ledger, "sync_inbox")
    return any(
        str(record.get("source_device_id") or "") == peer_id
        and str(record.get("table") or "") == table
        and str(record.get("record_id") or "") == row_id
        and str(record.get("source_payload_hash") or "") == payload_hash
        for record in records
        if str(record.get("record_type") or "") == "sync_import_row"
    )


def _public_conflict_record(record: dict[str, Any]) -> dict[str, Any]:
    public = dict(record)
    public.pop("remote_payload", None)
    return public


def _is_artifact_field(key: str) -> bool:
    return key in _ARTIFACT_FIELD_NAMES or key.endswith("_artifact_id")


def _is_artifact_id(value: str) -> bool:
    return _ARTIFACT_ID_RE.match(str(value or "")) is not None


def _artifact_payload_hash(artifact_id: str) -> str:
    digest = str(artifact_id).split(":", 1)[1].split(".", 1)[0]
    return f"sha256:{digest}"


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _hash_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _policy_denied(code: str) -> dict[str, Any]:
    return {
        "schema_version": SYNC_PREPARE_SCHEMA_VERSION,
        "status": "policy_denied",
        "write_performed": False,
        "error": {"code": code},
    }
