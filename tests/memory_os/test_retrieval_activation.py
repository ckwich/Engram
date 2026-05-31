from core.memory_os._records import list_records
from core.graph_store import JsonGraphStore
from core.memory_os.runtime import MemoryOSRuntime
from core.vector_index import InMemoryVectorIndex


def _embed(text):
    lowered = str(text).lower()
    if "runtime" in lowered or "activation" in lowered:
        return [1.0, 0.0]
    return [0.0, 1.0]


def _runtime(tmp_path):
    return MemoryOSRuntime(
        tmp_path / "memory_os",
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
        graph_store=JsonGraphStore(tmp_path / "edges.json"),
    )


def test_runtime_search_includes_activation_without_filtering_superseded(tmp_path):
    runtime = _runtime(tmp_path)
    runtime.initialize(rebuild_retrieval=True)
    runtime.store_memory(
        key="canonical_runtime_decision",
        title="Canonical Runtime Decision",
        content="Runtime activation should annotate selected retrieval results.",
        project="/repo/Engram",
        memory_type="decision",
        trust_state="source_backed",
        canonical=True,
    )
    runtime.store_memory(
        key="superseded_runtime_note",
        title="Superseded Runtime Note",
        content="Runtime activation should still return selected superseded evidence.",
        project="/repo/Engram",
        memory_type="project_state",
        trust_state="superseded",
    )

    result = runtime.search_memories(
        "runtime activation",
        project="/repo/Engram",
        limit=5,
    )

    by_key = {item["key"]: item for item in result["results"]}
    assert set(by_key) == {"canonical_runtime_decision", "superseded_runtime_note"}
    assert by_key["canonical_runtime_decision"]["activation"]["activation_score"] > 0.75
    assert by_key["canonical_runtime_decision"]["activation"]["action"] == "rank"
    assert by_key["superseded_runtime_note"]["activation"]["action"] == "rank"
    assert "superseded_penalty" in by_key["superseded_runtime_note"]["activation"]["signals"]
    assert list_records(runtime.ledger, "activation_receipts") == []


def test_retrieval_activation_is_secondary_to_vector_candidate_selection(tmp_path):
    runtime = _runtime(tmp_path)
    runtime.initialize(rebuild_retrieval=True)
    runtime.store_memory(
        key="matching_regular_memory",
        content="Activation search term appears here.",
        project="/repo/Engram",
        memory_type="fact",
        trust_state="reviewed",
    )
    runtime.store_memory(
        key="canonical_unmatched_memory",
        content="This unrelated canonical note should not be introduced by activation.",
        project="/repo/Engram",
        memory_type="decision",
        trust_state="source_backed",
        canonical=True,
    )

    result = runtime.search_memories(
        "activation search term",
        project="/repo/Engram",
        limit=1,
        retrieval_mode="hybrid",
    )

    assert [item["key"] for item in result["results"]] == ["matching_regular_memory"]
    assert "activation" in result["results"][0]
    assert result["results"][0]["activation"]["action"] == "rank"


def test_runtime_stores_activation_receipts_for_opt_in_audit_flows(tmp_path):
    runtime = _runtime(tmp_path)
    runtime.initialize(rebuild_retrieval=True)

    receipt = runtime.store_activation_receipt(
        query_context={"query": "runtime audit packet", "project": "/repo/Engram"},
        selected_refs=[
            {
                "kind": "memory",
                "key": "engram_runtime_choice",
                "activation_score": 0.83,
                "content": "body must not be persisted",
            }
        ],
        omitted_refs=[{"kind": "memory", "key": "engram_legacy_note", "reason": "budget"}],
    )

    inspector = runtime.inspector(limit=5)
    assert receipt["receipt_id"].startswith("activation:")
    assert inspector["activation_receipts"]["items"][0]["receipt_id"] == receipt["receipt_id"]
    assert inspector["summary"]["activation_receipt_count"] == 1
    assert "runtime audit packet" not in str(inspector["activation_receipts"])
    assert "body must not be persisted" not in str(inspector["activation_receipts"])
