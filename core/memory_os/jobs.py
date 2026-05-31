"""Durable job queue receipts for daemon-owned Memory OS work."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from core.memory_os._records import list_records, now_iso, read_record, stable_id, upsert_record
from core.memory_os.ledger import MemoryOSLedger


class JobQueue:
    """Record simple job state transitions and events in SQLite."""

    def __init__(self, ledger: MemoryOSLedger) -> None:
        self.ledger = ledger

    def enqueue(
        self,
        job_kind: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
        max_attempts: int = 1,
        now: str | None = None,
    ) -> dict[str, Any]:
        normalized_now = now or now_iso()
        normalized_idempotency_key = _optional_text(idempotency_key)
        if normalized_idempotency_key:
            job_id = stable_id("job", {"job_kind": job_kind, "idempotency_key": normalized_idempotency_key})
            existing = read_record(self.ledger, "jobs", job_id)
            if isinstance(existing, dict):
                return existing
        else:
            job_id = stable_id("job", {"job_kind": job_kind, "payload": payload, "created_at": normalized_now})
        job = {
            "job_id": job_id,
            "job_kind": job_kind,
            "payload": payload,
            "status": "queued",
            "attempt": 0,
            "max_attempts": max(int(max_attempts), 1),
            "lease_owner": None,
            "lease_expires_at": None,
            "heartbeat_at": None,
            "cancel_requested": False,
            "dead_lettered_at": None,
            "idempotency_key": normalized_idempotency_key,
            "created_at": normalized_now,
            "updated_at": normalized_now,
        }
        self._save_job(job)
        self._event(job["job_id"], "queued", {}, now=normalized_now)
        return job

    def start(self, job_id: str) -> dict[str, Any]:
        return self._transition(job_id, "running", "running")

    def succeed(self, job_id: str, *, result: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._transition(job_id, "succeeded", "succeeded", {"result": result or {}})

    def fail(self, job_id: str, *, error: str) -> dict[str, Any]:
        return self._transition(job_id, "failed", "failed", {"error": error})

    def cancel(self, job_id: str, *, reason: str) -> dict[str, Any]:
        return self._transition(job_id, "canceled", "canceled", {"reason": reason})

    def acquire_next(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        job_kind: str | None = None,
        now: str | None = None,
    ) -> dict[str, Any] | None:
        normalized_worker = _required_text(worker_id, "worker_id")
        normalized_now = now or now_iso()
        lease_expires_at = _add_seconds(normalized_now, max(int(lease_seconds), 1))
        self.ledger.initialize()
        with self.ledger.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT id, payload_json FROM jobs ORDER BY created_at, id"
            ).fetchall()
            for row in rows:
                job = _decode_payload(row["payload_json"])
                if not job:
                    continue
                if job_kind and job.get("job_kind") != job_kind:
                    continue
                if job.get("cancel_requested") is True:
                    continue
                if not _is_acquirable(job, normalized_now):
                    continue
                updated = {
                    **job,
                    "status": "running",
                    "attempt": int(job.get("attempt") or 0) + 1,
                    "lease_owner": normalized_worker,
                    "lease_expires_at": lease_expires_at,
                    "heartbeat_at": normalized_now,
                    "updated_at": normalized_now,
                }
                encoded = _encode_payload(updated)
                changed = conn.execute(
                    """
                    UPDATE jobs
                    SET payload_json = ?, updated_at = ?
                    WHERE id = ? AND payload_json = ?
                    """,
                    (encoded, normalized_now, row["id"], row["payload_json"]),
                ).rowcount
                if changed != 1:
                    continue
                _write_event(
                    conn,
                    _event_record(
                        updated["job_id"],
                        "lease_acquired",
                        {
                            "worker_id": normalized_worker,
                            "lease_expires_at": lease_expires_at,
                            "attempt": updated["attempt"],
                        },
                        now=normalized_now,
                    ),
                )
                conn.commit()
                return updated
            conn.commit()
        return None

    def heartbeat(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_seconds: int,
        now: str | None = None,
    ) -> dict[str, Any]:
        job = self._read_job(job_id)
        normalized_worker = _required_text(worker_id, "worker_id")
        _require_lease_owner(job, normalized_worker)
        normalized_now = now or now_iso()
        updated = {
            **job,
            "heartbeat_at": normalized_now,
            "lease_expires_at": _add_seconds(normalized_now, max(int(lease_seconds), 1)),
            "updated_at": normalized_now,
        }
        self._save_job(updated)
        self._event(
            job_id,
            "heartbeat",
            {"worker_id": normalized_worker, "lease_expires_at": updated["lease_expires_at"]},
            now=normalized_now,
        )
        return updated

    def complete(
        self,
        job_id: str,
        *,
        worker_id: str | None = None,
        result: dict[str, Any] | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        job = self._read_job(job_id)
        normalized_worker = _optional_text(worker_id)
        if normalized_worker:
            _require_lease_owner(job, normalized_worker)
        normalized_now = now or now_iso()
        updated = {
            **job,
            "status": "completed",
            "result": result or {},
            "lease_owner": None,
            "lease_expires_at": None,
            "heartbeat_at": job.get("heartbeat_at"),
            "updated_at": normalized_now,
        }
        self._save_job(updated)
        self._event(job_id, "completed", {"worker_id": normalized_worker, "result": result or {}}, now=normalized_now)
        return updated

    def record_worker_failure(
        self,
        job_id: str,
        *,
        worker_id: str | None = None,
        error: str,
        now: str | None = None,
    ) -> dict[str, Any]:
        job = self._read_job(job_id)
        normalized_worker = _optional_text(worker_id)
        if normalized_worker:
            _require_lease_owner(job, normalized_worker)
        normalized_now = now or now_iso()
        attempt = int(job.get("attempt") or 0)
        max_attempts = max(int(job.get("max_attempts") or 1), 1)
        terminal = attempt >= max_attempts
        updated = {
            **job,
            "status": "dead_lettered" if terminal else "queued",
            "last_error": error,
            "lease_owner": None,
            "lease_expires_at": None,
            "heartbeat_at": job.get("heartbeat_at"),
            "dead_lettered_at": normalized_now if terminal else None,
            "updated_at": normalized_now,
        }
        self._save_job(updated)
        self._event(
            job_id,
            "dead_lettered" if terminal else "retry_scheduled",
            {"worker_id": normalized_worker, "error": error, "attempt": attempt, "max_attempts": max_attempts},
            now=normalized_now,
        )
        return updated

    def request_cancel(
        self,
        job_id: str,
        *,
        reason: str,
        now: str | None = None,
    ) -> dict[str, Any]:
        normalized_now = now or now_iso()
        job = self._read_job(job_id)
        updated = {
            **job,
            "status": "cancelled",
            "cancel_requested": True,
            "reason": reason,
            "lease_owner": None,
            "lease_expires_at": None,
            "updated_at": normalized_now,
        }
        self._save_job(updated)
        self._event(job_id, "cancelled", {"reason": reason}, now=normalized_now)
        return updated

    def queue_health(self, *, now: str | None = None) -> dict[str, Any]:
        normalized_now = now or now_iso()
        records = list_records(self.ledger, "jobs")
        queued = [job for job in records if job.get("status") == "queued"]
        running = [job for job in records if job.get("status") == "running"]
        dead_lettered = [job for job in records if job.get("status") == "dead_lettered"]
        cancelled = [job for job in records if job.get("status") in {"cancelled", "canceled"}]
        oldest_queued = min((_age_seconds(job.get("created_at"), normalized_now) for job in queued), default=None)
        return {
            "status": "ready",
            "job_count": len(records),
            "queued_count": len(queued),
            "running_count": len(running),
            "dead_lettered_count": len(dead_lettered),
            "cancelled_count": len(cancelled),
            "oldest_queued_age_seconds": oldest_queued,
        }

    def events(self, job_id: str) -> list[dict[str, Any]]:
        return [event for event in list_records(self.ledger, "job_events") if event.get("job_id") == job_id]

    def _transition(
        self,
        job_id: str,
        status: str,
        event_type: str,
        updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        job = self._read_job(job_id)
        timestamp = now_iso()
        job["status"] = status
        job["updated_at"] = timestamp
        if updates:
            job.update(updates)
        self._save_job(job)
        self._event(job_id, event_type, updates or {}, now=timestamp)
        return job

    def _read_job(self, job_id: str) -> dict[str, Any]:
        for job in list_records(self.ledger, "jobs"):
            if job.get("job_id") == job_id:
                return job
        raise KeyError(f"job not found: {job_id}")

    def _save_job(self, job: dict[str, Any]) -> None:
        upsert_record(self.ledger, "jobs", job["job_id"], job)

    def _event(self, job_id: str, event_type: str, payload: dict[str, Any], *, now: str | None = None) -> None:
        event = _event_record(job_id, event_type, payload, now=now)
        upsert_record(self.ledger, "job_events", event["event_id"], event)


def _encode_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _decode_payload(raw: Any) -> dict[str, Any] | None:
    try:
        decoded = json.loads(str(raw))
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, dict) else None


def _event_record(job_id: str, event_type: str, payload: dict[str, Any], *, now: str | None = None) -> dict[str, Any]:
    timestamp = now or now_iso()
    return {
        "event_id": stable_id(
            "job_event",
            {
                "job_id": job_id,
                "event_type": event_type,
                "payload": payload,
                "created_at": timestamp,
            },
        ),
        "job_id": job_id,
        "event_type": event_type,
        "payload": payload,
        "created_at": timestamp,
    }


def _write_event(conn: Any, event: dict[str, Any]) -> None:
    timestamp = event["created_at"]
    conn.execute(
        """
        INSERT INTO job_events (id, payload_json, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            payload_json = excluded.payload_json,
            updated_at = excluded.updated_at
        """,
        (event["event_id"], _encode_payload(event), timestamp, timestamp),
    )


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _required_text(value: Any, field: str) -> str:
    text = _optional_text(value)
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _add_seconds(timestamp: str, seconds: int) -> str:
    return (_parse_timestamp(timestamp) + timedelta(seconds=seconds)).isoformat()


def _is_acquirable(job: dict[str, Any], now: str) -> bool:
    status = job.get("status")
    if status == "queued":
        return True
    if status != "running":
        return False
    lease_expires_at = job.get("lease_expires_at")
    if not lease_expires_at:
        return True
    return _parse_timestamp(lease_expires_at) <= _parse_timestamp(now)


def _require_lease_owner(job: dict[str, Any], worker_id: str) -> None:
    owner = job.get("lease_owner")
    if owner and owner != worker_id:
        raise PermissionError(f"job lease is owned by {owner}")


def _age_seconds(start: Any, end: str) -> int | None:
    if not start:
        return None
    return max(int((_parse_timestamp(end) - _parse_timestamp(start)).total_seconds()), 0)
