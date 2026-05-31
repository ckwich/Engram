import json

from core.graph_store import JsonGraphStore
from core.memory_os._records import list_records, read_record
from core.memory_os.memory_benchmarks import (
    list_memory_benchmark_suites,
    run_memory_benchmark,
)
from core.memory_os.runtime import MemoryOSRuntime
from core.vector_index import InMemoryVectorIndex


def _runtime(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path / "memory_os",
        embed_text=lambda text: [1.0, 0.0] if "daemon-owned" in str(text).lower() else [0.0, 1.0],
        vector_index=InMemoryVectorIndex(),
        graph_store=JsonGraphStore(tmp_path / "edges.json"),
    )
    runtime.initialize(rebuild_retrieval=False)
    return runtime


def test_benchmark_run_writes_reproducible_summary(tmp_path):
    runtime = _runtime(tmp_path)

    result = run_memory_benchmark(runtime, suite_id="smoke", seed=42, persist=True)

    assert result["schema_version"] == "2026-05-26.memory-benchmark.v1"
    assert result["suite_id"] == "smoke"
    assert result["seed"] == 42
    assert result["summary"]["status"] == "pass"
    assert result["artifact_id"].startswith("sha256:")
    assert result["write_performed"] is True
    assert result["active_memory_write_performed"] is False
    assert read_record(runtime.ledger, "memories", "_benchmark_project_decision") is None
    stored = read_record(runtime.ledger, "benchmark_runs", result["run_id"])
    assert stored["artifact_id"] == result["artifact_id"]
    assert stored["transaction_id"] == result["transaction_id"]
    assert stored["summary"]["status"] == "pass"
    transaction = read_record(runtime.ledger, "transactions", result["transaction_id"])
    assert transaction["operation_kind"] == "memory_benchmark_run"
    assert transaction["status"] == "promoted"

    artifact = json.loads(runtime.content_store.read_bytes(result["artifact_id"]).decode("utf-8"))
    assert artifact["suite_id"] == "smoke"
    assert artifact["seed"] == 42
    assert artifact["scenario_results"]
    assert artifact["summary"]["status"] == "pass"
    assert artifact["write_performed"] is False


def test_benchmark_run_is_reproducible_for_same_suite_and_seed(tmp_path):
    first_runtime = _runtime(tmp_path / "first")
    second_runtime = _runtime(tmp_path / "second")

    first = run_memory_benchmark(first_runtime, suite_id="smoke", seed=42, persist=True)
    second = run_memory_benchmark(second_runtime, suite_id="smoke", seed=42, persist=True)

    assert first["run_id"] == second["run_id"]
    assert first["artifact_id"] == second["artifact_id"]
    assert first["summary"] == second["summary"]
    assert first["scenario_results"] == second["scenario_results"]


def test_benchmark_scenarios_cover_retrieval_guardrails_graph_and_sync(tmp_path):
    runtime = _runtime(tmp_path)

    result = run_memory_benchmark(runtime, suite_id="smoke", seed=42, persist=False)

    by_id = {row["scenario_id"]: row for row in result["scenario_results"]}
    assert by_id["memory_retrieval_exact_project"]["status"] == "pass"
    assert by_id["memory_retrieval_exact_project"]["expected_key_rank"] == 1
    assert by_id["memory_retrieval_exact_project"]["citation_coverage_passed"] is True
    assert by_id["memory_retrieval_exact_project"]["citation_count"] >= 1
    assert by_id["guardrail_blocks_secret"]["decision"] == "block"
    assert by_id["guardrail_blocks_secret"]["expected_issue_code_found"] is True
    assert by_id["graph_edge_round_trip"]["status"] == "pass"
    assert by_id["sync_dry_run_excludes_local_only"]["excluded"][0]["reason"] == "local_only_table"
    assert result["write_performed"] is False
    assert list_records(runtime.ledger, "benchmark_runs") == []


def test_benchmark_suite_catalog_is_no_write():
    catalog = list_memory_benchmark_suites()

    assert catalog["schema_version"] == "2026-05-26.memory-benchmark-catalog.v1"
    assert catalog["write_performed"] is False
    assert catalog["suites"][0]["suite_id"] == "smoke"
    assert {"memory_retrieval_exact_project", "guardrail_blocks_secret"}.issubset(
        set(catalog["suites"][0]["scenario_ids"])
    )
