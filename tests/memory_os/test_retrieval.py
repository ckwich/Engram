import json

from core.memory_os.content_store import ContentAddressedStore
from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.legacy_import import import_legacy_memory_dir
from core.memory_os.retrieval import MemoryOSRetrievalIndex
from core.vector_index import InMemoryVectorIndex


def _ledger_and_store(root):
    return (
        MemoryOSLedger(root / "ledger.sqlite3"),
        ContentAddressedStore(root / "objects"),
    )


def _write_memory(path, payload):
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _embed(text):
    text = str(text).lower()
    if "prepare_codebase_mapping" in text:
        return [0.5, 0.0]
    if "visual hierarchy" in text or "design" in text:
        return [1.0, 0.0]
    return [0.0, 1.0]


def test_retrieval_rebuild_indexes_ledger_chunks_with_citations(tmp_path):
    legacy_dir = tmp_path / "legacy"
    store_root = tmp_path / "store"
    legacy_dir.mkdir()
    ledger, store = _ledger_and_store(store_root)
    _write_memory(
        legacy_dir / "alpha.json",
        {
            "key": "alpha",
            "title": "Alpha",
            "content": "# Alpha\n\nVisual hierarchy design notes.",
            "tags": ["design"],
            "project": "Engram",
            "domain": "books",
            "chunk_count": 1,
        },
    )
    import_legacy_memory_dir(legacy_dir, ledger, store, dry_run=False)
    retrieval = MemoryOSRetrievalIndex(
        ledger,
        tmp_path / "lance",
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )

    manifest = retrieval.rebuild_from_ledger()
    result = retrieval.search("visual hierarchy", filters={"project": "Engram"})

    assert manifest["indexed_count"] == 1
    assert manifest["source_manifest_hash"].startswith("sha256:")
    assert result["count"] == 1
    assert result["results"][0]["key"] == "alpha"
    assert result["results"][0]["citation"] == {
        "source": "memory_os_migration",
        "key": "alpha",
        "chunk_id": 0,
        "document_id": result["results"][0]["document_id"],
    }


def test_retrieval_metadata_filters_and_hybrid_identifier_ranking(tmp_path):
    legacy_dir = tmp_path / "legacy"
    store_root = tmp_path / "store"
    legacy_dir.mkdir()
    ledger, store = _ledger_and_store(store_root)
    _write_memory(
        legacy_dir / "alpha.json",
        {
            "key": "alpha",
            "title": "Alpha",
            "content": "General design mapping guidance.",
            "project": "Engram",
            "domain": "books",
            "chunk_count": 1,
        },
    )
    _write_memory(
        legacy_dir / "identifier.json",
        {
            "key": "identifier",
            "title": "Identifier",
            "content": "Use prepare_codebase_mapping before storing mapped repo context.",
            "project": "Engram",
            "domain": "code",
            "chunk_count": 1,
        },
    )
    _write_memory(
        legacy_dir / "external.json",
        {
            "key": "external",
            "title": "External",
            "content": "Visual hierarchy note from another project.",
            "project": "Other",
            "domain": "books",
            "chunk_count": 1,
        },
    )
    import_legacy_memory_dir(legacy_dir, ledger, store, dry_run=False)
    retrieval = MemoryOSRetrievalIndex(
        ledger,
        tmp_path / "lance",
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    first = retrieval.rebuild_from_ledger()
    second = retrieval.rebuild_from_ledger()

    semantic = retrieval.search("prepare_codebase_mapping", filters={"project": "Engram"}, limit=2)
    hybrid = retrieval.hybrid_search(
        "prepare_codebase_mapping",
        filters={"project": "Engram"},
        limit=2,
    )

    assert first["source_manifest_hash"] == second["source_manifest_hash"]
    assert [item["key"] for item in semantic["results"]] == ["alpha", "identifier"]
    assert [item["key"] for item in hybrid["results"]] == ["identifier", "alpha"]
    assert all(item["metadata"]["project"] == "Engram" for item in hybrid["results"])
