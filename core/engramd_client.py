"""Client helpers for talking to a local Engram daemon."""
from __future__ import annotations

import json
import os
import ipaddress
from typing import Any
from urllib import error, request
from urllib.parse import urlparse, urlunparse

from core.mcp.tool_registry import daemon_route


DEFAULT_DAEMON_TIMEOUT = 120.0
MAX_DAEMON_RESPONSE_BYTES = 5 * 1024 * 1024
DAEMON_REMOTE_URL_ACK_ENV = "ENGRAM_DAEMON_REMOTE_URL_ACK"


class EngramDaemonClientError(RuntimeError):
    """Raised when an Engram daemon request fails before returning JSON."""


class UrllibJSONTransport:
    """Standard-library JSON transport for daemon calls."""

    def request_json(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
        timeout: float = DEFAULT_DAEMON_TIMEOUT,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        _require_http_url(url)
        data = None
        request_headers = {"Accept": "application/json"}
        request_headers.update(headers or {})
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        req = request.Request(url, data=data, headers=request_headers, method=method)
        try:
            with request.urlopen(req, timeout=timeout) as response:  # nosec B310
                raw = _read_limited(response).decode("utf-8")
        except error.HTTPError as exc:
            raw_error = _read_limited(exc).decode("utf-8", errors="replace")
            try:
                return json.loads(raw_error)
            except json.JSONDecodeError as decode_exc:
                raise EngramDaemonClientError(
                    f"Daemon HTTP {exc.code} returned non-JSON error"
                ) from decode_exc
        except error.URLError as exc:
            raise EngramDaemonClientError(f"Daemon request failed: {exc}") from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EngramDaemonClientError("Daemon returned non-JSON response") from exc


def _require_http_url(url: str) -> None:
    parsed = urlparse(str(url or ""))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise EngramDaemonClientError("Daemon URL must use http or https")
    if parsed.username or parsed.password or "@" in parsed.netloc:
        raise EngramDaemonClientError("daemon_url_must_not_include_credentials")


def _read_limited(handle: Any, *, limit: int = MAX_DAEMON_RESPONSE_BYTES) -> bytes:
    raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise EngramDaemonClientError("daemon_response_too_large")
    return raw


def normalize_daemon_base_url(base_url: str, *, headers: dict[str, str] | None = None) -> str:
    parsed = urlparse(str(base_url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise EngramDaemonClientError("daemon_url_invalid")
    if parsed.username or parsed.password or "@" in parsed.netloc:
        raise EngramDaemonClientError("daemon_url_must_not_include_credentials")
    if parsed.params or parsed.query or parsed.fragment:
        raise EngramDaemonClientError("daemon_url_must_not_include_query_or_fragment")
    if parsed.path not in {"", "/"}:
        raise EngramDaemonClientError("daemon_url_must_not_include_path")
    if not _is_loopback_host(str(parsed.hostname or "")) and not _remote_daemon_url_allowed(headers or {}):
        raise EngramDaemonClientError("daemon_url_remote_requires_auth_or_opt_in")
    normalized = urlunparse((parsed.scheme.lower(), parsed.netloc, "", "", "", ""))
    return normalized.rstrip("/")


def _remote_daemon_url_allowed(headers: dict[str, str]) -> bool:
    if _env_truthy(os.environ.get(DAEMON_REMOTE_URL_ACK_ENV)):
        return True
    return bool(str(headers.get("Authorization") or "").strip())


def _is_loopback_host(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    if normalized in {"localhost", "::1"}:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _env_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


class EngramDaemonClient:
    """Small JSON client for daemon-owned memory operations."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = DEFAULT_DAEMON_TIMEOUT,
        headers: dict[str, str] | None = None,
        transport: Any | None = None,
    ):
        self.timeout = timeout
        self.headers = dict(headers or {})
        self.base_url = normalize_daemon_base_url(base_url, headers=self.headers)
        self.transport = transport or UrllibJSONTransport()

    def health(self) -> dict[str, Any]:
        return self._tool_request("health")

    def search_memories(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("search_memories", payload)

    def query_knowledge(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("query_knowledge", payload)

    def discover_memory_capabilities(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("discover_memory_capabilities", payload)

    def retrieve_chunk(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("retrieve_chunk", payload)

    def retrieve_chunks(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("retrieve_chunks", payload)

    def retrieve_memory(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("retrieve_memory", payload)

    def store_memory(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("store_memory", payload)

    def prepare_source_memory(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("prepare_source_memory", payload)

    def list_document_extractors(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("list_document_extractors", payload)

    def preview_document_source_connector(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("preview_document_source_connector", payload)

    def prepare_document_disassembly(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("prepare_document_disassembly", payload)

    def prepare_document_coverage_workbench(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("prepare_document_coverage_workbench", payload)

    def prepare_document_coverage_pass(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("prepare_document_coverage_pass", payload)

    def prepare_document_intake_review(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("prepare_document_intake_review", payload)

    def prepare_document_extraction_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("prepare_document_extraction_request", payload)

    def prepare_document_extraction_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("prepare_document_extraction_result", payload)

    def preview_document_extraction(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("preview_document_extraction", payload)

    def prepare_visual_extraction_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("prepare_visual_extraction_request", payload)

    def preview_visual_extraction(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("preview_visual_extraction", payload)

    def prepare_document_understanding_packet(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("prepare_document_understanding_packet", payload)

    def prepare_document_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("prepare_document_draft", payload)

    def prepare_document_promotion_transaction(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("prepare_document_promotion_transaction", payload)

    def apply_document_promotion_transaction(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("apply_document_promotion_transaction", payload)

    def prepare_document_artifact_store(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("prepare_document_artifact_store", payload)

    def store_document_artifact(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("store_document_artifact", payload)

    def prepare_document_ingestion_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("prepare_document_ingestion_plan", payload)

    def run_document_ingestion(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("run_document_ingestion", payload)

    def resume_document_ingestion(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("resume_document_ingestion", payload)

    def inspect_document_ingestion(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("inspect_document_ingestion", payload)

    def prepare_document_ingestion_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("prepare_document_ingestion_completion", payload)

    def complete_document_ingestion(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("complete_document_ingestion", payload)

    def prepare_knowledge_branch(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("prepare_knowledge_branch", payload)

    def prepare_knowledge_pr(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("prepare_knowledge_pr", payload)

    def run_memory_ci(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("run_memory_ci", payload)

    def inspect_knowledge_pr(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("inspect_knowledge_pr", payload)

    def merge_knowledge_pr(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("merge_knowledge_pr", payload)

    def list_memory_benchmark_suites(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("list_memory_benchmark_suites", payload)

    def run_memory_benchmark(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("run_memory_benchmark", payload)

    def inspect_benchmark_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("inspect_benchmark_run", payload)

    def ensure_sync_device_identity(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("ensure_sync_device_identity", payload)

    def export_local_sync_identity(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._tool_request("export_local_sync_identity", payload or {})

    def register_sync_peer(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("register_sync_peer", payload)

    def inspect_sync_state(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._tool_request("inspect_sync_state", payload or {})

    def prepare_sync_changeset(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("prepare_sync_changeset", payload)

    def export_sync_changeset(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("export_sync_changeset", payload)

    def prepare_sync_apply(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("prepare_sync_apply", payload)

    def apply_sync_changeset(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("apply_sync_changeset", payload)

    def inspect_sync_convergence(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("inspect_sync_convergence", payload)

    def list_sync_conflicts(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._tool_request("list_sync_conflicts", payload or {})

    def resolve_sync_conflict(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("resolve_sync_conflict", payload)

    def configure_sync_peer_transport(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("configure_sync_peer_transport", payload)

    def inspect_sync_peer(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("inspect_sync_peer", payload)

    def push_sync_changeset(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("push_sync_changeset", payload)

    def list_sync_inbox(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._tool_request("list_sync_inbox", payload or {})

    def prepare_sync_inbox_apply(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._tool_request("prepare_sync_inbox_apply", payload or {})

    def apply_sync_inbox(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("apply_sync_inbox", payload)

    def prune_applied_sync_inbox_artifacts(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("prune_applied_sync_inbox_artifacts", payload)

    def prepare_graph_readiness_report(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("prepare_graph_readiness_report", payload)

    def prepare_graph_proposal_batch(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("prepare_graph_proposal_batch", payload)

    def apply_graph_proposal_batch(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("apply_graph_proposal_batch", payload)

    def repair_graph_edge_refs(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("repair_graph_edge_refs", payload)

    def repair_graph_store_reconciliation(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("repair_graph_store_reconciliation", payload)

    def memory_os_status(self) -> dict[str, Any]:
        return self._tool_request("memory_os_status")

    def memory_os_inspector(self, *, limit: int | None = None) -> dict[str, Any]:
        path = daemon_route("memory_os_inspector").path
        if limit is not None:
            path = f"{path}?limit={max(1, min(int(limit), 100))}"
        return self._request(daemon_route("memory_os_inspector").method, path)

    def memory_os_source_import_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("memory_os_source_import_job", payload)

    def prepare_legacy_memory_os_migration(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("prepare_legacy_memory_os_migration", payload)

    def apply_legacy_memory_os_migration(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("apply_legacy_memory_os_migration", payload)

    def prepare_legacy_related_to_graph_migration(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("prepare_legacy_related_to_graph_migration", payload)

    def apply_legacy_related_to_graph_migration(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("apply_legacy_related_to_graph_migration", payload)

    def list_source_drafts(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("list_source_drafts", payload)

    def discard_source_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("discard_source_draft", payload)

    def store_prepared_memory(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("store_prepared_memory", payload)

    def check_duplicate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("check_duplicate", payload)

    def update_memory_metadata(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("update_memory_metadata", payload)

    def repair_memory_metadata(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("repair_memory_metadata", payload)

    def repair_document_metadata(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("repair_document_metadata", payload)

    def delete_memory(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._tool_request("delete_memory", payload)

    def _tool_request(
        self,
        route_name: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        route = daemon_route(route_name)
        return self._request(route.method, route.path, payload)

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.transport.request_json(
            method,
            f"{self.base_url}{path}",
            payload,
            self.timeout,
            headers=self.headers,
        )
