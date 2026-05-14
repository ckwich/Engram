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
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from core.engramd_client import EngramDaemonClient, EngramDaemonClientError
from core.mcp.tool_registry import (
    DOCUMENT_ARTIFACT_WORKFLOW,
    STABLE_DOCUMENT_WORKFLOW,
    STABLE_EKC_TASK_TYPES,
    build_memory_protocol_sections,
)


mcp = FastMCP("engram")
PRODUCT_NAME = "Engram"
PRODUCT_VERSION = "1.0.0"
PRODUCT_RELEASE_TRACK = "1.0"
PRODUCT_STABILITY = "stable"
PROTOCOL_VERSION = 2
PROTOCOL_SCHEMA_VERSION = "2026-04-27"
DEFAULT_DAEMON_URL = "http://127.0.0.1:8765"


def _daemon_url() -> str:
    configured = os.environ.get("ENGRAM_DAEMON_URL", "").strip().rstrip("/")
    return configured or DEFAULT_DAEMON_URL


def _daemon_client() -> EngramDaemonClient:
    return EngramDaemonClient(_daemon_url())


async def _call_daemon(method_name: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    client = _daemon_client()
    method = getattr(client, method_name)
    if payload is None:
        return await asyncio.to_thread(method)
    return await asyncio.to_thread(method, payload)


def _tool_error(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


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
    return f"Stored: '{title}' ({chunk_count} chunks, {chars} chars)"


@mcp.tool()
def memory_protocol() -> dict[str, Any]:
    """Describe the daemon-client Engram MCP contract for agents."""
    protocol_sections = build_memory_protocol_sections(thin_client=True)
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
        "knowledge_contract": {
            "tool": "query_knowledge",
            "contract_version": "engram.knowledge.request.v0",
            "response_version": "engram.knowledge.response.v0",
            "release_track": "1.0",
            "stability": "stable",
            "task_types": list(STABLE_EKC_TASK_TYPES),
            "scope": "project_orientation, source_orientation, document_orientation, review_preparation, evidence_audit, graph_evidence, entity_profile, decision_packet, implementation_context, evidence_bundle",
        },
        "aliases": {
            "find_memories": "search_memories",
            "read_chunk": "retrieve_chunk",
            "read_memory": "retrieve_memory",
            "write_memory": "store_memory",
        },
        "document_workflow": protocol_sections["document_workflow"],
        "document_artifact_workflow": protocol_sections["document_artifact_workflow"],
        "tool_groups": protocol_sections["tool_groups"],
        "canonical_tools": protocol_sections["canonical_tools"],
        "warnings": [
            "Start or autostart engramd before using this entrypoint.",
            "Use daemon_status() to prove daemon reachability before blaming missing memory.",
            "Use memory_os_status() to inspect the rebuilt SQLite/LanceDB/Kuzu runtime container.",
            "Backend promotion remains config-gated; live storage belongs to engramd.",
        ],
        "error": None,
    }


@mcp.tool()
async def daemon_status() -> dict[str, Any]:
    """Report whether the configured daemon is reachable without reading or writing memory."""
    try:
        health = await _call_daemon("health")
    except EngramDaemonClientError as exc:
        return {
            "mode": "daemon_client",
            "daemon_url": _daemon_url(),
            "reachable": False,
            "health": None,
            "error": _tool_error("runtime_error", str(exc)),
        }
    return {
        "mode": "daemon_client",
        "daemon_url": _daemon_url(),
        "reachable": health.get("status") == "ok" and health.get("error") is None,
        "health": health,
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
                        "code": "runtime_error",
                        "category": "infrastructure",
                        "message": f"Engram daemon error: {exc}",
                        "recoverable": True,
                    }
                ],
                "response_status": "unavailable",
            },
            "errors": [
                {
                    "code": "runtime_error",
                    "category": "infrastructure",
                    "message": f"Engram daemon error: {exc}",
                }
            ],
        }


@mcp.tool()
async def search_memories(
    query: str,
    limit: int = 5,
    project: str | None = None,
    domain: str | None = None,
    tags: str | list[str] | None = None,
    include_stale: bool = True,
    canonical_only: bool = False,
    pinned_first: bool = False,
    retrieval_mode: str = "semantic",
) -> dict[str, Any]:
    """Semantic search through the daemon. Start here before retrieving chunks."""
    payload = {
        "query": query,
        "limit": limit,
        "project": _optional_text(project),
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
) -> str:
    """Store one reviewed memory through the daemon's JSON-first write path."""
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
    }
    try:
        response = await _call_daemon("store_memory", payload)
    except EngramDaemonClientError as exc:
        return f"Engram daemon error: {exc}"
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
        return f"Engram daemon error: {exc}"
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
        os.environ["ENGRAM_DATA_DIR"] = str((Path(__file__).resolve().parent / "data").resolve())

    mcp.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
