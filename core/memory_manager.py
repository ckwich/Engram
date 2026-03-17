"""
core/memory_manager.py — Storage engine for Engram.

Maintains two parallel stores:
  1. JSON flat files — source of truth, human-readable, portable
  2. ChromaDB vector index — semantic search index

JSON is always written first. ChromaDB is the index, not the database.
If ChromaDB is lost or corrupted, it can be rebuilt from JSON via rebuild_index().

Async methods (used by MCP server) run ALL blocking I/O — ChromaDB queries, JSON
file reads/writes, directory globs — in a thread pool executor via _run_blocking().
No blocking call ever touches the event loop. Sync methods (used by webui/CLI) call
the same blocking code directly.

ChromaDB operations have a 30-second timeout via asyncio.wait_for() to prevent
indefinite hangs from SQLite locks or HNSW stalls. ChromaDB work runs in a
dedicated executor (_chroma_executor) so zombie threads from timed-out ops
cannot exhaust the default executor and block other async work.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Optional

import chromadb

from core.chunker import chunk_content
from core.embedder import embedder

# ── Limits ────────────────────────────────────────────────────────────────────
MAX_MEMORY_CHARS = 15_000
CHROMA_TIMEOUT = 30.0  # seconds — timeout for ChromaDB operations in async paths

# Dedicated executor for ChromaDB ops. If a Chroma call times out, the zombie
# thread stays here and cannot fill the default executor used by other async work.
_chroma_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="chroma")

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
JSON_DIR = PROJECT_ROOT / "data" / "memories"
CHROMA_DIR = PROJECT_ROOT / "data" / "chroma"
JSON_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_DIR.mkdir(parents=True, exist_ok=True)

# ── Thread-safe collection init lock ─────────────────────────────────────────
_init_lock = threading.Lock()


def _key_hash(key: str) -> str:
    return hashlib.md5(key.encode()).hexdigest()


def _chunk_doc_id(key: str, chunk_id: int) -> str:
    """Stable, unique ChromaDB document ID for a chunk."""
    return f"{_key_hash(key)}_{chunk_id}"


def _json_path(key: str) -> Path:
    return JSON_DIR / f"{_key_hash(key)}.json"


def _now() -> str:
    return datetime.now().astimezone().isoformat()


async def _run_blocking(func, *args, **kwargs):
    """Run a blocking function in the default thread pool executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))


async def _run_chroma(func, *args, **kwargs):
    """Run a ChromaDB function in the dedicated Chroma executor with timeout.
    If the call times out, the zombie thread remains in _chroma_executor (isolated
    from the default executor) and a RuntimeError is raised."""
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(_chroma_executor, partial(func, *args, **kwargs)),
            timeout=CHROMA_TIMEOUT,
        )
    except asyncio.TimeoutError:
        print(
            f"[Engram] WARNING: ChromaDB operation timed out after {CHROMA_TIMEOUT}s. "
            f"A zombie thread may remain in _chroma_executor.",
            file=sys.stderr,
        )
        raise RuntimeError(
            f"ChromaDB operation timed out after {CHROMA_TIMEOUT}s. "
            f"The database may be locked by another process."
        )


class MemoryManager:
    def __init__(self):
        self._chroma: Optional[chromadb.ClientAPI] = None
        self._collection = None

    # ── ChromaDB thread-safe lazy init ───────────────────────────────────

    def _get_collection(self):
        if self._collection is None:
            with _init_lock:
                if self._collection is None:
                    self._chroma = chromadb.PersistentClient(
                        path=str(CHROMA_DIR),
                        settings=chromadb.Settings(anonymized_telemetry=False),
                    )
                    self._collection = self._chroma.get_or_create_collection(
                        name="engram_memories",
                        metadata={"hnsw:space": "cosine"},
                    )
        return self._collection

    def _ensure_initialized(self):
        """Eagerly initialize ChromaDB. Call at server startup before mcp.run()."""
        self._get_collection()

    # ── Internal helpers ────────────────────────────────────────────────────

    def _load_json(self, key: str) -> Optional[dict]:
        path = _json_path(key)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Engram] Failed to load JSON for key '{key}': {e}", file=sys.stderr)
            return None

    def _save_json(self, data: dict):
        path = _json_path(data["key"])
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Engram] Failed to save JSON for key '{data['key']}': {e}", file=sys.stderr)
            raise

    def _delete_chunks_from_chroma(self, key: str):
        """Remove all existing chunks for a key from ChromaDB.
        Raises on failure so callers can handle sync drift."""
        col = self._get_collection()
        results = col.get(where={"parent_key": key})
        if results and results.get("ids"):
            col.delete(ids=results["ids"])

    def _index_chunks(self, key: str, chunks: list[dict], title: str, tags: list[str]):
        """Embed and upsert chunks into ChromaDB (sync — used by webui/CLI)."""
        col = self._get_collection()
        if not chunks:
            return

        texts = [c["text"] for c in chunks]
        embeddings = embedder.embed_batch(texts)

        ids = [_chunk_doc_id(key, c["chunk_id"]) for c in chunks]
        metadatas = [
            {
                "parent_key": key,
                "chunk_id": c["chunk_id"],
                "title": title,
                "tags": ",".join(tags),
            }
            for c in chunks
        ]

        col.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )

    async def _index_chunks_async(self, key: str, chunks: list[dict], title: str, tags: list[str]):
        """Embed and upsert chunks into ChromaDB (async — non-blocking for MCP).
        ALL blocking ops run in executor — nothing touches the event loop directly."""
        if not chunks:
            return

        texts = [c["text"] for c in chunks]
        embeddings = await embedder.embed_batch_async(texts)

        ids = [_chunk_doc_id(key, c["chunk_id"]) for c in chunks]
        metadatas = [
            {
                "parent_key": key,
                "chunk_id": c["chunk_id"],
                "title": title,
                "tags": ",".join(tags),
            }
            for c in chunks
        ]

        def _do_upsert():
            col = self._get_collection()
            col.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas,
            )

        await _run_chroma(_do_upsert)

    # ── Public API ──────────────────────────────────────────────────────────

    def _prepare_store(
        self,
        key: str,
        content: str,
        tags: list[str] = None,
        title: str = None,
    ) -> tuple[dict, list[dict]]:
        """
        Shared preparation for store_memory / store_memory_async.
        Validates size, builds the data dict, writes JSON first (source of truth),
        then cleans up old ChromaDB chunks. Returns (data, chunks).
        Raises ValueError if content exceeds MAX_MEMORY_CHARS.
        """
        if len(content) > MAX_MEMORY_CHARS:
            raise ValueError(
                f"Content is {len(content):,} chars — exceeds the {MAX_MEMORY_CHARS:,} char limit. "
                f"Split this into smaller memories with more specific keys "
                f"(e.g. '{key}_part1', '{key}_part2') for better chunking and retrieval."
            )

        tags = tags or []
        now = _now()

        # Preserve created_at and title if updating
        existing = self._load_json(key)
        created_at = existing["created_at"] if existing else now
        resolved_title = title or (existing["title"] if existing else key)

        # Append audit log to content
        action = "Updated" if existing else "Created"
        content_with_log = f"{content}\n\n---\n**{now} | {action} via Engram**"

        data = {
            "key": key,
            "title": resolved_title,
            "content": content_with_log,
            "tags": tags,
            "created_at": created_at,
            "updated_at": now,
            "chars": len(content_with_log),
            "lines": len(content_with_log.splitlines()),
        }

        # 1. Chunk content and set count
        chunks = chunk_content(content_with_log)
        data["chunk_count"] = len(chunks)

        # 2. Write JSON (source of truth) FIRST — before touching ChromaDB
        self._save_json(data)

        # 3. Remove old chunks from ChromaDB (index cleanup, after JSON is safe).
        #    If this fails, stale chunks may remain but JSON is already persisted.
        #    The new chunks will still be indexed, and rebuild_index can fix drift.
        try:
            self._delete_chunks_from_chroma(key)
        except Exception as e:
            print(f"[Engram] WARNING: Failed to delete old chunks for '{key}': {e}. "
                  f"Stale chunks may remain until next rebuild_index.", file=sys.stderr)

        return data, chunks

    def store_memory(
        self,
        key: str,
        content: str,
        tags: list[str] = None,
        title: str = None,
    ) -> dict:
        """
        Store or update a memory (sync — used by webui/CLI).
        Writes JSON first, then updates the vector index.
        Returns the stored memory metadata dict.
        """
        data, chunks = self._prepare_store(key, content, tags, title)
        self._index_chunks(key, chunks, data["title"], data["tags"])
        return data

    async def store_memory_async(
        self,
        key: str,
        content: str,
        tags: list[str] = None,
        title: str = None,
    ) -> dict:
        """
        Store or update a memory (async — non-blocking for MCP).
        Writes JSON first, then updates the vector index without blocking the event loop.
        """
        data, chunks = await _run_blocking(self._prepare_store, key, content, tags, title)
        await self._index_chunks_async(key, chunks, data["title"], data["tags"])
        return data

    def retrieve_memory(self, key: str) -> Optional[dict]:
        """Retrieve full memory content from JSON store."""
        return self._load_json(key)

    async def retrieve_memory_async(self, key: str) -> Optional[dict]:
        """Retrieve full memory content from JSON store (async — non-blocking for MCP)."""
        return await _run_blocking(self._load_json, key)

    def retrieve_chunk(self, key: str, chunk_id: int) -> Optional[dict]:
        """
        Retrieve a specific chunk by key and chunk_id.
        Returns {key, chunk_id, text} or None.
        """
        col = self._get_collection()
        doc_id = _chunk_doc_id(key, chunk_id)
        try:
            result = col.get(ids=[doc_id], include=["documents", "metadatas"])
            if result and result["ids"]:
                return {
                    "key": key,
                    "chunk_id": chunk_id,
                    "text": result["documents"][0],
                    "title": result["metadatas"][0].get("title", key),
                }
        except Exception as e:
            print(f"[Engram] retrieve_chunk failed for {doc_id}: {e}", file=sys.stderr)
        return None

    async def retrieve_chunk_async(self, key: str, chunk_id: int) -> Optional[dict]:
        """Retrieve a specific chunk (async — non-blocking for MCP)."""
        return await _run_chroma(self.retrieve_chunk, key, chunk_id)

    def search_memories(self, query: str, limit: int = 5) -> list[dict]:
        """
        Semantic search across all memory chunks.
        Returns scored snippets — NOT full content.
        Each result: {key, chunk_id, title, score, snippet, tags}
        """
        col = self._get_collection()
        query_embedding = embedder.embed(query)

        try:
            results = col.query(
                query_embeddings=[query_embedding],
                n_results=min(limit, col.count() or 1),
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            print(f"[Engram] search failed: {e}", file=sys.stderr)
            return []

        if not results or not results.get("ids") or not results["ids"][0]:
            return []

        return self._parse_search_results(results)

    @staticmethod
    def _parse_search_results(results) -> list[dict]:
        """Parse ChromaDB query results into scored snippet dicts.
        Handles missing/corrupt metadata gracefully."""
        if not results or not results.get("ids") or not results["ids"][0]:
            return []

        output = []
        for doc, meta, distance in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            # ChromaDB cosine distance: 0 = identical, 2 = opposite
            # Convert to a 0–1 similarity score
            score = round(1 - (distance / 2), 3)
            snippet = (doc[:150].rsplit(" ", 1)[0] + "...") if len(doc) > 150 else doc
            parent_key = meta.get("parent_key", "unknown")
            output.append({
                "key": parent_key,
                "chunk_id": int(meta.get("chunk_id", 0)),
                "title": meta.get("title", parent_key),
                "tags": [t.strip() for t in meta.get("tags", "").split(",") if t.strip()],
                "score": score,
                "snippet": snippet,
            })

        # Sort by score descending
        output.sort(key=lambda x: x["score"], reverse=True)
        return output

    async def search_memories_async(self, query: str, limit: int = 5) -> list[dict]:
        """
        Async semantic search (non-blocking for MCP).
        Embedding runs in the embedder's executor, ChromaDB query runs in the
        default executor. Same return format as search_memories().
        ALL blocking ops run in executor — nothing touches the event loop directly.
        """
        query_embedding = await embedder.embed_async(query)

        def _do_query():
            col = self._get_collection()
            try:
                return col.query(
                    query_embeddings=[query_embedding],
                    n_results=min(limit, col.count() or 1),
                    include=["documents", "metadatas", "distances"],
                )
            except Exception as e:
                print(f"[Engram] search failed: {e}", file=sys.stderr)
                return None

        results = await _run_chroma(_do_query)
        return self._parse_search_results(results)

    def list_memories(self) -> list[dict]:
        """
        List all memories with metadata only (no content).
        Reads from JSON directory.
        """
        memories = []
        for path in JSON_DIR.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                memories.append({
                    "key": data["key"],
                    "title": data.get("title", data["key"]),
                    "tags": data.get("tags", []),
                    "updated_at": data.get("updated_at", ""),
                    "created_at": data.get("created_at", ""),
                    "chars": data.get("chars", 0),
                    "chunk_count": data.get("chunk_count", "?"),
                })
            except Exception:
                continue

        return sorted(memories, key=lambda x: x["updated_at"], reverse=True)

    async def list_memories_async(self) -> list[dict]:
        """List all memories (async — non-blocking for MCP)."""
        return await _run_blocking(self.list_memories)

    def delete_memory(self, key: str) -> bool:
        """Delete memory from ChromaDB index first, then JSON store.
        Chroma-first ordering prevents ghost search results: if Chroma delete
        fails, JSON is still intact (consistent state). If Chroma succeeds but
        JSON delete fails (unlikely), rebuild_index can recover."""
        path = _json_path(key)
        if not path.exists():
            return False

        # 1. Delete from ChromaDB first — prevents ghost search results
        try:
            self._delete_chunks_from_chroma(key)
        except Exception as e:
            print(f"[Engram] WARNING: Failed to delete chunks for '{key}': {e}. "
                  f"JSON not deleted to keep consistent state.", file=sys.stderr)
            raise RuntimeError(f"Failed to delete '{key}' from index: {e}")

        # 2. Delete JSON (source of truth) — Chroma is already clean
        path.unlink()
        return True

    async def delete_memory_async(self, key: str) -> bool:
        """Delete memory (async — non-blocking for MCP)."""
        return await _run_chroma(self.delete_memory, key)

    def rebuild_index(self):
        """
        Rebuild the entire ChromaDB index from JSON files.
        Use when the vector index is lost or corrupted.
        """
        print("[Engram] Rebuilding index from JSON files...", file=sys.stderr)
        col = self._get_collection()
        col.delete(where={"parent_key": {"$ne": "__never__"}})  # clear all

        rebuilt = 0
        skipped = 0
        for path in JSON_DIR.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                chunks = chunk_content(data["content"])
                self._index_chunks(
                    data["key"],
                    chunks,
                    data.get("title", data["key"]),
                    data.get("tags", []),
                )
                rebuilt += 1
            except Exception as e:
                skipped += 1
                print(f"[Engram] Skipped {path.name}: {e}", file=sys.stderr)

        if skipped:
            print(f"[Engram] WARNING: {skipped} memories skipped due to errors.", file=sys.stderr)
        print(f"[Engram] Rebuilt index for {rebuilt} memories.", file=sys.stderr)
        return rebuilt

    def get_stats(self) -> dict:
        memories = self.list_memories()
        col = self._get_collection()
        return {
            "total_memories": len(memories),
            "total_chars": sum(m["chars"] for m in memories),
            "total_chunks": col.count(),
            "json_path": str(JSON_DIR),
            "chroma_path": str(CHROMA_DIR),
        }


# Singleton
memory_manager = MemoryManager()
