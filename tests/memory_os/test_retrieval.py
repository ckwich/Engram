import json

from core.memory_os.content_store import ContentAddressedStore
from core.memory_os._records import upsert_record
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


def test_retrieval_rebuild_indexes_document_ingestion_chunks_with_job_metadata(tmp_path):
    store_root = tmp_path / "store"
    ledger = MemoryOSLedger(store_root / "ledger.sqlite3")
    ledger.initialize()
    document_id = "doc_design_book"
    ingestion_id = "doc_ingest_design_book"
    chunk_record_id = f"{document_id}:ingestion:{ingestion_id}:window:0000:chunk:10000"
    upsert_record(
        ledger,
        "documents",
        document_id,
        {
            "document_id": document_id,
            "title": "The Art of Game Design",
            "document": {"title": "The Art of Game Design"},
        },
    )
    upsert_record(
        ledger,
        "jobs",
        ingestion_id,
        {
            "record_type": "document_ingestion",
            "ingestion_id": ingestion_id,
            "document_id": document_id,
            "project": "Engram",
            "domain": "document_intelligence",
            "readiness": {"searchable": True},
        },
    )
    upsert_record(
        ledger,
        "chunks",
        chunk_record_id,
        {
            "chunk_record_id": chunk_record_id,
            "document_id": document_id,
            "ingestion_id": ingestion_id,
            "window_index": 0,
            "page_range": {"start": 1, "end": 25},
            "local_chunk_id": 0,
            "chunk_id": 10000,
            "text": "The Art of Game Design introduces lenses for essential experience.",
            "heading_path": [],
            "chunk_kind": "paragraph",
        },
    )
    retrieval = MemoryOSRetrievalIndex(
        ledger,
        tmp_path / "lance",
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )

    manifest = retrieval.rebuild_from_ledger()
    result = retrieval.hybrid_search(
        "essential experience lenses",
        filters={"project": "Engram"},
        limit=3,
    )

    assert manifest["indexed_count"] == 1
    assert result["count"] == 1
    assert result["results"][0]["key"] == document_id
    assert result["results"][0]["metadata"]["title"] == "The Art of Game Design"
    assert result["results"][0]["metadata"]["domain"] == "document_intelligence"
    assert result["results"][0]["metadata"]["document_primary_subject"] == "game_design"
    assert result["results"][0]["metadata"]["document_reading_role"] == "core"
    assert result["results"][0]["metadata"]["document_collections"] == ["game_design_books"]
    assert "core-game-design" in result["results"][0]["metadata"]["tags"]
    assert result["results"][0]["citation"] == {
        "source": "memory_os",
        "key": document_id,
        "chunk_id": 10000,
        "document_id": chunk_record_id,
    }


def test_retrieval_search_deduplicates_document_chunk_rows(tmp_path):
    store_root = tmp_path / "store"
    ledger = MemoryOSLedger(store_root / "ledger.sqlite3")
    ledger.initialize()
    document_id = "doc_design_book"
    ingestion_id = "doc_ingest_design_book"
    upsert_record(
        ledger,
        "documents",
        document_id,
        {"document_id": document_id, "title": "The Art of Game Design"},
    )
    upsert_record(
        ledger,
        "jobs",
        ingestion_id,
        {
            "record_type": "document_ingestion",
            "ingestion_id": ingestion_id,
            "document_id": document_id,
            "project": "Engram",
            "domain": "document_intelligence",
        },
    )
    for record_id, window_index in (
        (f"{document_id}:chunk:10000", None),
        (f"{document_id}:ingestion:{ingestion_id}:window:0000:chunk:10000", 0),
    ):
        upsert_record(
            ledger,
            "chunks",
            record_id,
            {
                "chunk_record_id": record_id,
                "document_id": document_id,
                "ingestion_id": ingestion_id if window_index is not None else None,
                "window_index": window_index,
                "page_range": {"start": 1, "end": 25},
                "local_chunk_id": 0,
                "chunk_id": 10000,
                "text": "The Art of Game Design essential experience lenses.",
                "heading_path": [],
                "chunk_kind": "paragraph",
            },
        )
    retrieval = MemoryOSRetrievalIndex(
        ledger,
        tmp_path / "lance",
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )

    retrieval.rebuild_from_ledger()
    result = retrieval.hybrid_search("essential experience", filters={"project": "Engram"}, limit=5)

    assert result["count"] == 1
    assert result["results"][0]["key"] == document_id
    assert result["results"][0]["citation"]["document_id"].startswith(f"{document_id}:ingestion:")


def test_retrieval_search_deduplicates_same_text_with_different_chunk_ids(tmp_path):
    store_root = tmp_path / "store"
    ledger = MemoryOSLedger(store_root / "ledger.sqlite3")
    ledger.initialize()
    document_id = "doc_design_book"
    ingestion_id = "doc_ingest_design_book"
    upsert_record(
        ledger,
        "documents",
        document_id,
        {"document_id": document_id, "title": "The Art of Game Design"},
    )
    upsert_record(
        ledger,
        "jobs",
        ingestion_id,
        {
            "record_type": "document_ingestion",
            "ingestion_id": ingestion_id,
            "document_id": document_id,
            "project": "Engram",
            "domain": "document_intelligence",
        },
    )
    for record_id, chunk_id, window_index in (
        (f"{document_id}:chunk:10000", 10000, None),
        (f"{document_id}:ingestion:{ingestion_id}:window:0000:chunk:760031", 760031, 0),
    ):
        upsert_record(
            ledger,
            "chunks",
            record_id,
            {
                "chunk_record_id": record_id,
                "document_id": document_id,
                "ingestion_id": ingestion_id if window_index is not None else None,
                "window_index": window_index,
                "page_range": {"start": 1, "end": 25},
                "local_chunk_id": 0,
                "chunk_id": chunk_id,
                "text": "The Art of Game Design essential experience lenses.",
                "heading_path": [],
                "chunk_kind": "paragraph",
            },
        )
    retrieval = MemoryOSRetrievalIndex(
        ledger,
        tmp_path / "lance",
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )

    retrieval.rebuild_from_ledger()
    result = retrieval.hybrid_search("essential experience", filters={"project": "Engram"}, limit=5)

    assert result["count"] == 1
    assert result["results"][0]["citation"]["document_id"].startswith(f"{document_id}:ingestion:")


def test_retrieval_rebuild_reuses_current_manifest_without_reembedding(tmp_path):
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
            "project": "Engram",
            "chunk_count": 1,
        },
    )
    import_legacy_memory_dir(legacy_dir, ledger, store, dry_run=False)
    embed_calls = []

    def embed_once(text):
        embed_calls.append(text)
        return _embed(text)

    retrieval = MemoryOSRetrievalIndex(
        ledger,
        tmp_path / "lance",
        embed_text=embed_once,
        vector_index=InMemoryVectorIndex(),
    )

    first = retrieval.rebuild_from_ledger()
    second = retrieval.rebuild_from_ledger()

    assert first["rebuild_skipped"] is False
    assert second["rebuild_skipped"] is True
    assert len(embed_calls) == 1


def test_retrieval_existing_index_state_detects_stale_source_hash(tmp_path):
    legacy_dir = tmp_path / "legacy"
    store_root = tmp_path / "store"
    legacy_dir.mkdir()
    ledger, store = _ledger_and_store(store_root)
    alpha_path = legacy_dir / "alpha.json"
    _write_memory(
        alpha_path,
        {
            "key": "alpha",
            "title": "Alpha",
            "content": "# Alpha\n\nVisual hierarchy design notes.",
            "project": "Engram",
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
    retrieval.rebuild_from_ledger()
    _write_memory(
        alpha_path,
        {
            "key": "alpha",
            "title": "Alpha",
            "content": "# Alpha\n\nUpdated visual hierarchy design notes.",
            "project": "Engram",
            "chunk_count": 1,
        },
    )
    import_legacy_memory_dir(legacy_dir, ledger, store, dry_run=False)

    state = retrieval.existing_index_state()

    assert state["status"] == "stale_manifest"
    assert state["ready"] is False
    assert state["diagnostics"]["gate"] == "retrieval_manifest_consistency"
    assert "source_manifest_hash" in state["diagnostics"]["mismatches"]
    assert state["diagnostics"]["source_count"] == 1
    assert state["diagnostics"]["indexed_count"] == 1
    assert "Rebuild retrieval" in state["repair_guidance"]


def test_retrieval_existing_index_state_detects_count_skew(tmp_path):
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
            "project": "Engram",
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
    retrieval.rebuild_from_ledger()
    _write_memory(
        legacy_dir / "beta.json",
        {
            "key": "beta",
            "title": "Beta",
            "content": "# Beta\n\nNew source after the last retrieval rebuild.",
            "project": "Engram",
            "chunk_count": 1,
        },
    )
    import_legacy_memory_dir(legacy_dir, ledger, store, dry_run=False)

    state = retrieval.existing_index_state()

    assert state["status"] == "needs_rebuild"
    assert state["ready"] is False
    assert state["diagnostics"]["source_count"] == 2
    assert state["diagnostics"]["indexed_count"] == 1
    assert "indexed_count" in state["diagnostics"]["mismatches"]


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
