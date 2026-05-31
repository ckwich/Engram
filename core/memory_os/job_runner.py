"""Local job-runner facade for bounded Memory OS work."""
from __future__ import annotations

from typing import Any, Protocol

from core.memory_os.jobs import JobQueue
from core.memory_os.ledger import MemoryOSLedger


class JobRunner(Protocol):
    """Execution-lease contract for daemon-owned Memory OS workers."""

    def enqueue(
        self,
        job_kind: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
        max_attempts: int = 1,
    ) -> dict[str, Any]:
        """Queue a job and return its durable receipt."""

    def acquire(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 300,
        job_kind: str | None = None,
    ) -> dict[str, Any] | None:
        """Acquire the next queued or expired job for a worker lease."""

    def heartbeat(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_seconds: int = 300,
    ) -> dict[str, Any]:
        """Extend a running job lease."""

    def complete(
        self,
        job_id: str,
        *,
        worker_id: str,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Complete a leased job."""

    def fail(
        self,
        job_id: str,
        *,
        worker_id: str,
        error: str,
    ) -> dict[str, Any]:
        """Record a worker failure and either retry or dead-letter the job."""

    def cancel(self, job_id: str, *, reason: str) -> dict[str, Any]:
        """Cancel queued or running work."""

    def queue_health(self) -> dict[str, Any]:
        """Return queue counts and oldest queued age."""


class LocalJobRunner:
    """SQLite-backed local job runner for one daemon-owned Memory OS runtime."""

    def __init__(self, ledger: MemoryOSLedger, *, queue: JobQueue | None = None) -> None:
        self.queue = queue or JobQueue(ledger)

    def enqueue(
        self,
        job_kind: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str | None = None,
        max_attempts: int = 1,
        now: str | None = None,
    ) -> dict[str, Any]:
        return self.queue.enqueue(
            job_kind,
            payload,
            idempotency_key=idempotency_key,
            max_attempts=max_attempts,
            now=now,
        )

    def acquire(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 300,
        job_kind: str | None = None,
        now: str | None = None,
    ) -> dict[str, Any] | None:
        return self.queue.acquire_next(
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            job_kind=job_kind,
            now=now,
        )

    def heartbeat(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_seconds: int = 300,
        now: str | None = None,
    ) -> dict[str, Any]:
        return self.queue.heartbeat(
            job_id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            now=now,
        )

    def complete(
        self,
        job_id: str,
        *,
        worker_id: str,
        result: dict[str, Any] | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        return self.queue.complete(job_id, worker_id=worker_id, result=result, now=now)

    def fail(
        self,
        job_id: str,
        *,
        worker_id: str,
        error: str,
        now: str | None = None,
    ) -> dict[str, Any]:
        return self.queue.record_worker_failure(job_id, worker_id=worker_id, error=error, now=now)

    def cancel(self, job_id: str, *, reason: str, now: str | None = None) -> dict[str, Any]:
        return self.queue.request_cancel(job_id, reason=reason, now=now)

    def queue_health(self, *, now: str | None = None) -> dict[str, Any]:
        return self.queue.queue_health(now=now)
