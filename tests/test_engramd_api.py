from __future__ import annotations

import time
import json
import base64
from concurrent.futures import ThreadPoolExecutor, TimeoutError

from core.engramd_api import EngramDaemonAPI
from core.graph_store import JsonGraphStore
from core.memory_limits import MAX_DIRECT_MEMORY_CHARS
from core.memory_os._records import list_records, read_record
from core.memory_os.runtime import MemoryOSRuntime
from core.memory_os.sync_transport import store_inbound_sync_bundle
from core.vector_index import InMemoryVectorIndex


class FakeMemoryManager:
    def __init__(self):
        self.stored = None
        self.deleted = []
        self.updated = None

    def get_stats(self):
        return {
            "total_memories": 2,
            "total_chunks": 3,
            "storage_size": "12 KB",
        }

    async def search_memories_structured_async(self, query, **kwargs):
        return {
            "query": query,
            "count": 1,
            "results": [
                {
                    "key": "daemon_memory",
                    "chunk_id": 0,
                    "title": "Daemon Memory",
                    "score": 0.9,
                    "snippet": "Daemon-owned search result.",
                    "tags": ["daemon"],
                }
            ],
            "error": None,
            "kwargs": kwargs,
        }

    async def check_duplicate_async(self, key, content):
        return {
            "key": key,
            "duplicate": True,
            "match": {
                "status": "duplicate",
                "existing_key": "daemon_memory",
                "existing_title": "Daemon Memory",
                "score": 0.97,
            },
        }

    async def retrieve_chunks_async(self, requests):
        return [
            {
                "key": request["key"],
                "chunk_id": request["chunk_id"],
                "found": True,
                "text": f"chunk {request['chunk_id']}",
                "title": "Daemon Memory",
                "section_title": "Runtime",
                "heading_path": ["Daemon Memory", "Runtime"],
                "chunk_kind": "paragraph",
                "error": None,
            }
            for request in requests
        ]

    async def retrieve_memory_async(self, key):
        return {
            "key": key,
            "title": "Daemon Memory",
            "content": "Full memory body.",
        }

    async def store_memory_async(self, **kwargs):
        self.stored = kwargs
        return {
            "key": kwargs["key"],
            "title": kwargs["title"],
            "chunk_count": 1,
            "chars": len(kwargs["content"]),
        }

    async def update_memory_metadata_async(self, key, **changes):
        self.updated = {"key": key, "changes": changes}
        return {
            "key": key,
            "title": changes.get("title", "Daemon Memory"),
            "tags": changes.get("tags", []),
            "project": changes.get("project"),
            "domain": changes.get("domain"),
            "status": changes.get("status", "active"),
            "canonical": changes.get("canonical"),
        }

    async def repair_memory_metadata_async(self, keys, dry_run=True):
        return {
            "requested_count": len(keys),
            "repaired_count": 0 if dry_run else len(keys),
            "dry_run": dry_run,
            "repairs": [
                {
                    "key": key,
                    "repaired": not dry_run,
                    "issues": [],
                }
                for key in keys
            ],
        }

    async def delete_memory_async(self, key):
        self.deleted.append(key)
        return key == "daemon_memory"


class FailingStatsMemoryManager(FakeMemoryManager):
    def get_stats(self):
        raise RuntimeError("legacy stats unavailable")

    def get_json_fallback_stats(self, *, chroma_error=None):
        return {
            "total_memories": 2,
            "total_chunks": None,
            "chroma_error": chroma_error,
        }


class ContentionMemoryManager(FakeMemoryManager):
    def __init__(self):
        super().__init__()
        self.active_calls = 0
        self.max_active_calls = 0

    async def search_memories_structured_async(self, query, **kwargs):
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        time.sleep(0.01)
        self.active_calls -= 1
        return await super().search_memories_structured_async(query, **kwargs)


class FakeSourceIntakeManager:
    def __init__(self, draft=None):
        self.prepared = None
        self.listed = None
        self.discarded = None
        self.draft = draft or {
            "draft_id": "draft-a",
            "status": "draft",
            "proposed_memories": [
                {
                    "key": "daemon_source_memory",
                    "content": "Promoted source body.",
                    "title": "Daemon Source Memory",
                    "tags": ["source", "daemon"],
                    "related_to": [],
                    "project": "Engram",
                    "domain": "source-intake",
                    "status": "active",
                    "canonical": False,
                }
            ],
        }

    def prepare_source_memory(self, **kwargs):
        self.prepared = kwargs
        return self.draft

    def list_source_drafts(self, **kwargs):
        self.listed = kwargs
        return {
            "count": 1,
            "total": 1,
            "limit": kwargs["limit"],
            "offset": kwargs["offset"],
            "has_more": False,
            "drafts": [self.draft],
            "error": None,
        }

    def discard_source_draft(self, draft_id):
        self.discarded = draft_id
        return {"discarded": True, "draft_id": draft_id, "error": None}

    def get_source_draft(self, draft_id):
        if draft_id == self.draft.get("draft_id"):
            return self.draft
        return None


def real_memory_os_runtime(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path / "memory_os",
        embed_text=lambda text: [1.0, 0.0] if str(text).strip() else [0.0, 1.0],
        vector_index=InMemoryVectorIndex(),
        graph_store=JsonGraphStore(tmp_path / "edges.json"),
    )
    runtime.initialize()
    return runtime


def fake_document_disassembler(**kwargs):
    if not kwargs.get("source_path"):
        raise ValueError("source_path is required")
    return {
        "record_type": "document_disassembly_preview",
        "source": {"path": kwargs["source_path"]},
        "document": {"source_type": kwargs.get("source_type"), "page_limit": kwargs.get("max_pages")},
        "write_performed": False,
        "active_memory_write_performed": False,
        "error": None,
    }


class FakeDocumentWorkflow:
    def __init__(self):
        self.calls = []

    def run_stage(self, stage_name, request):
        result_keys = {
            "list_document_extractors": "catalog",
            "prepare_document_disassembly": "disassembly",
            "prepare_document_coverage_workbench": "workbench",
            "prepare_document_extraction_request": "request",
            "prepare_document_extraction_result": "result",
            "preview_document_extraction": "preview",
            "prepare_visual_extraction_request": "request",
            "preview_visual_extraction": "preview",
            "prepare_document_understanding_packet": "packet",
            "prepare_document_draft": "draft",
            "prepare_document_promotion_transaction": "transaction",
        }
        if stage_name == "list_document_extractors":
            result = self.list_document_extractors()
        else:
            result = getattr(self, stage_name)(**request)
        result_key = result_keys.get(stage_name)
        if result_key is None:
            return result
        return {result_key: result, "error": None}

    def list_document_extractors(self):
        self.calls.append(("list_document_extractors", {}))
        return {"extractors": [{"extractor_id": "fake"}], "error": None}

    def preview_document_source_connector(self, **kwargs):
        self.calls.append(("preview_document_source_connector", kwargs))
        return {"preview": kwargs, "error": None}

    def prepare_document_disassembly(self, **kwargs):
        self.calls.append(("prepare_document_disassembly", kwargs))
        return {"disassembly": {"source": {"path": kwargs["source_path"]}}, "error": None}

    def prepare_document_coverage_workbench(self, **kwargs):
        self.calls.append(("prepare_document_coverage_workbench", kwargs))
        return {"workbench": {"source": {"path": kwargs["source_path"]}}, "error": None}

    def prepare_document_intake_review(self, **kwargs):
        self.calls.append(("prepare_document_intake_review", kwargs))
        return {"status": "ok", "source": {"source_path": kwargs["source_path"]}, "error": None}

    def prepare_document_extraction_request(self, **kwargs):
        self.calls.append(("prepare_document_extraction_request", kwargs))
        return {"extraction_request": kwargs, "error": None}

    def prepare_document_extraction_result(self, **kwargs):
        self.calls.append(("prepare_document_extraction_result", kwargs))
        return {"extraction_result": kwargs, "error": None}

    def preview_document_extraction(self, **kwargs):
        self.calls.append(("preview_document_extraction", kwargs))
        return {"document": {"title": kwargs["title"]}, "error": None}

    def prepare_visual_extraction_request(self, **kwargs):
        self.calls.append(("prepare_visual_extraction_request", kwargs))
        return {"visual_request": kwargs, "error": None}

    def preview_visual_extraction(self, **kwargs):
        self.calls.append(("preview_visual_extraction", kwargs))
        return {"visual_preview": kwargs, "error": None}

    def prepare_document_understanding_packet(self, **kwargs):
        self.calls.append(("prepare_document_understanding_packet", kwargs))
        return {"understanding_packet": kwargs, "error": None}

    def prepare_document_draft(self, **kwargs):
        self.calls.append(("prepare_document_draft", kwargs))
        return {"document_draft": kwargs, "error": None}

    def prepare_document_promotion_transaction(self, **kwargs):
        self.calls.append(("prepare_document_promotion_transaction", kwargs))
        return {"transaction": kwargs, "error": None}


class BoundaryOnlyDocumentWorkflow:
    def __init__(self):
        self.calls = []

    def run_stage(self, stage_name, request):
        self.calls.append((stage_name, dict(request)))
        return {
            "preview": {
                "stage": stage_name,
                "request": dict(request),
            },
            "error": None,
        }


class FakeMemoryOSRuntime:
    def __init__(self):
        self.source_jobs = []
        self.calls = []
        self.run_queued_count = 0
        self._retrieval_state = {"status": "ready", "ready": True, "error": None}

    @property
    def retrieval_ready(self):
        return bool(self._retrieval_state.get("ready"))

    @retrieval_ready.setter
    def retrieval_ready(self, value):
        self._retrieval_state = {
            "status": "ready" if value else "rebuilding",
            "ready": bool(value),
            "error": None,
        }

    def retrieval_state(self):
        return dict(self._retrieval_state)

    def status(self):
        return {
            "status": "ok",
            "root": "C:/Dev/Engram/data/memory_os",
            "components": {
                "ledger": {"path": "C:/Dev/Engram/data/memory_os/ledger.sqlite3"},
                "retrieval": {
                    "backend": "LanceDBVectorIndex",
                    "state": {
                        **self.retrieval_state(),
                        "manifest": {
                            "source_count": 23,
                            "indexed_count": 23,
                            "stats": {"document_count": 23},
                        },
                    },
                },
                "graph": {
                    "backend": "KuzuGraphStore",
                    "state": {
                        "status": "reconciled",
                        "ledger": {"edge_count": 37},
                    },
                },
                "runtime_preflight": {
                    "ledger": {
                        "size_bytes": 4096,
                        "tables": {
                            "sources": 5,
                            "documents": 7,
                            "chunks": 23,
                            "memories": 11,
                            "graph_edges": 37,
                        },
                    },
                },
            },
        }

    def prepare_source_import_job(self, **kwargs):
        self.source_jobs.append(kwargs)
        return {
            "job_id": "job:source",
            "job_kind": "source_import",
            "status": "queued",
            "payload": kwargs,
        }

    def prepare_legacy_memory_os_migration(self, **kwargs):
        self.calls.append(("prepare_legacy_memory_os_migration", kwargs))
        return {
            "operation": "prepare_legacy_memory_os_migration",
            "status": "prepared",
            "legacy_dir": str(kwargs["legacy_dir"]),
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "prepared_transaction_id": "txn-legacy",
            "error": None,
        }

    def apply_legacy_memory_os_migration(self, **kwargs):
        self.calls.append(("apply_legacy_memory_os_migration", kwargs))
        return {
            "operation": "apply_legacy_memory_os_migration",
            "status": "ok" if kwargs.get("accept") else "policy_denied",
            "legacy_dir": str(kwargs["legacy_dir"]),
            "write_performed": bool(kwargs.get("accept")),
            "active_memory_write_performed": bool(kwargs.get("accept")),
            "graph_write_performed": False,
            "approved_by": kwargs.get("approved_by"),
            "idempotent_replay": False,
            "error": None,
        }

    def prepare_legacy_related_to_graph_migration(self, **kwargs):
        self.calls.append(("prepare_legacy_related_to_graph_migration", kwargs))
        return {
            "operation": "prepare_legacy_related_to_graph_migration",
            "status": "prepared",
            "legacy_dir": str(kwargs["legacy_dir"]),
            "candidate_edge_count": 2,
            "graphable_edge_count": 2,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "prepared_transaction_id": "txn-legacy-graph",
            "error": None,
        }

    def apply_legacy_related_to_graph_migration(self, **kwargs):
        self.calls.append(("apply_legacy_related_to_graph_migration", kwargs))
        return {
            "operation": "apply_legacy_related_to_graph_migration",
            "status": "ok" if kwargs.get("accept") else "policy_denied",
            "legacy_dir": str(kwargs["legacy_dir"]),
            "candidate_edge_count": 2,
            "graphable_edge_count": 2,
            "graph_edges_written": ["edge:legacy-related-to"],
            "write_performed": bool(kwargs.get("accept")),
            "active_memory_write_performed": False,
            "graph_write_performed": bool(kwargs.get("accept")),
            "approved_by": kwargs.get("approved_by"),
            "idempotent_replay": False,
            "error": None,
        }

    def search_memories(self, **kwargs):
        self.calls.append(("search_memories", kwargs))
        return {
            "query": kwargs["query"],
            "backend": "memory_os",
            "count": 1,
            "results": [{"key": "runtime_memory", "chunk_id": 0, "title": "Runtime"}],
            "error": None,
        }

    def retrieve_chunk(self, key, chunk_id):
        self.calls.append(("retrieve_chunk", {"key": key, "chunk_id": chunk_id}))
        return {
            "key": key,
            "chunk_id": chunk_id,
            "found": True,
            "chunk": {"title": "Runtime", "text": "runtime chunk"},
            "error": None,
        }

    def retrieve_memory(self, key):
        self.calls.append(("retrieve_memory", {"key": key}))
        return {
            "key": key,
            "found": True,
            "memory": {"key": key, "content": "runtime memory"},
            "error": None,
        }

    def store_memory(self, **kwargs):
        self.calls.append(("store_memory", kwargs))
        return {
            "key": kwargs["key"],
            "title": kwargs["title"],
            "chunk_count": 1,
            "chars": len(kwargs["content"]),
            "storage_backend": "memory_os",
        }

    def check_duplicate(self, key, content):
        self.calls.append(("check_duplicate", {"key": key, "content": content}))
        return {"key": key, "duplicate": False, "match": None, "error": None}

    def update_memory_metadata(self, key, **changes):
        self.calls.append(("update_memory_metadata", {"key": key, "changes": changes}))
        return {
            "key": key,
            "updated": True,
            "memory": {"key": key, **changes},
            "error": None,
        }

    def repair_memory_metadata(self, keys, dry_run=True):
        self.calls.append(("repair_memory_metadata", {"keys": keys, "dry_run": dry_run}))
        return {
            "requested_count": len(keys),
            "repaired_count": 0,
            "dry_run": dry_run,
            "repairs": [],
            "error": None,
        }

    def repair_document_metadata(self, *, project=None, document_ids=None, accept=False, approved_by=None):
        self.calls.append(
            (
                "repair_document_metadata",
                {
                    "project": project,
                    "document_ids": document_ids,
                    "accept": accept,
                    "approved_by": approved_by,
                },
            )
        )
        return {
            "status": "ok" if accept else "prepared",
            "repaired_document_count": 1 if accept else 0,
            "repairs": [{"document_id": "doc_book", "project": project}],
            "write_performed": bool(accept),
            "active_memory_write_performed": False,
            "error": None,
        }

    def delete_memory(self, key):
        self.calls.append(("delete_memory", {"key": key}))
        return {"key": key, "deleted": True, "error": None}

    def prepare_document_artifact_store(self, review_packet, *, artifact_family="document_evidence"):
        self.calls.append(
            (
                "prepare_document_artifact_store",
                {"review_packet": review_packet, "artifact_family": artifact_family},
            )
        )
        return {
            "status": "prepared",
            "prepared_transaction_id": "txn-doc",
            "error": None,
        }

    def store_document_artifact(self, prepared_transaction_id, *, accept=False, review_packet=None):
        self.calls.append(
            (
                "store_document_artifact",
                {
                    "prepared_transaction_id": prepared_transaction_id,
                    "accept": accept,
                    "review_packet": review_packet,
                },
            )
        )
        return {
            "status": "ok" if accept else "policy_denied",
            "prepared_transaction_id": prepared_transaction_id,
            "stored": bool(accept),
            "error": None,
        }

    def prepare_document_ingestion_completion(
        self,
        *,
        document_id,
        artifact_id=None,
        visual_request=None,
        visual_preview=None,
        understanding_packet=None,
        document_promotion_transaction=None,
        coverage_waivers=None,
    ):
        self.calls.append(
            (
                "prepare_document_ingestion_completion",
                {
                    "document_id": document_id,
                    "artifact_id": artifact_id,
                    "visual_request": visual_request,
                    "visual_preview": visual_preview,
                    "understanding_packet": understanding_packet,
                    "document_promotion_transaction": document_promotion_transaction,
                    "coverage_waivers": coverage_waivers,
                },
            )
        )
        return {
            "status": "ok",
            "document_id": document_id,
            "usable": True,
            "write_performed": False,
            "error": None,
        }

    def complete_document_ingestion(
        self,
        *,
        document_id,
        artifact_id=None,
        visual_request=None,
        visual_preview=None,
        understanding_packet=None,
        document_promotion_transaction=None,
        coverage_waivers=None,
        accept=False,
        approved_by=None,
        selected_operation_indexes=None,
    ):
        self.calls.append(
            (
                "complete_document_ingestion",
                {
                    "document_id": document_id,
                    "artifact_id": artifact_id,
                    "visual_request": visual_request,
                    "visual_preview": visual_preview,
                    "understanding_packet": understanding_packet,
                    "document_promotion_transaction": document_promotion_transaction,
                    "coverage_waivers": coverage_waivers,
                    "accept": accept,
                    "approved_by": approved_by,
                    "selected_operation_indexes": selected_operation_indexes,
                },
            )
        )
        return {
            "status": "ok" if accept else "policy_denied",
            "document_id": document_id,
            "usable": bool(accept),
            "write_performed": bool(accept),
            "graph_write_performed": bool(accept),
            "active_memory_write_performed": False,
            "error": None,
        }

    def prepare_document_ingestion_plan(self, **kwargs):
        self.calls.append(("prepare_document_ingestion_plan", kwargs))
        return {
            "status": "planned",
            "ingestion_id": "doc_ingest_book",
            "document_id": "doc_book",
            "source_path": kwargs["source_path"],
            "next_action": {"tool": "run_document_ingestion", "ingestion_id": "doc_ingest_book"},
            "write_performed": False,
            "error": None,
        }

    def run_document_ingestion(
        self,
        *,
        ingestion_id,
        accept=False,
        approved_by=None,
        review_packets=None,
        understanding_analysis=None,
        visual_preview=None,
    ):
        self.calls.append(
            (
                "run_document_ingestion",
                {
                    "ingestion_id": ingestion_id,
                    "accept": accept,
                    "approved_by": approved_by,
                    "review_packets": review_packets,
                    "understanding_analysis": understanding_analysis,
                    "visual_preview": visual_preview,
                },
            )
        )
        return {
            "status": "partial",
            "ingestion_id": ingestion_id,
            "write_performed": bool(accept),
            "active_memory_write_performed": bool(accept),
            "graph_write_performed": bool(accept),
            "error": None,
        }

    def enqueue_document_ingestion_run(self, **kwargs):
        self.calls.append(("enqueue_document_ingestion_run", kwargs))
        return {
            "status": "queued",
            "ingestion_id": kwargs["ingestion_id"],
            "background_job": {"job_id": "job:document-ingestion", "status": "queued"},
            "next_action": {"tool": "inspect_document_ingestion", "ingestion_id": kwargs["ingestion_id"]},
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None,
        }

    def enqueue_document_ingestion_resume(self, **kwargs):
        self.calls.append(("enqueue_document_ingestion_resume", kwargs))
        return {
            "status": "queued",
            "ingestion_id": kwargs["ingestion_id"],
            "resumed": True,
            "background_job": {"job_id": "job:document-ingestion-resume", "status": "queued"},
            "next_action": {"tool": "inspect_document_ingestion", "ingestion_id": kwargs["ingestion_id"]},
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None,
        }

    def run_queued_document_ingestion(self, *, worker_id):
        self.run_queued_count += 1
        self.calls.append(("run_queued_document_ingestion", {"worker_id": worker_id}))
        if self.run_queued_count > 1:
            return {"status": "idle", "worker_id": worker_id, "processed": False, "error": None}
        return {"status": "partial", "worker_id": worker_id, "processed": True, "error": None}

    def resume_document_ingestion(
        self,
        *,
        ingestion_id,
        accept=False,
        approved_by=None,
        review_packets=None,
        understanding_analysis=None,
        visual_preview=None,
    ):
        self.calls.append(
            (
                "resume_document_ingestion",
                {
                    "ingestion_id": ingestion_id,
                    "accept": accept,
                    "approved_by": approved_by,
                    "review_packets": review_packets,
                    "understanding_analysis": understanding_analysis,
                    "visual_preview": visual_preview,
                },
            )
        )
        return {
            "status": "partial",
            "ingestion_id": ingestion_id,
            "resumed": True,
            "write_performed": bool(accept),
            "active_memory_write_performed": bool(accept),
            "graph_write_performed": bool(accept),
            "error": None,
        }

    def inspect_document_ingestion(self, **kwargs):
        self.calls.append(("inspect_document_ingestion", kwargs))
        return {
            "status": "partial",
            "ingestion_id": kwargs.get("ingestion_id"),
            "document_id": kwargs.get("document_id"),
            "next_action": {"tool": "resume_document_ingestion", "ingestion_id": kwargs.get("ingestion_id")},
            "write_performed": False,
            "error": None,
        }

    def prepare_document_coverage_pass(self, **kwargs):
        self.calls.append(("prepare_document_coverage_pass", kwargs))
        return {
            "status": "ok",
            "ingestion_id": kwargs["ingestion_record"]["ingestion_id"],
            "document_id": kwargs["ingestion_record"]["document_id"],
            "coverage_policy": kwargs.get("coverage_policy", "auto_local"),
            "write_performed": True,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None,
        }

    def prepare_knowledge_branch(self, **kwargs):
        self.calls.append(("prepare_knowledge_branch", kwargs))
        return {
            "status": "open",
            "branch_id": "kbranch_review",
            "name": kwargs["name"],
            "write_performed": True,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None,
        }

    def prepare_knowledge_pr(self, **kwargs):
        self.calls.append(("prepare_knowledge_pr", kwargs))
        return {
            "status": "open",
            "knowledge_pr_id": "kpr_review",
            "branch_id": kwargs["branch_id"],
            "title": kwargs["title"],
            "write_performed": True,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None,
        }

    def run_memory_ci(self, **kwargs):
        self.calls.append(("run_memory_ci", kwargs))
        return {
            "status": "passed",
            "ci_run_id": "mci_review",
            "knowledge_pr_id": kwargs["knowledge_pr_id"],
            "write_performed": True,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None,
        }

    def inspect_knowledge_pr(self, **kwargs):
        self.calls.append(("inspect_knowledge_pr", kwargs))
        return {
            "status": "mergeable",
            "knowledge_pr_id": kwargs["knowledge_pr_id"],
            "mergeable": True,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None,
        }

    def list_memory_benchmark_suites(self, **kwargs):
        self.calls.append(("list_memory_benchmark_suites", kwargs))
        return {
            "schema_version": "2026-05-26.memory-benchmark-catalog.v1",
            "suites": [{"suite_id": "smoke", "scenario_ids": ["memory_retrieval_exact_project"]}],
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None,
        }

    def run_memory_benchmark(self, **kwargs):
        self.calls.append(("run_memory_benchmark", kwargs))
        return {
            "schema_version": "2026-05-26.memory-benchmark.v1",
            "status": "ok",
            "run_id": "benchmark_run:smoke",
            "suite_id": kwargs["suite_id"],
            "seed": kwargs["seed"],
            "summary": {"status": "pass"},
            "artifact_id": "sha256:" + "a" * 64,
            "write_performed": bool(kwargs.get("persist", True)),
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None,
        }

    def inspect_benchmark_run(self, **kwargs):
        self.calls.append(("inspect_benchmark_run", kwargs))
        return {
            "schema_version": "2026-05-26.memory-benchmark.v1",
            "status": "ok",
            "run_id": kwargs["run_id"],
            "run": {"run_id": kwargs["run_id"], "summary": {"status": "pass"}},
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None,
        }

    def merge_knowledge_pr(self, **kwargs):
        self.calls.append(("merge_knowledge_pr", kwargs))
        return {
            "status": "merged" if kwargs.get("accept") else "policy_denied",
            "knowledge_pr_id": kwargs["knowledge_pr_id"],
            "write_performed": bool(kwargs.get("accept")),
            "active_memory_write_performed": bool(kwargs.get("accept")),
            "graph_write_performed": False,
            "error": None,
        }

    def apply_document_promotion_transaction(
        self,
        document_promotion_transaction,
        *,
        accept=False,
        approved_by=None,
        selected_operation_indexes=None,
    ):
        self.calls.append(
            (
                "apply_document_promotion_transaction",
                {
                    "document_promotion_transaction": document_promotion_transaction,
                    "accept": accept,
                    "approved_by": approved_by,
                    "selected_operation_indexes": selected_operation_indexes,
                },
            )
        )
        return {
            "status": "ok" if accept else "policy_denied",
            "write_performed": bool(accept),
            "active_memory_write_performed": bool(accept),
            "graph_write_performed": False,
            "error": None,
        }

    def prepare_graph_readiness_report(
        self,
        *,
        scope="memory_os",
        project=None,
        exact_project_match=False,
        domain=None,
        limit=50,
    ):
        self.calls.append(
            (
                "prepare_graph_readiness_report",
                {
                    "scope": scope,
                    "project": project,
                    "exact_project_match": exact_project_match,
                    "domain": domain,
                    "limit": limit,
                },
            )
        )
        return {
            "status": "ok",
            "scope": scope,
            "inventory": {"memory_count": 1},
            "write_performed": False,
            "error": None,
        }

    def prepare_graph_proposal_batch(
        self,
        *,
        scope="memory_os",
        project=None,
        domain=None,
        source_refs=None,
        limit=10,
        budget_chars=12000,
        candidate_graph_edges=None,
    ):
        self.calls.append(
            (
                "prepare_graph_proposal_batch",
                {
                    "scope": scope,
                    "project": project,
                    "domain": domain,
                    "source_refs": source_refs,
                    "limit": limit,
                    "budget_chars": budget_chars,
                    "candidate_graph_edges": candidate_graph_edges,
                },
            )
        )
        return {
            "status": "ok",
            "scope": scope,
            "source_items": [],
            "validated_edges": [],
            "write_performed": False,
            "error": None,
        }

    def apply_graph_proposal_batch(
        self,
        *,
        scope="memory_os",
        project=None,
        domain=None,
        source_refs=None,
        candidate_graph_edges=None,
        accept=False,
        approved_by=None,
        limit=10,
        budget_chars=12000,
    ):
        self.calls.append(
            (
                "apply_graph_proposal_batch",
                {
                    "scope": scope,
                    "project": project,
                    "domain": domain,
                    "source_refs": source_refs,
                    "candidate_graph_edges": candidate_graph_edges,
                    "accept": accept,
                    "approved_by": approved_by,
                    "limit": limit,
                    "budget_chars": budget_chars,
                },
            )
        )
        return {
            "status": "ok" if accept else "policy_denied",
            "scope": scope,
            "graph_edges_written": ["edge:memory:supports:concept:123"] if accept else [],
            "write_performed": bool(accept),
            "graph_write_performed": bool(accept),
            "active_memory_write_performed": False,
            "error": None,
        }

    def repair_graph_edge_refs(
        self,
        *,
        source=None,
        limit=1000,
        accept=False,
        approved_by=None,
    ):
        self.calls.append(
            (
                "repair_graph_edge_refs",
                {
                    "source": source,
                    "limit": limit,
                    "accept": accept,
                    "approved_by": approved_by,
                },
            )
        )
        return {
            "operation": "repair_graph_edge_refs",
            "status": "ok" if accept else "prepared",
            "source": source,
            "candidate_count": 1,
            "repaired_count": 1 if accept else 0,
            "write_performed": bool(accept),
            "active_memory_write_performed": False,
            "graph_write_performed": bool(accept),
            "error": None,
        }

    def repair_graph_store_reconciliation(
        self,
        *,
        repair_mode="upsert_missing",
        limit=5000,
        accept=False,
        approved_by=None,
    ):
        self.calls.append(
            (
                "repair_graph_store_reconciliation",
                {
                    "repair_mode": repair_mode,
                    "limit": limit,
                    "accept": accept,
                    "approved_by": approved_by,
                },
            )
        )
        return {
            "operation": "repair_graph_store_reconciliation",
            "status": "ok" if accept else "prepared",
            "repair_mode": repair_mode,
            "candidate_count": 1,
            "repaired_count": 1 if accept else 0,
            "write_performed": bool(accept),
            "active_memory_write_performed": False,
            "graph_write_performed": bool(accept),
            "error": None,
        }

    def record_document_disassembly_job(self, disassembly, *, request):
        self.calls.append(
            (
                "record_document_disassembly_job",
                {"document_id": disassembly.get("document", {}).get("document_id"), "request": request},
            )
        )
        return {
            "job_id": "job:document",
            "job_kind": "document_disassembly",
            "status": "succeeded",
        }

    def inspector(self, *, limit=20):
        return {
            "schema_version": "2026-05-13.memory-os-inspector.v1",
            "limit": limit,
            "write_performed": False,
            "jobs": {"count": 1, "items": [{"job_id": "job:one"}]},
            "coverage_maps": {"count": 0, "items": []},
        }


class DegradedStoreMemoryRuntime(FakeMemoryOSRuntime):
    def store_memory(self, **kwargs):
        self.calls.append(("store_memory", kwargs))
        return {
            "key": kwargs["key"],
            "write_degraded": True,
            "repair_required": True,
            "write_state": "repair_pending",
            "error": {
                "code": "memory_write_degraded",
                "failed_gate": "retrieval",
                "message": "forced retrieval failure",
            },
        }


class RefreshCountingRuntime(FakeMemoryOSRuntime):
    def __init__(self):
        super().__init__()
        self.retrieval_state_calls = 0

    def retrieval_state(self):
        self.retrieval_state_calls += 1
        return super().retrieval_state()


class TelemetrySearchRuntime(FakeMemoryOSRuntime):
    def search_memories(self, **kwargs):
        payload = super().search_memories(**kwargs)
        payload["receipt"] = {
            "semantic_candidate_count": 7,
        }
        return payload


def test_health_reports_daemon_and_storage_stats():
    api = EngramDaemonAPI(memory_manager=FakeMemoryManager())

    response = api.handle("GET", "/health", None)

    assert response["status"] == 200
    assert response["body"]["daemon"] == "engramd"
    assert response["body"]["status"] == "ok"
    assert response["body"]["stats"]["total_memories"] == 2
    assert response["body"]["stats"]["total_chunks"] == 3
    assert response["body"]["serving"]["search_backend"] == "legacy_json_chroma"
    assert response["body"]["serving"]["primary_backend"] == "legacy_json_chroma"
    assert response["body"]["serving"]["fallback_active"] is False
    assert response["body"]["serving"]["fallback_reason"] is None
    assert response["body"]["serving"]["warnings"][0]["code"] == "memory_os_runtime_unavailable"


def test_health_reports_warm_memory_os_search_fallback():
    runtime = FakeMemoryOSRuntime()
    runtime.retrieval_ready = False
    api = EngramDaemonAPI(memory_manager=FakeMemoryManager(), memory_os_runtime=runtime)

    response = api.handle("GET", "/health", None)

    assert response["status"] == 200
    serving = response["body"]["serving"]
    assert serving["search_backend"] == "legacy_json_chroma"
    assert serving["primary_backend"] == "memory_os"
    assert serving["memory_os_configured"] is True
    assert serving["memory_os_retrieval_ready"] is False
    assert serving["memory_os_retrieval_status"] == "rebuilding"
    assert serving["fallback_active"] is True
    assert serving["fallback_reason"] == "memory_os_retrieval_warming"
    assert serving["warnings"][0]["code"] == "memory_os_retrieval_warming"


def test_health_reports_active_memory_os_stats_when_runtime_is_configured():
    runtime = FakeMemoryOSRuntime()
    api = EngramDaemonAPI(memory_manager=FakeMemoryManager(), memory_os_runtime=runtime)

    response = api.handle("GET", "/health", None)

    assert response["status"] == 200
    stats = response["body"]["stats"]
    assert stats["source"] == "memory_os"
    assert stats["total_memories"] == 11
    assert stats["total_chunks"] == 23
    assert stats["total_documents"] == 7
    assert stats["total_sources"] == 5
    assert stats["total_graph_edges"] == 37
    assert stats["retrieval_indexed_count"] == 23
    assert stats["memory_os_ledger_bytes"] == 4096
    assert stats["legacy_total_memories"] == 2
    assert stats["legacy_total_chunks"] == 3
    assert response["body"]["legacy_stats"]["total_memories"] == 2
    assert response["body"]["serving"]["search_backend"] == "memory_os"


def test_health_uses_json_fallback_when_legacy_stats_fail():
    api = EngramDaemonAPI(memory_manager=FailingStatsMemoryManager())

    response = api.handle("GET", "/health", None)

    assert response["status"] == 200
    assert response["body"]["status"] == "ok"
    assert response["body"]["stats"]["total_chunks"] is None
    assert response["body"]["legacy_stats_error"]["code"] == "legacy_stats_unavailable"


def test_health_bypasses_serialized_backend_queue():
    api = EngramDaemonAPI(memory_manager=FakeMemoryManager())

    api._request_lock.acquire()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(api.handle, "GET", "/health", None)
            try:
                response = future.result(timeout=1)
            except TimeoutError as exc:
                raise AssertionError("health should not wait behind serialized backend work") from exc
    finally:
        api._request_lock.release()

    assert response["status"] == 200


def test_read_routes_bypass_serialized_backend_queue():
    manager = ContentionMemoryManager()
    api = EngramDaemonAPI(memory_manager=manager)

    def run_search(index):
        return api.handle("POST", "/v1/search_memories", {"query": f"runtime {index}"})

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(run_search, range(16)))

    assert all(response["status"] == 200 for response in responses)
    assert manager.max_active_calls > 1


def test_write_routes_still_wait_for_serialized_backend_queue():
    api = EngramDaemonAPI(memory_manager=FakeMemoryManager())

    pool = ThreadPoolExecutor(max_workers=1)
    api._request_lock.acquire()
    try:
        future = pool.submit(
            api.handle,
            "POST",
            "/v1/store_memory",
            {"key": "queued_write", "content": "Queued write content."},
        )
        try:
            future.result(timeout=0.1)
        except TimeoutError:
            pass
        else:
            raise AssertionError("writes should wait behind serialized backend work")
    finally:
        api._request_lock.release()

    response = future.result(timeout=1)
    pool.shutdown()
    assert response["status"] == 200


def test_search_passes_filters_to_memory_manager():
    api = EngramDaemonAPI(memory_manager=FakeMemoryManager())

    response = api.handle(
        "POST",
        "/v1/search_memories",
        {
            "query": "daemon runtime",
            "limit": 7,
            "project": "C:/Dev/Engram",
            "domain": "runtime",
            "tags": ["daemon"],
            "include_stale": False,
            "canonical_only": True,
            "retrieval_mode": "hybrid",
            "pinned_keys": ["daemon_memory"],
            "pinned_first": True,
        },
    )

    assert response["status"] == 200
    body = response["body"]
    assert body["query"] == "daemon runtime"
    assert body["backend"] == "legacy_json_chroma"
    assert body["backend_used"] == "legacy_json_chroma"
    assert body["primary_backend"] == "legacy_json_chroma"
    assert body["fallback_used"] is False
    assert body["fallback_reason"] is None
    assert body["warnings"][0]["code"] == "memory_os_runtime_unavailable"
    assert body["results"][0]["key"] == "daemon_memory"
    assert body["kwargs"]["project"] == "C:/Dev/Engram"
    assert body["kwargs"]["retrieval_mode"] == "hybrid"
    assert body["kwargs"]["pinned_keys"] == ["daemon_memory"]
    assert body["kwargs"]["pinned_first"] is True


def test_search_falls_back_to_memory_manager_while_memory_os_retrieval_warms():
    manager = FakeMemoryManager()
    runtime = FakeMemoryOSRuntime()
    runtime.retrieval_ready = False
    api = EngramDaemonAPI(memory_manager=manager, memory_os_runtime=runtime)

    response = api.handle("POST", "/v1/search_memories", {"query": "daemon runtime"})

    assert response["status"] == 200
    body = response["body"]
    assert body["results"][0]["key"] == "daemon_memory"
    assert body["backend"] == "legacy_json_chroma"
    assert body["backend_used"] == "legacy_json_chroma"
    assert body["primary_backend"] == "memory_os"
    assert body["fallback_used"] is True
    assert body["fallback_reason"] == "memory_os_retrieval_warming"
    assert body["memory_os_retrieval_ready"] is False
    assert body["memory_os_retrieval_status"] == "rebuilding"
    assert body["memory_os_retrieval_state"]["status"] == "rebuilding"
    assert body["warnings"][0]["code"] == "memory_os_retrieval_warming"
    assert runtime.calls == []


def test_search_reports_memory_os_retrieval_error_fallback():
    manager = FakeMemoryManager()
    runtime = FakeMemoryOSRuntime()
    runtime._retrieval_state = {"status": "error", "ready": False, "error": "boom"}
    api = EngramDaemonAPI(memory_manager=manager, memory_os_runtime=runtime)

    search = api.handle("POST", "/v1/search_memories", {"query": "daemon runtime"})
    health = api.handle("GET", "/health", None)

    assert search["status"] == 200
    assert search["body"]["backend_used"] == "legacy_json_chroma"
    assert search["body"]["fallback_used"] is True
    assert search["body"]["fallback_reason"] == "memory_os_retrieval_error"
    assert search["body"]["memory_os_retrieval_state"]["error"] == "boom"
    assert search["body"]["warnings"][0]["code"] == "memory_os_retrieval_error"
    assert health["body"]["serving"]["fallback_reason"] == "memory_os_retrieval_error"
    assert health["body"]["serving"]["memory_os_retrieval_state"]["error"] == "boom"


def test_memory_os_search_receipt_uses_cached_retrieval_state_on_hot_path():
    runtime = RefreshCountingRuntime()
    api = EngramDaemonAPI(memory_manager=FakeMemoryManager(), memory_os_runtime=runtime)

    response = api.handle("POST", "/v1/search_memories", {"query": "runtime"})

    assert response["status"] == 200
    assert response["body"]["backend_used"] == "memory_os"
    assert response["body"]["memory_os_retrieval_status"] == "ready"
    assert runtime.retrieval_state_calls == 0


def test_daemon_records_thin_client_usage_telemetry_without_response_mutation(isolated_usage_meter):
    runtime = TelemetrySearchRuntime()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=runtime,
        usage_meter=isolated_usage_meter.usage_meter,
    )

    response = api.handle("POST", "/v1/search_memories", {"query": "runtime"})
    calls = isolated_usage_meter.usage_meter.list_calls(tool="search_memories", limit=5)["calls"]

    assert response["status"] == 200
    assert "usage" not in response["body"]
    assert len(calls) == 1
    event = calls[0]
    assert event["entrypoint"] == "engramd"
    assert event["backend_used"] == "memory_os"
    assert event["fallback_used"] is False
    assert event["fallback_reason"] is None
    assert event["chunks_scanned"] == 7
    assert event["chunks_returned"] == 1
    assert event["write_class"] == "read_only"
    assert event["request_outcome"] == "ok"
    assert event["http_status"] == 200
    assert event["duration_ms"] >= 0


def test_daemon_records_retrieval_fallback_usage_telemetry(isolated_usage_meter):
    runtime = FakeMemoryOSRuntime()
    runtime.retrieval_ready = False
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=runtime,
        usage_meter=isolated_usage_meter.usage_meter,
    )

    response = api.handle("POST", "/v1/search_memories", {"query": "runtime"})
    event = isolated_usage_meter.usage_meter.list_calls(
        tool="search_memories",
        limit=5,
    )["calls"][0]

    assert response["status"] == 200
    assert event["backend_used"] == "legacy_json_chroma"
    assert event["primary_backend"] == "memory_os"
    assert event["fallback_used"] is True
    assert event["fallback_reason"] == "memory_os_retrieval_warming"
    assert event["request_outcome"] == "ok"


def test_daemon_records_failed_write_usage_outcome(isolated_usage_meter):
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=FakeMemoryOSRuntime(),
        usage_meter=isolated_usage_meter.usage_meter,
    )

    response = api.handle(
        "POST",
        "/v1/store_memory",
        {
            "key": "oversized_direct_memory",
            "content": "x" * (MAX_DIRECT_MEMORY_CHARS + 1),
        },
    )
    calls = isolated_usage_meter.usage_meter.list_calls(tool="store_memory", limit=5)["calls"]

    assert response["status"] == 400
    assert len(calls) == 1
    event = calls[0]
    assert event["entrypoint"] == "engramd"
    assert event["write_class"] == "write"
    assert event["request_outcome"] == "http_error"
    assert event["http_status"] == 400
    assert event["error"].startswith("invalid_request: Content is 15,001 chars")
    assert event["input_summary"]["content"]["redacted"] is True


def test_daemon_sync_identity_routes_redact_private_material_from_usage(tmp_path, isolated_usage_meter):
    runtime = MemoryOSRuntime(tmp_path / "memory_os", embed_text=lambda text: [0.1, 0.2])
    runtime.initialize(rebuild_retrieval=False)
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=runtime,
        usage_meter=isolated_usage_meter.usage_meter,
    )

    ensured = api.handle("POST", "/v1/ensure_sync_device_identity", {"device_name": "laptop"})
    exported = api.handle("POST", "/v1/export_local_sync_identity", {})
    rejected = api.handle(
        "POST",
        "/v1/register_sync_peer",
        {
            "peer_identity_packet": {
                **exported["body"],
                "private_key": "secret raw sync key material",
            },
            "accept": True,
            "approved_by": "tester",
        },
    )
    calls = isolated_usage_meter.usage_meter.list_calls(tool="register_sync_peer", limit=5)["calls"]

    assert ensured["status"] == 200
    assert ensured["body"]["local_device"]["device_name"] == "laptop"
    assert exported["status"] == 200
    assert exported["body"]["record_type"] == "sync_public_identity"
    assert "private" not in json.dumps(exported["body"]).lower()
    assert rejected["status"] == 200
    assert rejected["body"]["error"]["code"] == "private_key_material_rejected"
    assert len(calls) == 1
    assert "secret raw sync key material" not in json.dumps(calls[0])


def test_daemon_sync_changeset_routes_export_encrypted_bundle(tmp_path, isolated_usage_meter):
    laptop = MemoryOSRuntime(tmp_path / "laptop" / "memory_os", embed_text=lambda text: [0.1, 0.2])
    desktop = MemoryOSRuntime(tmp_path / "desktop" / "memory_os", embed_text=lambda text: [0.1, 0.2])
    laptop.initialize(rebuild_retrieval=False)
    desktop.initialize(rebuild_retrieval=False)
    laptop_api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=laptop,
        usage_meter=isolated_usage_meter.usage_meter,
    )
    desktop_api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=desktop,
        usage_meter=isolated_usage_meter.usage_meter,
    )
    laptop_api.handle("POST", "/v1/ensure_sync_device_identity", {"device_name": "laptop"})
    desktop_api.handle("POST", "/v1/ensure_sync_device_identity", {"device_name": "desktop"})
    desktop_identity = desktop_api.handle("POST", "/v1/export_local_sync_identity", {})["body"]
    laptop_identity = laptop_api.handle("POST", "/v1/export_local_sync_identity", {})["body"]
    laptop_api.handle(
        "POST",
        "/v1/register_sync_peer",
        {"peer_identity_packet": desktop_identity, "accept": True, "approved_by": "tester"},
    )
    desktop_api.handle(
        "POST",
        "/v1/register_sync_peer",
        {"peer_identity_packet": laptop_identity, "accept": True, "approved_by": "tester"},
    )
    laptop.store_memory(
        key="daemon_sync_export",
        content="Daemon sync changeset export should be encrypted and artifact backed.",
        domain="sync",
        memory_type="fact",
        scope="project",
        trust_state="reviewed",
        sync_policy="sync",
    )

    state = laptop_api.handle("POST", "/v1/inspect_sync_state", {})
    plan = laptop_api.handle(
        "POST",
        "/v1/prepare_sync_changeset",
        {"peer_id": desktop_identity["device_id"]},
    )
    exported = laptop_api.handle(
        "POST",
        "/v1/export_sync_changeset",
        {"plan": plan["body"], "accept": True, "approved_by": "tester"},
    )
    bundle_b64 = base64.urlsafe_b64encode(
        laptop.content_store.read_bytes(exported["body"]["artifact_id"])
    ).decode("ascii")
    apply_plan = desktop_api.handle("POST", "/v1/prepare_sync_apply", {"bundle_b64": bundle_b64})
    applied = desktop_api.handle(
        "POST",
        "/v1/apply_sync_changeset",
        {
            "bundle_b64": bundle_b64,
            "plan": apply_plan["body"],
            "accept": True,
            "approved_by": "tester",
        },
    )
    convergence = desktop_api.handle(
        "POST",
        "/v1/inspect_sync_convergence",
        {"peer_id": laptop_identity["device_id"]},
    )
    conflicts = desktop_api.handle("POST", "/v1/list_sync_conflicts", {})

    assert state["status"] == 200
    assert plan["status"] == 200
    assert plan["body"]["write_performed"] is False
    assert exported["status"] == 200
    assert exported["body"]["status"] == "exported"
    assert exported["body"]["envelope"]["encrypted"] is True
    assert apply_plan["status"] == 200
    assert apply_plan["body"]["status"] == "ready"
    json.dumps(apply_plan["body"])
    assert applied["status"] == 200
    assert applied["body"]["status"] == "applied"
    assert convergence["status"] == 200
    assert convergence["body"]["converged"] is True
    assert conflicts["status"] == 200
    assert conflicts["body"]["unresolved_conflict_count"] == 0
    assert "Daemon sync changeset export" not in json.dumps(exported["body"])


def test_daemon_sync_inbox_apply_route_applies_staged_bundle(tmp_path, isolated_usage_meter):
    laptop = MemoryOSRuntime(tmp_path / "laptop" / "memory_os", embed_text=lambda text: [0.1, 0.2])
    desktop = MemoryOSRuntime(tmp_path / "desktop" / "memory_os", embed_text=lambda text: [0.1, 0.2])
    laptop.initialize(rebuild_retrieval=False)
    desktop.initialize(rebuild_retrieval=False)
    laptop_api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=laptop,
        usage_meter=isolated_usage_meter.usage_meter,
    )
    desktop_api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=desktop,
        usage_meter=isolated_usage_meter.usage_meter,
    )
    laptop_api.handle("POST", "/v1/ensure_sync_device_identity", {"device_name": "laptop"})
    desktop_api.handle("POST", "/v1/ensure_sync_device_identity", {"device_name": "desktop"})
    desktop_identity = desktop_api.handle("POST", "/v1/export_local_sync_identity", {})["body"]
    laptop_identity = laptop_api.handle("POST", "/v1/export_local_sync_identity", {})["body"]
    laptop_api.handle(
        "POST",
        "/v1/register_sync_peer",
        {"peer_identity_packet": desktop_identity, "accept": True, "approved_by": "tester"},
    )
    desktop_api.handle(
        "POST",
        "/v1/register_sync_peer",
        {"peer_identity_packet": laptop_identity, "accept": True, "approved_by": "tester"},
    )
    laptop.store_memory(
        key="daemon_sync_inbox_apply",
        content="Daemon sync inbox apply should promote a staged bundle.",
        domain="sync",
        memory_type="fact",
        scope="project",
        trust_state="reviewed",
        sync_policy="sync",
    )

    plan = laptop_api.handle(
        "POST",
        "/v1/prepare_sync_changeset",
        {"peer_id": desktop_identity["device_id"]},
    )
    exported = laptop_api.handle(
        "POST",
        "/v1/export_sync_changeset",
        {"plan": plan["body"], "accept": True, "approved_by": "tester"},
    )
    bundle = laptop.content_store.read_bytes(exported["body"]["artifact_id"])
    inbox = store_inbound_sync_bundle(
        desktop,
        bundle,
        {"transport_type": "sync_peer", "peer_id": laptop_identity["device_id"]},
    )
    inbox_artifact_path = desktop.content_store.path_for(inbox["artifact_id"])

    prepared = desktop_api.handle("POST", "/v1/prepare_sync_inbox_apply", {"limit": 0})
    applied = desktop_api.handle(
        "POST",
        "/v1/apply_sync_inbox",
        {"limit": 0, "accept": True, "approved_by": "tester"},
    )
    prune_replay = desktop_api.handle(
        "POST",
        "/v1/prune_applied_sync_inbox_artifacts",
        {"limit": 0, "accept": False},
    )
    stored_inbox = read_record(desktop.ledger, "sync_inbox", inbox["inbox_id"])

    assert prepared["status"] == 200
    assert prepared["body"]["status"] == "ready"
    assert applied["status"] == 200
    assert applied["body"]["status"] == "applied"
    assert applied["body"]["applied_bundle_count"] == 1
    assert read_record(desktop.ledger, "memories", "daemon_sync_inbox_apply")["key"] == "daemon_sync_inbox_apply"
    assert stored_inbox["status"] == "applied"
    assert stored_inbox["apply_performed"] is True
    assert stored_inbox["artifact_prune_status"] == "deleted"
    assert not inbox_artifact_path.exists()
    assert prune_replay["status"] == 200
    assert prune_replay["body"]["status"] == "empty"


def test_memory_os_writes_return_503_while_retrieval_warms():
    manager = FakeMemoryManager()
    runtime = FakeMemoryOSRuntime()
    runtime.retrieval_ready = False
    api = EngramDaemonAPI(memory_manager=manager, memory_os_runtime=runtime)

    response = api.handle(
        "POST",
        "/v1/store_memory",
        {"key": "warming_memory", "content": "Wait for retrieval readiness."},
    )

    assert response["status"] == 503
    assert response["body"]["error"]["code"] == "memory_os_warming"
    assert manager.stored is None
    assert runtime.calls == []


def test_store_memory_rejects_oversized_direct_content_before_runtime():
    manager = FakeMemoryManager()
    runtime = FakeMemoryOSRuntime()
    api = EngramDaemonAPI(memory_manager=manager, memory_os_runtime=runtime)

    response = api.handle(
        "POST",
        "/v1/store_memory",
        {
            "key": "oversized_direct_memory",
            "content": "x" * (MAX_DIRECT_MEMORY_CHARS + 1),
        },
    )

    assert response["status"] == 400
    assert response["body"]["error"]["code"] == "invalid_request"
    assert "direct memory limit" in response["body"]["error"]["message"]
    assert manager.stored is None
    assert runtime.calls == []


def test_store_memory_returns_503_for_repair_required_runtime_result():
    runtime = DegradedStoreMemoryRuntime()
    api = EngramDaemonAPI(memory_manager=FakeMemoryManager(), memory_os_runtime=runtime)

    response = api.handle(
        "POST",
        "/v1/store_memory",
        {"key": "degraded_memory", "content": "This write should return degraded."},
    )

    assert response["status"] == 503
    assert response["body"]["stored"] is False
    assert response["body"]["error"]["code"] == "memory_write_degraded"
    assert response["body"]["result"]["write_state"] == "repair_pending"


def test_check_duplicate_returns_daemon_duplicate_payload():
    api = EngramDaemonAPI(memory_manager=FakeMemoryManager())

    response = api.handle(
        "POST",
        "/v1/check_duplicate",
        {
            "key": "candidate_memory",
            "content": "Candidate body",
        },
    )

    assert response["status"] == 200
    assert response["body"]["key"] == "candidate_memory"
    assert response["body"]["duplicate"] is True
    assert response["body"]["match"]["existing_key"] == "daemon_memory"
    assert response["body"]["error"] is None


def test_check_duplicate_invalid_request_preserves_tool_payload_shape():
    api = EngramDaemonAPI(memory_manager=FakeMemoryManager())

    response = api.handle(
        "POST",
        "/v1/check_duplicate",
        {
            "key": "",
            "content": "",
        },
    )

    assert response["status"] == 200
    assert response["body"]["duplicate"] is False
    assert response["body"]["match"] is None
    assert response["body"]["error"]["code"] == "invalid_request"


def test_retrieve_chunks_wraps_chunk_payloads():
    api = EngramDaemonAPI(memory_manager=FakeMemoryManager())

    response = api.handle(
        "POST",
        "/v1/retrieve_chunks",
        {"requests": [{"key": "daemon_memory", "chunk_id": 0}]},
    )

    assert response["status"] == 200
    body = response["body"]
    assert body["requested_count"] == 1
    assert body["found_count"] == 1
    assert body["results"][0]["chunk"]["text"] == "chunk 0"


def test_store_memory_preserves_json_first_result_shape():
    manager = FakeMemoryManager()
    api = EngramDaemonAPI(memory_manager=manager)

    response = api.handle(
        "POST",
        "/v1/store_memory",
        {
            "key": "daemon_memory",
            "content": "Daemon memory body.",
            "title": "Daemon Memory",
            "tags": ["daemon", "runtime"],
            "related_to": ["engram_memory_os_rebuild_progress_2026_05_12"],
            "force": True,
            "project": "C:/Dev/Engram",
            "domain": "runtime",
            "status": "active",
            "canonical": True,
        },
    )

    assert response["status"] == 200
    assert response["body"]["stored"] is True
    assert response["body"]["result"]["chunk_count"] == 1
    assert manager.stored["tags"] == ["daemon", "runtime"]
    assert manager.stored["canonical"] is True


def test_update_memory_metadata_preserves_daemon_result_shape():
    manager = FakeMemoryManager()
    api = EngramDaemonAPI(memory_manager=manager)

    response = api.handle(
        "POST",
        "/v1/update_memory_metadata",
        {
            "key": "daemon_memory",
            "title": "Updated Daemon Memory",
            "tags": ["daemon", "metadata"],
            "project": "Engram",
            "domain": "daemon",
            "status": "active",
            "canonical": True,
        },
    )

    assert response["status"] == 200
    assert response["body"]["updated"] is True
    assert response["body"]["memory"]["title"] == "Updated Daemon Memory"
    assert manager.updated["key"] == "daemon_memory"
    assert manager.updated["changes"]["tags"] == ["daemon", "metadata"]


def test_repair_memory_metadata_preserves_daemon_result_shape():
    api = EngramDaemonAPI(memory_manager=FakeMemoryManager())

    response = api.handle(
        "POST",
        "/v1/repair_memory_metadata",
        {
            "keys": ["daemon_memory"],
            "dry_run": False,
        },
    )

    assert response["status"] == 200
    assert response["body"]["requested_count"] == 1
    assert response["body"]["repaired_count"] == 1
    assert response["body"]["dry_run"] is False
    assert response["body"]["error"] is None


def test_repair_document_metadata_routes_to_memory_os_runtime():
    runtime = FakeMemoryOSRuntime()
    api = EngramDaemonAPI(memory_manager=FakeMemoryManager(), memory_os_runtime=runtime)

    response = api.handle(
        "POST",
        "/v1/repair_document_metadata",
        {
            "project": "Design Skills",
            "document_ids": ["doc_book"],
            "accept": True,
            "approved_by": "agent-review",
        },
    )

    assert response["status"] == 200
    assert response["body"]["status"] == "ok"
    assert response["body"]["write_performed"] is True
    assert runtime.calls[-1] == (
        "repair_document_metadata",
        {
            "project": "Design Skills",
            "document_ids": ["doc_book"],
            "accept": True,
            "approved_by": "agent-review",
        },
    )


def test_store_prepared_memory_promotes_source_draft_via_daemon():
    manager = FakeMemoryManager()
    api = EngramDaemonAPI(
        memory_manager=manager,
        source_intake_manager=FakeSourceIntakeManager(),
    )

    response = api.handle(
        "POST",
        "/v1/store_prepared_memory",
        {
            "draft_id": "draft-a",
            "selected_items": [0],
            "force": True,
        },
    )

    assert response["status"] == 200
    assert response["body"]["stored_count"] == 1
    assert response["body"]["stored"][0]["key"] == "daemon_source_memory"
    assert response["body"]["skipped"] == []
    assert manager.stored["key"] == "daemon_source_memory"
    assert manager.stored["force"] is True
    assert response["body"]["error"] is None


def test_store_prepared_memory_uses_memory_os_runtime_and_promotes_drafts_to_reviewed():
    runtime = FakeMemoryOSRuntime()
    draft = {
        "draft_id": "draft-runtime",
        "status": "draft",
        "proposed_memories": [
            {
                "key": "runtime_source_memory",
                "content": "Reviewed source body.",
                "title": "Runtime Source Memory",
                "tags": ["source", "transcript"],
                "related_to": [],
                "project": "Engram",
                "domain": "source-intake",
                "status": "draft",
                "canonical": False,
            }
        ],
    }
    manager = FakeMemoryManager()
    api = EngramDaemonAPI(
        memory_manager=manager,
        memory_os_runtime=runtime,
        source_intake_manager=FakeSourceIntakeManager(draft=draft),
    )

    response = api.handle(
        "POST",
        "/v1/store_prepared_memory",
        {
            "draft_id": "draft-runtime",
            "selected_items": [0],
            "force": True,
        },
    )

    assert response["status"] == 200
    assert response["body"]["stored_count"] == 1
    assert response["body"]["stored"][0]["key"] == "runtime_source_memory"
    assert manager.stored is None
    assert runtime.calls[-1] == (
        "store_memory",
        {
            "key": "runtime_source_memory",
            "content": "Reviewed source body.",
            "tags": ["source", "transcript"],
            "title": "Runtime Source Memory",
            "related_to": [],
            "force": True,
            "project": "Engram",
            "domain": "source-intake",
            "status": "reviewed",
            "canonical": False,
            "memory_type": None,
            "scope": None,
            "trust_state": None,
            "retention_policy": None,
            "sync_policy": None,
            "document_id": None,
            "source_id": None,
            "source_document": None,
            "citations": None,
            "approved_by": "source_draft_promotion",
            "guardrail_context": {
                "operation_kind": "store_prepared_memory",
                "draft_id": "draft-runtime",
                "operation_index": 0,
            },
        },
    )


def test_store_prepared_memory_guardrail_preflight_blocks_partial_runtime_promotion():
    runtime = FakeMemoryOSRuntime()
    draft = {
        "draft_id": "draft-runtime",
        "status": "draft",
        "proposed_memories": [
            {
                "key": "safe-source-memory",
                "content": "Safe source body.",
                "title": "Safe Source Memory",
                "tags": ["source"],
                "status": "draft",
            },
            {
                "key": "secret-source-memory",
                "content": "API_TOKEN=abc123",
                "title": "Secret Source Memory",
                "tags": ["source"],
                "status": "draft",
            },
        ],
    }
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=runtime,
        source_intake_manager=FakeSourceIntakeManager(draft=draft),
    )

    response = api.handle(
        "POST",
        "/v1/store_prepared_memory",
        {
            "draft_id": "draft-runtime",
            "selected_items": [0, 1],
            "force": True,
        },
    )

    assert response["status"] == 200
    assert response["body"]["stored_count"] == 0
    assert response["body"]["stored"] == []
    assert response["body"]["error"]["code"] == "memory_guardrail_blocked"
    assert response["body"]["skipped"][0]["key"] == "secret-source-memory"
    assert runtime.calls == []


def test_store_prepared_memory_runtime_guardrail_preflight_writes_receipts(tmp_path):
    runtime = real_memory_os_runtime(tmp_path)
    draft = {
        "draft_id": "draft-runtime",
        "status": "draft",
        "proposed_memories": [
            {
                "key": "safe-source-memory",
                "content": "Safe source body.",
                "title": "Safe Source Memory",
                "tags": ["source"],
                "status": "draft",
            },
            {
                "key": "secret-source-memory",
                "content": "API_TOKEN=abc123",
                "title": "Secret Source Memory",
                "tags": ["source"],
                "status": "draft",
            },
        ],
    }
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=runtime,
        source_intake_manager=FakeSourceIntakeManager(draft=draft),
    )

    response = api.handle(
        "POST",
        "/v1/store_prepared_memory",
        {
            "draft_id": "draft-runtime",
            "selected_items": [0, 1],
            "force": True,
        },
    )

    assert response["status"] == 200
    assert response["body"]["stored_count"] == 0
    assert response["body"]["stored"] == []
    assert response["body"]["error"]["code"] == "memory_guardrail_blocked"
    assert read_record(runtime.ledger, "memories", "safe-source-memory") is None
    assert read_record(runtime.ledger, "memories", "secret-source-memory") is None
    receipts = list_records(runtime.ledger, "memory_guardrail_receipts")
    firewall_events = list_records(runtime.ledger, "firewall_events")
    assert len(receipts) == 1
    assert receipts[0]["issue_codes"] == ["secret_like_content"]
    assert receipts[0]["draft_id"] == "draft-runtime"
    assert "content_excerpt" not in receipts[0]
    assert len(firewall_events) == 1
    assert firewall_events[0]["source_ref"]["memory_key"] == "secret-source-memory"


def test_store_prepared_memory_runtime_rejection_aborts_and_rolls_back_prior_store():
    class LateRejectingRuntime(FakeMemoryOSRuntime):
        def __init__(self):
            super().__init__()
            self.deleted = []

        def _enforce_memory_guardrails(self, **kwargs):
            return {
                "allowed": True,
                "guardrail": {"decision": "allow", "issue_codes": []},
                "receipt": None,
                "firewall_event": None,
            }

        def store_memory(self, **kwargs):
            self.calls.append(("store_memory", kwargs))
            if kwargs["key"] == "late-rejected-memory":
                return {
                    "status": "policy_denied",
                    "error": {
                        "code": "memory_guardrail_blocked",
                        "category": "memory_guardrail",
                        "message": "late rejection",
                    },
                    "write_performed": True,
                    "active_memory_write_performed": False,
                }
            return {
                "key": kwargs["key"],
                "title": kwargs["title"],
                "chunk_count": 1,
                "chars": len(kwargs["content"]),
                "storage_backend": "memory_os",
            }

        def delete_memory(self, key):
            self.deleted.append(key)
            return {"key": key, "deleted": True, "error": None}

    runtime = LateRejectingRuntime()
    draft = {
        "draft_id": "draft-runtime",
        "status": "draft",
        "proposed_memories": [
            {
                "key": "safe-source-memory",
                "content": "Safe source body.",
                "title": "Safe Source Memory",
                "tags": ["source"],
                "status": "draft",
            },
            {
                "key": "late-rejected-memory",
                "content": "Late rejected source body.",
                "title": "Late Rejected Memory",
                "tags": ["source"],
                "status": "draft",
            },
        ],
    }
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=runtime,
        source_intake_manager=FakeSourceIntakeManager(draft=draft),
    )

    response = api.handle(
        "POST",
        "/v1/store_prepared_memory",
        {
            "draft_id": "draft-runtime",
            "selected_items": [0, 1],
            "force": True,
        },
    )

    assert response["status"] == 200
    assert response["body"]["stored_count"] == 0
    assert response["body"]["stored"] == []
    assert response["body"]["error"]["code"] == "memory_guardrail_blocked"
    assert response["body"]["rollback"]["deleted"] == ["safe-source-memory"]
    assert runtime.deleted == ["safe-source-memory"]


def test_store_prepared_memory_legacy_path_blocks_guardrail_without_write():
    manager = FakeMemoryManager()
    draft = {
        "draft_id": "draft-legacy",
        "status": "draft",
        "proposed_memories": [
            {
                "key": "secret-source-memory",
                "content": "API_TOKEN=abc123",
                "title": "Secret Source Memory",
                "tags": ["source"],
                "status": "draft",
            },
        ],
    }
    api = EngramDaemonAPI(
        memory_manager=manager,
        source_intake_manager=FakeSourceIntakeManager(draft=draft),
    )

    response = api.handle(
        "POST",
        "/v1/store_prepared_memory",
        {"draft_id": "draft-legacy", "selected_items": [0]},
    )

    assert response["status"] == 200
    assert response["body"]["stored_count"] == 0
    assert response["body"]["error"]["code"] == "memory_guardrail_blocked"
    assert manager.stored is None


def test_prepare_source_memory_creates_source_draft_via_daemon():
    source_intake = FakeSourceIntakeManager()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        source_intake_manager=source_intake,
    )

    response = api.handle(
        "POST",
        "/v1/prepare_source_memory",
        {
            "source_text": "Decision: route source drafts through daemon.",
            "source_type": "handoff",
            "source_uri": "file:///handoff.md",
            "project": "Engram",
            "domain": "daemon",
            "budget_chars": 4000,
            "pipeline": "handoff",
        },
    )

    assert response["status"] == 200
    assert response["body"]["draft"]["draft_id"] == "draft-a"
    assert response["body"]["error"] is None
    assert source_intake.prepared["source_type"] == "handoff"
    assert source_intake.prepared["pipeline"] == "handoff"


def test_prepare_source_memory_allows_large_source_text_for_review_path():
    source_intake = FakeSourceIntakeManager()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        source_intake_manager=source_intake,
    )
    source_text = "x" * (MAX_DIRECT_MEMORY_CHARS + 1)

    response = api.handle(
        "POST",
        "/v1/prepare_source_memory",
        {
            "source_text": source_text,
            "source_type": "transcript",
            "source_uri": "file:///large-transcript.txt",
            "project": "Engram",
            "domain": "source-intake",
            "budget_chars": 4000,
            "pipeline": "transcript",
        },
    )

    assert response["status"] == 200
    assert response["body"]["draft"]["draft_id"] == "draft-a"
    assert response["body"]["error"] is None
    assert source_intake.prepared["source_text"] == source_text


def test_prepare_document_disassembly_routes_to_document_disassembler():
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        document_disassembler=fake_document_disassembler,
    )

    response = api.handle(
        "POST",
        "/v1/prepare_document_disassembly",
        {
            "source_path": "C:/docs/book.pdf",
            "source_type": "pdf",
            "max_pages": 5,
        },
    )

    assert response["status"] == 200
    assert response["body"]["error"] is None
    assert response["body"]["disassembly"]["record_type"] == "document_disassembly_preview"
    assert response["body"]["disassembly"]["source"]["path"] == "C:/docs/book.pdf"
    assert response["body"]["disassembly"]["document"]["page_limit"] == 5


def test_prepare_document_intake_review_uses_injected_document_disassembler():
    calls = []

    def fake_intake_disassembler(**kwargs):
        calls.append(kwargs)
        return {
            "record_type": "document_disassembly_preview",
            "write_performed": False,
            "active_memory_write_performed": False,
            "source": {
                "source_uri": "file:///docs/book.pdf",
                "path": kwargs["source_path"],
                "source_type": "pdf",
                "media_type": "application/pdf",
                "content_hash": "sha256:" + "a" * 64,
            },
            "document": {
                "document_id": "doc_book",
                "title": "Book",
                "source_type": "pdf",
                "media_type": "application/pdf",
                "content_hash": "sha256:" + "a" * 64,
                "page_count": 1,
                "page_limit": 1,
            },
            "pages": [{"page_number": 1, "text_status": "text", "visual_review_needed": False}],
            "text": {"content": "# Book\n\nDaemon injected disassembler.", "char_count": 36, "page_count": 1},
            "image_inventory": {"image_count": 0, "pages_with_images": []},
            "quality_report": {"warnings": []},
            "artifact_manifest": {"record_type": "document_artifact_manifest"},
            "visual_extraction_request": None,
            "promotion_guidance": {"auto_promote": False},
            "error": None,
        }

    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        document_disassembler=fake_intake_disassembler,
    )

    response = api.handle(
        "POST",
        "/v1/prepare_document_intake_review",
        {"source_path": "C:/docs/book.pdf", "source_type": "pdf"},
    )

    assert response["status"] == 200
    assert response["body"]["status"] == "ok"
    assert response["body"]["source"]["document_id"] == "doc_book"
    assert calls and calls[0]["source_path"] == "C:/docs/book.pdf"


def test_prepare_document_disassembly_records_daemon_owned_job_when_runtime_available():
    runtime = FakeMemoryOSRuntime()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        document_disassembler=lambda **kwargs: {
            "record_type": "document_disassembly_preview",
            "status": "partial",
            "source": {"source_uri": "file:///book.pdf"},
            "document": {"document_id": "doc_book", "page_range": {"start": 2, "end": 2}},
            "resume": {"has_more": True, "next_page": 3},
            "error": None,
        },
        memory_os_runtime=runtime,
    )

    response = api.handle(
        "POST",
        "/v1/prepare_document_disassembly",
        {
            "source_path": "C:/docs/book.pdf",
            "source_type": "pdf",
            "page_range": "2-2",
        },
    )

    assert response["status"] == 200
    assert response["body"]["job"]["job_kind"] == "document_disassembly"
    assert runtime.calls[-1] == (
        "record_document_disassembly_job",
        {
            "document_id": "doc_book",
            "request": {
                "source_path": "C:/docs/book.pdf",
                "source_type": "pdf",
                "page_range": "2-2",
            },
        },
    )


def test_document_workflow_routes_delegate_to_document_toolset():
    document_tools = FakeDocumentWorkflow()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        document_tools=document_tools,
    )

    cases = [
        ("/v1/list_document_extractors", {}),
        ("/v1/preview_document_source_connector", {"connector_type": "local_path", "target": "docs"}),
        ("/v1/prepare_document_disassembly", {"source_path": "C:/docs/book.pdf"}),
        ("/v1/prepare_document_coverage_workbench", {"source_path": "C:/docs/book.pdf"}),
        ("/v1/prepare_document_intake_review", {"source_path": "C:/docs/book.pdf"}),
        ("/v1/prepare_document_extraction_request", {"source_ref": {"source_uri": "file:///book.pdf"}}),
        ("/v1/prepare_document_extraction_result", {"title": "Book", "content": "body"}),
        ("/v1/preview_document_extraction", {"title": "Book", "content": "body"}),
        ("/v1/prepare_visual_extraction_request", {"document_record": {}, "image_refs": []}),
        ("/v1/preview_visual_extraction", {"document_record": {}, "observations": []}),
        ("/v1/prepare_document_understanding_packet", {"document_record": {}, "analysis": {}}),
        ("/v1/prepare_document_draft", {"document_record": {}, "analysis": {}}),
        ("/v1/prepare_document_promotion_transaction", {"document_draft": {}, "approved_by": "reviewer"}),
    ]

    responses = [api.handle("POST", route, payload) for route, payload in cases]

    assert all(response["status"] == 200 for response in responses)
    assert [call[0] for call in document_tools.calls] == [
        "list_document_extractors",
        "preview_document_source_connector",
        "prepare_document_disassembly",
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
    ]


def test_document_workflow_routes_use_stage_boundary():
    document_tools = BoundaryOnlyDocumentWorkflow()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        document_tools=document_tools,
    )

    response = api.handle(
        "POST",
        "/v1/preview_document_extraction",
        {"title": "Book", "content": "body"},
    )

    assert response["status"] == 200
    assert response["body"] == {
        "preview": {
            "stage": "preview_document_extraction",
            "request": {"title": "Book", "content": "body"},
        },
        "error": None,
    }
    assert document_tools.calls == [
        ("preview_document_extraction", {"title": "Book", "content": "body"})
    ]


def test_document_artifact_routes_delegate_to_memory_os_runtime():
    runtime = FakeMemoryOSRuntime()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=runtime,
    )

    prepared = api.handle(
        "POST",
        "/v1/prepare_document_artifact_store",
        {"review_packet": {"status": "ok"}, "artifact_family": "document_evidence"},
    )
    stored = api.handle(
        "POST",
        "/v1/store_document_artifact",
        {"prepared_transaction_id": "txn-doc", "accept": True, "review_packet": {"status": "ok"}},
    )

    assert prepared["status"] == 200
    assert prepared["body"]["prepared_transaction_id"] == "txn-doc"
    assert stored["status"] == 200
    assert stored["body"]["stored"] is True
    assert runtime.calls[-2:] == [
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
    ]


def test_document_ingestion_completion_routes_delegate_to_memory_os_runtime():
    runtime = FakeMemoryOSRuntime()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=runtime,
    )

    prepared = api.handle(
        "POST",
        "/v1/prepare_document_ingestion_completion",
        {
            "document_id": "doc-book",
            "artifact_id": "doc_artifact:doc-book",
            "visual_request": {"request_id": "vis_req"},
            "visual_preview": {"status": "ok"},
            "understanding_packet": {"packet_id": "packet"},
            "document_promotion_transaction": {"transaction_id": "doc_promote"},
            "coverage_waivers": [{"page_number": 2, "capability": "table_structure"}],
        },
    )
    completed = api.handle(
        "POST",
        "/v1/complete_document_ingestion",
        {
            "document_id": "doc-book",
            "artifact_id": "doc_artifact:doc-book",
            "visual_request": {"request_id": "vis_req"},
            "visual_preview": {"status": "ok"},
            "understanding_packet": {"packet_id": "packet"},
            "document_promotion_transaction": {"transaction_id": "doc_promote"},
            "coverage_waivers": [{"page_number": 2, "capability": "table_structure"}],
            "accept": True,
            "approved_by": "agent-review",
            "selected_operation_indexes": [0],
        },
    )

    assert prepared["status"] == 200
    assert prepared["body"]["usable"] is True
    assert completed["status"] == 200
    assert completed["body"]["usable"] is True
    assert runtime.calls[-2:] == [
        (
            "prepare_document_ingestion_completion",
            {
                "document_id": "doc-book",
                "artifact_id": "doc_artifact:doc-book",
                "visual_request": {"request_id": "vis_req"},
                "visual_preview": {"status": "ok"},
                "understanding_packet": {"packet_id": "packet"},
                "document_promotion_transaction": {"transaction_id": "doc_promote"},
                "coverage_waivers": [{"page_number": 2, "capability": "table_structure"}],
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
                "coverage_waivers": [{"page_number": 2, "capability": "table_structure"}],
                "accept": True,
                "approved_by": "agent-review",
                "selected_operation_indexes": [0],
            },
        ),
    ]


def test_document_ingestion_routes_delegate_to_memory_os_runtime():
    runtime = FakeMemoryOSRuntime()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=runtime,
    )
    api._start_document_ingestion_worker = lambda runtime_arg: runtime.calls.append(("worker_started", {}))

    planned = api.handle(
        "POST",
        "/v1/prepare_document_ingestion_plan",
        {
            "source_path": "/docs/book.pdf",
            "project": "Engram",
            "domain": "documents",
            "profile": "graph_coverage",
            "page_window_size": 25,
            "analysis_policy": "defer",
            "approval_mode": "agent_authorized",
            "budget": {"max_windows": 2},
        },
    )
    run = api.handle(
        "POST",
        "/v1/run_document_ingestion",
        {
            "ingestion_id": "doc_ingest_book",
            "accept": True,
            "approved_by": "agent-review",
            "review_packets": [{"window_index": 0}],
            "understanding_analysis": {"summary": ["Window one"]},
            "visual_preview": {"status": "ok", "window_index": 0},
        },
    )
    resumed = api.handle(
        "POST",
        "/v1/resume_document_ingestion",
        {
            "ingestion_id": "doc_ingest_book",
            "accept": True,
            "approved_by": "agent-review",
            "review_packets": [{"window_index": 1}],
            "understanding_analysis": {"summary": ["Window two"]},
            "visual_preview": {"status": "ok", "window_index": 1},
        },
    )
    inspected = api.handle(
        "POST",
        "/v1/inspect_document_ingestion",
        {"ingestion_id": "doc_ingest_book", "document_id": "doc_book"},
    )

    assert planned["status"] == 200
    assert planned["body"]["status"] == "planned"
    assert run["status"] == 200
    assert run["body"]["status"] == "queued"
    assert resumed["status"] == 200
    assert resumed["body"]["resumed"] is True
    assert inspected["status"] == 200
    assert inspected["body"]["next_action"]["tool"] == "resume_document_ingestion"
    assert runtime.calls[-6:] == [
        (
            "prepare_document_ingestion_plan",
            {
                "source_path": "/docs/book.pdf",
                "project": "Engram",
                "domain": "documents",
                "profile": "graph_coverage",
                "page_window_size": 25,
                "analysis_policy": "defer",
                "approval_mode": "agent_authorized",
                "budget": {"max_windows": 2},
            },
        ),
        (
            "enqueue_document_ingestion_run",
            {
                "ingestion_id": "doc_ingest_book",
                "accept": True,
                "approved_by": "agent-review",
                "review_packets": [{"window_index": 0}],
                "understanding_analysis": {"summary": ["Window one"]},
                "visual_preview": {"status": "ok", "window_index": 0},
            },
        ),
        ("worker_started", {}),
        (
            "enqueue_document_ingestion_resume",
            {
                "ingestion_id": "doc_ingest_book",
                "accept": True,
                "approved_by": "agent-review",
                "review_packets": [{"window_index": 1}],
                "understanding_analysis": {"summary": ["Window two"]},
                "visual_preview": {"status": "ok", "window_index": 1},
            },
        ),
        ("worker_started", {}),
        (
            "inspect_document_ingestion",
            {"ingestion_id": "doc_ingest_book", "document_id": "doc_book"},
        ),
    ]


def test_document_ingestion_run_resume_reject_stale_schema_keys():
    runtime = FakeMemoryOSRuntime()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=runtime,
    )

    for route in ("/v1/run_document_ingestion", "/v1/resume_document_ingestion"):
        for stale_key in ("analysis", "selected_operation_indexes"):
            response = api.handle(
                "POST",
                route,
                {"ingestion_id": "doc_ingest_book", stale_key: {"stale": True}},
            )

            assert response["status"] == 400
            assert response["body"]["error"]["code"] == "invalid_request"
            assert stale_key in response["body"]["error"]["message"]

    assert runtime.calls == []


def test_document_ingestion_run_resume_require_ingestion_id():
    runtime = FakeMemoryOSRuntime()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=runtime,
    )

    for route in ("/v1/run_document_ingestion", "/v1/resume_document_ingestion"):
        response = api.handle("POST", route, {"accept": True, "approved_by": "agent-review"})

        assert response["status"] == 400
        assert response["body"]["error"]["code"] == "invalid_request"
        assert "ingestion_id is required" in response["body"]["error"]["message"]

    assert runtime.calls == []


def test_document_ingestion_prepare_and_inspect_validate_required_payloads():
    runtime = FakeMemoryOSRuntime()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=runtime,
    )

    prepare_response = api.handle("POST", "/v1/prepare_document_ingestion_plan", {"project": "Engram"})
    inspect_response = api.handle("POST", "/v1/inspect_document_ingestion", {})

    assert prepare_response["status"] == 400
    assert prepare_response["body"]["error"]["code"] == "invalid_request"
    assert "source_path is required" in prepare_response["body"]["error"]["message"]
    assert inspect_response["status"] == 400
    assert inspect_response["body"]["error"]["code"] == "invalid_request"
    assert "ingestion_id or document_id is required" in inspect_response["body"]["error"]["message"]
    assert runtime.calls == []


def test_document_coverage_pass_route_delegates_to_memory_os_runtime():
    runtime = FakeMemoryOSRuntime()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=runtime,
    )
    ingestion_record = {
        "ingestion_id": "doc_ingest_book",
        "document_id": "doc_book",
        "source": {"path": "/docs/book.pdf"},
    }

    response = api.handle(
        "POST",
        "/v1/prepare_document_coverage_pass",
        {
            "ingestion_record": ingestion_record,
            "review_packets": [{"window_index": 0}],
            "coverage_policy": "auto_local",
            "coverage_options": {"max_pages": 2},
        },
    )

    assert response["status"] == 200
    assert response["body"]["status"] == "ok"
    assert response["body"]["active_memory_write_performed"] is False
    assert response["body"]["graph_write_performed"] is False
    assert runtime.calls == [
        (
            "prepare_document_coverage_pass",
            {
                "ingestion_record": ingestion_record,
                "review_packets": [{"window_index": 0}],
                "coverage_policy": "auto_local",
                "coverage_options": {"max_pages": 2},
            },
        )
    ]


def test_document_coverage_pass_validates_payload_shape():
    runtime = FakeMemoryOSRuntime()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=runtime,
    )

    missing_record = api.handle("POST", "/v1/prepare_document_coverage_pass", {})
    stale_key = api.handle(
        "POST",
        "/v1/prepare_document_coverage_pass",
        {"ingestion_record": {"ingestion_id": "doc_ingest_book"}, "selected_operation_indexes": [0]},
    )

    assert missing_record["status"] == 400
    assert missing_record["body"]["error"]["code"] == "invalid_request"
    assert "ingestion_record is required" in missing_record["body"]["error"]["message"]
    assert stale_key["status"] == 400
    assert stale_key["body"]["error"]["code"] == "invalid_request"
    assert "selected_operation_indexes" in stale_key["body"]["error"]["message"]
    assert runtime.calls == []


def test_knowledge_pr_routes_delegate_to_memory_os_runtime():
    runtime = FakeMemoryOSRuntime()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=runtime,
    )

    branch = api.handle(
        "POST",
        "/v1/prepare_knowledge_branch",
        {
            "name": "Book import review",
            "source_refs": [{"kind": "document", "document_id": "doc_book"}],
            "base_snapshot_ref": "snapshot:before",
            "metadata": {"project": "Engram"},
        },
    )
    pr = api.handle(
        "POST",
        "/v1/prepare_knowledge_pr",
        {
            "branch_id": "kbranch_review",
            "title": "Promote book graph edges",
            "proposed_operations": [{"operation_id": "op:graph:1", "kind": "graph_edge"}],
            "source_refs": [{"kind": "document", "document_id": "doc_book"}],
            "document_refs": [{"document_id": "doc_book"}],
            "metadata": {"domain": "documents"},
        },
    )
    ci = api.handle(
        "POST",
        "/v1/run_memory_ci",
        {
            "knowledge_pr_id": "kpr_review",
            "gates": ["gate_provenance"],
            "ci_context": {"retrieval_probe_count": 1},
        },
    )
    inspected = api.handle("POST", "/v1/inspect_knowledge_pr", {"knowledge_pr_id": "kpr_review"})
    merged = api.handle(
        "POST",
        "/v1/merge_knowledge_pr",
        {
            "knowledge_pr_id": "kpr_review",
            "accept": True,
            "approved_by": "agent-review",
            "selected_operation_ids": ["op:graph:1"],
            "selected_operation_indexes": [0],
            "ci_waivers": [{"gate_id": "gate_retrieval_regression"}],
        },
    )

    assert branch["status"] == 200
    assert pr["status"] == 200
    assert ci["status"] == 200
    assert inspected["status"] == 200
    assert inspected["body"]["mergeable"] is True
    assert merged["status"] == 200
    assert merged["body"]["status"] == "merged"
    assert runtime.calls == [
        (
            "prepare_knowledge_branch",
            {
                "name": "Book import review",
                "source_refs": [{"kind": "document", "document_id": "doc_book"}],
                "base_snapshot_ref": "snapshot:before",
                "metadata": {"project": "Engram"},
            },
        ),
        (
            "prepare_knowledge_pr",
            {
                "branch_id": "kbranch_review",
                "title": "Promote book graph edges",
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


def test_knowledge_pr_routes_validate_required_payloads():
    runtime = FakeMemoryOSRuntime()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=runtime,
    )

    responses = [
        api.handle("POST", "/v1/prepare_knowledge_branch", {}),
        api.handle("POST", "/v1/prepare_knowledge_pr", {"branch_id": "kbranch_review"}),
        api.handle("POST", "/v1/run_memory_ci", {}),
        api.handle("POST", "/v1/inspect_knowledge_pr", {}),
        api.handle("POST", "/v1/merge_knowledge_pr", {"accept": True}),
    ]

    assert [response["status"] for response in responses] == [400, 400, 400, 400, 400]
    assert "name is required" in responses[0]["body"]["error"]["message"]
    assert "title is required" in responses[1]["body"]["error"]["message"]
    assert "knowledge_pr_id is required" in responses[2]["body"]["error"]["message"]
    assert "knowledge_pr_id is required" in responses[3]["body"]["error"]["message"]
    assert "knowledge_pr_id is required" in responses[4]["body"]["error"]["message"]
    assert runtime.calls == []


def test_memory_benchmark_routes_delegate_to_memory_os_runtime():
    runtime = FakeMemoryOSRuntime()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=runtime,
    )

    catalog = api.handle("POST", "/v1/list_memory_benchmark_suites", {"suite_id": "smoke"})
    run = api.handle(
        "POST",
        "/v1/run_memory_benchmark",
        {"suite_id": "smoke", "seed": 42, "persist": True},
    )
    inspected = api.handle("POST", "/v1/inspect_benchmark_run", {"run_id": "benchmark_run:smoke"})

    assert catalog["status"] == 200
    assert catalog["body"]["suites"][0]["suite_id"] == "smoke"
    assert run["status"] == 200
    assert run["body"]["summary"]["status"] == "pass"
    assert inspected["status"] == 200
    assert inspected["body"]["run_id"] == "benchmark_run:smoke"
    assert runtime.calls[-3:] == [
        ("list_memory_benchmark_suites", {}),
        ("run_memory_benchmark", {"suite_id": "smoke", "seed": 42, "persist": True}),
        ("inspect_benchmark_run", {"run_id": "benchmark_run:smoke"}),
    ]


def test_memory_benchmark_routes_validate_payloads():
    runtime = FakeMemoryOSRuntime()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=runtime,
    )

    bad_run = api.handle("POST", "/v1/run_memory_benchmark", {"suite_id": "smoke", "unexpected": True})
    missing_inspect = api.handle("POST", "/v1/inspect_benchmark_run", {})

    assert bad_run["status"] == 400
    assert "unexpected field(s)" in bad_run["body"]["error"]["message"]
    assert missing_inspect["status"] == 400
    assert "run_id is required" in missing_inspect["body"]["error"]["message"]
    assert runtime.calls == []


def test_graph_pipeline_routes_delegate_to_memory_os_runtime():
    runtime = FakeMemoryOSRuntime()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=runtime,
    )

    readiness = api.handle(
        "POST",
        "/v1/prepare_graph_readiness_report",
        {"scope": "memory_os", "project": "Engram", "domain": "graph", "limit": 25},
    )
    proposal = api.handle(
        "POST",
        "/v1/prepare_graph_proposal_batch",
        {
            "scope": "memory_os",
            "project": "Engram",
            "domain": "graph",
            "source_refs": [{"kind": "memory", "key": "memory_alpha"}],
            "limit": 5,
            "budget_chars": 5000,
            "candidate_graph_edges": [{"edge_type": "supports"}],
        },
    )
    applied = api.handle(
        "POST",
        "/v1/apply_graph_proposal_batch",
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
    )
    repaired = api.handle(
        "POST",
        "/v1/repair_graph_edge_refs",
        {
            "source": "document_ingestion.structural",
            "limit": 25,
            "accept": True,
            "approved_by": "agent-review",
        },
    )
    reconciled = api.handle(
        "POST",
        "/v1/repair_graph_store_reconciliation",
        {
            "repair_mode": "upsert_missing",
            "limit": 2500,
            "accept": True,
            "approved_by": "agent-review",
        },
    )

    assert readiness["status"] == 200
    assert proposal["status"] == 200
    assert applied["status"] == 200
    assert repaired["status"] == 200
    assert reconciled["status"] == 200
    assert applied["body"]["graph_write_performed"] is True
    assert repaired["body"]["graph_write_performed"] is True
    assert reconciled["body"]["graph_write_performed"] is True
    assert runtime.calls[-5:] == [
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


def test_apply_document_promotion_route_delegates_to_memory_os_runtime():
    runtime = FakeMemoryOSRuntime()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=runtime,
    )

    response = api.handle(
        "POST",
        "/v1/apply_document_promotion_transaction",
        {
            "document_promotion_transaction": {"transaction_id": "doc_promote_1"},
            "accept": True,
            "approved_by": "agent-review",
            "selected_operation_indexes": [0],
        },
    )

    assert response["status"] == 200
    assert response["body"]["write_performed"] is True
    assert runtime.calls[-1] == (
        "apply_document_promotion_transaction",
        {
            "document_promotion_transaction": {"transaction_id": "doc_promote_1"},
            "accept": True,
            "approved_by": "agent-review",
            "selected_operation_indexes": [0],
        },
    )


def test_apply_document_promotion_route_preserves_selected_operation_schema_for_executor():
    runtime = FakeMemoryOSRuntime()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=runtime,
    )

    response = api.handle(
        "POST",
        "/v1/apply_document_promotion_transaction",
        {
            "document_promotion_transaction": {"transaction_id": "doc_promote_bad_index"},
            "accept": True,
            "approved_by": "agent-review",
            "selected_operation_indexes": ["0"],
        },
    )

    assert response["status"] == 200
    assert runtime.calls[-1] == (
        "apply_document_promotion_transaction",
        {
            "document_promotion_transaction": {"transaction_id": "doc_promote_bad_index"},
            "accept": True,
            "approved_by": "agent-review",
            "selected_operation_indexes": ["0"],
        },
    )


def test_memory_os_status_routes_to_runtime_container():
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=FakeMemoryOSRuntime(),
    )

    response = api.handle("GET", "/v1/memory_os/status", None)

    assert response["status"] == 200
    assert response["body"]["status"] == "ok"
    assert response["body"]["components"]["retrieval"]["backend"] == "LanceDBVectorIndex"
    assert response["body"]["components"]["graph"]["backend"] == "KuzuGraphStore"


def test_memory_os_source_import_route_creates_runtime_job():
    runtime = FakeMemoryOSRuntime()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=runtime,
    )

    response = api.handle(
        "POST",
        "/v1/memory_os/source_import_job",
        {
            "source_ref": {"source_uri": "file:///books/design.pdf"},
            "source_type": "pdf",
            "connector_id": "local_path",
        },
    )

    assert response["status"] == 200
    assert response["body"]["status"] == "queued"
    assert runtime.source_jobs == [
        {
            "source_ref": {"source_uri": "file:///books/design.pdf"},
            "source_type": "pdf",
            "connector_id": "local_path",
        }
    ]


def test_legacy_migration_routes_use_memory_os_runtime_review_gate():
    runtime = FakeMemoryOSRuntime()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=runtime,
    )

    prepared = api.handle(
        "POST",
        "/v1/prepare_legacy_memory_os_migration",
        {"legacy_dir": "data/memories", "include_details": True},
    )
    applied = api.handle(
        "POST",
        "/v1/apply_legacy_memory_os_migration",
        {
            "legacy_dir": "data/memories",
            "accept": True,
            "approved_by": "agent-review",
            "include_details": False,
        },
    )

    assert prepared["status"] == 200
    assert prepared["body"]["write_performed"] is False
    assert prepared["body"]["prepared_transaction_id"] == "txn-legacy"
    assert applied["status"] == 200
    assert applied["body"]["write_performed"] is True
    assert applied["body"]["approved_by"] == "agent-review"
    assert runtime.calls[-2:] == [
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


def test_legacy_related_to_graph_routes_use_memory_os_runtime_review_gate():
    runtime = FakeMemoryOSRuntime()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=runtime,
    )

    prepared = api.handle(
        "POST",
        "/v1/prepare_legacy_related_to_graph_migration",
        {"legacy_dir": "data/memories", "include_details": True},
    )
    applied = api.handle(
        "POST",
        "/v1/apply_legacy_related_to_graph_migration",
        {
            "legacy_dir": "data/memories",
            "accept": True,
            "approved_by": "agent-review",
            "include_details": False,
        },
    )

    assert prepared["status"] == 200
    assert prepared["body"]["write_performed"] is False
    assert prepared["body"]["prepared_transaction_id"] == "txn-legacy-graph"
    assert applied["status"] == 200
    assert applied["body"]["write_performed"] is True
    assert applied["body"]["active_memory_write_performed"] is False
    assert applied["body"]["graph_write_performed"] is True
    assert applied["body"]["approved_by"] == "agent-review"
    assert runtime.calls[-2:] == [
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


def test_daemon_memory_routes_use_memory_os_runtime_when_available():
    manager = FakeMemoryManager()
    runtime = FakeMemoryOSRuntime()
    api = EngramDaemonAPI(memory_manager=manager, memory_os_runtime=runtime)

    store = api.handle(
        "POST",
        "/v1/store_memory",
        {"key": "runtime_memory", "content": "Runtime body", "title": "Runtime"},
    )
    search = api.handle("POST", "/v1/search_memories", {"query": "runtime"})
    chunk = api.handle("POST", "/v1/retrieve_chunk", {"key": "runtime_memory", "chunk_id": 0})
    memory = api.handle("POST", "/v1/retrieve_memory", {"key": "runtime_memory"})
    deleted = api.handle("POST", "/v1/delete_memory", {"key": "runtime_memory"})

    assert store["body"]["stored"] is True
    assert store["body"]["result"]["storage_backend"] == "memory_os"
    assert search["body"]["backend"] == "memory_os"
    assert search["body"]["backend_used"] == "memory_os"
    assert search["body"]["primary_backend"] == "memory_os"
    assert search["body"]["fallback_used"] is False
    assert search["body"]["fallback_reason"] is None
    assert search["body"]["memory_os_retrieval_ready"] is True
    assert search["body"]["memory_os_retrieval_status"] == "ready"
    assert search["body"]["warnings"] == []
    assert chunk["body"]["chunk"]["text"] == "runtime chunk"
    assert memory["body"]["memory"]["content"] == "runtime memory"
    assert deleted["body"]["deleted"] is True
    assert manager.stored is None
    assert [call[0] for call in runtime.calls] == [
        "store_memory",
        "search_memories",
        "retrieve_chunk",
        "retrieve_memory",
        "delete_memory",
    ]


def test_memory_os_inspector_route_returns_read_only_runtime_report():
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        memory_os_runtime=FakeMemoryOSRuntime(),
    )

    response = api.handle("GET", "/v1/memory_os/inspector", None)

    assert response["status"] == 200
    assert response["body"]["schema_version"] == "2026-05-13.memory-os-inspector.v1"
    assert response["body"]["write_performed"] is False
    assert response["body"]["jobs"]["items"] == [{"job_id": "job:one"}]


def test_prepare_document_disassembly_returns_structured_invalid_request():
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        document_disassembler=fake_document_disassembler,
    )

    response = api.handle("POST", "/v1/prepare_document_disassembly", {"source_path": ""})

    assert response["status"] == 200
    assert response["body"] == {
        "disassembly": None,
        "error": {
            "code": "invalid_request",
            "message": "source_path is required",
        },
    }


def test_list_source_drafts_reads_daemon_owned_drafts():
    source_intake = FakeSourceIntakeManager()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        source_intake_manager=source_intake,
    )

    response = api.handle(
        "POST",
        "/v1/list_source_drafts",
        {
            "project": "Engram",
            "status": "draft",
            "limit": 10,
            "offset": 2,
        },
    )

    assert response["status"] == 200
    assert response["body"]["count"] == 1
    assert response["body"]["drafts"][0]["draft_id"] == "draft-a"
    assert source_intake.listed == {
        "project": "Engram",
        "status": "draft",
        "limit": 10,
        "offset": 2,
    }


def test_discard_source_draft_marks_daemon_owned_draft_rejected():
    source_intake = FakeSourceIntakeManager()
    api = EngramDaemonAPI(
        memory_manager=FakeMemoryManager(),
        source_intake_manager=source_intake,
    )

    response = api.handle(
        "POST",
        "/v1/discard_source_draft",
        {"draft_id": "draft-a"},
    )

    assert response["status"] == 200
    assert response["body"]["discarded"] is True
    assert response["body"]["draft_id"] == "draft-a"
    assert source_intake.discarded == "draft-a"


def test_unknown_route_returns_structured_not_found_error():
    api = EngramDaemonAPI(memory_manager=FakeMemoryManager())

    response = api.handle("POST", "/v1/missing", {})

    assert response["status"] == 404
    assert response["body"]["error"]["code"] == "not_found"


def test_query_knowledge_routes_to_memory_os_runtime():
    class FakeRuntime:
        def query_knowledge(self, request):
            return {
                "contract_version": "engram.knowledge.response.v0",
                "request_id": request["request_id"],
                "status": "ok",
                "answer": {"project": request["ask"]["project"]},
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
                        "requested": {
                            "max_artifacts": 1,
                            "max_source_reads": 12,
                            "max_tokens_out": 2500,
                        },
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

    api = EngramDaemonAPI(memory_manager=FakeMemoryManager(), memory_os_runtime=FakeRuntime())
    response = api.handle(
        "POST",
        "/v1/query_knowledge",
        {
            "request_id": "req-api",
            "ask": {
                "goal": "Get context.",
                "task_type": "project_orientation",
                "project": "Engram",
            },
        },
    )

    assert response["status"] == 200
    assert response["body"]["request_id"] == "req-api"
    assert response["body"]["answer"]["project"] == "Engram"
