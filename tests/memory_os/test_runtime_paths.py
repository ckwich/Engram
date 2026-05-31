from __future__ import annotations

import sqlite3
from pathlib import Path

from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.runtime_paths import (
    default_data_root,
    resolve_data_root,
    validate_memory_os_preflight,
)


def test_default_data_root_is_outside_checkout():
    root = default_data_root()

    assert root.name == "default-data"
    assert "Engram" in str(root)
    assert not str(root).endswith("Engram/data")


def test_resolve_data_root_honors_explicit_environment(tmp_path):
    configured = tmp_path / "explicit-data"

    root = resolve_data_root({"ENGRAM_DATA_DIR": str(configured)})

    assert root == configured.resolve()


def test_preflight_accepts_clean_missing_ledger(tmp_path):
    root = tmp_path / "memory_os"

    report = validate_memory_os_preflight(root)

    assert report["status"] == "ok"
    assert report["safe_to_start"] is True
    assert report["ledger"]["exists"] is False


def test_preflight_blocks_synced_or_checkout_runtime_path(tmp_path):
    checkout = tmp_path / "Engram"
    root = checkout / "data" / "memory_os"

    report = validate_memory_os_preflight(root, repo_root=checkout)

    assert report["status"] == "blocked"
    assert report["safe_to_start"] is False
    assert "repo_checkout_runtime_path" in {risk["code"] for risk in report["risks"]}


def test_preflight_blocks_conflict_artifacts_next_to_ledger(tmp_path):
    root = tmp_path / "memory_os"
    MemoryOSLedger(root / "ledger.sqlite3").initialize()
    (root / "ledger 2.sqlite3").write_bytes(b"conflicted copy")

    report = validate_memory_os_preflight(root)

    assert report["status"] == "blocked"
    assert report["safe_to_start"] is False
    assert "conflict_artifact_detected" in {risk["code"] for risk in report["risks"]}
    assert any(item["name"] == "ledger 2.sqlite3" for item in report["conflict_artifacts"])


def test_preflight_blocks_malformed_ledger(tmp_path):
    root = tmp_path / "memory_os"
    root.mkdir(parents=True)
    (root / "ledger.sqlite3").write_text("not a sqlite database", encoding="utf-8")

    report = validate_memory_os_preflight(root)

    assert report["status"] == "blocked"
    assert report["safe_to_start"] is False
    assert report["ledger"]["quick_check"] != "ok"
    assert "malformed_ledger" in {risk["code"] for risk in report["risks"]}


def test_preflight_reports_valid_ledger_counts(tmp_path):
    root = tmp_path / "memory_os"
    ledger = MemoryOSLedger(root / "ledger.sqlite3")
    ledger.initialize()
    with sqlite3.connect(ledger.path) as conn:
        conn.execute(
            "INSERT INTO memories (id, payload_json) VALUES (?, ?)",
            ("memory:one", "{}"),
        )
        conn.commit()

    report = validate_memory_os_preflight(root)

    assert report["status"] == "ok"
    assert report["ledger"]["quick_check"] == "ok"
    assert report["ledger"]["tables"]["memories"] == 1
