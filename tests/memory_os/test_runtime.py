from core.memory_os.runtime import MemoryOSRuntime
from core.vector_index import InMemoryVectorIndex


def _embed(text):
    text = str(text).lower()
    if "visual hierarchy" in text:
        return [1.0, 0.0]
    if "daemon smoke" in text:
        return [0.8, 0.0]
    return [0.0, 1.0]


def test_memory_os_runtime_initializes_core_components(tmp_path):
    runtime = MemoryOSRuntime(tmp_path, embed_text=lambda text: [0.0])

    status = runtime.initialize()

    assert status["status"] == "ok"
    assert status["components"]["ledger"]["path"].endswith("ledger.sqlite3")
    assert status["components"]["content_store"]["path"].endswith("objects")
    assert status["components"]["retrieval"]["backend"] == "LanceDBVectorIndex"
    assert status["components"]["graph"]["backend"] == "KuzuGraphStore"
    assert status["components"]["jobs"]["status"] == "ready"
    assert status["components"]["transactions"]["status"] == "ready"
    assert status["components"]["firewall"]["status"] == "ready"


def test_memory_os_runtime_initializes_from_fresh_nested_root(tmp_path):
    root = tmp_path / "fresh" / "memory_os"

    runtime = MemoryOSRuntime(root, embed_text=lambda text: [0.0])
    status = runtime.initialize()

    assert status["status"] == "ok"
    assert root.exists()
    assert status["components"]["ledger"]["exists"] is True
    assert status["components"]["content_store"]["exists"] is True


def test_memory_os_runtime_source_imports_create_jobs(tmp_path):
    runtime = MemoryOSRuntime(tmp_path, embed_text=lambda text: [0.0])
    runtime.initialize()

    job = runtime.prepare_source_import_job(
        source_ref={"source_uri": "file:///books/design.pdf"},
        source_type="pdf",
        connector_id="local_path",
    )

    assert job["status"] == "queued"
    assert job["job_kind"] == "source_import"
    assert job["payload"]["source_ref"]["source_uri"] == "file:///books/design.pdf"


def test_memory_os_runtime_handles_stable_memory_cycle(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()

    stored = runtime.store_memory(
        key="design_alpha",
        content="# Design\n\nVisual hierarchy guides attention.",
        title="Design Alpha",
        tags=["design"],
        project="Engram",
        domain="books",
        canonical=True,
    )
    duplicate = runtime.check_duplicate("design_alpha", "Visual hierarchy guides attention.")
    search = runtime.search_memories("visual hierarchy", project="Engram")
    chunk = runtime.retrieve_chunk("design_alpha", 0)
    memory = runtime.retrieve_memory("design_alpha")
    updated = runtime.update_memory_metadata(
        "design_alpha",
        title="Updated Design Alpha",
        tags=["design", "reviewed"],
    )
    repair = runtime.repair_memory_metadata(["design_alpha"], dry_run=True)
    deleted = runtime.delete_memory("design_alpha")
    post_delete = runtime.search_memories("visual hierarchy", project="Engram")
    inspector = runtime.inspector()

    assert stored["key"] == "design_alpha"
    assert stored["storage_backend"] == "memory_os"
    assert duplicate["duplicate"] is True
    assert search["backend"] == "memory_os"
    assert search["results"][0]["key"] == "design_alpha"
    assert chunk["found"] is True
    assert chunk["chunk"]["text"].startswith("# Design")
    assert memory["found"] is True
    assert memory["memory"]["content"] == "# Design\n\nVisual hierarchy guides attention."
    assert updated["updated"] is True
    assert updated["memory"]["title"] == "Updated Design Alpha"
    assert repair["dry_run"] is True
    assert deleted["deleted"] is True
    assert post_delete["count"] == 0
    assert inspector["summary"]["transaction_count"] >= 1


def test_memory_os_runtime_records_metadata_updates_as_distinct_transactions(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()

    stored = runtime.store_memory(
        key="receipt_alpha",
        content="# Receipt\n\nStable content.",
        title="Receipt Alpha",
        tags=["alpha"],
    )
    before = runtime.inspector()["summary"]["transaction_count"]
    updated = runtime.update_memory_metadata(
        "receipt_alpha",
        title="Receipt Alpha Reviewed",
        tags=["alpha", "reviewed"],
    )
    after = runtime.inspector()["summary"]["transaction_count"]

    assert updated["updated"] is True
    assert updated["memory"]["transaction_id"] != stored["transaction_id"]
    assert after == before + 1
