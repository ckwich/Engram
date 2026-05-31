import json

from core.memory_os.content_store import ContentAddressedStore
from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.legacy_import import import_legacy_memory_dir
from core.memory_os_migration import MemoryOSMigrationKernel


def _write_memory(path, payload):
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _ledger_and_store(root):
    return (
        MemoryOSLedger(root / "ledger.sqlite3"),
        ContentAddressedStore(root / "objects"),
    )


def test_legacy_import_wrapper_dry_run_reports_without_writing_store(tmp_path):
    legacy_dir = tmp_path / "legacy"
    store_root = tmp_path / "store"
    legacy_dir.mkdir()
    ledger, store = _ledger_and_store(store_root)

    _write_memory(
        legacy_dir / "alpha.json",
        {
            "key": "alpha",
            "title": "Alpha",
            "content": "Alpha content",
            "tags": ["design"],
            "related_to": ["beta"],
            "chunk_count": 1,
        },
    )

    report = import_legacy_memory_dir(legacy_dir, ledger, store, dry_run=True)

    assert report["dry_run"] is True
    assert report["valid_count"] == 1
    assert report["key_set"] == ["alpha"]
    assert not ledger.path.exists()
    assert not store.root.exists()


def test_legacy_import_wrapper_preserves_metadata_graph_edges_and_artifacts(tmp_path):
    legacy_dir = tmp_path / "legacy"
    store_root = tmp_path / "store"
    legacy_dir.mkdir()
    ledger, store = _ledger_and_store(store_root)
    alpha = _write_memory(
        legacy_dir / "alpha.json",
        {
            "key": "alpha",
            "title": "Alpha",
            "content": "# Alpha\n\nAlpha content",
            "tags": ["design"],
            "project": "Engram",
            "domain": "memory-os",
            "status": "active",
            "canonical": True,
            "related_to": ["beta"],
            "chunk_count": 99,
        },
    )

    report = import_legacy_memory_dir(legacy_dir, ledger, store, dry_run=False)
    kernel = MemoryOSMigrationKernel(store_root)
    memory = kernel.read_memory_record("alpha")
    edges = kernel.read_graph_edge_records("alpha")

    assert report["imported_count"] == 1
    assert report["chunk_count_mismatches"] == [
        {"key": "alpha", "legacy_chunk_count": 99, "derived_chunk_count": 1}
    ]
    assert memory["title"] == "Alpha"
    assert memory["tags"] == ["design"]
    assert memory["project"] == "Engram"
    assert memory["canonical"] is True
    assert [(edge["from_ref"]["key"], edge["to_ref"]["key"]) for edge in edges] == [
        ("alpha", "beta")
    ]
    assert all("content" not in edge for edge in edges)
    artifact_path = kernel._artifact_path(report["artifact_hashes"]["alpha"])
    assert json.loads(artifact_path.read_text(encoding="utf-8")) == alpha
