import pytest

from core.graph_store import JsonGraphStore, empty_graph
from core.memory_limits import MAX_DIRECT_MEMORY_CHARS
from core.memory_os.runtime import MemoryOSRuntime
from core.memory_os._records import list_records, read_record, upsert_record
from core.vector_index import InMemoryVectorIndex, VectorIndexDocument


def _embed(text):
    text = str(text).lower()
    if "visual hierarchy" in text:
        return [1.0, 0.0]
    if "daemon smoke" in text:
        return [0.8, 0.0]
    return [0.0, 1.0]


class RecordingVectorIndex(InMemoryVectorIndex):
    def __init__(self):
        super().__init__()
        self.rebuild_calls = 0
        self.upsert_calls = 0
        self.deleted_parent_keys = []

    def rebuild(self, documents):
        self.rebuild_calls += 1
        super().rebuild(documents)

    def upsert_many(self, documents):
        self.upsert_calls += 1
        super().upsert_many(documents)

    def delete_by_parent_key(self, parent_key):
        self.deleted_parent_keys.append(parent_key)
        return super().delete_by_parent_key(parent_key)


class FailingUpsertVectorIndex(InMemoryVectorIndex):
    def __init__(self):
        super().__init__()
        self.fail_upserts = False

    def upsert_many(self, documents):
        if self.fail_upserts:
            raise RuntimeError("forced retrieval failure")
        return super().upsert_many(documents)


class FailingGraphStore:
    def upsert_edges(self, edges):
        raise RuntimeError("forced graph failure")

    def load_graph(self):
        return {"nodes": [], "edges": []}

    def save_graph(self, graph):
        raise RuntimeError("forced graph failure")


class ToggleFailingGraphStore:
    def __init__(self):
        self.fail = False
        self.edges: list[dict] = []

    def upsert_edges(self, edges):
        if self.fail:
            raise RuntimeError("forced graph replay failure")
        by_id = {edge["edge_id"]: edge for edge in self.edges}
        for edge in edges:
            by_id[edge["edge_id"]] = dict(edge)
        self.edges = [by_id[edge_id] for edge_id in sorted(by_id)]

    def load_graph(self):
        return {"nodes": [], "edges": list(self.edges)}

    def save_graph(self, graph):
        if self.fail:
            raise RuntimeError("forced graph replay failure")
        self.edges = list(graph.get("edges") or [])


def test_memory_os_runtime_initializes_core_components(tmp_path):
    runtime = MemoryOSRuntime(tmp_path, embed_text=lambda text: [0.0])

    status = runtime.initialize()

    assert status["status"] == "ok"
    assert status["components"]["ledger"]["path"].endswith("ledger.sqlite3")
    assert status["components"]["ledger"]["connection_profile"]["journal_mode"].lower() == "wal"
    assert status["components"]["ledger"]["connection_profile"]["busy_timeout_ms"] >= 30_000
    assert status["components"]["content_store"]["path"].endswith("objects")
    assert status["components"]["retrieval"]["backend"] == "LanceDBVectorIndex"
    assert status["components"]["graph"]["backend"] == "KuzuGraphStore"
    assert status["components"]["graph"]["state"]["status"] == "reconciled"
    assert status["components"]["graph"]["state"]["trusted_for_evidence"] is True
    assert status["components"]["jobs"]["status"] == "ready"
    assert status["components"]["transactions"]["status"] == "ready"
    assert status["components"]["firewall"]["status"] == "ready"
    assert status["components"]["retrieval"]["state"]["status"] == "ready"
    assert runtime.retrieval_ready is True


def test_memory_os_runtime_status_surfaces_graph_reconciliation_drift(tmp_path):
    graph_store = JsonGraphStore(tmp_path / "edges.json")
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=lambda text: [0.0],
        vector_index=InMemoryVectorIndex(),
        graph_store=graph_store,
    )
    runtime.initialize()
    runtime.graph.import_edges(
        [
            {
                "edge_id": "edge:runtime-drift",
                "from_ref": {"kind": "memory", "key": "source"},
                "to_ref": {"kind": "memory", "key": "target"},
                "edge_type": "related_to",
                "confidence": 0.9,
                "evidence": "Runtime status should report graph drift.",
                "source": "test",
                "status": "active",
                "created_by": "agent",
                "created_at": "2026-05-21T00:00:00+00:00",
                "updated_at": "2026-05-21T00:00:00+00:00",
            }
        ]
    )
    graph_store.save_graph(empty_graph())

    status = runtime.status()
    graph_state = status["components"]["graph"]["state"]

    assert graph_state["status"] == "drift"
    assert graph_state["repair_required"] is True
    assert graph_state["trusted_for_evidence"] is False
    assert graph_state["drift"]["missing_in_store_sample"] == ["edge:runtime-drift"]


def test_memory_os_runtime_exposes_knowledge_pr_service(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=lambda text: [0.0],
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()

    branch = runtime.prepare_knowledge_branch(name="Runtime Knowledge Branch")
    pr = runtime.prepare_knowledge_pr(
        branch_id=branch["branch_id"],
        title="Runtime Knowledge PR",
        proposed_operations=[
            {
                "operation_id": "op:runtime-memory-ci",
                "operation_kind": "memory_write",
                "evidence_refs": [{"kind": "chunk", "chunk_id": "chunk:runtime"}],
            }
        ],
    )
    ci = runtime.run_memory_ci(knowledge_pr_id=pr["knowledge_pr_id"])
    inspected = runtime.inspect_knowledge_pr(knowledge_pr_id=pr["knowledge_pr_id"])

    assert branch["write_performed"] is True
    assert branch["active_memory_write_performed"] is False
    assert branch["graph_write_performed"] is False
    assert pr["write_performed"] is True
    assert pr["active_memory_write_performed"] is False
    assert pr["graph_write_performed"] is False
    assert ci["status"] == "passed"
    assert ci["active_memory_write_performed"] is False
    assert ci["graph_write_performed"] is False
    assert inspected["status"] == "mergeable"
    assert inspected["active_memory_write_performed"] is False
    assert inspected["graph_write_performed"] is False


def test_memory_os_runtime_can_defer_retrieval_rebuild(tmp_path):
    vector_index = RecordingVectorIndex()
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=lambda text: [0.0],
        vector_index=vector_index,
    )

    status = runtime.initialize(rebuild_retrieval=False)

    assert vector_index.rebuild_calls == 0
    assert status["components"]["retrieval"]["state"]["status"] == "deferred"
    assert runtime.retrieval_ready is False

    manifest = runtime.rebuild_retrieval_from_ledger()

    assert vector_index.rebuild_calls == 1
    assert manifest["indexed_count"] == 0
    assert runtime.retrieval_ready is True


def test_memory_os_runtime_uses_existing_retrieval_index_when_rebuild_is_deferred(tmp_path):
    vector_index = RecordingVectorIndex()
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=lambda text: [1.0],
        vector_index=vector_index,
    )
    runtime.initialize()

    runtime.store_memory(
        key="alpha",
        content="Alpha note.",
        title="Alpha",
        project="Engram",
        force=True,
    )
    maintenance = runtime.run_queued_maintenance_job(worker_id="test-maintenance")
    rebuild_count = vector_index.rebuild_calls
    second_runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=lambda text: [1.0],
        vector_index=vector_index,
    )

    status = second_runtime.initialize(rebuild_retrieval=False)

    assert maintenance["processed"] is True
    assert vector_index.rebuild_calls == rebuild_count
    assert status["components"]["retrieval"]["state"]["status"] == "ready_existing"
    assert second_runtime.retrieval_ready is True


def test_memory_os_runtime_marks_existing_retrieval_stale_when_rebuild_is_deferred(tmp_path):
    vector_index = RecordingVectorIndex()
    vector_index.rebuild(
        [
            VectorIndexDocument(
                document_id="alpha-0",
                parent_key="alpha",
                chunk_id=0,
                text="Alpha",
                embedding=[1.0],
                metadata={},
                citation={},
            )
        ]
    )
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=lambda text: [1.0],
        vector_index=vector_index,
    )

    status = runtime.initialize(rebuild_retrieval=False)

    state = status["components"]["retrieval"]["state"]
    assert vector_index.rebuild_calls == 1
    assert state["status"] == "needs_rebuild"
    assert state["ready"] is False
    assert "missing_manifest" in state["diagnostics"]["mismatches"]
    assert runtime.retrieval_ready is False


def test_memory_os_runtime_status_refreshes_incremental_retrieval_manifest(tmp_path):
    vector_index = RecordingVectorIndex()
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=lambda text: [1.0],
        vector_index=vector_index,
    )
    runtime.initialize()

    runtime.store_memory(
        key="alpha",
        content="Alpha design note.",
        title="Alpha",
        project="Engram",
        domain="notes",
        force=True,
    )
    status = runtime.status()

    manifest = status["components"]["retrieval"]["state"]["manifest"]
    assert manifest["source_count"] == 1
    assert manifest["indexed_count"] == 1
    assert manifest["stats"]["document_count"] == 1


def test_store_memory_defers_full_manifest_refresh_off_request_path(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=lambda text: [1.0],
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()

    def fail_refresh():
        raise AssertionError("full manifest refresh must not run inline")

    runtime.retrieval.refresh_manifest_from_ledger = fail_refresh

    stored = runtime.store_memory(
        key="deferred_manifest_alpha",
        content="Alpha should index without a full manifest refresh.",
        title="Deferred Manifest Alpha",
        project="Engram",
        force=True,
    )

    assert stored["retrieval_state"] == "indexed"
    assert stored["retrieval_treatment"]["manifest_refresh_required"] is True
    assert stored["retrieval_treatment"]["manifest_refresh_job"]["status"] == "queued"
    assert runtime.search_memories("manifest refresh", project="Engram")["count"] == 1


def test_update_memory_metadata_queues_retrieval_metadata_refresh(tmp_path):
    vector_index = RecordingVectorIndex()
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=lambda text: [1.0],
        vector_index=vector_index,
    )
    runtime.initialize()
    runtime.store_memory(
        key="metadata_refresh_alpha",
        content="Metadata refresh should keep text stable.",
        title="Metadata Refresh Alpha",
        project="Engram",
        domain="before",
        force=True,
    )
    upserts_after_store = vector_index.upsert_calls

    updated = runtime.update_memory_metadata(
        "metadata_refresh_alpha",
        project="Other",
        domain="after",
    )
    old_filter = runtime.search_memories("Metadata refresh", project="Engram")
    new_filter_before_worker = runtime.search_memories("Metadata refresh", project="Other")
    upserts_after_update = vector_index.upsert_calls
    worker = runtime.run_queued_maintenance_job(worker_id="metadata-refresh-worker")
    new_filter_after_worker = runtime.search_memories("Metadata refresh", project="Other")

    assert updated["updated"] is True
    assert updated["memory"]["retrieval_state"] == "metadata_refresh_pending"
    assert updated["memory"]["retrieval_treatment"]["status"] == "queued"
    assert upserts_after_update == upserts_after_store
    assert old_filter["count"] == 1
    assert new_filter_before_worker["count"] == 0
    assert worker["processed"] is True
    assert new_filter_after_worker["count"] == 1


def test_delete_memory_defers_full_manifest_refresh_off_request_path(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=lambda text: [1.0],
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()
    runtime.store_memory(
        key="delete_manifest_alpha",
        content="Delete should avoid full manifest refresh inline.",
        title="Delete Manifest Alpha",
        project="Engram",
        force=True,
    )

    def fail_refresh():
        raise AssertionError("full manifest refresh must not run inline")

    runtime.retrieval.refresh_manifest_from_ledger = fail_refresh

    deleted = runtime.delete_memory("delete_manifest_alpha")

    assert deleted["deleted"] is True
    assert deleted["retrieval_treatment"]["manifest_refresh_required"] is True
    assert deleted["retrieval_treatment"]["manifest_refresh_job"]["status"] == "queued"
    assert runtime.search_memories("avoid full manifest", project="Engram")["count"] == 0


def test_memory_os_runtime_status_marks_ready_retrieval_stale_after_ledger_drift(tmp_path):
    vector_index = RecordingVectorIndex()
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=lambda text: [1.0],
        vector_index=vector_index,
    )
    runtime.initialize()
    runtime.store_memory(
        key="alpha",
        content="Alpha design note.",
        title="Alpha",
        project="Engram",
        force=True,
    )
    assert runtime.retrieval_ready is True
    upsert_record(
        runtime.ledger,
        "memories",
        "beta",
        {
            "key": "beta",
            "title": "Beta",
            "project": "Engram",
            "status": "active",
            "canonical": True,
        },
    )
    upsert_record(
        runtime.ledger,
        "chunks",
        "beta:chunk:0",
        {
            "chunk_record_id": "beta:chunk:0",
            "memory_key": "beta",
            "chunk_id": 0,
            "text": "Beta was written outside retrieval indexing.",
            "metadata": {"project": "Engram", "text_hash": "sha256:beta"},
        },
    )

    status = runtime.status()

    state = status["components"]["retrieval"]["state"]
    assert state["status"] == "needs_rebuild"
    assert state["ready"] is False
    assert "indexed_count" in state["diagnostics"]["mismatches"]
    assert runtime.retrieval_ready is False


def test_memory_os_runtime_repairs_graph_edge_ref_identities(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()
    upsert_record(
        runtime.ledger,
        "graph_edges",
        "edge:structural",
        {
            "edge_id": "edge:structural",
            "from_ref": {"kind": "document", "document_id": "doc_design"},
            "to_ref": {
                "kind": "chunk",
                "document_id": "doc_design",
                "chunk_id": 10000,
                "chunk_record_id": "doc_design:chunk:10000",
            },
            "edge_type": "contains",
            "confidence": 1.0,
            "evidence": "Document contains chunk.",
            "source": "document_ingestion.structural",
            "status": "active",
            "created_by": "agent",
            "created_at": "2026-05-14T00:00:00+00:00",
            "updated_at": "2026-05-14T00:00:00+00:00",
        },
    )

    prepared = runtime.repair_graph_edge_refs(source="document_ingestion.structural")
    denied = runtime.repair_graph_edge_refs(source="document_ingestion.structural", accept=True)
    repaired = runtime.repair_graph_edge_refs(
        source="document_ingestion.structural",
        accept=True,
        approved_by="agent-review",
    )
    replay = runtime.repair_graph_edge_refs(source="document_ingestion.structural")

    assert prepared["status"] == "prepared"
    assert prepared["candidate_count"] == 1
    assert prepared["write_performed"] is False
    assert denied["status"] == "policy_denied"
    assert repaired["status"] == "ok"
    assert repaired["repaired_count"] == 1
    assert repaired["remaining_missing_identity_count"] == 0
    edge = read_record(runtime.ledger, "graph_edges", "edge:structural")
    assert edge["from_ref"]["key"] == "doc_design"
    assert edge["to_ref"]["key"] == "doc_design:chunk:10000"
    assert edge["repaired_by"] == "agent-review"
    assert replay["status"] == "noop"


def test_memory_os_runtime_repairs_concept_and_entity_ref_identities(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()
    upsert_record(
        runtime.ledger,
        "graph_edges",
        "edge:concept",
        {
            "edge_id": "edge:concept",
            "from_ref": {"kind": "concept", "concept_id": "concept:affordance"},
            "to_ref": {"kind": "entity", "entity_id": "entity:book"},
            "edge_type": "applies_to",
            "confidence": 1.0,
            "evidence": "Concept applies to entity.",
            "source": "document_intelligence.auto_graph",
            "status": "active",
            "created_by": "agent",
            "created_at": "2026-05-14T00:00:00+00:00",
            "updated_at": "2026-05-14T00:00:00+00:00",
        },
    )

    repaired = runtime.repair_graph_edge_refs(
        source="document_intelligence.auto_graph",
        accept=True,
        approved_by="agent-review",
    )

    edge = read_record(runtime.ledger, "graph_edges", "edge:concept")
    assert repaired["status"] == "ok"
    assert repaired["remaining_missing_identity_count"] == 0
    assert edge["from_ref"]["key"] == "concept:affordance"
    assert edge["to_ref"]["key"] == "entity:book"


def test_memory_os_runtime_repairs_graph_store_reconciliation_from_ledger(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()
    edge = {
        "edge_id": "edge:ledger-only",
        "from_ref": {"kind": "memory", "key": "memory_alpha"},
        "to_ref": {"kind": "concept", "key": "concept_beta"},
        "edge_type": "mentions",
        "confidence": 1.0,
        "evidence": "Ledger edge should be replayed exactly.",
        "source": "memory_metadata_graphing",
        "status": "active",
        "created_by": "agent",
        "created_at": "2026-05-14T00:00:00+00:00",
        "updated_at": "2026-05-14T00:00:00+00:00",
    }
    upsert_record(runtime.ledger, "graph_edges", edge["edge_id"], edge)

    repaired = runtime.repair_graph_store_reconciliation(
        accept=True,
        approved_by="agent-review",
    )

    assert repaired["status"] == "ok"
    assert repaired["repaired_count"] == 1
    assert repaired["after"]["status"] == "reconciled"
    assert repaired["transaction_receipt"]["operation_kind"] == "repair_graph_store_reconciliation"
    assert runtime.graph.load_edges() == [edge]


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


def test_memory_os_runtime_rejects_oversized_direct_memory_before_writes(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()

    with pytest.raises(ValueError, match="direct memory limit"):
        runtime.store_memory(
            key="oversized_direct_memory",
            content="x" * (MAX_DIRECT_MEMORY_CHARS + 1),
            title="Oversized Direct Memory",
        )

    memory = runtime.retrieve_memory("oversized_direct_memory")

    assert memory["found"] is False
    assert read_record(runtime.ledger, "memories", "oversized_direct_memory") is None
    assert list_records(runtime.ledger, "chunks") == []


def test_store_memory_marks_retrieval_failure_as_repair_pending(tmp_path):
    index = FailingUpsertVectorIndex()
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=index,
    )
    runtime.initialize()
    index.fail_upserts = True

    result = runtime.store_memory(
        key="retrieval_failure_memory",
        content="# Retrieval Failure\n\nThis should degrade instead of looking clean.",
        title="Retrieval Failure Memory",
    )
    memory = read_record(runtime.ledger, "memories", "retrieval_failure_memory")
    chunks = list_records(runtime.ledger, "chunks")
    transactions = list_records(runtime.ledger, "transactions")

    assert result["write_degraded"] is True
    assert result["error"]["failed_gate"] == "retrieval"
    assert result["write_state"] == "repair_pending"
    assert result["retrieval_state"] == "repair_pending"
    assert result["graph_state"] == "not_attempted"
    assert memory["repair_required"] is True
    assert memory["last_error"]["exception_type"] == "RuntimeError"
    assert chunks and all(chunk["write_state"] == "repair_pending" for chunk in chunks)
    assert transactions[-1]["status"] == "degraded"
    assert transactions[-1]["repair_required"] is True
    assert transactions[-1]["failed_gate"] == "retrieval"


def test_store_memory_marks_graph_failure_as_repair_pending_but_searchable(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
        graph_store=FailingGraphStore(),
    )
    runtime.initialize()

    result = runtime.store_memory(
        key="graph_failure_memory",
        content="# Graph Failure\n\nVisual hierarchy should still be searchable.",
        title="Graph Failure Memory",
        project="Engram",
    )
    search = runtime.search_memories("visual hierarchy", project="Engram")
    memory = read_record(runtime.ledger, "memories", "graph_failure_memory")
    graph_edges = list_records(runtime.ledger, "graph_edges")
    concepts = list_records(runtime.ledger, "concepts")
    entities = list_records(runtime.ledger, "entities")
    transactions = list_records(runtime.ledger, "transactions")

    assert result["write_degraded"] is True
    assert result["error"]["failed_gate"] == "metadata_graph"
    assert result["retrieval_state"] == "indexed"
    assert result["graph_state"] == "repair_pending"
    assert memory["repair_required"] is True
    assert search["results"][0]["key"] == "graph_failure_memory"
    assert graph_edges == []
    assert concepts == []
    assert entities == []
    assert transactions[-1]["status"] == "degraded"
    assert transactions[-1]["failed_gate"] == "metadata_graph"


def test_promoted_store_memory_replay_does_not_degrade_on_later_retrieval_failure(tmp_path):
    index = FailingUpsertVectorIndex()
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=index,
    )
    runtime.initialize()
    first = runtime.store_memory(
        key="stable_replay_memory",
        content="# Stable Replay\n\nVisual hierarchy remains complete.",
        title="Stable Replay Memory",
        force=True,
    )
    index.fail_upserts = True

    second = runtime.store_memory(
        key="stable_replay_memory",
        content="# Stable Replay\n\nVisual hierarchy remains complete.",
        title="Stable Replay Memory",
        force=True,
    )
    memory = read_record(runtime.ledger, "memories", "stable_replay_memory")
    transactions = list_records(runtime.ledger, "transactions")

    assert second["idempotent_replay"] is True
    assert second["transaction_id"] == first["transaction_id"]
    assert second["write_state"] == "complete"
    assert memory["write_state"] == "complete"
    assert memory["repair_required"] is False
    assert len(transactions) == 1
    assert transactions[0]["status"] == "promoted"


def test_legacy_promoted_store_memory_replay_without_state_runs_gates_and_degrades_on_failure(tmp_path):
    index = FailingUpsertVectorIndex()
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=index,
    )
    runtime.initialize()
    first = runtime.store_memory(
        key="legacy_replay_memory",
        content="# Legacy Replay\n\nVisual hierarchy remains complete.",
        title="Legacy Replay Memory",
        force=True,
    )
    legacy_memory = read_record(runtime.ledger, "memories", "legacy_replay_memory")
    for field in ("write_state", "retrieval_state", "graph_state", "repair_required"):
        legacy_memory.pop(field, None)
    upsert_record(runtime.ledger, "memories", "legacy_replay_memory", legacy_memory)
    for chunk in list_records(runtime.ledger, "chunks"):
        if chunk.get("memory_key") == "legacy_replay_memory":
            for field in ("write_state", "retrieval_state", "graph_state", "repair_required"):
                chunk.pop(field, None)
            upsert_record(runtime.ledger, "chunks", chunk["chunk_record_id"], chunk)
    index.fail_upserts = True

    second = runtime.store_memory(
        key="legacy_replay_memory",
        content="# Legacy Replay\n\nVisual hierarchy remains complete.",
        title="Legacy Replay Memory",
        force=True,
    )
    memory = read_record(runtime.ledger, "memories", "legacy_replay_memory")
    chunks = [
        chunk
        for chunk in list_records(runtime.ledger, "chunks")
        if chunk.get("memory_key") == "legacy_replay_memory"
    ]
    transactions = list_records(runtime.ledger, "transactions")

    assert second["write_degraded"] is True
    assert second["transaction_id"] != first["transaction_id"]
    assert second["transaction_receipt"]["status"] == "degraded"
    assert second["transaction_receipt"]["original_promoted_transaction_id"] == first["transaction_id"]
    assert memory["write_state"] == "repair_pending"
    assert memory["retrieval_state"] == "repair_pending"
    assert memory["graph_state"] == "not_attempted"
    assert memory["repair_required"] is True
    assert chunks and all(chunk["write_state"] == "repair_pending" for chunk in chunks)
    assert {transaction["status"] for transaction in transactions} == {"promoted", "degraded"}


def test_legacy_promoted_store_memory_degraded_child_is_repaired_on_successful_retry(tmp_path):
    index = FailingUpsertVectorIndex()
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=index,
    )
    runtime.initialize()
    first = runtime.store_memory(
        key="legacy_repair_memory",
        content="# Legacy Repair\n\nVisual hierarchy becomes repairable.",
        title="Legacy Repair Memory",
        force=True,
    )
    legacy_memory = read_record(runtime.ledger, "memories", "legacy_repair_memory")
    for field in ("write_state", "retrieval_state", "graph_state", "repair_required"):
        legacy_memory.pop(field, None)
    upsert_record(runtime.ledger, "memories", "legacy_repair_memory", legacy_memory)
    for chunk in list_records(runtime.ledger, "chunks"):
        if chunk.get("memory_key") == "legacy_repair_memory":
            for field in ("write_state", "retrieval_state", "graph_state", "repair_required"):
                chunk.pop(field, None)
            upsert_record(runtime.ledger, "chunks", chunk["chunk_record_id"], chunk)

    index.fail_upserts = True
    degraded = runtime.store_memory(
        key="legacy_repair_memory",
        content="# Legacy Repair\n\nVisual hierarchy becomes repairable.",
        title="Legacy Repair Memory",
        force=True,
    )
    index.fail_upserts = False
    repaired = runtime.store_memory(
        key="legacy_repair_memory",
        content="# Legacy Repair\n\nVisual hierarchy becomes repairable.",
        title="Legacy Repair Memory",
        force=True,
    )
    memory = read_record(runtime.ledger, "memories", "legacy_repair_memory")
    transactions = list_records(runtime.ledger, "transactions")
    by_status = {transaction["status"]: transaction for transaction in transactions}

    assert degraded["transaction_receipt"]["status"] == "degraded"
    assert degraded["transaction_receipt"]["original_promoted_transaction_id"] == first["transaction_id"]
    assert repaired["transaction_id"] == first["transaction_id"]
    assert repaired["write_state"] == "complete"
    assert memory["write_state"] == "complete"
    assert memory["repair_required"] is False
    assert by_status["promoted"]["transaction_id"] == first["transaction_id"]
    assert by_status["repaired"]["transaction_id"] == degraded["transaction_id"]
    assert by_status["repaired"]["repair_required"] is False
    assert by_status["repaired"]["repaired_by_transaction_id"] == first["transaction_id"]


def test_complete_replay_repairs_lingering_degraded_child_transaction(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()
    first = runtime.store_memory(
        key="complete_child_repair_memory",
        content="# Complete Child Repair\n\nVisual hierarchy is already complete.",
        title="Complete Child Repair Memory",
        force=True,
    )
    promoted = next(
        transaction
        for transaction in list_records(runtime.ledger, "transactions")
        if transaction["transaction_id"] == first["transaction_id"]
    )
    degraded = runtime.transactions.degraded(
        operation_kind="store_memory",
        proposed_writes=[{"table": "memories", "id": "complete_child_repair_memory"}],
        idempotency_key=promoted["idempotency_key"],
        affected_refs=[{"kind": "memory", "key": "complete_child_repair_memory"}],
        failed_gate="retrieval",
        error={"code": "memory_write_degraded", "message": "interrupted repair"},
        repair_guidance="retry store_memory",
    )

    replay = runtime.store_memory(
        key="complete_child_repair_memory",
        content="# Complete Child Repair\n\nVisual hierarchy is already complete.",
        title="Complete Child Repair Memory",
        force=True,
    )
    transactions = list_records(runtime.ledger, "transactions")
    by_status = {transaction["status"]: transaction for transaction in transactions}

    assert replay["idempotent_replay"] is True
    assert replay["transaction_id"] == first["transaction_id"]
    assert replay["transaction_receipt"]["repaired_degraded_transaction_ids"] == [
        degraded["transaction_id"]
    ]
    assert by_status["promoted"]["transaction_id"] == first["transaction_id"]
    assert by_status["repaired"]["transaction_id"] == degraded["transaction_id"]
    assert by_status["repaired"]["repair_required"] is False
    assert by_status["repaired"]["repaired_by_transaction_id"] == first["transaction_id"]


def test_same_content_metadata_replay_updates_current_state_instead_of_fast_path(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()
    first = runtime.store_memory(
        key="metadata_replay_memory",
        content="# Metadata Replay\n\nVisual hierarchy is unchanged.",
        title="Title A",
        tags=["alpha"],
        force=True,
    )
    second = runtime.store_memory(
        key="metadata_replay_memory",
        content="# Metadata Replay\n\nVisual hierarchy is unchanged.",
        title="Title B",
        tags=["beta"],
        force=True,
    )
    third = runtime.store_memory(
        key="metadata_replay_memory",
        content="# Metadata Replay\n\nVisual hierarchy is unchanged.",
        title="Title A",
        tags=["alpha"],
        force=True,
    )
    memory = read_record(runtime.ledger, "memories", "metadata_replay_memory")

    assert first["transaction_id"] != second["transaction_id"]
    assert third["transaction_id"] == first["transaction_id"]
    assert third.get("idempotent_replay") is not True
    assert third["title"] == "Title A"
    assert third["tags"] == ["alpha"]
    assert memory["title"] == "Title A"
    assert memory["tags"] == ["alpha"]
    assert memory["write_state"] == "complete"


def test_promoted_store_memory_replay_does_not_degrade_on_later_graph_failure(tmp_path):
    graph_store = ToggleFailingGraphStore()
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
        graph_store=graph_store,
    )
    runtime.initialize()
    first = runtime.store_memory(
        key="stable_graph_replay_memory",
        content="# Stable Graph Replay\n\nVisual hierarchy remains complete.",
        title="Stable Graph Replay Memory",
        project="Engram",
        force=True,
    )
    graph_store.fail = True

    second = runtime.store_memory(
        key="stable_graph_replay_memory",
        content="# Stable Graph Replay\n\nVisual hierarchy remains complete.",
        title="Stable Graph Replay Memory",
        project="Engram",
        force=True,
    )
    memory = read_record(runtime.ledger, "memories", "stable_graph_replay_memory")
    transactions = list_records(runtime.ledger, "transactions")

    assert second["idempotent_replay"] is True
    assert second["transaction_id"] == first["transaction_id"]
    assert second["write_state"] == "complete"
    assert memory["graph_state"] == "complete"
    assert memory["repair_required"] is False
    assert len(transactions) == 1
    assert transactions[0]["status"] == "promoted"


def test_memory_os_runtime_retrieves_windowed_document_chunk_by_document_and_global_chunk_id(tmp_path):
    from core.memory_os.document_pipeline import DocumentPipeline

    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=lambda text: [0.0],
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()
    pipeline = DocumentPipeline(runtime.ledger, runtime.content_store)

    pipeline.materialize_document_job(
        {
            "document": {
                "document_id": "doc_windowed_book",
                "title": "Windowed Book",
                "page_count": 2,
                "page_range": {"start": 2, "end": 2},
            },
            "source": {"source_uri": "file:///book.pdf", "content_hash": "sha256:book"},
            "pages": [
                {"page_number": 2, "text_status": "text", "visual_review_needed": False},
            ],
            "text": {"content": "# Window Two\n\nBeta page text."},
            "quality_seed": {"text_pages": [2], "visual_review_needed_pages": []},
        },
        ingestion_id="ingest-book",
        window_index=1,
    )

    chunk = runtime.retrieve_chunk("doc_windowed_book", 20000)

    assert chunk["found"] is True
    assert chunk["chunk_id"] == 20000
    assert chunk["chunk"]["text"] == "# Window Two\n\nBeta page text."


def test_memory_os_runtime_retrieves_document_chunk_without_scan(tmp_path, monkeypatch):
    from core.memory_os.document_pipeline import DocumentPipeline

    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=lambda text: [0.0],
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()
    pipeline = DocumentPipeline(runtime.ledger, runtime.content_store)
    pipeline.materialize_document_job(
        {
            "document": {
                "document_id": "doc_direct_lookup",
                "title": "Direct Lookup",
                "page_count": 3,
                "page_range": {"start": 3, "end": 3},
            },
            "source": {"source_uri": "file:///book.pdf", "content_hash": "sha256:book"},
            "pages": [{"page_number": 3, "text_status": "text", "visual_review_needed": False}],
            "text": {"content": "# Window Three\n\nGamma page text."},
            "quality_seed": {"text_pages": [3], "visual_review_needed_pages": []},
        },
        ingestion_id="ingest-direct",
        window_index=2,
    )

    def fail_list_records(*args, **kwargs):
        raise AssertionError("retrieve_chunk should not scan all chunks")

    monkeypatch.setattr("core.memory_os.runtime.list_records", fail_list_records)

    chunk = runtime.retrieve_chunk("doc_direct_lookup", 30000)

    assert chunk["found"] is True
    assert chunk["chunk_id"] == 30000
    assert chunk["chunk"]["text"] == "# Window Three\n\nGamma page text."


def test_memory_os_runtime_retrieves_custom_memory_chunk_without_scan(tmp_path, monkeypatch):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=lambda text: [0.0],
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()
    upsert_record(
        runtime.ledger,
        "chunks",
        "custom-alpha-window:chunk:0",
        {
            "chunk_record_id": "custom-alpha-window:chunk:0",
            "memory_key": "custom_alpha",
            "document_id": "custom-alpha-window",
            "chunk_id": 0,
            "title": "Custom Alpha",
            "text": "Custom alpha text.",
            "heading_path": [],
            "chunk_kind": "paragraph",
        },
    )

    def fail_list_records(*args, **kwargs):
        raise AssertionError("retrieve_chunk should not scan all chunks")

    monkeypatch.setattr("core.memory_os.runtime.list_records", fail_list_records)

    chunk = runtime.retrieve_chunk("custom_alpha", 0)

    assert chunk["found"] is True
    assert chunk["chunk"]["text"] == "Custom alpha text."


def test_memory_os_runtime_prepares_and_applies_legacy_migration_with_review_gate(tmp_path):
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    (legacy_dir / "alpha.json").write_text(
        """
        {
          "key": "alpha",
          "title": "Alpha",
          "content": "# Alpha\\n\\nVisual hierarchy belongs in the migration corpus.",
          "tags": ["legacy"],
          "project": "Engram",
          "status": "active",
          "related_to": ["beta"],
          "chunk_count": 1
        }
        """,
        encoding="utf-8",
    )
    (legacy_dir / "beta.json").write_text(
        """
        {
          "key": "beta",
          "title": "Beta",
          "content": "Daemon smoke import target.",
          "status": "draft",
          "chunk_count": 1
        }
        """,
        encoding="utf-8",
    )
    memory_os_root = tmp_path / "memory_os"
    memory_os_root.mkdir()
    runtime = MemoryOSRuntime(
        memory_os_root,
        embed_text=_embed,
        vector_index=RecordingVectorIndex(),
    )
    runtime.initialize()

    prepared = runtime.prepare_legacy_memory_os_migration(legacy_dir=legacy_dir)
    prepared_memories = list_records(runtime.ledger, "memories")
    prepared_receipt = read_record(runtime.ledger, "transactions", prepared["prepared_transaction_id"])
    denied = runtime.apply_legacy_memory_os_migration(
        legacy_dir=legacy_dir,
        accept=False,
        approved_by="agent-review",
    )
    missing_reviewer = runtime.apply_legacy_memory_os_migration(
        legacy_dir=legacy_dir,
        accept=True,
        approved_by="",
    )
    applied = runtime.apply_legacy_memory_os_migration(
        legacy_dir=legacy_dir,
        accept=True,
        approved_by="agent-review",
    )
    replayed = runtime.apply_legacy_memory_os_migration(
        legacy_dir=legacy_dir,
        accept=True,
        approved_by="agent-review",
    )
    alpha = read_record(runtime.ledger, "memories", "alpha")
    beta = read_record(runtime.ledger, "memories", "beta")
    source = read_record(runtime.ledger, "sources", "legacy_memory:alpha")
    search = runtime.search_memories("visual hierarchy", project="Engram")

    assert prepared["write_performed"] is False
    assert prepared["active_memory_write_performed"] is False
    assert prepared["graph_write_performed"] is False
    assert prepared["would_import_count"] == 2
    assert prepared["prepared_transaction_id"].startswith("txn:")
    assert prepared_receipt["status"] == "dry_run"
    assert prepared_receipt["write_performed"] is False
    assert prepared_memories == []
    assert denied["status"] == "policy_denied"
    assert denied["write_performed"] is False
    assert missing_reviewer["status"] == "policy_denied"
    assert applied["status"] == "ok"
    assert applied["write_performed"] is True
    assert applied["active_memory_write_performed"] is True
    assert applied["graph_write_performed"] is False
    assert applied["imported_count"] == 2
    assert applied["changed_count"] == 2
    assert applied["replayed_count"] == 0
    assert applied["idempotent_replay"] is False
    assert alpha["legacy_import"]["legacy_filename"] == "alpha.json"
    assert alpha["legacy_import"]["raw_artifact_id"].endswith(".legacy.json")
    assert beta["status"] == "draft"
    assert source["memory_key"] == "alpha"
    assert source["source_type"] == "legacy_memory_json"
    assert search["results"][0]["key"] == "alpha"
    assert replayed["status"] == "ok"
    assert replayed["write_performed"] is False
    assert replayed["changed_count"] == 0
    assert replayed["replayed_count"] == 2
    assert replayed["idempotent_replay"] is True


def test_memory_os_search_project_filter_resolves_path_aliases(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=RecordingVectorIndex(),
    )
    runtime.initialize()
    runtime.store_memory(
        key="engram_label",
        content="Visual hierarchy belongs to Engram.",
        project="Engram",
        status="active",
        title="Engram Label",
    )
    runtime.store_memory(
        key="windows_label",
        content="Visual hierarchy also belongs to the Windows path.",
        project="C:\\Dev\\Engram",
        status="active",
        title="Windows Label",
    )
    runtime.store_memory(
        key="slash_label",
        content="Visual hierarchy also belongs to the slash path.",
        project="C:/Dev/Engram",
        status="active",
        title="Slash Label",
    )
    runtime.store_memory(
        key="other_project",
        content="Visual hierarchy for another project.",
        project="Other",
        status="active",
        title="Other",
    )

    aliased = runtime.search_memories("visual hierarchy", project="Engram", limit=10)
    exact = runtime.search_memories(
        "visual hierarchy",
        project="Engram",
        exact_project_match=True,
        limit=10,
    )

    assert {result["key"] for result in aliased["results"]} == {
        "engram_label",
        "windows_label",
        "slash_label",
    }
    assert [result["key"] for result in exact["results"]] == ["engram_label"]


def test_memory_os_store_memory_updates_retrieval_incrementally(tmp_path):
    index = RecordingVectorIndex()
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=index,
    )
    runtime.initialize()

    runtime.store_memory(
        key="incremental_alpha",
        content="# Incremental\n\nDaemon smoke should index one changed memory.",
        title="Incremental Alpha",
        tags=["daemon"],
        project="Engram",
        domain="daemon",
    )
    search = runtime.search_memories("daemon smoke", project="Engram", domain="daemon")

    assert index.rebuild_calls == 1
    assert index.deleted_parent_keys == ["incremental_alpha"]
    assert index.upsert_calls >= 2
    assert search["results"][0]["key"] == "incremental_alpha"


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


def test_memory_os_runtime_query_knowledge_returns_project_capsule_response(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()
    runtime.store_memory(
        key="engram_runtime_direction",
        content="# Summary\n\nEngram uses a daemon-owned Memory OS runtime.",
        title="Runtime Direction",
        project="Engram",
        tags=["reviewed", "decision"],
    )

    response = runtime.query_knowledge(
        {
            "request_id": "req-runtime",
            "ask": {
                "goal": "Get current project context.",
                "task_type": "project_orientation",
                "project": "Engram",
                "focus": ["runtime"],
            },
        }
    )

    assert response["contract_version"] == "engram.knowledge.response.v0"
    assert response["request_id"] == "req-runtime"
    assert response["status"] == "ok"
    assert response["answer"]["project"] == "Engram"
    assert "daemon-owned Memory OS runtime" in response["answer"]["summary"]
    assert response["citations"]
    assert response["budget_used"]["artifacts_built"] == 1
    assert response["budget_used"]["artifacts_read"] == 0
    assert response["planner"]["budget"]["requested"]["max_source_reads"] == 12
    assert response["planner"]["budget"]["used"]["artifacts_built"] == 1
    assert response["planner"]["strategy"] == "project_orientation"
    assert response["planner"]["failure_receipts"] == []
    assert response["policy"]["unsupported_inferences_used"] is False
    assert response["policy"]["review_state_available"] is False
    assert response["policy"]["review_filter_enforced"] is False
    assert response["policy"]["review_state_basis"] == "not_available_in_current_memory_os_records"


def test_memory_os_runtime_query_knowledge_focus_ranks_newer_full_text_context(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()
    runtime.store_memory(
        key="aaa_old_ekc_plan",
        content=(
            "# Summary\n\n"
            "Old EKC query_knowledge stable eval pack planning note. "
            "It contains the same focus terms but should not outrank fresher implementation evidence."
        ),
        title="Old EKC Plan",
        project="Engram",
        domain="planning",
        tags=["ekc", "query_knowledge", "stable eval pack"],
    )
    filler = " ".join(["context"] * 80)
    runtime.store_memory(
        key="zzz_current_ekc_slice",
        content=(
            "# Summary\n\n"
            "Current EKC query_knowledge stable eval pack implementation note. "
            f"{filler} "
            "Full-text marker: the stable eval pack now validates the whole EKC workflow."
        ),
        title="Current EKC Slice",
        project="Engram",
        domain="implementation",
        tags=["ekc", "query_knowledge", "stable eval pack"],
    )
    old_chunk = read_record(runtime.ledger, "chunks", "aaa_old_ekc_plan:chunk:0")
    current_chunk = read_record(runtime.ledger, "chunks", "zzz_current_ekc_slice:chunk:0")
    upsert_record(
        runtime.ledger,
        "chunks",
        "aaa_old_ekc_plan:chunk:0",
        {**old_chunk, "updated_at": "2026-05-13T00:00:00+00:00"},
    )
    upsert_record(
        runtime.ledger,
        "chunks",
        "zzz_current_ekc_slice:chunk:0",
        {**current_chunk, "updated_at": "2026-05-14T00:00:00+00:00"},
    )

    response = runtime.query_knowledge(
        {
            "request_id": "req-current-ekc",
            "ask": {
                "goal": "Orient me to the EKC stable eval work.",
                "task_type": "project_orientation",
                "project": "Engram",
                "focus": ["query_knowledge", "stable eval pack"],
            },
        }
    )

    assert response["status"] == "ok"
    assert response["citations"][0]["key"] == "zzz_current_ekc_slice"
    assert "Full-text marker" in response["answer"]["summary"]


def test_memory_os_runtime_query_knowledge_accepts_reviewed_source_statuses(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()
    runtime.store_memory(
        key="engram_accepted_direction",
        content="# Summary\n\nAccepted reviewed evidence is eligible for EKC project orientation.",
        title="Accepted Direction",
        project="Engram",
        status="accepted",
        tags=["reviewed", "decision"],
    )

    response = runtime.query_knowledge(
        {
            "request_id": "req-accepted-source",
            "ask": {
                "goal": "Get current project context.",
                "task_type": "project_orientation",
                "project": "Engram",
                "focus": ["reviewed"],
            },
        }
    )

    assert response["status"] == "ok"
    assert response["citations"][0]["key"] == "engram_accepted_direction"
    assert "Accepted reviewed evidence" in response["answer"]["summary"]


def test_memory_os_runtime_materializes_and_reads_persisted_project_capsule(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()
    runtime.store_memory(
        key="engram_persisted_direction",
        content="# Summary\n\nEngram persists reviewed project capsule artifacts.",
        title="Persisted Direction",
        project="Engram",
        tags=["reviewed", "decision"],
    )
    request = {
        "request_id": "req-materialize",
        "ask": {
            "goal": "Get current project context.",
            "task_type": "project_orientation",
            "project": "Engram",
            "focus": ["persistence"],
        },
    }

    materialized = runtime.materialize_project_capsule_artifact(request)
    response = runtime.query_knowledge(request)
    inspector = runtime.inspector()

    assert materialized["write_performed"] is True
    assert materialized["transaction_id"].startswith("txn:")
    assert materialized["artifact_record"]["artifact_type"] == "project_capsule"
    assert response["status"] == "ok"
    assert response["answer"]["summary"] == "Engram persists reviewed project capsule artifacts."
    assert response["budget_used"]["artifacts_read"] == 1
    assert response["budget_used"]["artifacts_built"] == 0
    assert response["budget_used"]["source_reads"] == 0
    assert response["freshness"]["artifact_id"] == materialized["artifact_record"]["artifact_id"]
    assert response["citations"][0]["level"] == "artifact"
    assert response["citations"][0]["artifact_id"] == materialized["artifact_record"]["artifact_id"]
    assert any(citation.get("level") == "chunk" for citation in response["citations"])
    assert "persisted_artifact" in response["planner"]["methods_used"]
    assert response["planner"]["budget"]["used"]["artifacts_read"] == 1
    assert inspector["summary"]["knowledge_artifact_count"] == 1
    assert inspector["knowledge_artifacts"]["items"][0]["artifact_id"] == materialized["artifact_record"]["artifact_id"]


def test_memory_os_runtime_query_knowledge_no_answer_has_failure_receipt(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()

    response = runtime.query_knowledge(
        {
            "request_id": "req-no-answer",
            "ask": {
                "goal": "Get current project context.",
                "task_type": "project_orientation",
                "project": "Engram",
            },
        }
    )

    assert response["status"] == "no_answer"
    assert response["planner"]["strategy"] == "project_orientation"
    assert response["planner"]["budget"]["requested"]["max_artifacts"] == 1
    assert response["planner"]["failure_receipts"] == [
        {
            "code": "no_project_sources",
            "category": "grounding",
            "message": "No eligible project sources found for Engram.",
            "recoverable": True,
        }
    ]


def test_memory_os_runtime_query_knowledge_returns_source_orientation(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()
    upsert_record(
        runtime.ledger,
        "sources",
        "source-design",
        {
            "source_uri": "file:///books/design.pdf",
            "source_type": "pdf",
            "project": "Engram",
        },
    )
    upsert_record(
        runtime.ledger,
        "documents",
        "doc_design",
        {
            "document_id": "doc_design",
            "title": "Design Book",
            "project": "Engram",
            "source_ref": {"source_uri": "file:///books/design.pdf", "source_type": "pdf"},
            "document": {"page_count": 3},
        },
    )

    response = runtime.query_knowledge(
        {
            "request_id": "req-source-orientation",
            "ask": {
                "goal": "Orient me to the source.",
                "task_type": "source_orientation",
                "project": "Engram",
                "focus": ["design"],
            },
        }
    )

    assert response["status"] == "partial"
    assert response["answer"]["orientation_type"] == "source_orientation"
    assert response["answer"]["documents"][0]["document_id"] == "doc_design"
    assert response["errors"][0]["code"] == "orientation_incomplete"
    assert response["citations"][0]["level"] == "document"
    assert response["budget_used"]["artifacts_built"] == 0
    assert response["planner"]["strategy"] == "source_orientation"


def test_memory_os_runtime_query_knowledge_returns_review_preparation(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()
    upsert_record(
        runtime.ledger,
        "documents",
        "doc_review",
        {
            "document_id": "doc_review",
            "title": "Review Doc",
            "project": "Engram",
            "source_ref": {"source_uri": "file:///docs/review.md"},
        },
    )
    upsert_record(
        runtime.ledger,
        "drafts",
        "draft:doc_review",
        {
            "draft_id": "draft:doc_review",
            "record_type": "document_draft",
            "document_id": "doc_review",
            "project": "Engram",
            "promotion_required": True,
            "proposed_memories": [{"key": "review_memory"}],
        },
    )
    before_memory_count = len(list_records(runtime.ledger, "memories"))

    response = runtime.query_knowledge(
        {
            "request_id": "req-review-prep",
            "ask": {
                "goal": "Prepare review packet.",
                "task_type": "review_preparation",
                "project": "Engram",
                "focus": ["review"],
            },
        }
    )

    after_memory_count = len(list_records(runtime.ledger, "memories"))
    assert response["status"] == "ok"
    assert response["answer"]["packet_type"] == "review_preparation"
    assert response["answer"]["review_items"][0]["draft_id"] == "draft:doc_review"
    assert response["answer"]["write_performed"] is False
    assert response["budget_used"]["artifacts_built"] == 0
    assert response["planner"]["strategy"] == "review_preparation"
    assert after_memory_count == before_memory_count


def test_memory_os_runtime_query_knowledge_returns_evidence_audit(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()
    upsert_record(
        runtime.ledger,
        "knowledge_artifacts",
        "artifact:stale",
        {
            "artifact_id": "artifact:stale",
            "artifact_type": "project_capsule",
            "artifact_version": "v0",
            "project": "Engram",
            "citations": [{"citation_id": "cit_bad"}],
            "staleness": {"state": "stale", "invalidated_by": ["newer_context"]},
        },
    )

    response = runtime.query_knowledge(
        {
            "request_id": "req-evidence-audit",
            "ask": {
                "goal": "Audit evidence.",
                "task_type": "evidence_audit",
                "project": "Engram",
            },
        }
    )

    assert response["status"] == "partial"
    assert response["answer"]["audit_type"] == "evidence_audit"
    assert response["answer"]["findings"][0]["code"] == "stale_artifact"
    assert response["planner"]["strategy"] == "evidence_audit"
    assert response["citations"][0]["level"] == "artifact"


def test_memory_os_runtime_query_knowledge_returns_graph_evidence(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()
    upsert_record(
        runtime.ledger,
        "graph_edges",
        "edge:contradicts",
        {
            "edge_id": "edge:contradicts",
            "from_ref": {"kind": "claim", "key": "new_claim"},
            "to_ref": {"kind": "claim", "key": "old_claim"},
            "edge_type": "contradicts",
            "confidence": 0.9,
            "evidence": "New claim contradicts old claim.",
            "source": "memory_os_test",
            "status": "active",
            "created_by": "agent",
            "created_at": "2026-05-14T00:00:00+00:00",
            "updated_at": "2026-05-14T00:00:00+00:00",
            "project": "Engram",
            "content": "Do not expose this body.",
        },
    )

    response = runtime.query_knowledge(
        {
            "request_id": "req-graph-evidence",
            "ask": {
                "goal": "Show bounded graph evidence.",
                "task_type": "graph_evidence",
                "project": "Engram",
                "focus": ["claim"],
            },
        }
    )

    assert response["status"] == "partial"
    assert response["answer"]["packet_type"] == "graph_evidence"
    assert response["answer"]["contradiction_count"] == 1
    assert "content" not in response["answer"]["evidence_paths"][0]["edges"][0]
    assert response["citations"][0]["level"] == "graph"
    assert response["planner"]["strategy"] == "graph_evidence"


def test_memory_os_runtime_query_knowledge_returns_implementation_context_artifact(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()
    upsert_record(
        runtime.ledger,
        "chunks",
        "impl:chunk:0",
        {
            "chunk_record_id": "impl:chunk:0",
            "memory_key": "impl_context",
            "document_id": "impl_context:chunk:0",
            "chunk_id": 0,
            "project": "Engram",
            "domain": "code",
            "text": "Use query_knowledge before implementation.",
        },
    )

    response = runtime.query_knowledge(
        {
            "request_id": "req-implementation-context",
            "ask": {
                "goal": "Build implementation context.",
                "task_type": "implementation_context",
                "project": "Engram",
                "focus": ["query_knowledge"],
            },
        }
    )

    assert response["status"] == "ok"
    assert response["answer"]["artifact_family"] == "implementation_context"
    assert response["answer"]["evidence_audit"]["required"] is False
    assert response["answer"]["items"][0]["key"] == "impl_context"
    assert response["citations"][0]["level"] == "chunk"
    assert response["planner"]["omissions"] == [
        {
            "code": "evidence_audit_unavailable",
            "message": "No artifact, coverage, or draft audit records matched this implementation_context request.",
        }
    ]
    assert response["errors"] == []
    assert response["planner"]["strategy"] == "implementation_context"


def test_memory_os_runtime_implementation_context_adds_ranked_brief(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()
    upsert_record(
        runtime.ledger,
        "chunks",
        "old_impl:chunk:0",
        {
            "chunk_record_id": "old_impl:chunk:0",
            "memory_key": "old_impl",
            "document_id": "old_impl:chunk:0",
            "chunk_id": 0,
            "project": "Engram",
            "domain": "planning",
            "updated_at": "2026-05-13T00:00:00+00:00",
            "text": "Earlier query_knowledge stable eval pack planning context.",
        },
    )
    upsert_record(
        runtime.ledger,
        "chunks",
        "current_impl:chunk:0",
        {
            "chunk_record_id": "current_impl:chunk:0",
            "memory_key": "current_impl",
            "document_id": "current_impl:chunk:0",
            "chunk_id": 0,
            "project": "Engram",
            "domain": "implementation",
            "updated_at": "2026-05-14T00:00:00+00:00",
            "text": (
                "Current implementation context for query_knowledge stable eval pack. "
                "Branch: codex/ekc-v0-contract. Keep the request/response envelope stable. "
                "Do not treat server.py/core/memory_manager.py as a real file path. "
                "Files changed: core/memory_os/runtime.py and tests/memory_os/test_runtime.py. "
                "Next recommended step: polish EKC ranking and implementation-context briefing."
            ),
        },
    )

    response = runtime.query_knowledge(
        {
            "request_id": "req-implementation-context-brief",
            "ask": {
                "goal": "Continue EKC implementation work.",
                "task_type": "implementation_context",
                "project": "Engram",
                "focus": ["query_knowledge", "stable eval pack"],
            },
        }
    )

    assert response["status"] == "ok"
    assert response["answer"]["items"][0]["key"] == "current_impl"
    assert response["answer"]["brief"]["summary"].startswith("Current implementation context")
    assert response["answer"]["brief"]["next_actions"] == [
        "polish EKC ranking and implementation-context briefing."
    ]
    assert response["answer"]["brief"]["relevant_files"] == [
        "core/memory_os/runtime.py",
        "tests/memory_os/test_runtime.py",
    ]


def test_memory_os_runtime_query_knowledge_returns_schema_failure(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()

    response = runtime.query_knowledge(
        {
            "request_id": "req-bad",
            "ask": {"task_type": "project_orientation"},
        }
    )

    assert response["status"] == "schema_failed"
    assert response["errors"][0]["code"] == "missing_project"
