from datetime import datetime, timedelta, timezone
import threading

from core.memory_os.job_runner import LocalJobRunner
from core.memory_os.jobs import JobQueue
from core.memory_os.ledger import MemoryOSLedger


def _now(offset_seconds: int = 0) -> str:
    return (datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc) + timedelta(seconds=offset_seconds)).isoformat()


def test_job_runner_enqueue_is_idempotent_for_same_key(tmp_path):
    runner = LocalJobRunner(MemoryOSLedger(tmp_path / "engram.sqlite"))

    first = runner.enqueue(
        "document_ingestion_window",
        {"document_id": "doc_design", "window": 1},
        idempotency_key="doc_design:window:1",
    )
    replay = runner.enqueue(
        "document_ingestion_window",
        {"document_id": "doc_design", "window": 1},
        idempotency_key="doc_design:window:1",
    )

    assert replay["job_id"] == first["job_id"]
    assert replay["status"] == "queued"


def test_job_runner_acquire_heartbeat_complete_lifecycle(tmp_path):
    runner = LocalJobRunner(MemoryOSLedger(tmp_path / "engram.sqlite"))
    queued = runner.enqueue("document_ingestion_window", {"document_id": "doc_design"}, max_attempts=3)

    acquired = runner.acquire(worker_id="worker-a", lease_seconds=30, now=_now())
    heartbeat = runner.heartbeat(queued["job_id"], worker_id="worker-a", lease_seconds=60, now=_now(10))
    completed = runner.complete(queued["job_id"], worker_id="worker-a", result={"chunks": 12}, now=_now(20))

    assert acquired is not None
    assert acquired["job_id"] == queued["job_id"]
    assert acquired["status"] == "running"
    assert acquired["attempt"] == 1
    assert acquired["lease_owner"] == "worker-a"
    assert heartbeat["lease_expires_at"] > acquired["lease_expires_at"]
    assert completed["status"] == "completed"
    assert completed["result"] == {"chunks": 12}


def test_job_runner_acquire_is_atomic_for_two_workers(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "engram.sqlite", timeout=2.0, busy_timeout_ms=2_000)
    runner = LocalJobRunner(ledger)
    queued = runner.enqueue(
        "document_ingestion_window",
        {"document_id": "doc_design", "window": 1},
    )
    start = threading.Barrier(3)
    results: list[dict | None] = []
    errors: list[str] = []

    def acquire(worker_id: str) -> None:
        try:
            start.wait(timeout=2)
            result = LocalJobRunner(ledger).acquire(
                worker_id=worker_id,
                lease_seconds=30,
                now=_now(),
                job_kind="document_ingestion_window",
            )
            results.append(result)
        except Exception as exc:  # pragma: no cover - assertion reports the error
            errors.append(f"{worker_id}: {exc}")

    first = threading.Thread(target=acquire, args=("worker-a",))
    second = threading.Thread(target=acquire, args=("worker-b",))
    first.start()
    second.start()
    start.wait(timeout=2)
    first.join(timeout=2)
    second.join(timeout=2)

    acquired = [result for result in results if result is not None]
    final = JobQueue(ledger)._read_job(queued["job_id"])
    lease_events = [
        event
        for event in JobQueue(ledger).events(queued["job_id"])
        if event["event_type"] == "lease_acquired"
    ]
    assert errors == []
    assert len(results) == 2
    assert len(acquired) == 1
    assert acquired[0]["job_id"] == queued["job_id"]
    assert final["status"] == "running"
    assert final["lease_owner"] in {"worker-a", "worker-b"}
    assert len(lease_events) == 1


def test_job_runner_failure_retries_then_dead_letters(tmp_path):
    runner = LocalJobRunner(MemoryOSLedger(tmp_path / "engram.sqlite"))
    queued = runner.enqueue("ocr_window", {"document_id": "doc_design"}, max_attempts=2)

    first = runner.acquire(worker_id="worker-a", lease_seconds=30, now=_now())
    retry = runner.fail(first["job_id"], worker_id="worker-a", error="temporary ocr failure", now=_now(1))
    second = runner.acquire(worker_id="worker-b", lease_seconds=30, now=_now(2))
    dead = runner.fail(second["job_id"], worker_id="worker-b", error="ocr still failing", now=_now(3))

    assert queued["status"] == "queued"
    assert retry["status"] == "queued"
    assert retry["attempt"] == 1
    assert retry["last_error"] == "temporary ocr failure"
    assert second["attempt"] == 2
    assert dead["status"] == "dead_lettered"
    assert dead["dead_lettered_at"] == _now(3)
    assert dead["last_error"] == "ocr still failing"


def test_job_runner_cancels_queued_and_running_work(tmp_path):
    runner = LocalJobRunner(MemoryOSLedger(tmp_path / "engram.sqlite"))
    queued = runner.enqueue("graph_build", {"document_id": "doc_design"})
    cancelled_queued = runner.cancel(queued["job_id"], reason="operator", now=_now())
    running_source = runner.enqueue("graph_build", {"document_id": "doc_other"})
    runner.acquire(worker_id="worker-a", lease_seconds=30, now=_now(1))
    cancelled_running = runner.cancel(running_source["job_id"], reason="shutdown", now=_now(2))

    assert cancelled_queued["status"] == "cancelled"
    assert cancelled_queued["cancel_requested"] is True
    assert cancelled_running["status"] == "cancelled"
    assert cancelled_running["cancel_requested"] is True


def test_job_runner_queue_health_reports_counts_and_oldest_age(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "engram.sqlite")
    jobs = JobQueue(ledger)
    runner = LocalJobRunner(ledger)
    jobs.enqueue("document_ingestion_window", {"window": 1}, now=_now(-120))
    running = jobs.enqueue("document_ingestion_window", {"window": 2}, now=_now(-60))
    jobs.acquire_next(worker_id="worker-a", lease_seconds=30, now=_now(-30), job_kind="document_ingestion_window")
    jobs.enqueue("ocr_window", {"window": 3}, now=_now(-10), max_attempts=1)
    acquired = runner.acquire(worker_id="worker-b", lease_seconds=30, now=_now(-5), job_kind="ocr_window")
    runner.fail(acquired["job_id"], worker_id="worker-b", error="boom", now=_now())

    health = runner.queue_health(now=_now())

    assert running["status"] == "queued"
    assert health["queued_count"] == 1
    assert health["running_count"] == 1
    assert health["dead_lettered_count"] == 1
    assert health["oldest_queued_age_seconds"] == 60
