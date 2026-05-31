from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core.memory_os.legacy_recovery_backup import (
    prepare_legacy_recovery_backup,
    restore_legacy_recovery_backup,
    verify_legacy_recovery_backup,
    write_legacy_recovery_backup,
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_prepare_legacy_recovery_backup_reports_json_chroma_and_graph_without_writing(tmp_path):
    memory_dir = tmp_path / "data" / "memories"
    chroma_dir = tmp_path / "data" / "chroma"
    graph_dir = tmp_path / "data" / "graph"
    backup_dir = tmp_path / "backups"
    _write(
        memory_dir / "alpha.json",
        json.dumps({"key": "alpha", "content": "Alpha content"}, indent=2),
    )
    _write(chroma_dir / "index" / "segment.bin", "vector rows")
    _write(graph_dir / "edges.json", json.dumps([{"edge_id": "edge-alpha"}]))

    report = prepare_legacy_recovery_backup(
        memory_dir=memory_dir,
        chroma_dir=chroma_dir,
        graph_dir=graph_dir,
        backup_dir=backup_dir,
    )

    assert report["schema_version"] == "2026-05-15.legacy_recovery_backup.v1"
    assert report["status"] == "ready"
    assert report["write_policy"] == "no_write"
    assert report["write_performed"] is False
    assert report["archive_path"] is None
    assert report["manifest_path"] is None
    assert report["file_count"] == 3
    assert report["total_bytes"] > 0
    assert report["stores"]["memories"]["file_count"] == 1
    assert report["stores"]["memories"]["json_file_count"] == 1
    assert report["stores"]["chroma"]["file_count"] == 1
    assert report["stores"]["graph"]["file_count"] == 1
    assert report["missing_required_stores"] == []
    assert not backup_dir.exists()


def test_write_verify_and_restore_legacy_recovery_backup(tmp_path):
    memory_dir = tmp_path / "data" / "memories"
    chroma_dir = tmp_path / "data" / "chroma"
    graph_dir = tmp_path / "data" / "graph"
    backup_dir = tmp_path / "data" / "backups" / "legacy_recovery"
    restore_root = tmp_path / "restored"
    _write(
        memory_dir / "alpha.json",
        json.dumps({"key": "alpha", "content": "Alpha content"}, indent=2),
    )
    _write(chroma_dir / "chroma.sqlite3", "sqlite bytes")
    _write(chroma_dir / "vectors" / "segment.bin", "vector rows")
    _write(graph_dir / "edges.json", json.dumps([{"edge_id": "edge-alpha"}]))

    denied = write_legacy_recovery_backup(
        memory_dir=memory_dir,
        chroma_dir=chroma_dir,
        graph_dir=graph_dir,
        backup_dir=backup_dir,
    )
    assert denied["status"] == "denied"
    assert denied["write_performed"] is False
    assert not backup_dir.exists()

    created = write_legacy_recovery_backup(
        memory_dir=memory_dir,
        chroma_dir=chroma_dir,
        graph_dir=graph_dir,
        backup_dir=backup_dir,
        accept=True,
        approved_by="pytest",
    )

    assert created["status"] == "written"
    assert created["write_performed"] is True
    assert created["active_memory_write_performed"] is False
    assert created["graph_write_performed"] is False
    assert created["archive_path"].endswith(".tar")
    assert created["manifest_path"].endswith(".manifest.json")
    assert created["file_count"] == 4
    archive_path = Path(created["archive_path"])
    manifest_path = Path(created["manifest_path"])
    assert archive_path.exists()
    assert manifest_path.exists()

    verified = verify_legacy_recovery_backup(archive_path, manifest_path=manifest_path)
    assert verified["status"] == "verified"
    assert verified["file_count"] == 4
    assert verified["missing_entries"] == []
    assert verified["mismatched_entries"] == []

    restored = restore_legacy_recovery_backup(
        archive_path,
        restore_root=restore_root,
        accept=True,
        approved_by="pytest",
    )

    assert restored["status"] == "restored"
    assert restored["write_performed"] is True
    assert restored["restored_file_count"] == 4
    assert (restore_root / "memories" / "alpha.json").read_text(encoding="utf-8")
    assert (restore_root / "chroma" / "chroma.sqlite3").read_text(encoding="utf-8")
    assert (restore_root / "chroma" / "vectors" / "segment.bin").read_text(
        encoding="utf-8"
    )
    assert (restore_root / "graph" / "edges.json").read_text(encoding="utf-8")


def test_legacy_recovery_backup_blocks_missing_required_store(tmp_path):
    memory_dir = tmp_path / "data" / "memories"
    chroma_dir = tmp_path / "data" / "chroma"
    _write(memory_dir / "alpha.json", json.dumps({"key": "alpha"}))

    report = prepare_legacy_recovery_backup(
        memory_dir=memory_dir,
        chroma_dir=chroma_dir,
    )

    assert report["status"] == "blocked"
    assert report["missing_required_stores"] == ["chroma"]
    assert report["write_performed"] is False


def test_legacy_recovery_backup_skips_symlinked_files(tmp_path):
    memory_dir = tmp_path / "data" / "memories"
    chroma_dir = tmp_path / "data" / "chroma"
    private = tmp_path / "private.txt"
    private.write_text("outside backup root", encoding="utf-8")
    _write(memory_dir / "alpha.json", json.dumps({"key": "alpha"}))
    _write(chroma_dir / "chroma.sqlite3", "sqlite bytes")
    link = memory_dir / "outside.json"
    try:
        os.symlink(private, link)
    except OSError:
        pytest.skip("symlink creation is not available in this environment")

    report = prepare_legacy_recovery_backup(
        memory_dir=memory_dir,
        chroma_dir=chroma_dir,
    )

    archive_paths = {entry["archive_path"] for entry in report["manifest"]["files"]}
    assert "memories/alpha.json" in archive_paths
    assert "memories/outside.json" not in archive_paths
