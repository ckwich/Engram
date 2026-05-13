from core.memory_os.runtime import MemoryOSRuntime


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
