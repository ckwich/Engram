from __future__ import annotations

import json
from pathlib import Path

from core.memory_os_migration import MemoryOSMigrationKernel
from core.memory_os.ledger import MemoryOSLedger
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
    assert status["golden_comparison_probe"]["status"] == "skipped"
    assert status["readiness_gates"]["lancedb_dependency"]["status"] == "blocked"
    assert status["readiness_gates"]["golden_retrieval_comparison"]["status"] == "skipped"
    assert status["readiness_gates"]["live_backend_switch"]["status"] == "blocked"


def test_retrieval_backend_status_exposes_runtime_truth_and_missing_operator_docs(tmp_path):
    missing_docs = tmp_path / "missing_recovery_docs.md"

    status = build_retrieval_backend_status(
        dependency_probe=lambda name: name == "chromadb",
        operator_docs_path=missing_docs,
    )

    assert status["runtime_mode"] == "direct_legacy_compatibility"
    assert status["daemon_owned"] is False
    assert status["direct_mode_legacy"] is True
    assert status["candidate_dependency_available"] is False
    assert status["daemon_memory_os_backend"]["role"] == "product_path"
    assert status["direct_legacy_backend"]["backend"] == "chroma"
    assert status["corpus_parity_status"]["status"] == "blocked"
    assert status["corpus_parity_status"]["source_status"] == "skipped"
    assert status["corpus_parity_status"]["blocker"] is True
    assert status["operator_docs_status"]["status"] == "blocked"
    assert status["recovery_gate_status"]["status"] == "blocked"
    assert status["live_switch_decision"]["decision"] == "deferred"
    assert status["live_switch_decision"]["allow_live_switch"] is False
    assert status["readiness_gates"]["corpus_parity"]["status"] == "blocked"
    assert status["readiness_gates"]["operator_docs"]["status"] == "blocked"


def test_retrieval_backend_status_exposes_daemon_owned_memory_os_mode(monkeypatch):
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")

    status = build_retrieval_backend_status(
        dependency_probe=lambda name: name in {"chromadb", "lancedb"},
    )

    assert status["runtime_mode"] == "daemon_owned_memory_os"
    assert status["daemon_owned"] is True
    assert status["direct_mode_legacy"] is False
    assert status["candidate_dependency_available"] is True
    assert status["current_live_backend"]["backend"] == "memory_os"
    assert status["direct_legacy_backend"]["role"] == "compatibility_and_recovery_input"
    assert status["candidate_backend"]["requested"] is False
    assert status["live_switch_decision"]["decision"] == "deferred"


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


def test_retrieval_backend_status_structures_generic_memory_os_ledger_mismatch(tmp_path):
    store_root = tmp_path / "memory_os"
    MemoryOSLedger(store_root / "ledger.sqlite3").initialize()

    status = build_retrieval_backend_status(store_root=store_root)

    assert status["store_probe"]["ledger_exists"] is True
    assert status["store_probe"]["vector_source_count"] is None
    assert "not compatible with migration vector-source probe" in status["store_probe"]["error"]
    assert status["readiness_gates"]["migrated_store_probe"]["status"] == "blocked"
