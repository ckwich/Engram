from core.document_intelligence import (
    prepare_document_draft,
    prepare_document_promotion_transaction,
    prepare_document_record,
)
from core.graph_store import JsonGraphStore
from core.memory_os._records import list_records
from core.memory_os.document_promotion import apply_document_promotion_transaction
from core.memory_os.runtime import MemoryOSRuntime
from core.vector_index import InMemoryVectorIndex


def _runtime(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path / "memory_os",
        embed_text=lambda text: [1.0, 0.0] if str(text).strip() else [0.0, 1.0],
        vector_index=InMemoryVectorIndex(),
        graph_store=JsonGraphStore(tmp_path / "edges.json"),
    )
    runtime.initialize()
    return runtime


def _promotion_transaction(content: str, *, memory_type: str = "fact"):
    document = prepare_document_record(
        title="Guardrail Note",
        source_uri="file:///docs/guardrail.md",
        source_type="markdown",
        content_hash="sha256:" + "e" * 64,
        media_type="text/markdown",
        metadata={"project": "Engram", "domain": "security"},
    )
    draft = prepare_document_draft(
        document_record=document,
        analysis={"decisions": [content]},
        created_by="agent",
    )
    transaction = prepare_document_promotion_transaction(
        document_draft=draft,
        selected_memory_indexes=[0],
        selected_edge_indexes=[],
        approved_by="agent-review",
    )
    operation = transaction["operations"][0]
    operation["payload"]["content"] = content
    operation["payload"]["memory_type"] = memory_type
    return transaction


def test_document_promotion_blocks_secret_like_memory_without_partial_write(tmp_path):
    runtime = _runtime(tmp_path)
    transaction = _promotion_transaction("API_TOKEN=abc123")

    result = apply_document_promotion_transaction(
        runtime.ledger,
        runtime,
        transaction,
        accept=True,
        approved_by="agent-review",
    )

    assert result["status"] == "policy_denied"
    assert result["error"]["code"] == "memory_guardrail_blocked"
    assert result["write_performed"] is True
    assert result["active_memory_write_performed"] is False
    assert result["memories_written"] == []
    assert list_records(runtime.ledger, "memories") == []
    assert len(list_records(runtime.ledger, "memory_guardrail_receipts")) == 1


def test_document_promotion_allows_reviewed_uncited_document_claim(tmp_path):
    runtime = _runtime(tmp_path)
    transaction = _promotion_transaction(
        "The architecture requires sync.",
        memory_type="document_claim",
    )

    result = apply_document_promotion_transaction(
        runtime.ledger,
        runtime,
        transaction,
        accept=True,
        approved_by="agent-review",
    )

    assert result["status"] == "ok"
    assert result["active_memory_write_performed"] is True
    receipts = list_records(runtime.ledger, "memory_guardrail_receipts")
    assert receipts[0]["decision"] == "require_review"
    assert receipts[0]["reviewed_by"] == "agent-review"
