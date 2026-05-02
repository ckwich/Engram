from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent
OPERATIONS_DIR = PROJECT_ROOT / "data" / "operations"
JOBS_PATH = OPERATIONS_DIR / "jobs.jsonl"
EVENTS_PATH = OPERATIONS_DIR / "events.jsonl"

SENSITIVE_KEYS = {"body", "content", "raw", "source_text", "text"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _strip_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                cleaned[key] = {"redacted": True}
            else:
                cleaned[key] = _strip_sensitive(item)
        return cleaned
    if isinstance(value, list):
        return [_strip_sensitive(item) for item in value]
    return value


class OperationLog:
    def record_job(
        self,
        *,
        operation_type: str,
        status: str,
        result: Any | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        job = {
            "job_id": _sha256(f"job:{operation_type}:{time.time_ns()}"),
            "timestamp": _now(),
            "operation_type": operation_type,
            "status": status,
            "result": _strip_sensitive(result or {}),
            "error": error,
            "metadata": _strip_sensitive(metadata or {}),
        }
        self._append(JOBS_PATH, job)
        return job

    def list_jobs(
        self,
        *,
        operation_type: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        jobs = self._read(JOBS_PATH)
        if operation_type:
            jobs = [job for job in jobs if job.get("operation_type") == operation_type]
        if status:
            jobs = [job for job in jobs if job.get("status") == status]
        jobs = jobs[-limit:]
        return {"count": len(jobs), "jobs": list(reversed(jobs)), "error": None}

    def record_event(
        self,
        *,
        event_type: str,
        subject: dict[str, Any],
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "event_id": _sha256(f"event:{event_type}:{time.time_ns()}"),
            "timestamp": _now(),
            "event_type": event_type,
            "subject": _strip_sensitive(subject),
            "summary": str(summary),
            "metadata": _strip_sensitive(metadata or {}),
        }
        self._append(EVENTS_PATH, event)
        return event

    def list_events(self, *, event_type: str | None = None, limit: int = 50) -> dict[str, Any]:
        events = self._read(EVENTS_PATH)
        if event_type:
            events = [event for event in events if event.get("event_type") == event_type]
        events = events[-limit:]
        return {"count": len(events), "events": list(reversed(events)), "error": None}

    def _append(self, path: Path, record: dict[str, Any]) -> None:
        OPERATIONS_DIR.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _read(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
        return records


operation_log = OperationLog()
