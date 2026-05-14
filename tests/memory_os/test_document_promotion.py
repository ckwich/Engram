from core.document_intelligence import (
    prepare_document_draft,
    prepare_document_promotion_transaction,
    prepare_document_record,
)
from core.memory_os._records import list_records, read_record
from core.memory_os.document_promotion import apply_document_promotion_transaction
from core.memory_os.runtime import MemoryOSRuntime
from core.vector_index import InMemoryVectorIndex


def _embed(text):
    return [1.0, 0.0] if "promotion" in str(text).lower() else [0.0, 1.0]


def _runtime(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()
    return runtime


def _promotion_transaction():
    document = prepare_document_record(
        title="Promotion Note",
        source_uri="file:///docs/promotion.md",
        source_type="markdown",
        content_hash="sha256:" + "d" * 64,
        media_type="text/markdown",
        metadata={"project": "Engram", "domain": "architecture"},
    )
    draft = prepare_document_draft(
        document_record=document,
        analysis={"decisions": ["Promotion execution must be explicit and reviewed."]},
        candidate_graph_edges=[
            {
                "from_ref": {"kind": "document", "key": document["document_id"]},
                "to_ref": {"kind": "memory", "key": "engram_document_promotion"},
                "edge_type": "supports",
                "confidence": 0.88,
                "evidence": "The reviewed document supports explicit promotion execution.",
            }
        ],
        created_by="agent",
    )
    return prepare_document_promotion_transaction(
        document_draft=draft,
        selected_memory_indexes=[0],
        selected_edge_indexes=[0],
        approved_by="agent-review",
    )


def test_apply_document_promotion_requires_acceptance(tmp_path):
    runtime = _runtime(tmp_path)
    transaction = _promotion_transaction()

    result = apply_document_promotion_transaction(
        runtime.ledger,
        runtime,
        transaction,
        accept=False,
        approved_by="agent-review",
    )

    assert result["status"] == "policy_denied"
    assert result["error"]["code"] == "accept_required"
    assert result["write_performed"] is False
    assert result["active_memory_write_performed"] is False
    assert list_records(runtime.ledger, "memories") == []
    assert list_records(runtime.ledger, "graph_edges") == []


def test_apply_document_promotion_writes_selected_memory_only(tmp_path):
    runtime = _runtime(tmp_path)
    transaction = _promotion_transaction()

    result = apply_document_promotion_transaction(
        runtime.ledger,
        runtime,
        transaction,
        accept=True,
        approved_by="agent-review",
        selected_operation_indexes=[0],
    )

    memory_key = transaction["operations"][0]["payload"]["key"]
    assert result["status"] == "ok"
    assert result["write_performed"] is True
    assert result["active_memory_write_performed"] is True
    assert result["graph_write_performed"] is False
    assert result["memories_written"] == [memory_key]
    assert result["graph_edges_written"] == []
    stored = runtime.retrieve_memory(memory_key)
    assert stored["found"] is True
    assert stored["memory"]["status"] == "active"
    assert stored["memory"]["project"] == "Engram"
    assert "Promotion execution must be explicit" in stored["memory"]["content"]
    assert list_records(runtime.ledger, "graph_edges") == []


def test_apply_document_promotion_writes_graph_edges_through_graph_service(tmp_path):
    runtime = _runtime(tmp_path)
    transaction = _promotion_transaction()

    result = apply_document_promotion_transaction(
        runtime.ledger,
        runtime,
        transaction,
        accept=True,
        approved_by="agent-review",
        selected_operation_indexes=[1],
    )

    assert result["status"] == "ok"
    assert result["write_performed"] is True
    assert result["active_memory_write_performed"] is False
    assert result["graph_write_performed"] is True
    assert result["memories_written"] == []
    assert len(result["graph_edges_written"]) == 1
    edge = read_record(runtime.ledger, "graph_edges", result["graph_edges_written"][0])
    assert edge["edge_type"] == "supports"
    assert edge["status"] == "active"
    assert edge["created_by"] == "agent-review"
    assert edge["source"] == "document_intelligence"


def test_apply_document_promotion_is_idempotent(tmp_path):
    runtime = _runtime(tmp_path)
    transaction = _promotion_transaction()

    first = apply_document_promotion_transaction(
        runtime.ledger,
        runtime,
        transaction,
        accept=True,
        approved_by="agent-review",
    )
    memory_count = len(list_records(runtime.ledger, "memories"))
    graph_edge_count = len(list_records(runtime.ledger, "graph_edges"))
    transaction_count = len(list_records(runtime.ledger, "transactions"))
    second = apply_document_promotion_transaction(
        runtime.ledger,
        runtime,
        transaction,
        accept=True,
        approved_by="agent-review",
    )

    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert second["idempotent_replay"] is True
    assert second["memories_written"] == first["memories_written"]
    assert second["graph_edges_written"] == first["graph_edges_written"]
    assert len(list_records(runtime.ledger, "memories")) == memory_count
    assert len(list_records(runtime.ledger, "graph_edges")) == graph_edge_count
    assert len(list_records(runtime.ledger, "transactions")) == transaction_count


def test_apply_document_promotion_rejects_unsafe_or_missing_operations(tmp_path):
    runtime = _runtime(tmp_path)
    transaction = _promotion_transaction()

    missing = apply_document_promotion_transaction(
        runtime.ledger,
        runtime,
        {**transaction, "operations": []},
        accept=True,
        approved_by="agent-review",
    )
    unsafe = apply_document_promotion_transaction(
        runtime.ledger,
        runtime,
        {
            **transaction,
            "operations": [
                {"kind": "shell", "tool": "powershell", "payload": {"command": "echo no"}}
            ],
        },
        accept=True,
        approved_by="agent-review",
    )
    no_reviewer = apply_document_promotion_transaction(
        runtime.ledger,
        runtime,
        transaction,
        accept=True,
        approved_by="",
    )
    wrong_record = apply_document_promotion_transaction(
        runtime.ledger,
        runtime,
        {"record_type": "document_draft", "operations": transaction["operations"]},
        accept=True,
        approved_by="agent-review",
    )
    missing_memory_key = apply_document_promotion_transaction(
        runtime.ledger,
        runtime,
        {
            **transaction,
            "operations": [{"kind": "memory", "tool": "write_memory", "payload": {"content": "body"}}],
        },
        accept=True,
        approved_by="agent-review",
    )
    missing_edge_evidence = apply_document_promotion_transaction(
        runtime.ledger,
        runtime,
        {
            **transaction,
            "operations": [
                {
                    "kind": "graph_edge",
                    "tool": "add_graph_edge",
                    "payload": {
                        "from_ref": {"kind": "document", "key": "doc"},
                        "to_ref": {"kind": "memory", "key": "memory"},
                        "edge_type": "supports",
                    },
                }
            ],
        },
        accept=True,
        approved_by="agent-review",
    )

    assert missing["status"] == "schema_failed"
    assert missing["error"]["code"] == "operations_required"
    assert unsafe["status"] == "schema_failed"
    assert unsafe["error"]["code"] == "unsupported_operation_kind"
    assert no_reviewer["status"] == "schema_failed"
    assert no_reviewer["error"]["code"] == "approved_by_required"
    assert wrong_record["status"] == "schema_failed"
    assert wrong_record["error"]["code"] == "invalid_record_type"
    assert missing_memory_key["status"] == "schema_failed"
    assert missing_memory_key["error"]["code"] == "memory_payload_key_required"
    assert missing_edge_evidence["status"] == "schema_failed"
    assert missing_edge_evidence["error"]["code"] == "graph_edge_payload_evidence_required"
