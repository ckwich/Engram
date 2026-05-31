"""Reviewed sync changeset import planning and apply."""
from __future__ import annotations

import base64
import json
import re
from collections import defaultdict
from typing import Any

from core.memory_os._records import (
    hash_payload,
    list_records,
    now_iso,
    read_record,
    stable_id,
    upsert_record,
)
from core.memory_os.runtime_snapshots import create_verified_runtime_snapshot
from core.memory_os.schema import SYNC_CONDITIONAL_TABLES, SYNC_ELIGIBLE_TABLES, TABLES
from core.memory_os.sync_changesets import MAX_SYNC_OBJECT_BYTES, MAX_SYNC_OBJECT_COUNT
from core.memory_os.sync_crypto import decrypt_sync_bundle
from core.memory_os.sync_identity import LOCAL_DEVICE_RECORD_ID


SYNC_APPLY_SCHEMA_VERSION = "2026-05-26.sync-apply.v1"
SYNC_CONFLICT_SCHEMA_VERSION = "2026-05-26.sync-conflict.v1"
EXPECTED_SYNC_CHANGESET_SCHEMA_VERSION = "2026-05-26.sync-changeset.v1"
REFRESH_TABLES = {"memories", "chunks", "documents", "knowledge_artifacts"}
GRAPH_TABLES = {"entities", "concepts", "aliases", "graph_edges"}
SYNC_IMPORT_TABLES = frozenset(SYNC_ELIGIBLE_TABLES) | frozenset(SYNC_CONDITIONAL_TABLES)
ARTIFACT_ID_RE = re.compile(r"^sha256:[a-f0-9]{64}(?:[.][A-Za-z0-9._-]+)?$")
VOLATILE_SYNC_FIELDS = {
    "created_at",
    "updated_at",
    "sync_provenance",
    "imported_at",
    "approved_by",
}


def prepare_sync_apply(runtime: Any, bundle_bytes: bytes) -> dict[str, Any]:
    """Decrypt, verify, and classify a sync bundle without writing."""
    return _prepare_sync_apply(runtime, bundle_bytes, include_decoded_objects=False)


def _prepare_sync_apply(
    runtime: Any,
    bundle_bytes: bytes,
    *,
    include_decoded_objects: bool,
) -> dict[str, Any]:
    try:
        payload = decrypt_sync_bundle(runtime, bundle_bytes)
    except Exception:
        return _policy_denied("bundle_verification_failed")
    if payload.get("schema_version") != EXPECTED_SYNC_CHANGESET_SCHEMA_VERSION:
        return _policy_denied("unsupported_changeset_schema")
    source_device_id = str(payload.get("source_device_id") or "")
    target_device_id = str(payload.get("target_device_id") or "")
    local = read_record(runtime.ledger, "sync_devices", LOCAL_DEVICE_RECORD_ID) or {}
    if target_device_id and target_device_id != local.get("device_id"):
        return _policy_denied("target_device_mismatch")

    object_results = _verify_objects(payload.get("objects") or [])
    if object_results.get("error") is not None:
        return _policy_denied(str(object_results["error"]["code"]))

    sync_rows = _sync_payload_rows(payload.get("rows") or [])
    if sync_rows.get("error") is not None:
        return _policy_denied(str(sync_rows["error"]["code"]))
    payload_rows = sync_rows["rows"]
    local_records = _read_local_records_for_rows(runtime, payload_rows)

    apply_rows: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    idempotent_rows: list[dict[str, Any]] = []
    for row in payload_rows:
        table = row["table"]
        row_id = row["id"]
        remote_payload = row["payload"]
        remote_hash = str(row.get("payload_hash") or hash_payload(remote_payload))
        local_record = local_records.get((table, row_id))
        classification = _classify_row(
            local_record,
            table=table,
            remote_payload=remote_payload,
            remote_hash=remote_hash,
            source_device_id=source_device_id,
        )
        plan_row = {
            "table": table,
            "id": row_id,
            "payload_hash": remote_hash,
            "payload": remote_payload,
            "source_device_id": source_device_id,
            "source_changeset_id": payload.get("changeset_id"),
        }
        if classification == "conflict":
            conflicts.append(_conflict_plan_row(plan_row, local_record))
        elif classification == "idempotent":
            idempotent_rows.append(plan_row)
        else:
            plan_row["action"] = classification
            apply_rows.append(plan_row)

    conflicts = _dedupe_dependent_conflicts(conflicts)
    plan_id = stable_id(
        "sync_apply_plan",
        {
            "changeset_id": payload.get("changeset_id"),
            "source_device_id": source_device_id,
            "target_device_id": target_device_id,
            "row_hashes": [row.get("payload_hash") for row in payload.get("rows") or []],
        },
    )
    return {
        "schema_version": SYNC_APPLY_SCHEMA_VERSION,
        "status": "ready",
        "write_performed": False,
        "plan_id": plan_id,
        "changeset_id": payload.get("changeset_id"),
        "source_device_id": source_device_id,
        "target_device_id": target_device_id,
        "transaction_ids": list(payload.get("transaction_ids") or []),
        "signature_verified": True,
        "payload_hash": hash_payload(payload),
        "insert_count": len([row for row in apply_rows if row.get("action") == "insert"]),
        "update_count": len([row for row in apply_rows if row.get("action") == "update"]),
        "idempotent_count": len(idempotent_rows),
        "conflict_count": len(conflicts),
        "apply_rows": apply_rows,
        "idempotent_rows": idempotent_rows,
        "conflicts": conflicts,
        "objects": (
            object_results["objects"]
            if include_decoded_objects
            else _public_objects(object_results["objects"])
        ),
        "required_snapshot": {"present": True, "restore_grade": True},
        "error": None,
    }


def _sync_payload_rows(rows: list[Any]) -> dict[str, Any]:
    sync_rows: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        table = str(row.get("table") or "")
        row_id = str(row.get("id") or "")
        remote_payload = row.get("payload")
        if not table or not row_id or not isinstance(remote_payload, dict):
            continue
        if not _is_sync_import_table(table):
            return {"error": {"code": "unsupported_sync_table"}}
        sync_rows.append({**row, "table": table, "id": row_id, "payload": remote_payload})
    return {"rows": sync_rows, "error": None}


def _read_local_records_for_rows(runtime: Any, rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    refs_by_table: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        refs_by_table[str(row["table"])].add(str(row["id"]))
    if not refs_by_table:
        return {}

    found: dict[tuple[str, str], dict[str, Any]] = {}
    runtime.ledger.initialize()
    with runtime.ledger.connect() as conn:
        for table, row_ids in refs_by_table.items():
            if not _is_sync_import_table(table):
                continue
            sorted_ids = sorted(row_ids)
            for batch_start in range(0, len(sorted_ids), 500):
                batch = sorted_ids[batch_start: batch_start + 500]
                placeholders = ",".join("?" for _ in batch)
                rows_from_db = conn.execute(
                    f"SELECT id, payload_json FROM {table} WHERE id IN ({placeholders})",  # nosec B608
                    tuple(batch),
                ).fetchall()
                for db_row in rows_from_db:
                    decoded = json.loads(db_row["payload_json"])
                    if isinstance(decoded, dict):
                        found[(table, str(db_row["id"]))] = decoded
    return found


def apply_sync_changeset(
    runtime: Any,
    bundle_bytes: bytes,
    plan: dict[str, Any],
    *,
    accept: bool,
    approved_by: str | None,
) -> dict[str, Any]:
    """Apply a reviewed sync import plan without silent conflict overwrites."""
    reviewer = str(approved_by or "").strip()
    if not accept or not reviewer:
        return _policy_denied("acceptance_required")
    if not isinstance(plan, dict) or plan.get("status") != "ready":
        return _policy_denied("ready_plan_required")
    if plan.get("signature_verified") is not True:
        return _policy_denied("signature_verification_required")
    required_snapshot = plan.get("required_snapshot") if isinstance(plan.get("required_snapshot"), dict) else {}
    if required_snapshot.get("present") is False:
        return _policy_denied("runtime_snapshot_required")

    verified_plan = _prepare_sync_apply(runtime, bundle_bytes, include_decoded_objects=True)
    if verified_plan.get("status") != "ready":
        return verified_plan
    replay = _idempotent_apply_replay(runtime, plan)
    if replay is not None:
        return replay
    if not _review_matches_verified_plan(plan, verified_plan):
        return _policy_denied("review_plan_mismatch")

    with runtime.write_lock:
        snapshot = create_verified_runtime_snapshot(
            runtime.root,
            created_by=f"sync_apply:{reviewer}",
        )
        imported_objects = _import_objects(runtime, verified_plan.get("objects") or [])
        if imported_objects.get("error") is not None:
            return _policy_denied(str(imported_objects["error"]["code"]))

        applied_rows: list[dict[str, Any]] = []
        graph_edges: list[dict[str, Any]] = []
        source_device_id = str(verified_plan.get("source_device_id") or "")
        changeset_id = str(verified_plan.get("changeset_id") or "")
        for row in verified_plan.get("apply_rows") or []:
            if not isinstance(row, dict):
                continue
            table = str(row.get("table") or "")
            row_id = str(row.get("id") or "")
            payload = row.get("payload")
            if (
                not table
                or not row_id
                or not isinstance(payload, dict)
                or not _is_sync_import_table(table)
            ):
                continue
            if table == "graph_edges":
                graph_edges.append(payload)
            else:
                upsert_record(runtime.ledger, table, row_id, dict(payload))
            applied = {
                "table": table,
                "id": row_id,
                "action": row.get("action"),
                "payload_hash": row.get("payload_hash"),
            }
            applied_rows.append(applied)
            _store_sync_inbox_row(
                runtime,
                applied,
                source_device_id=source_device_id,
                changeset_id=changeset_id,
                approved_by=reviewer,
            )
        if graph_edges:
            runtime.graph.import_edges(graph_edges)

        conflict_records = [
            _store_conflict(runtime, conflict, approved_by=reviewer)
            for conflict in verified_plan.get("conflicts") or []
            if isinstance(conflict, dict)
        ]
        cursor = _store_apply_cursor(runtime, verified_plan, approved_by=reviewer)
        refresh_jobs = _enqueue_refresh_jobs(runtime, applied_rows)
        graph_refresh = _graph_refresh_receipt(runtime, applied_rows)
        transaction = runtime.transactions.promote(
            operation_kind="sync_changeset_apply",
            proposed_writes=[
                *[{"table": row["table"], "id": row["id"]} for row in applied_rows],
                *[{"table": "sync_conflicts", "id": conflict["conflict_id"]} for conflict in conflict_records],
                {"table": "sync_cursors", "id": cursor["cursor_id"]},
            ],
            idempotency_key=(
                "sync_changeset_apply:"
                f"{verified_plan.get('changeset_id')}:{verified_plan.get('payload_hash')}"
            ),
            snapshot_ref=snapshot["snapshot_id"],
            affected_refs=[{"changeset_id": verified_plan.get("changeset_id")}],
        )
    return {
        "schema_version": SYNC_APPLY_SCHEMA_VERSION,
        "status": "applied",
        "write_performed": True,
        "changeset_id": verified_plan.get("changeset_id"),
        "applied_count": len(applied_rows),
        "idempotent_count": len(verified_plan.get("idempotent_rows") or []),
        "conflict_count": len(conflict_records),
        "conflicts": conflict_records,
        "cursor": cursor,
        "snapshot": snapshot,
        "imported_objects": imported_objects["objects"],
        "retrieval_refresh_jobs": refresh_jobs,
        "graph_refresh": graph_refresh,
        "transaction": transaction,
        "error": None,
    }


def list_sync_conflicts(runtime: Any, *, status: str | None = None) -> dict[str, Any]:
    """List sync conflicts without loading unrelated memory bodies."""
    requested_status = str(status or "").strip()
    conflicts = [
        _public_conflict_record(record) for record in list_records(runtime.ledger, "sync_conflicts")
        if not requested_status or record.get("status") == requested_status
    ]
    unresolved = [
        record for record in conflicts
        if str(record.get("status") or "pending_review") not in {"resolved", "dismissed"}
    ]
    return {
        "schema_version": "2026-05-26.sync-conflicts.v1",
        "status": "ok",
        "write_performed": False,
        "conflicts": conflicts,
        "unresolved_conflict_count": len(unresolved),
        "error": None,
    }


def resolve_sync_conflict(
    runtime: Any,
    conflict_id: str,
    *,
    resolution: str,
    accept: bool,
    approved_by: str | None,
) -> dict[str, Any]:
    """Mark a sync conflict reviewed without directly overwriting memory rows."""
    reviewer = str(approved_by or "").strip()
    normalized_conflict_id = str(conflict_id or "").strip()
    normalized_resolution = str(resolution or "").strip()
    if not accept or not reviewer:
        return _policy_denied("acceptance_required")
    if normalized_resolution not in {"keep_local", "keep_remote_for_pr", "dismiss"}:
        return _policy_denied("unsupported_resolution")
    conflict = read_record(runtime.ledger, "sync_conflicts", normalized_conflict_id)
    if not conflict:
        return _policy_denied("conflict_not_found")
    updated = {
        **conflict,
        "status": "resolved" if normalized_resolution in {"keep_local", "dismiss"} else "pending_knowledge_pr",
        "resolution": normalized_resolution,
        "resolved_at": now_iso(),
        "approved_by": reviewer,
    }
    upsert_record(runtime.ledger, "sync_conflicts", normalized_conflict_id, updated)
    transaction = runtime.transactions.promote(
        operation_kind="sync_conflict_resolve",
        proposed_writes=[{"table": "sync_conflicts", "id": normalized_conflict_id}],
        idempotency_key=f"sync_conflict_resolve:{normalized_conflict_id}:{normalized_resolution}",
        affected_refs=[{"table": "sync_conflicts", "id": normalized_conflict_id}],
    )
    return {
        "schema_version": SYNC_CONFLICT_SCHEMA_VERSION,
        "status": "resolved",
        "write_performed": True,
        "conflict": _public_conflict_record(updated),
        "transaction": transaction,
        "error": None,
    }


def _verify_objects(objects: list[Any]) -> dict[str, Any]:
    if len(objects) > MAX_SYNC_OBJECT_COUNT:
        return {"error": {"code": "sync_object_count_limit_exceeded"}}
    total_bytes = 0
    verified: list[dict[str, Any]] = []
    for obj in objects:
        if not isinstance(obj, dict):
            return {"error": {"code": "invalid_object"}}
        artifact_id = str(obj.get("artifact_id") or "")
        if not _is_artifact_id(artifact_id):
            return {"error": {"code": "malformed_object_artifact_id"}}
        content_b64 = str(obj.get("content_b64") or "")
        try:
            data = base64.urlsafe_b64decode(content_b64.encode("ascii"))
        except Exception:
            return {"error": {"code": "invalid_object_encoding"}}
        actual_hash = _hash_bytes(data)
        if obj.get("sha256") != actual_hash:
            return {"error": {"code": "object_hash_mismatch"}}
        if artifact_id and _artifact_payload_hash(artifact_id) != actual_hash:
            return {"error": {"code": "artifact_id_hash_mismatch"}}
        total_bytes += len(data)
        if total_bytes > MAX_SYNC_OBJECT_BYTES:
            return {"error": {"code": "sync_object_byte_limit_exceeded"}}
        verified.append({**obj, "decoded_bytes": data})
    return {"objects": verified}


def _public_objects(objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in obj.items() if key != "decoded_bytes"}
        for obj in objects
    ]


def _classify_row(
    local_record: dict[str, Any] | None,
    *,
    table: str,
    remote_payload: dict[str, Any],
    remote_hash: str,
    source_device_id: str,
) -> str:
    if local_record is None:
        return "insert"
    if hash_payload(local_record) == remote_hash:
        return "idempotent"
    provenance = local_record.get("sync_provenance") if isinstance(local_record.get("sync_provenance"), dict) else {}
    if (
        provenance.get("source_device_id") == source_device_id
        and provenance.get("source_payload_hash") == remote_hash
    ):
        return "idempotent"
    if _equivalent_sync_payload(table, local_record, remote_payload):
        return "idempotent"
    return "conflict"


def _review_matches_verified_plan(reviewed: dict[str, Any], verified: dict[str, Any]) -> bool:
    keys = (
        "plan_id",
        "changeset_id",
        "source_device_id",
        "target_device_id",
        "payload_hash",
        "insert_count",
        "update_count",
        "conflict_count",
    )
    return all(reviewed.get(key) == verified.get(key) for key in keys)


def _conflict_plan_row(row: dict[str, Any], local_record: dict[str, Any] | None) -> dict[str, Any]:
    local_hash = hash_payload(local_record) if isinstance(local_record, dict) else None
    conflict_id = stable_id(
        "sync_conflict",
        {
            "table": row["table"],
            "id": row["id"],
            "source_device_id": row["source_device_id"],
            "source_changeset_id": row["source_changeset_id"],
            "local_payload_hash": local_hash,
            "remote_payload_hash": row["payload_hash"],
        },
    )
    return {
        "conflict_id": conflict_id,
        "table": row["table"],
        "id": row["id"],
        "source_device_id": row["source_device_id"],
        "source_changeset_id": row["source_changeset_id"],
        "local_payload_hash": local_hash,
        "remote_payload_hash": row["payload_hash"],
        "remote_payload": row["payload"],
        "status": "pending_review",
    }


def _dedupe_dependent_conflicts(conflicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    memory_conflict_ids = {
        str(conflict.get("id") or "")
        for conflict in conflicts
        if conflict.get("table") == "memories"
    }
    filtered: list[dict[str, Any]] = []
    for conflict in conflicts:
        if conflict.get("table") == "chunks":
            row_id = str(conflict.get("id") or "")
            if any(row_id.startswith(f"{memory_key}:chunk:") for memory_key in memory_conflict_ids):
                continue
        if conflict.get("table") == "graph_edges" and _graph_conflict_depends_on_memory_conflict(
            conflict,
            memory_conflict_ids,
        ):
            continue
        filtered.append(conflict)
    return filtered


def _graph_conflict_depends_on_memory_conflict(
    conflict: dict[str, Any],
    memory_conflict_ids: set[str],
) -> bool:
    remote = conflict.get("remote_payload") if isinstance(conflict.get("remote_payload"), dict) else {}
    refs = [
        remote.get("from_ref"),
        remote.get("to_ref"),
        *(remote.get("evidence_refs") or [] if isinstance(remote.get("evidence_refs"), list) else []),
    ]
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        for field in ("key", "memory_key", "chunk_record_id"):
            value = str(ref.get(field) or "")
            if not value:
                continue
            if value in memory_conflict_ids:
                return True
            if any(value.startswith(f"{memory_key}:chunk:") for memory_key in memory_conflict_ids):
                return True
    return False


def _equivalent_sync_payload(table: str, local: dict[str, Any], remote: dict[str, Any]) -> bool:
    if table == "memories":
        return (
            local.get("content_hash") is not None
            and local.get("content_hash") == remote.get("content_hash")
            and local.get("content_artifact_id") == remote.get("content_artifact_id")
        )
    if table == "chunks":
        return (
            local.get("text_hash") is not None
            and local.get("text_hash") == remote.get("text_hash")
            and local.get("memory_key") == remote.get("memory_key")
        )
    return _stable_payload(local) == _stable_payload(remote)


def _stable_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _stable_payload(item)
            for key, item in sorted(value.items())
            if key not in VOLATILE_SYNC_FIELDS
        }
    if isinstance(value, list):
        return [_stable_payload(item) for item in value]
    return value


def _import_objects(runtime: Any, objects: list[dict[str, Any]]) -> dict[str, Any]:
    imported: list[dict[str, Any]] = []
    for obj in objects:
        artifact_id = str(obj.get("artifact_id") or "")
        if not _is_artifact_id(artifact_id):
            return {"error": {"code": "malformed_object_artifact_id"}}
        data = obj.get("decoded_bytes")
        if not isinstance(data, bytes):
            return {"error": {"code": "object_not_verified"}}
        suffix = _artifact_suffix(artifact_id)
        stored_id = runtime.content_store.put_bytes(data, suffix=suffix)
        if stored_id != artifact_id:
            return {"error": {"code": "artifact_store_id_mismatch"}}
        imported.append({"artifact_id": artifact_id, "size_bytes": len(data)})
    return {"objects": imported}


def _store_conflict(runtime: Any, conflict: dict[str, Any], *, approved_by: str) -> dict[str, Any]:
    existing = read_record(runtime.ledger, "sync_conflicts", str(conflict["conflict_id"]))
    if existing:
        return _public_conflict_record(existing)
    now = now_iso()
    knowledge_pr_id = _prepare_conflict_knowledge_pr(runtime, conflict)
    remote_payload = conflict.get("remote_payload") if isinstance(conflict.get("remote_payload"), dict) else {}
    record = {
        "schema_version": SYNC_CONFLICT_SCHEMA_VERSION,
        "record_type": "sync_conflict",
        **_conflict_metadata(conflict),
        "knowledge_pr_id": knowledge_pr_id,
        "remote_payload_summary": _remote_payload_summary(remote_payload),
        "detected_at": now,
        "updated_at": now,
        "approved_by": approved_by,
    }
    upsert_record(runtime.ledger, "sync_conflicts", record["conflict_id"], record)
    _store_conflict_payload(runtime, conflict, approved_by=approved_by)
    return _public_conflict_record(record)


def _prepare_conflict_knowledge_pr(runtime: Any, conflict: dict[str, Any]) -> str | None:
    service = getattr(runtime, "knowledge_prs", None)
    if service is None:
        return None
    branch = service.prepare_knowledge_branch(
        name=f"sync conflict {conflict['conflict_id']}",
        source_refs=[{"kind": "sync_conflict", "conflict_id": conflict["conflict_id"]}],
        metadata={"source": "sync_apply", "conflict_id": conflict["conflict_id"]},
    )
    branch_id = branch.get("branch_id")
    if not branch_id:
        return None
    remote = conflict.get("remote_payload") if isinstance(conflict.get("remote_payload"), dict) else {}
    operation = _conflict_pr_operation(runtime, conflict, remote)
    pr = service.prepare_knowledge_pr(
        branch_id=branch_id,
        title=f"Review sync conflict for {conflict['table']}:{conflict['id']}",
        proposed_operations=[operation],
        source_refs=[{"kind": "sync_conflict", "conflict_id": conflict["conflict_id"]}],
        metadata={"source": "sync_apply", "conflict_id": conflict["conflict_id"]},
    )
    return pr.get("knowledge_pr_id")


def _conflict_pr_operation(
    runtime: Any,
    conflict: dict[str, Any],
    remote: dict[str, Any],
) -> dict[str, Any]:
    evidence_refs = [{"kind": "sync_conflict", "conflict_id": conflict["conflict_id"]}]
    if conflict["table"] == "memories":
        return {
            "operation_id": f"sync_conflict:{conflict['conflict_id']}",
            "operation_kind": "memory_write",
            "key": remote.get("key") or conflict["id"],
            "content": _memory_content(runtime, remote),
            "title": remote.get("title"),
            "tags": list(remote.get("tags") or []),
            "project": remote.get("project"),
            "domain": remote.get("domain"),
            "status": remote.get("status") or "active",
            "canonical": remote.get("canonical"),
            "memory_type": remote.get("memory_type"),
            "scope": remote.get("scope"),
            "trust_state": remote.get("trust_state"),
            "retention_policy": remote.get("retention_policy"),
            "sync_policy": remote.get("sync_policy"),
            "document_id": remote.get("document_id"),
            "source_id": remote.get("source_id"),
            "source_document": (
                remote.get("source_document")
                if isinstance(remote.get("source_document"), dict)
                else None
            ),
            "citations": list(remote.get("citations") or []),
            "force": True,
            "evidence_refs": evidence_refs,
            "metadata": {"resolution_required": True},
        }
    if conflict["table"] == "graph_edges":
        return {
            "operation_id": f"sync_conflict:{conflict['conflict_id']}",
            "operation_kind": "graph_edges",
            "edges": [remote],
            "evidence_refs": evidence_refs,
            "metadata": {"resolution_required": True},
        }
    return {
        "operation_id": f"sync_conflict:{conflict['conflict_id']}",
        "operation_kind": "memory_write",
        "key": f"sync_conflict_{conflict['conflict_id'].split(':', 1)[-1][:16]}",
        "content": "Review unsupported sync conflict type before applying remote data.",
        "scope": "device",
        "memory_type": "open_loop",
        "trust_state": "unreviewed",
        "retention_policy": "local_only",
        "sync_policy": "local_only",
        "evidence_refs": evidence_refs,
        "metadata": {
            "resolution_required": True,
            "unsupported_sync_conflict_table": conflict["table"],
            "record_id": conflict["id"],
        },
    }


def _memory_content(runtime: Any, memory: dict[str, Any]) -> str:
    artifact_id = str(memory.get("content_artifact_id") or "")
    if not artifact_id:
        return str(memory.get("content") or memory.get("title") or "Review remote sync memory.")
    try:
        return runtime.content_store.read_bytes(artifact_id).decode("utf-8")
    except Exception:
        return str(memory.get("title") or "Remote sync memory content artifact is unavailable for review.")


def _conflict_metadata(conflict: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in conflict.items()
        if key != "remote_payload"
    }


def _remote_payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "content_hash": payload.get("content_hash"),
        "content_artifact_id": payload.get("content_artifact_id"),
        "text_hash": payload.get("text_hash"),
        "edge_id": payload.get("edge_id"),
        "edge_type": payload.get("edge_type"),
        "key": payload.get("key"),
        "memory_key": payload.get("memory_key"),
        "title": payload.get("title"),
    }
    return {key: value for key, value in summary.items() if value is not None}


def _store_conflict_payload(runtime: Any, conflict: dict[str, Any], *, approved_by: str) -> None:
    remote_payload = conflict.get("remote_payload")
    if not isinstance(remote_payload, dict):
        return
    inbox_id = f"sync_inbox:conflict:{conflict['conflict_id'].split(':', 1)[-1]}"
    upsert_record(
        runtime.ledger,
        "sync_inbox",
        inbox_id,
        {
            "record_type": "sync_conflict_payload",
            "conflict_id": conflict["conflict_id"],
            "table": conflict["table"],
            "record_id": conflict["id"],
            "remote_payload_hash": conflict.get("remote_payload_hash"),
            "remote_payload": remote_payload,
            "stored_at": now_iso(),
            "approved_by": approved_by,
            "sync_policy": "local_only",
        },
    )


def _public_conflict_record(record: dict[str, Any]) -> dict[str, Any]:
    public = dict(record)
    public.pop("remote_payload", None)
    return public


def _store_sync_inbox_row(
    runtime: Any,
    row: dict[str, Any],
    *,
    source_device_id: str,
    changeset_id: str,
    approved_by: str,
) -> None:
    inbox_id = stable_id(
        "sync_inbox",
        {
            "source_device_id": source_device_id,
            "changeset_id": changeset_id,
            "table": row.get("table"),
            "id": row.get("id"),
            "payload_hash": row.get("payload_hash"),
        },
    )
    upsert_record(
        runtime.ledger,
        "sync_inbox",
        inbox_id,
        {
            "record_type": "sync_import_row",
            "source_device_id": source_device_id,
            "source_changeset_id": changeset_id,
            "table": row.get("table"),
            "record_id": row.get("id"),
            "source_payload_hash": row.get("payload_hash"),
            "imported_at": now_iso(),
            "approved_by": approved_by,
            "sync_policy": "local_only",
        },
    )


def _store_apply_cursor(runtime: Any, plan: dict[str, Any], *, approved_by: str) -> dict[str, Any]:
    source_device_id = str(plan.get("source_device_id") or "")
    cursor_id = stable_id(
        "sync_cursor",
        {
            "peer_device_id": source_device_id,
            "changeset_id": plan.get("changeset_id"),
            "direction": "apply",
        },
    )
    cursor = {
        "record_type": "sync_cursor",
        "cursor_id": cursor_id,
        "peer_device_id": source_device_id,
        "table": "apply",
        "last_seen_transaction_id": _last_transaction_id(plan),
        "last_seen_changeset_id": plan.get("changeset_id"),
        "applied_at": now_iso(),
        "approved_by": approved_by,
    }
    upsert_record(runtime.ledger, "sync_cursors", cursor_id, cursor)
    return cursor


def _idempotent_apply_replay(runtime: Any, reviewed_plan: dict[str, Any]) -> dict[str, Any] | None:
    receipt = runtime.transactions.find_by_idempotency_key(
        f"sync_changeset_apply:{reviewed_plan.get('changeset_id')}:{reviewed_plan.get('payload_hash')}"
    )
    if not isinstance(receipt, dict) or receipt.get("status") != "promoted":
        return None
    if not _all_reviewed_rows_are_local(runtime, reviewed_plan):
        return None
    cursor = _existing_apply_cursor(runtime, reviewed_plan)
    if cursor is None:
        return None
    conflicts = [
        read_record(runtime.ledger, "sync_conflicts", str(conflict.get("conflict_id") or ""))
        for conflict in reviewed_plan.get("conflicts") or []
        if isinstance(conflict, dict) and conflict.get("conflict_id")
    ]
    public_conflicts = [
        _public_conflict_record(conflict)
        for conflict in conflicts
        if isinstance(conflict, dict)
    ]
    return {
        "schema_version": SYNC_APPLY_SCHEMA_VERSION,
        "status": "applied",
        "write_performed": False,
        "idempotent_replay": True,
        "changeset_id": reviewed_plan.get("changeset_id"),
        "applied_count": 0,
        "idempotent_count": len(reviewed_plan.get("apply_rows") or []) + len(reviewed_plan.get("idempotent_rows") or []),
        "conflict_count": len(public_conflicts),
        "conflicts": public_conflicts,
        "cursor": cursor,
        "snapshot": {"snapshot_id": receipt.get("snapshot_ref"), "restore_grade": True},
        "imported_objects": [],
        "retrieval_refresh_jobs": [],
        "graph_refresh": None,
        "transaction": {**receipt, "idempotent_replay": True},
        "error": None,
    }


def _all_reviewed_rows_are_local(runtime: Any, reviewed_plan: dict[str, Any]) -> bool:
    source_device_id = str(reviewed_plan.get("source_device_id") or "")
    for row in reviewed_plan.get("apply_rows") or []:
        if not isinstance(row, dict):
            return False
        table = str(row.get("table") or "")
        row_id = str(row.get("id") or "")
        payload_hash = str(row.get("payload_hash") or "")
        if not table or not row_id or not payload_hash or not _is_sync_import_table(table):
            return False
        local = read_record(runtime.ledger, table, row_id)
        if not isinstance(local, dict):
            return False
        if hash_payload(local) != payload_hash:
            return False
        if not _has_sync_inbox_row(
            runtime,
            source_device_id=source_device_id,
            changeset_id=str(reviewed_plan.get("changeset_id") or ""),
            table=table,
            row_id=row_id,
            payload_hash=payload_hash,
        ):
            return False
    return True


def _has_sync_inbox_row(
    runtime: Any,
    *,
    source_device_id: str,
    changeset_id: str,
    table: str,
    row_id: str,
    payload_hash: str,
) -> bool:
    return any(
        str(record.get("record_type") or "") == "sync_import_row"
        and str(record.get("source_device_id") or "") == source_device_id
        and str(record.get("source_changeset_id") or "") == changeset_id
        and str(record.get("table") or "") == table
        and str(record.get("record_id") or "") == row_id
        and str(record.get("source_payload_hash") or "") == payload_hash
        for record in list_records(runtime.ledger, "sync_inbox")
    )


def _is_sync_import_table(table: str) -> bool:
    return table in SYNC_IMPORT_TABLES and table in TABLES


def _existing_apply_cursor(runtime: Any, reviewed_plan: dict[str, Any]) -> dict[str, Any] | None:
    expected_id = stable_id(
        "sync_cursor",
        {
            "peer_device_id": str(reviewed_plan.get("source_device_id") or ""),
            "changeset_id": reviewed_plan.get("changeset_id"),
            "direction": "apply",
        },
    )
    return read_record(runtime.ledger, "sync_cursors", expected_id)


def _enqueue_refresh_jobs(runtime: Any, applied_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    memory_keys = {
        str(row["id"])
        for row in applied_rows
        if row.get("table") == "memories"
    }
    memory_keys.update(
        str(row["id"]).split(":chunk:", 1)[0]
        for row in applied_rows
        if row.get("table") == "chunks" and ":chunk:" in str(row.get("id") or "")
    )
    for key in sorted(memory_keys):
        if hasattr(runtime, "_enqueue_memory_retrieval_refresh"):
            jobs.append(runtime._enqueue_memory_retrieval_refresh(key))
    return jobs


def _graph_refresh_receipt(runtime: Any, applied_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not any(row.get("table") in GRAPH_TABLES for row in applied_rows):
        return None
    return runtime.graph.reconciliation_state()


def _last_transaction_id(plan: dict[str, Any]) -> str | None:
    transaction_ids = plan.get("transaction_ids")
    if isinstance(transaction_ids, list) and transaction_ids:
        return str(transaction_ids[-1])
    return str(plan.get("changeset_id") or "")


def _artifact_suffix(artifact_id: str) -> str:
    digest_part = artifact_id.split(":", 1)[1]
    if "." not in digest_part:
        return ""
    return "." + digest_part.split(".", 1)[1]


def _artifact_payload_hash(artifact_id: str) -> str:
    digest = str(artifact_id).split(":", 1)[1].split(".", 1)[0]
    return f"sha256:{digest}"


def _is_artifact_id(value: str) -> bool:
    return ARTIFACT_ID_RE.match(str(value or "")) is not None


def _hash_bytes(data: bytes) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(data).hexdigest()


def _policy_denied(code: str) -> dict[str, Any]:
    return {
        "schema_version": SYNC_APPLY_SCHEMA_VERSION,
        "status": "policy_denied",
        "write_performed": False,
        "error": {"code": code},
    }
