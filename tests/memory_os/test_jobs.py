from core.memory_os.jobs import JobQueue
from core.memory_os.ledger import MemoryOSLedger


def test_jobs_move_through_states_with_durable_events(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "engram.sqlite")
    jobs = JobQueue(ledger)

    queued = jobs.enqueue("document_import", {"source": "book.pdf"})
    running = jobs.start(queued["job_id"])
    succeeded = jobs.succeed(queued["job_id"], result={"documents": 1})

    assert queued["status"] == "queued"
    assert running["status"] == "running"
    assert succeeded["status"] == "succeeded"
    assert [event["event_type"] for event in jobs.events(queued["job_id"])] == [
        "queued",
        "running",
        "succeeded",
    ]


def test_jobs_can_fail_and_cancel(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "engram.sqlite")
    jobs = JobQueue(ledger)

    failed = jobs.fail(jobs.enqueue("ocr", {})["job_id"], error="missing extractor")
    canceled = jobs.cancel(jobs.enqueue("graph_build", {})["job_id"], reason="operator")

    assert failed["status"] == "failed"
    assert failed["error"] == "missing extractor"
    assert canceled["status"] == "canceled"
    assert canceled["reason"] == "operator"
