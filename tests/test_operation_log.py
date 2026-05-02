from __future__ import annotations

from pathlib import Path


def test_operation_paths_are_project_relative():
    import core.operation_log as operation_log_module

    project_root = Path(operation_log_module.__file__).resolve().parents[1]

    assert operation_log_module.OPERATIONS_DIR == project_root / "data" / "operations"
    assert operation_log_module.JOBS_PATH == operation_log_module.OPERATIONS_DIR / "jobs.jsonl"
    assert operation_log_module.EVENTS_PATH == operation_log_module.OPERATIONS_DIR / "events.jsonl"


def test_record_job_receipt_round_trips(isolated_operation_log):
    log = isolated_operation_log.operation_log

    job = log.record_job(
        operation_type="source_intake",
        status="completed",
        result={"draft_id": "sha256:abc"},
        error=None,
    )

    assert job["job_id"].startswith("sha256:")
    assert job["status"] == "completed"
    assert log.list_jobs()["jobs"][0]["job_id"] == job["job_id"]


def test_record_event_is_compact_and_queryable(isolated_operation_log):
    log = isolated_operation_log.operation_log

    event = log.record_event(
        event_type="source_draft_ready",
        subject={"kind": "source_draft", "draft_id": "sha256:abc"},
        summary="Source draft ready for review.",
    )

    events = log.list_events(event_type="source_draft_ready")

    assert event["event_id"].startswith("sha256:")
    assert events["count"] == 1
    assert events["events"][0]["summary"] == "Source draft ready for review."
