from core.graph_store import JsonGraphStore
from core.memory_os._records import list_records, read_record
from core.memory_os.memory_guardrails import evaluate_memory_write
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


def test_secret_like_memory_write_is_blocked():
    result = evaluate_memory_write(
        {
            "key": "bad_secret",
            "content": "AWS_SECRET_ACCESS_KEY=abc123",
            "memory_type": "fact",
        }
    )

    assert result["decision"] == "block"
    assert result["highest_severity"] == "blocker"
    assert "secret_like_content" in result["issue_codes"]
    assert result["write_performed"] is False


def test_uncited_document_claim_requires_review():
    result = evaluate_memory_write(
        {
            "key": "claim_without_source",
            "content": "The architecture requires sync.",
            "memory_type": "document_claim",
            "citations": [],
        }
    )

    assert result["decision"] == "require_review"
    assert "uncited_document_claim" in result["issue_codes"]


def test_runtime_blocks_secret_like_memory_before_active_write(tmp_path):
    runtime = _runtime(tmp_path)

    result = runtime.store_memory(
        key="bad_secret",
        content="AWS_SECRET_ACCESS_KEY=abc123",
        memory_type="fact",
    )

    assert result["status"] == "policy_denied"
    assert result["error"]["code"] == "memory_guardrail_blocked"
    assert result["guardrail"]["decision"] == "block"
    assert result["write_performed"] is True
    assert result["active_memory_write_performed"] is False
    assert list_records(runtime.ledger, "memories") == []
    receipts = list_records(runtime.ledger, "memory_guardrail_receipts")
    assert len(receipts) == 1
    assert receipts[0]["issue_codes"] == ["secret_like_content"]
    assert "content_excerpt" not in receipts[0]
    assert read_record(runtime.ledger, "firewall_events", receipts[0]["firewall_event_id"])


def test_runtime_requires_review_for_uncited_document_claim(tmp_path):
    runtime = _runtime(tmp_path)

    result = runtime.store_memory(
        key="claim_without_source",
        content="The architecture requires sync.",
        memory_type="document_claim",
    )

    assert result["status"] == "review_required"
    assert result["error"]["code"] == "memory_guardrail_review_required"
    assert result["guardrail"]["decision"] == "require_review"
    assert result["active_memory_write_performed"] is False
    assert list_records(runtime.ledger, "memories") == []
    receipts = list_records(runtime.ledger, "memory_guardrail_receipts")
    assert receipts[0]["content_excerpt"] == "The architecture requires sync."
