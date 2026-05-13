from __future__ import annotations

import json
from pathlib import Path

from core.memory_os_migration import MemoryOSMigrationKernel
from core.retrieval_backend_status import build_retrieval_backend_status


def _write_memory(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_retrieval_backend_status_reports_optional_lancedb_gate_without_writes(tmp_path):
    legacy_dir = tmp_path / "legacy"
    store_root = tmp_path / "store"
    legacy_dir.mkdir()
    _write_memory(
        legacy_dir / "alpha.json",
        {
            "key": "alpha",
            "title": "Alpha",
            "content": "# Alpha\n\nAlpha migration notes",
            "chunk_count": 1,
        },
    )
    MemoryOSMigrationKernel(store_root).import_legacy_json(legacy_dir)

    status = build_retrieval_backend_status(
        store_root=store_root,
        dependency_probe=lambda name: name == "chromadb",
    )

    assert status["schema_version"] == "2026-05-12.retrieval_backend_status.v1"
    assert status["operation"] == "retrieval_backend_status"
    assert status["write_performed"] is False
    assert status["active_memory_write_performed"] is False
    assert status["live_retrieval_changed"] is False
    assert status["current_live_backend"]["backend"] == "chroma"
    assert status["current_live_backend"]["role"] == "legacy_live_index"
    assert status["candidate_backend"]["backend"] == "lancedb"
    assert status["candidate_backend"]["required"] is False
    assert status["candidate_backend"]["promotion_ready"] is False
    assert status["candidate_backend"]["availability"]["installed"] is False
    assert status["store_probe"]["ledger_exists"] is True
    assert status["store_probe"]["vector_source_count"] == 1
    assert status["rebuild_probe"]["requested"] is False
    assert status["readiness_gates"]["lancedb_dependency"]["status"] == "blocked"
    assert status["readiness_gates"]["live_backend_switch"]["status"] == "blocked"


def test_retrieval_backend_status_can_run_deterministic_rebuild_probe(tmp_path):
    legacy_dir = tmp_path / "legacy"
    store_root = tmp_path / "store"
    legacy_dir.mkdir()
    _write_memory(
        legacy_dir / "alpha.json",
        {"key": "alpha", "title": "Alpha", "content": "Alpha content", "chunk_count": 1},
    )
    _write_memory(
        legacy_dir / "beta.json",
        {"key": "beta", "title": "Beta", "content": "Beta content", "chunk_count": 1},
    )
    MemoryOSMigrationKernel(store_root).import_legacy_json(legacy_dir)

    status = build_retrieval_backend_status(
        store_root=store_root,
        include_rebuild_probe=True,
        rebuild_batch_size=1,
        dependency_probe=lambda name: name == "chromadb",
    )

    assert status["store_probe"]["vector_source_count"] == 2
    assert status["rebuild_probe"]["requested"] is True
    assert status["rebuild_probe"]["status"] == "pass"
    assert status["rebuild_probe"]["source_count"] == 2
    assert status["rebuild_probe"]["document_count"] == 2
    assert status["rebuild_probe"]["batch_count"] == 2
    assert status["readiness_gates"]["deterministic_rebuild_probe"]["status"] == "pass"


def test_retrieval_backend_status_reports_configured_lancedb_without_switching(monkeypatch):
    monkeypatch.setenv("ENGRAM_RETRIEVAL_BACKEND", "lancedb")

    status = build_retrieval_backend_status(
        dependency_probe=lambda name: name in {"chromadb", "lancedb"},
    )

    assert status["backend_config"]["retrieval_backend"] == "lancedb"
    assert status["backend_config"]["retrieval_candidate_requested"] is True
    assert status["backend_config"]["live_switch_performed"] is False
    assert status["current_live_backend"]["backend"] == "chroma"
    assert status["candidate_backend"]["requested"] is True
    assert status["readiness_gates"]["live_backend_switch"]["status"] == "blocked"
