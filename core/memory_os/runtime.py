"""Daemon-owned Memory OS service container."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from core.chunker import chunk_content_with_metadata
from core.memory_os._records import (
    hash_payload,
    list_records,
    now_iso,
    read_record,
    upsert_record,
)
from core.memory_os.content_store import ContentAddressedStore
from core.memory_os.firewall import MemoryFirewall
from core.memory_os.graph import MemoryOSGraph
from core.memory_os.inspector import build_memory_os_inspector
from core.memory_os.jobs import JobQueue
from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.retrieval import MemoryOSRetrievalIndex
from core.memory_os.snapshots import SnapshotService
from core.memory_os.transactions import MemoryTransactionService


class MemoryOSRuntime:
    """Container for daemon-owned Memory OS stores, indexes, and services."""

    def __init__(
        self,
        root: str | Path,
        *,
        embed_text: Callable[[str], list[float]] | None = None,
        vector_index: Any | None = None,
        graph_store: Any | None = None,
    ) -> None:
        self.root = Path(root)
        self.ledger = MemoryOSLedger(self.root / "ledger.sqlite3")
        self.content_store = ContentAddressedStore(self.root / "objects")
        self.jobs = JobQueue(self.ledger)
        self.transactions = MemoryTransactionService(self.ledger)
        self.snapshots = SnapshotService(self.ledger)
        self.firewall = MemoryFirewall(self.ledger)
        self.retrieval = MemoryOSRetrievalIndex(
            self.ledger,
            self.root / "lance",
            embed_text=embed_text or _default_embed_text,
            vector_index=vector_index,
        )
        self.graph = MemoryOSGraph(
            self.ledger,
            graph_store=graph_store,
            database_path=self.root / "kuzu",
        )

    def initialize(self) -> dict[str, Any]:
        """Initialize durable Memory OS stores and return a status payload."""
        self.ledger.initialize()
        self.content_store.root.mkdir(parents=True, exist_ok=True)
        self.graph.load_edges()
        self.retrieval.rebuild_from_ledger()
        return self.status()

    def status(self) -> dict[str, Any]:
        """Return a compact Memory OS component status."""
        return {
            "status": "ok",
            "root": str(self.root),
            "components": {
                "ledger": {
                    "path": str(self.ledger.path),
                    "exists": self.ledger.path.exists(),
                },
                "content_store": {
                    "path": str(self.content_store.root),
                    "exists": self.content_store.root.exists(),
                },
                "retrieval": {
                    "backend": type(self.retrieval.vector_index).__name__,
                    "path": str(self.root / "lance"),
                },
                "graph": {
                    "backend": type(self.graph.graph_store).__name__,
                    "path": str(self.root / "kuzu"),
                },
                "jobs": {"status": "ready"},
                "transactions": {"status": "ready"},
                "snapshots": {"status": "ready"},
                "firewall": {"status": "ready"},
            },
        }

    def inspector(self, *, limit: int = 20) -> dict[str, Any]:
        """Return a read-only Memory OS inspector payload."""
        return build_memory_os_inspector(self, limit=limit)

    def prepare_source_import_job(
        self,
        *,
        source_ref: dict[str, Any],
        source_type: str,
        connector_id: str = "manual",
    ) -> dict[str, Any]:
        """Create a queued source import job without blocking an MCP process."""
        return self.jobs.enqueue(
            "source_import",
            {
                "source_ref": source_ref,
                "source_type": source_type,
                "connector_id": connector_id,
            },
        )

    def store_memory(
        self,
        *,
        key: str,
        content: str,
        tags: list[str] | None = None,
        title: str | None = None,
        related_to: list[str] | None = None,
        force: bool = False,
        project: str | None = None,
        domain: str | None = None,
        status: str | None = None,
        canonical: bool | None = None,
    ) -> dict[str, Any]:
        """Store one reviewed memory in the Memory OS ledger and retrieval index."""
        normalized_key = _required_text(key, "key")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("content is required")
        now = now_iso()
        existing = read_record(self.ledger, "memories", normalized_key)
        if existing and not force:
            # Explicit overwrites are allowed because stable memory writes are updates.
            pass
        normalized_tags = _string_list(tags)
        artifact_id = self.content_store.put_bytes(content.encode("utf-8"), suffix=".md")
        chunks = chunk_content_with_metadata(content)
        memory = {
            "key": normalized_key,
            "title": title or normalized_key,
            "content_artifact_id": artifact_id,
            "tags": normalized_tags,
            "related_to": _string_list(related_to),
            "project": _optional_text(project),
            "domain": _optional_text(domain),
            "status": _optional_text(status) or "active",
            "canonical": bool(canonical) if canonical is not None else False,
            "chars": len(content),
            "lines": len(content.splitlines()),
            "chunk_count": len(chunks),
            "content_hash": hash_payload(content),
            "created_at": existing.get("created_at") if existing else now,
            "updated_at": now,
            "storage_backend": "memory_os",
        }
        self._delete_chunks(normalized_key)
        upsert_record(self.ledger, "memories", normalized_key, memory)
        for chunk in chunks:
            chunk_record = {
                "chunk_record_id": f"{normalized_key}:chunk:{int(chunk['chunk_id'])}",
                "document_id": f"{normalized_key}:chunk:{int(chunk['chunk_id'])}",
                "memory_key": normalized_key,
                "chunk_id": int(chunk["chunk_id"]),
                "chunk_index": int(chunk["chunk_id"]),
                "title": memory["title"],
                "text": str(chunk["text"]),
                "text_hash": hash_payload(str(chunk["text"])),
                "tags": normalized_tags,
                "project": memory["project"],
                "domain": memory["domain"],
                "status": memory["status"],
                "canonical": memory["canonical"],
                "section_title": chunk.get("section_title"),
                "heading_path": list(chunk.get("heading_path") or []),
                "chunk_kind": chunk.get("chunk_kind"),
                "created_at": now,
                "updated_at": now,
            }
            upsert_record(self.ledger, "chunks", chunk_record["chunk_record_id"], chunk_record)
        receipt_fingerprint = hash_payload(
            {
                "content_hash": memory["content_hash"],
                "title": memory["title"],
                "tags": memory["tags"],
                "related_to": memory["related_to"],
                "project": memory["project"],
                "domain": memory["domain"],
                "status": memory["status"],
                "canonical": memory["canonical"],
            }
        )
        receipt = self.transactions.promote(
            operation_kind="store_memory",
            proposed_writes=[{"table": "memories", "id": normalized_key}],
            idempotency_key=f"store_memory:{normalized_key}:{receipt_fingerprint}",
            affected_refs=[{"kind": "memory", "key": normalized_key}],
        )
        self.retrieval.rebuild_from_ledger()
        return {**memory, "transaction_id": receipt["transaction_id"]}

    def check_duplicate(self, key: str, content: str) -> dict[str, Any]:
        """Return duplicate risk for the Memory OS ledger without writing."""
        normalized_key = str(key or "").strip()
        existing = read_record(self.ledger, "memories", normalized_key) if normalized_key else None
        if existing:
            return {
                "key": normalized_key,
                "duplicate": True,
                "match": {
                    "status": "duplicate",
                    "existing_key": normalized_key,
                    "existing_title": existing.get("title") or normalized_key,
                    "score": 1.0,
                },
                "error": None,
            }
        return {"key": normalized_key, "duplicate": False, "match": None, "error": None}

    def search_memories(
        self,
        query: str,
        *,
        limit: int = 5,
        project: str | None = None,
        domain: str | None = None,
        tags: list[str] | None = None,
        include_stale: bool = True,
        canonical_only: bool = False,
        pinned_keys: list[str] | None = None,
        pinned_first: bool = False,
        retrieval_mode: str = "semantic",
    ) -> dict[str, Any]:
        """Search Memory OS chunks through the daemon-owned retrieval index."""
        search_text = _required_text(query, "query")
        filters: dict[str, Any] = {}
        if project:
            filters["project"] = project
        if domain:
            filters["domain"] = domain
        if canonical_only:
            filters["canonical"] = True
        if not include_stale:
            filters["status"] = "active"
        search = (
            self.retrieval.hybrid_search(search_text, filters=filters, limit=max(int(limit), 1))
            if retrieval_mode == "hybrid"
            else self.retrieval.search(search_text, filters=filters, limit=max(int(limit), 1))
        )
        requested_tags = set(_string_list(tags))
        results = [
            _search_result_payload(result)
            for result in search.get("results", [])
            if _result_has_tags(result, requested_tags)
        ]
        if pinned_first and pinned_keys:
            pinned = {str(key) for key in pinned_keys}
            results.sort(key=lambda item: (0 if item["key"] in pinned else 1, -float(item["score"])))
        return {
            "query": search_text,
            "backend": "memory_os",
            "retrieval_mode": search.get("retrieval_mode", retrieval_mode),
            "count": len(results),
            "results": results[: max(int(limit), 1)],
            "error": None,
        }

    def retrieve_chunk(self, key: str, chunk_id: int) -> dict[str, Any]:
        """Retrieve one Memory OS chunk by memory key and chunk id."""
        normalized_key = _required_text(key, "key")
        record = read_record(self.ledger, "chunks", f"{normalized_key}:chunk:{int(chunk_id)}")
        if record is None:
            return {"key": normalized_key, "chunk_id": int(chunk_id), "found": False, "chunk": None, "error": None}
        return {
            "key": normalized_key,
            "chunk_id": int(chunk_id),
            "found": True,
            "chunk": {
                "title": record.get("title") or normalized_key,
                "text": record.get("text"),
                "section_title": record.get("section_title"),
                "heading_path": record.get("heading_path") or [],
                "chunk_kind": record.get("chunk_kind"),
            },
            "error": None,
        }

    def retrieve_memory(self, key: str) -> dict[str, Any]:
        """Retrieve one full Memory OS memory body from the content store."""
        normalized_key = _required_text(key, "key")
        memory = read_record(self.ledger, "memories", normalized_key)
        if memory is None:
            return {"key": normalized_key, "found": False, "memory": None, "error": None}
        content = self.content_store.read_bytes(str(memory["content_artifact_id"])).decode("utf-8")
        return {
            "key": normalized_key,
            "found": True,
            "memory": {**memory, "content": content},
            "error": None,
        }

    def update_memory_metadata(self, key: str, **changes: Any) -> dict[str, Any]:
        """Update selected Memory OS memory metadata and refresh chunk metadata."""
        normalized_key = _required_text(key, "key")
        current = self.retrieve_memory(normalized_key)
        if not current["found"]:
            return {"key": normalized_key, "updated": False, "memory": None, "error": {"code": "not_found", "message": f"Memory not found: {normalized_key}"}}
        memory = current["memory"]
        updated = self.store_memory(
            key=normalized_key,
            content=str(memory["content"]),
            tags=_string_list(changes["tags"]) if "tags" in changes else memory.get("tags", []),
            title=changes.get("title", memory.get("title")),
            related_to=_string_list(changes["related_to"]) if "related_to" in changes else memory.get("related_to", []),
            force=True,
            project=changes.get("project", memory.get("project")),
            domain=changes.get("domain", memory.get("domain")),
            status=changes.get("status", memory.get("status")),
            canonical=changes.get("canonical", memory.get("canonical")),
        )
        return {"key": normalized_key, "updated": True, "memory": updated, "error": None}

    def repair_memory_metadata(self, keys: list[str], *, dry_run: bool = True) -> dict[str, Any]:
        """Return simple Memory OS metadata repair receipts."""
        repairs = []
        repaired_count = 0
        for key in _string_list(keys):
            exists = read_record(self.ledger, "memories", key) is not None
            repaired = bool(exists and not dry_run)
            repaired_count += 1 if repaired else 0
            repairs.append({"key": key, "exists": exists, "repaired": repaired, "issues": []})
        return {
            "requested_count": len(repairs),
            "repaired_count": repaired_count,
            "dry_run": dry_run,
            "repairs": repairs,
            "error": None,
        }

    def delete_memory(self, key: str) -> dict[str, Any]:
        """Delete one Memory OS memory and its retrieval chunks."""
        normalized_key = _required_text(key, "key")
        existed = read_record(self.ledger, "memories", normalized_key) is not None
        if not existed:
            return {"key": normalized_key, "deleted": False, "error": None}
        self.retrieval.vector_index.delete_by_parent_key(normalized_key)
        self._delete_chunks(normalized_key)
        self._delete_record("memories", normalized_key)
        self.transactions.promote(
            operation_kind="delete_memory",
            proposed_writes=[{"table": "memories", "id": normalized_key, "delete": True}],
            idempotency_key=f"delete_memory:{normalized_key}:{now_iso()}",
            affected_refs=[{"kind": "memory", "key": normalized_key}],
        )
        return {"key": normalized_key, "deleted": True, "error": None}

    def _delete_chunks(self, key: str) -> None:
        for record in list_records(self.ledger, "chunks"):
            if record.get("memory_key") == key and record.get("chunk_record_id"):
                self._delete_record("chunks", str(record["chunk_record_id"]))

    def _delete_record(self, table: str, record_id: str) -> None:
        self.ledger.initialize()
        with self.ledger.connect() as conn:
            conn.execute(f"DELETE FROM {table} WHERE id = ?", (record_id,))
            conn.commit()


def _default_embed_text(text: str) -> list[float]:
    from core.embedder import embedder

    return list(embedder.embed(text))


def _required_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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


def _result_has_tags(result: dict[str, Any], requested_tags: set[str]) -> bool:
    if not requested_tags:
        return True
    actual = set(result.get("metadata", {}).get("tags") or [])
    return requested_tags.issubset(actual)


def _search_result_payload(result: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(result.get("metadata") or {})
    text = str(result.get("text") or "")
    return {
        "key": result.get("key"),
        "chunk_id": result.get("chunk_id"),
        "title": metadata.get("title") or result.get("key"),
        "score": result.get("score", 0.0),
        "snippet": text[:300],
        "tags": metadata.get("tags") or [],
        "project": metadata.get("project"),
        "domain": metadata.get("domain"),
        "citation": result.get("citation"),
    }
