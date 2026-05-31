import sqlite3
import threading
import time

from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.schema import SCHEMA_VERSION, TABLES


def test_ledger_initializes_required_tables(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "engram.sqlite")
    ledger.initialize()

    with sqlite3.connect(ledger.path) as db:
        tables = {
            row[0]
            for row in db.execute(
                "select name from sqlite_master where type = 'table'"
            ).fetchall()
        }

    assert set(TABLES).issubset(tables)


def test_ledger_records_schema_version(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "engram.sqlite")
    ledger.initialize()

    with sqlite3.connect(ledger.path) as db:
        version = db.execute(
            "select value from meta where key = 'schema_version'"
        ).fetchone()[0]

    assert version == SCHEMA_VERSION


def test_ledger_initializes_hot_chunk_lookup_indexes(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "engram.sqlite")
    ledger.initialize()

    with sqlite3.connect(ledger.path) as db:
        indexes = {
            row[0]
            for row in db.execute(
                "select name from sqlite_master where type = 'index'"
            ).fetchall()
        }

    assert "idx_chunks_memory_key_chunk_id" in indexes
    assert "idx_chunks_document_id_chunk_id" in indexes


def test_ledger_connections_enable_foreign_keys(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "nested" / "engram.sqlite")
    ledger.initialize()

    with ledger.connect() as db:
        enabled = db.execute("PRAGMA foreign_keys").fetchone()[0]

    assert enabled == 1
    assert ledger.path.exists()


def test_ledger_connections_use_wal_and_busy_timeout(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "engram.sqlite")
    ledger.initialize()

    with ledger.connect() as db:
        journal_mode = db.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = db.execute("PRAGMA busy_timeout").fetchone()[0]

    assert journal_mode.lower() == "wal"
    assert busy_timeout >= 30_000


def test_ledger_context_manager_closes_connection(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "engram.sqlite")
    ledger.initialize()

    with ledger.connect() as db:
        db.execute("SELECT 1").fetchone()

    try:
        db.execute("SELECT 1")
    except sqlite3.ProgrammingError as exc:
        assert "closed" in str(exc).lower()
    else:  # pragma: no cover - failure path reports the leaked handle
        raise AssertionError("ledger context manager left SQLite connection open")


def test_ledger_reports_sqlite_connection_profile(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "engram.sqlite")
    ledger.initialize()

    profile = ledger.connection_profile()

    assert profile["journal_mode"].lower() == "wal"
    assert profile["busy_timeout_ms"] >= 30_000
    assert profile["foreign_keys"] == 1


def test_ledger_reads_while_write_transaction_is_open(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "engram.sqlite", timeout=2.0, busy_timeout_ms=2_000)
    ledger.initialize()
    writer_started = threading.Event()
    release_writer = threading.Event()
    errors: list[str] = []
    rows: list[sqlite3.Row] = []

    def hold_write_lock():
        with ledger.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE meta SET value = value WHERE key = 'schema_version'")
            writer_started.set()
            release_writer.wait(timeout=2)
            db.commit()

    writer = threading.Thread(target=hold_write_lock)
    writer.start()
    assert writer_started.wait(timeout=1)
    try:
        reader = threading.Thread(
            target=lambda: rows.extend(
                ledger.connect()
                .execute("SELECT value FROM meta WHERE key = 'schema_version'")
                .fetchall()
            )
        )
        reader.start()
        reader.join(timeout=2)
        if reader.is_alive():
            errors.append("reader did not finish while writer held reserved lock")
    finally:
        release_writer.set()
        writer.join(timeout=2)

    assert errors == []
    assert rows[0]["value"] == SCHEMA_VERSION


def test_ledger_second_writer_waits_for_write_lock_instead_of_failing(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "engram.sqlite", timeout=2.0, busy_timeout_ms=2_000)
    ledger.initialize()
    writer_started = threading.Event()
    release_writer = threading.Event()
    second_writer_done = threading.Event()
    errors: list[str] = []

    def hold_write_lock():
        with ledger.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE meta SET value = value WHERE key = 'schema_version'")
            writer_started.set()
            release_writer.wait(timeout=2)
            db.commit()

    def second_writer():
        try:
            with ledger.connect() as db:
                db.execute("UPDATE meta SET value = value WHERE key = 'schema_version'")
                db.commit()
        except Exception as exc:  # pragma: no cover - assertion reports the error
            errors.append(str(exc))
        finally:
            second_writer_done.set()

    writer = threading.Thread(target=hold_write_lock)
    writer.start()
    assert writer_started.wait(timeout=1)
    try:
        contender = threading.Thread(target=second_writer)
        contender.start()
        time.sleep(0.05)
        assert not second_writer_done.is_set()
        release_writer.set()
        contender.join(timeout=2)
        if contender.is_alive():
            errors.append("second writer did not finish after writer released lock")
    finally:
        release_writer.set()
        writer.join(timeout=2)

    assert errors == []
