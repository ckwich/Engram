"""SQLite ledger for the Engram Memory OS runtime."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from core.memory_os.schema import SCHEMA_VERSION, TABLES


class MemoryOSLedger:
    """Small SQLite ledger wrapper with deterministic schema initialization."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        """Open a ledger connection with Memory OS defaults applied."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self) -> None:
        """Create the ledger schema if needed and record the schema version."""
        with self.connect() as conn:
            self._create_meta_table(conn)
            for table in TABLES:
                self._create_table(conn, table)
            conn.execute(
                """
                INSERT INTO meta (key, value)
                VALUES ('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (SCHEMA_VERSION,),
            )
            conn.commit()

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
