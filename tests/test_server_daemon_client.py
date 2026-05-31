from __future__ import annotations

import asyncio
import inspect

from core.mcp.tool_registry import (
    BENCHMARK_WORKFLOW,
    KNOWLEDGE_PR_WORKFLOW,
    STABLE_DOCUMENT_WORKFLOW,
    build_memory_protocol_sections,
    validate_protocol_sections,
)

import server
import server_daemon_client


class FakeDaemonClient:
    def __init__(self):
        self.calls = []

    def search_memories(self, payload):
        self.calls.append(("search_memories", payload))
        return {
            "query": payload["query"],
            "count": 1,
            "results": [{"key": "daemon_memory", "chunk_id": 0}],
            "error": None,
        }

    def check_duplicate(self, payload):
        self.calls.append(("check_duplicate", payload))
        return {
            "key": payload["key"],
            "duplicate": True,
            "match": {
                "status": "duplicate",
                "existing_key": "daemon_memory",
                "existing_title": "Daemon Memory",
                "score": 0.97,
            },
            "error": None,
        }

    def retrieve_chunk(self, payload):
        self.calls.append(("retrieve_chunk", payload))
        return {
            "key": payload["key"],
            "chunk_id": payload["chunk_id"],
            "found": True,
            "chunk": {"title": "Daemon Memory", "text": "chunk"},
            "error": None,
        }

    def retrieve_chunks(self, payload):
        self.calls.append(("retrieve_chunks", payload))
        return {
            "requested_count": len(payload["requests"]),
            "found_count": 1,
            "results": [
                {
                    "key": payload["requests"][0]["key"],
                    "chunk_id": payload["requests"][0]["chunk_id"],
                    "found": True,
                    "chunk": {"title": "Daemon Memory", "text": "chunk"},
                    "error": None,
                }
            ],
            "error": None,
        }

    def retrieve_memory(self, payload):
        self.calls.append(("retrieve_memory", payload))
        return {
            "key": payload["key"],
            "found": True,
            "memory": {"key": payload["key"], "title": "Daemon Memory", "content": "body"},
            "error": None,
        }

    def store_memory(self, payload):
        self.calls.append(("store_memory", payload))
        return {
            "stored": True,
            "result": {
                "key": payload["key"],
                "title": payload["title"],
                "chunk_count": 1,
                "chars": len(payload["content"]),
            },
            "error": None,
        }

    def update_memory_metadata(self, payload):
        self.calls.append(("update_memory_metadata", payload))
        return {
            "key": payload["key"],
            "updated": True,
            "memory": {
                "key": payload["key"],
                "title": payload["title"],
                "tags": payload["tags"],
            },
            "error": None,
        }

    def repair_memory_metadata(self, payload):
        self.calls.append(("repair_memory_metadata", payload))
        return {
            "requested_count": len(payload["keys"]),
            "repaired_count": 0 if payload.get("dry_run", True) else len(payload["keys"]),
            "dry_run": payload.get("dry_run", True),
            "repairs": [{"key": key, "repaired": not payload.get("dry_run", True)} for key in payload["keys"]],
            "error": None,
        }

    def prepare_source_memory(self, payload):
        self.calls.append(("prepare_source_memory", payload))
        return {
            "draft": {
                "draft_id": "draft-a",
                "proposed_memories": [{"key": "daemon_source_memory"}],
                "proposed_edges": [],
            },
            "error": None,
        }

    def prepare_document_disassembly(self, payload):
        self.calls.append(("prepare_document_disassembly", payload))
        return {
            "disassembly": {
                "record_type": "document_disassembly_preview",
                "source": {"path": payload["source_path"]},
                "document": {"page_limit": payload.get("max_pages")},
                "write_performed": False,
                "active_memory_write_performed": False,
                "error": None,
            },
            "error": None,
        }

    def prepare_document_coverage_workbench(self, payload):
        self.calls.append(("prepare_document_coverage_workbench", payload))
        return {
            "workbench": {
                "record_type": "document_coverage_workbench",
                "source": {"path": payload["source_path"]},
                "write_performed": False,
                "active_memory_write_performed": False,
            },
            "error": None,
        }

    def prepare_document_intake_review(self, payload):
        self.calls.append(("prepare_document_intake_review", payload))
        return {
            "status": "ok",
            "source": {"source_path": payload["source_path"], "document_id": "doc_1"},
            "disassembly": {"record_type": "document_disassembly_preview"},
            "extraction_request": None,
            "document_preview": {"preview": {"document": {"document_id": "doc_1"}}},
            "quality": {},
            "artifact_manifest": {},
            "draft_candidates": [],
            "promotion_guidance": {"auto_promote": False},
            "policy": {
                "write_behavior": "read_only",
                "active_memory_promoted": False,
                "graph_edges_promoted": False,
            },
            "receipts": {"artifacts_built": 1, "artifacts_read": 0, "coverage_missing": []},
            "error": None,
        }

    def list_document_extractors(self, payload):
        self.calls.append(("list_document_extractors", payload))
        return {"catalog": {"extractors": [{"id": "fake"}]}, "error": None}

    def preview_document_source_connector(self, payload):
        self.calls.append(("preview_document_source_connector", payload))
        return {"preview": {"items": []}, "error": None}

    def prepare_document_extraction_request(self, payload):
        self.calls.append(("prepare_document_extraction_request", payload))
        return {"request": {"source_ref": payload["source_ref"]}, "error": None}

    def prepare_document_extraction_result(self, payload):
        self.calls.append(("prepare_document_extraction_result", payload))
        return {"result": {"title": payload["title"]}, "error": None}

    def preview_document_extraction(self, payload):
        self.calls.append(("preview_document_extraction", payload))
        return {"preview": {"document": {"title": payload["title"]}}, "error": None}

    def prepare_visual_extraction_request(self, payload):
        self.calls.append(("prepare_visual_extraction_request", payload))
        return {"request": {"document_id": payload["document_record"]["document_id"]}, "error": None}

    def preview_visual_extraction(self, payload):
        self.calls.append(("preview_visual_extraction", payload))
        return {"preview": {"visual_artifacts": payload["observations"]}, "error": None}

    def prepare_document_understanding_packet(self, payload):
        self.calls.append(("prepare_document_understanding_packet", payload))
        return {"packet": {"document_id": payload["document_record"]["document_id"]}, "error": None}

    def prepare_document_draft(self, payload):
        self.calls.append(("prepare_document_draft", payload))
        return {"draft": {"document_id": payload["document_record"]["document_id"]}, "error": None}

    def prepare_document_promotion_transaction(self, payload):
        self.calls.append(("prepare_document_promotion_transaction", payload))
        return {"transaction": {"approved_by": payload["approved_by"]}, "error": None}

    def apply_document_promotion_transaction(self, payload):
        self.calls.append(("apply_document_promotion_transaction", payload))
        return {
            "status": "ok" if payload.get("accept") else "policy_denied",
            "write_performed": bool(payload.get("accept")),
            "active_memory_write_performed": bool(payload.get("accept")),
            "graph_write_performed": False,
            "error": None,
        }

    def prepare_document_artifact_store(self, payload):
        self.calls.append(("prepare_document_artifact_store", payload))
        return {
            "status": "prepared",
            "prepared_transaction_id": "txn-doc",
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None,
        }

    def store_document_artifact(self, payload):
        self.calls.append(("store_document_artifact", payload))
        return {
            "status": "ok" if payload.get("accept") else "policy_denied",
            "stored": bool(payload.get("accept")),
            "write_performed": bool(payload.get("accept")),
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None,
        }

    def prepare_document_ingestion_plan(self, payload):
        self.calls.append(("prepare_document_ingestion_plan", payload))
        return {
            "status": "planned",
            "ingestion_id": "doc_ingest_book",
            "document_id": "doc_book",
            "write_performed": False,
            "error": None,
        }

    def run_document_ingestion(self, payload):
        expected_keys = {
            "ingestion_id",
            "accept",
            "approved_by",
            "review_packets",
            "understanding_analysis",
            "visual_preview",
        }
        unexpected = set(payload) - expected_keys
        assert not unexpected, f"unexpected run_document_ingestion payload keys: {sorted(unexpected)}"
        self.calls.append(("run_document_ingestion", payload))
        return {
            "status": "partial",
            "ingestion_id": payload["ingestion_id"],
            "write_performed": bool(payload.get("accept")),
            "active_memory_write_performed": bool(payload.get("accept")),
            "graph_write_performed": bool(payload.get("accept")),
            "error": None,
        }

    def resume_document_ingestion(self, payload):
        expected_keys = {
            "ingestion_id",
            "accept",
            "approved_by",
            "review_packets",
            "understanding_analysis",
            "visual_preview",
        }
        unexpected = set(payload) - expected_keys
        assert not unexpected, f"unexpected resume_document_ingestion payload keys: {sorted(unexpected)}"
        self.calls.append(("resume_document_ingestion", payload))
        return {
            "status": "partial",
            "ingestion_id": payload["ingestion_id"],
            "resumed": True,
            "write_performed": bool(payload.get("accept")),
            "active_memory_write_performed": bool(payload.get("accept")),
            "graph_write_performed": bool(payload.get("accept")),
            "error": None,
        }

    def inspect_document_ingestion(self, payload):
        self.calls.append(("inspect_document_ingestion", payload))
        return {
            "status": "partial",
            "ingestion_id": payload.get("ingestion_id"),
            "document_id": payload.get("document_id"),
            "write_performed": False,
            "error": None,
        }

    def prepare_document_coverage_pass(self, payload):
        self.calls.append(("prepare_document_coverage_pass", payload))
        return {
            "status": "ok",
            "ingestion_id": payload["ingestion_record"]["ingestion_id"],
            "document_id": payload["ingestion_record"]["document_id"],
            "coverage_policy": payload["coverage_policy"],
            "write_performed": True,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None,
        }

    def prepare_knowledge_branch(self, payload):
        self.calls.append(("prepare_knowledge_branch", payload))
        return {
            "status": "open",
            "branch_id": "kbranch_review",
            "name": payload["name"],
            "write_performed": True,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None,
        }

    def prepare_knowledge_pr(self, payload):
        self.calls.append(("prepare_knowledge_pr", payload))
        return {
            "status": "open",
            "knowledge_pr_id": "kpr_review",
            "branch_id": payload["branch_id"],
            "title": payload["title"],
            "write_performed": True,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None,
        }

    def run_memory_ci(self, payload):
        self.calls.append(("run_memory_ci", payload))
        return {
            "status": "passed",
            "ci_run_id": "mci_review",
            "knowledge_pr_id": payload["knowledge_pr_id"],
            "write_performed": True,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None,
        }

    def inspect_knowledge_pr(self, payload):
        self.calls.append(("inspect_knowledge_pr", payload))
        return {
            "status": "mergeable",
            "knowledge_pr_id": payload["knowledge_pr_id"],
            "mergeable": True,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None,
        }

    def merge_knowledge_pr(self, payload):
        self.calls.append(("merge_knowledge_pr", payload))
        return {
            "status": "merged" if payload.get("accept") else "policy_denied",
            "knowledge_pr_id": payload["knowledge_pr_id"],
            "write_performed": bool(payload.get("accept")),
            "active_memory_write_performed": bool(payload.get("accept")),
            "graph_write_performed": False,
            "error": None,
        }

    def list_memory_benchmark_suites(self, payload):
        self.calls.append(("list_memory_benchmark_suites", payload))
        return {
            "schema_version": "2026-05-26.memory-benchmark-catalog.v1",
            "suites": [{"suite_id": "smoke"}],
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None,
        }

    def run_memory_benchmark(self, payload):
        self.calls.append(("run_memory_benchmark", payload))
        return {
            "schema_version": "2026-05-26.memory-benchmark.v1",
            "run_id": "benchmark_run:smoke",
            "suite_id": payload["suite_id"],
            "seed": payload["seed"],
            "summary": {"status": "pass"},
            "artifact_id": "sha256:" + "b" * 64,
            "write_performed": bool(payload.get("persist", True)),
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None,
        }

    def inspect_benchmark_run(self, payload):
        self.calls.append(("inspect_benchmark_run", payload))
        return {
            "schema_version": "2026-05-26.memory-benchmark.v1",
            "run_id": payload["run_id"],
            "status": "ok",
            "run": {"run_id": payload["run_id"]},
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None,
        }

    def prepare_document_ingestion_completion(self, payload):
        self.calls.append(("prepare_document_ingestion_completion", payload))
        return {
            "status": "ok",
            "document_id": payload["document_id"],
            "usable": True,
            "write_performed": False,
            "error": None,
        }

    def complete_document_ingestion(self, payload):
        self.calls.append(("complete_document_ingestion", payload))
        return {
            "status": "ok" if payload.get("accept") else "policy_denied",
            "document_id": payload["document_id"],
            "usable": bool(payload.get("accept")),
            "write_performed": bool(payload.get("accept")),
            "active_memory_write_performed": False,
            "graph_write_performed": bool(payload.get("accept")),
            "error": None,
        }

    def prepare_graph_readiness_report(self, payload):
        self.calls.append(("prepare_graph_readiness_report", payload))
        return {
            "status": "ok",
            "scope": payload.get("scope", "memory_os"),
            "inventory": {"memory_count": 1},
            "write_performed": False,
            "error": None,
        }

    def prepare_legacy_memory_os_migration(self, payload):
        self.calls.append(("prepare_legacy_memory_os_migration", payload))
        return {
            "operation": "prepare_legacy_memory_os_migration",
            "status": "prepared",
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "prepared_transaction_id": "txn-legacy",
            "error": None,
        }

    def apply_legacy_memory_os_migration(self, payload):
        self.calls.append(("apply_legacy_memory_os_migration", payload))
        return {
            "operation": "apply_legacy_memory_os_migration",
            "status": "ok" if payload.get("accept") else "policy_denied",
            "write_performed": bool(payload.get("accept")),
            "active_memory_write_performed": bool(payload.get("accept")),
            "graph_write_performed": False,
            "approved_by": payload.get("approved_by"),
            "idempotent_replay": False,
            "error": None,
        }

    def prepare_legacy_related_to_graph_migration(self, payload):
        self.calls.append(("prepare_legacy_related_to_graph_migration", payload))
        return {
            "operation": "prepare_legacy_related_to_graph_migration",
            "status": "prepared",
            "candidate_edge_count": 2,
            "graphable_edge_count": 2,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "prepared_transaction_id": "txn-legacy-graph",
            "error": None,
        }

    def apply_legacy_related_to_graph_migration(self, payload):
        self.calls.append(("apply_legacy_related_to_graph_migration", payload))
        return {
            "operation": "apply_legacy_related_to_graph_migration",
            "status": "ok" if payload.get("accept") else "policy_denied",
            "candidate_edge_count": 2,
            "graphable_edge_count": 2,
            "graph_edges_written": ["edge:legacy-related-to"],
            "write_performed": bool(payload.get("accept")),
            "active_memory_write_performed": False,
            "graph_write_performed": bool(payload.get("accept")),
            "approved_by": payload.get("approved_by"),
            "idempotent_replay": False,
            "error": None,
        }

    def prepare_graph_proposal_batch(self, payload):
        self.calls.append(("prepare_graph_proposal_batch", payload))
        return {
            "status": "ok",
            "scope": payload.get("scope", "memory_os"),
            "source_items": [],
            "validated_edges": [],
            "write_performed": False,
            "error": None,
        }

    def apply_graph_proposal_batch(self, payload):
        self.calls.append(("apply_graph_proposal_batch", payload))
        return {
            "status": "ok" if payload.get("accept") else "policy_denied",
            "scope": payload.get("scope", "memory_os"),
            "graph_edges_written": ["edge:memory:supports:concept:123"] if payload.get("accept") else [],
            "write_performed": bool(payload.get("accept")),
            "active_memory_write_performed": False,
            "graph_write_performed": bool(payload.get("accept")),
            "error": None,
        }

    def repair_graph_edge_refs(self, payload):
        self.calls.append(("repair_graph_edge_refs", payload))
        return {
            "operation": "repair_graph_edge_refs",
            "status": "ok" if payload.get("accept") else "prepared",
            "source": payload.get("source"),
            "candidate_count": 1,
            "write_performed": bool(payload.get("accept")),
            "active_memory_write_performed": False,
            "graph_write_performed": bool(payload.get("accept")),
            "error": None,
        }

    def repair_graph_store_reconciliation(self, payload):
        self.calls.append(("repair_graph_store_reconciliation", payload))
        return {
            "operation": "repair_graph_store_reconciliation",
            "status": "ok" if payload.get("accept") else "prepared",
            "repair_mode": payload.get("repair_mode", "upsert_missing"),
            "candidate_count": 1,
            "repaired_count": 1 if payload.get("accept") else 0,
            "write_performed": bool(payload.get("accept")),
            "active_memory_write_performed": False,
            "graph_write_performed": bool(payload.get("accept")),
            "error": None,
        }

    def list_source_drafts(self, payload):
        self.calls.append(("list_source_drafts", payload))
        return {
            "count": 1,
            "total": 1,
            "limit": payload["limit"],
            "offset": payload["offset"],
            "has_more": False,
            "drafts": [{"draft_id": "draft-a"}],
            "error": None,
        }

    def discard_source_draft(self, payload):
        self.calls.append(("discard_source_draft", payload))
        return {"discarded": True, "draft_id": payload["draft_id"], "error": None}

    def store_prepared_memory(self, payload):
        self.calls.append(("store_prepared_memory", payload))
        return {
            "stored_count": 1,
            "stored": [
                {
                    "index": 0,
                    "key": "daemon_source_memory",
                    "result": {"key": "daemon_source_memory", "chunk_count": 1},
                }
            ],
            "skipped": [],
            "error": None,
        }

    def delete_memory(self, payload):
        self.calls.append(("delete_memory", payload))
        return {"key": payload["key"], "deleted": True, "error": None}

    def query_knowledge(self, payload):
        self.calls.append(("query_knowledge", payload))
        return {
            "contract_version": "engram.knowledge.response.v0",
            "request_id": payload["request_id"],
            "status": "ok",
            "answer": {"project": payload["ask"]["project"]},
            "citations": [
                {
                    "citation_id": "cit_001",
                    "level": "chunk",
                    "source": "memory_os",
                    "key": "engram_direction",
                    "chunk_id": 0,
                }
            ],
            "freshness": {"state": "fresh"},
            "policy": {
                "unreviewed_sources_used": False,
                "unsupported_inferences_used": False,
                "review_state_available": False,
                "review_filter_enforced": False,
                "review_state_basis": "not_available_in_current_memory_os_records",
            },
            "budget_used": {
                "artifacts_built": 1,
                "artifacts_read": 0,
                "source_reads": 0,
                "tokens_out_estimate": 0,
            },
            "planner": {
                "strategy": "project_capsule",
                "methods_used": ["artifact"],
                "omissions": [],
                "budget": {
                    "requested": {"max_artifacts": 1, "max_source_reads": 12, "max_tokens_out": 2500},
                    "used": {
                        "artifacts_built": 1,
                        "artifacts_read": 0,
                        "source_reads": 0,
                        "tokens_out_estimate": 0,
                    },
                },
                "failure_receipts": [],
                "response_status": "ok",
            },
            "errors": [],
        }


def test_search_memories_uses_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    result = asyncio.run(server.search_memories("daemon check", retrieval_mode="hybrid"))

    assert result["results"][0]["key"] == "daemon_memory"
    assert client.calls[0][0] == "search_memories"
    assert client.calls[0][1]["retrieval_mode"] == "hybrid"


def test_check_duplicate_uses_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    payload = asyncio.run(server.check_duplicate("candidate_memory", "Candidate body"))

    assert payload["duplicate"] is True
    assert payload["match"]["existing_key"] == "daemon_memory"
    assert client.calls == [
        (
            "check_duplicate",
            {"key": "candidate_memory", "content": "Candidate body"},
        )
    ]


def test_read_tools_use_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    chunk = asyncio.run(server.retrieve_chunk("daemon_memory", 0))
    chunks = asyncio.run(server.retrieve_chunks([{"key": "daemon_memory", "chunk_id": 0}]))
    memory = asyncio.run(server.retrieve_memory("daemon_memory"))

    assert chunk["chunk"]["text"] == "chunk"
    assert chunks["found_count"] == 1
    assert memory["memory"]["content"] == "body"
    assert [call[0] for call in client.calls] == [
        "retrieve_chunk",
        "retrieve_chunks",
        "retrieve_memory",
    ]


def test_write_and_delete_tools_use_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    stored = asyncio.run(
        server.store_memory(
            key="daemon_memory",
            content="Daemon body.",
            title="Daemon Memory",
            tags=["daemon"],
            force=True,
        )
    )
    deleted = asyncio.run(server.delete_memory("daemon_memory"))

    assert "Stored: 'Daemon Memory'" in stored
    assert "Deleted memory: 'daemon_memory'" in deleted
    assert [call[0] for call in client.calls] == ["store_memory", "delete_memory"]


def test_query_knowledge_uses_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    payload = asyncio.run(
        server.query_knowledge(
            {
                "request_id": "req-server",
                "ask": {
                    "goal": "Get context.",
                    "task_type": "project_orientation",
                    "project": "Engram",
                },
            }
        )
    )

    assert payload["request_id"] == "req-server"
    assert payload["answer"]["project"] == "Engram"
    assert client.calls[-1][0] == "query_knowledge"


def test_update_memory_metadata_uses_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    payload = asyncio.run(
        server.update_memory_metadata(
            key="daemon_memory",
            title="Updated Daemon Memory",
            tags=["daemon", "metadata"],
        )
    )

    assert payload["updated"] is True
    assert payload["memory"]["title"] == "Updated Daemon Memory"
    assert client.calls == [
        (
            "update_memory_metadata",
            {
                "key": "daemon_memory",
                "title": "Updated Daemon Memory",
                "tags": ["daemon", "metadata"],
            },
        )
    ]


def test_repair_memory_metadata_uses_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    payload = asyncio.run(
        server.repair_memory_metadata(keys="daemon_memory", dry_run=False)
    )

    assert payload["repaired_count"] == 1
    assert payload["dry_run"] is False
    assert client.calls == [
        (
            "repair_memory_metadata",
            {"keys": ["daemon_memory"], "dry_run": False},
        )
    ]


def test_store_prepared_memory_uses_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    payload = asyncio.run(
        server.store_prepared_memory("draft-a", selected_items=[0], force=True)
    )

    assert payload["stored_count"] == 1
    assert payload["stored"][0]["key"] == "daemon_source_memory"
    assert client.calls == [
        (
            "store_prepared_memory",
            {"draft_id": "draft-a", "selected_items": [0], "force": True},
        )
    ]


def test_source_draft_lifecycle_uses_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    prepared = asyncio.run(
        server.prepare_source_memory(
            source_text="Decision: daemon owns source draft lifecycle.",
            source_type="handoff",
            source_uri="file:///handoff.md",
            project="Engram",
            domain="daemon",
            budget_chars=4000,
            pipeline="handoff",
        )
    )
    drafts = asyncio.run(
        server.list_source_drafts(project="Engram", status="draft", limit=10, offset=2)
    )
    discarded = asyncio.run(server.discard_source_draft("draft-a"))

    assert prepared["draft"]["draft_id"] == "draft-a"
    assert drafts["drafts"][0]["draft_id"] == "draft-a"
    assert discarded["discarded"] is True
    assert client.calls == [
        (
            "prepare_source_memory",
            {
                "source_text": "Decision: daemon owns source draft lifecycle.",
                "source_type": "handoff",
                "source_uri": "file:///handoff.md",
                "project": "Engram",
                "domain": "daemon",
                "budget_chars": 4000,
                "pipeline": "handoff",
            },
        ),
        (
            "list_source_drafts",
            {"project": "Engram", "status": "draft", "limit": 10, "offset": 2},
        ),
        ("discard_source_draft", {"draft_id": "draft-a"}),
    ]


def test_prepare_document_disassembly_uses_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    payload = asyncio.run(server.prepare_document_disassembly("C:/docs/book.pdf", max_pages=5))

    assert payload["error"] is None
    assert payload["disassembly"]["record_type"] == "document_disassembly_preview"
    assert client.calls == [
        (
            "prepare_document_disassembly",
            {
                "source_path": "C:/docs/book.pdf",
                "source_type": "pdf",
                "max_pages": 5,
                "page_range": None,
                "resume_token": None,
            },
        )
    ]


def test_document_intelligence_tools_use_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    document_record = {"document_id": "doc_1", "title": "Daemon Doc"}
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    asyncio.run(server.list_document_extractors())
    asyncio.run(server.preview_document_source_connector("local_path", "docs"))
    asyncio.run(
        server.prepare_document_coverage_workbench(
            source_path="C:/docs/book.pdf",
            document_record=document_record,
            visual_request={
                "request_id": "vis_req_1",
                "document_id": "doc_1",
                "image_refs": [{"source_uri": "file:///book.pdf", "page_number": 1}],
            },
            output_dir="C:/tmp/coverage",
        )
    )
    asyncio.run(server.prepare_document_intake_review("C:/docs/book.pdf"))
    asyncio.run(
        server.prepare_document_extraction_request(
            source_ref={"source_uri": "file:///book.pdf"},
            source_type="pdf",
            requested_outputs=["markdown"],
        )
    )
    asyncio.run(
        server.prepare_document_extraction_result(
            extraction_request={
                "request_id": "doc_req_1",
                "source_ref": {"source_uri": "file:///book.pdf"},
                "source_type": "pdf",
            },
            title="Daemon Book",
            content="Body",
            media_type="text/markdown",
        )
    )
    asyncio.run(
        server.preview_document_extraction(
            title="Daemon Book",
            source_uri="file:///book.pdf",
            source_type="pdf",
            content="Body",
            media_type="text/markdown",
        )
    )
    asyncio.run(
        server.prepare_visual_extraction_request(
            document_record=document_record,
            image_refs=[{"image_ref": "page:1"}],
            requested_capabilities=["ocr_text"],
        )
    )
    asyncio.run(
        server.preview_visual_extraction(
            document_record=document_record,
            observations=[
                {
                    "artifact_type": "ocr_block",
                    "source_ref": {"image_ref": "page:1"},
                    "text": "OCR",
                }
            ],
        )
    )
    asyncio.run(server.prepare_document_understanding_packet(document_record, {"summary": ["Summary"]}))
    asyncio.run(server.prepare_document_draft(document_record, {"summary": ["Summary"]}))
    asyncio.run(
        server.prepare_document_promotion_transaction(
            {"draft_id": "draft_1", "proposed_memories": [{"key": "doc"}], "proposed_edges": []},
            approved_by="reviewer",
            selected_memory_indexes=[0],
        )
    )
    asyncio.run(
        server.apply_document_promotion_transaction(
            {"transaction_id": "doc_promote_1"},
            accept=True,
            approved_by="reviewer",
            selected_operation_indexes=[0],
        )
    )

    assert [call[0] for call in client.calls] == [
        "list_document_extractors",
        "preview_document_source_connector",
        "prepare_document_coverage_workbench",
        "prepare_document_intake_review",
        "prepare_document_extraction_request",
        "prepare_document_extraction_result",
        "preview_document_extraction",
        "prepare_visual_extraction_request",
        "preview_visual_extraction",
        "prepare_document_understanding_packet",
        "prepare_document_draft",
        "prepare_document_promotion_transaction",
        "apply_document_promotion_transaction",
    ]


def test_thin_document_ingestion_tools_delegate_to_daemon(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setattr(server_daemon_client, "_daemon_client", lambda: client)

    planned = asyncio.run(
        server_daemon_client.prepare_document_ingestion_plan(
            source_path="/docs/book.pdf",
            project="Engram",
            domain="documents",
            page_window_size=10,
            budget={"max_windows": 2},
        )
    )
    run = asyncio.run(
        server_daemon_client.run_document_ingestion(
            ingestion_id="doc_ingest_book",
            accept=True,
            approved_by="agent-review",
            review_packets=[{"window_index": 0}],
            understanding_analysis={"summary": ["Window one"]},
            visual_preview={"status": "ok", "window_index": 0},
        )
    )
    resumed = asyncio.run(
        server_daemon_client.resume_document_ingestion(
            ingestion_id="doc_ingest_book",
            accept=True,
            approved_by="agent-review",
            review_packets=[{"window_index": 1}],
            understanding_analysis={"summary": ["Window two"]},
            visual_preview={"status": "ok", "window_index": 1},
        )
    )
    inspected = asyncio.run(
        server_daemon_client.inspect_document_ingestion(
            ingestion_id="doc_ingest_book",
            document_id="doc_book",
        )
    )

    assert planned["status"] == "planned"
    assert run["write_performed"] is True
    assert resumed["resumed"] is True
    assert inspected["document_id"] == "doc_book"
    assert client.calls == [
        (
            "prepare_document_ingestion_plan",
            {
                "source_path": "/docs/book.pdf",
                "project": "Engram",
                "domain": "documents",
                "profile": "graph_coverage",
                "page_window_size": 10,
                "analysis_policy": "defer",
                "approval_mode": "agent_authorized",
                "budget": {"max_windows": 2},
            },
        ),
        (
            "run_document_ingestion",
            {
                "ingestion_id": "doc_ingest_book",
                "accept": True,
                "approved_by": "agent-review",
                "review_packets": [{"window_index": 0}],
                "understanding_analysis": {"summary": ["Window one"]},
                "visual_preview": {"status": "ok", "window_index": 0},
            },
        ),
        (
            "resume_document_ingestion",
            {
                "ingestion_id": "doc_ingest_book",
                "accept": True,
                "approved_by": "agent-review",
                "review_packets": [{"window_index": 1}],
                "understanding_analysis": {"summary": ["Window two"]},
                "visual_preview": {"status": "ok", "window_index": 1},
            },
        ),
        (
            "inspect_document_ingestion",
            {"ingestion_id": "doc_ingest_book", "document_id": "doc_book"},
        ),
    ]


def test_document_coverage_pass_tools_delegate_to_daemon(monkeypatch):
    client = FakeDaemonClient()
    ingestion_record = {
        "ingestion_id": "doc_ingest_book",
        "document_id": "doc_book",
        "source": {"path": "/docs/book.pdf"},
    }
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    full_payload = asyncio.run(
        server.prepare_document_coverage_pass(
            ingestion_record=ingestion_record,
            review_packets=[{"window_index": 0}],
            coverage_policy="auto_local",
            coverage_options={"max_pages": 2},
        )
    )

    monkeypatch.setattr(server_daemon_client, "_daemon_client", lambda: client)
    thin_payload = asyncio.run(
        server_daemon_client.prepare_document_coverage_pass(
            ingestion_record=ingestion_record,
            review_packets=[{"window_index": 1}],
            coverage_policy="required",
            coverage_options={"max_pages": 3},
        )
    )

    assert full_payload["active_memory_write_performed"] is False
    assert thin_payload["graph_write_performed"] is False
    assert client.calls[-2:] == [
        (
            "prepare_document_coverage_pass",
            {
                "ingestion_record": ingestion_record,
                "review_packets": [{"window_index": 0}],
                "coverage_policy": "auto_local",
                "coverage_options": {"max_pages": 2},
            },
        ),
        (
            "prepare_document_coverage_pass",
            {
                "ingestion_record": ingestion_record,
                "review_packets": [{"window_index": 1}],
                "coverage_policy": "required",
                "coverage_options": {"max_pages": 3},
            },
        ),
    ]


def test_knowledge_pr_tools_use_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    branch = asyncio.run(
        server.prepare_knowledge_branch(
            name="Book review",
            source_refs=[{"kind": "document", "document_id": "doc_book"}],
            base_snapshot_ref="snapshot:before",
            metadata={"project": "Engram"},
        )
    )
    pr = asyncio.run(
        server.prepare_knowledge_pr(
            branch_id="kbranch_review",
            title="Promote reviewed book graph",
            proposed_operations=[{"operation_id": "op:graph:1", "kind": "graph_edge"}],
            source_refs=[{"kind": "document", "document_id": "doc_book"}],
            document_refs=[{"document_id": "doc_book"}],
            metadata={"domain": "documents"},
        )
    )
    ci = asyncio.run(
        server.run_memory_ci(
            knowledge_pr_id="kpr_review",
            gates=["gate_provenance"],
            ci_context={"retrieval_probe_count": 1},
        )
    )
    inspected = asyncio.run(server.inspect_knowledge_pr("kpr_review"))
    merged = asyncio.run(
        server.merge_knowledge_pr(
            knowledge_pr_id="kpr_review",
            accept=True,
            approved_by="agent-review",
            selected_operation_ids=["op:graph:1"],
            selected_operation_indexes=[0],
            ci_waivers=[{"gate_id": "gate_retrieval_regression"}],
        )
    )

    assert branch["branch_id"] == "kbranch_review"
    assert pr["knowledge_pr_id"] == "kpr_review"
    assert ci["status"] == "passed"
    assert inspected["mergeable"] is True
    assert merged["status"] == "merged"
    assert client.calls == [
        (
            "prepare_knowledge_branch",
            {
                "name": "Book review",
                "source_refs": [{"kind": "document", "document_id": "doc_book"}],
                "base_snapshot_ref": "snapshot:before",
                "metadata": {"project": "Engram"},
            },
        ),
        (
            "prepare_knowledge_pr",
            {
                "branch_id": "kbranch_review",
                "title": "Promote reviewed book graph",
                "proposed_operations": [{"operation_id": "op:graph:1", "kind": "graph_edge"}],
                "source_refs": [{"kind": "document", "document_id": "doc_book"}],
                "document_refs": [{"document_id": "doc_book"}],
                "metadata": {"domain": "documents"},
            },
        ),
        (
            "run_memory_ci",
            {
                "knowledge_pr_id": "kpr_review",
                "gates": ["gate_provenance"],
                "ci_context": {"retrieval_probe_count": 1},
            },
        ),
        ("inspect_knowledge_pr", {"knowledge_pr_id": "kpr_review"}),
        (
            "merge_knowledge_pr",
            {
                "knowledge_pr_id": "kpr_review",
                "accept": True,
                "approved_by": "agent-review",
                "selected_operation_ids": ["op:graph:1"],
                "selected_operation_indexes": [0],
                "ci_waivers": [{"gate_id": "gate_retrieval_regression"}],
            },
        ),
    ]


def test_thin_knowledge_pr_tools_delegate_to_daemon(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setattr(server_daemon_client, "_daemon_client", lambda: client)

    branch = asyncio.run(server_daemon_client.prepare_knowledge_branch("Book review"))
    pr = asyncio.run(server_daemon_client.prepare_knowledge_pr("kbranch_review", "Review PR"))
    ci = asyncio.run(server_daemon_client.run_memory_ci("kpr_review"))
    inspected = asyncio.run(server_daemon_client.inspect_knowledge_pr("kpr_review"))
    merged = asyncio.run(
        server_daemon_client.merge_knowledge_pr(
            "kpr_review",
            accept=True,
            approved_by="agent-review",
            selected_operation_indexes=[0],
        )
    )

    assert branch["branch_id"] == "kbranch_review"
    assert pr["knowledge_pr_id"] == "kpr_review"
    assert ci["status"] == "passed"
    assert inspected["mergeable"] is True
    assert merged["write_performed"] is True
    assert [call[0] for call in client.calls] == [
        "prepare_knowledge_branch",
        "prepare_knowledge_pr",
        "run_memory_ci",
        "inspect_knowledge_pr",
        "merge_knowledge_pr",
    ]


def test_memory_benchmark_tools_use_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    catalog = asyncio.run(server.list_memory_benchmark_suites("smoke"))
    run = asyncio.run(server.run_memory_benchmark(suite_id="smoke", seed=42, persist=True))
    inspected = asyncio.run(server.inspect_benchmark_run("benchmark_run:smoke"))

    assert catalog["suites"][0]["suite_id"] == "smoke"
    assert run["summary"]["status"] == "pass"
    assert inspected["run_id"] == "benchmark_run:smoke"
    assert client.calls[-3:] == [
        ("list_memory_benchmark_suites", {"suite_id": "smoke"}),
        ("run_memory_benchmark", {"suite_id": "smoke", "seed": 42, "persist": True}),
        ("inspect_benchmark_run", {"run_id": "benchmark_run:smoke"}),
    ]


def test_thin_memory_benchmark_tools_delegate_to_daemon(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setattr(server_daemon_client, "_daemon_client", lambda: client)

    catalog = asyncio.run(server_daemon_client.list_memory_benchmark_suites("smoke"))
    run = asyncio.run(server_daemon_client.run_memory_benchmark("smoke", seed=42, persist=True))
    inspected = asyncio.run(server_daemon_client.inspect_benchmark_run("benchmark_run:smoke"))

    assert catalog["suites"][0]["suite_id"] == "smoke"
    assert run["summary"]["status"] == "pass"
    assert inspected["run_id"] == "benchmark_run:smoke"
    assert [call[0] for call in client.calls[-3:]] == [
        "list_memory_benchmark_suites",
        "run_memory_benchmark",
        "inspect_benchmark_run",
    ]


def test_document_artifact_tools_use_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    prepared = asyncio.run(server.prepare_document_artifact_store({"status": "ok"}))
    stored = asyncio.run(server.store_document_artifact("txn-doc", accept=True, review_packet={"status": "ok"}))
    completion = asyncio.run(
        server.prepare_document_ingestion_completion(
            document_id="doc-book",
            artifact_id="doc_artifact:doc-book",
            visual_request={"request_id": "vis_req"},
            visual_preview={"status": "ok"},
            understanding_packet={"packet_id": "packet"},
            document_promotion_transaction={"transaction_id": "doc_promote"},
        )
    )
    completed = asyncio.run(
        server.complete_document_ingestion(
            document_id="doc-book",
            artifact_id="doc_artifact:doc-book",
            visual_request={"request_id": "vis_req"},
            visual_preview={"status": "ok"},
            understanding_packet={"packet_id": "packet"},
            document_promotion_transaction={"transaction_id": "doc_promote"},
            accept=True,
            approved_by="agent-review",
            selected_operation_indexes=[0],
        )
    )

    assert prepared["prepared_transaction_id"] == "txn-doc"
    assert stored["stored"] is True
    assert completion["usable"] is True
    assert completed["usable"] is True
    assert client.calls == [
        (
            "prepare_document_artifact_store",
            {"review_packet": {"status": "ok"}, "artifact_family": "document_evidence"},
        ),
        (
            "store_document_artifact",
            {
                "prepared_transaction_id": "txn-doc",
                "accept": True,
                "review_packet": {"status": "ok"},
            },
        ),
        (
            "prepare_document_ingestion_completion",
            {
                "document_id": "doc-book",
                "artifact_id": "doc_artifact:doc-book",
                "visual_request": {"request_id": "vis_req"},
                "visual_preview": {"status": "ok"},
                "understanding_packet": {"packet_id": "packet"},
                "document_promotion_transaction": {"transaction_id": "doc_promote"},
                "coverage_waivers": None,
            },
        ),
        (
            "complete_document_ingestion",
            {
                "document_id": "doc-book",
                "artifact_id": "doc_artifact:doc-book",
                "visual_request": {"request_id": "vis_req"},
                "visual_preview": {"status": "ok"},
                "understanding_packet": {"packet_id": "packet"},
                "document_promotion_transaction": {"transaction_id": "doc_promote"},
                "coverage_waivers": None,
                "accept": True,
                "approved_by": "agent-review",
                "selected_operation_indexes": [0],
            },
        ),
    ]


def test_graph_pipeline_tools_use_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    readiness = asyncio.run(
        server.prepare_graph_readiness_report(scope="memory_os", project="Engram", domain="graph", limit=25)
    )
    proposal = asyncio.run(
        server.prepare_graph_proposal_batch(
            scope="memory_os",
            project="Engram",
            domain="graph",
            source_refs=[{"kind": "memory", "key": "memory_alpha"}],
            candidate_graph_edges=[{"edge_type": "supports"}],
            limit=5,
            budget_chars=5000,
        )
    )
    applied = asyncio.run(
        server.apply_graph_proposal_batch(
            scope="memory_os",
            project="Engram",
            domain="graph",
            source_refs=[{"kind": "memory", "key": "memory_alpha"}],
            candidate_graph_edges=[{"edge_type": "supports"}],
            accept=True,
            approved_by="agent-review",
            limit=5,
            budget_chars=5000,
        )
    )
    repaired = asyncio.run(
        server.repair_graph_edge_refs(
            source="document_ingestion.structural",
            limit=25,
            accept=True,
            approved_by="agent-review",
        )
    )
    reconciled = asyncio.run(
        server.repair_graph_store_reconciliation(
            repair_mode="upsert_missing",
            limit=2500,
            accept=True,
            approved_by="agent-review",
        )
    )

    assert readiness["inventory"]["memory_count"] == 1
    assert proposal["write_performed"] is False
    assert applied["graph_write_performed"] is True
    assert repaired["graph_write_performed"] is True
    assert reconciled["graph_write_performed"] is True
    assert client.calls[-5:] == [
            (
                "prepare_graph_readiness_report",
                {
                    "scope": "memory_os",
                    "project": "Engram",
                    "exact_project_match": False,
                    "domain": "graph",
                    "limit": 25,
                },
            ),
        (
            "prepare_graph_proposal_batch",
            {
                "scope": "memory_os",
                "project": "Engram",
                "domain": "graph",
                "source_refs": [{"kind": "memory", "key": "memory_alpha"}],
                "limit": 5,
                "budget_chars": 5000,
                "candidate_graph_edges": [{"edge_type": "supports"}],
            },
        ),
        (
            "apply_graph_proposal_batch",
            {
                "scope": "memory_os",
                "project": "Engram",
                "domain": "graph",
                "source_refs": [{"kind": "memory", "key": "memory_alpha"}],
                "candidate_graph_edges": [{"edge_type": "supports"}],
                "accept": True,
                "approved_by": "agent-review",
                "limit": 5,
                "budget_chars": 5000,
            },
        ),
        (
            "repair_graph_edge_refs",
            {
                "source": "document_ingestion.structural",
                "limit": 25,
                "accept": True,
                "approved_by": "agent-review",
            },
        ),
        (
            "repair_graph_store_reconciliation",
            {
                "repair_mode": "upsert_missing",
                "limit": 2500,
                "accept": True,
                "approved_by": "agent-review",
            },
        ),
    ]


def test_legacy_migration_tools_use_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    prepared = asyncio.run(
        server.prepare_legacy_memory_os_migration(
            legacy_dir="data/memories",
            include_details=True,
        )
    )
    applied = asyncio.run(
        server.apply_legacy_memory_os_migration(
            legacy_dir="data/memories",
            accept=True,
            approved_by="agent-review",
            include_details=False,
        )
    )

    assert prepared["write_performed"] is False
    assert prepared["prepared_transaction_id"] == "txn-legacy"
    assert applied["write_performed"] is True
    assert applied["approved_by"] == "agent-review"
    assert client.calls[-2:] == [
        (
            "prepare_legacy_memory_os_migration",
            {"legacy_dir": "data/memories", "include_details": True},
        ),
        (
            "apply_legacy_memory_os_migration",
            {
                "legacy_dir": "data/memories",
                "accept": True,
                "approved_by": "agent-review",
                "include_details": False,
            },
        ),
    ]


def test_legacy_related_to_graph_tools_use_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    prepared = asyncio.run(
        server.prepare_legacy_related_to_graph_migration(
            legacy_dir="data/memories",
            include_details=True,
        )
    )
    applied = asyncio.run(
        server.apply_legacy_related_to_graph_migration(
            legacy_dir="data/memories",
            accept=True,
            approved_by="agent-review",
            include_details=False,
        )
    )

    assert prepared["write_performed"] is False
    assert prepared["prepared_transaction_id"] == "txn-legacy-graph"
    assert applied["write_performed"] is True
    assert applied["active_memory_write_performed"] is False
    assert applied["graph_write_performed"] is True
    assert applied["approved_by"] == "agent-review"
    assert client.calls[-2:] == [
        (
            "prepare_legacy_related_to_graph_migration",
            {"legacy_dir": "data/memories", "include_details": True},
        ),
        (
            "apply_legacy_related_to_graph_migration",
            {
                "legacy_dir": "data/memories",
                "accept": True,
                "approved_by": "agent-review",
                "include_details": False,
            },
        ),
    ]


def test_daemon_client_protocol_advertises_stable_document_workflow():
    protocol = server_daemon_client.memory_protocol()
    registry_sections = build_memory_protocol_sections(thin_client=True)

    assert protocol["document_workflow"] == STABLE_DOCUMENT_WORKFLOW
    assert protocol["tool_groups"] == registry_sections["tool_groups"]
    assert protocol["aliases"] == registry_sections["aliases"]
    assert protocol["knowledge_contract"] == registry_sections["knowledge_contract"]
    assert protocol["document_workflow"] == registry_sections["document_workflow"]
    assert protocol["document_artifact_workflow"] == registry_sections["document_artifact_workflow"]
    assert protocol["knowledge_pr_workflow"] == registry_sections["knowledge_pr_workflow"]
    assert protocol["benchmark_workflow"] == registry_sections["benchmark_workflow"]
    assert protocol["sync_transport_workflow"] == registry_sections["sync_transport_workflow"]
    assert protocol["canonical_tools"] == registry_sections["canonical_tools"]
    assert validate_protocol_sections(protocol, thin_client=True) == []
    assert set(STABLE_DOCUMENT_WORKFLOW).issubset(set(protocol["canonical_tools"]))
    assert set(KNOWLEDGE_PR_WORKFLOW).issubset(set(protocol["canonical_tools"]))
    assert set(BENCHMARK_WORKFLOW).issubset(set(protocol["canonical_tools"]))


def test_daemon_client_document_tool_docstrings_preserve_no_write_contract():
    write_tools = {
        "apply_document_promotion_transaction",
        "run_document_ingestion",
        "resume_document_ingestion",
    }
    for tool_name in [tool for tool in STABLE_DOCUMENT_WORKFLOW if tool not in write_tools]:
        doc = inspect.getdoc(getattr(server_daemon_client, tool_name))

        assert doc is not None
        normalized = doc.lower()
        assert "no-write" in normalized or "does not write" in normalized or "without writing" in normalized
        if tool_name not in {"prepare_document_ingestion_plan", "inspect_document_ingestion"}:
            assert "promot" in normalized

    for tool_name in write_tools:
        doc = inspect.getdoc(getattr(server_daemon_client, tool_name)) or ""
        assert "write" in doc.lower()
        assert "accept=True" in doc
        assert "explicit" in doc.lower()
