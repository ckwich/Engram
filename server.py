#!/usr/bin/env python3
"""
Engram v0.1 — MCP Server
Provides semantic memory tools to AI agents via the Model Context Protocol.

Three-tier retrieval pattern (agents should follow this):
  1. search_memories(query)         → scored snippets, identify key + chunk_id
  2. retrieve_chunk(key, chunk_id)  → one relevant section, usually sufficient
  3. retrieve_memory(key)           → full content, use sparingly
"""

import argparse
import json
import os
import sys

from fastmcp import FastMCP
from core.embedder import embedder
from core.memory_manager import memory_manager

mcp = FastMCP("engram")


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
        Scored list of matching chunks with snippets. Score is 0.0–1.0 (higher = more relevant).
    """
    try:
        results = await memory_manager.search_memories_async(query, limit=min(limit, 20))
    except RuntimeError as e:
        return f"❌ Engram error: {e}"
    if not results:
        return f"🔍 No memories found for '{query}'"

    lines = [f"🔍 {len(results)} results for '{query}':\n"]
    for r in results:
        tags = ", ".join(r["tags"]) if r["tags"] else "none"
        lines.append(
            f"[score: {r['score']}] {r['title']}\n"
            f"  key={r['key']}  chunk_id={r['chunk_id']}  tags={tags}\n"
            f"  snippet: {r['snippet']}\n"
        )
    return "\n".join(lines)


@mcp.tool()
async def list_all_memories() -> str:
    """
    List all stored memories as a directory — keys, titles, tags, timestamps, chunk counts.
    No content is returned. Use this when you need to browse what exists, not search by topic.

    For topic-based lookup, prefer search_memories() instead.
    """
    memories = memory_manager.list_memories()
    if not memories:
        return "📭 No memories stored yet."

    lines = [f"📚 Engram Memory Directory — {len(memories)} memories\n{'='*50}\n"]
    for m in memories:
        tags = ", ".join(m["tags"]) if m["tags"] else "none"
        lines.append(
            f"🔑 {m['key']}\n"
            f"   Title:   {m['title']}\n"
            f"   Tags:    {tags}\n"
            f"   Chunks:  {m['chunk_count']}\n"
            f"   Updated: {m['updated_at'][:16]}\n"
        )
    return "\n".join(lines)


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
    result = memory_manager.retrieve_chunk(key, chunk_id)
    if not result:
        return f"❌ Chunk not found: key='{key}' chunk_id={chunk_id}"
    return (
        f"📄 Chunk {chunk_id} from '{result['title']}'\n"
        f"🔑 Key: {key}\n\n"
        f"{result['text']}"
    )


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
    result = memory_manager.retrieve_memory(key)
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
async def store_memory(
    key: str,
    content: str,
    title: str = "",
    tags: str = "",
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

    Returns:
        Confirmation with chunk count.
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    try:
        result = await memory_manager.store_memory_async(key, content, tag_list, title or None)
        return (
            f"✅ Stored: '{result['title']}'\n"
            f"   Key: {key}\n"
            f"   Chunks: {result.get('chunk_count', '?')}\n"
            f"   Chars: {result['chars']}"
        )
    except ValueError as e:
        return f"⚠️ Memory too large: {e}"
    except RuntimeError as e:
        return f"❌ Engram error: {e}"
    except Exception as e:
        return f"❌ Failed to store '{key}': {e}"


@mcp.tool()
async def delete_memory(key: str) -> str:
    """
    Permanently delete a memory and all its indexed chunks.

    Args:
        key: The memory key to delete.

    Returns:
        Confirmation or not-found message.
    """
    deleted = memory_manager.delete_memory(key)
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

    # Pre-load the embedding model before accepting connections.
    # This prevents _load() from running inside the thread pool executor,
    # where asyncio.wait_for() cannot interrupt it if it blocks.
    print("[Engram] Pre-loading embedding model...", file=sys.stderr)
    embedder._load()
    print("[Engram] Model ready.", file=sys.stderr)

    if args.transport == "sse":
        print(f"[Engram] Starting — SSE on {args.host}:{args.port}", file=sys.stderr)
        mcp.run(transport="sse", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")
