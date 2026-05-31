"""SQLite ledger for the Engram Memory OS runtime."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from core.memory_os.schema import SCHEMA_VERSION, TABLES

DEFAULT_SQLITE_TIMEOUT_SECONDS = 30.0
DEFAULT_BUSY_TIMEOUT_MS = 30_000


class ClosingSQLiteConnection(sqlite3.Connection):
    """SQLite connection whose context manager also closes the handle."""

    def __exit__(self, exc_type, exc_value, traceback):  # type: ignore[override]
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class MemoryOSLedger:
    """Small SQLite ledger wrapper with deterministic schema initialization."""

    def __init__(
        self,
        path: str | Path,
        *,
        timeout: float = DEFAULT_SQLITE_TIMEOUT_SECONDS,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    ) -> None:
        self.path = Path(path)
        self.timeout = max(0.1, float(timeout))
        self.busy_timeout_ms = max(1, int(busy_timeout_ms))

    def connect(self) -> sqlite3.Connection:
        """Open a ledger connection with Memory OS defaults applied."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            self.path,
            timeout=self.timeout,
            factory=ClosingSQLiteConnection,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self) -> None:
        """Create the ledger schema if needed and record the schema version."""
        with self.connect() as conn:
            self._create_meta_table(conn)
            for table in TABLES:
                self._create_table(conn, table)
            self._create_indexes(conn)
            conn.execute(
                """
                INSERT INTO meta (key, value)
                VALUES ('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (SCHEMA_VERSION,),
            )
            conn.commit()

    def connection_profile(self) -> dict[str, int | float | str]:
        """Return the SQLite concurrency profile applied to new connections."""
        with self.connect() as conn:
            journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            busy_timeout_ms = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        return {
            "timeout_seconds": self.timeout,
            "busy_timeout_ms": int(busy_timeout_ms),
            "journal_mode": str(journal_mode),
            "foreign_keys": int(foreign_keys),
        }

    @staticmethod
    def _create_meta_table(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )

    @staticmethod
    def _create_table(conn: sqlite3.Connection, table: str) -> None:
        if table not in TABLES:
            raise ValueError(f"unknown Memory OS table: {table}")
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL DEFAULT '{{}}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

    @staticmethod
    def _create_indexes(conn: sqlite3.Connection) -> None:
        """Create targeted JSON-expression indexes for hot ledger lookups."""
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chunks_memory_key_chunk_id
            ON chunks (
                json_extract(payload_json, '$.memory_key'),
                CAST(json_extract(payload_json, '$.chunk_id') AS INTEGER)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chunks_document_id_chunk_id
            ON chunks (
                json_extract(payload_json, '$.document_id'),
                CAST(json_extract(payload_json, '$.chunk_id') AS INTEGER),
                id
            )
            """
        )
