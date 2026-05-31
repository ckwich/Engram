from core.graph_store import JsonGraphStore
from core.memory_os._records import list_records, read_record
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


def _mergeable_pr(runtime, operation):
    service = runtime.knowledge_prs
    branch = service.prepare_knowledge_branch(name="Guardrail Proposal")
    pr = service.prepare_knowledge_pr(
        branch_id=branch["branch_id"],
        title="Guardrail proposal",
        proposed_operations=[operation],
    )
    ci = service.run_memory_ci(knowledge_pr_id=pr["knowledge_pr_id"])
    assert ci["status"] == "passed"
    return pr


def test_knowledge_pr_merge_blocks_secret_like_memory_without_partial_write(tmp_path):
    runtime = _runtime(tmp_path)
    pr = _mergeable_pr(
        runtime,
        {
            "operation_id": "op:memory:secret",
            "operation_kind": "memory_write",
            "key": "secret-memory",
            "content": "API_TOKEN=abc123",
            "memory_type": "fact",
            "evidence_refs": [{"kind": "chunk", "chunk_id": "chunk:1"}],
        },
    )

    result = runtime.knowledge_prs.merge_knowledge_pr(
        knowledge_pr_id=pr["knowledge_pr_id"],
        accept=True,
        approved_by="agent-review",
    )

    assert result["status"] == "policy_denied"
    assert result["error"]["code"] == "memory_guardrail_blocked"
    assert result["active_memory_write_performed"] is False
    assert read_record(runtime.ledger, "memories", "secret-memory") is None
    assert len(list_records(runtime.ledger, "memory_guardrail_receipts")) == 1


def test_knowledge_pr_merge_allows_reviewed_uncited_document_claim(tmp_path):
    runtime = _runtime(tmp_path)
    pr = _mergeable_pr(
        runtime,
        {
            "operation_id": "op:memory:document-claim",
            "operation_kind": "memory_write",
            "key": "document-claim",
            "content": "The architecture requires sync.",
            "memory_type": "document_claim",
            "evidence_refs": [{"kind": "chunk", "chunk_id": "chunk:1"}],
        },
    )

    result = runtime.knowledge_prs.merge_knowledge_pr(
        knowledge_pr_id=pr["knowledge_pr_id"],
        accept=True,
        approved_by="agent-review",
    )

    assert result["status"] == "merged"
    assert result["active_memory_write_performed"] is True
    assert read_record(runtime.ledger, "memories", "document-claim") is not None
    receipts = list_records(runtime.ledger, "memory_guardrail_receipts")
    assert receipts[0]["decision"] == "require_review"
    assert receipts[0]["reviewed_by"] == "agent-review"
