from core.memory_os.knowledge_pr import KnowledgePRService
from core.graph_store import JsonGraphStore
from core.memory_os._records import hash_payload, list_records, read_record, upsert_record
from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.runtime import MemoryOSRuntime
from core.vector_index import InMemoryVectorIndex


def _service(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
    ledger.initialize()
    return KnowledgePRService(ledger, runtime=None), ledger


def _embed(text):
    return [1.0, 0.0] if str(text).strip() else [0.0, 1.0]


def _runtime_service(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path / "memory_os",
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
        graph_store=JsonGraphStore(tmp_path / "edges.json"),
    )
    runtime.initialize()
    return runtime.knowledge_prs, runtime


def _mergeable_pr(service, *, operations):
    branch = service.prepare_knowledge_branch(name="Mergeable Proposal")
    pr = service.prepare_knowledge_pr(
        branch_id=branch["branch_id"],
        title="Mergeable proposal",
        proposed_operations=operations,
    )
    ci = service.run_memory_ci(knowledge_pr_id=pr["knowledge_pr_id"])
    assert ci["status"] == "passed"
    return pr


def test_prepare_knowledge_branch_is_idempotent(tmp_path):
    service, _ledger = _service(tmp_path)

    created = service.prepare_knowledge_branch(
        name="Design Books",
        source_refs=[{"kind": "document", "document_id": "doc_design_books"}],
        base_snapshot_ref="snapshot:base",
        metadata={"project": "Engram"},
    )
    replayed = service.prepare_knowledge_branch(
        name="Design Books",
        source_refs=[{"kind": "document", "document_id": "doc_design_books"}],
        base_snapshot_ref="snapshot:base",
        metadata={"project": "Engram"},
    )

    assert created["status"] == "open"
    assert created["branch_id"].startswith("kbranch:")
    assert created["write_performed"] is True
    assert created["active_memory_write_performed"] is False
    assert created["graph_write_performed"] is False
    assert replayed["branch_id"] == created["branch_id"]
    assert replayed["write_performed"] is False


def test_prepare_knowledge_pr_requires_existing_branch(tmp_path):
    service, _ledger = _service(tmp_path)

    result = service.prepare_knowledge_pr(
        branch_id="kbranch:missing",
        title="Review missing branch",
    )

    assert result["status"] == "not_found"
    assert result["error"]["code"] == "not_found"
    assert result["write_performed"] is False
    assert result["active_memory_write_performed"] is False
    assert result["graph_write_performed"] is False


def test_prepare_knowledge_pr_rejects_malformed_operations(tmp_path):
    service, _ledger = _service(tmp_path)
    branch = service.prepare_knowledge_branch(name="Malformed Proposal")

    result = service.prepare_knowledge_pr(
        branch_id=branch["branch_id"],
        title="Malformed proposal",
        proposed_operations=["bad-operation"],
    )

    assert result["status"] == "schema_failed"
    assert result["error"]["code"] == "invalid_proposed_operations"
    assert result["write_performed"] is False
    assert result["active_memory_write_performed"] is False
    assert result["graph_write_performed"] is False


def test_prepare_and_inspect_knowledge_pr_return_ci_runs(tmp_path):
    service, ledger = _service(tmp_path)
    branch = service.prepare_knowledge_branch(
        name="Design Books",
        source_refs=[{"kind": "source", "source_id": "source_design_books"}],
        base_snapshot_ref="snapshot:base",
    )

    created = service.prepare_knowledge_pr(
        branch_id=branch["branch_id"],
        title="Graph Advanced Game Design",
        proposed_operations=[
            {
                "operation_id": "op:graph:advanced-game-design",
                "operation_kind": "graph_edge",
                "evidence_refs": [{"kind": "chunk", "chunk_id": "chunk:1"}],
            }
        ],
        document_refs=[{"kind": "document", "document_id": "doc_advanced_game_design"}],
        metadata={"domain": "document_intelligence"},
    )
    upsert_record(
        ledger,
        "memory_ci_runs",
        "mci:advanced-game-design",
        {
            "record_type": "memory_ci_run",
            "ci_run_id": "mci:advanced-game-design",
            "knowledge_pr_id": created["knowledge_pr_id"],
            "status": "passed",
            "gate_results": [],
        },
    )

    inspected = service.inspect_knowledge_pr(knowledge_pr_id=created["knowledge_pr_id"])

    assert created["status"] == "open"
    assert created["knowledge_pr_id"].startswith("kpr:")
    assert created["base_snapshot_ref"] == "snapshot:base"
    assert created["source_refs"] == branch["source_refs"]
    assert created["write_performed"] is True
    assert created["active_memory_write_performed"] is False
    assert created["graph_write_performed"] is False
    assert inspected["write_performed"] is False
    assert inspected["active_memory_write_performed"] is False
    assert inspected["graph_write_performed"] is False
    assert inspected["ci_runs"][0]["ci_run_id"] == "mci:advanced-game-design"


def test_run_memory_ci_blocks_uncited_operations(tmp_path):
    service, _ledger = _service(tmp_path)
    branch = service.prepare_knowledge_branch(name="Uncited Proposal")
    pr = service.prepare_knowledge_pr(
        branch_id=branch["branch_id"],
        title="Uncited graph proposal",
        proposed_operations=[
            {
                "operation_id": "op:graph:uncited",
                "operation_kind": "graph_edge",
                "edge_type": "related_to",
                "from_ref": {"kind": "memory", "key": "alpha"},
                "to_ref": {"kind": "concept", "concept_id": "beta"},
            }
        ],
    )

    result = service.run_memory_ci(knowledge_pr_id=pr["knowledge_pr_id"])
    inspected = service.inspect_knowledge_pr(knowledge_pr_id=pr["knowledge_pr_id"])

    assert result["status"] == "blocked"
    assert result["write_performed"] is True
    assert result["active_memory_write_performed"] is False
    assert result["graph_write_performed"] is False
    assert "gate_provenance" in result["blocking_gate_ids"]
    assert inspected["status"] == "ci_blocked"
    assert inspected["ci_summary"]["status"] == "blocked"
    assert inspected["ci_runs"][0]["ci_run_id"] == result["ci_run_id"]


def test_run_memory_ci_passes_cited_idempotent_operations(tmp_path):
    service, _ledger = _service(tmp_path)
    branch = service.prepare_knowledge_branch(name="Cited Proposal")
    pr = service.prepare_knowledge_pr(
        branch_id=branch["branch_id"],
        title="Cited memory proposal",
        proposed_operations=[
            {
                "operation_id": "op:memory:cited",
                "operation_kind": "memory_write",
                "evidence_refs": [{"kind": "chunk", "chunk_id": "chunk:1"}],
            }
        ],
    )

    result = service.run_memory_ci(knowledge_pr_id=pr["knowledge_pr_id"])
    inspected = service.inspect_knowledge_pr(knowledge_pr_id=pr["knowledge_pr_id"])

    assert result["status"] == "passed"
    assert result["blocking_gate_ids"] == []
    assert inspected["status"] == "mergeable"
    assert inspected["ci_summary"]["status"] == "passed"


def test_run_memory_ci_blocks_missing_operation_ids(tmp_path):
    service, _ledger = _service(tmp_path)
    branch = service.prepare_knowledge_branch(name="No Id Proposal")
    pr = service.prepare_knowledge_pr(
        branch_id=branch["branch_id"],
        title="No id proposal",
        proposed_operations=[
            {
                "operation_kind": "memory_write",
                "evidence_refs": [{"kind": "chunk", "chunk_id": "chunk:1"}],
            }
        ],
    )

    result = service.run_memory_ci(knowledge_pr_id=pr["knowledge_pr_id"])

    assert result["status"] == "blocked"
    assert "gate_idempotency" in result["blocking_gate_ids"]


def test_run_memory_ci_rerun_replaces_prior_blockers(tmp_path):
    service, _ledger = _service(tmp_path)
    branch = service.prepare_knowledge_branch(name="Retryable Proposal")
    pr = service.prepare_knowledge_pr(
        branch_id=branch["branch_id"],
        title="Retryable proposal",
        proposed_operations=[
            {
                "operation_id": "op:memory:retryable",
                "operation_kind": "memory_write",
                "evidence_refs": [{"kind": "chunk", "chunk_id": "chunk:1"}],
            }
        ],
    )

    failed = service.run_memory_ci(
        knowledge_pr_id=pr["knowledge_pr_id"],
        ci_context={"retrieval_receipts": [{"status": "failed"}]},
    )
    passed = service.run_memory_ci(
        knowledge_pr_id=pr["knowledge_pr_id"],
        ci_context={"retrieval_receipts": [{"status": "passed"}]},
    )
    inspected = service.inspect_knowledge_pr(knowledge_pr_id=pr["knowledge_pr_id"])

    assert failed["status"] == "blocked"
    assert "gate_retrieval_regression" in failed["blocking_gate_ids"]
    assert passed["status"] == "passed"
    assert passed["blocking_gate_ids"] == []
    assert inspected["status"] == "mergeable"
    assert inspected["blocking_issues"] == []


def test_merge_knowledge_pr_requires_acceptance(tmp_path):
    service, _runtime = _runtime_service(tmp_path)
    pr = _mergeable_pr(
        service,
        operations=[
            {
                "operation_id": "op:memory:accept-required",
                "operation_kind": "memory_write",
                "key": "accept-required",
                "content": "Reviewed memory content.",
                "evidence_refs": [{"kind": "chunk", "chunk_id": "chunk:1"}],
            }
        ],
    )

    result = service.merge_knowledge_pr(knowledge_pr_id=pr["knowledge_pr_id"], accept=False, approved_by="agent-review")

    assert result["status"] == "policy_denied"
    assert result["error"]["code"] == "accept_required"
    assert result["write_performed"] is False
    assert result["active_memory_write_performed"] is False
    assert result["graph_write_performed"] is False


def test_merge_knowledge_pr_requires_approved_by(tmp_path):
    service, _runtime = _runtime_service(tmp_path)
    pr = _mergeable_pr(
        service,
        operations=[
            {
                "operation_id": "op:memory:approval-required",
                "operation_kind": "memory_write",
                "key": "approval-required",
                "content": "Reviewed memory content.",
                "evidence_refs": [{"kind": "chunk", "chunk_id": "chunk:1"}],
            }
        ],
    )

    result = service.merge_knowledge_pr(knowledge_pr_id=pr["knowledge_pr_id"], accept=True)

    assert result["status"] == "schema_failed"
    assert result["error"]["code"] == "approved_by_required"
    assert result["write_performed"] is False


def test_merge_knowledge_pr_blocks_failed_memory_ci(tmp_path):
    service, _runtime = _runtime_service(tmp_path)
    branch = service.prepare_knowledge_branch(name="Blocked Merge")
    pr = service.prepare_knowledge_pr(
        branch_id=branch["branch_id"],
        title="Blocked merge",
        proposed_operations=[
            {
                "operation_id": "op:graph:blocked",
                "operation_kind": "graph_edge",
                "edge_type": "related_to",
                "from_ref": {"kind": "memory", "key": "alpha"},
                "to_ref": {"kind": "concept", "concept_id": "beta"},
            }
        ],
    )
    ci = service.run_memory_ci(knowledge_pr_id=pr["knowledge_pr_id"])
    assert ci["status"] == "blocked"

    result = service.merge_knowledge_pr(
        knowledge_pr_id=pr["knowledge_pr_id"],
        accept=True,
        approved_by="agent-review",
    )

    assert result["status"] == "policy_denied"
    assert result["error"]["code"] == "memory_ci_blocked"
    assert result["write_performed"] is False
    assert list_records(_runtime.ledger, "graph_edges") == []


def test_merge_knowledge_pr_writes_memory_and_transaction_receipt(tmp_path):
    service, runtime = _runtime_service(tmp_path)
    pr = _mergeable_pr(
        service,
        operations=[
            {
                "operation_id": "op:memory:merge",
                "operation_kind": "memory_write",
                "key": "merged-memory",
                "title": "Merged Memory",
                "content": "Reviewed memory content with a cited source.",
                "tags": ["knowledge-pr"],
                "project": "Engram",
                "domain": "architecture",
                "evidence_refs": [{"kind": "chunk", "chunk_id": "chunk:1"}],
            }
        ],
    )

    result = service.merge_knowledge_pr(
        knowledge_pr_id=pr["knowledge_pr_id"],
        accept=True,
        approved_by="agent-review",
    )

    assert result["status"] == "merged"
    assert result["write_performed"] is True
    assert result["active_memory_write_performed"] is True
    assert result["transaction"]["operation_kind"] == "merge_knowledge_pr"
    assert result["transaction"]["proposed_writes"][-1] == {
        "table": "knowledge_prs",
        "id": pr["knowledge_pr_id"],
    }
    memory = read_record(runtime.ledger, "memories", "merged-memory")
    assert memory["title"] == "Merged Memory"
    inspected = service.inspect_knowledge_pr(knowledge_pr_id=pr["knowledge_pr_id"])
    assert inspected["status"] == "merged"
    assert inspected["merge_transaction_id"] == result["transaction"]["transaction_id"]


def test_merge_knowledge_pr_rejects_invalid_batch_before_active_writes(tmp_path):
    service, runtime = _runtime_service(tmp_path)
    pr = _mergeable_pr(
        service,
        operations=[
            {
                "operation_id": "op:memory:should-not-persist",
                "operation_kind": "memory_write",
                "key": "should-not-persist",
                "content": "This write must not persist when a later operation is invalid.",
                "evidence_refs": [{"kind": "chunk", "chunk_id": "chunk:1"}],
            },
            {
                "operation_id": "op:document:invalid-completion",
                "operation_kind": "document_completion",
                "document_id": "doc_missing_completion_inputs",
                "evidence_refs": [{"kind": "chunk", "chunk_id": "chunk:2"}],
            },
        ],
    )

    result = service.merge_knowledge_pr(
        knowledge_pr_id=pr["knowledge_pr_id"],
        accept=True,
        approved_by="agent-review",
    )

    assert result["status"] == "schema_failed"
    assert result["error"]["code"] == "completion_args_required"
    assert result["write_performed"] is False
    assert result["active_memory_write_performed"] is False
    assert read_record(runtime.ledger, "memories", "should-not-persist") is None
    assert list_records(runtime.ledger, "transactions") == []
    inspected = service.inspect_knowledge_pr(knowledge_pr_id=pr["knowledge_pr_id"])
    assert inspected["status"] == "mergeable"
    assert inspected.get("merge_transaction_id") is None


def test_merge_knowledge_pr_rolls_back_prior_writes_when_later_operation_fails(tmp_path):
    service, runtime = _runtime_service(tmp_path)
    original_completion = runtime.complete_document_ingestion

    def fail_completion(**_kwargs):
        return {
            "status": "schema_failed",
            "error": {"code": "synthetic_completion_failure"},
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
        }

    runtime.complete_document_ingestion = fail_completion
    pr = _mergeable_pr(
        service,
        operations=[
            {
                "operation_id": "op:memory:rollback-runtime-failure",
                "operation_kind": "memory_write",
                "key": "rollback-runtime-failure",
                "content": "This write must roll back when a later runtime operation fails.",
                "evidence_refs": [{"kind": "chunk", "chunk_id": "chunk:1"}],
            },
            {
                "operation_id": "op:document:runtime-failure",
                "operation_kind": "document_completion",
                "document_id": "doc_runtime_failure",
                "completion_args": {
                    "document_promotion_transaction": {
                        "record_type": "document_promotion_transaction",
                        "document_id": "doc_runtime_failure",
                        "operations": [
                            {
                                "kind": "graph_edge",
                                "payload": {
                                    "from_ref": {"kind": "document", "document_id": "doc_runtime_failure"},
                                    "to_ref": {"kind": "concept", "concept_id": "runtime_failure"},
                                    "edge_type": "related_to",
                                    "evidence": "chunk:2",
                                },
                            }
                        ],
                    }
                },
                "evidence_refs": [{"kind": "chunk", "chunk_id": "chunk:2"}],
            },
        ],
    )

    result = service.merge_knowledge_pr(
        knowledge_pr_id=pr["knowledge_pr_id"],
        accept=True,
        approved_by="agent-review",
    )

    runtime.complete_document_ingestion = original_completion
    assert result["status"] == "schema_failed"
    assert result["error"]["code"] == "merge_operation_failed"
    assert result["write_performed"] is False
    assert result["active_memory_write_performed"] is False
    assert read_record(runtime.ledger, "memories", "rollback-runtime-failure") is None
    assert list_records(runtime.ledger, "transactions") == []
    assert runtime.search_memories("runtime operation fails", limit=5)["results"] == []
    inspected = service.inspect_knowledge_pr(knowledge_pr_id=pr["knowledge_pr_id"])
    assert inspected["status"] == "mergeable"
    assert inspected.get("merge_transaction_id") is None


def test_merge_knowledge_pr_rolls_back_prior_graph_writes_when_later_operation_fails(tmp_path):
    service, runtime = _runtime_service(tmp_path)
    original_completion = runtime.complete_document_ingestion

    def fail_completion(**_kwargs):
        return {
            "status": "schema_failed",
            "error": {"code": "synthetic_completion_failure"},
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
        }

    runtime.complete_document_ingestion = fail_completion
    pr = _mergeable_pr(
        service,
        operations=[
            {
                "operation_id": "op:graph:rollback-runtime-failure",
                "operation_kind": "graph_edge",
                "edge_type": "related_to",
                "from_ref": {"kind": "memory", "key": "alpha"},
                "to_ref": {"kind": "concept", "concept_id": "runtime_failure"},
                "evidence_refs": [{"kind": "chunk", "chunk_id": "chunk:1"}],
            },
            {
                "operation_id": "op:document:runtime-failure-after-graph",
                "operation_kind": "document_completion",
                "document_id": "doc_runtime_failure_after_graph",
                "completion_args": {
                    "document_promotion_transaction": {
                        "record_type": "document_promotion_transaction",
                        "document_id": "doc_runtime_failure_after_graph",
                        "operations": [
                            {
                                "kind": "graph_edge",
                                "payload": {
                                    "from_ref": {"kind": "document", "document_id": "doc_runtime_failure_after_graph"},
                                    "to_ref": {"kind": "concept", "concept_id": "runtime_failure"},
                                    "edge_type": "related_to",
                                    "evidence": "chunk:2",
                                },
                            }
                        ],
                    }
                },
                "evidence_refs": [{"kind": "chunk", "chunk_id": "chunk:2"}],
            },
        ],
    )

    result = service.merge_knowledge_pr(
        knowledge_pr_id=pr["knowledge_pr_id"],
        accept=True,
        approved_by="agent-review",
    )

    runtime.complete_document_ingestion = original_completion
    assert result["status"] == "schema_failed"
    assert result["error"]["code"] == "merge_operation_failed"
    assert result["write_performed"] is False
    assert result["graph_write_performed"] is False
    assert list_records(runtime.ledger, "graph_edges") == []
    assert list_records(runtime.ledger, "transactions") == []
    assert runtime.graph.load_edges() == []


def test_merge_knowledge_pr_imports_graph_edges_idempotently(tmp_path):
    service, runtime = _runtime_service(tmp_path)
    operation = {
        "operation_id": "op:graph:merge",
        "operation_kind": "graph_edge",
        "edge_type": "related_to",
        "from_ref": {"kind": "memory", "key": "alpha"},
        "to_ref": {"kind": "concept", "concept_id": "beta"},
        "confidence": 0.9,
        "evidence_refs": [{"kind": "chunk", "chunk_id": "chunk:1"}],
    }
    pr = _mergeable_pr(service, operations=[operation])

    first = service.merge_knowledge_pr(
        knowledge_pr_id=pr["knowledge_pr_id"],
        accept=True,
        approved_by="agent-review",
    )
    second = service.merge_knowledge_pr(
        knowledge_pr_id=pr["knowledge_pr_id"],
        accept=True,
        approved_by="agent-review",
    )

    assert first["status"] == "merged"
    assert first["graph_write_performed"] is True
    assert second["status"] == "merged"
    assert second["idempotent_replay"] is True
    assert second["write_performed"] is False
    edges = list_records(runtime.ledger, "graph_edges")
    assert len(edges) == 1
    assert edges[0]["edge_type"] == "related_to"
    assert len(list_records(runtime.ledger, "transactions")) == 1


def test_merge_knowledge_pr_already_merged_ignores_changed_selection(tmp_path):
    service, runtime = _runtime_service(tmp_path)
    operations = [
        {
            "operation_id": "op:graph:one",
            "operation_kind": "graph_edge",
            "edge_type": "related_to",
            "from_ref": {"kind": "memory", "key": "alpha"},
            "to_ref": {"kind": "concept", "concept_id": "one"},
            "evidence_refs": [{"kind": "chunk", "chunk_id": "chunk:1"}],
        },
        {
            "operation_id": "op:graph:two",
            "operation_kind": "graph_edge",
            "edge_type": "supports",
            "from_ref": {"kind": "memory", "key": "alpha"},
            "to_ref": {"kind": "concept", "concept_id": "two"},
            "evidence_refs": [{"kind": "chunk", "chunk_id": "chunk:2"}],
        },
    ]
    pr = _mergeable_pr(service, operations=operations)
    first = service.merge_knowledge_pr(
        knowledge_pr_id=pr["knowledge_pr_id"],
        accept=True,
        approved_by="agent-review",
    )

    second = service.merge_knowledge_pr(
        knowledge_pr_id=pr["knowledge_pr_id"],
        accept=True,
        approved_by="agent-review",
        selected_operation_ids=["op:graph:one"],
    )

    assert first["status"] == "merged"
    assert len(first["operation_results"]) == 2
    assert second["status"] == "merged"
    assert second["idempotent_replay"] is True
    assert second["write_performed"] is False
    assert second["operation_results"] == first["operation_results"]
    assert len(list_records(runtime.ledger, "graph_edges")) == 2
    assert len(list_records(runtime.ledger, "transactions")) == 1


def test_merge_knowledge_pr_recovers_existing_transaction_without_side_effects(tmp_path):
    service, runtime = _runtime_service(tmp_path)
    operation = {
        "operation_id": "op:memory:existing-transaction",
        "operation_kind": "memory_write",
        "key": "should-not-write",
        "content": "This write should be skipped because the merge transaction exists.",
        "evidence_refs": [{"kind": "chunk", "chunk_id": "chunk:1"}],
    }
    pr = _mergeable_pr(service, operations=[operation])
    idempotency_key = f"merge_knowledge_pr:{pr['knowledge_pr_id']}:{hash_payload(['op:memory:existing-transaction'])}"
    seeded = runtime.transactions.promote(
        operation_kind="merge_knowledge_pr",
        proposed_writes=[
            {"table": "memories", "id": "should-not-write"},
            {"table": "knowledge_prs", "id": pr["knowledge_pr_id"]},
        ],
        idempotency_key=idempotency_key,
        affected_refs=[{"kind": "knowledge_pr", "knowledge_pr_id": pr["knowledge_pr_id"]}],
    )

    result = service.merge_knowledge_pr(
        knowledge_pr_id=pr["knowledge_pr_id"],
        accept=True,
        approved_by="agent-review",
    )

    assert result["status"] == "merged"
    assert result["idempotent_replay"] is True
    assert result["transaction"]["transaction_id"] == seeded["transaction_id"]
    assert result["active_memory_write_performed"] is False
    assert result["graph_write_performed"] is False
    assert read_record(runtime.ledger, "memories", "should-not-write") is None
    assert len(list_records(runtime.ledger, "transactions")) == 1
    inspected = service.inspect_knowledge_pr(knowledge_pr_id=pr["knowledge_pr_id"])
    assert inspected["status"] == "merged"
    assert inspected["merge_transaction_id"] == seeded["transaction_id"]


def test_run_memory_ci_and_merge_support_batch_graph_edges(tmp_path):
    service, runtime = _runtime_service(tmp_path)
    operation = {
        "operation_id": "op:graph:batch",
        "operation_kind": "graph_edges",
        "edges": [
            {
                "edge_type": "related_to",
                "from_ref": {"kind": "memory", "key": "alpha"},
                "to_ref": {"kind": "concept", "concept_id": "one"},
                "evidence_refs": [{"kind": "chunk", "chunk_id": "chunk:1"}],
            },
            {
                "edge_type": "supports",
                "from_ref": {"kind": "memory", "key": "alpha"},
                "to_ref": {"kind": "concept", "concept_id": "two"},
                "evidence_refs": [{"kind": "chunk", "chunk_id": "chunk:2"}],
            },
        ],
    }
    branch = service.prepare_knowledge_branch(name="Batch Graph Proposal")
    pr = service.prepare_knowledge_pr(
        branch_id=branch["branch_id"],
        title="Batch graph proposal",
        proposed_operations=[operation],
    )

    ci = service.run_memory_ci(knowledge_pr_id=pr["knowledge_pr_id"])
    result = service.merge_knowledge_pr(
        knowledge_pr_id=pr["knowledge_pr_id"],
        accept=True,
        approved_by="agent-review",
    )

    assert ci["status"] == "passed"
    assert result["status"] == "merged"
    assert result["graph_write_performed"] is True
    edges = list_records(runtime.ledger, "graph_edges")
    assert {edge["edge_type"] for edge in edges} == {"related_to", "supports"}
