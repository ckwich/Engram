from __future__ import annotations

import json
from pathlib import Path

from core.backend_gates.graph_gate import build_graph_backend_gate
from core.memory_os_migration import MemoryOSMigrationKernel


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_graph_backend_gate_wraps_existing_status_without_switching(tmp_path):
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

    gate = build_graph_backend_gate(
        store_root=store_root,
        graph_path=graph_path,
        dependency_probe=lambda name: name == "kuzu",
    )

    assert gate["schema_version"] == "2026-05-13.backend-gate.v1"
    assert gate["operation"] == "graph_backend_gate"
    assert gate["source_operation"] == "graph_backend_status"
    assert gate["backend"] == "graph"
    assert gate["write_performed"] is False
    assert gate["active_memory_write_performed"] is False
    assert gate["live_backend_changed"] is False
    assert gate["decision"] == "not_ready"
    assert gate["source_status"]["current_live_backend"]["backend"] == "json_graph_store"
    assert gate["parity"]["status"] == "skipped"
    assert {failure["gate"] for failure in gate["blocking_failures"]} >= {
        "graph_parity",
        "real_kuzu_corpus_spike",
        "live_backend_switch",
        "windows_reliability",
    }


def test_graph_backend_gate_blocks_if_status_reports_live_switch():
    gate = build_graph_backend_gate(
        status_payload={
            "schema_version": "test",
            "operation": "graph_backend_status",
            "live_graph_backend_changed": True,
            "readiness_gates": {
                "live_backend_switch": {"status": "pass", "evidence": "forced in test"},
                "windows_path_reliability": {"status": "pass", "evidence": "synthetic"},
            },
            "graph_parity_probe": {"status": "pass"},
            "recommendation": "test",
            "error": None,
        }
    )

    assert gate["decision"] == "not_ready"
    assert any(failure["gate"] == "live_graph_backend_changed" for failure in gate["blocking_failures"])
