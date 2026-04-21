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
import os
import re
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any, Optional

import chromadb

from core.chunker import chunk_content_with_metadata
from core.embedder import embedder

# ── Limits ────────────────────────────────────────────────────────────────────
MAX_MEMORY_CHARS = 15_000
CHROMA_TIMEOUT = 30.0  # seconds — timeout for ChromaDB operations in async paths
DEFAULT_MEMORY_STATUS = "active"
ALLOWED_MEMORY_STATUSES = {
    "active",
    "draft",
    "historical",
    "superseded",
    "archived",
}

# Dedicated executor for ChromaDB ops. If a Chroma call times out, the zombie
# thread stays here and cannot fill the default executor used by other async work.
_chroma_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="chroma")

# ── Paths ──────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
JSON_DIR = PROJECT_ROOT / "data" / "memories"
CHROMA_DIR = PROJECT_ROOT / "data" / "chroma"
JSON_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_DIR.mkdir(parents=True, exist_ok=True)

# ── Config ─────────────────────────────────────────────────────────────────
_CONFIG_PATH = PROJECT_ROOT / "config.json"

def _load_config() -> dict:
    """Load Engram config.json with safe defaults. Missing file = all defaults."""
    defaults = {
        "dedup_threshold": 0.92,
        "stale_days": 90,
    }
    try:
        if _CONFIG_PATH.exists():
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            defaults.update(user_config)
    except Exception as e:
        print(f"[Engram] WARNING: Failed to load config.json: {e}. Using defaults.", file=sys.stderr)
    return defaults

_config = _load_config()


class DuplicateMemoryError(Exception):
    """Raised when store_memory detects a near-duplicate and force=False."""
    def __init__(self, duplicate: dict):
        self.duplicate = duplicate
        super().__init__(
            f"Duplicate detected: {duplicate['existing_key']} (score={duplicate['score']})"
        )


_AUDIT_SUFFIX_RE = re.compile(
    r'(\n\n---\n\*\*[^\n]+\| (?:Created|Updated) via Engram\*\*)+\s*$'
)

def _strip_audit_log(content: str) -> str:
    """Strip all accumulated audit log suffixes from content for dedup comparison."""
    return _AUDIT_SUFFIX_RE.sub('', content)


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


def _normalize_optional_text(value: Any) -> Optional[str]:
    """Normalize optional string-like metadata values."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_status(value: Any) -> Optional[str]:
    """Normalize lifecycle status inputs to lower-case text."""
    text = _normalize_optional_text(value)
    return text.lower() if text else None


def _coerce_allowed_status(value: Any, default: str = DEFAULT_MEMORY_STATUS) -> str:
    """Coerce missing or unsupported lifecycle statuses to a safe default."""
    normalized = _normalize_status(value)
    if normalized in ALLOWED_MEMORY_STATUSES:
        return normalized
    return default


def _normalize_tags(tags: Any) -> list[str]:
    """Normalize tags to a stable, de-duplicated list of non-empty strings."""
    if tags is None:
        return []

    raw_tags = [tags] if isinstance(tags, str) else list(tags)
    normalized: list[str] = []
    seen: set[str] = set()
    for tag in raw_tags:
        text = str(tag).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _normalize_related_to(related_to: Any) -> list[str]:
    """Normalize related memory keys while preserving order."""
    if related_to is None:
        return []

    raw_keys = [related_to] if isinstance(related_to, str) else list(related_to)
    normalized: list[str] = []
    seen: set[str] = set()
    for key in raw_keys:
        text = str(key).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _normalize_bool(value: Any, default: bool = False) -> bool:
    """Normalize permissive bool-like inputs without treating every string as true."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"true", "1", "yes", "y", "on"}:
            return True
        if text in {"false", "0", "no", "n", "off", ""}:
            return False
    return bool(value)


def _extract_heading_title(content: str) -> Optional[str]:
    """Suggest a title from the first markdown heading or text line."""
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            return heading or None
        return line[:80].strip() or None
    return None


def _suggest_tags_from_content(content: str, max_tags: int = 5) -> list[str]:
    """Extract a small stable tag set from headings and early prose."""
    stop_words = {
        "about",
        "after",
        "also",
        "and",
        "are",
        "because",
        "been",
        "before",
        "being",
        "below",
        "between",
        "brief",
        "content",
        "could",
        "draft",
        "from",
        "have",
        "into",
        "memory",
        "more",
        "note",
        "notes",
        "only",
        "over",
        "section",
        "should",
        "that",
        "their",
        "them",
        "there",
        "these",
        "this",
        "through",
        "under",
        "updated",
        "using",
        "with",
        "without",
    }
    candidates = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", content.lower())
    tags: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in stop_words or candidate in seen:
            continue
        seen.add(candidate)
        tags.append(candidate)
        if len(tags) >= max_tags:
            break
    return tags


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

    @staticmethod
    def _normalize_memory_record(data: Optional[dict]) -> Optional[dict]:
        """Backfill additive metadata defaults without mutating on-disk legacy JSON."""
        if data is None:
            return None

        normalized = dict(data)
        key = normalized.get("key", "")
        normalized["key"] = key
        normalized["title"] = normalized.get("title") or key
        normalized["tags"] = _normalize_tags(normalized.get("tags"))
        normalized["related_to"] = _normalize_related_to(normalized.get("related_to"))
        normalized["project"] = _normalize_optional_text(normalized.get("project"))
        normalized["domain"] = _normalize_optional_text(normalized.get("domain"))
        normalized["status"] = _coerce_allowed_status(normalized.get("status"))
        normalized["canonical"] = _normalize_bool(normalized.get("canonical"), default=False)
        return normalized

    @staticmethod
    def _make_snippet(text: str, max_chars: int = 150) -> str:
        """Truncate a chunk into a readable snippet without breaking callers."""
        if len(text) <= max_chars:
            return text
        truncated = text[:max_chars].rsplit(" ", 1)
        return (truncated[0] if len(truncated) > 1 else text[: max_chars - 3]) + "..."

    @staticmethod
    def _score_from_distance(distance: float) -> float:
        """Convert Chroma cosine distance to a similarity score."""
        return round(1 - (distance / 2), 3)

    @staticmethod
    def _normalize_limit(limit: int) -> int:
        """Clamp result limits to a non-negative integer."""
        return max(int(limit), 0)

    @staticmethod
    def _normalize_filter_tags(tags: Any) -> list[str]:
        """Accept either a string or list-like tags filter."""
        return _normalize_tags(tags)

    def _chunk_metadata(self, key: str, chunk: dict, data: dict) -> dict:
        """Build Chroma metadata for a chunk using normalized memory metadata."""
        metadata = {
            "parent_key": key,
            "chunk_id": chunk["chunk_id"],
            "chunk_index": chunk["chunk_id"],
            "title": data["title"],
            "tags": ",".join(data["tags"]),
            "project": data["project"] or "",
            "domain": data["domain"] or "",
            "status": data["status"],
            "canonical": data["canonical"],
            "section_title": chunk.get("section_title", ""),
            "heading_path": " > ".join(chunk.get("heading_path", [])),
            "chunk_kind": chunk.get("chunk_kind", "section"),
        }
        if data.get("related_to"):
            metadata["related_to"] = ",".join(data["related_to"])
        return metadata

    def _memory_stale_state(self, data: dict, days: int = None) -> dict:
        """Return structured stale metadata for a memory record."""
        threshold_days = days if days is not None else _config.get("stale_days", 90)
        now_dt = datetime.now().astimezone()

        is_time_stale = False
        days_since = 0
        last_accessed = data.get("last_accessed")
        if last_accessed is not None:
            try:
                accessed_dt = datetime.fromisoformat(last_accessed)
                if accessed_dt.tzinfo is None:
                    accessed_dt = accessed_dt.astimezone()
                delta = now_dt - accessed_dt
                days_since = delta.days
                is_time_stale = days_since >= threshold_days
            except Exception:
                pass

        is_code_stale = bool(data.get("potentially_stale", False))
        stale_reason = _normalize_optional_text(data.get("stale_reason")) or ""

        if is_time_stale and is_code_stale:
            stale_type = "both"
            stale_detail = f"{days_since} days; {stale_reason}" if stale_reason else f"{days_since} days"
        elif is_time_stale:
            stale_type = "time"
            stale_detail = f"{days_since} days"
        elif is_code_stale:
            stale_type = "code"
            stale_detail = stale_reason
        else:
            stale_type = None
            stale_detail = ""

        return {
            "stale_type": stale_type,
            "stale_detail": stale_detail,
            "last_accessed": last_accessed,
            "stale_flagged_at": data.get("stale_flagged_at"),
            "days_since": days_since,
            "is_time_stale": is_time_stale,
            "is_code_stale": is_code_stale,
        }

    @staticmethod
    def _semantic_query_include() -> list[str]:
        """Shared Chroma query include list for semantic search."""
        return ["documents", "metadatas", "distances"]

    def _query_semantic_results(self, query_embedding: list[float], limit: int):
        """Run a semantic search query against the chunk index."""
        col = self._get_collection()
        return col.query(
            query_embeddings=[query_embedding],
            n_results=min(limit, col.count() or 1),
            include=self._semantic_query_include(),
        )

    def _query_structured_semantic_results(self, query_embedding: list[float]):
        """Run a structured search query across the full indexed candidate set."""
        col = self._get_collection()
        total_chunks = col.count()
        return col.query(
            query_embeddings=[query_embedding],
            n_results=total_chunks or 1,
            include=self._semantic_query_include(),
        )

    @staticmethod
    def _normalize_pinned_keys(pinned_keys: Any) -> set[str]:
        """Normalize pinned key collections into a comparable set."""
        if pinned_keys is None:
            return set()
        if isinstance(pinned_keys, str):
            candidates = [pinned_keys]
        else:
            candidates = list(pinned_keys)
        return {
            str(candidate).strip()
            for candidate in candidates
            if str(candidate).strip()
        }

    def _build_result_explanation(
        self,
        *,
        score: float,
        meta: dict,
        memory: dict,
        filter_tags: list[str],
        include_stale: bool,
        canonical_only: bool,
        stale_info: dict,
        pinned: bool,
        pinned_first: bool,
    ) -> str:
        """Explain why a structured search result was ranked and kept."""
        parts = [f"semantic score {score:.3f}"]
        if pinned:
            parts.insert(0, "session-pinned")
            if pinned_first:
                parts.insert(1, "promoted ahead of unpinned results")

        section_title = meta.get("section_title")
        if section_title:
            parts.append(f"section '{section_title}'")
        elif meta.get("chunk_kind"):
            parts.append(f"chunk kind {meta['chunk_kind']}")

        if memory.get("project"):
            parts.append(f"project={memory['project']}")
        if memory.get("domain"):
            parts.append(f"domain={memory['domain']}")

        if filter_tags:
            parts.append(f"matched tags {', '.join(filter_tags)}")
        elif memory["tags"]:
            parts.append(f"tags {', '.join(memory['tags'])}")

        parts.append(f"status={memory['status']}")
        parts.append("canonical memory" if memory["canonical"] else "non-canonical memory")

        if stale_info["stale_type"]:
            detail = stale_info["stale_detail"] or "flagged as stale"
            parts.append(f"stale={stale_info['stale_type']} ({detail})")
        elif not include_stale or canonical_only:
            parts.append("fresh memory")

        return "; ".join(parts)

    def _build_structured_payload(
        self,
        *,
        query: str,
        raw_results,
        limit: int,
        project: Optional[str],
        domain: Optional[str],
        tags: list[str],
        include_stale: bool,
        canonical_only: bool,
        pinned_keys: Any = None,
        pinned_first: bool = False,
    ) -> dict:
        """Filter and enrich semantic results into the structured payload."""
        normalized_limit = self._normalize_limit(limit)
        payload = {"query": query, "count": 0, "results": []}
        if normalized_limit == 0:
            return payload

        if not raw_results or not raw_results.get("ids") or not raw_results["ids"][0]:
            return payload

        normalized_project = _normalize_optional_text(project)
        normalized_domain = _normalize_optional_text(domain)
        required_tags = self._normalize_filter_tags(tags)
        normalized_pinned_keys = self._normalize_pinned_keys(pinned_keys)

        enriched_results: list[dict] = []
        for doc, meta, distance in zip(
            raw_results["documents"][0],
            raw_results["metadatas"][0],
            raw_results["distances"][0],
        ):
            parent_key = meta.get("parent_key", "unknown")
            memory = self._load_json(parent_key)
            if memory is None:
                continue
            stale_info = self._memory_stale_state(memory)

            if normalized_project and memory["project"] != normalized_project:
                continue
            if normalized_domain and memory["domain"] != normalized_domain:
                continue
            if required_tags and not all(tag in memory["tags"] for tag in required_tags):
                continue
            if canonical_only and not memory["canonical"]:
                continue
            if not include_stale and stale_info["stale_type"]:
                continue

            score = self._score_from_distance(distance)
            is_pinned = parent_key in normalized_pinned_keys
            enriched_results.append(
                {
                    "key": parent_key,
                    "chunk_id": int(meta.get("chunk_id", 0)),
                    "title": memory["title"],
                    "score": score,
                    "snippet": self._make_snippet(doc),
                    "tags": memory["tags"],
                    "project": memory["project"],
                    "domain": memory["domain"],
                    "status": memory["status"],
                    "canonical": memory["canonical"],
                    "stale_type": stale_info["stale_type"],
                    "pinned": is_pinned,
                    "explanation": self._build_result_explanation(
                        score=score,
                        meta=meta,
                        memory=memory,
                        filter_tags=required_tags,
                        include_stale=include_stale,
                        canonical_only=canonical_only,
                        stale_info=stale_info,
                        pinned=is_pinned,
                        pinned_first=pinned_first,
                    ),
                }
            )

        enriched_results.sort(
            key=lambda result: (
                0 if pinned_first and result["pinned"] else 1,
                -result["score"],
                result["key"],
                result["chunk_id"],
            )
        )
        payload["results"] = enriched_results[:normalized_limit]
        payload["count"] = len(payload["results"])
        return payload

    def _load_json(self, key: str) -> Optional[dict]:
        path = _json_path(key)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return self._normalize_memory_record(json.load(f))
        except Exception as e:
            print(f"[Engram] Failed to load JSON for key '{key}': {e}", file=sys.stderr)
            return None

    def _save_json(self, data: dict, require_existing: bool = False) -> bool:
        path = _json_path(data["key"])
        fd, temp_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f"{path.name}.",
            suffix=".tmp",
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            if require_existing and not path.exists():
                temp_path.unlink(missing_ok=True)
                return False
            temp_path.replace(path)
            return True
        except Exception as e:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass
            print(f"[Engram] Failed to save JSON for key '{data['key']}': {e}", file=sys.stderr)
            raise

    def _delete_chunks_from_chroma(self, key: str):
        """Remove all existing chunks for a key from ChromaDB.
        Raises on failure so callers can handle sync drift."""
        col = self._get_collection()
        results = col.get(where={"parent_key": key})
        if results and results.get("ids"):
            col.delete(ids=results["ids"])

    def _index_chunks(self, key: str, chunks: list[dict], data: dict):
        """Embed and upsert chunks into ChromaDB (sync — used by webui/CLI)."""
        col = self._get_collection()
        if not chunks:
            return

        texts = [c["text"] for c in chunks]
        embeddings = embedder.embed_batch(texts)

        ids = [_chunk_doc_id(key, c["chunk_id"]) for c in chunks]
        metadatas = [self._chunk_metadata(key, chunk, data) for chunk in chunks]

        col.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )

    async def _index_chunks_async(self, key: str, chunks: list[dict], data: dict):
        """Embed and upsert chunks into ChromaDB (async — non-blocking for MCP).
        ALL blocking ops run in executor — nothing touches the event loop directly."""
        if not chunks:
            return

        texts = [c["text"] for c in chunks]
        embeddings = await embedder.embed_batch_async(texts)

        ids = [_chunk_doc_id(key, c["chunk_id"]) for c in chunks]
        metadatas = [self._chunk_metadata(key, chunk, data) for chunk in chunks]

        def _do_upsert():
            col = self._get_collection()
            col.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas,
            )

        await _run_chroma(_do_upsert)

    # ── Dedup & tracking helpers ──────────────────────────────────────────

    def _check_dedup(self, content: str, key: str) -> Optional[dict]:
        """
        Returns duplicate warning dict if content is too similar to an existing memory,
        None if safe to store.
        Uses stripped content for embedding to avoid audit log corruption (DEDU-04).
        Skips self-updates (same key updating — always allowed).
        """
        threshold = _config.get("dedup_threshold", 0.92)
        stripped = _strip_audit_log(content)

        # Skip dedup for very short content (unreliable embeddings)
        if len(stripped) < 150:
            return None

        col = self._get_collection()
        if col.count() == 0:
            return None

        embedding = embedder.embed(stripped)
        try:
            n = min(5, col.count())
            results = col.query(
                query_embeddings=[embedding],
                n_results=n,
                include=["metadatas", "distances"],
            )
        except Exception as e:
            print(f"[Engram] WARNING: Dedup check failed: {e}. Proceeding without dedup.", file=sys.stderr)
            return None

        if not results or not results.get("ids") or not results["ids"][0]:
            return None

        # Check top results: if any chunk belongs to the same key, this is a self-update — allow it.
        # This handles the case where other near-duplicates exist but the key's own chunks rank differently.
        for meta in results["metadatas"][0]:
            if meta.get("parent_key") == key:
                return None

        # Now check for duplicates among the top results
        distance = results["distances"][0][0]
        score = round(1 - (distance / 2), 3)

        if score >= threshold:
            meta = results["metadatas"][0][0]
            existing_key = meta.get("parent_key", "unknown")
            return {
                "status": "duplicate",
                "existing_key": existing_key,
                "existing_title": meta.get("title", existing_key),
                "score": score,
            }
        return None

    async def _update_last_accessed_async(self, keys: list[str]) -> None:
        """Background task: update last_accessed timestamp in JSON for the given keys.
        Fire-and-forget — caller must NOT await this. Exceptions are caught and logged."""
        now = _now()
        def _do_updates():
            for key in keys:
                data = self._load_json(key)
                if data is None:
                    continue
                data["last_accessed"] = now
                try:
                    self._save_json(data, require_existing=True)
                except Exception as e:
                    print(f"[Engram] WARNING: last_accessed update failed for '{key}': {e}", file=sys.stderr)
        try:
            await _run_blocking(_do_updates)
        except Exception as e:
            print(f"[Engram] WARNING: last_accessed batch update failed: {e}", file=sys.stderr)

    # ── Public API ──────────────────────────────────────────────────────────

    def check_duplicate(self, key: str, content: str) -> dict:
        """Check whether content is a near-duplicate of an existing memory."""
        duplicate = self._check_dedup(content, key)
        return {
            "key": key,
            "duplicate": duplicate is not None,
            "match": duplicate,
        }

    async def check_duplicate_async(self, key: str, content: str) -> dict:
        """Async wrapper for duplicate checks."""
        return await _run_blocking(self.check_duplicate, key, content)

    def suggest_memory_metadata(self, content: str) -> dict:
        """Suggest lightweight metadata defaults from markdown content."""
        stripped_content = _strip_audit_log(content).strip()
        title = _extract_heading_title(stripped_content)
        return {
            "title": title or "Untitled memory",
            "tags": _suggest_tags_from_content(stripped_content),
            "project": None,
            "domain": None,
            "status": "draft",
            "canonical": False,
            "related_to": [],
        }

    async def suggest_memory_metadata_async(self, content: str) -> dict:
        """Async wrapper for metadata suggestions."""
        return await _run_blocking(self.suggest_memory_metadata, content)

    def validate_memory(
        self,
        *,
        content: str,
        related_to: Any = None,
        status: str = None,
        tags: Any = None,
        title: str = None,
        project: str = None,
        domain: str = None,
        canonical: Any = None,
    ) -> dict:
        """Validate memory content and additive metadata fields."""
        normalized_related_to = _normalize_related_to(related_to)
        normalized_status = _normalize_status(status)
        normalized = {
            "title": _normalize_optional_text(title),
            "tags": _normalize_tags(tags),
            "related_to": normalized_related_to,
            "project": _normalize_optional_text(project),
            "domain": _normalize_optional_text(domain),
            "status": normalized_status or DEFAULT_MEMORY_STATUS,
            "canonical": _normalize_bool(canonical, default=False),
            "content_chars": len(content),
        }

        errors: list[dict[str, Any]] = []
        if len(content) > MAX_MEMORY_CHARS:
            errors.append(
                {
                    "field": "content",
                    "code": "content_too_long",
                    "message": (
                        f"Content is {len(content):,} chars — exceeds the "
                        f"{MAX_MEMORY_CHARS:,} char limit."
                    ),
                }
            )

        if len(normalized_related_to) > 10:
            errors.append(
                {
                    "field": "related_to",
                    "code": "too_many_related_memories",
                    "message": (
                        f"related_to has {len(normalized_related_to)} entries — maximum is 10."
                    ),
                }
            )

        if normalized_status and normalized_status not in ALLOWED_MEMORY_STATUSES:
            allowed = ", ".join(sorted(ALLOWED_MEMORY_STATUSES))
            errors.append(
                {
                    "field": "status",
                    "code": "invalid_status",
                    "message": f"status must be one of: {allowed}.",
                }
            )

        return {
            "valid": not errors,
            "errors": errors,
            "normalized": normalized,
        }

    async def validate_memory_async(self, **kwargs) -> dict:
        """Async wrapper for memory validation."""
        return await _run_blocking(self.validate_memory, **kwargs)

    @staticmethod
    def _validation_error_message(validation: dict) -> str:
        """Collapse structured validation errors into a stable exception string."""
        return "; ".join(error["message"] for error in validation["errors"])

    def _prepare_metadata_update(self, key: str, **changes) -> tuple[dict, list[dict], Optional[str]]:
        """Apply additive metadata updates, persist JSON first, then reindex content."""
        existing = self._load_json(key)
        if existing is None:
            raise KeyError(key)

        allowed_fields = {"title", "tags", "related_to", "project", "domain", "status", "canonical"}
        unsupported = sorted(set(changes) - allowed_fields)
        if unsupported:
            raise ValueError(
                f"Unsupported metadata fields: {', '.join(unsupported)}. "
                f"Allowed fields: {', '.join(sorted(allowed_fields))}."
            )

        content = existing["content"]
        stripped_content = _strip_audit_log(content)

        resolved_title = (
            (_normalize_optional_text(changes.get("title")) or key)
            if "title" in changes
            else existing["title"]
        )
        resolved_tags = (
            _normalize_tags(changes.get("tags"))
            if "tags" in changes
            else existing["tags"]
        )
        resolved_related_to = (
            _normalize_related_to(changes.get("related_to"))
            if "related_to" in changes
            else existing.get("related_to", [])
        )
        resolved_project = (
            _normalize_optional_text(changes.get("project"))
            if "project" in changes
            else existing.get("project")
        )
        resolved_domain = (
            _normalize_optional_text(changes.get("domain"))
            if "domain" in changes
            else existing.get("domain")
        )
        resolved_status = (
            _normalize_status(changes.get("status")) or DEFAULT_MEMORY_STATUS
            if "status" in changes
            else existing.get("status", DEFAULT_MEMORY_STATUS)
        )
        resolved_canonical = (
            _normalize_bool(changes.get("canonical"), default=False)
            if "canonical" in changes
            else existing.get("canonical", False)
        )

        validation = self.validate_memory(
            content=stripped_content,
            related_to=resolved_related_to,
            status=resolved_status,
            tags=resolved_tags,
            title=resolved_title,
            project=resolved_project,
            domain=resolved_domain,
            canonical=resolved_canonical,
        )
        if not validation["valid"]:
            raise ValueError(self._validation_error_message(validation))

        now = _now()
        data = self._normalize_memory_record(
            {
                **existing,
                "key": key,
                "title": resolved_title,
                "content": content,
                "tags": resolved_tags,
                "related_to": resolved_related_to,
                "project": resolved_project,
                "domain": resolved_domain,
                "status": resolved_status,
                "canonical": resolved_canonical,
                "updated_at": now,
                "chars": len(content),
                "lines": len(content.splitlines()),
            }
        )

        chunks = chunk_content_with_metadata(content)
        data["chunk_count"] = len(chunks)

        self._save_json(data)

        cleanup_warning = None
        try:
            self._delete_chunks_from_chroma(key)
        except Exception as e:
            cleanup_warning = (
                f"Failed to delete old indexed chunks for '{key}' before reindex: {e}"
            )

        return data, chunks, cleanup_warning

    def update_memory_metadata(self, key: str, **changes) -> dict:
        """Update metadata fields and reindex existing chunk content safely."""
        data, chunks, cleanup_warning = self._prepare_metadata_update(key, **changes)
        self._index_chunks(key, chunks, data)
        result = dict(data)
        if cleanup_warning:
            result["index_cleanup_warning"] = cleanup_warning
        return result

    async def update_memory_metadata_async(self, key: str, **changes) -> dict:
        """Async metadata update wrapper with JSON-first / Chroma-second ordering."""
        data, chunks, cleanup_warning = await _run_blocking(self._prepare_metadata_update, key, **changes)
        await self._index_chunks_async(key, chunks, data)
        result = dict(data)
        if cleanup_warning:
            result["index_cleanup_warning"] = cleanup_warning
        return result

    def _prepare_store(
        self,
        key: str,
        content: str,
        tags: list[str] = None,
        title: str = None,
        related_to: list[str] = None,
        force: bool = False,
        project: str = None,
        domain: str = None,
        status: str = None,
        canonical: Optional[bool] = None,
    ) -> tuple[dict, list[dict]]:
        """
        Shared preparation for store_memory / store_memory_async.
        Validates size, builds the data dict, writes JSON first (source of truth),
        then cleans up old ChromaDB chunks. Returns (data, chunks).
        Raises ValueError if content exceeds MAX_MEMORY_CHARS.
        Raises DuplicateMemoryError if near-duplicate detected and force=False.
        """
        # Dedup gate: check for near-duplicate content before writing (per D-01, DEDU-01)
        if not force:
            dup = self._check_dedup(content, key)
            if dup:
                raise DuplicateMemoryError(dup)

        # Preserve created_at and title if updating
        existing = self._load_json(key)
        now = _now()
        created_at = existing["created_at"] if existing else now
        resolved_title = title or (existing["title"] if existing else key)
        resolved_project = (
            _normalize_optional_text(project)
            if project is not None
            else (existing.get("project") if existing else None)
        )
        resolved_domain = (
            _normalize_optional_text(domain)
            if domain is not None
            else (existing.get("domain") if existing else None)
        )
        resolved_status = (
            _normalize_status(status)
            if status is not None
            else (existing.get("status") if existing else None)
        ) or DEFAULT_MEMORY_STATUS
        resolved_canonical = (
            _normalize_bool(existing.get("canonical"), default=False)
            if canonical is None and existing
            else _normalize_bool(canonical, default=False)
        )
        validation = self.validate_memory(
            content=content,
            related_to=related_to if related_to is not None else (existing.get("related_to") if existing else []),
            status=resolved_status,
            tags=tags if tags is not None else (existing.get("tags") if existing else []),
            title=resolved_title,
            project=resolved_project,
            domain=resolved_domain,
            canonical=resolved_canonical,
        )
        if not validation["valid"]:
            raise ValueError(self._validation_error_message(validation))

        normalized_fields = validation["normalized"]

        # Append audit log to content
        action = "Updated" if existing else "Created"
        content_with_log = f"{content}\n\n---\n**{now} | {action} via Engram**"

        data = {
            "key": key,
            "title": resolved_title,
            "content": content_with_log,
            "tags": normalized_fields["tags"],
            "created_at": created_at,
            "updated_at": now,
            "last_accessed": existing.get("last_accessed", None) if existing else None,
            "related_to": normalized_fields["related_to"],
            "project": normalized_fields["project"],
            "domain": normalized_fields["domain"],
            "status": normalized_fields["status"],
            "canonical": normalized_fields["canonical"],
            "chars": len(content_with_log),
            "lines": len(content_with_log.splitlines()),
        }
        data = self._normalize_memory_record(data)

        # 1. Chunk content and set count
        chunks = chunk_content_with_metadata(content_with_log)
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
        related_to: list[str] = None,
        force: bool = False,
        project: str = None,
        domain: str = None,
        status: str = None,
        canonical: Optional[bool] = None,
    ) -> dict:
        """
        Store or update a memory (sync — used by webui/CLI).
        Writes JSON first, then updates the vector index.
        Returns the stored memory metadata dict.
        Raises DuplicateMemoryError if near-duplicate detected and force=False.
        """
        data, chunks = self._prepare_store(
            key,
            content,
            tags,
            title,
            related_to,
            force,
            project,
            domain,
            status,
            canonical,
        )
        self._index_chunks(key, chunks, data)
        return data

    async def store_memory_async(
        self,
        key: str,
        content: str,
        tags: list[str] = None,
        title: str = None,
        related_to: list[str] = None,
        force: bool = False,
        project: str = None,
        domain: str = None,
        status: str = None,
        canonical: Optional[bool] = None,
    ) -> dict:
        """
        Store or update a memory (async — non-blocking for MCP).
        Writes JSON first, then updates the vector index without blocking the event loop.
        Raises DuplicateMemoryError if near-duplicate detected and force=False.
        """
        data, chunks = await _run_blocking(
            self._prepare_store,
            key,
            content,
            tags,
            title,
            related_to,
            force,
            project,
            domain,
            status,
            canonical,
        )
        await self._index_chunks_async(key, chunks, data)
        return data

    @staticmethod
    def _chunk_heading_path(meta: dict) -> list[str]:
        """Convert stored heading metadata back into a structured path."""
        heading_path = meta.get("heading_path", "")
        if not heading_path:
            return []
        return [part.strip() for part in str(heading_path).split(" > ") if part.strip()]

    @classmethod
    def _build_chunk_result(
        cls,
        *,
        key: str,
        chunk_id: Any,
        text: Optional[str] = None,
        meta: Optional[dict] = None,
        found: bool = False,
        error: Optional[dict] = None,
    ) -> dict:
        """Build a stable structured chunk payload for retrieval tools."""
        payload = {
            "key": key,
            "chunk_id": chunk_id,
            "found": found,
            "title": key,
            "text": None,
            "section_title": None,
            "heading_path": [],
            "chunk_kind": None,
        }

        if meta:
            payload["title"] = meta.get("title", key)
            payload["section_title"] = meta.get("section_title") or None
            payload["heading_path"] = cls._chunk_heading_path(meta)
            payload["chunk_kind"] = meta.get("chunk_kind") or None

        if found:
            payload["text"] = text
        if error:
            payload["error"] = error
        return payload

    @staticmethod
    def _chunk_error(code: str, message: str) -> dict:
        """Build a structured per-item error payload for batch retrieval."""
        return {
            "code": code,
            "message": message,
        }

    @staticmethod
    def _normalize_chunk_request(request: Any) -> dict:
        """Normalize a single chunk retrieval request for batch retrieval."""
        if not isinstance(request, dict):
            return {
                "key": "",
                "chunk_id": -1,
                "error": MemoryManager._chunk_error(
                    "invalid_request",
                    "request must be an object with key and chunk_id",
                ),
            }

        key = str(request.get("key", "")).strip()
        if not key:
            return {
                "key": "",
                "chunk_id": -1,
                "error": MemoryManager._chunk_error("invalid_request", "key is required"),
            }

        raw_chunk_id = request.get("chunk_id")
        if isinstance(raw_chunk_id, bool) or not isinstance(raw_chunk_id, int):
            return {
                "key": key,
                "chunk_id": raw_chunk_id,
                "error": MemoryManager._chunk_error(
                    "invalid_request",
                    "chunk_id must be an integer",
                ),
            }

        return {
            "key": key,
            "chunk_id": raw_chunk_id,
            "error": None,
        }

    def retrieve_memory(self, key: str) -> Optional[dict]:
        """Retrieve full memory content from JSON store."""
        return self._load_json(key)

    async def retrieve_memory_async(self, key: str) -> Optional[dict]:
        """Retrieve full memory content from JSON store (async — non-blocking for MCP)."""
        result = await _run_blocking(self._load_json, key)
        if result:
            asyncio.create_task(self._update_last_accessed_async([key]))
        return result

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

    def retrieve_chunks(self, requests: list[dict]) -> list[dict]:
        """
        Retrieve multiple chunks in one batch.
        Returns one structured result per request, preserving order.
        """
        if not requests:
            return []

        results: list[Optional[dict]] = [None] * len(requests)
        doc_ids: list[str] = []
        doc_positions: dict[str, list[tuple[int, str, int]]] = {}

        for index, request in enumerate(requests):
            normalized = self._normalize_chunk_request(request)
            key = normalized["key"]
            chunk_id = normalized["chunk_id"]
            error = normalized["error"]

            if error:
                results[index] = self._build_chunk_result(
                    key=key,
                    chunk_id=chunk_id,
                    found=False,
                    error=error,
                )
                continue

            doc_id = _chunk_doc_id(key, chunk_id)
            doc_ids.append(doc_id)
            doc_positions.setdefault(doc_id, []).append((index, key, chunk_id))

        if doc_ids:
            try:
                col = self._get_collection()
                raw = col.get(ids=list(dict.fromkeys(doc_ids)), include=["documents", "metadatas"])
                docs_by_id = {
                    doc_id: (document, meta)
                    for doc_id, document, meta in zip(
                        raw.get("ids", []),
                        raw.get("documents", []),
                        raw.get("metadatas", []),
                    )
                }

                for doc_id, positions in doc_positions.items():
                    document, meta = docs_by_id.get(doc_id, (None, None))
                    for index, key, chunk_id in positions:
                        if document is None:
                            results[index] = self._build_chunk_result(
                                key=key,
                                chunk_id=chunk_id,
                                found=False,
                            )
                            continue

                        results[index] = self._build_chunk_result(
                            key=key,
                            chunk_id=chunk_id,
                            text=document,
                            meta=meta,
                            found=True,
                        )
            except Exception as e:
                print(f"[Engram] retrieve_chunks failed: {e}", file=sys.stderr)
                for doc_id, positions in doc_positions.items():
                    for index, key, chunk_id in positions:
                        if results[index] is None:
                            results[index] = self._build_chunk_result(
                                key=key,
                                chunk_id=chunk_id,
                                found=False,
                                error=self._chunk_error(
                                    "runtime_error",
                                    "batch retrieval failed",
                                ),
                            )

        return [result for result in results if result is not None]

    async def retrieve_chunk_async(self, key: str, chunk_id: int) -> Optional[dict]:
        """Retrieve a specific chunk (async — non-blocking for MCP)."""
        result = await _run_chroma(self.retrieve_chunk, key, chunk_id)
        if result:
            asyncio.create_task(self._update_last_accessed_async([key]))
        return result

    def memory_exists(self, key: str) -> bool:
        """Check whether a memory exists without mutating access metadata."""
        return self._load_json(key) is not None

    async def memory_exists_async(self, key: str) -> bool:
        """Async existence check that does not update last_accessed."""
        return await _run_blocking(self.memory_exists, key)

    async def retrieve_chunks_async(self, requests: list[dict]) -> list[dict]:
        """Retrieve multiple chunks (async — non-blocking for MCP)."""
        results = await _run_chroma(self.retrieve_chunks, requests)
        found_keys = list({result["key"] for result in results if result.get("found")})
        if found_keys:
            asyncio.create_task(self._update_last_accessed_async(found_keys))
        return results

    def search_memories(self, query: str, limit: int = 5) -> list[dict]:
        """
        Semantic search across all memory chunks.
        Returns scored snippets — NOT full content.
        Each result: {key, chunk_id, title, score, snippet, tags}
        """
        normalized_limit = self._normalize_limit(limit)
        if normalized_limit == 0:
            return []

        query_embedding = embedder.embed(query)

        try:
            results = self._query_semantic_results(query_embedding, normalized_limit)
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
            score = MemoryManager._score_from_distance(distance)
            parent_key = meta.get("parent_key", "unknown")
            output.append({
                "key": parent_key,
                "chunk_id": int(meta.get("chunk_id", 0)),
                "title": meta.get("title", parent_key),
                "tags": [t.strip() for t in meta.get("tags", "").split(",") if t.strip()],
                "score": score,
                "snippet": MemoryManager._make_snippet(doc),
            })

        # Sort by score descending
        output.sort(key=lambda x: x["score"], reverse=True)
        return output

    async def search_memories_async(self, query: str, limit: int = 5) -> list[dict]:
        """
        Async semantic search (non-blocking for MCP).
        Embedding runs in the embedder's executor, ChromaDB query runs in the
        dedicated Chroma executor via _run_chroma(). Same return format as
        search_memories(). Nothing touches the event loop directly.
        """
        normalized_limit = self._normalize_limit(limit)
        if normalized_limit == 0:
            return []

        query_embedding = await embedder.embed_async(query)

        def _do_query():
            try:
                return self._query_semantic_results(query_embedding, normalized_limit)
            except Exception as e:
                print(f"[Engram] search failed: {e}", file=sys.stderr)
                return None

        raw = await _run_chroma(_do_query)
        results = self._parse_search_results(raw)
        if results:
            keys = list({r["key"] for r in results})
            asyncio.create_task(self._update_last_accessed_async(keys))
        return results

    def search_memories_structured(
        self,
        query: str,
        limit: int = 5,
        project: str = None,
        domain: str = None,
        tags: Any = None,
        include_stale: bool = True,
        canonical_only: bool = False,
        pinned_keys: Any = None,
        pinned_first: bool = False,
    ) -> dict:
        """
        Semantic search with additive metadata filters and explanations.
        Returns {query, count, results}, where results are enriched chunk matches.
        """
        if not query.strip():
            return {"query": query, "count": 0, "results": []}

        normalized_limit = self._normalize_limit(limit)
        if normalized_limit == 0:
            return {"query": query, "count": 0, "results": []}

        query_embedding = embedder.embed(query)
        try:
            raw = self._query_structured_semantic_results(query_embedding)
        except Exception as e:
            print(f"[Engram] structured search failed: {e}", file=sys.stderr)
            return {"query": query, "count": 0, "results": []}

        return self._build_structured_payload(
            query=query,
            raw_results=raw,
            limit=normalized_limit,
            project=project,
            domain=domain,
            tags=tags,
            include_stale=include_stale,
            canonical_only=canonical_only,
            pinned_keys=pinned_keys,
            pinned_first=pinned_first,
        )

    async def search_memories_structured_async(
        self,
        query: str,
        limit: int = 5,
        project: str = None,
        domain: str = None,
        tags: Any = None,
        include_stale: bool = True,
        canonical_only: bool = False,
        pinned_keys: Any = None,
        pinned_first: bool = False,
    ) -> dict:
        """Async wrapper for structured semantic search."""
        if not query.strip():
            return {"query": query, "count": 0, "results": []}

        normalized_limit = self._normalize_limit(limit)
        if normalized_limit == 0:
            return {"query": query, "count": 0, "results": []}

        query_embedding = await embedder.embed_async(query)

        def _do_query():
            try:
                return self._query_structured_semantic_results(query_embedding)
            except Exception as e:
                print(f"[Engram] structured search failed: {e}", file=sys.stderr)
                return None

        raw = await _run_chroma(_do_query)
        payload = self._build_structured_payload(
            query=query,
            raw_results=raw,
            limit=normalized_limit,
            project=project,
            domain=domain,
            tags=tags,
            include_stale=include_stale,
            canonical_only=canonical_only,
            pinned_keys=pinned_keys,
            pinned_first=pinned_first,
        )
        if payload["results"]:
            keys = list({result["key"] for result in payload["results"]})
            asyncio.create_task(self._update_last_accessed_async(keys))
        return payload

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
        #    Retry on Windows PermissionError (fire-and-forget tasks may hold the file briefly)
        import time as _time
        for attempt in range(3):
            try:
                path.unlink()
                break
            except PermissionError:
                if attempt < 2:
                    _time.sleep(0.05)
                else:
                    raise
        return True

    async def delete_memory_async(self, key: str) -> bool:
        """Delete memory (async — non-blocking for MCP)."""
        return await _run_chroma(self.delete_memory, key)

    def get_related_memories(self, key: str) -> dict:
        """
        Return all memories related to the given key, bidirectionally.
        Forward: memories that key explicitly links to (key's related_to list).
        Reverse: memories that have key in their related_to list.
        Silently skips dangling references (D-07).
        Returns: {key, found, forward: [{key, title, tags, updated_at}], reverse: [...]}
        """
        source = self._load_json(key)
        if source is None:
            return {"key": key, "found": False, "forward": [], "reverse": []}

        forward_keys = source.get("related_to", [])
        reverse_keys = []

        for path in JSON_DIR.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("key") == key:
                    continue  # skip self
                if key in data.get("related_to", []):
                    reverse_keys.append(data["key"])
            except Exception:
                continue

        def _resolve(keys: list[str]) -> list[dict]:
            result = []
            for k in keys:
                mem = self._load_json(k)
                if mem is None:
                    continue  # silently skip dangling refs (D-07)
                result.append({
                    "key": k,
                    "title": mem.get("title", k),
                    "tags": mem.get("tags", []),
                    "updated_at": mem.get("updated_at", ""),
                })
            return result

        return {
            "key": key,
            "found": True,
            "forward": _resolve(forward_keys),
            "reverse": _resolve(reverse_keys),
        }

    async def get_related_memories_async(self, key: str) -> dict:
        """Async wrapper for get_related_memories (non-blocking for MCP)."""
        return await _run_blocking(self.get_related_memories, key)

    def get_stale_memories(self, days: int = None, type: str = "all") -> list[dict]:
        """
        Return memories that are time-stale (not accessed in N days) or code-stale
        (potentially_stale flag set by indexer evolve mode).

        No memory is ever deleted — surfacing only (STAL-04).

        Args:
            days: Threshold in days for time-staleness. None = use config stale_days (default 90).
            type: Filter — 'time' (access-based), 'code' (indexer-flagged), 'all' (both).

        Returns:
            List of dicts with key, title, tags, stale_type, stale_detail, last_accessed, stale_flagged_at.
        """
        threshold_days = days if days is not None else _config.get("stale_days", 90)
        results = []

        for path in JSON_DIR.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = self._normalize_memory_record(json.load(f))
            except Exception:
                continue

            stale_info = self._memory_stale_state(data, threshold_days)
            if not stale_info["stale_type"]:
                continue

            # Apply type filter
            if type == "time" and not stale_info["is_time_stale"]:
                continue
            if type == "code" and not stale_info["is_code_stale"]:
                continue

            results.append({
                "key": data.get("key", ""),
                "title": data.get("title", data.get("key", "")),
                "tags": data.get("tags", []),
                "stale_type": stale_info["stale_type"],
                "stale_detail": stale_info["stale_detail"],
                "last_accessed": stale_info["last_accessed"],
                "stale_flagged_at": stale_info["stale_flagged_at"],
                "_days_since": stale_info["days_since"],
            })

        # Sort: code-stale entries first by stale_flagged_at desc, then time entries by days_since desc
        def _sort_key(r):
            # Code entries first (stale_type "code" or "both"), then time
            is_code = 0 if r["stale_type"] in ("code", "both") else 1
            return (is_code, -r["_days_since"])

        results.sort(key=_sort_key)

        # Strip internal sort key
        for r in results:
            del r["_days_since"]

        return results

    async def get_stale_memories_async(self, days: int = None, type: str = "all") -> list[dict]:
        """Async wrapper for get_stale_memories (non-blocking for MCP)."""
        return await _run_blocking(self.get_stale_memories, days, type)

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
                    data = self._normalize_memory_record(json.load(f))
                chunks = chunk_content_with_metadata(data["content"])
                self._index_chunks(data["key"], chunks, data)
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
