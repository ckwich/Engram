"""Migration kernel for the Engram Memory OS rebuild.

This module is intentionally separate from memory_manager.py. The first rebuild
slice must prove that legacy JSON memories can round-trip through a new durable
ledger and content-addressed artifact store without touching ChromaDB.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "2026-05-11.memory_os_migration.v1"
LEDGER_FILENAME = "ledger.sqlite3"

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
}


def legacy_json_filename(key: str) -> str:
    """Return the legacy Engram JSON filename for a memory key."""
    digest = hashlib.md5(key.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"{digest}.json"


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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
                }
            )

        return {
            "schema_version": SCHEMA_VERSION,
            "exported_at": _now(),
            "memory_count": len(memories),
            "memories": memories,
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
        conn.commit()

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
        return {
            "key": key,
            "title": _normalize_optional_text(data.get("title")) or key,
            "content_hash": _sha256_text(content),
            "artifact_sha256": _sha256_bytes(raw_bytes),
            "tags": _normalize_string_list(data.get("tags")),
            "related_to": _normalize_string_list(data.get("related_to")),
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
            "unsupported_fields": sorted(set(data) - KNOWN_LEGACY_FIELDS),
            "imported_at": imported_at,
        }

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

        return {
            "key": key,
            "title": _normalize_optional_text(ledger.get("title")) or key,
            "content_hash": ledger["content_hash"],
            "artifact_sha256": artifact_sha,
            "tags": _normalize_string_list(ledger.get("tags")),
            "related_to": _normalize_string_list(ledger.get("related_to")),
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
            "unsupported_fields": [],
            "imported_at": _now(),
        }

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
            "related_to_count": sum(len(record["related_to"]) for record in records),
            "unsupported_fields": unsupported,
            "field_mappings": dict(FIELD_MAPPINGS),
            "artifact_hashes": {
                record["key"]: record["artifact_sha256"]
                for record in records
            },
            "invalid": invalid,
        }
