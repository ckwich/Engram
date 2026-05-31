"""Loopback JSON API surface for the Engram daemon.

The daemon owns live storage/index state. MCP stdio processes can call this
API as thin clients instead of each process trying to own embedded ChromaDB.
"""
from __future__ import annotations

import asyncio
import base64
import os
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from core.document_extractors import prepare_document_disassembly
from core.document_workflow import DocumentWorkflow
from core.memory_limits import MAX_DIRECT_MEMORY_CHARS, direct_memory_too_long_message
from core.memory_os._records import hash_payload
from core.memory_manager import DuplicateMemoryError, memory_manager
from core.memory_os.memory_guardrails import evaluate_memory_write
from core.memory_os.runtime import MemoryOSRuntime
from core.memory_os.runtime_paths import memory_os_root_for_data_root, resolve_data_root
from core.memory_os.sync_peer_transport import record_sync_request_nonce, verify_sync_request_signature
from core.memory_os.sync_transport import store_inbound_sync_bundle
from core.mcp.tool_registry import CANONICAL_TOOLS, DAEMON_ROUTES, concurrent_daemon_route_paths
from core.source_intake import source_intake_manager
from core.usage_meter import usage_meter as daemon_usage_meter


_DOCUMENT_INGESTION_PLAN_FIELDS = frozenset(
    {
        "source_path",
        "project",
        "domain",
        "profile",
        "page_window_size",
        "analysis_policy",
        "approval_mode",
        "budget",
    }
)
_DOCUMENT_INGESTION_RUN_FIELDS = frozenset(
    {
        "ingestion_id",
        "accept",
        "approved_by",
        "review_packets",
        "understanding_analysis",
        "visual_preview",
    }
)
_DOCUMENT_INGESTION_INSPECT_FIELDS = frozenset({"ingestion_id", "document_id"})
_DOCUMENT_COVERAGE_PASS_FIELDS = frozenset(
    {
        "ingestion_record",
        "review_packets",
        "coverage_policy",
        "coverage_options",
    }
)
_KNOWLEDGE_BRANCH_FIELDS = frozenset(
    {
        "name",
        "source_refs",
        "base_snapshot_ref",
        "metadata",
    }
)
_KNOWLEDGE_PR_FIELDS = frozenset(
    {
        "branch_id",
        "title",
        "proposed_operations",
        "source_refs",
        "document_refs",
        "metadata",
    }
)
_MEMORY_CI_FIELDS = frozenset({"knowledge_pr_id", "gates", "ci_context"})
_KNOWLEDGE_PR_INSPECT_FIELDS = frozenset({"knowledge_pr_id"})
_KNOWLEDGE_PR_MERGE_FIELDS = frozenset(
    {
        "knowledge_pr_id",
        "accept",
        "approved_by",
        "selected_operation_ids",
        "selected_operation_indexes",
        "ci_waivers",
    }
)
_BENCHMARK_LIST_FIELDS = frozenset({"suite_id"})
_BENCHMARK_RUN_FIELDS = frozenset({"suite_id", "seed", "persist"})
_BENCHMARK_INSPECT_FIELDS = frozenset({"run_id"})
_SYNC_DEVICE_IDENTITY_FIELDS = frozenset({"device_name"})
_SYNC_PEER_REGISTER_FIELDS = frozenset({"peer_identity_packet", "accept", "approved_by"})
_SYNC_CHANGESET_PREPARE_FIELDS = frozenset({"peer_id"})
_SYNC_CHANGESET_EXPORT_FIELDS = frozenset({"plan", "accept", "approved_by"})
_SYNC_APPLY_PREPARE_FIELDS = frozenset({"bundle_b64"})
_SYNC_APPLY_FIELDS = frozenset({"bundle_b64", "plan", "accept", "approved_by"})
_SYNC_CONVERGENCE_FIELDS = frozenset({"peer_id"})
_SYNC_CONFLICT_LIST_FIELDS = frozenset({"status"})
_SYNC_CONFLICT_RESOLVE_FIELDS = frozenset({"conflict_id", "resolution", "accept", "approved_by"})
_SYNC_PEER_TRANSPORT_FIELDS = frozenset(
    {"peer_id", "url", "mode", "allow_pull", "accept", "approved_by"}
)
_SYNC_PEER_INSPECT_FIELDS = frozenset({"peer_id"})
_SYNC_PUSH_CHANGESET_FIELDS = frozenset({"peer_id", "accept", "approved_by"})
_SYNC_INBOX_LIST_FIELDS = frozenset({"peer_id"})
_SYNC_INBOX_PREPARE_APPLY_FIELDS = frozenset({"peer_id", "limit"})
_SYNC_INBOX_APPLY_FIELDS = frozenset(
    {"peer_id", "limit", "accept", "approved_by", "stop_on_error"}
)
_SYNC_INBOX_PRUNE_FIELDS = frozenset({"peer_id", "limit", "accept", "approved_by"})
_SYNC_PEER_ROUTE_HELLO = "/v1/sync/hello"
_SYNC_PEER_ROUTE_INBOX = "/v1/sync/inbox"
_SYNC_PEER_ROUTE_STATE = "/v1/sync/state"
_SYNC_PEER_ROUTE_PULL_BUNDLE = "/v1/sync/pull_bundle"
_SYNC_PEER_ROUTES = frozenset(
    {
        _SYNC_PEER_ROUTE_HELLO,
        _SYNC_PEER_ROUTE_INBOX,
        _SYNC_PEER_ROUTE_STATE,
        _SYNC_PEER_ROUTE_PULL_BUNDLE,
    }
)

_CONCURRENT_READ_ROUTES = frozenset(concurrent_daemon_route_paths())
_DAEMON_TOOL_BY_PATH = {
    (route.path.rstrip("/") or "/"): name
    for name, route in DAEMON_ROUTES.items()
    if name in CANONICAL_TOOLS
}


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_int(*values: Any) -> int | None:
    for value in values:
        integer = _int_or_none(value)
        if integer is not None:
            return integer
    return None


def _format_health_size(num_bytes: int | None) -> str | None:
    if num_bytes is None:
        return None
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024.0
    return f"{size:.1f} PB"


def _memory_os_health_stats(
    legacy_stats: dict[str, Any],
    memory_os_status: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build active `/health.stats` counts from Memory OS when it owns serving."""
    if not isinstance(memory_os_status, dict):
        stats = dict(legacy_stats)
        stats.setdefault("source", "legacy_json_chroma")
        return stats

    components = memory_os_status.get("components") or {}
    runtime_preflight = components.get("runtime_preflight") or {}
    ledger = runtime_preflight.get("ledger") or {}
    tables = ledger.get("tables") or {}
    retrieval_state = ((components.get("retrieval") or {}).get("state") or {})
    retrieval_manifest = retrieval_state.get("manifest") or {}
    graph_state = ((components.get("graph") or {}).get("state") or {})
    graph_ledger = graph_state.get("ledger") or {}
    ledger_size_bytes = _int_or_none(ledger.get("size_bytes"))

    stats = dict(legacy_stats)
    stats.update(
        {
            "source": "memory_os",
            "total_memories": _first_int(tables.get("memories")),
            "total_chunks": _first_int(
                tables.get("chunks"),
                retrieval_manifest.get("indexed_count"),
                retrieval_manifest.get("source_count"),
            ),
            "total_documents": _first_int(
                tables.get("documents"),
                (retrieval_manifest.get("stats") or {}).get("document_count"),
            ),
            "total_sources": _first_int(tables.get("sources")),
            "total_graph_edges": _first_int(
                tables.get("graph_edges"),
                graph_ledger.get("edge_count"),
            ),
            "retrieval_source_count": _first_int(retrieval_manifest.get("source_count")),
            "retrieval_indexed_count": _first_int(retrieval_manifest.get("indexed_count")),
            "memory_os_root": memory_os_status.get("root"),
            "memory_os_ledger_bytes": ledger_size_bytes,
            "memory_os_ledger_size": _format_health_size(ledger_size_bytes),
            "legacy_total_memories": legacy_stats.get("total_memories"),
            "legacy_total_chunks": legacy_stats.get("total_chunks"),
            "storage_source": "legacy_json_chroma",
        }
    )
    return stats


class EngramDaemonAPI:
    """Small request dispatcher for daemon-owned memory operations."""

    def __init__(
        self,
        memory_manager=memory_manager,
        source_intake_manager=source_intake_manager,
        document_disassembler=prepare_document_disassembly,
        document_tools: Any | None = None,
        memory_os_runtime: MemoryOSRuntime | None = None,
        usage_meter: Any | None = daemon_usage_meter,
    ):
        self.memory_manager = memory_manager
        self.source_intake_manager = source_intake_manager
        self.document_disassembler = document_disassembler
        self.document_tools = document_tools or DocumentWorkflow(document_disassembler)
        self.memory_os_runtime = memory_os_runtime
        self.usage_meter = usage_meter
        self._request_lock = threading.RLock()
        self._background_threads: list[threading.Thread] = []

    def handle(self, method: str, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        """Handle one daemon request and return {status, body}."""
        started_at = time.perf_counter()
        route = urlparse(path).path.rstrip("/") or "/"
        if self._route_can_run_concurrently(method, route):
            response = asyncio.run(self.handle_async(method, path, payload))
        else:
            with self._request_lock:
                response = asyncio.run(self.handle_async(method, path, payload))
        self._record_daemon_usage(method, path, payload, response, started_at)
        return response

    def handle_sync_peer(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Handle one sync-only sidecar request; not used by the raw daemon."""
        with self._request_lock:
            return asyncio.run(self.handle_sync_peer_async(method, path, payload))

    def _route_can_run_concurrently(self, method: str, route: str) -> bool:
        normalized_method = method.upper()
        if normalized_method == "GET":
            return route in _CONCURRENT_READ_ROUTES
        if normalized_method == "POST":
            return route in _CONCURRENT_READ_ROUTES
        return False

    async def handle_async(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        parsed_path = urlparse(path)
        route = parsed_path.path.rstrip("/") or "/"
        query = parse_qs(parsed_path.query)
        request = payload if isinstance(payload, dict) else {}
        method = method.upper()

        try:
            if route.startswith("/v1/sync/"):
                return self._error(
                    404,
                    "sync_route_not_available",
                    "Sync peer routes are served only by the sync listener.",
                )
            if method == "GET" and route == "/health":
                stats_error = None
                try:
                    stats = self.memory_manager.get_stats()
                except Exception as exc:
                    stats_error = {"code": "legacy_stats_unavailable", "message": str(exc)}
                    stats = self.memory_manager.get_json_fallback_stats(chroma_error=str(exc))
                memory_os_status = (
                    self.memory_os_runtime.status()
                    if self.memory_os_runtime is not None
                    else None
                )
                active_stats = _memory_os_health_stats(stats, memory_os_status)
                body = {
                    "daemon": "engramd",
                    "status": "ok",
                    "stats": active_stats,
                    "serving": self._serving_status(
                        refresh_retrieval_state=True,
                        memory_os_status=memory_os_status,
                    ),
                    "legacy_stats": stats,
                    "legacy_stats_error": stats_error,
                    "error": None,
                }
                if memory_os_status is not None:
                    body["memory_os"] = memory_os_status
                return self._ok(body)
            if method == "GET" and route == "/v1/memory_os/status":
                return self._ok(self._runtime().status())
            if method == "GET" and route == "/v1/memory_os/inspector":
                limit = _bounded_query_int(query, "limit", default=20, minimum=1, maximum=100)
                return self._ok(self._runtime().inspector(limit=limit))
            if method != "POST":
                return self._error(405, "method_not_allowed", f"{method} is not allowed for {route}")
            if route == "/v1/memory_os/source_import_job":
                return self._memory_os_source_import_job(request)
            if route == "/v1/prepare_legacy_memory_os_migration":
                return self._prepare_legacy_memory_os_migration(request)
            if route == "/v1/apply_legacy_memory_os_migration":
                return self._apply_legacy_memory_os_migration(request)
            if route == "/v1/prepare_legacy_related_to_graph_migration":
                return self._prepare_legacy_related_to_graph_migration(request)
            if route == "/v1/apply_legacy_related_to_graph_migration":
                return self._apply_legacy_related_to_graph_migration(request)
            if route == "/v1/query_knowledge":
                return await self._query_knowledge(request)
            if route == "/v1/discover_memory_capabilities":
                return await self._discover_memory_capabilities(request)
            if route == "/v1/search_memories":
                return await self._search_memories(request)
            if route == "/v1/retrieve_chunk":
                return await self._retrieve_chunk(request)
            if route == "/v1/retrieve_chunks":
                return await self._retrieve_chunks(request)
            if route == "/v1/retrieve_memory":
                return await self._retrieve_memory(request)
            if route == "/v1/store_memory":
                return await self._store_memory(request)
            if route == "/v1/prepare_source_memory":
                return await self._prepare_source_memory(request)
            if route == "/v1/list_document_extractors":
                return await self._document_tool("list_document_extractors", request)
            if route == "/v1/preview_document_source_connector":
                return await self._document_tool("preview_document_source_connector", request)
            if route == "/v1/prepare_document_disassembly":
                return await self._prepare_document_disassembly(request)
            if route == "/v1/prepare_document_coverage_workbench":
                return await self._document_tool("prepare_document_coverage_workbench", request)
            if route == "/v1/prepare_document_coverage_pass":
                return await self._prepare_document_coverage_pass(request)
            if route == "/v1/prepare_document_intake_review":
                return await self._document_tool("prepare_document_intake_review", request)
            if route == "/v1/prepare_document_extraction_request":
                return await self._document_tool("prepare_document_extraction_request", request)
            if route == "/v1/prepare_document_extraction_result":
                return await self._document_tool("prepare_document_extraction_result", request)
            if route == "/v1/preview_document_extraction":
                return await self._document_tool("preview_document_extraction", request)
            if route == "/v1/prepare_visual_extraction_request":
                return await self._document_tool("prepare_visual_extraction_request", request)
            if route == "/v1/preview_visual_extraction":
                return await self._document_tool("preview_visual_extraction", request)
            if route == "/v1/prepare_document_understanding_packet":
                return await self._document_tool("prepare_document_understanding_packet", request)
            if route == "/v1/prepare_document_draft":
                return await self._document_tool("prepare_document_draft", request)
            if route == "/v1/prepare_document_promotion_transaction":
                return await self._document_tool("prepare_document_promotion_transaction", request)
            if route == "/v1/apply_document_promotion_transaction":
                return await self._apply_document_promotion_transaction(request)
            if route == "/v1/prepare_document_artifact_store":
                return await self._prepare_document_artifact_store(request)
            if route == "/v1/store_document_artifact":
                return await self._store_document_artifact(request)
            if route == "/v1/prepare_document_ingestion_plan":
                return await self._prepare_document_ingestion_plan(request)
            if route == "/v1/run_document_ingestion":
                return await self._run_document_ingestion(request)
            if route == "/v1/resume_document_ingestion":
                return await self._resume_document_ingestion(request)
            if route == "/v1/inspect_document_ingestion":
                return await self._inspect_document_ingestion(request)
            if route == "/v1/prepare_document_ingestion_completion":
                return await self._prepare_document_ingestion_completion(request)
            if route == "/v1/complete_document_ingestion":
                return await self._complete_document_ingestion(request)
            if route == "/v1/prepare_knowledge_branch":
                return await self._prepare_knowledge_branch(request)
            if route == "/v1/prepare_knowledge_pr":
                return await self._prepare_knowledge_pr(request)
            if route == "/v1/run_memory_ci":
                return await self._run_memory_ci(request)
            if route == "/v1/inspect_knowledge_pr":
                return await self._inspect_knowledge_pr(request)
            if route == "/v1/merge_knowledge_pr":
                return await self._merge_knowledge_pr(request)
            if route == "/v1/list_memory_benchmark_suites":
                return await self._list_memory_benchmark_suites(request)
            if route == "/v1/run_memory_benchmark":
                return await self._run_memory_benchmark(request)
            if route == "/v1/inspect_benchmark_run":
                return await self._inspect_benchmark_run(request)
            if route == "/v1/ensure_sync_device_identity":
                return await self._ensure_sync_device_identity(request)
            if route == "/v1/export_local_sync_identity":
                return await self._export_local_sync_identity(request)
            if route == "/v1/register_sync_peer":
                return await self._register_sync_peer(request)
            if route == "/v1/inspect_sync_state":
                return await self._inspect_sync_state(request)
            if route == "/v1/prepare_sync_changeset":
                return await self._prepare_sync_changeset(request)
            if route == "/v1/export_sync_changeset":
                return await self._export_sync_changeset(request)
            if route == "/v1/prepare_sync_apply":
                return await self._prepare_sync_apply(request)
            if route == "/v1/apply_sync_changeset":
                return await self._apply_sync_changeset(request)
            if route == "/v1/inspect_sync_convergence":
                return await self._inspect_sync_convergence(request)
            if route == "/v1/list_sync_conflicts":
                return await self._list_sync_conflicts(request)
            if route == "/v1/resolve_sync_conflict":
                return await self._resolve_sync_conflict(request)
            if route == "/v1/configure_sync_peer_transport":
                return await self._configure_sync_peer_transport(request)
            if route == "/v1/inspect_sync_peer":
                return await self._inspect_sync_peer(request)
            if route == "/v1/push_sync_changeset":
                return await self._push_sync_changeset(request)
            if route == "/v1/list_sync_inbox":
                return await self._list_sync_inbox(request)
            if route == "/v1/prepare_sync_inbox_apply":
                return await self._prepare_sync_inbox_apply(request)
            if route == "/v1/apply_sync_inbox":
                return await self._apply_sync_inbox(request)
            if route == "/v1/prune_applied_sync_inbox_artifacts":
                return await self._prune_applied_sync_inbox_artifacts(request)
            if route == "/v1/prepare_graph_readiness_report":
                return await self._prepare_graph_readiness_report(request)
            if route == "/v1/prepare_graph_proposal_batch":
                return await self._prepare_graph_proposal_batch(request)
            if route == "/v1/apply_graph_proposal_batch":
                return await self._apply_graph_proposal_batch(request)
            if route == "/v1/repair_graph_edge_refs":
                return await self._repair_graph_edge_refs(request)
            if route == "/v1/repair_graph_store_reconciliation":
                return await self._repair_graph_store_reconciliation(request)
            if route == "/v1/list_source_drafts":
                return await self._list_source_drafts(request)
            if route == "/v1/discard_source_draft":
                return await self._discard_source_draft(request)
            if route == "/v1/store_prepared_memory":
                return await self._store_prepared_memory(request)
            if route == "/v1/check_duplicate":
                return await self._check_duplicate(request)
            if route == "/v1/update_memory_metadata":
                return await self._update_memory_metadata(request)
            if route == "/v1/repair_memory_metadata":
                return await self._repair_memory_metadata(request)
            if route == "/v1/repair_document_metadata":
                return await self._repair_document_metadata(request)
            if route == "/v1/delete_memory":
                return await self._delete_memory(request)
            return self._error(404, "not_found", f"Unknown daemon route: {route}")
        except Exception as exc:
            return self._error(500, "runtime_error", f"Engram daemon error: {exc}")

    async def handle_sync_peer_async(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Handle signed peer sync requests from the sync listener sidecar."""
        route = urlparse(path).path.rstrip("/") or "/"
        request = payload if isinstance(payload, dict) else {}
        method = method.upper()
        if method != "POST":
            return self._error(405, "method_not_allowed", f"{method} is not allowed for {route}")
        try:
            return await self._sync_peer_route(method, route, request)
        except Exception as exc:
            return self._error(500, "runtime_error", f"Engram sync listener error: {exc}")

    async def _query_knowledge(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.memory_os_runtime is None:
            return self._error(
                503,
                "memory_os_unavailable",
                "query_knowledge requires daemon-owned Memory OS runtime.",
            )
        return self._ok(self.memory_os_runtime.query_knowledge(request))

    async def _discover_memory_capabilities(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.memory_os_runtime is None:
            return self._error(
                503,
                "memory_os_unavailable",
                "discover_memory_capabilities requires daemon-owned Memory OS runtime.",
            )
        return self._ok(
            self.memory_os_runtime.discover_memory_capabilities(
                query=str(request.get("query") or ""),
                budget_chars=_int_value(request.get("budget_chars"), default=4000),
            )
        )

    async def _prepare_document_artifact_store(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.memory_os_runtime is None:
            return self._error(
                503,
                "memory_os_unavailable",
                "prepare_document_artifact_store requires daemon-owned Memory OS runtime.",
            )
        review_packet = request.get("review_packet")
        artifact_family = str(request.get("artifact_family") or "document_evidence")
        return self._ok(
            self.memory_os_runtime.prepare_document_artifact_store(
                review_packet,
                artifact_family=artifact_family,
            )
        )

    async def _store_document_artifact(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.memory_os_runtime is None:
            return self._error(
                503,
                "memory_os_unavailable",
                "store_document_artifact requires daemon-owned Memory OS runtime.",
            )
        return self._ok(
            self.memory_os_runtime.store_document_artifact(
                str(request.get("prepared_transaction_id") or ""),
                accept=bool(request.get("accept", False)),
                review_packet=request.get("review_packet"),
            )
        )

    async def _prepare_document_ingestion_plan(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _DOCUMENT_INGESTION_PLAN_FIELDS)
        if error is not None:
            return error
        if not _required_text(request, "source_path"):
            return self._error(400, "invalid_request", "source_path is required")
        return self._ok(self._runtime().prepare_document_ingestion_plan(**request))

    async def _run_document_ingestion(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _DOCUMENT_INGESTION_RUN_FIELDS)
        if error is not None:
            return error
        if not _required_text(request, "ingestion_id"):
            return self._error(400, "invalid_request", "ingestion_id is required")
        runtime = self._runtime()
        queued = runtime.enqueue_document_ingestion_run(**request)
        if queued.get("status") == "queued":
            self._start_document_ingestion_worker(runtime)
        return self._ok(queued)

    async def _resume_document_ingestion(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _DOCUMENT_INGESTION_RUN_FIELDS)
        if error is not None:
            return error
        if not _required_text(request, "ingestion_id"):
            return self._error(400, "invalid_request", "ingestion_id is required")
        runtime = self._runtime()
        queued = runtime.enqueue_document_ingestion_resume(**request)
        if queued.get("status") == "queued":
            self._start_document_ingestion_worker(runtime)
        return self._ok(queued)

    async def _inspect_document_ingestion(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _DOCUMENT_INGESTION_INSPECT_FIELDS)
        if error is not None:
            return error
        if not (_required_text(request, "ingestion_id") or _required_text(request, "document_id")):
            return self._error(400, "invalid_request", "ingestion_id or document_id is required")
        return self._ok(self._runtime().inspect_document_ingestion(**request))

    async def _prepare_document_coverage_pass(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _DOCUMENT_COVERAGE_PASS_FIELDS)
        if error is not None:
            return error
        if not isinstance(request.get("ingestion_record"), dict):
            return self._error(400, "invalid_request", "ingestion_record is required")
        return self._ok(self._runtime().prepare_document_coverage_pass(**request))

    async def _prepare_knowledge_branch(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _KNOWLEDGE_BRANCH_FIELDS)
        if error is not None:
            return error
        if not _required_text(request, "name"):
            return self._error(400, "invalid_request", "name is required")
        return self._ok(self._runtime().prepare_knowledge_branch(**request))

    async def _prepare_knowledge_pr(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _KNOWLEDGE_PR_FIELDS)
        if error is not None:
            return error
        if not _required_text(request, "branch_id"):
            return self._error(400, "invalid_request", "branch_id is required")
        if not _required_text(request, "title"):
            return self._error(400, "invalid_request", "title is required")
        return self._ok(self._runtime().prepare_knowledge_pr(**request))

    async def _run_memory_ci(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _MEMORY_CI_FIELDS)
        if error is not None:
            return error
        if not _required_text(request, "knowledge_pr_id"):
            return self._error(400, "invalid_request", "knowledge_pr_id is required")
        return self._ok(self._runtime().run_memory_ci(**request))

    async def _inspect_knowledge_pr(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _KNOWLEDGE_PR_INSPECT_FIELDS)
        if error is not None:
            return error
        if not _required_text(request, "knowledge_pr_id"):
            return self._error(400, "invalid_request", "knowledge_pr_id is required")
        return self._ok(self._runtime().inspect_knowledge_pr(**request))

    async def _merge_knowledge_pr(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _KNOWLEDGE_PR_MERGE_FIELDS)
        if error is not None:
            return error
        if not _required_text(request, "knowledge_pr_id"):
            return self._error(400, "invalid_request", "knowledge_pr_id is required")
        return self._ok(self._runtime().merge_knowledge_pr(**request))

    async def _list_memory_benchmark_suites(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _BENCHMARK_LIST_FIELDS)
        if error is not None:
            return error
        suite_id = _optional_text(request.get("suite_id"))
        payload = self._runtime().list_memory_benchmark_suites()
        if suite_id:
            suites = [
                suite
                for suite in payload.get("suites") or []
                if isinstance(suite, dict) and suite.get("suite_id") == suite_id
            ]
            payload = {**payload, "suites": suites}
        return self._ok(payload)

    async def _run_memory_benchmark(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _BENCHMARK_RUN_FIELDS)
        if error is not None:
            return error
        return self._ok(
            self._runtime().run_memory_benchmark(
                suite_id=_optional_text(request.get("suite_id")) or "smoke",
                seed=_int_value(request.get("seed"), default=42),
                persist=bool(request.get("persist", True)),
            )
        )

    async def _inspect_benchmark_run(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _BENCHMARK_INSPECT_FIELDS)
        if error is not None:
            return error
        if not _required_text(request, "run_id"):
            return self._error(400, "invalid_request", "run_id is required")
        return self._ok(self._runtime().inspect_benchmark_run(**request))

    async def _ensure_sync_device_identity(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _SYNC_DEVICE_IDENTITY_FIELDS)
        if error is not None:
            return error
        return self._ok(
            self._runtime().ensure_sync_device_identity(
                device_name=_optional_text(request.get("device_name")) or "local",
            )
        )

    async def _export_local_sync_identity(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, frozenset())
        if error is not None:
            return error
        return self._ok(self._runtime().export_local_sync_identity())

    async def _register_sync_peer(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _SYNC_PEER_REGISTER_FIELDS)
        if error is not None:
            return error
        packet = request.get("peer_identity_packet")
        if not isinstance(packet, dict):
            return self._error(400, "invalid_request", "peer_identity_packet is required")
        return self._ok(
            self._runtime().register_sync_peer(
                peer_identity_packet=packet,
                accept=bool(request.get("accept", False)),
                approved_by=_optional_text(request.get("approved_by")),
            )
        )

    async def _inspect_sync_state(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, frozenset())
        if error is not None:
            return error
        return self._ok(self._runtime().inspect_sync_state())

    async def _prepare_sync_changeset(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _SYNC_CHANGESET_PREPARE_FIELDS)
        if error is not None:
            return error
        if not _required_text(request, "peer_id"):
            return self._error(400, "invalid_request", "peer_id is required")
        return self._ok(self._runtime().prepare_sync_changeset(peer_id=str(request["peer_id"])))

    async def _export_sync_changeset(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _SYNC_CHANGESET_EXPORT_FIELDS)
        if error is not None:
            return error
        plan = request.get("plan")
        if not isinstance(plan, dict):
            return self._error(400, "invalid_request", "plan is required")
        return self._ok(
            self._runtime().export_sync_changeset(
                plan=plan,
                accept=bool(request.get("accept", False)),
                approved_by=_optional_text(request.get("approved_by")),
            )
        )

    async def _prepare_sync_apply(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _SYNC_APPLY_PREPARE_FIELDS)
        if error is not None:
            return error
        bundle = _decode_b64_field(request, "bundle_b64")
        if bundle is None:
            return self._error(400, "invalid_request", "bundle_b64 is required")
        return self._ok(self._runtime().prepare_sync_apply(bundle_bytes=bundle))

    async def _apply_sync_changeset(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _SYNC_APPLY_FIELDS)
        if error is not None:
            return error
        bundle = _decode_b64_field(request, "bundle_b64")
        if bundle is None:
            return self._error(400, "invalid_request", "bundle_b64 is required")
        plan = request.get("plan")
        if not isinstance(plan, dict):
            return self._error(400, "invalid_request", "plan is required")
        return self._ok(
            self._runtime().apply_sync_changeset(
                bundle_bytes=bundle,
                plan=plan,
                accept=bool(request.get("accept", False)),
                approved_by=_optional_text(request.get("approved_by")),
            )
        )

    async def _inspect_sync_convergence(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _SYNC_CONVERGENCE_FIELDS)
        if error is not None:
            return error
        if not _required_text(request, "peer_id"):
            return self._error(400, "invalid_request", "peer_id is required")
        return self._ok(self._runtime().inspect_sync_convergence(peer_id=str(request["peer_id"])))

    async def _list_sync_conflicts(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _SYNC_CONFLICT_LIST_FIELDS)
        if error is not None:
            return error
        return self._ok(self._runtime().list_sync_conflicts(status=_optional_text(request.get("status"))))

    async def _resolve_sync_conflict(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _SYNC_CONFLICT_RESOLVE_FIELDS)
        if error is not None:
            return error
        if not _required_text(request, "conflict_id"):
            return self._error(400, "invalid_request", "conflict_id is required")
        if not _required_text(request, "resolution"):
            return self._error(400, "invalid_request", "resolution is required")
        return self._ok(
            self._runtime().resolve_sync_conflict(
                conflict_id=str(request["conflict_id"]),
                resolution=str(request["resolution"]),
                accept=bool(request.get("accept", False)),
                approved_by=_optional_text(request.get("approved_by")),
            )
        )

    async def _configure_sync_peer_transport(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _SYNC_PEER_TRANSPORT_FIELDS)
        if error is not None:
            return error
        if not _required_text(request, "peer_id"):
            return self._error(400, "invalid_request", "peer_id is required")
        if not _required_text(request, "url"):
            return self._error(400, "invalid_request", "url is required")
        return self._ok(
            self._runtime().configure_sync_peer_transport(
                peer_id=str(request["peer_id"]),
                url=str(request["url"]),
                mode=_optional_text(request.get("mode")) or "manual",
                allow_pull=bool(request.get("allow_pull", False)),
                accept=bool(request.get("accept", False)),
                approved_by=_optional_text(request.get("approved_by")),
            )
        )

    async def _inspect_sync_peer(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _SYNC_PEER_INSPECT_FIELDS)
        if error is not None:
            return error
        if not _required_text(request, "peer_id"):
            return self._error(400, "invalid_request", "peer_id is required")
        return self._ok(self._runtime().inspect_sync_peer(peer_id=str(request["peer_id"])))

    async def _push_sync_changeset(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _SYNC_PUSH_CHANGESET_FIELDS)
        if error is not None:
            return error
        if not _required_text(request, "peer_id"):
            return self._error(400, "invalid_request", "peer_id is required")
        return self._ok(
            self._runtime().push_sync_changeset(
                peer_id=str(request["peer_id"]),
                accept=bool(request.get("accept", False)),
                approved_by=_optional_text(request.get("approved_by")),
            )
        )

    async def _list_sync_inbox(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _SYNC_INBOX_LIST_FIELDS)
        if error is not None:
            return error
        return self._ok(self._runtime().list_sync_inbox(peer_id=_optional_text(request.get("peer_id"))))

    async def _prepare_sync_inbox_apply(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _SYNC_INBOX_PREPARE_APPLY_FIELDS)
        if error is not None:
            return error
        return self._ok(
            self._runtime().prepare_sync_inbox_apply(
                peer_id=_optional_text(request.get("peer_id")),
                limit=_int_value(request.get("limit"), default=50),
            )
        )

    async def _apply_sync_inbox(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _SYNC_INBOX_APPLY_FIELDS)
        if error is not None:
            return error
        return self._ok(
            self._runtime().apply_sync_inbox(
                peer_id=_optional_text(request.get("peer_id")),
                limit=_int_value(request.get("limit"), default=50),
                accept=bool(request.get("accept", False)),
                approved_by=_optional_text(request.get("approved_by")),
                stop_on_error=bool(request.get("stop_on_error", True)),
            )
        )

    async def _prune_applied_sync_inbox_artifacts(self, request: dict[str, Any]) -> dict[str, Any]:
        error = self._validate_allowed_fields(request, _SYNC_INBOX_PRUNE_FIELDS)
        if error is not None:
            return error
        return self._ok(
            self._runtime().prune_applied_sync_inbox_artifacts(
                peer_id=_optional_text(request.get("peer_id")),
                limit=_int_value(request.get("limit"), default=50),
                accept=bool(request.get("accept", False)),
                approved_by=_optional_text(request.get("approved_by")),
            )
        )

    async def _sync_peer_route(
        self,
        method: str,
        route: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        if route not in _SYNC_PEER_ROUTES:
            return self._error(404, "sync_route_not_found", f"Unknown sync peer route: {route}")
        if route == _SYNC_PEER_ROUTE_HELLO:
            body_payload = {"peer_id": _optional_text(request.get("peer_id"))}
            verified = self._verify_sync_peer_request(method, route, request, body_payload)
            if verified is not None:
                return verified
            return self._ok(
                {
                    "schema_version": "2026-05-26.sync-peer-route.v1",
                    "status": "ok",
                    "write_performed": False,
                    "local_identity": self._runtime().export_local_sync_identity(),
                    "peer_id": _optional_text(request.get("peer_id")),
                    "error": None,
                }
            )
        if route == _SYNC_PEER_ROUTE_INBOX:
            bundle_b64 = _optional_text(request.get("bundle"))
            body_payload = {"bundle": bundle_b64}
            verified = self._verify_sync_peer_request(method, route, request, body_payload)
            if verified is not None:
                return verified
            bundle = _decode_b64_field({"bundle": bundle_b64}, "bundle")
            if bundle is None:
                return self._error(400, "invalid_request", "bundle is required")
            return self._ok(
                store_inbound_sync_bundle(
                    self._runtime(),
                    bundle,
                    {
                        "transport_type": "sync_peer",
                        "peer_id": _optional_text(request.get("peer_id")),
                        "route": route,
                        "nonce": _optional_text(request.get("nonce")),
                    },
                )
            )
        if route == _SYNC_PEER_ROUTE_STATE:
            body_payload = {"peer_id": _optional_text(request.get("peer_id"))}
            verified = self._verify_sync_peer_request(method, route, request, body_payload)
            if verified is not None:
                return verified
            peer_id = _optional_text(request.get("peer_id"))
            state = self._runtime().inspect_sync_state()
            peer = self._runtime().inspect_sync_peer(peer_id=peer_id or "")
            return self._ok(
                {
                    "schema_version": "2026-05-26.sync-peer-route.v1",
                    "status": "ok",
                    "write_performed": False,
                    "peer": peer.get("peer") if isinstance(peer, dict) else None,
                    "sync_state": state,
                    "error": None,
                }
            )
        if route == _SYNC_PEER_ROUTE_PULL_BUNDLE:
            body_payload = {"peer_id": _optional_text(request.get("peer_id"))}
            verified = self._verify_sync_peer_request(method, route, request, body_payload)
            if verified is not None:
                return verified
            return self._ok(
                {
                    "schema_version": "2026-05-26.sync-peer-route.v1",
                    "status": "policy_denied",
                    "write_performed": False,
                    "error": {"code": "sync_pull_not_allowed"},
                }
            )
        return self._error(404, "sync_route_not_found", f"Unknown sync peer route: {route}")

    def _verify_sync_peer_request(
        self,
        method: str,
        route: str,
        request: dict[str, Any],
        body_payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        required = ("peer_id", "target_device_id", "nonce", "timestamp", "body_hash", "signature")
        if any(not _optional_text(request.get(field)) for field in required):
            return self._error(
                401,
                "sync_peer_signature_required",
                "Signed sync peer request metadata is required.",
            )
        expected_body_hash = hash_payload(body_payload)
        verified = verify_sync_request_signature(
            self._runtime(),
            peer_id=str(request["peer_id"]),
            nonce=str(request["nonce"]),
            timestamp=str(request["timestamp"]),
            body_hash=str(request["body_hash"]),
            signature=str(request["signature"]),
            method=method,
            route=route,
            target_device_id=str(request["target_device_id"]),
            record_nonce=False,
        )
        if verified.get("status") == "ok":
            if str(request.get("body_hash") or "") != expected_body_hash:
                return self._error(
                    401,
                    "sync_body_hash_mismatch",
                    "Sync request body hash does not match the signed payload.",
                )
            recorded = record_sync_request_nonce(
                self._runtime(),
                peer_id=str(request["peer_id"]),
                nonce=str(request["nonce"]),
                route=route,
                body_hash=str(request["body_hash"]),
            )
            if recorded.get("status") != "ok":
                code = str((recorded.get("error") or {}).get("code") or "sync_nonce_replay")
                return self._error(_sync_error_status(code), code, _sync_error_message(code))
            return None
        code = str((verified.get("error") or {}).get("code") or "sync_peer_signature_invalid")
        return self._error(_sync_error_status(code), code, _sync_error_message(code))

    async def _repair_document_metadata(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._ok(
            self._runtime().repair_document_metadata(
                project=_optional_text(request.get("project")),
                document_ids=_string_list(request.get("document_ids")),
                accept=bool(request.get("accept", False)),
                approved_by=_optional_text(request.get("approved_by")),
            )
        )

    async def _prepare_document_ingestion_completion(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.memory_os_runtime is None:
            return self._error(
                503,
                "memory_os_unavailable",
                "prepare_document_ingestion_completion requires daemon-owned Memory OS runtime.",
            )
        return self._ok(
            self.memory_os_runtime.prepare_document_ingestion_completion(
                document_id=str(request.get("document_id") or ""),
                artifact_id=_optional_text(request.get("artifact_id")),
                visual_request=request.get("visual_request"),
                visual_preview=request.get("visual_preview"),
                understanding_packet=request.get("understanding_packet"),
                document_promotion_transaction=request.get("document_promotion_transaction"),
                coverage_waivers=request.get("coverage_waivers"),
            )
        )

    async def _complete_document_ingestion(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.memory_os_runtime is None:
            return self._error(
                503,
                "memory_os_unavailable",
                "complete_document_ingestion requires daemon-owned Memory OS runtime.",
            )
        return self._ok(
            self.memory_os_runtime.complete_document_ingestion(
                document_id=str(request.get("document_id") or ""),
                artifact_id=_optional_text(request.get("artifact_id")),
                visual_request=request.get("visual_request"),
                visual_preview=request.get("visual_preview"),
                understanding_packet=request.get("understanding_packet"),
                document_promotion_transaction=request.get("document_promotion_transaction"),
                coverage_waivers=request.get("coverage_waivers"),
                accept=bool(request.get("accept", False)),
                approved_by=_optional_text(request.get("approved_by")),
                selected_operation_indexes=request.get("selected_operation_indexes"),
            )
        )

    async def _prepare_graph_readiness_report(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.memory_os_runtime is None:
            return self._error(
                503,
                "memory_os_unavailable",
                "prepare_graph_readiness_report requires daemon-owned Memory OS runtime.",
            )
        return self._ok(
            self.memory_os_runtime.prepare_graph_readiness_report(
                scope=str(request.get("scope") or "memory_os"),
                project=_optional_text(request.get("project")),
                exact_project_match=bool(request.get("exact_project_match", False)),
                domain=_optional_text(request.get("domain")),
                limit=_int_value(request.get("limit"), default=50),
            )
        )

    async def _prepare_graph_proposal_batch(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.memory_os_runtime is None:
            return self._error(
                503,
                "memory_os_unavailable",
                "prepare_graph_proposal_batch requires daemon-owned Memory OS runtime.",
            )
        return self._ok(
            self.memory_os_runtime.prepare_graph_proposal_batch(
                scope=str(request.get("scope") or "memory_os"),
                project=_optional_text(request.get("project")),
                domain=_optional_text(request.get("domain")),
                source_refs=request.get("source_refs"),
                limit=_int_value(request.get("limit"), default=10),
                budget_chars=_int_value(request.get("budget_chars"), default=12_000),
                candidate_graph_edges=request.get("candidate_graph_edges"),
            )
        )

    async def _apply_graph_proposal_batch(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.memory_os_runtime is None:
            return self._error(
                503,
                "memory_os_unavailable",
                "apply_graph_proposal_batch requires daemon-owned Memory OS runtime.",
            )
        return self._ok(
            self.memory_os_runtime.apply_graph_proposal_batch(
                scope=str(request.get("scope") or "memory_os"),
                project=_optional_text(request.get("project")),
                domain=_optional_text(request.get("domain")),
                source_refs=request.get("source_refs"),
                candidate_graph_edges=request.get("candidate_graph_edges"),
                accept=bool(request.get("accept", False)),
                approved_by=_optional_text(request.get("approved_by")),
                limit=_int_value(request.get("limit"), default=10),
                budget_chars=_int_value(request.get("budget_chars"), default=12_000),
            )
        )

    async def _repair_graph_edge_refs(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.memory_os_runtime is None:
            return self._error(
                503,
                "memory_os_unavailable",
                "repair_graph_edge_refs requires daemon-owned Memory OS runtime.",
            )
        return self._ok(
            self.memory_os_runtime.repair_graph_edge_refs(
                source=_optional_text(request.get("source")),
                limit=_int_value(request.get("limit"), default=1000),
                accept=bool(request.get("accept", False)),
                approved_by=_optional_text(request.get("approved_by")),
            )
        )

    async def _repair_graph_store_reconciliation(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.memory_os_runtime is None:
            return self._error(
                503,
                "memory_os_unavailable",
                "repair_graph_store_reconciliation requires daemon-owned Memory OS runtime.",
            )
        return self._ok(
            self.memory_os_runtime.repair_graph_store_reconciliation(
                repair_mode=str(request.get("repair_mode") or "upsert_missing"),
                limit=_int_value(request.get("limit"), default=5000),
                accept=bool(request.get("accept", False)),
                approved_by=_optional_text(request.get("approved_by")),
            )
        )

    async def _apply_document_promotion_transaction(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.memory_os_runtime is None:
            return self._error(
                503,
                "memory_os_unavailable",
                "apply_document_promotion_transaction requires daemon-owned Memory OS runtime.",
            )
        return self._ok(
            self.memory_os_runtime.apply_document_promotion_transaction(
                request.get("document_promotion_transaction") or {},
                accept=bool(request.get("accept", False)),
                approved_by=_optional_text(request.get("approved_by")),
                selected_operation_indexes=request.get("selected_operation_indexes"),
            )
        )

    async def _search_memories(self, request: dict[str, Any]) -> dict[str, Any]:
        query = str(request.get("query") or "").strip()
        if not query:
            return self._error(400, "invalid_request", "query is required")
        if self.memory_os_runtime is not None and self._memory_os_retrieval_ready():
            payload = self.memory_os_runtime.search_memories(
                query=query,
                limit=_int_value(request.get("limit"), default=5),
                project=_optional_text(request.get("project")),
                exact_project_match=bool(request.get("exact_project_match", False)),
                domain=_optional_text(request.get("domain")),
                tags=_string_list(request.get("tags")),
                include_stale=bool(request.get("include_stale", True)),
                canonical_only=bool(request.get("canonical_only", False)),
                pinned_keys=_string_list(request.get("pinned_keys")),
                pinned_first=bool(request.get("pinned_first", False)),
                retrieval_mode=str(request.get("retrieval_mode") or "semantic"),
            )
            return self._ok(self._annotate_search_backend(payload, backend_used="memory_os"))
        payload = await self.memory_manager.search_memories_structured_async(
            query,
            limit=_int_value(request.get("limit"), default=5),
            project=_optional_text(request.get("project")),
            domain=_optional_text(request.get("domain")),
            tags=request.get("tags"),
            include_stale=bool(request.get("include_stale", True)),
            canonical_only=bool(request.get("canonical_only", False)),
            pinned_keys=_string_list(request.get("pinned_keys")),
            pinned_first=bool(request.get("pinned_first", False)),
            retrieval_mode=str(request.get("retrieval_mode") or "semantic"),
        )
        payload["error"] = payload.get("error")
        return self._ok(self._annotate_search_backend(payload, backend_used="legacy_json_chroma"))

    def _annotate_search_backend(
        self,
        payload: dict[str, Any],
        *,
        backend_used: str,
    ) -> dict[str, Any]:
        annotated = dict(payload)
        serving = self._serving_status(
            backend_used=backend_used,
            refresh_retrieval_state=False,
        )
        annotated.setdefault("backend", backend_used)
        annotated["backend_used"] = backend_used
        annotated["primary_backend"] = serving["primary_backend"]
        annotated["fallback_used"] = serving["fallback_active"]
        annotated["fallback_reason"] = serving["fallback_reason"]
        annotated["memory_os_retrieval_ready"] = serving["memory_os_retrieval_ready"]
        annotated["memory_os_retrieval_status"] = serving["memory_os_retrieval_status"]
        annotated["memory_os_retrieval_state"] = serving["memory_os_retrieval_state"]
        warnings = annotated.get("warnings")
        if not isinstance(warnings, list):
            warnings = [warnings] if warnings else []
        annotated["warnings"] = [
            *warnings,
            *serving["warnings"],
        ]
        return annotated

    def _serving_status(
        self,
        *,
        backend_used: str | None = None,
        refresh_retrieval_state: bool = True,
        memory_os_status: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        memory_os_configured = self.memory_os_runtime is not None
        memory_os_retrieval_state = self._memory_os_retrieval_state(
            refresh=refresh_retrieval_state,
            memory_os_status=memory_os_status,
        )
        memory_os_retrieval_ready = self._memory_os_retrieval_ready()
        primary_backend = "memory_os" if memory_os_configured else "legacy_json_chroma"
        search_backend = backend_used or (
            "memory_os"
            if memory_os_configured and memory_os_retrieval_ready
            else "legacy_json_chroma"
        )
        fallback_active = bool(
            search_backend == "legacy_json_chroma"
            and memory_os_configured
            and not memory_os_retrieval_ready
        )
        fallback_reason = None
        warnings: list[dict[str, str]] = []
        if fallback_active:
            fallback_reason = _memory_os_fallback_reason(memory_os_retrieval_state)
            warnings.append(
                {
                    "code": fallback_reason,
                    "message": _memory_os_fallback_message(fallback_reason),
                }
            )
        elif search_backend == "legacy_json_chroma" and not memory_os_configured:
            warnings.append(
                {
                    "code": "memory_os_runtime_unavailable",
                    "message": (
                        "Memory OS runtime is unavailable; search is served by "
                        "legacy JSON/Chroma."
                    ),
                }
            )
        return {
            "search_backend": search_backend,
            "primary_backend": primary_backend,
            "memory_os_configured": memory_os_configured,
            "memory_os_retrieval_ready": memory_os_retrieval_ready,
            "memory_os_retrieval_status": (
                (memory_os_retrieval_state or {}).get("status")
                if memory_os_retrieval_state is not None
                else None
            ),
            "memory_os_retrieval_state": memory_os_retrieval_state,
            "fallback_active": fallback_active,
            "fallback_reason": fallback_reason,
            "warnings": warnings,
        }

    def _memory_os_retrieval_state(
        self,
        *,
        refresh: bool = True,
        memory_os_status: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        runtime = self.memory_os_runtime
        if runtime is None:
            return None
        state = None
        if memory_os_status is not None:
            state = (
                ((memory_os_status.get("components") or {}).get("retrieval") or {})
                .get("state")
            )
        if not refresh:
            state = getattr(runtime, "_retrieval_state", None)
        elif not isinstance(state, dict):
            state_getter = getattr(runtime, "retrieval_state", None)
            if callable(state_getter):
                try:
                    state = state_getter()
                except Exception as exc:
                    state = {"status": "error", "ready": False, "error": str(exc)}
        if refresh and not isinstance(state, dict):
            try:
                status_payload = runtime.status()
                state = (
                    ((status_payload.get("components") or {}).get("retrieval") or {})
                    .get("state")
                )
            except Exception:
                state = None
        if not isinstance(state, dict):
            ready = self._memory_os_retrieval_ready()
            state = {
                "status": "ready" if ready else "warming",
                "ready": ready,
                "error": None,
            }
        else:
            state = dict(state)
            state.setdefault("ready", self._memory_os_retrieval_ready())
            state.setdefault("status", "ready" if state.get("ready") else "warming")
        return state

    async def _retrieve_chunk(self, request: dict[str, Any]) -> dict[str, Any]:
        key = str(request.get("key") or "").strip()
        if not key:
            return self._error(400, "invalid_request", "key is required")
        chunk_id = _int_value(request.get("chunk_id"), default=0)
        if self.memory_os_runtime is not None:
            return self._ok(self.memory_os_runtime.retrieve_chunk(key, chunk_id))
        raw_results = await self.memory_manager.retrieve_chunks_async(
            [{"key": key, "chunk_id": chunk_id}]
        )
        result = raw_results[0] if raw_results else None
        return self._ok(_chunk_payload(result, key, chunk_id))

    async def _retrieve_chunks(self, request: dict[str, Any]) -> dict[str, Any]:
        requests = request.get("requests")
        if not isinstance(requests, list):
            return self._error(400, "invalid_request", "requests must be a list")
        if self.memory_os_runtime is not None:
            results = [
                self.memory_os_runtime.retrieve_chunk(
                    str(item.get("key") or ""),
                    _int_value(item.get("chunk_id"), default=0),
                )
                for item in requests
                if isinstance(item, dict)
            ]
            return self._ok(
                {
                    "requested_count": len(requests),
                    "found_count": sum(1 for result in results if result["found"]),
                    "results": results,
                    "error": None,
                }
            )
        raw_results = await self.memory_manager.retrieve_chunks_async(requests)
        results = [
            _chunk_payload(result, result.get("key", ""), result.get("chunk_id", -1))
            for result in raw_results
        ]
        return self._ok(
            {
                "requested_count": len(requests),
                "found_count": sum(1 for result in results if result["found"]),
                "results": results,
                "error": None,
            }
        )

    async def _retrieve_memory(self, request: dict[str, Any]) -> dict[str, Any]:
        key = str(request.get("key") or "").strip()
        if not key:
            return self._error(400, "invalid_request", "key is required")
        if self.memory_os_runtime is not None:
            return self._ok(self.memory_os_runtime.retrieve_memory(key))
        result = await self.memory_manager.retrieve_memory_async(key)
        return self._ok(
            {
                "key": key,
                "found": result is not None,
                "memory": result,
                "error": None,
            }
        )

    async def _store_memory(self, request: dict[str, Any]) -> dict[str, Any]:
        key = str(request.get("key") or "").strip()
        content = request.get("content")
        if not key:
            return self._error(400, "invalid_request", "key is required")
        if not isinstance(content, str) or not content.strip():
            return self._error(400, "invalid_request", "content is required")
        if len(content) > MAX_DIRECT_MEMORY_CHARS:
            return self._error(
                400,
                "invalid_request",
                direct_memory_too_long_message(len(content)),
            )
        if self.memory_os_runtime is not None:
            if not self._memory_os_retrieval_ready():
                return self._memory_os_warming_error("store_memory")
            try:
                result = self.memory_os_runtime.store_memory(
                    key=key,
                    content=content,
                    tags=_string_list(request.get("tags")),
                    title=_optional_text(request.get("title")) or key,
                    related_to=_string_list(request.get("related_to")),
                    force=bool(request.get("force", False)),
                    project=_optional_text(request.get("project")),
                    domain=_optional_text(request.get("domain")),
                    status=_optional_text(request.get("status")),
                    canonical=request.get("canonical"),
                    memory_type=_optional_text(request.get("memory_type")),
                    scope=_optional_text(request.get("scope")),
                    trust_state=_optional_text(request.get("trust_state")),
                    retention_policy=_optional_text(request.get("retention_policy")),
                    sync_policy=_optional_text(request.get("sync_policy")),
                    document_id=_optional_text(request.get("document_id")),
                    source_id=_optional_text(request.get("source_id")),
                    source_document=request.get("source_document") if isinstance(request.get("source_document"), dict) else None,
                )
            except ValueError as exc:
                return self._error(400, "invalid_request", str(exc))
            if result.get("status") in {"policy_denied", "review_required"}:
                return {
                    "status": 403,
                    "body": {
                        "stored": False,
                        "result": result,
                        "error": result.get("error")
                        or {
                            "code": "memory_guardrail_failed",
                            "message": "store_memory was rejected by Memory OS guardrails.",
                        },
                    },
                }
            if result.get("write_degraded") is True or result.get("repair_required") is True:
                return {
                    "status": 503,
                    "body": {
                        "stored": False,
                        "result": result,
                        "error": result.get("error")
                        or {
                            "code": "memory_write_degraded",
                            "message": "store_memory completed with repair-required state.",
                        },
                    },
                }
            self._start_memory_os_maintenance_worker(self.memory_os_runtime)
            return self._ok({"stored": True, "result": result, "error": None})
        try:
            result = await self.memory_manager.store_memory_async(
                key=key,
                content=content,
                tags=_string_list(request.get("tags")),
                title=_optional_text(request.get("title")),
                related_to=_string_list(request.get("related_to")),
                force=bool(request.get("force", False)),
                project=_optional_text(request.get("project")),
                domain=_optional_text(request.get("domain")),
                status=_optional_text(request.get("status")),
                canonical=request.get("canonical"),
            )
        except DuplicateMemoryError as exc:
            return self._ok(
                {
                    "stored": False,
                    "duplicate": exc.duplicate,
                    "error": {
                        "code": "duplicate",
                        "message": "Similar memory already exists.",
                    },
                }
            )
        except ValueError as exc:
            return self._error(400, "invalid_request", str(exc))
        return self._ok({"stored": True, "result": result, "error": None})

    async def _prepare_source_memory(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            draft = self.source_intake_manager.prepare_source_memory(
                source_text=request.get("source_text"),
                source_type=request.get("source_type"),
                source_uri=request.get("source_uri"),
                project=request.get("project"),
                domain=request.get("domain"),
                budget_chars=request.get("budget_chars", 6000),
                pipeline=request.get("pipeline", "generic"),
            )
        except ValueError as exc:
            return self._ok(
                {
                    "draft": None,
                    "error": {
                        "code": "invalid_request",
                        "message": str(exc),
                    },
                }
            )
        except RuntimeError as exc:
            return self._ok(
                {
                    "draft": None,
                    "error": {
                        "code": "runtime_error",
                        "message": str(exc),
                    },
                }
            )
        return self._ok({"draft": draft, "error": None})

    async def _document_tool(
        self,
        tool_name: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        return self._ok(self.document_tools.run_stage(tool_name, request))

    async def _prepare_document_disassembly(self, request: dict[str, Any]) -> dict[str, Any]:
        payload = self.document_tools.run_stage(
            "prepare_document_disassembly",
            {
                "source_path": request.get("source_path"),
                "source_type": request.get("source_type", "pdf"),
                "max_pages": request.get("max_pages"),
                "page_range": request.get("page_range"),
                "resume_token": request.get("resume_token"),
            },
        )
        disassembly = payload.get("disassembly")
        if self.memory_os_runtime is not None and isinstance(disassembly, dict):
            payload["job"] = self.memory_os_runtime.record_document_disassembly_job(
                disassembly,
                request=request,
            )
        return self._ok(payload)

    def _memory_os_source_import_job(self, request: dict[str, Any]) -> dict[str, Any]:
        source_ref = request.get("source_ref")
        if not isinstance(source_ref, dict):
            return self._error(400, "invalid_request", "source_ref must be an object")
        source_type = _optional_text(request.get("source_type"))
        if not source_type:
            return self._error(400, "invalid_request", "source_type is required")
        connector_id = _optional_text(request.get("connector_id")) or "manual"
        return self._ok(
            self._runtime().prepare_source_import_job(
                source_ref=source_ref,
                source_type=source_type,
                connector_id=connector_id,
            )
        )

    def _prepare_legacy_memory_os_migration(self, request: dict[str, Any]) -> dict[str, Any]:
        legacy_dir = _optional_text(request.get("legacy_dir")) or "data/memories"
        return self._ok(
            self._runtime().prepare_legacy_memory_os_migration(
                legacy_dir=legacy_dir,
                include_details=bool(request.get("include_details", False)),
            )
        )

    def _apply_legacy_memory_os_migration(self, request: dict[str, Any]) -> dict[str, Any]:
        legacy_dir = _optional_text(request.get("legacy_dir")) or "data/memories"
        return self._ok(
            self._runtime().apply_legacy_memory_os_migration(
                legacy_dir=legacy_dir,
                accept=bool(request.get("accept", False)),
                approved_by=_optional_text(request.get("approved_by")),
                include_details=bool(request.get("include_details", False)),
            )
        )

    def _prepare_legacy_related_to_graph_migration(self, request: dict[str, Any]) -> dict[str, Any]:
        legacy_dir = _optional_text(request.get("legacy_dir")) or "data/memories"
        return self._ok(
            self._runtime().prepare_legacy_related_to_graph_migration(
                legacy_dir=legacy_dir,
                include_details=bool(request.get("include_details", False)),
            )
        )

    def _apply_legacy_related_to_graph_migration(self, request: dict[str, Any]) -> dict[str, Any]:
        legacy_dir = _optional_text(request.get("legacy_dir")) or "data/memories"
        return self._ok(
            self._runtime().apply_legacy_related_to_graph_migration(
                legacy_dir=legacy_dir,
                accept=bool(request.get("accept", False)),
                approved_by=_optional_text(request.get("approved_by")),
                include_details=bool(request.get("include_details", False)),
            )
        )

    async def _list_source_drafts(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            payload = self.source_intake_manager.list_source_drafts(
                project=request.get("project"),
                status=request.get("status"),
                limit=request.get("limit", 50),
                offset=request.get("offset", 0),
            )
        except RuntimeError as exc:
            payload = {
                "count": 0,
                "drafts": [],
                "error": {
                    "code": "runtime_error",
                    "message": str(exc),
                },
            }
        return self._ok(payload)

    async def _discard_source_draft(self, request: dict[str, Any]) -> dict[str, Any]:
        draft_id = str(request.get("draft_id") or "").strip()
        if not draft_id:
            return self._ok(
                {
                    "discarded": False,
                    "draft_id": draft_id,
                    "error": {
                        "code": "invalid_request",
                        "message": "draft_id is required",
                    },
                }
            )
        try:
            payload = self.source_intake_manager.discard_source_draft(draft_id)
        except RuntimeError as exc:
            payload = {
                "discarded": False,
                "draft_id": draft_id,
                "error": {
                    "code": "runtime_error",
                    "message": str(exc),
                },
            }
        return self._ok(payload)

    async def _store_prepared_memory(self, request: dict[str, Any]) -> dict[str, Any]:
        draft_id = str(request.get("draft_id") or "").strip()
        if not draft_id:
            return self._ok(
                {
                    "stored_count": 0,
                    "stored": [],
                    "skipped": [],
                    "error": {
                        "code": "invalid_request",
                        "message": "draft_id is required",
                    },
                }
            )
        draft = self.source_intake_manager.get_source_draft(draft_id)
        if draft is None:
            return self._ok(
                {
                    "stored_count": 0,
                    "stored": [],
                    "skipped": [],
                    "error": {
                        "code": "not_found",
                        "message": f"source draft not found: {draft_id}",
                    },
                }
            )
        if draft.get("status") == "rejected":
            return self._ok(
                {
                    "stored_count": 0,
                    "stored": [],
                    "skipped": [],
                    "error": {
                        "code": "invalid_state",
                        "message": "source draft is rejected and cannot be promoted",
                    },
                }
            )

        proposed_memories = draft.get("proposed_memories", [])
        requested_indices = request.get("selected_items")
        indices = (
            requested_indices
            if isinstance(requested_indices, list)
            else list(range(len(proposed_memories)))
        )
        force = bool(request.get("force", False))
        stored: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        valid_items: list[tuple[int, dict[str, Any]]] = []

        for index in indices:
            if not isinstance(index, int) or index < 0 or index >= len(proposed_memories):
                skipped.append({"index": index, "reason": "invalid_index"})
                continue
            memory = proposed_memories[index]
            valid_items.append((index, memory))
            guardrail_payload = _source_draft_guardrail_memory(memory)
            guardrail_payload["status"] = _promoted_source_memory_status(memory.get("status"))
            guardrail_treatment = _source_draft_guardrail_treatment(
                memory_os_runtime=self.memory_os_runtime,
                memory=guardrail_payload,
                draft_id=draft_id,
                operation_index=index,
                approved_by="source_draft_promotion",
            )
            guardrail = guardrail_treatment["guardrail"]
            if guardrail.get("decision") == "block":
                return self._ok(
                    {
                        "stored_count": 0,
                        "stored": [],
                        "skipped": [
                            *skipped,
                            {
                                "index": index,
                                "key": memory.get("key"),
                                "reason": "policy_denied",
                                "guardrail": guardrail,
                                "receipt": guardrail_treatment.get("receipt"),
                                "firewall_event": guardrail_treatment.get("firewall_event"),
                            },
                        ],
                        "error": {
                            "code": "memory_guardrail_blocked",
                            "category": "memory_guardrail",
                            "message": "Memory guardrails blocked a selected source draft memory write.",
                            "issue_codes": list(guardrail.get("issue_codes") or []),
                        },
                    }
                )
            if guardrail.get("decision") == "require_review" and self.memory_os_runtime is None:
                return self._ok(
                    {
                        "stored_count": 0,
                        "stored": [],
                        "skipped": [
                            *skipped,
                            {
                                "index": index,
                                "key": memory.get("key"),
                                "reason": "review_required",
                                "guardrail": guardrail,
                                "receipt": guardrail_treatment.get("receipt"),
                                "firewall_event": guardrail_treatment.get("firewall_event"),
                            },
                        ],
                        "error": {
                            "code": "memory_guardrail_review_required",
                            "category": "memory_guardrail",
                            "message": (
                                "Memory guardrails require daemon-owned reviewed promotion "
                                "for this source draft memory write."
                            ),
                            "issue_codes": list(guardrail.get("issue_codes") or []),
                        },
                    }
                )

        for index, memory in valid_items:
            try:
                store_kwargs = {
                    "key": memory["key"],
                    "content": memory["content"],
                    "tags": memory.get("tags", []),
                    "title": memory.get("title"),
                    "related_to": memory.get("related_to"),
                    "force": force,
                    "project": memory.get("project"),
                    "domain": memory.get("domain"),
                    "status": _promoted_source_memory_status(memory.get("status")),
                    "canonical": memory.get("canonical"),
                    "memory_type": memory.get("memory_type"),
                    "scope": memory.get("scope"),
                    "trust_state": memory.get("trust_state"),
                    "retention_policy": memory.get("retention_policy"),
                    "sync_policy": memory.get("sync_policy"),
                    "document_id": memory.get("document_id"),
                    "source_id": memory.get("source_id"),
                    "source_document": memory.get("source_document"),
                    "citations": memory.get("citations"),
                    "approved_by": "source_draft_promotion",
                    "guardrail_context": {
                        "operation_kind": "store_prepared_memory",
                        "draft_id": draft_id,
                        "operation_index": index,
                    },
                }
                if self.memory_os_runtime is not None:
                    if not self._memory_os_retrieval_ready():
                        return self._memory_os_warming_error("store_prepared_memory")
                    result = self.memory_os_runtime.store_memory(**store_kwargs)
                    if result.get("write_degraded") is not True and result.get("repair_required") is not True:
                        self._start_memory_os_maintenance_worker(self.memory_os_runtime)
                else:
                    legacy_store_kwargs = dict(store_kwargs)
                    legacy_store_kwargs.pop("memory_type", None)
                    legacy_store_kwargs.pop("scope", None)
                    legacy_store_kwargs.pop("trust_state", None)
                    legacy_store_kwargs.pop("retention_policy", None)
                    legacy_store_kwargs.pop("sync_policy", None)
                    legacy_store_kwargs.pop("document_id", None)
                    legacy_store_kwargs.pop("source_id", None)
                    legacy_store_kwargs.pop("source_document", None)
                    legacy_store_kwargs.pop("citations", None)
                    legacy_store_kwargs.pop("approved_by", None)
                    legacy_store_kwargs.pop("guardrail_context", None)
                    result = await self.memory_manager.store_memory_async(**legacy_store_kwargs)
                if isinstance(result, dict) and result.get("status") in {"policy_denied", "review_required"}:
                    rollback = _rollback_source_draft_runtime_stores(
                        self.memory_os_runtime,
                        [str(item.get("key") or "") for item in stored],
                    )
                    return self._ok(
                        {
                            "stored_count": 0,
                            "stored": [],
                            "skipped": [
                                *skipped,
                                {
                                    "index": index,
                                    "key": memory.get("key"),
                                    "reason": result.get("status"),
                                    "message": (result.get("error") or {}).get("message")
                                    if isinstance(result.get("error"), dict)
                                    else "memory guardrail rejected the write",
                                    "result": result,
                                },
                            ],
                            "rollback": rollback,
                            "error": result.get("error")
                            or {
                                "code": "memory_guardrail_failed",
                                "category": "memory_guardrail",
                                "message": "Memory guardrails rejected a source draft memory write.",
                            },
                        }
                    )
            except DuplicateMemoryError as exc:
                skipped.append(
                    {
                        "index": index,
                        "key": memory.get("key"),
                        "reason": "duplicate",
                        "message": str(exc),
                    }
                )
                continue
            stored.append({"index": index, "key": memory["key"], "result": result})

        return self._ok(
            {
                "stored_count": len(stored),
                "stored": stored,
                "skipped": skipped,
                "error": None,
            }
        )

    async def _check_duplicate(self, request: dict[str, Any]) -> dict[str, Any]:
        key = str(request.get("key") or "").strip()
        content = request.get("content")
        if not key:
            return self._ok(
                {
                    "key": key,
                    "duplicate": False,
                    "match": None,
                    "error": {
                        "code": "invalid_request",
                        "message": "key is required",
                    },
                }
            )
        if not isinstance(content, str) or not content.strip():
            return self._ok(
                {
                    "key": key,
                    "duplicate": False,
                    "match": None,
                    "error": {
                        "code": "invalid_request",
                        "message": "content is required",
                    },
                }
            )
        if self.memory_os_runtime is not None:
            return self._ok(self.memory_os_runtime.check_duplicate(key, content))
        result = await self.memory_manager.check_duplicate_async(key, content)
        return self._ok(
            {
                "key": result.get("key", key),
                "duplicate": bool(result.get("duplicate", False)),
                "match": result.get("match"),
                "error": None,
            }
        )

    async def _update_memory_metadata(self, request: dict[str, Any]) -> dict[str, Any]:
        key = str(request.get("key") or "").strip()
        if not key:
            return self._error(400, "invalid_request", "key is required")
        changes = {
            name: value
            for name, value in {
                "title": request.get("title") if "title" in request else None,
                "tags": _string_list(request.get("tags")) if "tags" in request else None,
                "related_to": _string_list(request.get("related_to")) if "related_to" in request else None,
                "project": request.get("project") if "project" in request else None,
                "domain": request.get("domain") if "domain" in request else None,
                "status": request.get("status") if "status" in request else None,
                "canonical": request.get("canonical") if "canonical" in request else None,
            }.items()
            if value is not None
        }
        if self.memory_os_runtime is not None:
            if not self._memory_os_retrieval_ready():
                return self._memory_os_warming_error("update_memory_metadata")
            try:
                result = self.memory_os_runtime.update_memory_metadata(key, **changes)
            except ValueError as exc:
                return self._error(400, "invalid_request", str(exc))
            if result.get("updated") is True:
                self._start_memory_os_maintenance_worker(self.memory_os_runtime)
            return self._ok(result)
        try:
            memory = await self.memory_manager.update_memory_metadata_async(key, **changes)
        except KeyError:
            return self._ok(
                {
                    "key": key,
                    "updated": False,
                    "memory": None,
                    "error": {
                        "code": "not_found",
                        "message": f"❌ Memory not found: '{key}'",
                    },
                }
            )
        except ValueError as exc:
            return self._ok(
                {
                    "key": key,
                    "updated": False,
                    "memory": None,
                    "error": {
                        "code": "invalid_metadata",
                        "message": str(exc),
                    },
                }
            )
        return self._ok({"key": key, "updated": True, "memory": memory, "error": None})

    async def _repair_memory_metadata(self, request: dict[str, Any]) -> dict[str, Any]:
        keys = _string_list(request.get("keys"))
        dry_run = bool(request.get("dry_run", True))
        if not keys:
            return self._ok(
                {
                    "requested_count": 0,
                    "repaired_count": 0,
                    "dry_run": dry_run,
                    "repairs": [],
                    "error": {
                        "code": "invalid_keys",
                        "message": "keys must include at least one memory key.",
                    },
                }
            )
        if self.memory_os_runtime is not None:
            return self._ok(self.memory_os_runtime.repair_memory_metadata(keys, dry_run=dry_run))
        payload = await self.memory_manager.repair_memory_metadata_async(keys, dry_run=dry_run)
        payload["error"] = None
        return self._ok(payload)

    async def _delete_memory(self, request: dict[str, Any]) -> dict[str, Any]:
        key = str(request.get("key") or "").strip()
        if not key:
            return self._error(400, "invalid_request", "key is required")
        if self.memory_os_runtime is not None:
            if not self._memory_os_retrieval_ready():
                return self._memory_os_warming_error("delete_memory")
            result = self.memory_os_runtime.delete_memory(key)
            if result.get("deleted") is True:
                self._start_memory_os_maintenance_worker(self.memory_os_runtime)
            return self._ok(result)
        deleted = await self.memory_manager.delete_memory_async(key)
        return self._ok({"key": key, "deleted": bool(deleted), "error": None})

    @staticmethod
    def _ok(body: dict[str, Any]) -> dict[str, Any]:
        return {"status": 200, "body": body}

    @staticmethod
    def _error(status: int, code: str, message: str) -> dict[str, Any]:
        return {
            "status": status,
            "body": {
                "error": {
                    "code": code,
                    "message": message,
                }
            },
        }

    def _memory_os_retrieval_ready(self) -> bool:
        runtime = self.memory_os_runtime
        if runtime is None:
            return False
        return bool(getattr(runtime, "retrieval_ready", True))

    def _memory_os_warming_error(self, operation: str) -> dict[str, Any]:
        return self._error(
            503,
            "memory_os_warming",
            f"{operation} is temporarily unavailable while Memory OS retrieval warms.",
        )

    def _record_daemon_usage(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
        response: dict[str, Any],
        started_at: float,
    ) -> None:
        if self.usage_meter is None:
            return
        tool_name = _daemon_usage_tool_name(method, path)
        if tool_name is None:
            return
        body = response.get("body") if isinstance(response, dict) else None
        if not isinstance(body, dict):
            body = {}
        status_code = _int_value(
            response.get("status") if isinstance(response, dict) else None,
            default=500,
        )
        error = _daemon_payload_error_message(body)
        outcome = _daemon_request_outcome(status_code, error)
        try:
            self.usage_meter.record_tool_call(
                tool=tool_name,
                input_payload=_sanitize_usage_payload(payload if isinstance(payload, dict) else {}),
                output_payload=body,
                status="ok" if outcome == "ok" else "error",
                duration_ms=int((time.perf_counter() - started_at) * 1000),
                error=error,
                telemetry=self._daemon_usage_telemetry(
                    tool_name=tool_name,
                    method=method,
                    route=urlparse(path).path.rstrip("/") or "/",
                    body=body,
                    status_code=status_code,
                    request_outcome=outcome,
                ),
            )
        except Exception:
            return

    def _daemon_usage_telemetry(
        self,
        *,
        tool_name: str,
        method: str,
        route: str,
        body: dict[str, Any],
        status_code: int,
        request_outcome: str,
    ) -> dict[str, Any]:
        serving = self._serving_status(refresh_retrieval_state=False)
        result = body.get("result") if isinstance(body.get("result"), dict) else {}
        return {
            "entrypoint": "engramd",
            "method": method.upper(),
            "route": route,
            "http_status": status_code,
            "request_outcome": request_outcome,
            "backend_used": body.get("backend_used")
            or body.get("backend")
            or result.get("storage_backend"),
            "primary_backend": body.get("primary_backend") or serving["primary_backend"],
            "fallback_used": (
                body.get("fallback_used")
                if body.get("fallback_used") is not None
                else serving["fallback_active"]
            ),
            "fallback_reason": body.get("fallback_reason") or serving["fallback_reason"],
            "chunks_scanned": _daemon_chunks_scanned(body),
            "chunks_returned": _daemon_chunks_returned(tool_name, body),
            "write_class": _daemon_write_class(tool_name),
        }

    def _start_document_ingestion_worker(self, runtime: MemoryOSRuntime) -> None:
        self._background_threads = [thread for thread in self._background_threads if thread.is_alive()]
        worker_id = f"engramd-document-ingestion-{len(self._background_threads) + 1}"
        thread = threading.Thread(
            target=self._run_document_ingestion_worker,
            args=(runtime, worker_id),
            name=worker_id,
            daemon=True,
        )
        self._background_threads.append(thread)
        thread.start()

    @staticmethod
    def _run_document_ingestion_worker(runtime: MemoryOSRuntime, worker_id: str) -> None:
        while True:
            try:
                result = runtime.run_queued_document_ingestion(worker_id=worker_id)
            except Exception:
                # Worker failures are recorded by the runtime when possible; never let
                # a background exception tear down the daemon request handler.
                return
            if result.get("status") == "idle":
                return

    def _start_memory_os_maintenance_worker(self, runtime: MemoryOSRuntime) -> None:
        self._background_threads = [thread for thread in self._background_threads if thread.is_alive()]
        worker_id = f"engramd-memory-maintenance-{len(self._background_threads) + 1}"
        thread = threading.Thread(
            target=self._run_memory_os_maintenance_worker,
            args=(runtime, worker_id),
            name=worker_id,
            daemon=True,
        )
        self._background_threads.append(thread)
        thread.start()

    @staticmethod
    def _run_memory_os_maintenance_worker(runtime: MemoryOSRuntime, worker_id: str) -> None:
        while True:
            try:
                result = runtime.run_queued_maintenance_job(worker_id=worker_id)
            except Exception:
                return
            if result.get("status") == "idle":
                return

    def _validate_allowed_fields(
        self,
        request: dict[str, Any],
        allowed_fields: frozenset[str],
    ) -> dict[str, Any] | None:
        unexpected_fields = sorted(set(request) - allowed_fields)
        if not unexpected_fields:
            return None
        return self._error(
            400,
            "invalid_request",
            f"unexpected field(s): {', '.join(unexpected_fields)}",
        )

    def _runtime(self) -> MemoryOSRuntime:
        if self.memory_os_runtime is None:
            self.memory_os_runtime = MemoryOSRuntime(_memory_os_root())
            self.memory_os_runtime.initialize()
        return self.memory_os_runtime


def _memory_os_root() -> Path:
    return memory_os_root_for_data_root(resolve_data_root())


def _memory_os_fallback_reason(state: dict[str, Any] | None) -> str:
    status = str((state or {}).get("status") or "").strip().lower()
    if (state or {}).get("error") or status == "error":
        return "memory_os_retrieval_error"
    if status in {"needs_rebuild", "stale_manifest", "repair_pending"}:
        return "memory_os_retrieval_needs_rebuild"
    if status in {"not_initialized", "rebuilding", "warming"}:
        return "memory_os_retrieval_warming"
    return "memory_os_retrieval_not_ready"


def _memory_os_fallback_message(reason: str) -> str:
    if reason == "memory_os_retrieval_error":
        return (
            "Memory OS retrieval reported an error; search was served by legacy "
            "JSON/Chroma fallback."
        )
    if reason == "memory_os_retrieval_needs_rebuild":
        return (
            "Memory OS retrieval needs rebuild or manifest repair; search was "
            "served by legacy JSON/Chroma fallback."
        )
    if reason == "memory_os_retrieval_warming":
        return (
            "Memory OS retrieval is not ready; search was served by legacy "
            "JSON/Chroma fallback."
        )
    return (
        "Memory OS retrieval is unavailable; search was served by legacy "
        "JSON/Chroma fallback."
    )


def _promoted_source_memory_status(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text or text in {"draft", "candidate", "prepared"}:
        return "reviewed"
    return text


def _source_draft_guardrail_memory(memory: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": memory.get("key"),
        "content": memory.get("content"),
        "memory_type": memory.get("memory_type"),
        "citations": memory.get("citations"),
        "project": memory.get("project"),
        "domain": memory.get("domain"),
        "scope": memory.get("scope"),
        "trust_state": memory.get("trust_state"),
        "status": memory.get("status"),
    }


def _source_draft_guardrail_context(draft_id: str, operation_index: int) -> dict[str, Any]:
    return {
        "operation_kind": "store_prepared_memory",
        "draft_id": draft_id,
        "operation_index": operation_index,
    }


def _source_draft_guardrail_treatment(
    *,
    memory_os_runtime: MemoryOSRuntime | None,
    memory: dict[str, Any],
    draft_id: str,
    operation_index: int,
    approved_by: str,
) -> dict[str, Any]:
    context = _source_draft_guardrail_context(draft_id, operation_index)
    enforce = getattr(memory_os_runtime, "_enforce_memory_guardrails", None)
    if callable(enforce):
        return enforce(memory=memory, approved_by=approved_by, context=context)
    guardrail = evaluate_memory_write(memory)
    if guardrail.get("decision") == "allow":
        return {
            "allowed": True,
            "guardrail": guardrail,
            "receipt": None,
            "firewall_event": None,
        }
    return {
        "allowed": False,
        "guardrail": guardrail,
        "receipt": None,
        "firewall_event": None,
    }


def _rollback_source_draft_runtime_stores(
    memory_os_runtime: MemoryOSRuntime | None,
    memory_keys: list[str],
) -> dict[str, Any]:
    if memory_os_runtime is None:
        return {"attempted": False, "deleted": [], "errors": []}
    delete = getattr(memory_os_runtime, "delete_memory", None)
    if not callable(delete):
        return {
            "attempted": bool(memory_keys),
            "deleted": [],
            "errors": [
                {
                    "code": "delete_memory_unavailable",
                    "message": "runtime does not expose delete_memory for rollback",
                }
            ]
            if memory_keys
            else [],
        }
    deleted: list[str] = []
    errors: list[dict[str, Any]] = []
    for key in memory_keys:
        if not key:
            continue
        try:
            result = delete(key)
        except Exception as exc:  # pragma: no cover - defensive rollback report
            errors.append({"key": key, "exception": type(exc).__name__, "message": str(exc)})
            continue
        if isinstance(result, dict) and result.get("deleted") is True:
            deleted.append(key)
        elif isinstance(result, dict) and result.get("error"):
            errors.append({"key": key, "error": result.get("error")})
    return {"attempted": bool(memory_keys), "deleted": deleted, "errors": errors}


def _bounded_query_int(
    query: dict[str, list[str]],
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw_value = (query.get(name) or [default])[0]
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


def _chunk_payload(result: dict[str, Any] | None, key: str, chunk_id: int) -> dict[str, Any]:
    if not result:
        return {
            "key": key,
            "chunk_id": chunk_id,
            "found": False,
            "chunk": None,
            "error": None,
        }
    found = bool(result.get("found", True))
    chunk = None
    if found:
        chunk = {
            "title": result.get("title", key),
            "text": result.get("text"),
            "section_title": result.get("section_title"),
            "heading_path": result.get("heading_path", []),
            "chunk_kind": result.get("chunk_kind"),
        }
    return {
        "key": result.get("key", key),
        "chunk_id": result.get("chunk_id", chunk_id),
        "found": found,
        "chunk": chunk,
        "error": result.get("error"),
    }


def _daemon_usage_tool_name(method: str, path: str) -> str | None:
    route_path = urlparse(path).path.rstrip("/") or "/"
    tool_name = _DAEMON_TOOL_BY_PATH.get(route_path)
    if tool_name is None:
        return None
    route = DAEMON_ROUTES.get(tool_name)
    if route is None or route.method.upper() != method.upper():
        return None
    return tool_name


def _daemon_payload_error_message(payload: dict[str, Any]) -> str | None:
    error = payload.get("error")
    if not error:
        return None
    if isinstance(error, dict):
        code = str(error.get("code") or "").strip()
        message = str(error.get("message") or code or error).strip()
        if code and message and message != code:
            return f"{code}: {message}"
        return message or code or str(error)
    return str(error)


def _sanitize_usage_payload(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if "private" in str(key).lower():
                sanitized[key] = "[redacted]"
            else:
                sanitized[key] = _sanitize_usage_payload(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_usage_payload(item) for item in value]
    return value


def _daemon_request_outcome(status_code: int, error: str | None) -> str:
    if status_code >= 400:
        return "http_error"
    if error:
        return "tool_error"
    return "ok"


def _daemon_chunks_scanned(payload: dict[str, Any]) -> int | None:
    receipt = payload.get("receipt") if isinstance(payload.get("receipt"), dict) else {}
    counts = [
        _int_or_none(container.get(key))
        for container in (payload, receipt)
        for key in (
            "chunks_scanned",
            "candidate_count",
            "candidate_chunk_count",
            "retrieval_candidate_count",
            "semantic_candidate_count",
            "lexical_candidate_count",
        )
    ]
    present = [count for count in counts if count is not None]
    return max(present) if present else None


def _daemon_chunks_returned(tool_name: str, payload: dict[str, Any]) -> int | None:
    if tool_name == "search_memories":
        results = payload.get("results")
        if isinstance(results, list):
            return len(results)
        return _int_or_none(payload.get("count"))
    if tool_name == "retrieve_chunk":
        return 1 if payload.get("found") else 0
    if tool_name == "retrieve_chunks":
        found_count = _int_or_none(payload.get("found_count"))
        if found_count is not None:
            return found_count
        results = payload.get("results")
        if isinstance(results, list):
            return sum(
                1
                for result in results
                if isinstance(result, dict) and result.get("found")
            )
    return None


def _daemon_write_class(tool_name: str) -> str:
    metadata = CANONICAL_TOOLS.get(tool_name)
    if metadata is None:
        return "unknown"
    return metadata.write_behavior


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _required_text(request: dict[str, Any], key: str) -> str:
    return str(request.get(key) or "").strip()


def _decode_b64_field(request: dict[str, Any], key: str) -> bytes | None:
    text = str(request.get(key) or "").strip()
    if not text:
        return None
    try:
        padding = "=" * (-len(text) % 4)
        return base64.urlsafe_b64decode((text + padding).encode("ascii"))
    except Exception:
        return None


def _sync_error_status(code: str) -> int:
    if code in {"sync_peer_signature_required", "sync_signature_invalid", "sync_timestamp_out_of_range"}:
        return 401
    if code in {"sync_peer_not_registered", "sync_target_mismatch"}:
        return 403
    if code == "sync_nonce_replay":
        return 409
    return 400


def _sync_error_message(code: str) -> str:
    messages = {
        "sync_peer_signature_required": "Signed sync peer request metadata is required.",
        "sync_peer_not_registered": "The sync peer is not registered or active.",
        "sync_target_mismatch": "The sync request targets a different local device identity.",
        "sync_timestamp_out_of_range": "The sync request timestamp is outside the allowed clock skew.",
        "sync_signature_invalid": "The sync peer request signature is invalid.",
        "sync_nonce_replay": "The sync peer request nonce has already been used.",
    }
    return messages.get(code, code)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    raw_items = value.split(",") if isinstance(value, str) else list(value)
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _int_value(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
