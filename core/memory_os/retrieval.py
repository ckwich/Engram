"""Memory OS retrieval service over migrated ledger chunks."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any, Callable

from core.lancedb_vector_index import LanceDBVectorIndex
from core.memory_os._records import hash_payload, list_records
from core.memory_os.document_catalog import enrich_document_record, merge_catalog_into_chunk_metadata
from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.memory_activation import score_activation
from core.memory_os_migration import MemoryOSMigrationKernel, build_vector_index_documents
from core.vector_index import VectorIndex, VectorIndexQuery, VectorIndexSearchResult


MANIFEST_FILENAME = ".engram_retrieval_manifest.json"
MANIFEST_HASH_VERIFIED = "verified"
MANIFEST_HASH_DEFERRED = "deferred"


class MemoryOSRetrievalIndex:
    """Rebuild and query a vector index from Memory OS ledger chunk records."""

    def __init__(
        self,
        ledger: MemoryOSLedger,
        index_uri: str | Path,
        *,
        embed_text: Callable[[str], list[float]],
        vector_index: VectorIndex | None = None,
    ) -> None:
        self.ledger = ledger
        self.index_uri = Path(index_uri)
        self.embed_text = embed_text
        self.vector_index = vector_index or LanceDBVectorIndex(self.index_uri)

    def rebuild_from_ledger(self, *, force: bool = False) -> dict[str, Any]:
        sources = self._read_vector_sources()
        source_manifest_hash = self._source_manifest_hash(sources)
        stats = self.vector_index.stats()
        existing = self._read_manifest()
        if not force and self._manifest_matches_sources(
            existing,
            source_manifest_hash=source_manifest_hash,
            source_count=len(sources),
            stats=stats,
        ):
            return {
                **existing,
                "stats": stats,
                "rebuild_skipped": True,
            }
        embeddings = {
            str(source["document_id"]): self.embed_text(str(source["text"]))
            for source in sources
        }
        documents = build_vector_index_documents(sources, embeddings)
        self.vector_index.rebuild(documents)
        manifest = {
            "backend": type(self.vector_index).__name__,
            "source_count": len(sources),
            "indexed_count": len(documents),
            "source_manifest_hash": source_manifest_hash,
            "source_manifest_hash_status": MANIFEST_HASH_VERIFIED,
            "manifest_refresh_required": False,
            "stats": self.vector_index.stats(),
            "rebuild_skipped": False,
        }
        self._write_manifest(manifest)
        return manifest

    def refresh_manifest_from_ledger(self) -> dict[str, Any]:
        """Refresh the persisted retrieval manifest after incremental index writes."""
        sources = self._read_vector_sources()
        stats = self.vector_index.stats()
        manifest = {
            "backend": type(self.vector_index).__name__,
            "source_count": len(sources),
            "indexed_count": int(stats.get("document_count", 0)),
            "source_manifest_hash": self._source_manifest_hash(sources),
            "source_manifest_hash_status": MANIFEST_HASH_VERIFIED,
            "manifest_refresh_required": False,
            "stats": stats,
            "rebuild_skipped": False,
        }
        self._write_manifest(manifest)
        return manifest

    def mark_incremental_manifest_refresh_required(
        self,
        *,
        reason: str,
        parent_key: str,
        indexed_count: int = 0,
        deleted_count: int = 0,
    ) -> dict[str, Any]:
        """Persist a small retrieval manifest receipt without scanning all chunks."""
        normalized_parent_key = str(parent_key or "").strip()
        stats = self.vector_index.stats()
        document_count = int(stats.get("document_count", 0))
        manifest = {
            "backend": type(self.vector_index).__name__,
            "source_count": document_count,
            "indexed_count": document_count,
            "source_manifest_hash": None,
            "source_manifest_hash_status": MANIFEST_HASH_DEFERRED,
            "manifest_refresh_required": True,
            "deferred_reason": str(reason or "incremental_write"),
            "stats": stats,
            "rebuild_skipped": False,
            "last_incremental_update": {
                "parent_key": normalized_parent_key,
                "indexed_count": int(indexed_count),
                "deleted_count": int(deleted_count),
            },
        }
        self._write_manifest(manifest)
        return manifest

    def existing_index_state(self) -> dict[str, Any]:
        """Return a ready state for an already materialized retrieval index."""
        sources = self._read_vector_sources()
        source_count = len(sources)
        source_manifest_hash = self._source_manifest_hash(sources)
        stats = self.vector_index.stats()
        document_count = int(stats.get("document_count", 0))
        if document_count < 1:
            if source_count > 0:
                return self._stale_index_state(
                    status="needs_rebuild",
                    manifest=self._read_manifest(),
                    stats=stats,
                    source_count=source_count,
                    source_manifest_hash=source_manifest_hash,
                    mismatches=["vector_index_empty"],
                )
            return {
                "status": "deferred",
                "ready": False,
                "manifest": None,
                "error": None,
            }
        manifest = self._read_manifest()
        if self._manifest_matches_sources(
            manifest,
            source_manifest_hash=source_manifest_hash,
            source_count=source_count,
            stats=stats,
        ):
            return {
                "status": "ready_existing",
                "ready": True,
                "manifest": {
                    **manifest,
                    "stats": stats,
                    "indexed_count": document_count,
                    "rebuild_skipped": True,
                },
                "error": None,
            }
        mismatches = self._manifest_mismatches(
            manifest,
            source_manifest_hash=source_manifest_hash,
            source_count=source_count,
            stats=stats,
        )
        status = "needs_rebuild" if "indexed_count" in mismatches else "stale_manifest"
        return self._stale_index_state(
            status=status,
            manifest=manifest,
            stats=stats,
            source_count=source_count,
            source_manifest_hash=source_manifest_hash,
            mismatches=mismatches,
        )

    def _stale_index_state(
        self,
        *,
        status: str,
        manifest: dict[str, Any] | None,
        stats: dict[str, Any],
        source_count: int,
        source_manifest_hash: str,
        mismatches: list[str],
    ) -> dict[str, Any]:
        current = {
            "backend": type(self.vector_index).__name__,
            "source_count": source_count,
            "indexed_count": int(stats.get("document_count", 0)),
            "source_manifest_hash": source_manifest_hash,
            "stats": stats,
            "rebuild_skipped": True,
        }
        return {
            "status": status,
            "ready": False,
            "manifest": current,
            "persisted_manifest": manifest,
            "error": None,
            "diagnostics": {
                "gate": "retrieval_manifest_consistency",
                "mismatches": mismatches,
                "source_count": source_count,
                "indexed_count": current["indexed_count"],
                "source_manifest_hash": source_manifest_hash,
                "persisted_source_count": _manifest_int(manifest, "source_count"),
                "persisted_indexed_count": _manifest_int(manifest, "indexed_count"),
                "persisted_source_manifest_hash": (manifest or {}).get("source_manifest_hash"),
            },
            "repair_guidance": (
                "Retrieval index is not current with the Memory OS ledger. "
                "Rebuild retrieval from the ledger before trusting search coverage."
            ),
        }

    def source_record_count(self) -> int:
        """Return the current chunk-source count without loading chunk payloads."""
        self.ledger.initialize()
        with self.ledger.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM chunks").fetchone()
        return int(row["count"] if row is not None else 0)

    def upsert_chunk_records(
        self,
        parent_key: str,
        chunk_records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Replace indexed chunks for one memory/source key without rebuilding all rows."""
        normalized_parent_key = str(parent_key or "").strip()
        if not normalized_parent_key:
            raise ValueError("parent_key is required")
        sources = [_generic_chunk_source(record) for record in chunk_records]
        embeddings = {
            str(source["document_id"]): self.embed_text(str(source["text"]))
            for source in sources
        }
        documents = build_vector_index_documents(sources, embeddings)
        deleted_count = self.vector_index.delete_by_parent_key(normalized_parent_key)
        self.vector_index.upsert_many(documents)
        stats = self.vector_index.stats()
        manifest = self.mark_incremental_manifest_refresh_required(
            reason="upsert_chunk_records",
            parent_key=normalized_parent_key,
            indexed_count=len(documents),
            deleted_count=deleted_count,
        )
        return {
            "backend": type(self.vector_index).__name__,
            "parent_key": normalized_parent_key,
            "deleted_count": deleted_count,
            "indexed_count": len(documents),
            "stats": stats,
            "manifest": manifest,
            "manifest_refresh_required": True,
        }

    def search(
        self,
        query: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        return self._search(query, filters=filters, limit=limit, retrieval_mode="semantic")

    def hybrid_search(
        self,
        query: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        return self._search(query, filters=filters, limit=limit, retrieval_mode="hybrid")

    def _search(
        self,
        query: str,
        *,
        filters: dict[str, Any] | None,
        limit: int,
        retrieval_mode: str,
    ) -> dict[str, Any]:
        requested_limit = max(int(limit), 1)
        candidate_limit = max(requested_limit, requested_limit * 4)
        results = self.vector_index.search(
            VectorIndexQuery(
                query_text=query,
                query_embedding=self.embed_text(query),
                limit=candidate_limit,
                filters=filters or {},
                retrieval_mode=retrieval_mode,
            )
        )
        payloads = _dedupe_result_payloads([self._result_payload(result) for result in results])
        payloads = payloads[:requested_limit]
        query_context = {"query": query, **(filters or {})}
        for payload in payloads:
            metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            payload["activation"] = score_activation(metadata, query_context=query_context)
        return {
            "query": query,
            "retrieval_mode": retrieval_mode,
            "count": len(payloads),
            "results": payloads,
        }

    def _read_vector_sources(self) -> list[dict[str, Any]]:
        kernel = MemoryOSMigrationKernel(self.ledger.path.parent)
        try:
            return kernel.read_vector_source_records()
        except sqlite3.DatabaseError:
            document_context = _document_context_by_id(self.ledger)
            ingestion_context = _document_ingestion_context_by_id(self.ledger)
            return [
                _generic_chunk_source(
                    record,
                    document_context=document_context,
                    ingestion_context=ingestion_context,
                )
                for record in list_records(self.ledger, "chunks")
            ]

    def _manifest_path(self) -> Path:
        return self.index_uri / MANIFEST_FILENAME

    def _read_manifest(self) -> dict[str, Any] | None:
        path = self._manifest_path()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _write_manifest(self, manifest: dict[str, Any]) -> None:
        self.index_uri.mkdir(parents=True, exist_ok=True)
        path = self._manifest_path()
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(path)

    @staticmethod
    def _source_manifest_hash(sources: list[dict[str, Any]]) -> str:
        return hash_payload(
            [
                {
                    "document_id": source["document_id"],
                    "parent_key": source["parent_key"],
                    "chunk_id": source["chunk_id"],
                    "text_hash": source.get("metadata", {}).get("text_hash"),
                    "metadata_hash": hash_payload(source.get("metadata", {})),
                }
                for source in sources
            ]
        )

    @staticmethod
    def _manifest_matches_sources(
        manifest: dict[str, Any] | None,
        *,
        source_manifest_hash: str,
        source_count: int,
        stats: dict[str, Any],
    ) -> bool:
        if not manifest:
            return False
        if manifest.get("manifest_refresh_required") is True:
            return False
        if manifest.get("source_manifest_hash_status", MANIFEST_HASH_VERIFIED) != MANIFEST_HASH_VERIFIED:
            return False
        document_count = int(stats.get("document_count", 0))
        return (
            manifest.get("source_manifest_hash") == source_manifest_hash
            and _manifest_int(manifest, "source_count") == source_count
            and _manifest_int(manifest, "indexed_count") == source_count
            and document_count == source_count
        )

    @staticmethod
    def _manifest_mismatches(
        manifest: dict[str, Any] | None,
        *,
        source_manifest_hash: str,
        source_count: int,
        stats: dict[str, Any],
    ) -> list[str]:
        mismatches: list[str] = []
        document_count = int(stats.get("document_count", 0))
        if not manifest:
            mismatches.append("missing_manifest")
        if (manifest or {}).get("manifest_refresh_required") is True:
            mismatches.append("source_manifest_hash_pending")
        elif (manifest or {}).get("source_manifest_hash_status", MANIFEST_HASH_VERIFIED) != MANIFEST_HASH_VERIFIED:
            mismatches.append("source_manifest_hash_pending")
        elif (manifest or {}).get("source_manifest_hash") != source_manifest_hash:
            mismatches.append("source_manifest_hash")
        if _manifest_int(manifest, "source_count") != source_count:
            mismatches.append("source_count")
        if _manifest_int(manifest, "indexed_count") != source_count:
            mismatches.append("manifest_indexed_count")
        if document_count != source_count:
            mismatches.append("indexed_count")
        return mismatches

    @staticmethod
    def _result_payload(result: VectorIndexSearchResult) -> dict[str, Any]:
        return {
            "document_id": result.document_id,
            "key": result.parent_key,
            "chunk_id": result.chunk_id,
            "text": result.text,
            "score": result.score,
            "metadata": result.metadata,
            "citation": result.citation
            or {
                "source": "memory_os_retrieval",
                "key": result.parent_key,
                "chunk_id": result.chunk_id,
                "document_id": result.document_id,
            },
        }


def _generic_chunk_source(
    record: dict[str, Any],
    *,
    document_context: dict[str, dict[str, Any]] | None = None,
    ingestion_context: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    logical_document_id = str(record.get("document_id") or "").strip()
    chunk_record_id = str(record.get("chunk_record_id") or "").strip()
    key = str(
        record.get("memory_key")
        or record.get("key")
        or record.get("parent_key")
        or logical_document_id
        or ""
    )
    chunk_id = int(record.get("chunk_id", 0))
    document_id = (
        chunk_record_id
        if chunk_record_id and not record.get("memory_key")
        else str(record.get("document_id") or f"{key}:chunk:{chunk_id}")
    )
    text = str(record.get("text") or "")
    metadata = dict(record.get("metadata") or {})
    for field in (
        "title",
        "tags",
        "project",
        "domain",
        "status",
        "canonical",
        "memory_type",
        "scope",
        "trust_state",
        "retention_policy",
        "sync_policy",
        "section_title",
        "heading_path",
        "chunk_kind",
    ):
        if field in record and field not in metadata:
            metadata[field] = record[field]
    if logical_document_id and not record.get("memory_key"):
        _merge_document_chunk_metadata(
            metadata,
            logical_document_id,
            chunk_record_id,
            record=record,
            document_context=document_context or {},
            ingestion_context=ingestion_context or {},
        )
    metadata.setdefault("text_hash", hash_payload(text))
    return {
        "document_id": document_id,
        "parent_key": key,
        "chunk_id": chunk_id,
        "text": text,
        "metadata": metadata,
        "citation": {
            "source": "memory_os",
            "key": key,
            "chunk_id": chunk_id,
            "document_id": document_id,
        },
    }


def _manifest_int(manifest: dict[str, Any] | None, field: str) -> int | None:
    if not manifest:
        return None
    try:
        return int(manifest.get(field))
    except (TypeError, ValueError):
        return None


def _document_context_by_id(ledger: MemoryOSLedger) -> dict[str, dict[str, Any]]:
    context: dict[str, dict[str, Any]] = {}
    for record in list_records(ledger, "documents"):
        document_id = str(record.get("document_id") or "").strip()
        if document_id:
            context[document_id] = record
    return context


def _document_ingestion_context_by_id(ledger: MemoryOSLedger) -> dict[str, dict[str, Any]]:
    context: dict[str, dict[str, Any]] = {}
    for record in list_records(ledger, "jobs"):
        if record.get("record_type") != "document_ingestion":
            continue
        document_id = str(record.get("document_id") or "").strip()
        if document_id:
            context[document_id] = record
    return context


def _merge_document_chunk_metadata(
    metadata: dict[str, Any],
    logical_document_id: str,
    chunk_record_id: str,
    *,
    record: dict[str, Any],
    document_context: dict[str, dict[str, Any]],
    ingestion_context: dict[str, dict[str, Any]],
) -> None:
    document = document_context.get(logical_document_id) or {}
    document = enrich_document_record(document) if document else {}
    ingestion = ingestion_context.get(logical_document_id) or {}
    document_payload = document.get("document") if isinstance(document.get("document"), dict) else {}
    title = document.get("title") or document_payload.get("title") or logical_document_id
    metadata.setdefault("document_id", logical_document_id)
    if chunk_record_id:
        metadata.setdefault("chunk_record_id", chunk_record_id)
    metadata.setdefault("title", title)
    metadata.setdefault("tags", ["document-ingestion"])
    metadata.setdefault("project", ingestion.get("project"))
    metadata.setdefault("domain", ingestion.get("domain"))
    metadata.setdefault("status", "active")
    metadata.setdefault("source", "document_ingestion")
    merge_catalog_into_chunk_metadata(metadata, document)
    for field in ("ingestion_id", "window_index", "page_range", "local_chunk_id"):
        if field in record and field not in metadata:
            metadata[field] = record[field]


def _dedupe_result_payloads(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for result in results:
        key = _result_dedupe_key(result)
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = result
            order.append(key)
            continue
        if _result_specificity(result) > _result_specificity(existing):
            deduped[key] = result
    return [deduped[key] for key in order]


def _result_dedupe_key(result: dict[str, Any]) -> tuple[str, str]:
    key = str(result.get("key") or "")
    text = " ".join(str(result.get("text") or "").split())
    if text:
        return (key, hash_payload(text))
    return (key, str(int(result.get("chunk_id") or 0)))


def _result_specificity(result: dict[str, Any]) -> tuple[int, int]:
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    citation = result.get("citation") if isinstance(result.get("citation"), dict) else {}
    document_id = str(citation.get("document_id") or result.get("document_id") or "")
    return (
        1 if metadata.get("ingestion_id") else 0,
        1 if ":ingestion:" in document_id else 0,
    )
