import hashlib

import pytest

from core.memory_os._records import read_record
from core.memory_os.content_store import ContentAddressedStore
from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.storage_adapters import LocalArtifactStore, LocalRecordLedger


def test_local_record_ledger_preserves_existing_record_helper_semantics(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
    adapter = LocalRecordLedger(ledger)
    payload = {
        "key": "runtime-seam",
        "title": "Runtime seam",
        "status": "active",
        "tags": ["adapter"],
    }

    receipt = adapter.upsert_record("memories", "runtime-seam", payload)

    assert receipt.table == "memories"
    assert receipt.record_id == "runtime-seam"
    assert adapter.read_record("memories", "runtime-seam") == payload
    assert read_record(ledger, "memories", "runtime-seam") == payload


def test_local_record_ledger_lists_filters_and_deletes_records(tmp_path):
    adapter = LocalRecordLedger(tmp_path / "ledger.sqlite3")
    adapter.upsert_record("memories", "a", {"key": "a", "project": "Engram"})
    adapter.upsert_record("memories", "b", {"key": "b", "project": "Other"})
    adapter.upsert_record("memories", "c", {"key": "c", "project": "Engram"})

    records = adapter.list_records("memories", filters={"project": "Engram"}, limit=1)
    delete_receipt = adapter.delete_record("memories", "a")

    assert records == [{"key": "a", "project": "Engram"}]
    assert delete_receipt.deleted is True
    assert adapter.read_record("memories", "a") is None


def test_local_record_ledger_rejects_unknown_tables(tmp_path):
    adapter = LocalRecordLedger(tmp_path / "ledger.sqlite3")

    with pytest.raises(ValueError, match="unknown Memory OS table"):
        adapter.upsert_record("not_a_table", "x", {})


def test_local_artifact_store_preserves_content_addressed_store_shape(tmp_path):
    root = tmp_path / "objects"
    adapter = LocalArtifactStore(root)
    data = b"adapter evidence"

    artifact_id = adapter.put_bytes(data, suffix=".bin")
    descriptor = adapter.verify(artifact_id)

    assert artifact_id == f"sha256:{hashlib.sha256(data).hexdigest()}.bin"
    assert adapter.read_bytes(artifact_id) == data
    assert ContentAddressedStore(root).read_bytes(artifact_id) == data
    assert descriptor.artifact_id == artifact_id
    assert descriptor.digest == f"sha256:{hashlib.sha256(data).hexdigest()}"
    assert descriptor.size_bytes == len(data)
    assert descriptor.local_path == adapter.path_for(artifact_id)


def test_local_artifact_store_write_bytes_returns_descriptor(tmp_path):
    adapter = LocalArtifactStore(tmp_path / "objects")

    descriptor = adapter.write_bytes(b"review packet", suffix=".json")

    assert descriptor.artifact_id.endswith(".json")
    assert descriptor.local_path is not None
    assert descriptor.local_path.exists()
