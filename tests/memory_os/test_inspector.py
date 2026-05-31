from core.memory_os._records import upsert_record
from core.memory_os.inspector import build_memory_os_inspector
from core.memory_os.ledger import MemoryOSLedger


class FakeRuntime:
    def __init__(self, ledger):
        self.ledger = ledger

    def status(self):
        return {
            "status": "ok",
            "components": {
                "ledger": {"path": str(self.ledger.path), "exists": True},
                "retrieval": {"backend": "LanceDBVectorIndex"},
                "graph": {"backend": "KuzuGraphStore"},
            },
        }


def test_memory_os_inspector_summarizes_read_only_runtime_state(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "engram.sqlite")
    upsert_record(
        ledger,
        "jobs",
        "job:one",
        {"job_id": "job:one", "job_kind": "document_materialization", "status": "queued"},
    )
    upsert_record(
        ledger,
        "transactions",
        "txn:one",
        {"transaction_id": "txn:one", "operation_kind": "import_document", "status": "dry_run"},
    )
    upsert_record(
        ledger,
        "retrieval_receipts",
        "coverage:one",
        {"coverage_map_id": "coverage:one", "document_id": "doc:one", "skipped_region_count": 0},
    )
    upsert_record(
        ledger,
        "entities",
        "entity:one",
        {"entity_id": "entity:one", "canonical_name": "Visual Hierarchy", "review_state": "reviewed"},
    )
    upsert_record(
        ledger,
        "concepts",
        "concept:one",
        {"concept_id": "concept:one", "label": "attention priority", "review_state": "draft"},
    )
    upsert_record(
        ledger,
        "firewall_events",
        "firewall:one",
        {"event_id": "firewall:one", "decision": "quarantine", "guidance_allowed": False},
    )
    upsert_record(
        ledger,
        "memory_guardrail_receipts",
        "memory_guardrail:one",
        {
            "receipt_id": "memory_guardrail:one",
            "decision": "block",
            "issue_codes": ["secret_like_content"],
            "affected_ref": {"kind": "memory", "key": "bad_secret"},
        },
    )
    upsert_record(
        ledger,
        "snapshots",
        "snapshot:one",
        {"snapshot_id": "snapshot:one", "ledger_revision": 1},
    )
    upsert_record(
        ledger,
        "skill_packs",
        "skill:one",
        {"compilation_id": "skill:one", "scope_id": "frontend-design"},
    )
    upsert_record(
        ledger,
        "graph_edges",
        "edge:one",
        {
            "edge_id": "edge:one",
            "from_ref": {"kind": "concept", "key": "visual_hierarchy"},
            "to_ref": {"kind": "concept", "key": "attention_priority"},
            "edge_type": "supports",
            "confidence": 0.9,
        },
    )

    payload = build_memory_os_inspector(FakeRuntime(ledger), limit=3)

    assert payload["schema_version"] == "2026-05-13.memory-os-inspector.v1"
    assert payload["write_performed"] is False
    assert payload["runtime"]["status"] == "ok"
    assert payload["jobs"]["items"][0]["job_id"] == "job:one"
    assert payload["transactions"]["items"][0]["transaction_id"] == "txn:one"
    assert payload["coverage_maps"]["items"][0]["coverage_map_id"] == "coverage:one"
    assert payload["entity_registry"]["entities"][0]["canonical_name"] == "Visual Hierarchy"
    assert payload["entity_registry"]["concepts"][0]["label"] == "attention priority"
    assert payload["firewall_queue"]["items"][0]["decision"] == "quarantine"
    assert payload["memory_guardrail_receipts"]["items"][0]["issue_codes"] == ["secret_like_content"]
    assert payload["snapshots"]["items"][0]["snapshot_id"] == "snapshot:one"
    assert payload["snapshots"]["semantics"]["record_type"] == "snapshot_manifest_section"
    assert payload["snapshots"]["semantics"]["restore_grade"] is False
    assert payload["snapshots"]["semantics"]["rollback_supported"] is False
    assert payload["skill_packs"]["items"][0]["compilation_id"] == "skill:one"
    assert payload["graph"]["edges"][0]["edge_id"] == "edge:one"
    assert payload["summary"]["coverage_map_count"] == 1
    assert payload["summary"]["memory_guardrail_receipt_count"] == 1


def test_memory_os_inspector_surfaces_review_promotion_and_release_state(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "engram.sqlite")
    upsert_record(
        ledger,
        "drafts",
        "draft:book",
        {
            "draft_id": "draft:book",
            "record_type": "document_draft",
            "review_state": "pending_review",
            "status": "draft",
        },
    )
    upsert_record(
        ledger,
        "transactions",
        "txn:artifact",
        {
            "transaction_id": "txn:artifact",
            "operation_kind": "document_artifact_store",
            "status": "dry_run",
            "write_performed": False,
        },
    )
    upsert_record(
        ledger,
        "transactions",
        "txn:promote",
        {
            "transaction_id": "txn:promote",
            "record_type": "document_promotion_transaction",
            "operation_kind": "prepare_document_promotion_transaction",
            "status": "dry_run",
            "write_performed": False,
        },
    )
    upsert_record(
        ledger,
        "graph_edges",
        "edge:contradicts",
        {
            "edge_id": "edge:contradicts",
            "from_ref": {"kind": "document", "key": "book"},
            "to_ref": {"kind": "memory", "key": "older_claim"},
            "edge_type": "contradicts",
            "confidence": 0.83,
        },
    )
    upsert_record(
        ledger,
        "knowledge_branches",
        "kbranch:book",
        {
            "branch_id": "kbranch:book",
            "record_type": "knowledge_branch",
            "name": "Book review branch",
            "status": "open",
        },
    )
    upsert_record(
        ledger,
        "knowledge_prs",
        "kpr:book",
        {
            "knowledge_pr_id": "kpr:book",
            "record_type": "knowledge_pr",
            "branch_id": "kbranch:book",
            "title": "Book coverage PR",
            "status": "ci_blocked",
            "document_refs": [{"document_id": "doc_book"}],
            "source_refs": [{"source_uri": "file:///books/book.pdf"}],
            "proposed_operations": [{"operation_id": "op:book", "operation_kind": "memory"}],
            "ci_summary": {"status": "blocked", "blocking_gate_ids": ["gate_document_coverage"]},
            "blocking_issues": [{"gate_id": "gate_document_coverage"}],
        },
    )
    upsert_record(
        ledger,
        "memory_ci_runs",
        "mci:book",
        {
            "ci_run_id": "mci:book",
            "record_type": "memory_ci_run",
            "knowledge_pr_id": "kpr:book",
            "status": "blocked",
            "blocking_gate_ids": ["gate_document_coverage"],
            "gate_results": [
                {
                    "gate_id": "gate_document_coverage",
                    "status": "blocked",
                    "required": True,
                    "findings": [{"document_id": "doc_book"}],
                }
            ],
        },
    )
    upsert_record(
        ledger,
        "transactions",
        "txn:kpr",
        {
            "transaction_id": "txn:kpr",
            "operation_kind": "merge_knowledge_pr",
            "status": "committed",
            "affected_refs": [{"kind": "knowledge_pr", "knowledge_pr_id": "kpr:book"}],
        },
    )

    payload = build_memory_os_inspector(FakeRuntime(ledger), limit=5)

    assert payload["daemon_status"]["status"] == "ok"
    assert payload["review_preparation_queue"]["items"][0]["draft_id"] == "draft:book"
    assert payload["document_artifact_transactions"]["items"][0]["transaction_id"] == "txn:artifact"
    assert payload["promotion_transactions"]["items"][0]["transaction_id"] == "txn:promote"
    assert payload["graph_evidence"]["edge_count"] == 1
    assert payload["graph_evidence"]["contradiction_count"] == 1
    assert payload["ekc_eval_summary"]["scenario_count"] >= 1
    assert any(
        "server.py --agent-eval" in command["command"]
        for command in payload["release_gate_commands"]["items"]
    )
    assert payload["summary"]["review_queue_count"] == 1
    assert payload["summary"]["promotion_transaction_count"] == 1
    assert payload["summary"]["knowledge_branch_count"] == 1
    assert payload["summary"]["knowledge_pr_count"] == 1
    assert payload["summary"]["memory_ci_run_count"] == 1
    assert payload["summary"]["knowledge_pr_ci_blocked_count"] == 1
    review_state = payload["knowledge_pr_review_state"]
    assert review_state["open_count"] == 1
    assert review_state["ci_blocked_count"] == 1
    assert review_state["items"][0]["latest_ci_run_id"] == "mci:book"
    assert review_state["blocked_document_coverage_refs"][0]["document_id"] == "doc_book"
    assert review_state["merge_transaction_refs"][0]["transaction_id"] == "txn:kpr"
    assert review_state["write_performed"] is False
