import json

from core.memory_os.bundles import export_memory_passport, restore_memory_passport
from core.memory_os.content_store import ContentAddressedStore
from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.legacy_import import import_legacy_memory_dir
from core.memory_os.schema import SCHEMA_VERSION
from core.memory_os_migration import MemoryOSMigrationKernel


def _ledger_and_store(root):
    return (
        MemoryOSLedger(root / "ledger.sqlite3"),
        ContentAddressedStore(root / "objects"),
    )


def test_memory_passport_export_writes_manifest_with_artifact_ids(tmp_path):
    legacy_dir = tmp_path / "legacy"
    store_root = tmp_path / "store"
    bundle_dir = tmp_path / "bundle"
    legacy_dir.mkdir()
    ledger, store = _ledger_and_store(store_root)
    (legacy_dir / "alpha.json").write_text(
        json.dumps(
            {
                "key": "alpha",
                "title": "Alpha",
                "content": "Alpha content",
                "tags": ["design"],
                "chunk_count": 1,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    import_legacy_memory_dir(legacy_dir, ledger, store, dry_run=False)

    manifest = export_memory_passport(ledger, store, bundle_dir)
    bundle = json.loads((bundle_dir / "memory_passport.json").read_text(encoding="utf-8"))

    assert manifest["schema_version"] == SCHEMA_VERSION
    assert manifest["memory_count"] == 1
    assert manifest["artifact_ids"] == [bundle["memories"][0]["artifact_sha256"]]
    assert manifest["bundle_path"] == str(bundle_dir / "memory_passport.json")
    assert bundle["memory_count"] == 1


def test_memory_passport_restore_preserves_keys_and_metadata_without_chroma(tmp_path):
    legacy_dir = tmp_path / "legacy"
    store_root = tmp_path / "store"
    bundle_dir = tmp_path / "bundle"
    restored_root = tmp_path / "restored"
    legacy_dir.mkdir()
    ledger, store = _ledger_and_store(store_root)
    (legacy_dir / "alpha.json").write_text(
        json.dumps(
            {
                "key": "alpha",
                "title": "Alpha",
                "content": "Alpha content",
                "tags": ["design"],
                "project": "Engram",
                "chunk_count": 1,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    import_legacy_memory_dir(legacy_dir, ledger, store, dry_run=False)
    export_memory_passport(ledger, store, bundle_dir)

    report = restore_memory_passport(bundle_dir / "memory_passport.json", restored_root)
    restored = MemoryOSMigrationKernel(restored_root)

    assert report["schema_version"] == SCHEMA_VERSION
    assert report["restored_count"] == 1
    assert restored.key_set() == ["alpha"]
    assert restored.read_memory_record("alpha")["project"] == "Engram"
    assert not (restored_root / "chroma").exists()
