from __future__ import annotations

from core.graph_store import JsonGraphStore
from core.memory_os._records import list_records, upsert_record
from core.memory_os.runtime import MemoryOSRuntime
from core.vector_index import InMemoryVectorIndex


def _embed(text):
    return [1.0, 0.0] if "memory" in str(text).lower() else [0.0, 1.0]


def _runtime(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path / "memory_os",
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
        graph_store=JsonGraphStore(tmp_path / "edges.json"),
    )
    runtime.initialize()
    return runtime


def _seed_memory(runtime, key="memory_alpha", content=None):
    return runtime.store_memory(
        key=key,
        title="Memory Alpha",
        content=content
        or (
            "# Memory Alpha\n\n"
            "Agent memory should preserve cited evidence before graph promotion.\n\n"
            "Graph proposal batches keep the agent's synthesis reviewable."
        ),
        tags=["graph", "memory"],
        project="Engram",
        domain="graph",
        status="accepted",
        canonical=True,
        force=True,
    )


def _seed_staged_document(runtime):
    upsert_record(
        runtime.ledger,
        "documents",
        "doc_staged_book",
        {
            "document_id": "doc_staged_book",
            "title": "Staged Book",
            "project": "Engram",
            "ingestion_status": "staged",
            "usable": False,
        },
    )


def _graph_edges(runtime, source=None):
    edges = list_records(runtime.ledger, "graph_edges")
    if source is None:
        return edges
    return [edge for edge in edges if edge.get("source") == source]


def test_prepare_graph_readiness_report_inventory_is_no_write_and_excludes_staged_docs(tmp_path):
    runtime = _runtime(tmp_path)
    _seed_memory(runtime)
    _seed_staged_document(runtime)
    baseline_edges = list_records(runtime.ledger, "graph_edges")

    report = runtime.prepare_graph_readiness_report(scope="memory_os", project="Engram")

    assert report["status"] == "partial"
    assert report["write_performed"] is False
    assert report["inventory"]["memory_count"] == 1
    assert report["inventory"]["eligible_memory_count"] == 1
    assert report["inventory"]["document_count"] == 1
    assert report["inventory"]["usable_document_count"] == 0
    assert report["inventory"]["staged_document_count"] == 1
    assert report["eligible_source_count"] == 1
    assert report["eligible_sources"][0]["ref"] == {"kind": "memory", "key": "memory_alpha"}
    assert report["blocking_issues"][0]["code"] == "staged_documents_excluded"
    assert list_records(runtime.ledger, "graph_edges") == baseline_edges


def test_graph_readiness_project_filter_resolves_engram_path_aliases(tmp_path):
    runtime = _runtime(tmp_path)
    runtime.store_memory(
        key="engram_label",
        content="Engram label memory.",
        title="Engram Label",
        project="Engram",
        status="active",
    )
    runtime.store_memory(
        key="windows_label",
        content="Windows path label memory.",
        title="Windows Label",
        project="C:\\Dev\\Engram",
        status="active",
    )
    runtime.store_memory(
        key="slash_label",
        content="Slash path label memory.",
        title="Slash Label",
        project="C:/Dev/Engram",
        status="active",
    )
    runtime.store_memory(
        key="other_project",
        content="Other project memory.",
        title="Other",
        project="Other",
        status="active",
    )

    aliased = runtime.prepare_graph_readiness_report(scope="memory_os", project="Engram")
    exact = runtime.prepare_graph_readiness_report(
        scope="memory_os",
        project="Engram",
        exact_project_match=True,
    )

    assert aliased["inventory"]["memory_count"] == 3
    assert aliased["inventory"]["eligible_memory_count"] == 3
    assert {source["ref"]["key"] for source in aliased["eligible_sources"]} == {
        "engram_label",
        "windows_label",
        "slash_label",
    }
    assert exact["inventory"]["memory_count"] == 1
    assert exact["eligible_sources"][0]["ref"]["key"] == "engram_label"


def test_prepare_graph_proposal_batch_returns_bounded_cited_source_context(tmp_path):
    runtime = _runtime(tmp_path)
    _seed_memory(runtime)

    batch = runtime.prepare_graph_proposal_batch(
        scope="memory_os",
        project="Engram",
        source_refs=[{"kind": "memory", "key": "memory_alpha"}],
        budget_chars=80,
    )

    assert batch["status"] == "ok"
    assert batch["write_performed"] is False
    assert batch["source_count"] == 1
    source = batch["source_items"][0]
    assert source["ref"] == {"kind": "memory", "key": "memory_alpha"}
    assert source["evidence_excerpt"]
    assert len(source["evidence_excerpt"]) <= 80
    assert source["citations"][0]["level"] == "chunk"
    assert source["citations"][0]["key"] == "memory_alpha"
    assert batch["proposal_validation"]["ready_to_promote"] is False
    assert batch["proposal_schema"]["required_edge_fields"] == [
        "from_ref",
        "to_ref",
        "edge_type",
        "evidence",
        "evidence_refs",
    ]


def test_prepare_graph_proposal_batch_validates_candidate_edges_without_writing(tmp_path):
    runtime = _runtime(tmp_path)
    _seed_memory(runtime)
    baseline_edges = list_records(runtime.ledger, "graph_edges")

    batch = runtime.prepare_graph_proposal_batch(
        scope="memory_os",
        project="Engram",
        source_refs=[{"kind": "memory", "key": "memory_alpha"}],
        candidate_graph_edges=[
            {
                "from_ref": {"kind": "memory", "key": "memory_alpha"},
                "to_ref": {"kind": "concept", "name": "Evidence-first graphing"},
                "edge_type": "supports",
                "confidence": 0.82,
                "evidence": "Memory Alpha says graph proposal batches keep synthesis reviewable.",
                "evidence_refs": [{"kind": "memory", "key": "memory_alpha"}],
            },
            {
                "from_ref": {"kind": "memory", "key": "memory_alpha"},
                "to_ref": {"kind": "concept", "name": "Unsupported graphing"},
                "edge_type": "supports",
                "evidence": "",
                "evidence_refs": [],
            },
        ],
    )

    assert batch["status"] == "partial"
    assert batch["proposal_validation"]["candidate_count"] == 2
    assert batch["proposal_validation"]["valid_count"] == 1
    assert batch["proposal_validation"]["ready_to_promote"] is False
    assert batch["validated_edges"][0]["edge_id"].startswith(
        "edge:memory-alpha:supports:evidence-first-graphing:"
    )
    assert batch["validated_edges"][0]["to_ref"] == {
        "kind": "concept",
        "id": "concept:evidence-first-graphing",
        "name": "Evidence-first graphing",
    }
    assert batch["blocking_issues"][0]["code"] == "edge_evidence_required"
    assert list_records(runtime.ledger, "graph_edges") == baseline_edges


def test_apply_graph_proposal_batch_requires_acceptance_and_reviewer(tmp_path):
    runtime = _runtime(tmp_path)
    _seed_memory(runtime)
    baseline_edges = list_records(runtime.ledger, "graph_edges")
    candidate = {
        "from_ref": {"kind": "memory", "key": "memory_alpha"},
        "to_ref": {"kind": "concept", "name": "Evidence-first graphing"},
        "edge_type": "supports",
        "confidence": 0.82,
        "evidence": "Memory Alpha says graph proposal batches keep synthesis reviewable.",
        "evidence_refs": [{"kind": "memory", "key": "memory_alpha"}],
    }

    no_accept = runtime.apply_graph_proposal_batch(
        scope="memory_os",
        project="Engram",
        source_refs=[{"kind": "memory", "key": "memory_alpha"}],
        candidate_graph_edges=[candidate],
        accept=False,
        approved_by="agent-review",
    )
    no_reviewer = runtime.apply_graph_proposal_batch(
        scope="memory_os",
        project="Engram",
        source_refs=[{"kind": "memory", "key": "memory_alpha"}],
        candidate_graph_edges=[candidate],
        accept=True,
        approved_by=None,
    )

    assert no_accept["status"] == "policy_denied"
    assert no_accept["write_performed"] is False
    assert no_reviewer["status"] == "schema_failed"
    assert no_reviewer["error"]["code"] == "approved_by_required"
    assert list_records(runtime.ledger, "graph_edges") == baseline_edges


def test_apply_graph_proposal_batch_promotes_reviewed_edges_and_concepts(tmp_path):
    runtime = _runtime(tmp_path)
    _seed_memory(runtime)
    baseline_edge_count = len(list_records(runtime.ledger, "graph_edges"))
    candidate = {
        "from_ref": {"kind": "memory", "key": "memory_alpha"},
        "to_ref": {"kind": "concept", "name": "Evidence-first graphing"},
        "edge_type": "supports",
        "confidence": 0.82,
        "evidence": "Memory Alpha says graph proposal batches keep synthesis reviewable.",
        "evidence_refs": [{"kind": "memory", "key": "memory_alpha"}],
    }

    result = runtime.apply_graph_proposal_batch(
        scope="memory_os",
        project="Engram",
        source_refs=[{"kind": "memory", "key": "memory_alpha"}],
        candidate_graph_edges=[candidate],
        accept=True,
        approved_by="agent-review",
    )

    assert result["status"] == "ok"
    assert result["write_performed"] is True
    assert result["graph_write_performed"] is True
    assert result["active_memory_write_performed"] is False
    assert result["graph_edges_written"] == [result["validated_edges"][0]["edge_id"]]
    assert len(list_records(runtime.ledger, "graph_edges")) == baseline_edge_count + 1
    assert len(_graph_edges(runtime, "graph_proposal_batch")) == 1
    assert any(
        concept["concept_id"] == "concept:evidence-first-graphing"
        for concept in list_records(runtime.ledger, "concepts")
    )
    assert result["transaction_receipt"]["operation_kind"] == "apply_graph_proposal_batch"


def test_apply_graph_proposal_batch_replays_idempotently_without_rewriting(tmp_path):
    runtime = _runtime(tmp_path)
    _seed_memory(runtime)
    baseline_edge_count = len(list_records(runtime.ledger, "graph_edges"))
    candidate = {
        "from_ref": {"kind": "memory", "key": "memory_alpha"},
        "to_ref": {"kind": "concept", "name": "Evidence-first graphing"},
        "edge_type": "supports",
        "confidence": 0.82,
        "evidence": "Memory Alpha says graph proposal batches keep synthesis reviewable.",
        "evidence_refs": [{"kind": "memory", "key": "memory_alpha"}],
    }

    first = runtime.apply_graph_proposal_batch(
        scope="memory_os",
        project="Engram",
        source_refs=[{"kind": "memory", "key": "memory_alpha"}],
        candidate_graph_edges=[candidate],
        accept=True,
        approved_by="agent-review",
    )
    original_edge = _graph_edges(runtime, "graph_proposal_batch")[0]

    replay = runtime.apply_graph_proposal_batch(
        scope="memory_os",
        project="Engram",
        source_refs=[{"kind": "memory", "key": "memory_alpha"}],
        candidate_graph_edges=[candidate],
        accept=True,
        approved_by="agent-review",
    )

    assert first["status"] == "ok"
    assert replay["status"] == "ok"
    assert replay["idempotent_replay"] is True
    assert replay["write_performed"] is False
    assert replay["graph_write_performed"] is False
    assert len(list_records(runtime.ledger, "graph_edges")) == baseline_edge_count + 1
    assert len(_graph_edges(runtime, "graph_proposal_batch")) == 1
    assert _graph_edges(runtime, "graph_proposal_batch")[0]["updated_at"] == original_edge["updated_at"]
