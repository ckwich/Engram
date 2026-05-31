from __future__ import annotations

import json
from pathlib import Path

from core.memory_os._records import upsert_record
from core.memory_os.corpus_inventory import build_corpus_inventory
from core.memory_os.ledger import MemoryOSLedger


def _write_legacy_memory(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def test_corpus_inventory_reports_legacy_and_memory_os_parity(tmp_path):
    legacy_dir = tmp_path / "legacy"
    memory_os_root = tmp_path / "memory_os"
    legacy_dir.mkdir()

    _write_legacy_memory(
        legacy_dir / "alpha.json",
        {
            "key": "alpha",
            "title": "Alpha",
            "content": "# Alpha\n\nAlpha content",
            "project": "Engram",
            "status": "active",
            "related_to": ["beta", "gamma"],
            "chunk_count": 1,
            "legacy_only_field": "artifact-only",
        },
    )
    _write_legacy_memory(
        legacy_dir / "beta.json",
        {
            "key": "beta",
            "title": "Beta",
            "content": "Beta content",
            "project": "C:\\Dev\\Engram",
            "status": "draft",
            "related_to": [],
            "chunk_count": 1,
        },
    )
    _write_legacy_memory(
        legacy_dir / "gamma.json",
        {
            "key": "gamma",
            "title": "Gamma",
            "content": "Gamma content",
            "project": "C:/Dev/Engram",
            "related_to": [],
            "chunk_count": 1,
        },
    )
    (legacy_dir / "broken.json").write_text("{not-json", encoding="utf-8")

    ledger = MemoryOSLedger(memory_os_root / "ledger.sqlite3")
    upsert_record(
        ledger,
        "memories",
        "alpha",
        {"key": "alpha", "project": "Engram", "status": "active", "chunk_count": 1},
    )
    upsert_record(
        ledger,
        "memories",
        "omega",
        {"key": "omega", "project": "Other", "status": "accepted", "chunk_count": 1},
    )
    upsert_record(ledger, "chunks", "alpha:chunk:0", {"memory_key": "alpha", "chunk_id": 0})
    upsert_record(ledger, "chunks", "omega:chunk:0", {"memory_key": "omega", "chunk_id": 0})
    upsert_record(ledger, "documents", "doc:one", {"document_id": "doc:one"})
    upsert_record(
        ledger,
        "graph_edges",
        "edge:one",
        {"edge_id": "edge:one", "from_ref": {"kind": "memory", "key": "alpha"}},
    )

    report = build_corpus_inventory(
        legacy_dir=legacy_dir,
        memory_os_root=memory_os_root,
    )

    assert report["write_policy"] == "no_write"
    assert report["write_performed"] is False
    assert report["legacy_json_count"] == 4
    assert report["legacy_invalid_json_count"] == 1
    assert report["legacy_related_to_count"] == 1
    assert report["legacy_related_to_edge_count"] == 2
    assert report["legacy_status_counts"] == {"<null>": 1, "active": 1, "draft": 1}
    assert report["legacy_project_counts"] == {
        "C:/Dev/Engram": 1,
        "C:\\Dev\\Engram": 1,
        "Engram": 1,
    }
    assert report["memory_os_memory_count"] == 2
    assert report["memory_os_chunk_count"] == 2
    assert report["memory_os_document_count"] == 1
    assert report["memory_os_graph_edge_count"] == 1
    assert report["memory_os_project_counts"] == {"Engram": 1, "Other": 1}
    assert report["memory_os_status_counts"] == {"accepted": 1, "active": 1}
    assert report["missing_in_memory_os"] == ["beta", "gamma"]
    assert report["extra_in_memory_os"] == ["omega"]
    assert report["unsupported_legacy_fields"] == {"alpha": ["legacy_only_field"]}
    assert report["status_mapping_gaps"] == []
    assert report["project_identity_collisions"] == [
        {
            "canonical_project": "engram",
            "labels": ["C:/Dev/Engram", "C:\\Dev\\Engram", "Engram"],
            "memory_count": 4,
        }
    ]


def test_corpus_inventory_is_no_write_when_memory_os_ledger_is_missing(tmp_path):
    legacy_dir = tmp_path / "legacy"
    memory_os_root = tmp_path / "missing_memory_os"
    legacy_dir.mkdir()
    _write_legacy_memory(
        legacy_dir / "alpha.json",
        {"key": "alpha", "title": "Alpha", "content": "Alpha content"},
    )

    report = build_corpus_inventory(
        legacy_dir=legacy_dir,
        memory_os_root=memory_os_root,
    )

    assert report["memory_os_memory_count"] == 0
    assert report["missing_in_memory_os"] == ["alpha"]
    assert report["extra_in_memory_os"] == []
    assert not memory_os_root.exists()
