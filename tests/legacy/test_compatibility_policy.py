from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_import_probe(source: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", source],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_policy_import_does_not_import_legacy_memory_manager() -> None:
    probe = _run_import_probe(
        "import sys\n"
        "import core.legacy.compatibility_policy\n"
        "print('core.memory_manager' in sys.modules)\n"
    )

    assert probe.returncode == 0, probe.stderr
    assert probe.stdout.strip() == "False"


def test_legacy_compatibility_policy_is_recovery_only() -> None:
    from core.legacy.compatibility_policy import LEGACY_COMPATIBILITY_MODE

    assert LEGACY_COMPATIBILITY_MODE["runtime_role"] == "compatibility_recovery"
    assert LEGACY_COMPATIBILITY_MODE["product_core"] is False
    assert LEGACY_COMPATIBILITY_MODE["deletion_allowed"] is False
    assert "new_memory_os_features" in LEGACY_COMPATIBILITY_MODE["blocked_callers"]


def test_legacy_retirement_requires_all_explicit_gates() -> None:
    from core.legacy.compatibility_policy import (
        REQUIRED_LEGACY_RETIREMENT_GATE_IDS,
        legacy_retirement_gate_report,
    )

    assert "corpus_parity_verified" in REQUIRED_LEGACY_RETIREMENT_GATE_IDS
    assert "operator_backup_verified" in REQUIRED_LEGACY_RETIREMENT_GATE_IDS

    report = legacy_retirement_gate_report(
        completed_gate_ids={
            "migration_replay_stable",
            "daemon_serving_stable",
            "rollback_backup_verified",
        }
    )

    assert report["status"] == "blocked"
    assert report["retirement_allowed"] is False
    assert report["completed_gate_ids"] == [
        "daemon_serving_stable",
        "migration_replay_stable",
        "rollback_backup_verified",
    ]
    assert report["missing_gate_ids"] == [
        gate_id
        for gate_id in REQUIRED_LEGACY_RETIREMENT_GATE_IDS
        if gate_id not in report["completed_gate_ids"]
    ]

    complete = legacy_retirement_gate_report(completed_gate_ids=REQUIRED_LEGACY_RETIREMENT_GATE_IDS)

    assert complete["status"] == "ready_for_operator_retirement_action"
    assert complete["retirement_allowed"] is True
    assert complete["missing_gate_ids"] == []


def test_retirement_gate_report_rejects_unknown_gates() -> None:
    from core.legacy.compatibility_policy import legacy_retirement_gate_report

    report = legacy_retirement_gate_report(completed_gate_ids={"migration_replay_stable", "shortcut"})

    assert report["status"] == "blocked"
    assert report["retirement_allowed"] is False
    assert report["unknown_gate_ids"] == ["shortcut"]
