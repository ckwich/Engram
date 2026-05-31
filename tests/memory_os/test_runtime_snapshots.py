from __future__ import annotations

import json

import pytest

from core.memory_os.content_store import ContentAddressedStore
from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.runtime_snapshots import (
    RuntimeSnapshotError,
    create_verified_runtime_snapshot,
    verify_runtime_snapshot,
)


def test_runtime_snapshot_copies_restore_grade_ledger_and_objects(tmp_path):
    root = tmp_path / "memory_os"
    ledger = MemoryOSLedger(root / "ledger.sqlite3")
    ledger.initialize()
    artifact_id = ContentAddressedStore(root / "objects").put_bytes(b"durable payload", suffix=".md")
    (root / "lance").mkdir()
    (root / "lance" / "index.bin").write_bytes(b"rebuildable")

    snapshot = create_verified_runtime_snapshot(
        root,
        snapshot_parent=tmp_path / "snapshots",
        created_by="test",
    )

    snapshot_path = tmp_path / "snapshots" / snapshot["snapshot_id"]
    manifest = json.loads((snapshot_path / "SNAPSHOT_MANIFEST.json").read_text(encoding="utf-8"))
    copied_artifact = ContentAddressedStore(snapshot_path / "objects").read_bytes(artifact_id)

    assert snapshot["restore_grade"] is True
    assert snapshot["ledger"]["quick_check"] == "ok"
    assert (snapshot_path / "ledger.sqlite3").exists()
    assert copied_artifact == b"durable payload"
    assert not (snapshot_path / "lance").exists()
    assert manifest["rebuildable_indexes_excluded"] == ["lance", "kuzu", "chroma"]
    assert verify_runtime_snapshot(snapshot_path)["status"] == "ok"


def test_runtime_snapshot_rejects_malformed_ledger(tmp_path):
    root = tmp_path / "memory_os"
    root.mkdir(parents=True)
    (root / "ledger.sqlite3").write_text("not sqlite", encoding="utf-8")

    with pytest.raises(RuntimeSnapshotError, match="malformed ledger"):
        create_verified_runtime_snapshot(root, snapshot_parent=tmp_path / "snapshots", created_by="test")
