"""Reviewed application of locally staged sync inbox bundles."""
from __future__ import annotations

from copy import deepcopy
from time import perf_counter
from typing import Any

from core.memory_os._records import list_records, now_iso, read_record, upsert_record
from core.memory_os.sync_apply import apply_sync_changeset, prepare_sync_apply


SYNC_INBOX_APPLY_SCHEMA_VERSION = "2026-05-27.sync-inbox-apply.v1"
SYNC_INBOX_PRUNE_SCHEMA_VERSION = "2026-05-28.sync-inbox-prune.v1"
PLAN_CACHE_MAX_ENTRIES = 8


def prepare_sync_inbox_apply(
    runtime: Any,
    *,
    peer_id: str | None = None,
    limit: int | None = 50,
) -> dict[str, Any]:
    """Prepare a compact no-write plan for applying staged sync inbox bundles."""
    records = _pending_bundle_records(runtime, peer_id=peer_id, limit=limit)
    bundles = []
    totals = _empty_totals()
    for record in records:
        started_at = perf_counter()
        plan = _prepare_record_plan(runtime, record)
        plan["_prepare_duration_ms"] = round((perf_counter() - started_at) * 1000, 3)
        bundles.append(_public_bundle_plan(record, plan))
        _add_plan_totals(totals, plan)

    blocked = [item for item in bundles if item.get("plan_status") != "ready"]
    return {
        "schema_version": SYNC_INBOX_APPLY_SCHEMA_VERSION,
        "status": "blocked" if blocked else ("ready" if bundles else "empty"),
        "write_performed": False,
        "peer_id": _text(peer_id),
        "limit": _public_limit(limit),
        "pending_bundle_count": len(bundles),
        "blocked_bundle_count": len(blocked),
        **totals,
        "bundles": bundles,
        "error": None,
    }


def apply_sync_inbox(
    runtime: Any,
    *,
    accept: bool,
    approved_by: str | None,
    peer_id: str | None = None,
    limit: int | None = 50,
    stop_on_error: bool = True,
) -> dict[str, Any]:
    """Apply staged sync inbox bundles after explicit operator acceptance."""
    reviewer = _text(approved_by)
    if not accept or not reviewer:
        return _policy_denied("acceptance_required")

    records = _pending_bundle_records(runtime, peer_id=peer_id, limit=limit)
    outcomes = []
    totals = _empty_totals()
    failures = []
    for record in records:
        outcome = _apply_inbox_record(runtime, record, approved_by=reviewer)
        outcomes.append(outcome)
        _add_outcome_totals(totals, outcome)
        if outcome.get("status") != "applied":
            failures.append(outcome)
            if stop_on_error:
                break

    if failures and len(outcomes) < len(records):
        status = "partial"
    elif failures:
        status = "blocked"
    elif outcomes:
        status = "applied"
    else:
        status = "empty"

    return {
        "schema_version": SYNC_INBOX_APPLY_SCHEMA_VERSION,
        "status": status,
        "write_performed": any(item.get("status") == "applied" for item in outcomes),
        "peer_id": _text(peer_id),
        "limit": _public_limit(limit),
        "pending_bundle_count": len(records),
        "processed_bundle_count": len(outcomes),
        "applied_bundle_count": len([item for item in outcomes if item.get("status") == "applied"]),
        "failed_bundle_count": len(failures),
        **totals,
        "bundles": outcomes,
        "error": failures[0].get("error") if failures else None,
    }


def _apply_inbox_record(runtime: Any, record: dict[str, Any], *, approved_by: str) -> dict[str, Any]:
    plan = _prepare_record_plan(runtime, record)
    if plan.get("status") != "ready":
        return {
            **_public_bundle_record(record),
            "status": "blocked",
            "plan_status": plan.get("status"),
            "error": plan.get("error") or {"code": "sync_inbox_plan_not_ready"},
        }
    bundle = _read_bundle(runtime, record)
    if bundle.get("error") is not None:
        return {
            **_public_bundle_record(record),
            "status": "blocked",
            "plan_status": plan.get("status"),
            "error": bundle["error"],
        }
    result = apply_sync_changeset(
        runtime,
        bundle["bundle"],
        plan,
        accept=True,
        approved_by=approved_by,
    )
    outcome = {
        **_public_bundle_record(record),
        "status": result.get("status"),
        "plan_status": plan.get("status"),
        "changeset_id": result.get("changeset_id") or plan.get("changeset_id"),
        "insert_count": int(plan.get("insert_count") or 0),
        "update_count": int(plan.get("update_count") or 0),
        "idempotent_count": int(result.get("idempotent_count") or plan.get("idempotent_count") or 0),
        "conflict_count": int(result.get("conflict_count") or 0),
        "applied_count": int(result.get("applied_count") or 0),
        "snapshot_id": (result.get("snapshot") or {}).get("snapshot_id"),
        "transaction_id": (result.get("transaction") or {}).get("transaction_id"),
        "idempotent_replay": bool(result.get("idempotent_replay", False)),
        "error": result.get("error"),
    }
    if result.get("status") == "applied":
        _mark_inbox_bundle_applied(runtime, record, outcome, approved_by=approved_by)
        outcome["artifact_prune"] = _prune_applied_bundle_artifact(
            runtime,
            inbox_id=str(record["inbox_id"]),
            approved_by=approved_by,
        )
    return outcome


def prune_applied_sync_inbox_artifacts(
    runtime: Any,
    *,
    accept: bool,
    approved_by: str | None,
    peer_id: str | None = None,
    limit: int | None = 50,
) -> dict[str, Any]:
    """Prune encrypted bundle bytes after staged sync bundles have been applied."""
    records = _applied_bundle_records(runtime, peer_id=peer_id, limit=limit)
    if not accept:
        outcomes = [
            _prune_preview(runtime, record)
            for record in records
        ]
        return _prune_response(
            status="ready" if outcomes else "empty",
            write_performed=False,
            peer_id=peer_id,
            limit=limit,
            outcomes=outcomes,
        )

    reviewer = _text(approved_by)
    if not reviewer:
        return _prune_policy_denied("acceptance_required")

    outcomes = [
        _prune_applied_bundle_artifact(
            runtime,
            inbox_id=str(record["inbox_id"]),
            approved_by=reviewer,
        )
        for record in records
    ]
    failures = [item for item in outcomes if item.get("status") == "failed"]
    if failures:
        status = "partial" if len(failures) < len(outcomes) else "blocked"
    elif outcomes:
        status = "pruned"
    else:
        status = "empty"
    return _prune_response(
        status=status,
        write_performed=any(item.get("write_performed") for item in outcomes),
        peer_id=peer_id,
        limit=limit,
        outcomes=outcomes,
        error=failures[0].get("error") if failures else None,
    )


def _prepare_record_plan(runtime: Any, record: dict[str, Any]) -> dict[str, Any]:
    cache_key = _plan_cache_key(runtime, record)
    cache = _plan_cache(runtime)
    if cache_key in cache:
        cached = deepcopy(cache[cache_key])
        cached["_cache_status"] = "hit"
        return cached

    bundle = _read_bundle(runtime, record)
    if bundle.get("error") is not None:
        return {
            "status": "blocked",
            "write_performed": False,
            "error": bundle["error"],
            "_cache_status": "miss",
        }
    plan = prepare_sync_apply(runtime, bundle["bundle"])
    _store_cached_plan(cache, cache_key, plan)
    result = deepcopy(plan)
    result["_cache_status"] = "miss"
    return result


def _read_bundle(runtime: Any, record: dict[str, Any]) -> dict[str, Any]:
    artifact_id = _text(record.get("artifact_id"))
    if not artifact_id:
        return {"error": {"code": "sync_inbox_artifact_missing"}}
    try:
        return {"bundle": runtime.content_store.read_bytes(artifact_id), "error": None}
    except Exception as exc:
        return {
            "error": {
                "code": "sync_inbox_artifact_unreadable",
                "message": str(exc),
            }
        }


def _pending_bundle_records(
    runtime: Any,
    *,
    peer_id: str | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    normalized_peer_id = _text(peer_id)
    normalized_limit = _normalize_limit(limit)
    records = []
    for record in list_records(runtime.ledger, "sync_inbox"):
        if record.get("record_type") != "sync_bundle":
            continue
        if bool(record.get("apply_performed", False)):
            continue
        if str(record.get("status") or "") == "applied":
            continue
        artifact_id = str(record.get("artifact_id") or "")
        if not artifact_id.endswith(".engram-sync"):
            continue
        if normalized_peer_id and record.get("peer_id") != normalized_peer_id:
            continue
        records.append(record)
    records.sort(key=lambda item: str(item.get("received_at") or ""))
    if normalized_limit is not None:
        return records[:normalized_limit]
    return records


def _mark_inbox_bundle_applied(
    runtime: Any,
    record: dict[str, Any],
    outcome: dict[str, Any],
    *,
    approved_by: str,
) -> None:
    timestamp = now_iso()
    updated = {
        **record,
        "status": "applied",
        "apply_performed": True,
        "applied_at": timestamp,
        "updated_at": timestamp,
        "approved_by": approved_by,
        "apply_result": {
            "changeset_id": outcome.get("changeset_id"),
            "applied_count": outcome.get("applied_count"),
            "idempotent_count": outcome.get("idempotent_count"),
            "conflict_count": outcome.get("conflict_count"),
            "snapshot_id": outcome.get("snapshot_id"),
            "transaction_id": outcome.get("transaction_id"),
            "idempotent_replay": outcome.get("idempotent_replay"),
        },
    }
    upsert_record(runtime.ledger, "sync_inbox", str(record["inbox_id"]), updated)


def _applied_bundle_records(
    runtime: Any,
    *,
    peer_id: str | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    normalized_peer_id = _text(peer_id)
    normalized_limit = _normalize_limit(limit)
    records = []
    for record in list_records(runtime.ledger, "sync_inbox"):
        if record.get("record_type") != "sync_bundle":
            continue
        if normalized_peer_id and record.get("peer_id") != normalized_peer_id:
            continue
        if not _bundle_is_applied(record):
            continue
        if not _text(record.get("artifact_id")):
            continue
        if record.get("artifact_prune_status") in {"deleted", "already_missing"}:
            continue
        records.append(record)
    records.sort(key=lambda item: str(item.get("applied_at") or item.get("updated_at") or ""))
    if normalized_limit is not None:
        return records[:normalized_limit]
    return records


def _bundle_is_applied(record: dict[str, Any]) -> bool:
    return bool(record.get("apply_performed", False)) or str(record.get("status") or "") == "applied"


def _prune_applied_bundle_artifact(runtime: Any, *, inbox_id: str, approved_by: str) -> dict[str, Any]:
    record = read_record(runtime.ledger, "sync_inbox", inbox_id)
    if not isinstance(record, dict):
        return _prune_outcome(inbox_id=inbox_id, status="failed", error={"code": "sync_inbox_record_missing"})
    if record.get("record_type") != "sync_bundle" or not _bundle_is_applied(record):
        return _prune_outcome(record=record, status="skipped", reason="bundle_not_applied")
    if record.get("artifact_prune_status") in {"deleted", "already_missing"}:
        return _prune_outcome(record=record, status=str(record.get("artifact_prune_status")), already_pruned=True)

    artifact_id = _text(record.get("artifact_id"))
    if not artifact_id or not artifact_id.endswith(".engram-sync"):
        return _prune_outcome(record=record, status="skipped", reason="non_sync_artifact")
    if _artifact_has_unapplied_reference(runtime, artifact_id=artifact_id):
        return _prune_outcome(record=record, status="skipped", reason="artifact_still_referenced_by_pending_bundle")

    timestamp = now_iso()
    try:
        path = runtime.content_store.path_for(artifact_id)
    except Exception as exc:
        return _prune_outcome(
            record=record,
            status="failed",
            error={"code": "invalid_artifact_id", "message": str(exc)},
        )

    existed = path.exists()
    size_bytes = path.stat().st_size if existed else 0
    if existed:
        try:
            path.unlink()
        except Exception as exc:
            return _prune_outcome(
                record=record,
                status="failed",
                error={"code": "artifact_delete_failed", "message": str(exc)},
            )

    updated = {
        **record,
        "artifact_prune_status": "deleted" if existed else "already_missing",
        "artifact_pruned_at": timestamp,
        "artifact_pruned_by": approved_by,
        "artifact_size_bytes_pruned": size_bytes,
        "updated_at": timestamp,
    }
    upsert_record(runtime.ledger, "sync_inbox", str(record["inbox_id"]), updated)
    return _prune_outcome(
        record=updated,
        status=updated["artifact_prune_status"],
        write_performed=True,
        size_bytes_pruned=size_bytes,
    )


def _artifact_has_unapplied_reference(runtime: Any, *, artifact_id: str) -> bool:
    for record in list_records(runtime.ledger, "sync_inbox"):
        if record.get("record_type") != "sync_bundle":
            continue
        if record.get("artifact_id") != artifact_id:
            continue
        if not _bundle_is_applied(record):
            return True
    return False


def _prune_preview(runtime: Any, record: dict[str, Any]) -> dict[str, Any]:
    artifact_id = _text(record.get("artifact_id"))
    exists = False
    actual_size = 0
    if artifact_id:
        try:
            path = runtime.content_store.path_for(artifact_id)
            exists = path.exists()
            actual_size = path.stat().st_size if exists else 0
        except Exception:
            exists = False
    return _prune_outcome(
        record=record,
        status="candidate",
        write_performed=False,
        artifact_exists=exists,
        size_bytes_pruned=actual_size,
    )


def _prune_response(
    *,
    status: str,
    write_performed: bool,
    peer_id: str | None,
    limit: int | None,
    outcomes: list[dict[str, Any]],
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pruned_statuses = {"deleted", "already_missing"}
    return {
        "schema_version": SYNC_INBOX_PRUNE_SCHEMA_VERSION,
        "status": status,
        "write_performed": bool(write_performed),
        "peer_id": _text(peer_id),
        "limit": _public_limit(limit),
        "candidate_count": len(outcomes),
        "pruned_count": len([item for item in outcomes if item.get("status") in pruned_statuses]),
        "skipped_count": len([item for item in outcomes if item.get("status") == "skipped"]),
        "failed_count": len([item for item in outcomes if item.get("status") == "failed"]),
        "bytes_prunable": sum(int(item.get("size_bytes_pruned") or 0) for item in outcomes),
        "bytes_pruned": sum(
            int(item.get("size_bytes_pruned") or 0)
            for item in outcomes
            if item.get("status") in pruned_statuses
        ),
        "bundles": outcomes,
        "error": error,
    }


def _prune_outcome(
    *,
    status: str,
    record: dict[str, Any] | None = None,
    inbox_id: str | None = None,
    write_performed: bool = False,
    artifact_exists: bool | None = None,
    size_bytes_pruned: int = 0,
    already_pruned: bool = False,
    reason: str | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "inbox_id": (record or {}).get("inbox_id") or inbox_id,
        "artifact_id": (record or {}).get("artifact_id"),
        "peer_id": (record or {}).get("peer_id"),
        "status": status,
        "write_performed": bool(write_performed),
        "artifact_exists": artifact_exists,
        "size_bytes": (record or {}).get("size_bytes"),
        "size_bytes_pruned": int(size_bytes_pruned or 0),
        "already_pruned": bool(already_pruned),
        "reason": reason,
        "error": error,
    }
    return {key: value for key, value in payload.items() if value is not None}


def _prune_policy_denied(code: str) -> dict[str, Any]:
    return {
        "schema_version": SYNC_INBOX_PRUNE_SCHEMA_VERSION,
        "status": "policy_denied",
        "write_performed": False,
        "error": {"code": code},
    }


def _public_bundle_plan(record: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    return {
        **_public_bundle_record(record),
        "cache_status": plan.get("_cache_status") or "none",
        "prepare_duration_ms": float(plan.get("_prepare_duration_ms") or 0),
        "plan_status": plan.get("status"),
        "changeset_id": plan.get("changeset_id"),
        "source_device_id": plan.get("source_device_id"),
        "target_device_id": plan.get("target_device_id"),
        "insert_count": int(plan.get("insert_count") or 0),
        "update_count": int(plan.get("update_count") or 0),
        "idempotent_count": int(plan.get("idempotent_count") or 0),
        "conflict_count": int(plan.get("conflict_count") or 0),
        "object_count": len(plan.get("objects") or []),
        "error": plan.get("error"),
    }


def _public_bundle_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "inbox_id": record.get("inbox_id"),
        "artifact_id": record.get("artifact_id"),
        "peer_id": record.get("peer_id"),
        "transport_type": (record.get("transport") or {}).get("transport_type")
        if isinstance(record.get("transport"), dict)
        else None,
        "size_bytes": record.get("size_bytes"),
        "received_at": record.get("received_at"),
    }


def _empty_totals() -> dict[str, int]:
    return {
        "insert_count": 0,
        "update_count": 0,
        "idempotent_count": 0,
        "conflict_count": 0,
        "applied_count": 0,
    }


def _add_plan_totals(totals: dict[str, int], plan: dict[str, Any]) -> None:
    if plan.get("status") != "ready":
        return
    for key in totals:
        totals[key] += int(plan.get(key) or 0)


def _add_outcome_totals(totals: dict[str, int], outcome: dict[str, Any]) -> None:
    for key in totals:
        totals[key] += int(outcome.get(key) or 0)


def _policy_denied(code: str) -> dict[str, Any]:
    return {
        "schema_version": SYNC_INBOX_APPLY_SCHEMA_VERSION,
        "status": "policy_denied",
        "write_performed": False,
        "error": {"code": code},
    }


def _plan_cache(runtime: Any) -> dict[tuple[Any, ...], dict[str, Any]]:
    cache = getattr(runtime, "_sync_inbox_apply_plan_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        setattr(runtime, "_sync_inbox_apply_plan_cache", cache)
    return cache


def _store_cached_plan(
    cache: dict[tuple[Any, ...], dict[str, Any]],
    key: tuple[Any, ...],
    plan: dict[str, Any],
) -> None:
    cache[key] = deepcopy(plan)
    while len(cache) > PLAN_CACHE_MAX_ENTRIES:
        oldest_key = next(iter(cache))
        cache.pop(oldest_key, None)


def _plan_cache_key(runtime: Any, record: dict[str, Any]) -> tuple[Any, ...]:
    return (
        SYNC_INBOX_APPLY_SCHEMA_VERSION,
        record.get("inbox_id"),
        record.get("artifact_id"),
        record.get("size_bytes"),
        record.get("status"),
        bool(record.get("apply_performed", False)),
        record.get("updated_at"),
        _ledger_revision(runtime),
    )


def _ledger_revision(runtime: Any) -> tuple[int, str]:
    runtime.ledger.initialize()
    with runtime.ledger.connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count, COALESCE(MAX(updated_at), '') AS updated_at FROM transactions"
        ).fetchone()
    return int(row["count"] or 0), str(row["updated_at"] or "")


def _normalize_limit(value: int | None) -> int | None:
    if value is None:
        return 50
    try:
        integer = int(value)
    except (TypeError, ValueError):
        return 50
    if integer <= 0:
        return None
    return integer


def _public_limit(value: int | None) -> int | None:
    return _normalize_limit(value)


def _text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
