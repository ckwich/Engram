from __future__ import annotations

import json
from pathlib import Path

from core.graph_backend_status import build_graph_backend_status
from core.memory_os.ledger import MemoryOSLedger
from core.memory_os_migration import MemoryOSMigrationKernel


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_graph_backend_status_reports_json_live_and_optional_kuzu_gate(tmp_path):
    graph_path = tmp_path / "graph" / "edges.json"
    legacy_dir = tmp_path / "legacy"
    store_root = tmp_path / "store"
    legacy_dir.mkdir()
    _write_json(
        graph_path,
        {
            "schema_version": "2026-04-27",
            "edges": [
                {
                    "edge_id": "sha256:edge",
                    "from_ref": {"kind": "memory", "key": "alpha"},
                    "to_ref": {"kind": "memory", "key": "beta"},
                    "edge_type": "supports",
                    "confidence": 0.8,
                    "evidence": "Alpha supports beta.",
                    "source": "test",
                    "status": "active",
                    "created_by": "pytest",
                    "created_at": "2026-05-12T00:00:00-07:00",
                    "updated_at": "2026-05-12T00:00:00-07:00",
                }
            ],
        },
    )
    _write_json(
        legacy_dir / "alpha.json",
        {
            "key": "alpha",
            "title": "Alpha",
            "content": "Alpha content",
            "related_to": ["beta"],
            "chunk_count": 1,
        },
    )
    MemoryOSMigrationKernel(store_root).import_legacy_json(legacy_dir)

    status = build_graph_backend_status(
        store_root=store_root,
        graph_path=graph_path,
        dependency_probe=lambda name: False,
    )

    assert status["schema_version"] == "2026-05-12.graph_backend_status.v1"
    assert status["operation"] == "graph_backend_status"
    assert status["write_performed"] is False
    assert status["active_memory_write_performed"] is False
    assert status["live_graph_backend_changed"] is False
    assert status["current_live_backend"]["backend"] == "json_graph_store"
    assert status["current_live_backend"]["edge_count"] == 1
    assert status["candidate_backend"]["backend"] == "kuzu"
    assert status["candidate_backend"]["required"] is False
    assert status["candidate_backend"]["promotion_ready"] is False
    assert status["candidate_backend"]["availability"]["installed"] is False
    assert status["store_probe"]["ledger_exists"] is True
    assert status["store_probe"]["graph_edge_count"] == 1
    assert status["graph_parity_probe"]["status"] == "skipped"
    assert status["readiness_gates"]["graph_store_contract"]["status"] == "pass"
    assert status["readiness_gates"]["kuzu_dependency"]["status"] == "blocked"
    assert status["readiness_gates"]["graph_parity"]["status"] == "skipped"
    assert status["readiness_gates"]["live_backend_switch"]["status"] == "blocked"


def test_graph_backend_status_exposes_runtime_truth_and_missing_operator_docs(tmp_path):
    missing_docs = tmp_path / "missing_graph_recovery_docs.md"

    status = build_graph_backend_status(
        graph_path=None,
        dependency_probe=lambda name: False,
        operator_docs_path=missing_docs,
    )

    assert status["runtime_mode"] == "direct_legacy_compatibility"
    assert status["daemon_owned"] is False
    assert status["direct_mode_legacy"] is True
    assert status["candidate_dependency_available"] is False
    assert status["daemon_memory_os_backend"]["role"] == "product_path"
    assert status["direct_legacy_backend"]["backend"] == "json_graph_store"
    assert status["corpus_parity_status"]["status"] == "blocked"
    assert status["corpus_parity_status"]["source_status"] == "skipped"
    assert status["corpus_parity_status"]["blocker"] is True
    assert status["operator_docs_status"]["status"] == "blocked"
    assert status["recovery_gate_status"]["status"] == "blocked"
    assert status["live_switch_decision"]["decision"] == "deferred"
    assert status["live_switch_decision"]["allow_live_switch"] is False
    assert status["readiness_gates"]["corpus_parity"]["status"] == "blocked"
    assert status["readiness_gates"]["operator_docs"]["status"] == "blocked"


def test_graph_backend_status_exposes_daemon_owned_memory_os_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")

    status = build_graph_backend_status(
        graph_path=tmp_path / "missing" / "edges.json",
        dependency_probe=lambda name: name == "kuzu",
    )

    assert status["runtime_mode"] == "daemon_owned_memory_os"
    assert status["daemon_owned"] is True
    assert status["direct_mode_legacy"] is False
    assert status["candidate_dependency_available"] is True
    assert status["current_live_backend"]["backend"] == "memory_os"
    assert status["direct_legacy_backend"]["role"] == "compatibility_and_recovery_input"
    assert status["candidate_backend"]["requested"] is False
    assert status["live_switch_decision"]["decision"] == "deferred"


def test_graph_backend_status_reports_configured_kuzu_without_switching(monkeypatch, tmp_path):
    monkeypatch.setenv("ENGRAM_GRAPH_BACKEND", "kuzu")

    status = build_graph_backend_status(
        graph_path=tmp_path / "missing" / "edges.json",
        dependency_probe=lambda name: name == "kuzu",
    )

    assert status["backend_config"]["graph_backend"] == "kuzu"
    assert status["backend_config"]["graph_candidate_requested"] is True
    assert status["backend_config"]["live_switch_performed"] is False
    assert status["current_live_backend"]["backend"] == "json_graph_store"
    assert status["candidate_backend"]["requested"] is True
    assert status["readiness_gates"]["live_backend_switch"]["status"] == "blocked"


def test_graph_backend_status_structures_generic_memory_os_ledger_mismatch(tmp_path):
    store_root = tmp_path / "memory_os"
    MemoryOSLedger(store_root / "ledger.sqlite3").initialize()

    status = build_graph_backend_status(store_root=store_root, graph_path=None)

    assert status["store_probe"]["ledger_exists"] is True
    assert status["store_probe"]["graph_edge_count"] is None
    assert "not compatible with migration graph-edge probe" in status["store_probe"]["error"]
    assert status["readiness_gates"]["migrated_graph_edges"]["status"] == "blocked"
