from __future__ import annotations

import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import importlib.util


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "benchmark_engram.py"
DOC = ROOT / "docs" / "PERFORMANCE_BENCHMARKS.md"


def _benchmark_module():
    spec = importlib.util.spec_from_file_location("benchmark_engram_under_test", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _catalog() -> dict:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--list", "--json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_benchmark_suite_files_exist() -> None:
    assert SCRIPT.exists()
    assert DOC.exists()


def test_benchmark_catalog_covers_startup_regression_dimensions() -> None:
    payload = _catalog()
    scenarios = {scenario["id"]: scenario for scenario in payload["scenarios"]}

    assert payload["schema_version"] == "2026-05-21.engram-benchmark-catalog.v1"
    assert set(scenarios) >= {
        "startup_imports",
        "daemon_search",
        "daemon_retrieve_chunk",
        "daemon_direct_write",
        "daemon_metadata_update",
        "document_ingestion",
        "docker_startup",
        "ops_commands",
    }
    assert {scenario["category"] for scenario in scenarios.values()} >= {
        "startup",
        "search",
        "retrieval",
        "write",
        "metadata",
        "document_ingestion",
        "docker",
        "ops",
    }


def test_benchmark_scenarios_are_repeatable_and_metric_bearing() -> None:
    payload = _catalog()

    for scenario in payload["scenarios"]:
        assert scenario["repeatable"] is True
        assert scenario["metrics"], scenario["id"]
        assert scenario["command"], scenario["id"]
        assert scenario["data_scope"] in {"isolated", "live-daemon-cleanup", "static", "docker"}


def test_benchmark_plan_json_is_machine_readable_without_running_live_work() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--plan", "--json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["schema_version"] == "2026-05-21.engram-benchmark-plan.v1"
    assert payload["run_performed"] is False
    assert payload["scenario_count"] >= 8
    assert any(
        scenario["id"] == "docker_startup" and scenario["default_enabled"] is False
        for scenario in payload["scenarios"]
    )


def test_benchmark_harness_has_live_safety_guards() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "ENGRAM_DAEMON_AUTOSTART" in source
    assert "memory_os retrieval not ready" in source
    assert "pass --include-live-daemon" in source
    assert "_engram_benchmark_" in source
    assert "cleanup failed" in source
    assert "127.0.0.1:8765 is already in use" in source


def test_live_daemon_scenario_is_skipped_without_live_flag() -> None:
    benchmark = _benchmark_module()
    args = Namespace(
        scenario=["daemon_search"],
        include_live_daemon=False,
        include_docker_live=False,
        require_live_daemon=False,
        daemon_url="http://127.0.0.1:1",
        timeout=1,
        include_slow_ops=False,
    )

    payload = benchmark.run_benchmarks(args)

    assert payload["summary"] == {"passed": 0, "skipped": 1, "failed": 0}
    assert payload["results"][0]["status"] == "skipped"
    assert "pass --include-live-daemon" in payload["results"][0]["error"]


def test_benchmark_docs_name_required_commands() -> None:
    docs = DOC.read_text(encoding="utf-8")

    assert "Live daemon scenarios require `--include-live-daemon`" in docs
    assert "scripts/benchmark_engram.py --list --json" in docs
    assert "scripts/benchmark_engram.py --run --json" in docs
    assert "--include-live-daemon" in docs
    assert "--include-docker-live" in docs
