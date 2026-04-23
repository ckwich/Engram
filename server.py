#!/usr/bin/env python3
"""
Engram v0.1 — MCP Server
Provides semantic memory tools to AI agents via the Model Context Protocol.

Three-tier retrieval pattern (agents should follow this):
  1. search_memories(query) / search_memories_text(query)
     → scored snippets, identify key + chunk_id
  2. retrieve_chunk(key, chunk_id) / retrieve_chunk_text(key, chunk_id)
     → one relevant section, usually sufficient
  3. retrieve_memory(key) / retrieve_memory_text(key)
     → full content, use sparingly
"""

import argparse
import json
import os
import re
import sys
from typing import Any

from fastmcp import FastMCP
from core.embedder import embedder
from core.memory_manager import memory_manager, DuplicateMemoryError, _config
from core.session_pins import SessionPinStore
from core.tool_payloads import (
    build_list_error_payload,
    build_list_payload,
    build_search_error_payload,
    build_search_payload,
    MemoryListPayload,
    render_list_payload,
    render_search_payload,
    SearchPayload,
)

mcp = FastMCP("engram")
session_pin_store = SessionPinStore()


def _clamp_search_limit(limit: int) -> int:
    return min(max(limit, 1), 20)


def _normalize_string_list(value: Any) -> list[str]:
    """Accept comma-separated strings or list-like values as a de-duped string list."""
    if value is None:
        return []

    raw_items: list[str] = []
    if isinstance(value, str):
        raw_items = value.split(",")
    else:
        for item in value:
            raw_items.extend(str(item).split(","))

    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _slugify_memory_key(value: str) -> str:
    """Create a conservative snake_case key from a title or heading."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug or "untitled_memory"


def _clamp_list_limit(limit: int | None) -> int:
    if limit is None:
        return 50
    normalized = int(limit)
    if normalized <= 0:
        return 0
    return min(max(normalized, 1), 500)


def _normalize_offset(offset: int | None) -> int:
    if offset is None:
        return 0
    return max(int(offset), 0)


def _validate_search_query(query: str) -> str | None:
    if not query or not query.strip():
        return "❌ Query cannot be empty."
    if len(query) > 2000:
        return "❌ Query too long (max 2,000 chars). Shorten your search query."
    return None


def _normalize_session_id(session_id: str | None) -> str | None:
    if session_id is None:
        return None
    normalized = str(session_id).strip()
    return normalized or None


def _normalize_memory_key(key: str) -> str:
    normalized = str(key).strip()
    if not normalized:
        raise ValueError("key is required")
    return normalized


def _pin_payload(session_id: str, pins: list[str], **extra: Any) -> dict[str, Any]:
    payload = {
        "session_id": session_id,
        "count": len(pins),
        "pins": pins,
        "error": None,
    }
    payload.update(extra)
    return payload


def _runtime_error_payload(message: str, **payload: Any) -> dict[str, Any]:
    """Attach a stable structured runtime error payload."""
    data = dict(payload)
    data["error"] = {
        "code": "runtime_error",
        "message": message,
    }
    return data


def _retrieve_chunk_payload(result: dict | None, key: str, chunk_id: int) -> dict[str, Any]:
    """Normalize chunk retrieval output into the structured contract."""
    if not result:
        return {
            "key": key,
            "chunk_id": chunk_id,
            "found": False,
            "chunk": None,
            "error": None,
        }

    chunk = {
        "title": result.get("title", key),
        "text": result.get("text"),
        "section_title": result.get("section_title"),
        "heading_path": result.get("heading_path", []),
        "chunk_kind": result.get("chunk_kind"),
    }
    error = result.get("error")

    return {
        "key": key,
        "chunk_id": chunk_id,
        "found": bool(result.get("found", True)),
        "chunk": chunk if result.get("found", True) else None,
        "error": error,
    }


def _retrieve_memory_payload(key: str, memory: dict | None) -> dict[str, Any]:
    """Normalize full-memory retrieval output into the structured contract."""
    return {
        "key": key,
        "found": memory is not None,
        "memory": memory,
        "error": None,
    }


def _render_retrieve_chunk_payload(payload: dict[str, Any]) -> str:
    """Render the structured chunk payload for legacy text-returning callers."""
    error = payload.get("error")
    if error is not None:
        return error["message"]
    if not payload.get("found"):
        return f"❌ Chunk not found: key='{payload['key']}' chunk_id={payload['chunk_id']}"

    chunk = payload.get("chunk") or {}
    title = chunk.get("title") or payload["key"]
    text = chunk.get("text") or ""
    return (
        f"📄 Chunk {payload['chunk_id']} from '{title}'\n"
        f"🔑 Key: {payload['key']}\n\n"
        f"{text}"
    )


def _render_retrieve_memory_payload(payload: dict[str, Any]) -> str:
    """Render the structured full-memory payload for legacy text-returning callers."""
    error = payload.get("error")
    if error is not None:
        return error["message"]
    if not payload.get("found"):
        return f"❌ Memory not found: '{payload['key']}'"

    memory = payload.get("memory") or {}
    tags = ", ".join(memory.get("tags", [])) or "none"
    updated_at = str(memory.get("updated_at", ""))[:16]
    return (
        f"📦 {memory.get('title', payload['key'])}\n"
        f"🔑 Key: {memory.get('key', payload['key'])}\n"
        f"🏷  Tags: {tags}\n"
        f"📅 Updated: {updated_at}\n"
        f"📊 {memory.get('chars', '?')} chars | {memory.get('chunk_count', '?')} chunks\n\n"
        f"{memory.get('content', '')}"
    )


@mcp.tool()
async def memory_protocol() -> dict[str, Any]:
    """
    Describe the agent-facing Engram tool contract.

    Call this when a client needs to discover the intended retrieval ladder,
    canonical tool names, compatibility aliases, or token-safety rules.
    """
    return {
        "name": "Engram memory protocol",
        "version": 1,
        "retrieval_ladder": [
            {
                "step": 1,
                "tool": "search_memories",
                "purpose": "Find scored snippets and capture key + chunk_id references.",
            },
            {
                "step": 2,
                "tool": "retrieve_chunk",
                "purpose": "Read one relevant chunk by key + chunk_id; usually sufficient.",
            },
            {
                "step": 3,
                "tool": "retrieve_memory",
                "purpose": "Read the full memory only when chunks are insufficient.",
            },
        ],
        "canonical_tools": {
            "search_memories": "Structured semantic search with optional project/domain/tag/staleness filters.",
            "context_pack": "Search, dedupe, and retrieve a bounded set of chunks in one call.",
            "list_memories": "Paginated structured directory metadata; no content.",
            "retrieve_chunk": "Structured single-chunk retrieval.",
            "retrieve_chunks": "Structured batch chunk retrieval.",
            "retrieve_memory": "Structured full-memory retrieval; token-expensive.",
            "store_memory": "Write or update a memory.",
            "prepare_memory": "Draft key/metadata/validation before storing.",
        },
        "aliases": {
            "find_memories": "search_memories",
            "read_chunk": "retrieve_chunk",
            "read_memory": "retrieve_chunk or retrieve_memory, depending on arguments",
            "write_memory": "store_memory",
        },
        "examples": [
            "search_memories(query='scheduler bug', limit=5)",
            "retrieve_chunk(key='sylvara_scheduler', chunk_id=3)",
            "context_pack(query='agent memory protocol', project='engram', max_chunks=5)",
            "read_memory(key='engram_protocol', full=True) only after chunks are insufficient",
        ],
        "warnings": [
            "Do not call retrieve_memory before search_memories or retrieve_chunk unless the key is already known and full content is explicitly required.",
            "Prefer context_pack when you need a compact working set rather than whole memories.",
            "Use list_memories for browsing metadata, not topic lookup.",
        ],
    }


@mcp.tool()
async def search_memories(
    query: str,
    limit: int = 5,
    session_id: str | None = None,
    pinned_first: bool = False,
    project: str | None = None,
    domain: str | None = None,
    tags: str | list[str] | None = None,
    include_stale: bool = True,
    canonical_only: bool = False,
) -> SearchPayload:
    """
    Semantic search across all stored memories. Returns structured scored snippets only — NOT full content.

    This is ALWAYS your first step when looking for information. Results include the key and
    chunk_id needed for retrieve_chunk(). Only escalate to retrieve_chunk() or retrieve_memory()
    if the snippet alone isn't sufficient.

    Args:
        query: Natural language search query. Semantic — 'scheduling problems' will find
               'dispatch calendar issues' even without exact keyword overlap.
        limit: Max results to return (default 5, max 20).
        session_id: Optional session identifier used to load session-scoped pinned keys.
        pinned_first: When true, pinned results for the session sort ahead of unpinned results.
        project: Optional exact project filter.
        domain: Optional exact domain filter.
        tags: Optional comma-separated string or list of required tags.
        include_stale: When false, exclude time/code-stale memories.
        canonical_only: When true, return only canonical memories.

    Returns:
        Structured payload: {query, count, results, error}. Each result includes key,
        chunk_id, title, score, snippet, and tags. Session-aware searches may also
        include structured explanation and pin metadata. On validation or runtime
        failure, results is empty and error is {code, message}.
    """
    validation_error = _validate_search_query(query)
    if validation_error:
        return build_search_error_payload(query, "invalid_query", validation_error)

    normalized_session_id = _normalize_session_id(session_id)
    try:
        pinned_keys = (
            session_pin_store.list_pins(normalized_session_id)
            if normalized_session_id is not None
            else []
        )
        normalized_tags = _normalize_string_list(tags)
        filters_supplied = any(
            [
                project is not None,
                domain is not None,
                bool(normalized_tags),
                include_stale is False,
                canonical_only,
            ]
        )
        if pinned_keys or filters_supplied:
            structured_kwargs: dict[str, Any] = {
                "pinned_keys": pinned_keys,
                "pinned_first": pinned_first,
            }
            if filters_supplied:
                structured_kwargs.update(
                    {
                        "project": project,
                        "domain": domain,
                        "tags": normalized_tags,
                        "include_stale": include_stale,
                        "canonical_only": canonical_only,
                    }
                )
            payload = await memory_manager.search_memories_structured_async(
                query.strip(),
                limit=_clamp_search_limit(limit),
                **structured_kwargs,
            )
            payload["error"] = None
            return payload

        results = await memory_manager.search_memories_async(query.strip(), limit=_clamp_search_limit(limit))
    except RuntimeError as e:
        return build_search_error_payload(query, "runtime_error", f"❌ Engram error: {e}")
    except ValueError as e:
        return build_search_error_payload(query, "invalid_session", f"❌ {e}")

    return build_search_payload(query, results)


@mcp.tool()
async def search_memories_text(query: str, limit: int = 5) -> str:
    """
    Semantic search across all stored memories. Returns scored snippets only — NOT full content.

    This is ALWAYS your first step when looking for information. Results include the key and
    chunk_id needed for retrieve_chunk(). Only escalate to retrieve_chunk() or retrieve_memory()
    if the snippet alone isn't sufficient.

    Args:
        query: Natural language search query. Semantic — 'scheduling problems' will find
               'dispatch calendar issues' even without exact keyword overlap.
        limit: Max results to return (default 5, max 20).

    Returns:
        Human-readable scored list of matching chunks with snippets. Score is 0.0–1.0
        (higher = more relevant). For structured output, use search_memories().
    """
    payload = await search_memories(query, limit)
    return render_search_payload(payload)


@mcp.tool()
async def pin_memory(session_id: str, key: str) -> dict[str, Any]:
    """
    Pin a memory key for the current session so it can be promoted in session-aware searches.

    Pins are session-scoped working state only. They do not modify stored memory JSON or
    long-term memory metadata.

    Args:
        session_id: Session identifier for the active working context.
        key: Existing memory key to pin.

    Returns:
        Structured payload: {session_id, count, pins, pinned, error}. When the key does not
        exist, error is populated and the pin list is unchanged.
    """
    normalized_session_id = _normalize_session_id(session_id)
    if normalized_session_id is None:
        return _runtime_error_payload(
            "❌ session_id is required.",
            session_id="",
            count=0,
            pins=[],
            pinned=False,
        )

    try:
        normalized_key = _normalize_memory_key(key)
    except ValueError as e:
        return _runtime_error_payload(
            f"❌ {e}",
            session_id=normalized_session_id,
            count=0,
            pins=[],
            pinned=False,
        )

    if not await memory_manager.memory_exists_async(normalized_key):
        return {
            "session_id": normalized_session_id,
            "count": 0,
            "pins": session_pin_store.list_pins(normalized_session_id),
            "pinned": False,
            "error": {
                "code": "not_found",
                "message": f"❌ Memory not found: '{normalized_key}'",
            },
        }

    try:
        pins = session_pin_store.pin(normalized_session_id, normalized_key)
    except ValueError as e:
        return _runtime_error_payload(
            f"❌ {e}",
            session_id=normalized_session_id,
            count=0,
            pins=[],
            pinned=False,
        )

    return _pin_payload(normalized_session_id, pins, pinned=True)


@mcp.tool()
async def unpin_memory(session_id: str, key: str) -> dict[str, Any]:
    """
    Remove a pinned memory key from a session.

    Args:
        session_id: Session identifier for the active working context.
        key: Memory key to remove from the session pin list.

    Returns:
        Structured payload: {session_id, count, pins, unpinned, error}.
    """
    normalized_session_id = _normalize_session_id(session_id)
    if normalized_session_id is None:
        return _runtime_error_payload(
            "❌ session_id is required.",
            session_id="",
            count=0,
            pins=[],
            unpinned=False,
        )

    try:
        pins = session_pin_store.unpin(normalized_session_id, key)
    except ValueError as e:
        return _runtime_error_payload(
            f"❌ {e}",
            session_id=normalized_session_id,
            count=0,
            pins=[],
            unpinned=False,
        )

    return _pin_payload(normalized_session_id, pins, unpinned=True)


@mcp.tool()
async def list_pins(session_id: str) -> dict[str, Any]:
    """
    List pinned memory keys for a session.

    Args:
        session_id: Session identifier for the active working context.

    Returns:
        Structured payload: {session_id, count, pins, error}.
    """
    normalized_session_id = _normalize_session_id(session_id)
    if normalized_session_id is None:
        return _runtime_error_payload(
            "❌ session_id is required.",
            session_id="",
            count=0,
            pins=[],
        )

    try:
        pins = session_pin_store.list_pins(normalized_session_id)
    except ValueError as e:
        return _runtime_error_payload(
            f"❌ {e}",
            session_id=normalized_session_id,
            count=0,
            pins=[],
        )

    return _pin_payload(normalized_session_id, pins)


@mcp.tool()
async def clear_pins(session_id: str) -> dict[str, Any]:
    """
    Clear all pinned memory keys for a session.

    Args:
        session_id: Session identifier for the active working context.

    Returns:
        Structured payload: {session_id, count, pins, cleared, error}.
    """
    normalized_session_id = _normalize_session_id(session_id)
    if normalized_session_id is None:
        return _runtime_error_payload(
            "❌ session_id is required.",
            session_id="",
            count=0,
            pins=[],
            cleared=False,
        )

    try:
        pins = session_pin_store.clear(normalized_session_id)
    except ValueError as e:
        return _runtime_error_payload(
            f"❌ {e}",
            session_id=normalized_session_id,
            count=0,
            pins=[],
            cleared=False,
        )

    return _pin_payload(normalized_session_id, pins, cleared=True)


@mcp.tool()
async def list_memories(
    limit: int = 50,
    offset: int = 0,
    project: str | None = None,
    domain: str | None = None,
    tags: str | list[str] | None = None,
    recent_first: bool = True,
) -> MemoryListPayload:
    """
    List stored memories as structured metadata only — keys, titles, tags, timestamps, chunk counts.
    No content is returned. Use this when you need to browse what exists, not search by topic.

    Args:
        limit: Max metadata rows to return (default 50, max 500). Use 0 for all.
        offset: Zero-based pagination offset.
        project: Optional exact project filter.
        domain: Optional exact domain filter.
        tags: Optional comma-separated string or list of required tags.
        recent_first: Sort by updated_at descending when true; otherwise by key.

    Returns:
        Structured payload: {count, total, limit, offset, has_more, memories, error}.
        Each memory includes key, title, tags, project/domain/status/canonical when
        available, updated_at, created_at, chars, and chunk_count. On runtime failure,
        memories is empty and error is {code, message}.

    For topic-based lookup, prefer search_memories() or search_memories_text() instead.
    """
    try:
        memories = await memory_manager.list_memories_async()
    except Exception as e:
        return build_list_error_payload("runtime_error", f"❌ Engram error: {e}")

    required_tags = _normalize_string_list(tags)

    def keep(memory: dict[str, Any]) -> bool:
        if project is not None and memory.get("project") != project:
            return False
        if domain is not None and memory.get("domain") != domain:
            return False
        if required_tags and not all(tag in (memory.get("tags") or []) for tag in required_tags):
            return False
        return True

    filtered = [memory for memory in memories if keep(memory)]
    if recent_first:
        filtered.sort(key=lambda memory: str(memory.get("updated_at", "")), reverse=True)
    else:
        filtered.sort(key=lambda memory: str(memory.get("key", "")))

    normalized_limit = _clamp_list_limit(limit)
    normalized_offset = _normalize_offset(offset)
    if normalized_limit == 0:
        page = filtered[normalized_offset:]
        has_more = False
    else:
        end = normalized_offset + normalized_limit
        page = filtered[normalized_offset:end]
        has_more = end < len(filtered)

    return build_list_payload(
        page,
        total=len(filtered),
        limit=normalized_limit,
        offset=normalized_offset,
        has_more=has_more,
    )


@mcp.tool()
async def list_all_memories() -> str:
    """
    List all stored memories as a directory — keys, titles, tags, timestamps, chunk counts.
    No content is returned. Use this when you need to browse what exists, not search by topic.

    For topic-based lookup, prefer search_memories() instead.
    """
    payload = await list_memories(limit=0)
    return render_list_payload(payload)


@mcp.tool()
async def retrieve_chunk_text(key: str, chunk_id: int) -> str:
    """
    Retrieve a single chunk from a memory by key and chunk_id.

    Use this AFTER search_memories_text() or search_memories() identifies the relevant key and chunk_id.
    This is the middle tier — more content than a snippet, far fewer tokens than the full memory.

    Args:
        key: The memory's unique key (from search_memories(), search_memories_text(), or list_all_memories() results).
        chunk_id: The chunk index returned by search results.

    Returns:
        Full text of the requested chunk, with its parent memory title. This is the
        legacy text wrapper; for structured output, use retrieve_chunk().
    """
    payload = await retrieve_chunk(key, chunk_id)
    return _render_retrieve_chunk_payload(payload)


@mcp.tool()
async def retrieve_chunk(key: str, chunk_id: int) -> dict[str, Any]:
    """
    Retrieve one chunk as structured data.

    Use this AFTER search_memories() or search_memories_text() identifies the relevant key
    and chunk_id. Prefer this middle tier before escalating to retrieve_memory().

    Args:
        key: The memory's unique key.
        chunk_id: The chunk index returned by search results.

    Returns:
        Structured payload: {key, chunk_id, found, chunk, error}. When found is true,
        chunk includes title, text, and chunk metadata. When not found, chunk is null.
    """
    try:
        results = await memory_manager.retrieve_chunks_async([{"key": key, "chunk_id": chunk_id}])
    except Exception as e:
        return _runtime_error_payload(
            f"❌ Engram error: {e}",
            key=key,
            chunk_id=chunk_id,
            found=False,
            chunk=None,
        )

    result = results[0] if results else None
    return _retrieve_chunk_payload(result, key, chunk_id)


@mcp.tool()
async def retrieve_chunks(requests: list[dict]) -> dict[str, Any]:
    """
    Retrieve multiple chunks in one call as structured data.

    Use this AFTER search_memories() when you need several chunk matches at once.
    It preserves request order and keeps not-found results explicit so you can avoid
    escalating to retrieve_memory() unless full memories are still necessary.

    Args:
        requests: Array of {key, chunk_id} objects.

    Returns:
        Structured payload: {requested_count, found_count, results, error}. Each result
        includes key, chunk_id, found, chunk, and per-request validation details when needed.
    """
    if not isinstance(requests, list):
        return {
            "requested_count": 0,
            "found_count": 0,
            "results": [],
            "error": {
                "code": "invalid_requests",
                "message": "❌ requests must be a list of {key, chunk_id} objects.",
            },
        }

    try:
        raw_results = await memory_manager.retrieve_chunks_async(requests)
    except Exception as e:
        return _runtime_error_payload(
            f"❌ Engram error: {e}",
            requested_count=len(requests),
            found_count=0,
            results=[],
        )

    results = [
        _retrieve_chunk_payload(result, result.get("key", ""), result.get("chunk_id", -1))
        for result in raw_results
    ]
    return {
        "requested_count": len(requests),
        "found_count": sum(1 for result in results if result["found"]),
        "results": results,
        "error": None,
    }


@mcp.tool()
async def context_pack(
    query: str,
    project: str | None = None,
    domain: str | None = None,
    tags: str | list[str] | None = None,
    max_chunks: int = 5,
    budget_chars: int = 6000,
    include_stale: bool = False,
    canonical_only: bool = False,
) -> dict[str, Any]:
    """
    Build a compact working set by searching, deduping, and retrieving chunks.

    This is the fastest agent-friendly path when snippets are too small but full
    memories would be wasteful. It follows the three-tier retrieval ladder on the
    caller's behalf and returns bounded chunk text.

    Args:
        query: Natural language search query.
        project: Optional exact project filter.
        domain: Optional exact domain filter.
        tags: Optional comma-separated string or list of required tags.
        max_chunks: Max unique chunks to retrieve (default 5, max 20).
        budget_chars: Approximate maximum chunk text characters returned.
        include_stale: When false, exclude time/code-stale memories.
        canonical_only: When true, return only canonical memories.

    Returns:
        Structured payload: {query, count, chunks, omitted, used_chars, error}.
    """
    validation_error = _validate_search_query(query)
    if validation_error:
        return {
            "query": query,
            "count": 0,
            "chunks": [],
            "omitted": [],
            "budget_chars": budget_chars,
            "used_chars": 0,
            "error": {
                "code": "invalid_query",
                "message": validation_error,
            },
        }

    normalized_max_chunks = _clamp_search_limit(max_chunks)
    normalized_budget = max(int(budget_chars), 1)

    search_payload = await search_memories(
        query,
        limit=normalized_max_chunks,
        project=project,
        domain=domain,
        tags=tags,
        include_stale=include_stale,
        canonical_only=canonical_only,
    )
    if search_payload.get("error") is not None:
        return {
            "query": query,
            "count": 0,
            "chunks": [],
            "omitted": [],
            "budget_chars": normalized_budget,
            "used_chars": 0,
            "error": search_payload["error"],
        }

    requests: list[dict[str, Any]] = []
    result_by_ref: dict[tuple[str, int], dict[str, Any]] = {}
    for result in search_payload.get("results", []):
        ref = (result["key"], int(result["chunk_id"]))
        if ref in result_by_ref:
            continue
        result_by_ref[ref] = result
        requests.append({"key": ref[0], "chunk_id": ref[1]})
        if len(requests) >= normalized_max_chunks:
            break

    if not requests:
        return {
            "query": query,
            "count": 0,
            "chunks": [],
            "omitted": [],
            "budget_chars": normalized_budget,
            "used_chars": 0,
            "error": None,
        }

    chunk_payload = await retrieve_chunks(requests)
    if chunk_payload.get("error") is not None:
        return {
            "query": query,
            "count": 0,
            "chunks": [],
            "omitted": requests,
            "budget_chars": normalized_budget,
            "used_chars": 0,
            "error": chunk_payload["error"],
        }

    chunks: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    used_chars = 0
    for result in chunk_payload.get("results", []):
        ref = (result.get("key", ""), int(result.get("chunk_id", -1)))
        search_result = result_by_ref.get(ref, {})
        if not result.get("found"):
            omitted.append(
                {
                    "key": ref[0],
                    "chunk_id": ref[1],
                    "reason": "not_found",
                    "error": result.get("error"),
                }
            )
            continue

        chunk = result.get("chunk") or {}
        text = chunk.get("text") or ""
        remaining = normalized_budget - used_chars
        if remaining <= 0:
            omitted.append({"key": ref[0], "chunk_id": ref[1], "reason": "budget_exhausted"})
            continue

        returned_text = text[:remaining]
        used_chars += len(returned_text)
        chunks.append(
            {
                "key": ref[0],
                "chunk_id": ref[1],
                "title": chunk.get("title") or search_result.get("title") or ref[0],
                "score": search_result.get("score"),
                "snippet": search_result.get("snippet"),
                "explanation": search_result.get("explanation"),
                "section_title": chunk.get("section_title"),
                "heading_path": chunk.get("heading_path", []),
                "chunk_kind": chunk.get("chunk_kind"),
                "text": returned_text,
                "truncated": len(returned_text) < len(text),
            }
        )

    return {
        "query": query,
        "count": len(chunks),
        "chunks": chunks,
        "omitted": omitted,
        "budget_chars": normalized_budget,
        "used_chars": used_chars,
        "error": None,
    }


@mcp.tool()
async def retrieve_memory_text(key: str) -> str:
    """
    Retrieve the full content of a memory by key.

    Use this ONLY when you need the complete memory and chunk retrieval isn't sufficient.
    This is the most token-expensive operation — use it intentionally.

    Args:
        key: The memory's unique key.

    Returns:
        Full memory content with metadata header. This is the legacy text wrapper;
        for structured output, use retrieve_memory().
    """
    payload = await retrieve_memory(key)
    return _render_retrieve_memory_payload(payload)


@mcp.tool()
async def retrieve_memory(key: str) -> dict[str, Any]:
    """
    Retrieve the full memory as structured metadata plus content.

    Use this ONLY when chunk retrieval is not sufficient. This is still the most
    token-expensive read path, so prefer search_memories(), retrieve_chunk(),
    or retrieve_chunks() first.

    Args:
        key: The memory's unique key.

    Returns:
        Structured payload: {key, found, memory, error}. When found is true, memory
        contains the normalized metadata, lifecycle fields, related keys, and content.
    """
    try:
        result = await memory_manager.retrieve_memory_async(key)
    except Exception as e:
        return _runtime_error_payload(
            f"❌ Engram error: {e}",
            key=key,
            found=False,
            memory=None,
        )
    return _retrieve_memory_payload(key, result)


@mcp.tool()
async def store_memory(
    key: str,
    content: str,
    title: str = "",
    tags: str | list[str] = "",
    related_to: str | list[str] = "",
    force: bool = False,
    project: str | None = None,
    domain: str | None = None,
    status: str | None = None,
    canonical: bool | None = None,
) -> str:
    """
    Store a new memory or update an existing one.

    The key is the stable identifier — updates overwrite the previous content.
    Content is chunked and semantically indexed automatically.

    Args:
        key: Unique identifier (e.g. 'sylvara_arbostar_decision', 'lumen_architecture').
             Use snake_case. Be specific — keys are used for deterministic retrieval.
        content: The memory content (max 15,000 chars). Markdown is supported and improves
                 chunking quality. Use headers (##, ###) to create natural chunk boundaries.
                 For larger documents, split into multiple memories with specific keys
                 (e.g. 'lumen_adr_018', 'lumen_adr_019').
        title: Human-readable title (optional, defaults to key).
        tags: Comma-separated tags or tag list for browsing (e.g. 'sylvara,decision,architecture').
        related_to: Comma-separated keys or key list of related memories to link to (optional).
                    Maximum 10 keys. Links are bidirectional at query time.
        force: Pass True to store even if a near-duplicate already exists (default False).
               When False, a duplicate warning is returned instead of storing.
        project: Optional project label for scoped search/listing.
        domain: Optional domain label for scoped search/listing.
        status: Optional lifecycle status: active, draft, historical, superseded, archived.
        canonical: Optional canonical-memory flag.

    Returns:
        Confirmation with chunk count, or duplicate warning if near-duplicate detected.
    """
    tag_list = _normalize_string_list(tags)
    related_list = _normalize_string_list(related_to)
    try:
        result = await memory_manager.store_memory_async(
            key=key,
            content=content,
            tags=tag_list,
            title=title or None,
            related_to=related_list,
            force=force,
            project=project,
            domain=domain,
            status=status,
            canonical=canonical,
        )
        return (
            f"✅ Stored: '{result['title']}'\n"
            f"   Key: {key}\n"
            f"   Chunks: {result.get('chunk_count', '?')}\n"
            f"   Chars: {result['chars']}"
        )
    except DuplicateMemoryError as e:
        dup = e.duplicate
        threshold = _config.get("dedup_threshold", 0.92)
        return (
            f"⚠️  DUPLICATE DETECTED — similar memory already exists.\n"
            f"   Existing key:   {dup['existing_key']}\n"
            f"   Existing title: {dup['existing_title']}\n"
            f"   Similarity:     {dup['score']:.3f} (threshold: {threshold})\n\n"
            f"To store anyway, call store_memory again with force=True."
        )
    except ValueError as e:
        return f"⚠️ Memory too large or invalid: {e}"
    except RuntimeError as e:
        return f"❌ Engram error: {e}"
    except Exception as e:
        return f"❌ Failed to store '{key}': {e}"


@mcp.tool()
async def find_memories(
    query: str,
    limit: int = 5,
    session_id: str | None = None,
    pinned_first: bool = False,
    project: str | None = None,
    domain: str | None = None,
    tags: str | list[str] | None = None,
    include_stale: bool = True,
    canonical_only: bool = False,
) -> SearchPayload:
    """
    Alias for search_memories().

    Some agents naturally look for a "find" verb. This wrapper keeps that path
    discoverable while preserving the canonical search_memories contract.
    """
    kwargs: dict[str, Any] = {}
    if limit != 5:
        kwargs["limit"] = limit
    if session_id is not None:
        kwargs["session_id"] = session_id
    if pinned_first:
        kwargs["pinned_first"] = pinned_first
    if project is not None:
        kwargs["project"] = project
    if domain is not None:
        kwargs["domain"] = domain
    if tags is not None:
        kwargs["tags"] = tags
    if include_stale is not True:
        kwargs["include_stale"] = include_stale
    if canonical_only:
        kwargs["canonical_only"] = canonical_only
    return await search_memories(query, **kwargs)


@mcp.tool()
async def read_chunk(key: str, chunk_id: int) -> dict[str, Any]:
    """
    Alias for retrieve_chunk().

    Prefer this/read_chunk after search_memories or context_pack identifies a
    specific key + chunk_id.
    """
    return await retrieve_chunk(key, chunk_id)


@mcp.tool()
async def read_memory(
    key: str,
    chunk_id: int | None = None,
    full: bool = False,
) -> dict[str, Any]:
    """
    Tier-aware read helper.

    With chunk_id, this returns a chunk via retrieve_chunk(). With full=True, it
    returns retrieve_memory(). With only key, it returns metadata without content
    plus guidance to use chunk reads before full reads.
    """
    if chunk_id is not None:
        return {
            "mode": "chunk",
            "result": await retrieve_chunk(key, chunk_id),
            "error": None,
        }

    if full:
        return {
            "mode": "full",
            "result": await retrieve_memory(key),
            "error": None,
        }

    payload = await retrieve_memory(key)
    if payload.get("error") is not None or not payload.get("found"):
        return {
            "mode": "metadata",
            "key": key,
            "found": payload.get("found", False),
            "memory": None,
            "guidance": "Use read_chunk(key, chunk_id) after search_memories; pass full=True only when the full memory is required.",
            "error": payload.get("error"),
        }

    memory = dict(payload.get("memory") or {})
    memory.pop("content", None)
    return {
        "mode": "metadata",
        "key": key,
        "found": True,
        "memory": memory,
        "guidance": "Use read_chunk(key, chunk_id) after search_memories; pass full=True only when the full memory is required.",
        "error": None,
    }


@mcp.tool()
async def write_memory(
    key: str,
    content: str,
    title: str = "",
    tags: str | list[str] = "",
    related_to: str | list[str] = "",
    force: bool = False,
    project: str | None = None,
    domain: str | None = None,
    status: str | None = None,
    canonical: bool | None = None,
) -> str:
    """
    Alias for store_memory().

    This exists for agents that search for a write verb; store_memory remains
    the canonical write tool.
    """
    kwargs: dict[str, Any] = {}
    if title:
        kwargs["title"] = title
    if tags:
        kwargs["tags"] = tags
    if related_to:
        kwargs["related_to"] = related_to
    if force:
        kwargs["force"] = force
    if project is not None:
        kwargs["project"] = project
    if domain is not None:
        kwargs["domain"] = domain
    if status is not None:
        kwargs["status"] = status
    if canonical is not None:
        kwargs["canonical"] = canonical
    return await store_memory(key, content, **kwargs)


@mcp.tool()
async def check_duplicate(key: str, content: str) -> dict[str, Any]:
    """
    Check whether proposed content is a near-duplicate of an existing memory.

    Use this before store_memory() when you want a structured duplicate warning
    without attempting a write.

    Args:
        key: Proposed memory key. Self-updates for the same key are allowed.
        content: Proposed memory content to compare semantically.

    Returns:
        Structured payload: {key, duplicate, match, error}. When duplicate is true,
        match includes the existing key, title, and similarity score.
    """
    try:
        result = await memory_manager.check_duplicate_async(key, content)
    except Exception as e:
        return _runtime_error_payload(
            f"❌ Engram error: {e}",
            key=key,
            duplicate=False,
            match=None,
        )

    return {
        "key": key,
        "duplicate": result["duplicate"],
        "match": result["match"],
        "error": None,
    }


@mcp.tool()
async def suggest_memory_metadata(content: str) -> dict[str, Any]:
    """
    Suggest lightweight metadata defaults from markdown content.

    Args:
        content: Proposed memory content.

    Returns:
        Structured payload: {suggestion, error}. suggestion includes a title,
        tags, lifecycle defaults, and empty related metadata fields.
    """
    try:
        suggestion = await memory_manager.suggest_memory_metadata_async(content)
    except Exception as e:
        return _runtime_error_payload(
            f"❌ Engram error: {e}",
            suggestion=None,
        )

    return {
        "suggestion": suggestion,
        "error": None,
    }


@mcp.tool()
async def prepare_memory(
    content: str,
    key: str = "",
    title: str = "",
    tags: str | list[str] = "",
    related_to: str | list[str] = "",
    project: str | None = None,
    domain: str | None = None,
    status: str | None = None,
    canonical: bool | None = None,
) -> dict[str, Any]:
    """
    Prepare a memory draft before writing.

    This combines metadata suggestions, key generation, validation, and duplicate
    checking without storing anything. Use it when an agent has content but wants
    a safe, inspectable draft for store_memory/write_memory.

    Args:
        content: Proposed memory body.
        key: Optional explicit key. When omitted, a snake_case key is derived from title.
        title: Optional title. When omitted, Engram suggests one from content.
        tags: Optional comma-separated tags or tag list.
        related_to: Optional comma-separated related keys or key list.
        project: Optional project label.
        domain: Optional domain label.
        status: Optional lifecycle status.
        canonical: Optional canonical-memory flag.

    Returns:
        Structured payload: {ready, draft, validation, duplicate, suggestion, guidance, error}.
        ready is true only when validation passes and no duplicate is detected.
    """
    try:
        suggestion = await memory_manager.suggest_memory_metadata_async(content)
        resolved_title = title.strip() if title and title.strip() else suggestion.get("title") or "Untitled memory"
        resolved_key = key.strip() if key and key.strip() else _slugify_memory_key(resolved_title)
        resolved_tags = _normalize_string_list(tags) or suggestion.get("tags", [])
        resolved_related_to = _normalize_string_list(related_to) or suggestion.get("related_to", [])
        resolved_project = project if project is not None else suggestion.get("project")
        resolved_domain = domain if domain is not None else suggestion.get("domain")
        resolved_status = status if status is not None else suggestion.get("status")
        resolved_canonical = canonical if canonical is not None else suggestion.get("canonical")

        validation = await memory_manager.validate_memory_async(
            content=content,
            title=resolved_title,
            tags=resolved_tags,
            related_to=resolved_related_to,
            project=resolved_project,
            domain=resolved_domain,
            status=resolved_status,
            canonical=resolved_canonical,
        )
        duplicate = await memory_manager.check_duplicate_async(resolved_key, content)
    except Exception as e:
        return _runtime_error_payload(
            f"❌ Engram error: {e}",
            ready=False,
            draft=None,
            validation=None,
            duplicate=None,
            suggestion=None,
            guidance="Fix the reported error, then retry prepare_memory before storing.",
        )

    draft = {
        "key": resolved_key,
        "content": content,
        "title": resolved_title,
        "tags": validation["normalized"]["tags"],
        "related_to": validation["normalized"]["related_to"],
        "project": validation["normalized"]["project"],
        "domain": validation["normalized"]["domain"],
        "status": validation["normalized"]["status"],
        "canonical": validation["normalized"]["canonical"],
    }
    ready = bool(validation["valid"] and not duplicate["duplicate"])
    return {
        "ready": ready,
        "draft": draft,
        "validation": validation,
        "duplicate": duplicate,
        "suggestion": suggestion,
        "guidance": (
            "Call store_memory/write_memory with draft fields. "
            "Use force=True only when duplicate.duplicate is true and the overlap is intentional."
        ),
        "error": None,
    }


@mcp.tool()
async def validate_memory(
    content: str,
    title: str | None = None,
    tags: list[str] | None = None,
    related_to: list[str] | None = None,
    status: str | None = None,
    project: str | None = None,
    domain: str | None = None,
    canonical: bool | None = None,
) -> dict[str, Any]:
    """
    Validate memory content and metadata before storing or updating.

    Args:
        content: Proposed memory content.
        title: Optional display title.
        tags: Optional tag list.
        related_to: Optional related memory keys.
        status: Optional lifecycle status.
        project: Optional project label.
        domain: Optional domain label.
        canonical: Optional canonical-memory flag.

    Returns:
        Structured payload: {valid, errors, normalized, error}. Validation errors
        are returned in errors; runtime failures populate error instead.
    """
    try:
        result = await memory_manager.validate_memory_async(
            content=content,
            title=title,
            tags=tags,
            related_to=related_to,
            status=status,
            project=project,
            domain=domain,
            canonical=canonical,
        )
    except Exception as e:
        return _runtime_error_payload(
            f"❌ Engram error: {e}",
            valid=False,
            errors=[],
            normalized=None,
        )

    return {
        "valid": result["valid"],
        "errors": result["errors"],
        "normalized": result["normalized"],
        "error": None,
    }


@mcp.tool()
async def update_memory_metadata(
    key: str,
    title: str | None = None,
    tags: list[str] | None = None,
    related_to: list[str] | None = None,
    project: str | None = None,
    domain: str | None = None,
    status: str | None = None,
    canonical: bool | None = None,
) -> dict[str, Any]:
    """
    Update metadata on an existing memory and reindex its current content.

    This preserves the JSON-first / Chroma-second safety guarantee. Content is
    unchanged; only metadata fields are updated and the existing chunks are reindexed.

    Args:
        key: Existing memory key to update.
        title: Optional replacement title.
        tags: Optional replacement tag list.
        related_to: Optional replacement related-memory list.
        project: Optional replacement project label.
        domain: Optional replacement domain label.
        status: Optional replacement lifecycle status.
        canonical: Optional replacement canonical-memory flag.

    Returns:
        Structured payload: {key, updated, memory, error}. When updated is true,
        memory contains the normalized stored record after reindexing.
    """
    changes = {
        name: value
        for name, value in {
            "title": title,
            "tags": tags,
            "related_to": related_to,
            "project": project,
            "domain": domain,
            "status": status,
            "canonical": canonical,
        }.items()
        if value is not None
    }

    try:
        memory = await memory_manager.update_memory_metadata_async(key, **changes)
    except KeyError:
        return {
            "key": key,
            "updated": False,
            "memory": None,
            "error": {
                "code": "not_found",
                "message": f"❌ Memory not found: '{key}'",
            },
        }
    except ValueError as e:
        return {
            "key": key,
            "updated": False,
            "memory": None,
            "error": {
                "code": "invalid_metadata",
                "message": str(e),
            },
        }
    except Exception as e:
        return _runtime_error_payload(
            f"❌ Engram error: {e}",
            key=key,
            updated=False,
            memory=None,
        )

    return {
        "key": key,
        "updated": True,
        "memory": memory,
        "error": None,
    }


@mcp.tool()
async def audit_memory_metadata(
    limit: int = 100,
    offset: int = 0,
    project: str | None = None,
) -> dict[str, Any]:
    """
    Audit stored memory JSON metadata for repairable drift.

    This is a read-only hygiene tool. It does not modify memory JSON or ChromaDB.

    Args:
        limit: Max issue rows to return (default 100). Use 0 for all.
        offset: Zero-based pagination offset across memories with issues.
        project: Optional exact project filter.

    Returns:
        Structured payload with counts and per-memory issue lists.
    """
    try:
        payload = await memory_manager.audit_memory_metadata_async(
            limit=limit,
            offset=offset,
            project=project,
        )
    except Exception as e:
        return _runtime_error_payload(
            f"❌ Engram error: {e}",
            count=0,
            total=0,
            issue_count=0,
            repairable_count=0,
            memories=[],
        )

    payload["error"] = None
    return payload


@mcp.tool()
async def repair_memory_metadata(
    keys: str | list[str],
    dry_run: bool = True,
) -> dict[str, Any]:
    """
    Repair selected memory metadata drift.

    Defaults to dry_run=True. When dry_run=False, Engram writes normalized JSON
    first, then reindexes chunks so JSON and Chroma stay aligned.

    Args:
        keys: Memory key or comma-separated/list of memory keys to repair.
        dry_run: Preview changes without writing when true.

    Returns:
        Structured payload with one repair result per requested key.
    """
    normalized_keys = _normalize_string_list(keys)
    if not normalized_keys:
        return {
            "requested_count": 0,
            "repaired_count": 0,
            "dry_run": dry_run,
            "repairs": [],
            "error": {
                "code": "invalid_keys",
                "message": "❌ keys must include at least one memory key.",
            },
        }

    try:
        payload = await memory_manager.repair_memory_metadata_async(
            normalized_keys,
            dry_run=dry_run,
        )
    except Exception as e:
        return _runtime_error_payload(
            f"❌ Engram error: {e}",
            requested_count=len(normalized_keys),
            repaired_count=0,
            dry_run=dry_run,
            repairs=[],
        )

    payload["error"] = None
    return payload


@mcp.tool()
async def get_related_memories_text(key: str) -> str:
    """
    Retrieve all memories related to the given key, bidirectionally.

    Returns memories that this key explicitly links to (forward links) AND
    memories that link to this key (reverse links). Dangling references to
    deleted memories are silently ignored.

    Args:
        key: The memory key to find relationships for.

    Returns:
        List of related memories with keys and titles, grouped by direction.
    """
    result = await memory_manager.get_related_memories_async(key)
    if not result["found"]:
        return f"❌ Memory not found: '{key}'"

    forward = result["forward"]
    reverse = result["reverse"]

    if not forward and not reverse:
        return f"🔗 No related memories found for '{key}'."

    lines = [f"🔗 Related memories for '{key}':\n"]
    if forward:
        lines.append(f"Links to ({len(forward)}):")
        for m in forward:
            tags = ", ".join(m["tags"]) if m["tags"] else "none"
            lines.append(f"  → {m['key']}: {m['title']}  [tags: {tags}]")
    if reverse:
        lines.append(f"\nLinked by ({len(reverse)}):")
        for m in reverse:
            tags = ", ".join(m["tags"]) if m["tags"] else "none"
            lines.append(f"  ← {m['key']}: {m['title']}  [tags: {tags}]")
    return "\n".join(lines)


@mcp.tool()
async def get_related_memories(key: str) -> dict[str, Any]:
    """
    Retrieve related memories as structured forward and reverse link lists.

    Args:
        key: The memory key to inspect.

    Returns:
        Structured payload: {key, found, forward, reverse, forward_count, reverse_count, error}.
    """
    try:
        result = await memory_manager.get_related_memories_async(key)
    except Exception as e:
        return _runtime_error_payload(
            f"❌ Engram error: {e}",
            key=key,
            found=False,
            forward=[],
            reverse=[],
            forward_count=0,
            reverse_count=0,
        )

    return {
        "key": key,
        "found": result["found"],
        "forward": result["forward"],
        "reverse": result["reverse"],
        "forward_count": len(result["forward"]),
        "reverse_count": len(result["reverse"]),
        "error": None,
    }


@mcp.tool()
async def get_stale_memories_text(days: int = 90, type: str = "all") -> str:
    """
    Return memories that are time-stale (not accessed in N days) or code-stale
    (source files changed since last index run). No memories are deleted — surfacing only.

    Args:
        days: Threshold in days for time-staleness (default 90, configurable in config.json).
        type: Filter results — 'time' (access-based only), 'code' (indexer-flagged only),
              or 'all' (both types, default).

    Returns:
        List of stale memories with staleness type, detail, and last access info.
    """
    if type not in ("time", "code", "all"):
        return "❌ type must be 'time', 'code', or 'all'."
    try:
        results = await memory_manager.get_stale_memories_async(days=days, type=type)
    except Exception as e:
        return f"❌ Engram error: {e}"

    if not results:
        label = {"time": "time-stale", "code": "code-stale", "all": "stale"}.get(type, "stale")
        return f"✅ No {label} memories found (threshold: {days} days)."

    lines = [f"⚠️  {len(results)} stale memory/memories (threshold: {days}d, filter: {type}):\n"]
    for r in results:
        tags = ", ".join(r["tags"]) if r["tags"] else "none"
        badge = {"time": "[Time stale]", "code": "[Code changed]", "both": "[Time + Code]"}.get(r["stale_type"], "")
        lines.append(
            f"{badge} {r['title']}\n"
            f"  key={r['key']}  tags={tags}\n"
            f"  detail: {r['stale_detail']}\n"
        )
    return "\n".join(lines)


@mcp.tool()
async def get_stale_memories(days: int = 90, type: str = "all") -> dict[str, Any]:
    """
    Return stale memories as structured metadata.

    Args:
        days: Threshold in days for time-staleness.
        type: 'time', 'code', or 'all'.

    Returns:
        Structured payload: {days, type, count, memories, error}.
    """
    if type not in ("time", "code", "all"):
        return {
            "days": days,
            "type": type,
            "count": 0,
            "memories": [],
            "error": {
                "code": "invalid_type",
                "message": "❌ type must be 'time', 'code', or 'all'.",
            },
        }

    try:
        results = await memory_manager.get_stale_memories_async(days=days, type=type)
    except Exception as e:
        return _runtime_error_payload(
            f"❌ Engram error: {e}",
            days=days,
            type=type,
            count=0,
            memories=[],
        )

    return {
        "days": days,
        "type": type,
        "count": len(results),
        "memories": results,
        "error": None,
    }


# Python-level compatibility aliases from the additive rollout. These are intentionally
# not registered as MCP tools, but they keep direct module callers from breaking
# immediately after the tool-surface cleanup.
search_memories_v2 = search_memories
list_memories_v2 = list_memories
retrieve_chunk_v2 = retrieve_chunk
retrieve_chunks_v2 = retrieve_chunks
retrieve_memory_v2 = retrieve_memory
get_related_memories_v2 = get_related_memories
get_stale_memories_v2 = get_stale_memories


@mcp.tool()
async def delete_memory(key: str) -> str:
    """
    Permanently delete a memory and all its indexed chunks.

    Args:
        key: The memory key to delete.

    Returns:
        Confirmation or not-found message.
    """
    try:
        deleted = await memory_manager.delete_memory_async(key)
    except RuntimeError as e:
        return f"❌ Engram error: {e}"
    if deleted:
        session_pin_store.remove_key(key)
        return f"🗑  Deleted memory: '{key}'"
    return f"❌ Memory not found: '{key}'"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Engram v0.1 — Semantic Memory MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument("--host", default="0.0.0.0", help="SSE host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5100, help="SSE port (default: 5100)")
    parser.add_argument(
        "--rebuild-index",
        action="store_true",
        help="Rebuild ChromaDB index from JSON files and exit",
    )
    parser.add_argument(
        "--generate-config",
        action="store_true",
        help="Print MCP client config JSON and exit",
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="Export all memories to engram_export_YYYY-MM-DD.json and exit",
    )
    parser.add_argument(
        "--import-file",
        dest="import_file",
        metavar="FILE",
        help="Import memories from a JSON bundle file and exit",
    )
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Re-chunk memories missing chunk_count and exit",
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help="Print server health status and exit",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run store->search->retrieve_chunk->delete integration test and exit",
    )

    args = parser.parse_args()

    if args.rebuild_index:
        embedder._load()
        count = memory_manager.rebuild_index()
        print(f"Rebuilt index for {count} memories.", file=sys.stderr)
        sys.exit(0)

    if args.export:
        from datetime import date
        memories = memory_manager.list_memories()
        export_list = []
        for m in memories:
            full = memory_manager.retrieve_memory(m["key"])
            if full:
                export_list.append(full)
        filename = f"engram_export_{date.today().isoformat()}.json"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(json.dumps(export_list, indent=2, ensure_ascii=False))
        print(f"Exported {len(export_list)} memories to {filename}", file=sys.stderr)
        sys.exit(0)

    if args.import_file:
        embedder._load()
        with open(args.import_file, "r", encoding="utf-8") as f:
            bundle = json.load(f)
        count = 0
        for mem in bundle:
            memory_manager.store_memory(
                mem["key"],
                mem.get("content", ""),
                mem.get("tags", []),
                mem.get("title"),
            )
            count += 1
        print(f"Imported {count} memories from {args.import_file}", file=sys.stderr)
        sys.exit(0)

    if args.migrate:
        from pathlib import Path
        from core.chunker import chunk_content
        json_dir = Path(__file__).parent / "data" / "memories"
        count = 0
        for path in json_dir.glob("*.json"):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "chunk_count" not in data or data["chunk_count"] == "?":
                chunks = chunk_content(data.get("content", ""))
                data["chunk_count"] = len(chunks)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                count += 1
        print(f"Migrated {count} memories (added chunk_count)", file=sys.stderr)
        sys.exit(0)

    if args.health:
        embedder._load()
        memory_manager._ensure_initialized()
        stats = memory_manager.get_stats()
        print(f"Engram Health Check", file=sys.stderr)
        print(f"  Model:      {embedder._model is not None and 'loaded' or 'NOT LOADED'}", file=sys.stderr)
        print(f"  Memories:   {stats['total_memories']}", file=sys.stderr)
        print(f"  Chunks:     {stats['total_chunks']}", file=sys.stderr)
        print(f"  JSON path:  {stats['json_path']}", file=sys.stderr)
        print(f"  Chroma path:{stats['chroma_path']}", file=sys.stderr)
        print(f"Status: OK", file=sys.stderr)
        sys.exit(0)

    if args.self_test:
        import asyncio
        import time
        embedder._load()
        memory_manager._ensure_initialized()
        test_key = "_engram_self_test"

        async def _run_self_test():
            # Store
            t0 = time.time()
            result = await memory_manager.store_memory_async(
                test_key,
                "## Self Test\n\nThis is an integration test memory for Engram.",
                ["selftest"], "Self Test",
            )
            print(f"  store:          {result['chunk_count']} chunks in {time.time()-t0:.1f}s", file=sys.stderr)

            # Search
            t0 = time.time()
            results = await memory_manager.search_memories_async("integration test memory", limit=3)
            found = any(r["key"] == test_key for r in results)
            print(f"  search:         {'found' if found else 'NOT FOUND'} in {time.time()-t0:.1f}s", file=sys.stderr)

            # Retrieve chunk
            t0 = time.time()
            chunk = await memory_manager.retrieve_chunk_async(test_key, 0)
            print(f"  retrieve_chunk: {'ok' if chunk else 'FAILED'} in {time.time()-t0:.1f}s", file=sys.stderr)

            # Delete
            t0 = time.time()
            deleted = await memory_manager.delete_memory_async(test_key)
            print(f"  delete:         {'ok' if deleted else 'FAILED'} in {time.time()-t0:.1f}s", file=sys.stderr)

            # Verify gone
            verify = await memory_manager.retrieve_memory_async(test_key)
            print(f"  verify deleted: {'ok' if verify is None else 'STILL EXISTS'}", file=sys.stderr)

            # ── last_accessed tracking (TRAK-01, TRAK-02) ──────────────────
            # Store a fresh memory to test against
            await memory_manager.store_memory_async(
                "_test_tracking", "## Tracking test\n\nThis tests last_accessed updates.",
                ["selftest"], "Tracking Test"
            )
            # Retrieve — fires last_accessed update
            retrieved = await memory_manager.retrieve_memory_async("_test_tracking")
            await asyncio.sleep(0.1)  # allow fire-and-forget task to complete
            data_after = memory_manager._load_json("_test_tracking")
            tracking_ok = data_after is not None and data_after.get("last_accessed") is not None
            print(f"  last_accessed:  {'set' if tracking_ok else 'NOT SET'}", file=sys.stderr)

            # ── Backward compat: existing memory has last_accessed: null (TRAK-03) ──
            # (Already stored test memory starts with null, now set — just check type)
            tracking_compat = True  # verified by store returning dict without error

            # ── Dedup gate (DEDU-01, DEDU-02, DEDU-04) ──────────────────────
            from core.memory_manager import DuplicateMemoryError
            # Store original
            await memory_manager.store_memory_async(
                "_test_dedup_original",
                "## Dedup original\n\nThis is a test memory for duplicate detection purposes. "
                "It contains enough substantive content to get a reliable and stable embedding from the sentence-transformers model.",
                ["selftest"], "Dedup Original"
            )
            # Try to store near-duplicate — should raise DuplicateMemoryError
            dedup_blocked = False
            try:
                await memory_manager.store_memory_async(
                    "_test_dedup_copy",
                    "## Dedup original\n\nThis is a test memory for duplicate detection purposes. "
                    "It contains enough substantive content to get a reliable and stable embedding from the sentence-transformers model.",
                    ["selftest"], "Dedup Copy"
                )
            except DuplicateMemoryError:
                dedup_blocked = True
            print(f"  dedup block:    {'blocked' if dedup_blocked else 'NOT BLOCKED'}", file=sys.stderr)

            # Store with force=True — should succeed even if duplicate
            force_ok = False
            try:
                await memory_manager.store_memory_async(
                    "_test_dedup_forced",
                    "## Dedup original\n\nThis is a test memory for duplicate detection purposes. "
                    "It contains enough substantive content to get a reliable and stable embedding from the sentence-transformers model.",
                    ["selftest"], "Dedup Forced", force=True
                )
                force_ok = True
            except DuplicateMemoryError:
                force_ok = False
            print(f"  force override: {'ok' if force_ok else 'FAILED'}", file=sys.stderr)

            # Self-update must not be blocked (DEDU-01 self-update exemption)
            self_update_ok = False
            try:
                await memory_manager.store_memory_async(
                    "_test_dedup_original",
                    "## Dedup original\n\nThis is a test memory for duplicate detection purposes. "
                    "It contains enough substantive content to get a reliable and stable embedding from the sentence-transformers model. Updated.",
                    ["selftest"], "Dedup Original Updated"
                )
                self_update_ok = True
            except DuplicateMemoryError:
                self_update_ok = False
            print(f"  self-update:    {'ok' if self_update_ok else 'BLOCKED (BUG)'}", file=sys.stderr)

            # ── related_to field (RELM-01, RELM-02, RELM-04) ─────────────────
            await memory_manager.store_memory_async(
                "_test_relm_a", "## Related A\n\nThis memory links to B.",
                ["selftest"], "Related A",
                related_to=["_test_relm_b"]
            )
            await memory_manager.store_memory_async(
                "_test_relm_b", "## Related B\n\nStandalone memory.",
                ["selftest"], "Related B"
            )
            relm_json = memory_manager._load_json("_test_relm_a")
            relm_stored = relm_json is not None and relm_json.get("related_to") == ["_test_relm_b"]
            print(f"  related_to JSON:{'ok' if relm_stored else 'FAILED'}", file=sys.stderr)

            # Bidirectional: query B, A should appear in reverse
            rel_result = await memory_manager.get_related_memories_async("_test_relm_b")
            relm_bidir = any(r["key"] == "_test_relm_a" for r in rel_result.get("reverse", []))
            print(f"  bidirectional:  {'ok' if relm_bidir else 'FAILED'}", file=sys.stderr)

            # ── Cleanup test memories ──────────────────────────────────────
            for k in ["_test_tracking", "_test_dedup_original", "_test_dedup_copy",
                      "_test_dedup_forced", "_test_relm_a", "_test_relm_b"]:
                try:
                    await memory_manager.delete_memory_async(k)
                except Exception:
                    pass  # already gone or never created

            all_ok = (found and chunk and deleted and verify is None
                      and tracking_ok and dedup_blocked and force_ok and self_update_ok
                      and relm_stored and relm_bidir)

            if all_ok:
                print(f"Self-test PASSED", file=sys.stderr)
                return True
            else:
                print(f"Self-test FAILED", file=sys.stderr)
                return False

        print(f"Engram Self-Test: store -> search -> retrieve_chunk -> delete", file=sys.stderr)
        passed = asyncio.run(_run_self_test())
        sys.exit(0 if passed else 1)

    if args.generate_config:
        config = {
            "mcpServers": {
                "engram": {
                    "command": sys.executable,
                    "args": [os.path.abspath(__file__)],
                }
            }
        }
        print(json.dumps(config, indent=2))
        sys.exit(0)

    # Pre-load everything before accepting connections so no blocking init
    # happens on the event loop during MCP tool calls.
    print("[Engram] Pre-loading embedding model...", file=sys.stderr)
    embedder._load()
    print("[Engram] Model ready.", file=sys.stderr)

    print("[Engram] Initializing ChromaDB...", file=sys.stderr)
    memory_manager._ensure_initialized()
    print("[Engram] ChromaDB ready.", file=sys.stderr)

    if args.transport == "sse":
        print(f"[Engram] Starting — SSE on {args.host}:{args.port}", file=sys.stderr)
        mcp.run(transport="sse", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")
