"""Migration kernel for the Engram Memory OS rebuild.

This module is intentionally separate from memory_manager.py. The first rebuild
slice must prove that legacy JSON memories can round-trip through a new durable
ledger and content-addressed artifact store without touching ChromaDB.
"""
from __future__ import annotations

import base64
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.chunker import chunk_content_with_metadata
from core.vector_index import VectorIndexDocument

SCHEMA_VERSION = "2026-05-11.memory_os_migration.v7"
LEDGER_FILENAME = "ledger.sqlite3"
LEGACY_RELATED_TO_EDGE_SOURCE = "legacy_related_to"
DOCUMENT_EVIDENCE_ID_FIELDS = {
    "document": "document_id",
    "document_extraction_request": "request_id",
    "document_extraction_result": "result_id",
    "visual_extraction_request": "request_id",
    "visual_artifact": "artifact_id",
    "extractor_receipt": "receipt_id",
    "document_draft": "draft_id",
    "document_promotion_transaction": "transaction_id",
}
DOCUMENT_EVIDENCE_RECORD_ORDER = {
    "document": 0,
    "document_extraction_request": 1,
    "document_extraction_result": 2,
    "visual_extraction_request": 3,
    "visual_artifact": 4,
    "extractor_receipt": 5,
    "document_draft": 6,
    "document_promotion_transaction": 7,
}

KNOWN_LEGACY_FIELDS = {
    "key",
    "title",
    "content",
    "tags",
    "project",
    "domain",
    "status",
    "canonical",
    "related_to",
    "created_at",
    "updated_at",
    "last_accessed",
    "chars",
    "lines",
    "chunk_count",
    "stale",
    "stale_type",
    "stale_reason",
    "stale_at",
    "reviewed_at",
}

FIELD_MAPPINGS = {
    "key": "memories.key",
    "title": "memories.title",
    "content": "content_artifacts.raw_json",
    "tags": "memories.tags_json",
    "related_to": "memories.related_to_json",
    "project": "memories.project",
    "domain": "memories.domain",
    "status": "memories.status",
    "canonical": "memories.canonical",
    "created_at": "memories.created_at",
    "updated_at": "memories.updated_at",
    "last_accessed": "memories.last_accessed",
    "chars": "memories.chars",
    "lines": "memories.lines",
    "chunk_count": "memories.chunk_count",
    "derived_chunks": "chunks",
}


def legacy_json_filename(key: str) -> str:
    """Return the legacy Engram JSON filename for a memory key."""
    digest = hashlib.md5(key.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"{digest}.json"


def legacy_chunk_document_id(key: str, chunk_id: int) -> str:
    """Return the legacy Engram vector document ID for a memory chunk."""
    digest = hashlib.md5(key.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"{digest}_{chunk_id}"


def _graph_edge_id(edge: dict[str, Any]) -> str:
    base = {
        "from_ref": edge["from_ref"],
        "to_ref": edge["to_ref"],
        "edge_type": edge["edge_type"],
        "source": edge["source"],
    }
    return f"sha256:{hashlib.sha256(_json_dumps(base).encode('utf-8')).hexdigest()}"


def _ref_key(ref: dict[str, Any]) -> str:
    return str(ref.get("key") or _json_dumps(ref))


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _pretty_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                decoded = json.loads(text)
            except json.JSONDecodeError:
                decoded = None
            if isinstance(decoded, list):
                value = decoded
            else:
                value = text.split(",")
        else:
            value = text.split(",")

    if not isinstance(value, (list, tuple, set)):
        value = [value]

    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _normalize_heading_path(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def build_vector_index_documents(
    source_records: list[dict[str, Any]],
    embeddings_by_document_id: dict[str, list[float]],
) -> list[VectorIndexDocument]:
    """Pair migration chunk source records with caller-provided embeddings."""
    documents: list[VectorIndexDocument] = []
    for source in source_records:
        document_id = str(source["document_id"])
        embedding = embeddings_by_document_id.get(document_id)
        if embedding is None:
            raise ValueError(f"missing embedding for document_id: {document_id}")
        documents.append(
            VectorIndexDocument(
                document_id=document_id,
                parent_key=str(source["parent_key"]),
                chunk_id=int(source["chunk_id"]),
                text=str(source["text"]),
                embedding=list(embedding),
                metadata=dict(source.get("metadata") or {}),
                citation=dict(source.get("citation") or {}),
            )
        )
    return documents


class MemoryOSMigrationKernel:
    """Import legacy Engram JSON into a SQLite ledger plus artifact store."""

    def __init__(self, store_root: str | Path) -> None:
        self.store_root = Path(store_root)
        self.ledger_path = self.store_root / LEDGER_FILENAME
        self.objects_dir = self.store_root / "objects"

    def import_legacy_json(self, legacy_dir: str | Path, dry_run: bool = False) -> dict[str, Any]:
        records, invalid = self._scan_legacy_dir(Path(legacy_dir))
        if dry_run:
            return self._build_import_report(records, invalid, dry_run=True, imported_count=0)

        self.store_root.mkdir(parents=True, exist_ok=True)
        with self._connection() as conn:
            for record in records:
                self._write_artifact(record)
                self._upsert_memory(conn, record)

        return self._build_import_report(
            records,
            invalid,
            dry_run=False,
            imported_count=len(records),
        )

    def import_legacy_graph_edges(self, graph_path: str | Path) -> dict[str, Any]:
        graph_path = Path(graph_path)
        data = json.loads(graph_path.read_text(encoding="utf-8"))
        raw_edges = data.get("edges") if isinstance(data, dict) else None
        if not isinstance(raw_edges, list):
            raise ValueError("legacy graph document must contain an edges list")

        edges: list[dict[str, Any]] = []
        invalid: list[dict[str, Any]] = []
        for index, raw_edge in enumerate(raw_edges):
            try:
                edges.append(self._normalize_bundle_graph_edge(raw_edge))
            except ValueError as error:
                invalid.append({"edge_index": index, "message": str(error)})

        self.store_root.mkdir(parents=True, exist_ok=True)
        with self._connection() as conn:
            self._upsert_graph_edges(conn, edges)
            conn.commit()

        return {
            "schema_version": SCHEMA_VERSION,
            "source_count": len(raw_edges),
            "imported_count": len(edges),
            "invalid_count": len(invalid),
            "edge_ids": [edge["edge_id"] for edge in edges],
            "invalid": invalid,
        }

    def store_document_evidence_records(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        """Store no-write document intelligence evidence records in the migration ledger."""
        if not isinstance(records, list) or not records:
            raise ValueError("document evidence records must include at least one item")
        normalized_records = [self._normalize_document_evidence_record(record) for record in records]

        self.store_root.mkdir(parents=True, exist_ok=True)
        with self._connection() as conn:
            self._upsert_document_evidence_records(conn, normalized_records)
            conn.commit()

        return {
            "schema_version": SCHEMA_VERSION,
            "stored_count": len(normalized_records),
            "record_ids": [record["record_id"] for record in normalized_records],
        }

    def read_document_evidence_records(
        self,
        document_id: str | None = None,
        record_type: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM document_evidence_records"
        conditions: list[str] = []
        params: list[Any] = []
        if document_id is not None:
            conditions.append("document_id = ?")
            params.append(document_id)
        if record_type is not None:
            conditions.append("record_type = ?")
            params.append(record_type)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY document_id, record_order, record_id"

        try:
            with self._connection(initialize=False) as conn:
                rows = conn.execute(query, tuple(params)).fetchall()
        except sqlite3.OperationalError as error:
            if "no such table: document_evidence_records" in str(error):
                return []
            raise

        records: list[dict[str, Any]] = []
        for row in rows:
            artifact_path = self._artifact_path(row["artifact_sha256"])
            records.append(json.loads(artifact_path.read_text(encoding="utf-8")))
        return records

    def export_bundle(self) -> dict[str, Any]:
        with self._connection(initialize=False) as conn:
            rows = conn.execute(
                """
                SELECT memories.*, legacy_artifacts.legacy_filename,
                       legacy_artifacts.artifact_sha256
                FROM memories
                JOIN legacy_artifacts ON legacy_artifacts.memory_key = memories.key
                ORDER BY memories.key
                """
            ).fetchall()

        memories: list[dict[str, Any]] = []
        for row in rows:
            artifact_sha = row["artifact_sha256"]
            artifact_path = self._artifact_path(artifact_sha)
            artifact_raw = artifact_path.read_bytes()
            memories.append(
                {
                    "key": row["key"],
                    "ledger": self._row_to_memory(row),
                    "legacy_filename": row["legacy_filename"],
                    "artifact_sha256": artifact_sha,
                    "artifact_base64": base64.b64encode(artifact_raw).decode("ascii"),
                    "graph_edges": self.read_graph_edge_records(row["key"]),
                }
            )

        document_evidence_records = self.read_document_evidence_records()
        return {
            "schema_version": SCHEMA_VERSION,
            "exported_at": _now(),
            "memory_count": len(memories),
            "memories": memories,
            "graph_edges": self.read_graph_edge_records(),
            "document_evidence_count": len(document_evidence_records),
            "document_evidence_records": document_evidence_records,
        }

    def restore_bundle(self, bundle: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(bundle, dict) or bundle.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported memory OS migration bundle")
        memories = bundle.get("memories")
        if not isinstance(memories, list):
            raise ValueError("bundle memories must be a list")

        self.store_root.mkdir(parents=True, exist_ok=True)
        restored: list[str] = []
        with self._connection() as conn:
            for item in memories:
                record = self._record_from_bundle_item(item)
                self._write_artifact(record)
                self._upsert_memory(conn, record)
                restored.append(record["key"])
            graph_edges = bundle.get("graph_edges")
            if isinstance(graph_edges, list):
                conn.execute("DELETE FROM graph_edges")
                self._upsert_graph_edges(
                    conn,
                    [self._normalize_bundle_graph_edge(edge) for edge in graph_edges],
                )
            document_evidence_records = bundle.get("document_evidence_records")
            if isinstance(document_evidence_records, list):
                conn.execute("DELETE FROM document_evidence_records")
                self._upsert_document_evidence_records(
                    conn,
                    [
                        self._normalize_document_evidence_record(record)
                        for record in document_evidence_records
                    ],
                )
            conn.commit()

        restored.sort()
        return {
            "schema_version": SCHEMA_VERSION,
            "restored_count": len(restored),
            "key_set": restored,
        }

    def restore_legacy_json(self, target_dir: str | Path) -> dict[str, Any]:
        target = Path(target_dir)
        restored: list[str] = []
        with self._connection(initialize=False) as conn:
            rows = conn.execute(
                """
                SELECT memories.key, legacy_artifacts.artifact_sha256
                FROM memories
                JOIN legacy_artifacts ON legacy_artifacts.memory_key = memories.key
                ORDER BY memories.key
                """
            ).fetchall()

        for row in rows:
            artifact_path = self._artifact_path(row["artifact_sha256"])
            raw = artifact_path.read_bytes()
            _atomic_write(target / legacy_json_filename(row["key"]), raw)
            restored.append(row["key"])

        return {"restored_count": len(restored), "key_set": restored}

    def key_set(self) -> list[str]:
        with self._connection(initialize=False) as conn:
            rows = conn.execute("SELECT key FROM memories ORDER BY key").fetchall()
        return [row["key"] for row in rows]

    def read_memory_record(self, key: str) -> dict[str, Any] | None:
        with self._connection(initialize=False) as conn:
            row = conn.execute("SELECT * FROM memories WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        return self._row_to_memory(row)

    def read_chunk_records(self, key: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM chunks"
        params: tuple[Any, ...] = ()
        if key is not None:
            query += " WHERE memory_key = ?"
            params = (key,)
        query += " ORDER BY memory_key, chunk_index"

        with self._connection(initialize=False) as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_chunk(row) for row in rows]

    def read_vector_source_records(self, key: str | None = None) -> list[dict[str, Any]]:
        query = """
            SELECT chunks.*,
                   memories.title,
                   memories.tags_json,
                   memories.project,
                   memories.domain,
                   memories.status,
                   memories.canonical
            FROM chunks
            JOIN memories ON memories.key = chunks.memory_key
        """
        params: tuple[Any, ...] = ()
        if key is not None:
            query += " WHERE chunks.memory_key = ?"
            params = (key,)
        query += " ORDER BY chunks.memory_key, chunks.chunk_index"

        with self._connection(initialize=False) as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_vector_source(row) for row in rows]

    def read_graph_edge_records(self, key: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM graph_edges"
        params: tuple[Any, ...] = ()
        if key is not None:
            query += " WHERE from_key = ?"
            params = (key,)
        query += " ORDER BY from_key, to_key, edge_id"

        with self._connection(initialize=False) as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_graph_edge(row) for row in rows]

    def _connect(self, initialize: bool = True) -> sqlite3.Connection:
        if initialize:
            self.store_root.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.ledger_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if initialize:
            self._initialize_schema(conn)
        return conn

    @contextmanager
    def _connection(self, initialize: bool = True):
        conn = self._connect(initialize=initialize)
        try:
            yield conn
        finally:
            conn.close()

    def _initialize_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_info (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memories (
                key TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                artifact_sha256 TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                related_to_json TEXT NOT NULL,
                project TEXT,
                domain TEXT,
                status TEXT,
                canonical INTEGER NOT NULL DEFAULT 0,
                created_at TEXT,
                updated_at TEXT,
                last_accessed TEXT,
                chars INTEGER,
                lines INTEGER,
                chunk_count INTEGER,
                imported_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS legacy_artifacts (
                memory_key TEXT PRIMARY KEY,
                legacy_filename TEXT NOT NULL,
                artifact_sha256 TEXT NOT NULL,
                source_path TEXT,
                imported_at TEXT NOT NULL,
                FOREIGN KEY(memory_key) REFERENCES memories(key) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS chunks (
                document_id TEXT PRIMARY KEY,
                memory_key TEXT NOT NULL,
                chunk_id INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                text_hash TEXT NOT NULL,
                chars INTEGER NOT NULL,
                section_title TEXT NOT NULL,
                heading_path_json TEXT NOT NULL,
                chunk_kind TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(memory_key) REFERENCES memories(key) ON DELETE CASCADE,
                UNIQUE(memory_key, chunk_id)
            );

            CREATE INDEX IF NOT EXISTS idx_chunks_memory_key
            ON chunks(memory_key);

            CREATE TABLE IF NOT EXISTS graph_edges (
                edge_id TEXT PRIMARY KEY,
                from_key TEXT NOT NULL,
                to_key TEXT NOT NULL,
                from_ref_json TEXT NOT NULL,
                to_ref_json TEXT NOT NULL,
                edge_type TEXT NOT NULL,
                confidence REAL NOT NULL,
                evidence TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_graph_edges_from_key
            ON graph_edges(from_key);

            CREATE TABLE IF NOT EXISTS document_evidence_records (
                record_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                record_type TEXT NOT NULL,
                record_order INTEGER NOT NULL,
                artifact_sha256 TEXT NOT NULL,
                record_hash TEXT NOT NULL,
                review_status TEXT,
                active_memory_write_performed INTEGER NOT NULL DEFAULT 0,
                promotion_required INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_document_evidence_document_id
            ON document_evidence_records(document_id);

            CREATE INDEX IF NOT EXISTS idx_document_evidence_record_type
            ON document_evidence_records(record_type);
            """
        )
        conn.execute(
            """
            INSERT INTO schema_info(key, value)
            VALUES('schema_version', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (SCHEMA_VERSION,),
        )
        conn.commit()

    def _artifact_path(self, artifact_sha256: str) -> Path:
        return self.objects_dir / artifact_sha256[:2] / f"{artifact_sha256}.json"

    def _write_artifact(self, record: dict[str, Any]) -> None:
        path = self._artifact_path(record["artifact_sha256"])
        if path.exists():
            return
        _atomic_write(path, record["raw_bytes"])

    def _upsert_memory(self, conn: sqlite3.Connection, record: dict[str, Any]) -> None:
        conn.execute(
            """
            INSERT INTO memories (
                key, title, content_hash, artifact_sha256, tags_json,
                related_to_json, project, domain, status, canonical,
                created_at, updated_at, last_accessed, chars, lines,
                chunk_count, imported_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                title = excluded.title,
                content_hash = excluded.content_hash,
                artifact_sha256 = excluded.artifact_sha256,
                tags_json = excluded.tags_json,
                related_to_json = excluded.related_to_json,
                project = excluded.project,
                domain = excluded.domain,
                status = excluded.status,
                canonical = excluded.canonical,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                last_accessed = excluded.last_accessed,
                chars = excluded.chars,
                lines = excluded.lines,
                chunk_count = excluded.chunk_count,
                imported_at = excluded.imported_at
            """,
            (
                record["key"],
                record["title"],
                record["content_hash"],
                record["artifact_sha256"],
                _json_dumps(record["tags"]),
                _json_dumps(record["related_to"]),
                record["project"],
                record["domain"],
                record["status"],
                1 if record["canonical"] else 0,
                record["created_at"],
                record["updated_at"],
                record["last_accessed"],
                record["chars"],
                record["lines"],
                record["chunk_count"],
                record["imported_at"],
            ),
        )
        conn.execute(
            """
            INSERT INTO legacy_artifacts (
                memory_key, legacy_filename, artifact_sha256, source_path, imported_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(memory_key) DO UPDATE SET
                legacy_filename = excluded.legacy_filename,
                artifact_sha256 = excluded.artifact_sha256,
                source_path = excluded.source_path,
                imported_at = excluded.imported_at
            """,
            (
                record["key"],
                record["legacy_filename"],
                record["artifact_sha256"],
                record["source_path"],
                record["imported_at"],
            ),
        )
        conn.execute("DELETE FROM chunks WHERE memory_key = ?", (record["key"],))
        conn.executemany(
            """
            INSERT INTO chunks (
                document_id, memory_key, chunk_id, chunk_index, text, text_hash,
                chars, section_title, heading_path_json, chunk_kind, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    chunk["document_id"],
                    chunk["memory_key"],
                    chunk["chunk_id"],
                    chunk["chunk_index"],
                    chunk["text"],
                    chunk["text_hash"],
                    chunk["chars"],
                    chunk["section_title"],
                    _json_dumps(chunk["heading_path"]),
                    chunk["chunk_kind"],
                    record["imported_at"],
                )
                for chunk in record["chunks"]
            ],
        )
        conn.execute("DELETE FROM graph_edges WHERE from_key = ?", (record["key"],))
        self._upsert_graph_edges(conn, record["graph_edges"])
        conn.commit()

    def _upsert_graph_edges(self, conn: sqlite3.Connection, edges: list[dict[str, Any]]) -> None:
        conn.executemany(
            """
            INSERT INTO graph_edges (
                edge_id, from_key, to_key, from_ref_json, to_ref_json,
                edge_type, confidence, evidence, source, status, created_by,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(edge_id) DO UPDATE SET
                from_key = excluded.from_key,
                to_key = excluded.to_key,
                from_ref_json = excluded.from_ref_json,
                to_ref_json = excluded.to_ref_json,
                edge_type = excluded.edge_type,
                confidence = excluded.confidence,
                evidence = excluded.evidence,
                source = excluded.source,
                status = excluded.status,
                created_by = excluded.created_by,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            [
                (
                    edge["edge_id"],
                    _ref_key(edge["from_ref"]),
                    _ref_key(edge["to_ref"]),
                    _json_dumps(edge["from_ref"]),
                    _json_dumps(edge["to_ref"]),
                    edge["edge_type"],
                    edge["confidence"],
                    edge["evidence"],
                    edge["source"],
                    edge["status"],
                    edge["created_by"],
                    edge["created_at"],
                    edge["updated_at"],
                )
                for edge in edges
            ],
        )

    def _upsert_document_evidence_records(
        self,
        conn: sqlite3.Connection,
        records: list[dict[str, Any]],
    ) -> None:
        for record in records:
            path = self._artifact_path(record["artifact_sha256"])
            if not path.exists():
                _atomic_write(path, record["artifact_bytes"])
        conn.executemany(
            """
            INSERT INTO document_evidence_records (
                record_id, document_id, record_type, record_order,
                artifact_sha256, record_hash, review_status,
                active_memory_write_performed, promotion_required, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(record_id) DO UPDATE SET
                document_id = excluded.document_id,
                record_type = excluded.record_type,
                record_order = excluded.record_order,
                artifact_sha256 = excluded.artifact_sha256,
                record_hash = excluded.record_hash,
                review_status = excluded.review_status,
                active_memory_write_performed = excluded.active_memory_write_performed,
                promotion_required = excluded.promotion_required,
                created_at = excluded.created_at
            """,
            [
                (
                    record["record_id"],
                    record["document_id"],
                    record["record_type"],
                    record["record_order"],
                    record["artifact_sha256"],
                    record["record_hash"],
                    record["review_status"],
                    1 if record["active_memory_write_performed"] else 0,
                    1 if record["promotion_required"] else 0,
                    record["created_at"],
                )
                for record in records
            ],
        )

    def _scan_legacy_dir(self, legacy_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        records: list[dict[str, Any]] = []
        invalid: list[dict[str, Any]] = []
        for path in sorted(legacy_dir.glob("*.json")):
            try:
                raw_bytes = path.read_bytes()
                raw_text = raw_bytes.decode("utf-8")
                data = json.loads(raw_text)
            except Exception as error:
                invalid.append(
                    {
                        "filename": path.name,
                        "reason": "invalid_json",
                        "message": str(error),
                    }
                )
                continue

            try:
                records.append(self._record_from_legacy(path, raw_bytes, data))
            except ValueError as error:
                invalid.append(
                    {
                        "filename": path.name,
                        "reason": "invalid_record",
                        "message": str(error),
                    }
                )

        records.sort(key=lambda item: item["key"])
        return records, invalid

    def _record_from_legacy(self, path: Path, raw_bytes: bytes, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise ValueError("legacy memory JSON must be an object")

        key = _normalize_optional_text(data.get("key"))
        if not key:
            raise ValueError("legacy memory is missing key")
        content = data.get("content")
        if not isinstance(content, str):
            raise ValueError("legacy memory is missing text content")

        imported_at = _now()
        related_to = _normalize_string_list(data.get("related_to"))
        record = {
            "key": key,
            "title": _normalize_optional_text(data.get("title")) or key,
            "content_hash": _sha256_text(content),
            "artifact_sha256": _sha256_bytes(raw_bytes),
            "tags": _normalize_string_list(data.get("tags")),
            "related_to": related_to,
            "project": _normalize_optional_text(data.get("project")),
            "domain": _normalize_optional_text(data.get("domain")),
            "status": _normalize_optional_text(data.get("status")),
            "canonical": _normalize_bool(data.get("canonical")),
            "created_at": _normalize_optional_text(data.get("created_at")),
            "updated_at": _normalize_optional_text(data.get("updated_at")),
            "last_accessed": _normalize_optional_text(data.get("last_accessed")),
            "chars": _optional_int(data.get("chars")),
            "lines": _optional_int(data.get("lines")),
            "chunk_count": _optional_int(data.get("chunk_count")),
            "legacy_filename": path.name,
            "source_path": str(path),
            "raw_bytes": raw_bytes,
            "chunks": self._derive_chunk_records(key, content),
            "unsupported_fields": sorted(set(data) - KNOWN_LEGACY_FIELDS),
            "imported_at": imported_at,
        }
        record["graph_edges"] = self._derive_related_to_edges(record)
        return record

    def _record_from_bundle_item(self, item: Any) -> dict[str, Any]:
        if not isinstance(item, dict):
            raise ValueError("bundle memory item must be an object")
        ledger = item.get("ledger")
        artifact_base64 = item.get("artifact_base64")
        artifact_sha = item.get("artifact_sha256")
        if not isinstance(ledger, dict) or not isinstance(artifact_base64, str) or not isinstance(artifact_sha, str):
            raise ValueError("bundle memory item is missing ledger or artifact data")

        raw_bytes = base64.b64decode(artifact_base64.encode("ascii"), validate=True)
        actual_sha = _sha256_bytes(raw_bytes)
        if actual_sha != artifact_sha:
            raise ValueError(f"artifact checksum mismatch for {item.get('key')}")

        key = _normalize_optional_text(ledger.get("key"))
        if not key:
            raise ValueError("bundle memory item is missing key")
        try:
            legacy_data = json.loads(raw_bytes.decode("utf-8"))
        except Exception as error:
            raise ValueError(f"bundle artifact is not valid legacy JSON for {key}") from error
        content = legacy_data.get("content") if isinstance(legacy_data, dict) else None
        if not isinstance(content, str):
            raise ValueError(f"bundle artifact is missing text content for {key}")

        related_to = _normalize_string_list(ledger.get("related_to"))
        record = {
            "key": key,
            "title": _normalize_optional_text(ledger.get("title")) or key,
            "content_hash": ledger["content_hash"],
            "artifact_sha256": artifact_sha,
            "tags": _normalize_string_list(ledger.get("tags")),
            "related_to": related_to,
            "project": _normalize_optional_text(ledger.get("project")),
            "domain": _normalize_optional_text(ledger.get("domain")),
            "status": _normalize_optional_text(ledger.get("status")),
            "canonical": _normalize_bool(ledger.get("canonical")),
            "created_at": _normalize_optional_text(ledger.get("created_at")),
            "updated_at": _normalize_optional_text(ledger.get("updated_at")),
            "last_accessed": _normalize_optional_text(ledger.get("last_accessed")),
            "chars": _optional_int(ledger.get("chars")),
            "lines": _optional_int(ledger.get("lines")),
            "chunk_count": _optional_int(ledger.get("chunk_count")),
            "legacy_filename": str(item.get("legacy_filename") or legacy_json_filename(key)),
            "source_path": None,
            "raw_bytes": raw_bytes,
            "chunks": self._derive_chunk_records(key, content),
            "unsupported_fields": [],
            "imported_at": _now(),
        }
        graph_edges = item.get("graph_edges")
        if isinstance(graph_edges, list):
            record["graph_edges"] = [self._normalize_bundle_graph_edge(edge) for edge in graph_edges]
        else:
            record["graph_edges"] = self._derive_related_to_edges(record)
        return record

    def _row_to_memory(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "key": row["key"],
            "title": row["title"],
            "content_hash": row["content_hash"],
            "artifact_sha256": row["artifact_sha256"],
            "tags": json.loads(row["tags_json"]),
            "related_to": json.loads(row["related_to_json"]),
            "project": row["project"],
            "domain": row["domain"],
            "status": row["status"],
            "canonical": bool(row["canonical"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_accessed": row["last_accessed"],
            "chars": row["chars"],
            "lines": row["lines"],
            "chunk_count": row["chunk_count"],
            "imported_at": row["imported_at"],
        }

    def _row_to_chunk(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "document_id": row["document_id"],
            "memory_key": row["memory_key"],
            "chunk_id": row["chunk_id"],
            "chunk_index": row["chunk_index"],
            "text": row["text"],
            "text_hash": row["text_hash"],
            "chars": row["chars"],
            "section_title": row["section_title"],
            "heading_path": json.loads(row["heading_path_json"]),
            "chunk_kind": row["chunk_kind"],
        }

    def _row_to_vector_source(self, row: sqlite3.Row) -> dict[str, Any]:
        heading_path = json.loads(row["heading_path_json"])
        metadata = {
            "key": row["memory_key"],
            "title": row["title"],
            "tags": json.loads(row["tags_json"]),
            "project": row["project"],
            "domain": row["domain"],
            "status": row["status"],
            "canonical": bool(row["canonical"]),
            "section_title": row["section_title"],
            "heading_path": heading_path,
            "chunk_kind": row["chunk_kind"],
            "text_hash": row["text_hash"],
        }
        return {
            "document_id": row["document_id"],
            "parent_key": row["memory_key"],
            "chunk_id": row["chunk_id"],
            "text": row["text"],
            "metadata": metadata,
            "citation": {
                "source": "memory_os_migration",
                "key": row["memory_key"],
                "chunk_id": row["chunk_id"],
                "document_id": row["document_id"],
            },
        }

    def _row_to_graph_edge(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "edge_id": row["edge_id"],
            "from_ref": json.loads(row["from_ref_json"]),
            "to_ref": json.loads(row["to_ref_json"]),
            "edge_type": row["edge_type"],
            "confidence": float(row["confidence"]),
            "evidence": row["evidence"],
            "source": row["source"],
            "status": row["status"],
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _derive_chunk_records(self, key: str, content: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for chunk in chunk_content_with_metadata(content):
            chunk_id = int(chunk["chunk_id"])
            text = str(chunk["text"])
            records.append(
                {
                    "document_id": legacy_chunk_document_id(key, chunk_id),
                    "memory_key": key,
                    "chunk_id": chunk_id,
                    "chunk_index": chunk_id,
                    "text": text,
                    "text_hash": _sha256_text(text),
                    "chars": len(text),
                    "section_title": str(chunk.get("section_title") or ""),
                    "heading_path": _normalize_heading_path(chunk.get("heading_path")),
                    "chunk_kind": str(chunk.get("chunk_kind") or "section"),
                }
            )
        return records

    def _derive_related_to_edges(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        edges: list[dict[str, Any]] = []
        from_ref = {"kind": "memory", "key": record["key"]}
        timestamp = record.get("created_at") or record.get("imported_at") or _now()
        updated_at = record.get("updated_at") or timestamp
        for related_key in record.get("related_to", []):
            to_ref = {"kind": "memory", "key": related_key}
            edge = {
                "from_ref": from_ref,
                "to_ref": to_ref,
                "edge_type": "related_to",
                "confidence": 1.0,
                "evidence": f"Legacy related_to metadata on memory '{record['key']}'.",
                "source": LEGACY_RELATED_TO_EDGE_SOURCE,
                "status": "active",
                "created_by": "migration",
                "created_at": timestamp,
                "updated_at": updated_at,
            }
            edge["edge_id"] = _graph_edge_id(edge)
            edges.append(edge)
        return edges

    def _normalize_document_evidence_record(self, record: Any) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise ValueError("document evidence record must be an object")
        if _normalize_bool(record.get("active_memory_write_performed")):
            raise ValueError("document evidence records must not be active memory writes")
        if _normalize_bool(record.get("write_performed")):
            raise ValueError("document evidence records must not be executed write receipts")

        record_type = _normalize_optional_text(record.get("record_type"))
        if not record_type or record_type not in DOCUMENT_EVIDENCE_ID_FIELDS:
            valid = ", ".join(sorted(DOCUMENT_EVIDENCE_ID_FIELDS))
            raise ValueError(f"document evidence record_type must be one of: {valid}")

        id_field = DOCUMENT_EVIDENCE_ID_FIELDS[record_type]
        record_id = _normalize_optional_text(record.get(id_field))
        if not record_id:
            raise ValueError(f"document evidence record is missing {id_field}")

        if record_type == "document":
            document_id = record_id
        elif record_type == "document_extraction_request":
            document_id = _normalize_optional_text(record.get("document_id")) or record_id
        elif record_type == "document_extraction_result":
            document_record = record.get("document_record")
            embedded_document_id = None
            if isinstance(document_record, dict):
                embedded_document_id = _normalize_optional_text(document_record.get("document_id"))
            document_id = _normalize_optional_text(record.get("document_id")) or embedded_document_id or record_id
        else:
            document_id = _normalize_optional_text(record.get("document_id"))
            if not document_id:
                raise ValueError("document evidence record is missing document_id")

        artifact_bytes = _pretty_json_bytes(record)
        artifact_sha = _sha256_bytes(artifact_bytes)
        return {
            "record_id": record_id,
            "document_id": document_id,
            "record_type": record_type,
            "record_order": DOCUMENT_EVIDENCE_RECORD_ORDER.get(record_type, 99),
            "artifact_sha256": artifact_sha,
            "artifact_bytes": artifact_bytes,
            "record_hash": _sha256_text(_json_dumps(record)),
            "review_status": _normalize_optional_text(record.get("review_status")),
            "active_memory_write_performed": False,
            "promotion_required": _normalize_bool(record.get("promotion_required", True)),
            "created_at": _now(),
        }

    def _normalize_bundle_graph_edge(self, edge: Any) -> dict[str, Any]:
        if not isinstance(edge, dict):
            raise ValueError("bundle graph edge must be an object")
        required = {
            "edge_id",
            "from_ref",
            "to_ref",
            "edge_type",
            "confidence",
            "evidence",
            "source",
            "status",
            "created_by",
            "created_at",
            "updated_at",
        }
        missing = sorted(required - set(edge))
        if missing:
            raise ValueError(f"bundle graph edge is missing field: {missing[0]}")
        return {
            "edge_id": str(edge["edge_id"]),
            "from_ref": dict(edge["from_ref"]),
            "to_ref": dict(edge["to_ref"]),
            "edge_type": str(edge["edge_type"]),
            "confidence": float(edge["confidence"]),
            "evidence": str(edge["evidence"]),
            "source": str(edge["source"]),
            "status": str(edge["status"]),
            "created_by": str(edge["created_by"]),
            "created_at": str(edge["created_at"]),
            "updated_at": str(edge["updated_at"]),
        }

    def _build_import_report(
        self,
        records: list[dict[str, Any]],
        invalid: list[dict[str, Any]],
        dry_run: bool,
        imported_count: int,
    ) -> dict[str, Any]:
        unsupported = {
            record["key"]: record["unsupported_fields"]
            for record in records
            if record["unsupported_fields"]
        }
        chunk_counts = [record["chunk_count"] for record in records if isinstance(record["chunk_count"], int)]
        chunk_count_mismatches = [
            {
                "key": record["key"],
                "legacy_chunk_count": record["chunk_count"],
                "derived_chunk_count": len(record["chunks"]),
            }
            for record in records
            if isinstance(record["chunk_count"], int) and record["chunk_count"] != len(record["chunks"])
        ]
        return {
            "schema_version": SCHEMA_VERSION,
            "dry_run": dry_run,
            "source_count": len(records) + len(invalid),
            "valid_count": len(records),
            "invalid_count": len(invalid),
            "would_import_count": len(records),
            "imported_count": imported_count,
            "key_set": [record["key"] for record in records],
            "chunk_count_total": sum(chunk_counts),
            "derived_chunk_count_total": sum(len(record["chunks"]) for record in records),
            "chunk_count_mismatches": chunk_count_mismatches,
            "related_to_count": sum(len(record["related_to"]) for record in records),
            "unsupported_fields": unsupported,
            "field_mappings": dict(FIELD_MAPPINGS),
            "artifact_hashes": {
                record["key"]: record["artifact_sha256"]
                for record in records
            },
            "invalid": invalid,
        }


def run_round_trip_check(
    legacy_dir: str | Path,
    work_root: str | Path,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run a full legacy import/export/restore parity check."""
    work_root = Path(work_root)
    store_root = work_root / "store"
    restored_store_root = work_root / "restored_store"
    restored_json_dir = work_root / "restored_json"

    for path in (store_root, restored_store_root, restored_json_dir):
        if path.exists():
            raise FileExistsError(f"round-trip work path already exists: {path}")

    work_root.mkdir(parents=True, exist_ok=True)

    kernel = MemoryOSMigrationKernel(store_root)
    dry_run = kernel.import_legacy_json(legacy_dir, dry_run=True)
    imported = kernel.import_legacy_json(legacy_dir)
    bundle = kernel.export_bundle()
    restored = MemoryOSMigrationKernel(restored_store_root)
    restore = restored.restore_bundle(bundle)
    legacy_json_restore = restored.restore_legacy_json(restored_json_dir)

    key_sets_match = (
        imported["key_set"]
        == restore["key_set"]
        == legacy_json_restore["key_set"]
    )
    count_parity = (
        dry_run["valid_count"]
        == imported["imported_count"]
        == bundle["memory_count"]
        == restore["restored_count"]
        == legacy_json_restore["restored_count"]
    )
    status = "pass" if key_sets_match and count_parity and dry_run["invalid_count"] == 0 else "fail"

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "status": status,
        "paths": {
            "legacy_dir": str(Path(legacy_dir)),
            "work_root": str(work_root),
            "store_root": str(store_root),
            "restored_store_root": str(restored_store_root),
            "restored_json_dir": str(restored_json_dir),
        },
        "dry_run": {
            "source_count": dry_run["source_count"],
            "valid_count": dry_run["valid_count"],
            "invalid_count": dry_run["invalid_count"],
            "chunk_count_total": dry_run["chunk_count_total"],
            "derived_chunk_count_total": dry_run["derived_chunk_count_total"],
            "chunk_count_mismatch_count": len(dry_run["chunk_count_mismatches"]),
            "chunk_count_mismatches": dry_run["chunk_count_mismatches"],
            "related_to_count": dry_run["related_to_count"],
            "unsupported_fields": dry_run["unsupported_fields"],
            "invalid": dry_run["invalid"],
        },
        "import": {
            "imported_count": imported["imported_count"],
        },
        "bundle": {
            "memory_count": bundle["memory_count"],
        },
        "restore": {
            "restored_count": restore["restored_count"],
        },
        "legacy_json_restore": {
            "restored_count": legacy_json_restore["restored_count"],
        },
        "parity": {
            "key_sets_match": key_sets_match,
            "count_parity": count_parity,
        },
    }

    if report_path is not None:
        _write_json_file(Path(report_path), report)

    return report


def run_import_legacy(
    legacy_dir: str | Path,
    store_root: str | Path,
    *,
    report_path: str | Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Import legacy JSON memories into a Memory OS migration store."""
    report = MemoryOSMigrationKernel(store_root).import_legacy_json(legacy_dir, dry_run=dry_run)
    if report_path is not None:
        _write_json_file(Path(report_path), report)
    return report


def run_import_graph_edges(
    store_root: str | Path,
    graph_path: str | Path,
    *,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    """Import legacy graph edge documents into a Memory OS migration store."""
    report = MemoryOSMigrationKernel(store_root).import_legacy_graph_edges(graph_path)
    if report_path is not None:
        _write_json_file(Path(report_path), report)
    return report


def run_export_bundle(store_root: str | Path, bundle_path: str | Path) -> dict[str, Any]:
    """Export a Memory OS migration store to a portable JSON bundle."""
    bundle_path = Path(bundle_path)
    bundle = MemoryOSMigrationKernel(store_root).export_bundle()
    _write_json_file(bundle_path, bundle)
    return {
        "schema_version": SCHEMA_VERSION,
        "bundle_path": str(bundle_path),
        "memory_count": bundle["memory_count"],
        "graph_edge_count": len(bundle.get("graph_edges", [])),
        "document_evidence_count": bundle.get("document_evidence_count", 0),
    }


def run_restore_bundle(
    store_root: str | Path,
    bundle_path: str | Path,
    *,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    """Restore a Memory OS migration store from a portable JSON bundle."""
    bundle_path = Path(bundle_path)
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    report = MemoryOSMigrationKernel(store_root).restore_bundle(bundle)
    report["bundle_path"] = str(bundle_path)
    if report_path is not None:
        _write_json_file(Path(report_path), report)
    return report


def run_list_document_records(
    store_root: str | Path,
    *,
    document_id: str | None = None,
    record_type: str | None = None,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    """List persisted document-intelligence records from a migration store."""
    records = MemoryOSMigrationKernel(store_root).read_document_evidence_records(
        document_id=document_id,
        record_type=record_type,
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "store_root": str(Path(store_root)),
        "filters": {
            "document_id": document_id,
            "record_type": record_type,
        },
        "count": len(records),
        "records": records,
    }
    if report_path is not None:
        _write_json_file(Path(report_path), report)
    return report


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    encoded = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    _atomic_write(path, encoded)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m core.memory_os_migration",
        description="Engram Memory OS migration utilities.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    round_trip = subparsers.add_parser(
        "round-trip",
        help="Run legacy JSON import/export/restore parity checks.",
    )
    round_trip.add_argument("--legacy-dir", required=True, help="Legacy data/memories directory.")
    round_trip.add_argument("--work-root", required=True, help="Empty output directory for check artifacts.")
    round_trip.add_argument("--report", help="Optional JSON report path.")

    import_legacy = subparsers.add_parser(
        "import-legacy",
        help="Import legacy JSON memories into a migration store.",
    )
    import_legacy.add_argument("--legacy-dir", required=True, help="Legacy data/memories directory.")
    import_legacy.add_argument("--store-root", required=True, help="Memory OS migration store root.")
    import_legacy.add_argument("--report", help="Optional JSON report path.")
    import_legacy.add_argument("--dry-run", action="store_true", help="Validate import without writing the store.")

    import_graph_edges = subparsers.add_parser(
        "import-graph-edges",
        help="Import a legacy graph edges JSON document into a migration store.",
    )
    import_graph_edges.add_argument("--store-root", required=True, help="Memory OS migration store root.")
    import_graph_edges.add_argument("--graph-path", required=True, help="Legacy graph edges JSON path.")
    import_graph_edges.add_argument("--report", help="Optional JSON report path.")

    export_bundle = subparsers.add_parser(
        "export-bundle",
        help="Export a migration store to a portable JSON bundle.",
    )
    export_bundle.add_argument("--store-root", required=True, help="Memory OS migration store root.")
    export_bundle.add_argument("--bundle", required=True, help="Output bundle JSON path.")

    restore_bundle = subparsers.add_parser(
        "restore-bundle",
        help="Restore a migration store from a portable JSON bundle.",
    )
    restore_bundle.add_argument("--store-root", required=True, help="Target Memory OS migration store root.")
    restore_bundle.add_argument("--bundle", required=True, help="Input bundle JSON path.")
    restore_bundle.add_argument("--report", help="Optional JSON restore report path.")

    list_document_records = subparsers.add_parser(
        "list-document-records",
        help="List persisted document-intelligence records from a migration store.",
    )
    list_document_records.add_argument("--store-root", required=True, help="Memory OS migration store root.")
    list_document_records.add_argument("--document-id", help="Optional document_id filter.")
    list_document_records.add_argument("--record-type", help="Optional record_type filter.")
    list_document_records.add_argument("--report", help="Optional JSON report path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "round-trip":
        report = run_round_trip_check(
            legacy_dir=args.legacy_dir,
            work_root=args.work_root,
            report_path=args.report,
        )
        sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        return 0 if report["status"] == "pass" else 1

    if args.command == "import-legacy":
        report = run_import_legacy(
            legacy_dir=args.legacy_dir,
            store_root=args.store_root,
            report_path=args.report,
            dry_run=args.dry_run,
        )
        sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        return 0

    if args.command == "import-graph-edges":
        report = run_import_graph_edges(
            store_root=args.store_root,
            graph_path=args.graph_path,
            report_path=args.report,
        )
        sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        return 0

    if args.command == "export-bundle":
        report = run_export_bundle(
            store_root=args.store_root,
            bundle_path=args.bundle,
        )
        sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        return 0

    if args.command == "restore-bundle":
        report = run_restore_bundle(
            store_root=args.store_root,
            bundle_path=args.bundle,
            report_path=args.report,
        )
        sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        return 0

    if args.command == "list-document-records":
        report = run_list_document_records(
            store_root=args.store_root,
            document_id=args.document_id,
            record_type=args.record_type,
            report_path=args.report,
        )
        sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        return 0

    parser.error(f"unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
