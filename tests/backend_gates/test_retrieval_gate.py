from __future__ import annotations

import json
from pathlib import Path

from core.backend_gates.retrieval_gate import build_retrieval_backend_gate
from core.memory_os_migration import MemoryOSMigrationKernel


def _write_memory(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_retrieval_backend_gate_wraps_existing_status_without_switching(tmp_path):
    legacy_dir = tmp_path / "legacy"
    store_root = tmp_path / "store"
    legacy_dir.mkdir()
    _write_memory(
        legacy_dir / "alpha.json",
        {
            "key": "alpha",
            "title": "Alpha",
            "content": "Alpha migration notes",
            "chunk_count": 1,
        },
    )
    MemoryOSMigrationKernel(store_root).import_legacy_json(legacy_dir)

    gate = build_retrieval_backend_gate(
        store_root=store_root,
        include_rebuild_probe=True,
        dependency_probe=lambda name: name in {"chromadb", "lancedb"},
    )

    assert gate["schema_version"] == "2026-05-13.backend-gate.v1"
    assert gate["operation"] == "retrieval_backend_gate"
    assert gate["source_operation"] == "retrieval_backend_status"
    assert gate["backend"] == "retrieval"
    assert gate["write_performed"] is False
    assert gate["active_memory_write_performed"] is False
    assert gate["live_backend_changed"] is False
    assert gate["decision"] == "not_ready"
    assert gate["source_status"]["current_live_backend"]["backend"] == "chroma"
    assert gate["rebuild_status"]["status"] == "pass"
    assert gate["parity"]["status"] == "skipped"
    assert gate["live_switch_decision"]["decision"] == "deferred"
    assert gate["corpus_parity_status"]["status"] == "blocked"
    assert gate["recovery_gate_status"]["status"] == "blocked"
    assert gate["operator_docs_status"]["status"] == "pass"
    assert {failure["gate"] for failure in gate["blocking_failures"]} >= {
        "corpus_parity",
        "golden_retrieval_comparison",
        "live_backend_switch",
        "recovery_gate",
        "real_lancedb_corpus_spike",
        "windows_reliability",
    }


def test_retrieval_backend_gate_blocks_if_status_reports_live_switch():
    gate = build_retrieval_backend_gate(
        status_payload={
            "schema_version": "test",
            "operation": "retrieval_backend_status",
            "live_retrieval_changed": True,
            "readiness_gates": {
                "live_backend_switch": {"status": "pass", "evidence": "forced in test"},
                "windows_path_reliability": {"status": "pass", "evidence": "synthetic"},
            },
            "golden_comparison_probe": {"status": "pass"},
            "recommendation": "test",
            "error": None,
        }
    )

    assert gate["decision"] == "not_ready"
    assert any(failure["gate"] == "live_retrieval_changed" for failure in gate["blocking_failures"])


def test_retrieval_backend_gate_passes_through_final_state_truth():
    gate = build_retrieval_backend_gate(
        status_payload={
            "schema_version": "test",
            "operation": "retrieval_backend_status",
            "runtime_mode": "daemon_owned_memory_os",
            "daemon_owned": True,
            "direct_mode_legacy": False,
            "live_retrieval_changed": False,
            "candidate_dependency_available": True,
            "corpus_parity_status": {"status": "blocked", "source_status": "skipped"},
            "recovery_gate_status": {"status": "blocked"},
            "operator_docs_status": {"status": "pass"},
            "live_switch_decision": {"decision": "deferred", "allow_live_switch": False},
            "readiness_gates": {
                "corpus_parity": {"status": "blocked", "evidence": "skipped parity is blocker"},
                "operator_docs": {"status": "pass", "evidence": "documented"},
                "recovery_gate": {"status": "blocked", "evidence": "not drilled"},
                "live_backend_switch": {"status": "blocked", "evidence": "deferred"},
                "windows_path_reliability": {"status": "blocked", "evidence": "not proven"},
            },
            "golden_comparison_probe": {"status": "skipped"},
            "recommendation": "test",
            "error": None,
        }
    )

    assert gate["runtime_mode"] == "daemon_owned_memory_os"
    assert gate["daemon_owned"] is True
    assert gate["direct_mode_legacy"] is False
    assert gate["candidate_dependency_available"] is True
    assert gate["live_switch_decision"]["allow_live_switch"] is False
