"""
core/memory_manager.py — Storage engine for Engram.

Maintains two parallel stores:
  1. JSON flat files — source of truth, human-readable, portable
  2. ChromaDB vector index — semantic search index

JSON is always written first. ChromaDB is the index, not the database.
If ChromaDB is lost or corrupted, it can be rebuilt from JSON via rebuild_index().
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import chromadb

from core.chunker import chunk_content
from core.embedder import embedder

# ── Limits ────────────────────────────────────────────────────────────────────
MAX_MEMORY_CHARS = 15_000

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
JSON_DIR = PROJECT_ROOT / "data" / "memories"
CHROMA_DIR = PROJECT_ROOT / "data" / "chroma"
JSON_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_DIR.mkdir(parents=True, exist_ok=True)


def _key_hash(key: str) -> str:
    return hashlib.md5(key.encode()).hexdigest()


def _chunk_doc_id(key: str, chunk_id: int) -> str:
    """Stable, unique ChromaDB document ID for a chunk."""
    return f"{_key_hash(key)}_{chunk_id}"


def _json_path(key: str) -> Path:
    return JSON_DIR / f"{_key_hash(key)}.json"


def _now() -> str:
    return datetime.now().astimezone().isoformat()


class MemoryManager:
    def __init__(self):
        self._chroma: Optional[chromadb.ClientAPI] = None
        self._collection = None

    # ── ChromaDB lazy init ──────────────────────────────────────────────────

    def _get_collection(self):
        if self._collection is None:
            self._chroma = chromadb.PersistentClient(path=str(CHROMA_DIR))
            self._collection = self._chroma.get_or_create_collection(
                name="engram_memories",
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

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
        """Remove all existing chunks for a key from ChromaDB."""
        col = self._get_collection()
        try:
            results = col.get(where={"parent_key": key})
            if results and results.get("ids"):
                col.delete(ids=results["ids"])
        except Exception as e:
            print(f"[Engram] Failed to delete chunks for key '{key}': {e}", file=sys.stderr)

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
        """Embed and upsert chunks into ChromaDB (async — non-blocking for MCP)."""
        col = self._get_collection()
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

        col.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )

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
        Validates size, builds the data dict, writes JSON, returns (data, chunks).
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

        # 1. Remove old chunks from ChromaDB
        self._delete_chunks_from_chroma(key)

        # 2. Chunk content and set count before saving
        chunks = chunk_content(content_with_log)
        data["chunk_count"] = len(chunks)

        # 3. Write JSON (source of truth) — with chunk_count included
        self._save_json(data)

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
        data, chunks = self._prepare_store(key, content, tags, title)
        await self._index_chunks_async(key, chunks, data["title"], data["tags"])
        return data

    def retrieve_memory(self, key: str) -> Optional[dict]:
        """Retrieve full memory content from JSON store."""
        return self._load_json(key)

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

        output = []
        for doc, meta, distance in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            # ChromaDB cosine distance: 0 = identical, 2 = opposite
            # Convert to a 0–1 similarity score
            score = round(1 - (distance / 2), 3)
            snippet = doc[:150] + "..." if len(doc) > 150 else doc
            output.append({
                "key": meta["parent_key"],
                "chunk_id": meta["chunk_id"],
                "title": meta.get("title", meta["parent_key"]),
                "tags": [t for t in meta.get("tags", "").split(",") if t],
                "score": score,
                "snippet": snippet,
            })

        # Sort by score descending
        output.sort(key=lambda x: x["score"], reverse=True)
        return output

    async def search_memories_async(self, query: str, limit: int = 5) -> list[dict]:
        """
        Async semantic search (non-blocking for MCP).
        Same return format as search_memories().
        """
        col = self._get_collection()
        query_embedding = await embedder.embed_async(query)

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

        output = []
        for doc, meta, distance in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            score = round(1 - (distance / 2), 3)
            snippet = doc[:150] + "..." if len(doc) > 150 else doc
            output.append({
                "key": meta["parent_key"],
                "chunk_id": meta["chunk_id"],
                "title": meta.get("title", meta["parent_key"]),
                "tags": [t for t in meta.get("tags", "").split(",") if t],
                "score": score,
                "snippet": snippet,
            })

        output.sort(key=lambda x: x["score"], reverse=True)
        return output

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

    def delete_memory(self, key: str) -> bool:
        """Delete memory from JSON store and ChromaDB index."""
        path = _json_path(key)
        deleted = False
        if path.exists():
            path.unlink()
            deleted = True
        self._delete_chunks_from_chroma(key)
        return deleted

    def rebuild_index(self):
        """
        Rebuild the entire ChromaDB index from JSON files.
        Use when the vector index is lost or corrupted.
        """
        print("[Engram] Rebuilding index from JSON files...", file=sys.stderr)
        col = self._get_collection()
        col.delete(where={"parent_key": {"$ne": "__never__"}})  # clear all

        rebuilt = 0
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
                print(f"[Engram] Skipped {path.name}: {e}", file=sys.stderr)

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
