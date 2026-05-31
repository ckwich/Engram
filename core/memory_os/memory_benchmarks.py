"""Reproducible Memory OS benchmark suites."""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from core.graph_store import JsonGraphStore
from core.memory_os._records import hash_payload, list_records, read_record, stable_id, upsert_record
from core.memory_os.memory_guardrails import evaluate_memory_write
from core.memory_os.schema import SYNC_LOCAL_ONLY_TABLES
from core.vector_index import InMemoryVectorIndex


MEMORY_BENCHMARK_SCHEMA_VERSION = "2026-05-26.memory-benchmark.v1"
MEMORY_BENCHMARK_CATALOG_SCHEMA_VERSION = "2026-05-26.memory-benchmark-catalog.v1"

SMOKE_BENCHMARK_SCENARIOS = (
    {
        "scenario_id": "memory_retrieval_exact_project",
        "seed_memory": {
            "key": "_benchmark_project_decision",
            "content": "Engram benchmark decision: daemon-owned Memory OS is the single writer.",
            "project": "/benchmark/engram",
            "domain": "benchmark",
            "tags": ["benchmark", "decision"],
            "memory_type": "decision",
        },
        "query": "daemon-owned Memory OS single writer decision",
        "expected_key": "_benchmark_project_decision",
        "max_rank": 1,
    },
    {
        "scenario_id": "guardrail_blocks_secret",
        "guardrail_input": {
            "key": "_benchmark_secret",
            "content": "API_TOKEN=abc123",
            "memory_type": "fact",
        },
        "expected_decision": "block",
        "expected_issue_code": "secret_like_content",
    },
    {
        "scenario_id": "graph_edge_round_trip",
        "graph_edges": [
            {
                "from_ref": "memory:_benchmark_project_decision",
                "to_ref": "concept:daemon_ownership",
                "edge_type": "supports",
                "confidence": 0.9,
                "evidence": [{"kind": "benchmark", "scenario_id": "graph_edge_round_trip"}],
            }
        ],
        "expected_edge_type": "supports",
    },
    {
        "scenario_id": "sync_dry_run_excludes_local_only",
        "sync_rows": [
            {"table": "memories", "payload": {"key": "syncable", "scope": "project"}},
            {"table": "jobs", "payload": {"job_id": "job:local"}},
        ],
        "expected_excluded_reason": "local_only_table",
    },
)

BENCHMARK_SUITES: dict[str, tuple[dict[str, Any], ...]] = {
    "smoke": SMOKE_BENCHMARK_SCENARIOS,
}


def list_memory_benchmark_suites() -> dict[str, Any]:
    """Return available deterministic benchmark suites without writing."""
    return {
        "schema_version": MEMORY_BENCHMARK_CATALOG_SCHEMA_VERSION,
        "suites": [
            {
                "suite_id": suite_id,
                "scenario_count": len(scenarios),
                "scenario_ids": [str(scenario["scenario_id"]) for scenario in scenarios],
                "requires_external_documents": False,
            }
            for suite_id, scenarios in sorted(BENCHMARK_SUITES.items())
        ],
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "error": None,
    }


def run_memory_benchmark(
    runtime: Any,
    *,
    suite_id: str = "smoke",
    seed: int = 42,
    persist: bool = True,
) -> dict[str, Any]:
    """Run a deterministic benchmark suite and optionally persist its result receipt."""
    normalized_suite_id = str(suite_id or "").strip() or "smoke"
    if normalized_suite_id not in BENCHMARK_SUITES:
        return _benchmark_error(normalized_suite_id, seed, "unknown_benchmark_suite")
    scenario_specs = BENCHMARK_SUITES[normalized_suite_id]
    with tempfile.TemporaryDirectory(prefix="engram-benchmark-") as temp_dir:
        fixture_runtime = _fixture_runtime(Path(temp_dir), runtime)
        scenario_results = [
            _run_scenario(fixture_runtime, scenario, seed=seed)
            for scenario in scenario_specs
        ]
    summary = _summarize_results(scenario_results)
    run_id = stable_id(
        "benchmark_run",
        {
            "suite_id": normalized_suite_id,
            "seed": int(seed),
            "scenario_hash": hash_payload(scenario_specs),
        },
    )
    result = {
        "schema_version": MEMORY_BENCHMARK_SCHEMA_VERSION,
        "record_type": "memory_benchmark_run",
        "run_id": run_id,
        "suite_id": normalized_suite_id,
        "seed": int(seed),
        "scenario_results": scenario_results,
        "summary": summary,
        "artifact_id": None,
        "created_at": _benchmark_timestamp(seed=int(seed), scenario_id=normalized_suite_id),
        "transaction_id": None,
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "error": None,
    }
    if not persist:
        return result
    artifact_payload = {
        **result,
        "artifact_id": None,
        "transaction_id": None,
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
    }
    artifact_id = runtime.content_store.put_bytes(
        json.dumps(artifact_payload, indent=2, sort_keys=True).encode("utf-8"),
        suffix=".json",
    )
    transaction = runtime.transactions.promote(
        operation_kind="memory_benchmark_run",
        proposed_writes=[
            {
                "table": "benchmark_runs",
                "id": run_id,
                "record_type": "memory_benchmark_run",
                "suite_id": normalized_suite_id,
                "seed": int(seed),
                "summary": summary,
                "artifact_id": artifact_id,
            },
            {
                "table": "content_artifacts",
                "id": artifact_id,
                "record_type": "memory_benchmark_artifact",
                "suite_id": normalized_suite_id,
                "seed": int(seed),
            },
        ],
        idempotency_key=stable_id(
            "benchmark_idempotency",
            {
                "suite_id": normalized_suite_id,
                "seed": int(seed),
                "scenario_hash": hash_payload(scenario_specs),
                "result_hash": hash_payload(scenario_results),
                "artifact_id": artifact_id,
            },
        ),
        affected_refs=[{"table": "benchmark_runs", "id": run_id}, {"artifact_id": artifact_id}],
    )
    persisted = {
        **result,
        "artifact_id": artifact_id,
        "transaction_id": transaction["transaction_id"],
        "write_performed": True,
    }
    upsert_record(
        runtime.ledger,
        "benchmark_runs",
        run_id,
        {
            "schema_version": MEMORY_BENCHMARK_SCHEMA_VERSION,
            "record_type": "memory_benchmark_run",
            "run_id": run_id,
            "suite_id": normalized_suite_id,
            "seed": int(seed),
            "summary": summary,
            "artifact_id": artifact_id,
            "transaction_id": transaction["transaction_id"],
            "scenario_count": len(scenario_results),
            "created_at": persisted["created_at"],
            "write_performed": True,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
        },
    )
    return persisted


def inspect_benchmark_run(runtime: Any, *, run_id: str) -> dict[str, Any]:
    """Inspect one persisted benchmark run receipt without reading active memories."""
    normalized_run_id = str(run_id or "").strip()
    if not normalized_run_id:
        return {
            "schema_version": MEMORY_BENCHMARK_SCHEMA_VERSION,
            "status": "schema_failed",
            "run_id": normalized_run_id,
            "run": None,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": {"code": "run_id_required", "message": "run_id is required."},
        }
    record = read_record(runtime.ledger, "benchmark_runs", normalized_run_id)
    return {
        "schema_version": MEMORY_BENCHMARK_SCHEMA_VERSION,
        "status": "ok" if isinstance(record, dict) else "not_found",
        "run_id": normalized_run_id,
        "run": record,
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "error": None if isinstance(record, dict) else {"code": "not_found", "message": "benchmark run was not found."},
    }


def _fixture_runtime(root: Path, _source_runtime: Any) -> Any:
    from core.memory_os.runtime import MemoryOSRuntime

    runtime = MemoryOSRuntime(
        root / "memory_os",
        embed_text=_benchmark_embed_text,
        vector_index=InMemoryVectorIndex(),
        graph_store=JsonGraphStore(root / "edges.json"),
    )
    runtime.initialize(rebuild_retrieval=False)
    return runtime


def _benchmark_embed_text(text: str) -> list[float]:
    normalized = str(text or "").lower()
    if "daemon-owned" in normalized or "single writer" in normalized:
        return [1.0, 0.0]
    if normalized.strip():
        return [0.0, 1.0]
    return [0.0, 0.0]


def _run_scenario(runtime: Any, scenario: dict[str, Any], *, seed: int) -> dict[str, Any]:
    scenario_id = str(scenario.get("scenario_id") or "")
    if "seed_memory" in scenario:
        return _run_retrieval_scenario(runtime, scenario, seed=seed)
    if "guardrail_input" in scenario:
        return _run_guardrail_scenario(scenario, seed=seed)
    if "graph_edges" in scenario:
        return _run_graph_scenario(runtime, scenario, seed=seed)
    if "sync_rows" in scenario:
        return _run_sync_scenario(scenario, seed=seed)
    return {
        "scenario_id": scenario_id,
        "status": "fail",
        "seed": int(seed),
        "error": {"code": "unsupported_benchmark_scenario"},
    }


def _run_retrieval_scenario(runtime: Any, scenario: dict[str, Any], *, seed: int) -> dict[str, Any]:
    seed_memory = dict(scenario.get("seed_memory") or {})
    key = str(seed_memory.get("key") or "")
    stored = runtime.store_memory(
        key=key,
        content=str(seed_memory.get("content") or ""),
        tags=list(seed_memory.get("tags") or []),
        project=seed_memory.get("project"),
        domain=seed_memory.get("domain"),
        memory_type=seed_memory.get("memory_type"),
        status="accepted",
        trust_state="reviewed",
        force=True,
    )
    search = runtime.search_memories(
        str(scenario.get("query") or ""),
        limit=max(int(scenario.get("max_rank") or 1), 1),
        project=seed_memory.get("project"),
        exact_project_match=True,
        domain=seed_memory.get("domain"),
        include_stale=False,
    )
    results = list(search.get("results") or [])
    expected_key = str(scenario.get("expected_key") or "")
    found_rank = next(
        (index for index, row in enumerate(results, start=1) if row.get("key") == expected_key),
        None,
    )
    max_rank = int(scenario.get("max_rank") or 1)
    citations = [
        row.get("citation")
        for row in results
        if row.get("key") == expected_key and isinstance(row.get("citation"), dict) and row.get("citation")
    ]
    citation_coverage_passed = bool(citations)
    runtime.delete_memory(key)
    status = (
        "pass"
        if found_rank is not None
        and found_rank <= max_rank
        and citation_coverage_passed
        else "fail"
    )
    return {
        "scenario_id": scenario["scenario_id"],
        "status": status,
        "seed": int(seed),
        "expected_key": expected_key,
        "expected_key_rank": found_rank,
        "max_rank": max_rank,
        "top_keys": [row.get("key") for row in results],
        "citation_count": len(citations),
        "citation_coverage_passed": citation_coverage_passed,
        "citations": citations,
        "fixture_transaction_id": stored.get("transaction_id"),
        "write_performed": False,
        "active_memory_write_performed": False,
    }


def _run_guardrail_scenario(scenario: dict[str, Any], *, seed: int) -> dict[str, Any]:
    guardrail = evaluate_memory_write(dict(scenario.get("guardrail_input") or {}))
    expected_decision = str(scenario.get("expected_decision") or "")
    expected_issue_code = str(scenario.get("expected_issue_code") or "")
    passed = (
        guardrail.get("decision") == expected_decision
        and expected_issue_code in set(guardrail.get("issue_codes") or [])
    )
    return {
        "scenario_id": scenario["scenario_id"],
        "status": "pass" if passed else "fail",
        "seed": int(seed),
        "decision": guardrail.get("decision"),
        "issue_codes": list(guardrail.get("issue_codes") or []),
        "expected_decision": expected_decision,
        "expected_issue_code": expected_issue_code,
        "expected_issue_code_found": expected_issue_code in set(guardrail.get("issue_codes") or []),
        "write_performed": False,
        "active_memory_write_performed": False,
    }


def _run_graph_scenario(runtime: Any, scenario: dict[str, Any], *, seed: int) -> dict[str, Any]:
    now = _benchmark_timestamp(seed=seed, scenario_id=str(scenario["scenario_id"]))
    edges = [
        _benchmark_edge_payload(edge, scenario_id=str(scenario["scenario_id"]), now=now)
        for edge in scenario.get("graph_edges") or []
        if isinstance(edge, dict)
    ]
    imported = runtime.graph.import_edges(edges)
    ledger_edges = [
        edge
        for edge in list_records(runtime.ledger, "graph_edges")
        if edge.get("source") == "memory_benchmark"
        and edge.get("benchmark_scenario_id") == scenario["scenario_id"]
    ]
    expected_edge_type = str(scenario.get("expected_edge_type") or "")
    passed = bool(ledger_edges) and all(edge.get("edge_type") == expected_edge_type for edge in ledger_edges)
    return {
        "scenario_id": scenario["scenario_id"],
        "status": "pass" if passed else "fail",
        "seed": int(seed),
        "expected_edge_type": expected_edge_type,
        "edge_ids": list(imported.get("edge_ids") or []),
        "round_trip_count": len(ledger_edges),
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
    }


def _run_sync_scenario(scenario: dict[str, Any], *, seed: int) -> dict[str, Any]:
    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for row in scenario.get("sync_rows") or []:
        table = str((row or {}).get("table") or "")
        if table in SYNC_LOCAL_ONLY_TABLES:
            excluded.append({"table": table, "reason": "local_only_table"})
        else:
            included.append({"table": table, "reason": "sync_eligible"})
    expected_reason = str(scenario.get("expected_excluded_reason") or "")
    passed = any(row.get("reason") == expected_reason for row in excluded)
    return {
        "scenario_id": scenario["scenario_id"],
        "status": "pass" if passed else "fail",
        "seed": int(seed),
        "included": included,
        "excluded": excluded,
        "expected_excluded_reason": expected_reason,
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
    }


def _benchmark_edge_payload(edge: dict[str, Any], *, scenario_id: str, now: str) -> dict[str, Any]:
    payload = {
        "from_ref": _ref(edge.get("from_ref")),
        "to_ref": _ref(edge.get("to_ref")),
        "edge_type": str(edge.get("edge_type") or ""),
        "confidence": float(edge.get("confidence") or 0.0),
        "evidence": list(edge.get("evidence") or []),
        "source": "memory_benchmark",
        "status": "active",
        "created_by": "memory_benchmark",
        "created_at": now,
        "updated_at": now,
        "benchmark_scenario_id": scenario_id,
    }
    payload["edge_id"] = stable_id("edge", payload)
    return payload


def _benchmark_timestamp(*, seed: int, scenario_id: str) -> str:
    digest = hash_payload({"seed": int(seed), "scenario_id": str(scenario_id)}).removeprefix("sha256:")
    seconds = int(digest[:8], 16) % 86400
    hour, remainder = divmod(seconds, 3600)
    minute, second = divmod(remainder, 60)
    return f"2026-05-26T{hour:02d}:{minute:02d}:{second:02d}+00:00"


def _ref(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(key): str(item) for key, item in value.items()}
    text = str(value or "").strip()
    if ":" in text:
        kind, key = text.split(":", 1)
        return {"kind": kind, "key": key}
    return {"kind": "ref", "key": text}


def _summarize_results(scenario_results: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [row for row in scenario_results if row.get("status") != "pass"]
    return {
        "status": "pass" if not failed else "fail",
        "scenario_count": len(scenario_results),
        "passed": len(scenario_results) - len(failed),
        "failed": len(failed),
        "failed_scenario_ids": [str(row.get("scenario_id") or "") for row in failed],
    }


def _benchmark_error(suite_id: str, seed: int, code: str) -> dict[str, Any]:
    return {
        "schema_version": MEMORY_BENCHMARK_SCHEMA_VERSION,
        "suite_id": suite_id,
        "seed": int(seed),
        "scenario_results": [],
        "summary": {"status": "fail", "scenario_count": 0, "passed": 0, "failed": 0},
        "artifact_id": None,
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "error": {"code": code},
    }


def _run_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Engram Memory CI benchmarks.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="Run a benchmark suite.")
    run_parser.add_argument("--suite", default="smoke")
    run_parser.add_argument("--seed", type=int, default=42)
    run_parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "run":
        from core.memory_os.runtime import MemoryOSRuntime

        with tempfile.TemporaryDirectory(prefix="engram-benchmark-cli-") as temp_dir:
            runtime = MemoryOSRuntime(
                Path(temp_dir) / "memory_os",
                vector_index=InMemoryVectorIndex(),
                graph_store=JsonGraphStore(Path(temp_dir) / "edges.json"),
            )
            runtime.initialize(rebuild_retrieval=False)
            result = run_memory_benchmark(
                runtime,
                suite_id=args.suite,
                seed=args.seed,
                persist=not args.no_persist,
            )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("summary", {}).get("status") == "pass" else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(_run_cli())
