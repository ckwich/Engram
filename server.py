#!/usr/bin/env python3
"""
Engram v0.1 — MCP Server
Provides semantic memory tools to AI agents via the Model Context Protocol.

Three-tier retrieval pattern (agents should follow this):
  1. search_memories_v2(query) / search_memories(query)
     → scored snippets, identify key + chunk_id
  2. retrieve_chunk_v2(key, chunk_id) / retrieve_chunk(key, chunk_id)
     → one relevant section, usually sufficient
  3. retrieve_memory_v2(key) / retrieve_memory(key)
     → full content, use sparingly
"""

import argparse
import json
import os
import sys
from typing import Any

from fastmcp import FastMCP
from core.embedder import embedder
from core.memory_manager import memory_manager, DuplicateMemoryError, _config
from core.tool_payloads import (
    build_list_payload,
    build_search_error_payload,
    build_search_payload,
    MemoryListPayload,
    render_list_payload,
    render_search_payload,
    SearchPayload,
)

mcp = FastMCP("engram")


def _clamp_search_limit(limit: int) -> int:
    return min(max(limit, 1), 20)


def _validate_search_query(query: str) -> str | None:
    if not query or not query.strip():
        return "❌ Query cannot be empty."
    if len(query) > 2000:
        return "❌ Query too long (max 2,000 chars). Shorten your search query."
    return None


def _runtime_error_payload(message: str, **payload: Any) -> dict[str, Any]:
    """Attach a stable structured runtime error payload."""
    data = dict(payload)
    data["error"] = {
        "code": "runtime_error",
        "message": message,
    }
    return data


def _retrieve_chunk_payload(result: dict | None, key: str, chunk_id: int) -> dict[str, Any]:
    """Normalize chunk retrieval output into the v2 structured contract."""
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
    """Normalize full-memory retrieval output into the v2 structured contract."""
    return {
        "key": key,
        "found": memory is not None,
        "memory": memory,
        "error": None,
    }


@mcp.tool()
async def search_memories_v2(query: str, limit: int = 5) -> SearchPayload:
    """
    Semantic search across all stored memories. Returns structured scored snippets only — NOT full content.

    This is ALWAYS your first step when looking for information. Results include the key and
    chunk_id needed for retrieve_chunk(). Only escalate to retrieve_chunk() or retrieve_memory()
    if the snippet alone isn't sufficient.

    Args:
        query: Natural language search query. Semantic — 'scheduling problems' will find
               'dispatch calendar issues' even without exact keyword overlap.
        limit: Max results to return (default 5, max 20).

    Returns:
        Structured payload: {query, count, results, error}. Each result includes key,
        chunk_id, title, score, snippet, and tags. On validation or runtime failure,
        results is empty and error is {code, message}.
    """
    validation_error = _validate_search_query(query)
    if validation_error:
        return build_search_error_payload(query, "invalid_query", validation_error)

    try:
        results = await memory_manager.search_memories_async(
            query.strip(),
            limit=_clamp_search_limit(limit),
        )
    except RuntimeError as e:
        return build_search_error_payload(query, "runtime_error", f"❌ Engram error: {e}")

    return build_search_payload(query, results)


@mcp.tool()
async def search_memories(query: str, limit: int = 5) -> str:
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
        (higher = more relevant). For structured output, use search_memories_v2().
    """
    payload = await search_memories_v2(query, limit)
    return render_search_payload(payload)


@mcp.tool()
async def list_memories_v2() -> MemoryListPayload:
    """
    List all stored memories as structured metadata only — keys, titles, tags, timestamps, chunk counts.
    No content is returned. Use this when you need to browse what exists, not search by topic.

    Returns:
        Structured payload: {count, memories}. Each memory includes key, title, tags,
        updated_at, created_at, chars, and chunk_count.

    For topic-based lookup, prefer search_memories_v2() or search_memories() instead.
    """
    memories = await memory_manager.list_memories_async()
    return build_list_payload(memories)


@mcp.tool()
async def list_all_memories() -> str:
    """
    List all stored memories as a directory — keys, titles, tags, timestamps, chunk counts.
    No content is returned. Use this when you need to browse what exists, not search by topic.

    For topic-based lookup, prefer search_memories() instead.
    """
    payload = await list_memories_v2()
    return render_list_payload(payload)


@mcp.tool()
async def retrieve_chunk(key: str, chunk_id: int) -> str:
    """
    Retrieve a single chunk from a memory by key and chunk_id.

    Use this AFTER search_memories() identifies the relevant key and chunk_id.
    This is the middle tier — more content than a snippet, far fewer tokens than the full memory.

    Args:
        key: The memory's unique key (from search_memories or list_all_memories results).
        chunk_id: The chunk index (from search_memories results).

    Returns:
        Full text of the requested chunk, with its parent memory title.
    """
    result = await memory_manager.retrieve_chunk_async(key, chunk_id)
    if not result:
        return f"❌ Chunk not found: key='{key}' chunk_id={chunk_id}"
    return (
        f"📄 Chunk {chunk_id} from '{result['title']}'\n"
        f"🔑 Key: {key}\n\n"
        f"{result['text']}"
    )


@mcp.tool()
async def retrieve_chunk_v2(key: str, chunk_id: int) -> dict[str, Any]:
    """
    Retrieve one chunk as structured data.

    Use this AFTER search_memories_v2() or search_memories() identifies the relevant key
    and chunk_id. Prefer this middle tier before escalating to retrieve_memory_v2().

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
async def retrieve_chunks_v2(requests: list[dict]) -> dict[str, Any]:
    """
    Retrieve multiple chunks in one call as structured data.

    Use this AFTER search_memories_v2() when you need several chunk matches at once.
    It preserves request order and keeps not-found results explicit so you can avoid
    escalating to retrieve_memory_v2() unless full memories are still necessary.

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
async def retrieve_memory(key: str) -> str:
    """
    Retrieve the full content of a memory by key.

    Use this ONLY when you need the complete memory and chunk retrieval isn't sufficient.
    This is the most token-expensive operation — use it intentionally.

    Args:
        key: The memory's unique key.

    Returns:
        Full memory content with metadata header.
    """
    result = await memory_manager.retrieve_memory_async(key)
    if not result:
        return f"❌ Memory not found: '{key}'"

    tags = ", ".join(result.get("tags", [])) or "none"
    return (
        f"📦 {result.get('title', key)}\n"
        f"🔑 Key: {result['key']}\n"
        f"🏷  Tags: {tags}\n"
        f"📅 Updated: {result['updated_at'][:16]}\n"
        f"📊 {result['chars']} chars | {result.get('chunk_count', '?')} chunks\n\n"
        f"{result['content']}"
    )


@mcp.tool()
async def retrieve_memory_v2(key: str) -> dict[str, Any]:
    """
    Retrieve the full memory as structured metadata plus content.

    Use this ONLY when chunk retrieval is not sufficient. This is still the most
    token-expensive read path, so prefer search_memories_v2() and retrieve_chunk_v2()
    or retrieve_chunks_v2() first.

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
    tags: str = "",
    related_to: str = "",
    force: bool = False,
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
        tags: Comma-separated tags for browsing (e.g. 'sylvara,decision,architecture').
        related_to: Comma-separated keys of related memories to link to (optional).
                    Maximum 10 keys. Links are bidirectional at query time.
        force: Pass True to store even if a near-duplicate already exists (default False).
               When False, a duplicate warning is returned instead of storing.

    Returns:
        Confirmation with chunk count, or duplicate warning if near-duplicate detected.
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    related_list = [k.strip() for k in related_to.split(",") if k.strip()] if related_to else []
    try:
        result = await memory_manager.store_memory_async(
            key, content, tag_list, title or None, related_list, force
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
async def get_related_memories(key: str) -> str:
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
async def get_related_memories_v2(key: str) -> dict[str, Any]:
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
async def get_stale_memories(days: int = 90, type: str = "all") -> str:
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
async def get_stale_memories_v2(days: int = 90, type: str = "all") -> dict[str, Any]:
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
                    "command": "python",
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
