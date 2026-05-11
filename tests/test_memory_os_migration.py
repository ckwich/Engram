from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from core.memory_os_migration import MemoryOSMigrationKernel, legacy_json_filename


def _write_memory(path: Path, payload: dict) -> dict:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def test_legacy_import_dry_run_reports_counts_without_writing_store(tmp_path):
    legacy_dir = tmp_path / "legacy"
    store_root = tmp_path / "store"
    legacy_dir.mkdir()

    _write_memory(
        legacy_dir / "alpha.json",
        {
            "key": "alpha",
            "title": "Alpha",
            "content": "Alpha content",
            "tags": ["one"],
            "related_to": ["beta"],
            "project": "Engram",
            "domain": "migration",
            "status": "active",
            "canonical": True,
            "created_at": "2026-05-01T00:00:00+00:00",
            "updated_at": "2026-05-02T00:00:00+00:00",
            "chars": 13,
            "lines": 1,
            "chunk_count": 2,
            "legacy_note": "preserve me in the artifact",
        },
    )
    _write_memory(
        legacy_dir / "beta.json",
        {
            "key": "beta",
            "title": "Beta",
            "content": "Beta content",
            "tags": "two,three",
            "related_to": "alpha",
            "chunk_count": 1,
        },
    )
    (legacy_dir / "broken.json").write_text("{not-json", encoding="utf-8")

    report = MemoryOSMigrationKernel(store_root).import_legacy_json(legacy_dir, dry_run=True)

    assert report["dry_run"] is True
    assert report["source_count"] == 3
    assert report["valid_count"] == 2
    assert report["invalid_count"] == 1
    assert report["would_import_count"] == 2
    assert report["imported_count"] == 0
    assert report["key_set"] == ["alpha", "beta"]
    assert report["chunk_count_total"] == 3
    assert report["related_to_count"] == 2
    assert report["unsupported_fields"] == {"alpha": ["legacy_note"]}
    assert report["field_mappings"]["related_to"] == "memories.related_to_json"
    assert not (store_root / "ledger.sqlite3").exists()
    assert not (store_root / "objects").exists()


def test_legacy_import_exports_bundle_and_restores_legacy_json_artifacts(tmp_path):
    legacy_dir = tmp_path / "legacy"
    store_root = tmp_path / "store"
    restore_root = tmp_path / "restored"
    restored_json_dir = tmp_path / "legacy_restored"
    legacy_dir.mkdir()

    alpha = _write_memory(
        legacy_dir / "alpha.json",
        {
            "key": "alpha",
            "title": "Alpha",
            "content": "# Alpha\n\nAlpha content",
            "tags": ["one", "two"],
            "related_to": ["beta"],
            "project": "Engram",
            "domain": "migration",
            "status": "active",
            "canonical": True,
            "created_at": "2026-05-01T00:00:00+00:00",
            "updated_at": "2026-05-02T00:00:00+00:00",
            "chars": 22,
            "lines": 3,
            "chunk_count": 4,
            "legacy_note": "artifact-only field",
        },
    )
    beta = _write_memory(
        legacy_dir / "beta.json",
        {
            "key": "beta",
            "title": "Beta",
            "content": "Beta content",
            "tags": ["three"],
            "related_to": [],
            "chunk_count": 1,
        },
    )

    kernel = MemoryOSMigrationKernel(store_root)
    import_report = kernel.import_legacy_json(legacy_dir)

    assert import_report["dry_run"] is False
    assert import_report["imported_count"] == 2
    assert import_report["key_set"] == ["alpha", "beta"]
    assert (store_root / "ledger.sqlite3").exists()
    assert (store_root / "objects").exists()
    assert kernel.read_memory_record("alpha")["related_to"] == ["beta"]
    assert kernel.read_memory_record("alpha")["chunk_count"] == 4

    bundle = kernel.export_bundle()
    restored = MemoryOSMigrationKernel(restore_root)
    restore_report = restored.restore_bundle(bundle)

    assert restore_report["restored_count"] == 2
    assert restored.key_set() == ["alpha", "beta"]
    assert restored.read_memory_record("alpha")["tags"] == ["one", "two"]
    assert restored.read_memory_record("alpha")["related_to"] == ["beta"]
    assert restored.read_memory_record("alpha")["canonical"] is True
    assert restored.read_memory_record("beta")["tags"] == ["three"]

    legacy_report = restored.restore_legacy_json(restored_json_dir)

    assert legacy_report["restored_count"] == 2
    assert json.loads((restored_json_dir / legacy_json_filename("alpha")).read_text(encoding="utf-8")) == alpha
    assert json.loads((restored_json_dir / legacy_json_filename("beta")).read_text(encoding="utf-8")) == beta

    shutil.rmtree(store_root)
    shutil.rmtree(restore_root)


def test_round_trip_cli_writes_durable_parity_report(tmp_path):
    legacy_dir = tmp_path / "legacy"
    work_root = tmp_path / "migration_work"
    report_path = tmp_path / "migration_report.json"
    legacy_dir.mkdir()

    _write_memory(
        legacy_dir / "alpha.json",
        {
            "key": "alpha",
            "title": "Alpha",
            "content": "Alpha content",
            "tags": ["one"],
            "related_to": ["beta"],
            "chunk_count": 1,
        },
    )
    _write_memory(
        legacy_dir / "beta.json",
        {
            "key": "beta",
            "title": "Beta",
            "content": "Beta content",
            "tags": ["two"],
            "related_to": [],
            "chunk_count": 1,
        },
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "core.memory_os_migration",
            "round-trip",
            "--legacy-dir",
            str(legacy_dir),
            "--work-root",
            str(work_root),
            "--report",
            str(report_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    stdout_report = json.loads(result.stdout)
    assert stdout_report == report
    assert report["status"] == "pass"
    assert report["dry_run"]["valid_count"] == 2
    assert report["import"]["imported_count"] == 2
    assert report["bundle"]["memory_count"] == 2
    assert report["restore"]["restored_count"] == 2
    assert report["legacy_json_restore"]["restored_count"] == 2
    assert report["parity"]["key_sets_match"] is True
    assert (work_root / "store" / "ledger.sqlite3").exists()
    assert (work_root / "restored_store" / "ledger.sqlite3").exists()
    assert (work_root / "restored_json").is_dir()
