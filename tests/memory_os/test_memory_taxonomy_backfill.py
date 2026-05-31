from core.memory_os._records import read_record, upsert_record
from core.memory_os.memory_taxonomy_backfill import repair_memory_taxonomy_metadata
from core.memory_os.runtime import MemoryOSRuntime


def _runtime(tmp_path):
    runtime = MemoryOSRuntime(tmp_path / "memory_os", embed_text=lambda text: [0.1, 0.2])
    runtime.initialize(rebuild_retrieval=False)
    return runtime


def test_taxonomy_backfill_dry_run_does_not_write(tmp_path):
    runtime = _runtime(tmp_path)
    upsert_record(
        runtime.ledger,
        "memories",
        "memory:one",
        {"key": "one", "content": "A decision.", "tags": ["decision"]},
    )

    result = repair_memory_taxonomy_metadata(runtime.ledger, accept=False, approved_by="tester")
    stored = read_record(runtime.ledger, "memories", "memory:one")

    assert result["write_performed"] is False
    assert result["candidate_count"] == 1
    assert "memory_type" not in stored


def test_taxonomy_backfill_requires_accept_and_approved_by(tmp_path):
    runtime = _runtime(tmp_path)
    upsert_record(
        runtime.ledger,
        "memories",
        "memory:one",
        {"key": "one", "content": "A decision.", "tags": ["decision"]},
    )

    result = repair_memory_taxonomy_metadata(runtime.ledger, accept=True, approved_by="")

    assert result["status"] == "policy_denied"
    assert result["write_performed"] is False


def test_taxonomy_backfill_updates_existing_memory_rows(tmp_path):
    runtime = _runtime(tmp_path)
    upsert_record(
        runtime.ledger,
        "memories",
        "memory:one",
        {"key": "one", "content": "A decision.", "tags": ["decision"]},
    )

    result = repair_memory_taxonomy_metadata(runtime.ledger, accept=True, approved_by="tester")
    stored = read_record(runtime.ledger, "memories", "memory:one")

    assert result["write_performed"] is True
    assert result["updated_count"] == 1
    assert stored["memory_type"] == "decision"
    assert stored["scope"] == "project"
    assert stored["trust_state"] == "reviewed"
    assert stored["retention_policy"] == "standard"
    assert stored["sync_policy"] == "sync"
    assert stored["taxonomy_backfilled_by"] == "tester"
