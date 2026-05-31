#!/usr/bin/env python3
"""Engram thin daemon-client MCP server.

This entrypoint is for multi-session agent clients. It does not import the
local storage manager, ChromaDB, sentence-transformers, graph stores, or
document extractors. Every tool delegates to a loopback `engramd` daemon so one
process owns mutable Engram storage and indexes.
"""
from __future__ import annotations

import argparse
import asyncio
import os
from typing import Any

from fastmcp import FastMCP

from core.engramd_client import (
    DEFAULT_DAEMON_TIMEOUT,
    EngramDaemonClient,
    EngramDaemonClientError,
)
from core.hub_client_config import (
    build_hub_headers,
    describe_hub_mode,
    read_hub_client_config,
    validate_hub_client_config,
)
from core.memory_os.runtime_paths import resolve_data_root
from core.mcp.tool_registry import build_memory_protocol_sections


mcp = FastMCP("engram")
PRODUCT_NAME = "Engram"
PRODUCT_VERSION = "1.0.0"
PRODUCT_RELEASE_TRACK = "1.0"
PRODUCT_STABILITY = "stable"
PROTOCOL_VERSION = 2
PROTOCOL_SCHEMA_VERSION = "2026-04-27"
DEFAULT_DAEMON_URL = "http://127.0.0.1:8765"


def _daemon_url() -> str:
    hub_config = read_hub_client_config()
    if hub_config.get("hub_configured"):
        return str(hub_config.get("hub_url") or "invalid-hub-url")
    configured = os.environ.get("ENGRAM_DAEMON_URL", "").strip().rstrip("/")
    return configured or DEFAULT_DAEMON_URL


def _daemon_timeout() -> float:
    configured = os.environ.get("ENGRAM_DAEMON_TIMEOUT", "").strip()
    if not configured:
        return DEFAULT_DAEMON_TIMEOUT
    try:
        timeout = float(configured)
    except ValueError:
        return DEFAULT_DAEMON_TIMEOUT
    return max(1.0, timeout)


def _daemon_client() -> EngramDaemonClient:
    hub_config = read_hub_client_config()
    if hub_config.get("hub_configured"):
        validation = validate_hub_client_config(hub_config)
        if validation.get("status") != "ready":
            code = (validation.get("error") or {}).get("code") or "hub_config_invalid"
            raise EngramDaemonClientError(
                f"hub mode configured but unavailable before request: {code}"
            )
        return EngramDaemonClient(
            str(hub_config.get("hub_url")),
            timeout=_daemon_timeout(),
            headers=build_hub_headers(hub_config),
        )
    return EngramDaemonClient(_daemon_url(), timeout=_daemon_timeout())


async def _call_daemon(method_name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    client = _daemon_client()
    method = getattr(client, method_name)
    if payload is None:
        return await asyncio.to_thread(method)
    return await asyncio.to_thread(method, payload)


def _tool_error(code: str, message: str) -> dict[str, str]:
    if code == "runtime_error":
        hub_config = read_hub_client_config()
        if hub_config.get("hub_configured"):
            hub_validation = validate_hub_client_config(hub_config)
            if hub_validation.get("status") != "ready":
                hub_code = str(
                    (hub_validation.get("error") or {}).get("code")
                    or "hub_config_invalid"
                )
                return {
                    "code": hub_code,
                    "message": (
                        "Hub mode is configured but its client configuration is invalid. "
                        f"{message}"
                    ),
                }
            return {
                "code": "hub_unreachable",
                "message": (
                    "Hub mode is configured and failed closed before local storage "
                    f"could be used. {message}"
                ),
            }
    return {"code": code, "message": message}


def _daemon_exception_message(exc: EngramDaemonClientError) -> str:
    error = _tool_error("runtime_error", f"Engram daemon error: {exc}")
    return f"{error['code']}: {error['message']}"


def _normalize_string_list(value: Any) -> list[str]:
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


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _format_daemon_store_response(key: str, response: dict[str, Any]) -> str:
    error = response.get("error")
    if error:
        message = error.get("message") if isinstance(error, dict) else str(error)
        return f"Failed to store '{key}': {message}"
    if not response.get("stored"):
        return f"Failed to store '{key}': daemon did not store memory"
    result = response.get("result")
    if not isinstance(result, dict):
        return f"Failed to store '{key}': daemon returned an invalid response"
    title = result.get("title") or key
    chunk_count = result.get("chunk_count", 0)
    chars = result.get("chars", 0)
    graph_treatment = result.get("graph_treatment") if isinstance(result.get("graph_treatment"), dict) else {}
    semantic_treatment = (
        result.get("semantic_graph_treatment")
        if isinstance(result.get("semantic_graph_treatment"), dict)
        else {}
    )
    graph_count = len(graph_treatment.get("graph_edges_written") or []) + len(
        semantic_treatment.get("graph_edges_written") or []
    )
    graph_suffix = f", {graph_count} graph edges" if graph_count else ""
    return f"Stored: '{title}' ({chunk_count} chunks, {chars} chars{graph_suffix})"


@mcp.tool()
def memory_protocol() -> dict[str, Any]:
    """Describe the daemon-client Engram MCP contract for agents."""
    protocol_sections = build_memory_protocol_sections(thin_client=True)
    hub_config = read_hub_client_config()
    hub_validation = validate_hub_client_config(hub_config)
    hub_description = dict(describe_hub_mode(hub_config))
    hub_description["status"] = hub_validation.get("status")
    if hub_validation.get("error"):
        hub_description["error"] = hub_validation.get("error")
    warnings = [
        "Start or autostart engramd before using this entrypoint.",
        "Use daemon_status() to prove daemon reachability before blaming missing memory.",
        "Use memory_os_status() to inspect the rebuilt SQLite/LanceDB/Kuzu runtime container.",
        "Backend promotion remains config-gated; live storage belongs to engramd.",
    ]
    protocol_error = None
    if hub_config.get("hub_configured") and hub_validation.get("status") != "ready":
        protocol_error = _tool_error(
            str((hub_validation.get("error") or {}).get("code") or "hub_config_invalid"),
            "Hub mode is configured but its client configuration is invalid.",
        )
        warnings.append(
            "Hub clients fail closed until ENGRAM_HUB_ACCESS_TOKEN is configured with a valid token."
        )
    return {
        "product": {
            "name": PRODUCT_NAME,
            "version": PRODUCT_VERSION,
            "release_track": PRODUCT_RELEASE_TRACK,
            "stability": PRODUCT_STABILITY,
        },
        "protocol": {
            "version": PROTOCOL_VERSION,
            "schema_version": PROTOCOL_SCHEMA_VERSION,
            "entrypoint": "server_daemon_client.py",
            "mode": "daemon_client",
        },
        "daemon": {
            "url": _daemon_url(),
            "hub_mode": hub_description,
            "single_owner_rule": (
                "This MCP process is a thin client. It never opens local ChromaDB, "
                "Kuzu, LanceDB, memory JSON, graph JSON, or document extraction state."
            ),
        },
        "retrieval_ladder": [
            "search_memories(query, limit=5) returns scored snippets and key/chunk_id refs.",
            "retrieve_chunk(key, chunk_id) reads one cited chunk.",
            "retrieve_memory(key) reads a full memory only when chunks are insufficient.",
        ],
        "preferred_shortcut": "context_pack is available on the full server; this thin entrypoint keeps stable daemon-owned CRUD/search tools only.",
        "knowledge_contract": protocol_sections["knowledge_contract"],
        "memory_taxonomy": protocol_sections["memory_taxonomy"],
        "aliases": protocol_sections["aliases"],
        "document_workflow": protocol_sections["document_workflow"],
        "document_artifact_workflow": protocol_sections["document_artifact_workflow"],
        "knowledge_pr_workflow": protocol_sections["knowledge_pr_workflow"],
        "benchmark_workflow": protocol_sections["benchmark_workflow"],
        "sync_identity_workflow": protocol_sections["sync_identity_workflow"],
        "sync_changeset_workflow": protocol_sections["sync_changeset_workflow"],
        "sync_transport_workflow": protocol_sections["sync_transport_workflow"],
        "tool_groups": protocol_sections["tool_groups"],
        "canonical_tools": protocol_sections["canonical_tools"],
        "warnings": warnings,
        "error": protocol_error,
    }


@mcp.tool()
async def daemon_status() -> dict[str, Any]:
    """Report whether the configured daemon is reachable without reading or writing memory."""
    hub_config = read_hub_client_config()
    hub_validation = validate_hub_client_config(hub_config)
    hub_description = describe_hub_mode(hub_config)
    if hub_config.get("hub_configured") and hub_validation.get("status") != "ready":
        return {
            "mode": "hub",
            "daemon_url": _daemon_url(),
            "reachable": False,
            "health": None,
            "hub_mode": hub_description,
            "error": _tool_error(
                str((hub_validation.get("error") or {}).get("code") or "hub_config_invalid"),
                "Hub mode is configured but its client configuration is invalid.",
            ),
        }
    try:
        health = await _call_daemon("health")
    except EngramDaemonClientError as exc:
        error_code = "hub_unreachable" if hub_config.get("hub_configured") else "runtime_error"
        return {
            "mode": "hub" if hub_config.get("hub_configured") else "daemon_client",
            "daemon_url": _daemon_url(),
            "reachable": False,
            "health": None,
            "hub_mode": hub_description,
            "error": _tool_error(error_code, str(exc)),
        }
    return {
        "mode": "hub" if hub_config.get("hub_configured") else "daemon_client",
        "daemon_url": _daemon_url(),
        "reachable": health.get("status") == "ok" and health.get("error") is None,
        "health": health,
        "hub_mode": hub_description,
        "error": health.get("error"),
    }


@mcp.tool()
async def memory_os_status() -> dict[str, Any]:
    """Report daemon-owned Memory OS SQLite, LanceDB, Kuzu, job, transaction, and firewall readiness."""
    try:
        return await _call_daemon("memory_os_status")
    except EngramDaemonClientError as exc:
        return {
            "status": "degraded",
            "components": {},
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def ensure_sync_device_identity(device_name: str = "local") -> dict[str, Any]:
    """Ensure this daemon-owned Memory OS runtime has a public sync identity."""
    try:
        return await _call_daemon(
            "ensure_sync_device_identity",
            {"device_name": _optional_text(device_name) or "local"},
        )
    except EngramDaemonClientError as exc:
        return {
            "status": "unavailable",
            "local_device": None,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def export_local_sync_identity() -> dict[str, Any]:
    """Export this runtime's public-only sync identity packet."""
    try:
        return await _call_daemon("export_local_sync_identity", {})
    except EngramDaemonClientError as exc:
        return {
            "record_type": "sync_public_identity",
            "device_id": None,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def register_sync_peer(
    peer_identity_packet: dict[str, Any],
    accept: bool = False,
    approved_by: str | None = None,
) -> dict[str, Any]:
    """Register a reviewed peer public sync identity packet through the daemon."""
    try:
        return await _call_daemon(
            "register_sync_peer",
            {
                "peer_identity_packet": peer_identity_packet,
                "accept": accept,
                "approved_by": approved_by,
            },
        )
    except EngramDaemonClientError as exc:
        return {
            "status": "unavailable",
            "write_performed": False,
            "peer": None,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def inspect_sync_state() -> dict[str, Any]:
    """Inspect sync identity, cursor, changeset, and conflict state through the daemon."""
    try:
        return await _call_daemon("inspect_sync_state", {})
    except EngramDaemonClientError as exc:
        return {
            "schema_version": "2026-05-26.sync-state.v1",
            "write_performed": False,
            "status": {"status": "unavailable"},
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def prepare_sync_changeset(peer_id: str) -> dict[str, Any]:
    """Prepare a no-write reviewed changeset export packet for a registered peer."""
    normalized_peer_id = _optional_text(peer_id)
    if not normalized_peer_id:
        return {
            "schema_version": "2026-05-26.sync-prepare.v1",
            "status": "policy_denied",
            "write_performed": False,
            "error": _tool_error("invalid_request", "peer_id is required"),
        }
    try:
        return await _call_daemon("prepare_sync_changeset", {"peer_id": normalized_peer_id})
    except EngramDaemonClientError as exc:
        return {
            "schema_version": "2026-05-26.sync-prepare.v1",
            "status": "unavailable",
            "write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def export_sync_changeset(
    plan: dict[str, Any],
    accept: bool = False,
    approved_by: str | None = None,
) -> dict[str, Any]:
    """Export a reviewed sync changeset as a signed encrypted bundle through the daemon."""
    try:
        return await _call_daemon(
            "export_sync_changeset",
            {
                "plan": plan,
                "accept": accept,
                "approved_by": approved_by,
            },
        )
    except EngramDaemonClientError as exc:
        return {
            "schema_version": "2026-05-26.sync-export.v1",
            "status": "unavailable",
            "write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def prepare_sync_apply(bundle_b64: str) -> dict[str, Any]:
    """Prepare a no-write apply plan for a signed encrypted sync bundle."""
    normalized_bundle = _optional_text(bundle_b64)
    if not normalized_bundle:
        return {
            "schema_version": "2026-05-26.sync-apply.v1",
            "status": "policy_denied",
            "write_performed": False,
            "error": _tool_error("invalid_request", "bundle_b64 is required"),
        }
    try:
        return await _call_daemon("prepare_sync_apply", {"bundle_b64": normalized_bundle})
    except EngramDaemonClientError as exc:
        return {
            "schema_version": "2026-05-26.sync-apply.v1",
            "status": "unavailable",
            "write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def apply_sync_changeset(
    bundle_b64: str,
    plan: dict[str, Any],
    accept: bool = False,
    approved_by: str | None = None,
) -> dict[str, Any]:
    """Apply a reviewed sync bundle only after re-verification and explicit acceptance."""
    normalized_bundle = _optional_text(bundle_b64)
    if not normalized_bundle:
        return {
            "schema_version": "2026-05-26.sync-apply.v1",
            "status": "policy_denied",
            "write_performed": False,
            "error": _tool_error("invalid_request", "bundle_b64 is required"),
        }
    try:
        return await _call_daemon(
            "apply_sync_changeset",
            {
                "bundle_b64": normalized_bundle,
                "plan": plan,
                "accept": accept,
                "approved_by": approved_by,
            },
        )
    except EngramDaemonClientError as exc:
        return {
            "schema_version": "2026-05-26.sync-apply.v1",
            "status": "unavailable",
            "write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def inspect_sync_convergence(peer_id: str) -> dict[str, Any]:
    """Inspect unresolved sync conflicts for a registered peer."""
    normalized_peer_id = _optional_text(peer_id)
    if not normalized_peer_id:
        return {
            "schema_version": "2026-05-26.sync-convergence.v1",
            "status": "policy_denied",
            "write_performed": False,
            "error": _tool_error("invalid_request", "peer_id is required"),
        }
    try:
        return await _call_daemon("inspect_sync_convergence", {"peer_id": normalized_peer_id})
    except EngramDaemonClientError as exc:
        return {
            "schema_version": "2026-05-26.sync-convergence.v1",
            "status": "unavailable",
            "write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def list_sync_conflicts(status: str | None = None) -> dict[str, Any]:
    """List sync conflict review records without full remote payload bodies."""
    try:
        return await _call_daemon("list_sync_conflicts", {"status": _optional_text(status)})
    except EngramDaemonClientError as exc:
        return {
            "schema_version": "2026-05-26.sync-conflicts.v1",
            "status": "unavailable",
            "write_performed": False,
            "conflicts": [],
            "unresolved_conflict_count": 0,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def resolve_sync_conflict(
    conflict_id: str,
    resolution: str,
    accept: bool = False,
    approved_by: str | None = None,
) -> dict[str, Any]:
    """Resolve a sync conflict review record without directly overwriting memory."""
    try:
        return await _call_daemon(
            "resolve_sync_conflict",
            {
                "conflict_id": conflict_id,
                "resolution": resolution,
                "accept": accept,
                "approved_by": approved_by,
            },
        )
    except EngramDaemonClientError as exc:
        return {
            "schema_version": "2026-05-26.sync-conflict.v1",
            "status": "unavailable",
            "write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def configure_sync_peer_transport(
    peer_id: str,
    url: str,
    mode: str = "manual",
    allow_pull: bool = False,
    accept: bool = False,
    approved_by: str | None = None,
) -> dict[str, Any]:
    """Configure reviewed LAN/Tailscale sync listener coordinates for a registered peer."""
    try:
        return await _call_daemon(
            "configure_sync_peer_transport",
            {
                "peer_id": _optional_text(peer_id),
                "url": _optional_text(url),
                "mode": _optional_text(mode) or "manual",
                "allow_pull": bool(allow_pull),
                "accept": accept,
                "approved_by": approved_by,
            },
        )
    except EngramDaemonClientError as exc:
        return {
            "schema_version": "2026-05-26.sync-peer-transport.v1",
            "status": "unavailable",
            "write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def inspect_sync_peer(peer_id: str) -> dict[str, Any]:
    """Inspect one registered sync peer and its transport coordinates."""
    try:
        return await _call_daemon("inspect_sync_peer", {"peer_id": _optional_text(peer_id)})
    except EngramDaemonClientError as exc:
        return {
            "schema_version": "2026-05-26.sync-peer-transport.v1",
            "status": "unavailable",
            "write_performed": False,
            "peer": None,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def push_sync_changeset(
    peer_id: str,
    accept: bool = False,
    approved_by: str | None = None,
) -> dict[str, Any]:
    """Prepare, export, and push a reviewed encrypted changeset to a sync-only peer listener."""
    try:
        return await _call_daemon(
            "push_sync_changeset",
            {
                "peer_id": _optional_text(peer_id),
                "accept": accept,
                "approved_by": approved_by,
            },
        )
    except EngramDaemonClientError as exc:
        return {
            "schema_version": "2026-05-26.sync-peer-transport.v1",
            "status": "unavailable",
            "write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def list_sync_inbox(peer_id: str | None = None) -> dict[str, Any]:
    """List encrypted inbound sync bundles without applying or returning bundle bytes."""
    try:
        return await _call_daemon("list_sync_inbox", {"peer_id": _optional_text(peer_id)})
    except EngramDaemonClientError as exc:
        return {
            "schema_version": "2026-05-26.sync-inbox.v1",
            "status": "unavailable",
            "write_performed": False,
            "inbox": [],
            "inbox_count": 0,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def prepare_sync_inbox_apply(peer_id: str | None = None, limit: int = 50) -> dict[str, Any]:
    """Prepare a no-write plan for applying already staged sync inbox bundles."""
    try:
        return await _call_daemon(
            "prepare_sync_inbox_apply",
            {"peer_id": _optional_text(peer_id), "limit": int(limit or 0)},
        )
    except EngramDaemonClientError as exc:
        return {
            "schema_version": "2026-05-27.sync-inbox-apply.v1",
            "status": "unavailable",
            "write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def apply_sync_inbox(
    accept: bool = False,
    approved_by: str | None = None,
    peer_id: str | None = None,
    limit: int = 50,
    stop_on_error: bool = True,
) -> dict[str, Any]:
    """Apply already staged signed sync inbox bundles after explicit acceptance."""
    try:
        return await _call_daemon(
            "apply_sync_inbox",
            {
                "peer_id": _optional_text(peer_id),
                "limit": int(limit or 0),
                "accept": accept,
                "approved_by": _optional_text(approved_by),
                "stop_on_error": stop_on_error,
            },
        )
    except EngramDaemonClientError as exc:
        return {
            "schema_version": "2026-05-27.sync-inbox-apply.v1",
            "status": "unavailable",
            "write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def discover_memory_capabilities(
    query: str = "",
    budget_chars: int = 4000,
) -> dict[str, Any]:
    """Return a budgeted, no-write catalog of daemon-owned Memory OS capabilities."""
    payload = {"query": str(query or ""), "budget_chars": int(budget_chars or 4000)}
    try:
        return await _call_daemon("discover_memory_capabilities", payload)
    except EngramDaemonClientError as exc:
        return {
            "schema_version": "2026-05-26.capability-discovery.v1",
            "write_performed": False,
            "capability_groups": {},
            "warnings": [],
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def query_knowledge(request: dict[str, Any]) -> dict[str, Any]:
    """
    Return an Engram Knowledge Contract 1.0 response for task-shaped orientation.

    EKC 1.0 supports project_orientation, source_orientation,
    document_orientation, review_preparation, evidence_audit, graph_evidence,
    entity_profile, decision_packet, implementation_context, and
    evidence_bundle requests with citations, freshness, policy, budget,
    planner, and explicit errors. The envelope remains
    engram.knowledge.*.v0 for compatibility. This tool is read-only.
    """
    try:
        return await _call_daemon("query_knowledge", request)
    except EngramDaemonClientError as exc:
        error = _tool_error("runtime_error", f"Engram daemon error: {exc}")
        return {
            "contract_version": "engram.knowledge.response.v0",
            "request_id": str((request or {}).get("request_id") or ""),
            "status": "unavailable",
            "answer": None,
            "citations": [],
            "freshness": {"state": "unknown"},
            "policy": {
                "unreviewed_sources_used": False,
                "unsupported_inferences_used": False,
                "review_state_available": False,
                "review_filter_enforced": False,
                "review_state_basis": "not_available_in_current_memory_os_records",
            },
            "budget_used": {
                "artifacts_built": 0,
                "artifacts_read": 0,
                "source_reads": 0,
                "tokens_out_estimate": 0,
            },
            "planner": {
                "strategy": "none",
                "methods_used": [],
                "omissions": [],
                "budget": {
                    "requested": {},
                    "used": {
                        "artifacts_built": 0,
                        "artifacts_read": 0,
                        "source_reads": 0,
                        "tokens_out_estimate": 0,
                    },
                },
                "failure_receipts": [
                    {
                        "code": error["code"],
                        "category": "infrastructure",
                        "message": error["message"],
                        "recoverable": True,
                    }
                ],
                "response_status": "unavailable",
            },
            "errors": [
                {
                    "code": error["code"],
                    "category": "infrastructure",
                    "message": error["message"],
                }
            ],
        }


@mcp.tool()
async def search_memories(
    query: str,
    limit: int = 5,
    project: str | None = None,
    exact_project_match: bool = False,
    domain: str | None = None,
    tags: str | list[str] | None = None,
    include_stale: bool = True,
    canonical_only: bool = False,
    pinned_first: bool = False,
    retrieval_mode: str = "semantic",
) -> dict[str, Any]:
    """
    Semantic search through the daemon. Start here before retrieving chunks.

    Results include activation metadata as a rank-only signal. Receipts include
    backend_used/fallback fields so agents can tell whether Memory OS retrieval
    or legacy JSON/Chroma served the request.
    """
    payload = {
        "query": query,
        "limit": limit,
        "project": _optional_text(project),
        "exact_project_match": exact_project_match,
        "domain": _optional_text(domain),
        "tags": _normalize_string_list(tags),
        "include_stale": include_stale,
        "canonical_only": canonical_only,
        "pinned_keys": [],
        "pinned_first": pinned_first,
        "retrieval_mode": retrieval_mode,
    }
    try:
        return await _call_daemon("search_memories", payload)
    except EngramDaemonClientError as exc:
        return {
            "query": query,
            "count": 0,
            "results": [],
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def find_memories(
    query: str,
    limit: int = 5,
    project: str | None = None,
    exact_project_match: bool = False,
    domain: str | None = None,
    tags: str | list[str] | None = None,
    include_stale: bool = True,
    canonical_only: bool = False,
    pinned_first: bool = False,
    retrieval_mode: str = "semantic",
) -> dict[str, Any]:
    """Alias for search_memories()."""
    return await search_memories(
        query=query,
        limit=limit,
        project=project,
        exact_project_match=exact_project_match,
        domain=domain,
        tags=tags,
        include_stale=include_stale,
        canonical_only=canonical_only,
        pinned_first=pinned_first,
        retrieval_mode=retrieval_mode,
    )


@mcp.tool()
async def retrieve_chunk(key: str, chunk_id: int) -> dict[str, Any]:
    """Retrieve one memory chunk through the daemon after search identifies it."""
    try:
        return await _call_daemon("retrieve_chunk", {"key": key, "chunk_id": chunk_id})
    except EngramDaemonClientError as exc:
        return {
            "key": key,
            "chunk_id": chunk_id,
            "found": False,
            "chunk": None,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def read_chunk(key: str, chunk_id: int) -> dict[str, Any]:
    """Alias for retrieve_chunk()."""
    return await retrieve_chunk(key, chunk_id)


@mcp.tool()
async def retrieve_chunks(requests: list[dict[str, Any]]) -> dict[str, Any]:
    """Retrieve multiple specific chunks through the daemon."""
    try:
        return await _call_daemon("retrieve_chunks", {"requests": requests})
    except EngramDaemonClientError as exc:
        return {
            "requested_count": len(requests) if isinstance(requests, list) else 0,
            "found_count": 0,
            "results": [],
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def retrieve_memory(key: str) -> dict[str, Any]:
    """Retrieve a full memory through the daemon only after chunks are insufficient."""
    try:
        return await _call_daemon("retrieve_memory", {"key": key})
    except EngramDaemonClientError as exc:
        return {
            "key": key,
            "found": False,
            "memory": None,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def read_memory(key: str) -> dict[str, Any]:
    """Alias for retrieve_memory()."""
    return await retrieve_memory(key)


@mcp.tool()
async def store_memory(
    key: str,
    content: str,
    tags: str | list[str] | None = None,
    title: str | None = None,
    related_to: str | list[str] | None = None,
    force: bool = False,
    project: str | None = None,
    domain: str | None = None,
    status: str | None = None,
    canonical: bool | None = None,
    memory_type: str | None = None,
    scope: str | None = None,
    trust_state: str | None = None,
    retention_policy: str | None = None,
    sync_policy: str | None = None,
) -> str:
    """Store one reviewed memory through the daemon with metadata and semantic graph treatment."""
    payload = {
        "key": key,
        "content": content,
        "tags": _normalize_string_list(tags),
        "title": title or key,
        "related_to": _normalize_string_list(related_to),
        "force": force,
        "project": _optional_text(project),
        "domain": _optional_text(domain),
        "status": _optional_text(status),
        "canonical": canonical,
        "memory_type": _optional_text(memory_type),
        "scope": _optional_text(scope),
        "trust_state": _optional_text(trust_state),
        "retention_policy": _optional_text(retention_policy),
        "sync_policy": _optional_text(sync_policy),
    }
    try:
        response = await _call_daemon("store_memory", payload)
    except EngramDaemonClientError as exc:
        return _daemon_exception_message(exc)
    return _format_daemon_store_response(key, response)


@mcp.tool()
async def write_memory(
    key: str,
    content: str,
    tags: str | list[str] | None = None,
    title: str | None = None,
    related_to: str | list[str] | None = None,
    force: bool = False,
    project: str | None = None,
    domain: str | None = None,
    status: str | None = None,
    canonical: bool | None = None,
    memory_type: str | None = None,
    scope: str | None = None,
    trust_state: str | None = None,
    retention_policy: str | None = None,
    sync_policy: str | None = None,
) -> str:
    """Alias for store_memory()."""
    return await store_memory(
        key=key,
        content=content,
        tags=tags,
        title=title,
        related_to=related_to,
        force=force,
        project=project,
        domain=domain,
        status=status,
        canonical=canonical,
        memory_type=memory_type,
        scope=scope,
        trust_state=trust_state,
        retention_policy=retention_policy,
        sync_policy=sync_policy,
    )


@mcp.tool()
async def check_duplicate(key: str, content: str) -> dict[str, Any]:
    """Check duplicate risk through the daemon before a reviewed write."""
    try:
        return await _call_daemon("check_duplicate", {"key": key, "content": content})
    except EngramDaemonClientError as exc:
        return {
            "key": key,
            "duplicate": False,
            "match": None,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def prepare_source_memory(
    source_text: str,
    source_type: str,
    source_uri: str | None = None,
    project: str | None = None,
    domain: str | None = None,
    budget_chars: int = 6000,
    pipeline: str = "generic",
) -> dict[str, Any]:
    """Prepare source drafts through the daemon; no active memory is promoted."""
    payload = {
        "source_text": source_text,
        "source_type": source_type,
        "source_uri": source_uri,
        "project": project,
        "domain": domain,
        "budget_chars": budget_chars,
        "pipeline": pipeline,
    }
    try:
        return await _call_daemon("prepare_source_memory", payload)
    except EngramDaemonClientError as exc:
        return {
            "draft": None,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def list_source_drafts(
    project: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """List reviewable source drafts through the daemon."""
    try:
        return await _call_daemon(
            "list_source_drafts",
            {"project": project, "status": status, "limit": limit, "offset": offset},
        )
    except EngramDaemonClientError as exc:
        return {
            "count": 0,
            "drafts": [],
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def discard_source_draft(draft_id: str) -> dict[str, Any]:
    """Discard a reviewable source draft through the daemon."""
    try:
        return await _call_daemon("discard_source_draft", {"draft_id": draft_id})
    except EngramDaemonClientError as exc:
        return {
            "discarded": False,
            "draft_id": draft_id,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def store_prepared_memory(
    draft_id: str,
    selected_items: list[int] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Promote selected source-draft memories through the daemon."""
    try:
        return await _call_daemon(
            "store_prepared_memory",
            {"draft_id": draft_id, "selected_items": selected_items, "force": force},
        )
    except EngramDaemonClientError as exc:
        return {
            "stored_count": 0,
            "stored": [],
            "skipped": [],
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def list_document_extractors() -> dict[str, Any]:
    """Return the no-write document extractor catalog through the daemon before promotion planning."""
    try:
        return await _call_daemon("list_document_extractors", {})
    except EngramDaemonClientError as exc:
        return {
            "catalog": None,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def preview_document_source_connector(
    connector_type: str,
    target: str,
    include_globs: list[str] | None = None,
    max_files: int = 20,
    max_file_size_kb: int = 256,
    max_source_text_chars: int = 12000,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Preview document source arguments through the daemon as a no-write step before promotion."""
    payload = {
        "connector_type": connector_type,
        "target": target,
        "include_globs": include_globs,
        "max_files": max_files,
        "max_file_size_kb": max_file_size_kb,
        "max_source_text_chars": max_source_text_chars,
        "metadata": metadata,
    }
    try:
        return await _call_daemon("preview_document_source_connector", payload)
    except EngramDaemonClientError as exc:
        return {
            "preview": None,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def prepare_document_disassembly(
    source_path: str,
    source_type: str = "pdf",
    max_pages: int | None = None,
    page_range: str | None = None,
    resume_token: str | None = None,
) -> dict[str, Any]:
    """Prepare a no-write document disassembly through the daemon before any promotion."""
    try:
        return await _call_daemon(
            "prepare_document_disassembly",
            {
                "source_path": source_path,
                "source_type": source_type,
                "max_pages": max_pages,
                "page_range": page_range,
                "resume_token": resume_token,
            },
        )
    except EngramDaemonClientError as exc:
        return {
            "disassembly": None,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def prepare_document_coverage_workbench(
    source_path: str,
    document_record: dict[str, Any] | None = None,
    visual_request: dict[str, Any] | None = None,
    image_refs: list[dict[str, Any]] | None = None,
    output_dir: str | None = None,
    render_pages: bool = True,
    run_ocr: bool = False,
    run_table_detection: bool = False,
    max_pages: int | None = None,
) -> dict[str, Any]:
    """Prepare a no-write document coverage workbench through the daemon before promotion."""
    payload = {
        "source_path": source_path,
        "document_record": document_record,
        "visual_request": visual_request,
        "image_refs": image_refs,
        "output_dir": output_dir,
        "render_pages": render_pages,
        "run_ocr": run_ocr,
        "run_table_detection": run_table_detection,
        "max_pages": max_pages,
    }
    try:
        return await _call_daemon("prepare_document_coverage_workbench", payload)
    except EngramDaemonClientError as exc:
        return {
            "workbench": None,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def prepare_document_intake_review(
    source_path: str,
    extractor_id: str | None = None,
    max_pages: int | None = None,
    require_visual_coverage: bool = True,
    require_table_coverage: bool = True,
    require_ocr_coverage: bool = True,
    source_type: str = "pdf",
    page_range: str | None = None,
    resume_token: str | None = None,
) -> dict[str, Any]:
    """Prepare an end-to-end no-write document review packet without promoting memory."""
    payload = {
        "source_path": source_path,
        "extractor_id": extractor_id,
        "max_pages": max_pages,
        "require_visual_coverage": require_visual_coverage,
        "require_table_coverage": require_table_coverage,
        "require_ocr_coverage": require_ocr_coverage,
        "source_type": source_type,
        "page_range": page_range,
        "resume_token": resume_token,
    }
    try:
        return await _call_daemon("prepare_document_intake_review", payload)
    except EngramDaemonClientError as exc:
        return {
            "status": "unavailable",
            "source": {"source_path": source_path},
            "disassembly": None,
            "extraction_request": None,
            "document_preview": None,
            "quality": None,
            "artifact_manifest": None,
            "draft_candidates": [],
            "promotion_guidance": {"auto_promote": False},
            "policy": {
                "write_behavior": "read_only",
                "active_memory_promoted": False,
                "graph_edges_promoted": False,
            },
            "receipts": {"artifacts_built": 0, "artifacts_read": 0, "coverage_missing": []},
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def prepare_document_extraction_request(
    source_ref: dict[str, Any],
    source_type: str,
    requested_outputs: list[str],
    extractor_id: str = "engram-document-request",
    extractor_kind: str = "external_document",
    instructions: str | None = None,
) -> dict[str, Any]:
    """Prepare a no-write document extraction request through the daemon before promotion."""
    payload = {
        "source_ref": source_ref,
        "source_type": source_type,
        "requested_outputs": requested_outputs,
        "extractor_id": extractor_id,
        "extractor_kind": extractor_kind,
        "instructions": instructions,
    }
    try:
        return await _call_daemon("prepare_document_extraction_request", payload)
    except EngramDaemonClientError as exc:
        return {
            "request": None,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def prepare_document_extraction_result(
    extraction_request: dict[str, Any],
    title: str,
    content: str,
    media_type: str,
    metadata: dict[str, Any] | None = None,
    image_refs: list[dict[str, Any]] | None = None,
    requested_visual_capabilities: list[str] | None = None,
) -> dict[str, Any]:
    """Normalize parser output as a no-write daemon result before document promotion."""
    payload = {
        "extraction_request": extraction_request,
        "title": title,
        "content": content,
        "media_type": media_type,
        "metadata": metadata,
        "image_refs": image_refs,
        "requested_visual_capabilities": requested_visual_capabilities,
    }
    try:
        return await _call_daemon("prepare_document_extraction_result", payload)
    except EngramDaemonClientError as exc:
        return {
            "result": None,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def preview_document_extraction(
    title: str,
    source_uri: str,
    source_type: str,
    content: str,
    media_type: str,
    metadata: dict[str, Any] | None = None,
    extractor_id: str = "engram-text-preview",
    extractor_kind: str = "agent_native",
) -> dict[str, Any]:
    """Preview document evidence and chunks as a no-write daemon step before promotion."""
    payload = {
        "title": title,
        "source_uri": source_uri,
        "source_type": source_type,
        "content": content,
        "media_type": media_type,
        "metadata": metadata,
        "extractor_id": extractor_id,
        "extractor_kind": extractor_kind,
    }
    try:
        return await _call_daemon("preview_document_extraction", payload)
    except EngramDaemonClientError as exc:
        return {
            "preview": None,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def prepare_visual_extraction_request(
    document_record: dict[str, Any],
    image_refs: list[dict[str, Any]],
    requested_capabilities: list[str],
    extractor_id: str = "engram-visual-request",
    extractor_kind: str = "ocr_vision",
    instructions: str | None = None,
) -> dict[str, Any]:
    """Prepare a no-write OCR/vision coverage request through the daemon before promotion."""
    payload = {
        "document_record": document_record,
        "image_refs": image_refs,
        "requested_capabilities": requested_capabilities,
        "extractor_id": extractor_id,
        "extractor_kind": extractor_kind,
        "instructions": instructions,
    }
    try:
        return await _call_daemon("prepare_visual_extraction_request", payload)
    except EngramDaemonClientError as exc:
        return {
            "request": None,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def preview_visual_extraction(
    document_record: dict[str, Any],
    observations: list[dict[str, Any]],
    extractor_id: str = "engram-visual-preview",
    extractor_kind: str = "agent_native",
    visual_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Preview caller-supplied visual evidence as no-write daemon evidence before promotion."""
    payload = {
        "document_record": document_record,
        "observations": observations,
        "extractor_id": extractor_id,
        "extractor_kind": extractor_kind,
        "visual_request": visual_request,
    }
    try:
        return await _call_daemon("preview_visual_extraction", payload)
    except EngramDaemonClientError as exc:
        return {
            "preview": None,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def prepare_document_understanding_packet(
    document_record: dict[str, Any],
    analysis: dict[str, Any],
    chunk_refs: list[dict[str, Any]] | None = None,
    visual_artifacts: list[dict[str, Any]] | None = None,
    candidate_graph_edges: list[dict[str, Any]] | None = None,
    created_by: str = "agent",
) -> dict[str, Any]:
    """Prepare a no-write document understanding packet through the daemon before promotion."""
    payload = {
        "document_record": document_record,
        "analysis": analysis,
        "chunk_refs": chunk_refs,
        "visual_artifacts": visual_artifacts,
        "candidate_graph_edges": candidate_graph_edges,
        "created_by": created_by,
    }
    try:
        return await _call_daemon("prepare_document_understanding_packet", payload)
    except EngramDaemonClientError as exc:
        return {
            "packet": None,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def prepare_document_draft(
    document_record: dict[str, Any],
    analysis: dict[str, Any],
    chunk_refs: list[dict[str, Any]] | None = None,
    visual_artifacts: list[dict[str, Any]] | None = None,
    candidate_graph_edges: list[dict[str, Any]] | None = None,
    created_by: str = "agent",
) -> dict[str, Any]:
    """Prepare a no-write document draft through the daemon before any memory promotion."""
    payload = {
        "document_record": document_record,
        "analysis": analysis,
        "chunk_refs": chunk_refs,
        "visual_artifacts": visual_artifacts,
        "candidate_graph_edges": candidate_graph_edges,
        "created_by": created_by,
    }
    try:
        return await _call_daemon("prepare_document_draft", payload)
    except EngramDaemonClientError as exc:
        return {
            "draft": None,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def prepare_document_promotion_transaction(
    document_draft: dict[str, Any],
    approved_by: str,
    selected_memory_indexes: list[int] | None = None,
    selected_edge_indexes: list[int] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Prepare a no-write reviewed document promotion transaction without executing promotion."""
    payload = {
        "document_draft": document_draft,
        "approved_by": approved_by,
        "selected_memory_indexes": selected_memory_indexes,
        "selected_edge_indexes": selected_edge_indexes,
        "notes": notes,
    }
    try:
        return await _call_daemon("prepare_document_promotion_transaction", payload)
    except EngramDaemonClientError as exc:
        return {
            "transaction": None,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def apply_document_promotion_transaction(
    document_promotion_transaction: dict[str, Any],
    accept: bool = False,
    approved_by: str | None = None,
    selected_operation_indexes: list[int] | None = None,
) -> dict[str, Any]:
    """Apply reviewed document promotion writes; requires explicit accept=True."""
    payload = {
        "document_promotion_transaction": document_promotion_transaction,
        "accept": accept,
        "approved_by": approved_by,
        "selected_operation_indexes": selected_operation_indexes,
    }
    try:
        return await _call_daemon("apply_document_promotion_transaction", payload)
    except EngramDaemonClientError as exc:
        return {
            "status": "unavailable",
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def prepare_document_artifact_store(
    review_packet: dict[str, Any],
    artifact_family: str = "document_evidence",
) -> dict[str, Any]:
    """Prepare a reviewed document artifact-store transaction without promoting active memory."""
    payload = {"review_packet": review_packet, "artifact_family": artifact_family}
    try:
        return await _call_daemon("prepare_document_artifact_store", payload)
    except EngramDaemonClientError as exc:
        return {
            "status": "unavailable",
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def store_document_artifact(
    prepared_transaction_id: str,
    accept: bool = False,
    review_packet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Store ledgered document evidence after accept=True and a matching reviewed packet."""
    payload = {
        "prepared_transaction_id": prepared_transaction_id,
        "accept": accept,
        "review_packet": review_packet,
    }
    try:
        return await _call_daemon("store_document_artifact", payload)
    except EngramDaemonClientError as exc:
        return {
            "status": "unavailable",
            "stored": False,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def prepare_document_ingestion_plan(
    source_path: str,
    project: str | None = None,
    domain: str | None = None,
    profile: str = "graph_coverage",
    page_window_size: int = 25,
    analysis_policy: str = "defer",
    approval_mode: str = "agent_authorized",
    budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prepare a no-write resumable document ingestion plan through the daemon."""
    payload = {
        "source_path": source_path,
        "project": project,
        "domain": domain,
        "profile": profile,
        "page_window_size": page_window_size,
        "analysis_policy": analysis_policy,
        "approval_mode": approval_mode,
        "budget": budget,
    }
    try:
        return await _call_daemon("prepare_document_ingestion_plan", payload)
    except EngramDaemonClientError as exc:
        return {
            "status": "unavailable",
            "source_path": source_path,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def run_document_ingestion(
    ingestion_id: str,
    accept: bool = False,
    approved_by: str | None = None,
    review_packets: list[dict[str, Any]] | None = None,
    understanding_analysis: dict[str, Any] | None = None,
    visual_preview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Queue reviewed document ingestion writes through the daemon; requires explicit accept=True and progress polling."""
    payload = {
        "ingestion_id": ingestion_id,
        "accept": accept,
        "approved_by": approved_by,
        "review_packets": review_packets,
        "understanding_analysis": understanding_analysis,
        "visual_preview": visual_preview,
    }
    try:
        return await _call_daemon("run_document_ingestion", payload)
    except EngramDaemonClientError as exc:
        return {
            "status": "unavailable",
            "ingestion_id": ingestion_id,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def resume_document_ingestion(
    ingestion_id: str,
    accept: bool = False,
    approved_by: str | None = None,
    review_packets: list[dict[str, Any]] | None = None,
    understanding_analysis: dict[str, Any] | None = None,
    visual_preview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Queue reviewed document ingestion resume writes through the daemon; requires explicit accept=True and progress polling."""
    payload = {
        "ingestion_id": ingestion_id,
        "accept": accept,
        "approved_by": approved_by,
        "review_packets": review_packets,
        "understanding_analysis": understanding_analysis,
        "visual_preview": visual_preview,
    }
    try:
        return await _call_daemon("resume_document_ingestion", payload)
    except EngramDaemonClientError as exc:
        return {
            "status": "unavailable",
            "ingestion_id": ingestion_id,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def inspect_document_ingestion(
    ingestion_id: str | None = None,
    document_id: str | None = None,
) -> dict[str, Any]:
    """Inspect a document ingestion plan or progress record through the daemon without writing."""
    payload = {"ingestion_id": ingestion_id, "document_id": document_id}
    try:
        return await _call_daemon("inspect_document_ingestion", payload)
    except EngramDaemonClientError as exc:
        return {
            "status": "unavailable",
            "ingestion_id": ingestion_id,
            "document_id": document_id,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def prepare_document_coverage_pass(
    ingestion_record: dict[str, Any],
    review_packets: list[dict[str, Any]] | None = None,
    coverage_policy: str = "auto_local",
    coverage_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prepare automatic visual/OCR/table coverage evidence without writing or promoting active memory or graph edges."""
    payload = {
        "ingestion_record": ingestion_record,
        "review_packets": review_packets,
        "coverage_policy": coverage_policy,
        "coverage_options": coverage_options,
    }
    try:
        return await _call_daemon("prepare_document_coverage_pass", payload)
    except EngramDaemonClientError as exc:
        return {
            "status": "unavailable",
            "ingestion_id": ingestion_record.get("ingestion_id") if isinstance(ingestion_record, dict) else None,
            "document_id": ingestion_record.get("document_id") if isinstance(ingestion_record, dict) else None,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def prepare_knowledge_branch(
    name: str,
    source_refs: list[dict[str, Any]] | None = None,
    base_snapshot_ref: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prepare a Knowledge Branch review record through the daemon."""
    payload = {
        "name": name,
        "source_refs": source_refs,
        "base_snapshot_ref": base_snapshot_ref,
        "metadata": metadata,
    }
    try:
        return await _call_daemon("prepare_knowledge_branch", payload)
    except EngramDaemonClientError as exc:
        return {
            "status": "unavailable",
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def prepare_knowledge_pr(
    branch_id: str,
    title: str,
    proposed_operations: list[dict[str, Any]] | None = None,
    source_refs: list[dict[str, Any]] | None = None,
    document_refs: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prepare a Knowledge PR review packet through the daemon."""
    payload = {
        "branch_id": branch_id,
        "title": title,
        "proposed_operations": proposed_operations,
        "source_refs": source_refs,
        "document_refs": document_refs,
        "metadata": metadata,
    }
    try:
        return await _call_daemon("prepare_knowledge_pr", payload)
    except EngramDaemonClientError as exc:
        return {
            "status": "unavailable",
            "branch_id": branch_id,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def run_memory_ci(
    knowledge_pr_id: str,
    gates: list[str] | None = None,
    ci_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run Memory CI gates for a Knowledge PR through the daemon."""
    payload = {
        "knowledge_pr_id": knowledge_pr_id,
        "gates": gates,
        "ci_context": ci_context,
    }
    try:
        return await _call_daemon("run_memory_ci", payload)
    except EngramDaemonClientError as exc:
        return {
            "status": "unavailable",
            "knowledge_pr_id": knowledge_pr_id,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def inspect_knowledge_pr(knowledge_pr_id: str) -> dict[str, Any]:
    """Inspect a Knowledge PR, latest CI status, and mergeability through the daemon."""
    payload = {"knowledge_pr_id": knowledge_pr_id}
    try:
        return await _call_daemon("inspect_knowledge_pr", payload)
    except EngramDaemonClientError as exc:
        return {
            "status": "unavailable",
            "knowledge_pr_id": knowledge_pr_id,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def list_memory_benchmark_suites(suite_id: str | None = None) -> dict[str, Any]:
    """List deterministic Memory CI benchmark suites through the daemon without writing."""
    payload = {"suite_id": suite_id}
    try:
        return await _call_daemon("list_memory_benchmark_suites", payload)
    except EngramDaemonClientError as exc:
        return {
            "status": "unavailable",
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def run_memory_benchmark(
    suite_id: str = "smoke",
    seed: int = 42,
    persist: bool = True,
) -> dict[str, Any]:
    """Run a deterministic Memory CI benchmark suite through the daemon."""
    payload = {"suite_id": suite_id, "seed": seed, "persist": persist}
    try:
        return await _call_daemon("run_memory_benchmark", payload)
    except EngramDaemonClientError as exc:
        return {
            "status": "unavailable",
            "suite_id": suite_id,
            "seed": seed,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def inspect_benchmark_run(run_id: str) -> dict[str, Any]:
    """Inspect one persisted Memory CI benchmark run through the daemon."""
    payload = {"run_id": run_id}
    try:
        return await _call_daemon("inspect_benchmark_run", payload)
    except EngramDaemonClientError as exc:
        return {
            "status": "unavailable",
            "run_id": run_id,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def merge_knowledge_pr(
    knowledge_pr_id: str,
    accept: bool = False,
    approved_by: str | None = None,
    selected_operation_ids: list[str] | None = None,
    selected_operation_indexes: list[int] | None = None,
    ci_waivers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Merge selected reviewed Knowledge PR operations after explicit acceptance."""
    payload = {
        "knowledge_pr_id": knowledge_pr_id,
        "accept": accept,
        "approved_by": approved_by,
        "selected_operation_ids": selected_operation_ids,
        "selected_operation_indexes": selected_operation_indexes,
        "ci_waivers": ci_waivers,
    }
    try:
        return await _call_daemon("merge_knowledge_pr", payload)
    except EngramDaemonClientError as exc:
        return {
            "status": "unavailable",
            "knowledge_pr_id": knowledge_pr_id,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def prepare_document_ingestion_completion(
    document_id: str,
    artifact_id: str | None = None,
    visual_request: dict[str, Any] | None = None,
    visual_preview: dict[str, Any] | None = None,
    understanding_packet: dict[str, Any] | None = None,
    document_promotion_transaction: dict[str, Any] | None = None,
    coverage_waivers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate usable document completion as a no-write daemon gate before promotion."""
    payload = {
        "document_id": document_id,
        "artifact_id": artifact_id,
        "visual_request": visual_request,
        "visual_preview": visual_preview,
        "understanding_packet": understanding_packet,
        "document_promotion_transaction": document_promotion_transaction,
        "coverage_waivers": coverage_waivers,
    }
    try:
        return await _call_daemon("prepare_document_ingestion_completion", payload)
    except EngramDaemonClientError as exc:
        return {
            "status": "unavailable",
            "document_id": document_id,
            "usable": False,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def complete_document_ingestion(
    document_id: str,
    artifact_id: str | None = None,
    visual_request: dict[str, Any] | None = None,
    visual_preview: dict[str, Any] | None = None,
    understanding_packet: dict[str, Any] | None = None,
    document_promotion_transaction: dict[str, Any] | None = None,
    coverage_waivers: list[dict[str, Any]] | None = None,
    accept: bool = False,
    approved_by: str | None = None,
    selected_operation_indexes: list[int] | None = None,
) -> dict[str, Any]:
    """Write the usable document marker after explicit accept=True and reviewed graph evidence."""
    payload = {
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
    }
    try:
        return await _call_daemon("complete_document_ingestion", payload)
    except EngramDaemonClientError as exc:
        return {
            "status": "unavailable",
            "document_id": document_id,
            "usable": False,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def prepare_legacy_memory_os_migration(
    legacy_dir: str = "data/memories",
    include_details: bool = False,
) -> dict[str, Any]:
    """Prepare a no-write legacy JSON migration transaction through the daemon."""
    payload = {"legacy_dir": legacy_dir, "include_details": include_details}
    try:
        return await _call_daemon("prepare_legacy_memory_os_migration", payload)
    except EngramDaemonClientError as exc:
        return {
            "operation": "prepare_legacy_memory_os_migration",
            "status": "unavailable",
            "legacy_dir": legacy_dir,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def apply_legacy_memory_os_migration(
    legacy_dir: str = "data/memories",
    accept: bool = False,
    approved_by: str | None = None,
    include_details: bool = False,
) -> dict[str, Any]:
    """Apply reviewed legacy JSON migration writes; requires explicit accept=True."""
    payload = {
        "legacy_dir": legacy_dir,
        "accept": accept,
        "approved_by": approved_by,
        "include_details": include_details,
    }
    try:
        return await _call_daemon("apply_legacy_memory_os_migration", payload)
    except EngramDaemonClientError as exc:
        return {
            "operation": "apply_legacy_memory_os_migration",
            "status": "unavailable",
            "legacy_dir": legacy_dir,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def prepare_legacy_related_to_graph_migration(
    legacy_dir: str = "data/memories",
    include_details: bool = False,
) -> dict[str, Any]:
    """Prepare a no-write legacy related_to graph migration transaction through the daemon."""
    payload = {"legacy_dir": legacy_dir, "include_details": include_details}
    try:
        return await _call_daemon("prepare_legacy_related_to_graph_migration", payload)
    except EngramDaemonClientError as exc:
        return {
            "operation": "prepare_legacy_related_to_graph_migration",
            "status": "unavailable",
            "legacy_dir": legacy_dir,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def apply_legacy_related_to_graph_migration(
    legacy_dir: str = "data/memories",
    accept: bool = False,
    approved_by: str | None = None,
    include_details: bool = False,
) -> dict[str, Any]:
    """Apply reviewed legacy related_to graph edges; requires explicit accept=True."""
    payload = {
        "legacy_dir": legacy_dir,
        "accept": accept,
        "approved_by": approved_by,
        "include_details": include_details,
    }
    try:
        return await _call_daemon("apply_legacy_related_to_graph_migration", payload)
    except EngramDaemonClientError as exc:
        return {
            "operation": "apply_legacy_related_to_graph_migration",
            "status": "unavailable",
            "legacy_dir": legacy_dir,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def prepare_graph_readiness_report(
    scope: str = "memory_os",
    project: str | None = None,
    exact_project_match: bool = False,
    domain: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Inventory graphable Memory OS sources without writing graph edges."""
    payload = {
        "scope": scope,
        "project": project,
        "exact_project_match": exact_project_match,
        "domain": domain,
        "limit": limit,
    }
    try:
        return await _call_daemon("prepare_graph_readiness_report", payload)
    except EngramDaemonClientError as exc:
        return {
            "status": "unavailable",
            "scope": scope,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def prepare_graph_proposal_batch(
    scope: str = "memory_os",
    project: str | None = None,
    domain: str | None = None,
    source_refs: list[dict[str, Any]] | None = None,
    limit: int = 10,
    budget_chars: int = 12000,
    candidate_graph_edges: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Prepare cited graph proposal context and validate candidate edges without writing."""
    payload = {
        "scope": scope,
        "project": project,
        "domain": domain,
        "source_refs": source_refs,
        "limit": limit,
        "budget_chars": budget_chars,
        "candidate_graph_edges": candidate_graph_edges,
    }
    try:
        return await _call_daemon("prepare_graph_proposal_batch", payload)
    except EngramDaemonClientError as exc:
        return {
            "status": "unavailable",
            "scope": scope,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def apply_graph_proposal_batch(
    scope: str = "memory_os",
    project: str | None = None,
    domain: str | None = None,
    source_refs: list[dict[str, Any]] | None = None,
    candidate_graph_edges: list[dict[str, Any]] | None = None,
    accept: bool = False,
    approved_by: str | None = None,
    limit: int = 10,
    budget_chars: int = 12000,
) -> dict[str, Any]:
    """Write reviewed graph proposal edges only after explicit accept=True."""
    payload = {
        "scope": scope,
        "project": project,
        "domain": domain,
        "source_refs": source_refs,
        "candidate_graph_edges": candidate_graph_edges,
        "accept": accept,
        "approved_by": approved_by,
        "limit": limit,
        "budget_chars": budget_chars,
    }
    try:
        return await _call_daemon("apply_graph_proposal_batch", payload)
    except EngramDaemonClientError as exc:
        return {
            "status": "unavailable",
            "scope": scope,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def repair_graph_edge_refs(
    source: str | None = None,
    limit: int = 1000,
    accept: bool = False,
    approved_by: str | None = None,
) -> dict[str, Any]:
    """Add compact key/id identities to graph refs; dry-run unless accept=True."""
    payload = {
        "source": source,
        "limit": limit,
        "accept": accept,
        "approved_by": approved_by,
    }
    try:
        return await _call_daemon("repair_graph_edge_refs", payload)
    except EngramDaemonClientError as exc:
        return {
            "operation": "repair_graph_edge_refs",
            "status": "unavailable",
            "source": source,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def repair_graph_store_reconciliation(
    repair_mode: str = "upsert_missing",
    limit: int = 5000,
    accept: bool = False,
    approved_by: str | None = None,
) -> dict[str, Any]:
    """Replay exact ledger graph edges into the graph store; dry-run unless accept=True."""
    payload = {
        "repair_mode": repair_mode,
        "limit": limit,
        "accept": accept,
        "approved_by": approved_by,
    }
    try:
        return await _call_daemon("repair_graph_store_reconciliation", payload)
    except EngramDaemonClientError as exc:
        return {
            "operation": "repair_graph_store_reconciliation",
            "status": "unavailable",
            "repair_mode": repair_mode,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def update_memory_metadata(
    key: str,
    title: str | None = None,
    tags: str | list[str] | None = None,
    related_to: str | list[str] | None = None,
    project: str | None = None,
    domain: str | None = None,
    status: str | None = None,
    canonical: bool | None = None,
) -> dict[str, Any]:
    """Update selected memory metadata through the daemon."""
    payload = {
        "key": key,
        "title": title,
        "tags": _normalize_string_list(tags) if tags is not None else None,
        "related_to": _normalize_string_list(related_to) if related_to is not None else None,
        "project": project,
        "domain": domain,
        "status": status,
        "canonical": canonical,
    }
    payload = {name: value for name, value in payload.items() if value is not None}
    try:
        return await _call_daemon("update_memory_metadata", payload)
    except EngramDaemonClientError as exc:
        return {
            "key": key,
            "updated": False,
            "memory": None,
            "error": _tool_error("runtime_error", f"Engram daemon error: {exc}"),
        }


@mcp.tool()
async def repair_memory_metadata(keys: str | list[str], dry_run: bool = True) -> dict[str, Any]:
    """Dry-run or execute selected metadata repair through the daemon."""
    normalized_keys = _normalize_string_list(keys)
    try:
        return await _call_daemon(
            "repair_memory_metadata",
            {"keys": normalized_keys, "dry_run": dry_run},
        )
    except EngramDaemonClientError as exc:
        return {
            "requested_count": len(normalized_keys),
            "repaired_count": 0,
            "dry_run": dry_run,
            "repairs": [],
            "error": _tool_error("runtime_error", f"❌ Engram daemon error: {exc}"),
        }


@mcp.tool()
async def delete_memory(key: str) -> str:
    """Delete one memory through the daemon."""
    try:
        payload = await _call_daemon("delete_memory", {"key": key})
    except EngramDaemonClientError as exc:
        return _daemon_exception_message(exc)
    error = payload.get("error")
    if error:
        message = error.get("message") if isinstance(error, dict) else str(error)
        return f"Engram daemon error: {message}"
    if payload.get("deleted"):
        return f"Deleted memory: '{key}'"
    return f"Memory not found: '{key}'"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Engram thin daemon-client MCP server",
    )
    parser.add_argument(
        "--daemon-url",
        default=None,
        help=f"Daemon URL to use for this process (default: {DEFAULT_DAEMON_URL})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.daemon_url:
        os.environ["ENGRAM_DAEMON_URL"] = args.daemon_url.strip().rstrip("/")

    data_dir = os.environ.get("ENGRAM_DATA_DIR", "").strip()
    if not data_dir:
        os.environ["ENGRAM_DATA_DIR"] = str(resolve_data_root())

    mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
