import sqlite3

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


def test_ledger_connections_enable_foreign_keys(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "nested" / "engram.sqlite")
    ledger.initialize()

    with ledger.connect() as db:
        enabled = db.execute("PRAGMA foreign_keys").fetchone()[0]

    assert enabled == 1
    assert ledger.path.exists()
