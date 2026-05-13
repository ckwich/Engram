"""Durable job queue receipts for daemon-owned Memory OS work."""
from __future__ import annotations

from typing import Any

from core.memory_os._records import list_records, now_iso, stable_id, upsert_record
from core.memory_os.ledger import MemoryOSLedger


class JobQueue:
    """Record simple job state transitions and events in SQLite."""

    def __init__(self, ledger: MemoryOSLedger) -> None:
        self.ledger = ledger

    def enqueue(self, job_kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        job = {
            "job_id": stable_id("job", {"job_kind": job_kind, "payload": payload, "created_at": now_iso()}),
            "job_kind": job_kind,
            "payload": payload,
            "status": "queued",
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        self._save_job(job)
        self._event(job["job_id"], "queued", {})
        return job

    def start(self, job_id: str) -> dict[str, Any]:
        return self._transition(job_id, "running", "running")

    def succeed(self, job_id: str, *, result: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._transition(job_id, "succeeded", "succeeded", {"result": result or {}})

    def fail(self, job_id: str, *, error: str) -> dict[str, Any]:
        return self._transition(job_id, "failed", "failed", {"error": error})

    def cancel(self, job_id: str, *, reason: str) -> dict[str, Any]:
        return self._transition(job_id, "canceled", "canceled", {"reason": reason})

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
        job["status"] = status
        job["updated_at"] = now_iso()
        if updates:
            job.update(updates)
        self._save_job(job)
        self._event(job_id, event_type, updates or {})
        return job

    def _read_job(self, job_id: str) -> dict[str, Any]:
        for job in list_records(self.ledger, "jobs"):
            if job.get("job_id") == job_id:
                return job
        raise KeyError(f"job not found: {job_id}")

    def _save_job(self, job: dict[str, Any]) -> None:
        upsert_record(self.ledger, "jobs", job["job_id"], job)

    def _event(self, job_id: str, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "event_id": stable_id(
                "job_event",
                {
                    "job_id": job_id,
                    "event_type": event_type,
                    "payload": payload,
                    "created_at": now_iso(),
                },
            ),
            "job_id": job_id,
            "event_type": event_type,
            "payload": payload,
            "created_at": now_iso(),
        }
        upsert_record(self.ledger, "job_events", event["event_id"], event)
