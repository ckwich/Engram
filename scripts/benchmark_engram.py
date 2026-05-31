#!/usr/bin/env python3
"""Repeatable Engram benchmark harness for startup and runtime checks."""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
CATALOG_SCHEMA_VERSION = "2026-05-21.engram-benchmark-catalog.v1"
PLAN_SCHEMA_VERSION = "2026-05-21.engram-benchmark-plan.v1"
RUN_SCHEMA_VERSION = "2026-05-21.engram-benchmark-run.v1"
DEFAULT_DAEMON_URL = os.environ.get("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")


@dataclass(frozen=True)
class BenchmarkScenario:
    id: str
    category: str
    description: str
    command: str
    metrics: list[str]
    data_scope: str
    default_enabled: bool
    repeatable: bool = True
    requires: list[str] | None = None

    def catalog_entry(self) -> dict[str, Any]:
        entry = asdict(self)
        entry["requires"] = self.requires or []
        return entry


SCENARIOS = [
    BenchmarkScenario(
        id="startup_imports",
        category="startup",
        description=(
            "Measure cold Python import time for the thin client, full MCP server, "
            "and Memory OS runtime."
        ),
        command="python scripts/benchmark_engram.py --run --scenario startup_imports --json",
        metrics=[
            "server_daemon_client_import_ms",
            "server_import_ms",
            "memory_os_runtime_import_ms",
        ],
        data_scope="isolated",
        default_enabled=True,
    ),
    BenchmarkScenario(
        id="daemon_search",
        category="search",
        description=(
            "Measure live daemon semantic search latency against a temporary "
            "benchmark memory."
        ),
        command=(
            "python scripts/benchmark_engram.py --run --include-live-daemon "
            "--scenario daemon_search --json"
        ),
        metrics=["search_ms", "result_count", "backend_used", "fallback_used"],
        data_scope="live-daemon-cleanup",
        default_enabled=False,
        requires=["running engramd"],
    ),
    BenchmarkScenario(
        id="daemon_retrieve_chunk",
        category="retrieval",
        description=(
            "Measure live daemon chunk retrieval latency against a temporary "
            "benchmark memory."
        ),
        command=(
            "python scripts/benchmark_engram.py --run --include-live-daemon "
            "--scenario daemon_retrieve_chunk --json"
        ),
        metrics=["retrieve_chunk_ms", "found"],
        data_scope="live-daemon-cleanup",
        default_enabled=False,
        requires=["running engramd"],
    ),
    BenchmarkScenario(
        id="daemon_direct_write",
        category="write",
        description="Measure live daemon direct memory write latency with cleanup.",
        command=(
            "python scripts/benchmark_engram.py --run --include-live-daemon "
            "--scenario daemon_direct_write --json"
        ),
        metrics=["store_memory_ms", "chunk_count", "storage_backend"],
        data_scope="live-daemon-cleanup",
        default_enabled=False,
        requires=["running engramd"],
    ),
    BenchmarkScenario(
        id="daemon_metadata_update",
        category="metadata",
        description=(
            "Measure live daemon metadata update latency against a temporary "
            "benchmark memory."
        ),
        command=(
            "python scripts/benchmark_engram.py --run --include-live-daemon "
            "--scenario daemon_metadata_update --json"
        ),
        metrics=["update_memory_metadata_ms", "updated"],
        data_scope="live-daemon-cleanup",
        default_enabled=False,
        requires=["running engramd"],
    ),
    BenchmarkScenario(
        id="document_ingestion",
        category="document_ingestion",
        description="Measure isolated synthetic Document Intelligence ingestion runtime.",
        command="python scripts/benchmark_engram.py --run --scenario document_ingestion --json",
        metrics=["document_ingestion_ms", "chunk_count", "indexed_count", "status"],
        data_scope="isolated",
        default_enabled=True,
    ),
    BenchmarkScenario(
        id="docker_startup",
        category="docker",
        description=(
            "Measure Compose config validation by default, and optional isolated "
            "Docker startup with --include-docker-live."
        ),
        command=(
            "python scripts/benchmark_engram.py --run --include-docker-live "
            "--scenario docker_startup --json"
        ),
        metrics=["docker_compose_config_ms", "docker_compose_startup_ms"],
        data_scope="docker",
        default_enabled=False,
        requires=["docker", "docker compose"],
    ),
    BenchmarkScenario(
        id="ops_commands",
        category="ops",
        description=(
            "Measure operator command duration; slow release checks are included "
            "only with --include-slow-ops."
        ),
        command=(
            "python scripts/benchmark_engram.py --run --scenario ops_commands "
            "--include-slow-ops --json"
        ),
        metrics=[
            "validate_self_hosting_ms",
            "server_help_ms",
            "doctor_ms",
            "smoke_test_ms",
            "self_test_ms",
            "agent_eval_ms",
        ],
        data_scope="static",
        default_enabled=True,
    ),
]
SCENARIO_BY_ID = {scenario.id: scenario for scenario in SCENARIOS}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def scenario_catalog() -> dict[str, Any]:
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "scenario_count": len(SCENARIOS),
        "scenarios": [scenario.catalog_entry() for scenario in SCENARIOS],
    }


def benchmark_plan(selected_ids: list[str] | None = None) -> dict[str, Any]:
    if selected_ids:
        unknown = sorted(set(selected_ids) - set(SCENARIO_BY_ID))
        if unknown:
            raise SystemExit(f"unknown benchmark scenario(s): {', '.join(unknown)}")
        scenarios = [SCENARIO_BY_ID[scenario_id] for scenario_id in selected_ids]
    else:
        scenarios = SCENARIOS
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "run_performed": False,
        "scenario_count": len(scenarios),
        "scenarios": [scenario.catalog_entry() for scenario in scenarios],
    }


def run_benchmarks(args: argparse.Namespace) -> dict[str, Any]:
    scenarios = _selected_scenarios(
        args.scenario,
        include_live_daemon=args.include_live_daemon,
        include_docker_live=args.include_docker_live,
    )
    results = []
    for scenario in scenarios:
        if scenario.data_scope == "live-daemon-cleanup" and not args.include_live_daemon:
            results.append(_live_daemon_disabled_result(scenario.id, args))
            continue
        runner = SCENARIO_RUNNERS[scenario.id]
        results.append(runner(args))
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "run_performed": True,
        "scenario_count": len(results),
        "summary": {
            "passed": sum(1 for result in results if result["status"] == "pass"),
            "skipped": sum(1 for result in results if result["status"] == "skipped"),
            "failed": sum(1 for result in results if result["status"] == "fail"),
        },
        "results": results,
    }


def _selected_scenarios(
    selected_ids: list[str] | None,
    *,
    include_live_daemon: bool,
    include_docker_live: bool,
) -> list[BenchmarkScenario]:
    if selected_ids:
        unknown = sorted(set(selected_ids) - set(SCENARIO_BY_ID))
        if unknown:
            raise SystemExit(f"unknown benchmark scenario(s): {', '.join(unknown)}")
        return [SCENARIO_BY_ID[scenario_id] for scenario_id in selected_ids]
    return [
        scenario
        for scenario in SCENARIOS
        if scenario.default_enabled
        or (include_live_daemon and scenario.data_scope == "live-daemon-cleanup")
        or (include_docker_live and scenario.id == "docker_startup")
    ]


def _isolated_env(temp_root: str) -> dict[str, str]:
    return {
        **os.environ,
        "ENGRAM_DATA_DIR": temp_root,
        "ENGRAM_DAEMON_URL": "",
        "ENGRAM_DAEMON_AUTOSTART": "0",
    }


def _timed(label: str, func: Callable[[], Any]) -> tuple[Any, dict[str, int]]:
    started = time.perf_counter()
    value = func()
    return value, {f"{label}_ms": int((time.perf_counter() - started) * 1000)}


def _run_command(
    command: list[str],
    *,
    timeout: int,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    duration_ms = int((time.perf_counter() - started) * 1000)
    return {
        "command": command,
        "duration_ms": duration_ms,
        "exit_code": completed.returncode,
        "status": "pass" if completed.returncode == 0 else "fail",
        "stdout_tail": completed.stdout[-1000:],
        "stderr_tail": completed.stderr[-1000:],
    }


def _base_result(scenario_id: str) -> dict[str, Any]:
    scenario = SCENARIO_BY_ID[scenario_id]
    return {
        "id": scenario.id,
        "category": scenario.category,
        "status": "pass",
        "metrics": {},
        "details": {},
        "error": None,
    }


def run_startup_imports(args: argparse.Namespace) -> dict[str, Any]:
    result = _base_result("startup_imports")
    targets = {
        "server_daemon_client_import": "server_daemon_client",
        "server_import": "server",
        "memory_os_runtime_import": "core.memory_os.runtime",
    }
    with tempfile.TemporaryDirectory(prefix="engram-benchmark-startup-") as temp_root:
        env = _isolated_env(temp_root)
        for metric, module_name in targets.items():
            command_result = _run_command(
                [
                    sys.executable,
                    "-c",
                    f"import importlib; importlib.import_module({module_name!r})",
                ],
                timeout=args.timeout,
                env=env,
            )
            result["metrics"][f"{metric}_ms"] = command_result["duration_ms"]
            result["details"][metric] = command_result
            if command_result["status"] != "pass":
                result["status"] = "fail"
                result["error"] = f"{module_name} import failed"
    return result


def _daemon_health(client: Any) -> dict[str, Any]:
    health = client.health()
    serving = health.get("serving") if isinstance(health.get("serving"), dict) else {}
    if health.get("status") != "ok" or health.get("daemon") != "engramd":
        raise RuntimeError(f"daemon health failed: {health}")
    if not serving:
        raise RuntimeError(f"memory_os retrieval not ready: missing serving status in {health}")
    if serving.get("memory_os_retrieval_ready") is not True:
        status = serving.get("memory_os_retrieval_status")
        reason = serving.get("fallback_reason")
        raise RuntimeError(f"memory_os retrieval not ready: status={status} fallback={reason}")
    return health


def _compact_health(health: dict[str, Any]) -> dict[str, Any]:
    serving = health.get("serving") if isinstance(health.get("serving"), dict) else {}
    retrieval_state = serving.get("memory_os_retrieval_state")
    if not isinstance(retrieval_state, dict):
        retrieval_state = {}
    manifest = retrieval_state.get("manifest")
    if not isinstance(manifest, dict):
        manifest = {}
    return {
        "status": health.get("status"),
        "daemon": health.get("daemon"),
        "primary_backend": serving.get("primary_backend"),
        "fallback_active": serving.get("fallback_active"),
        "fallback_reason": serving.get("fallback_reason"),
        "memory_os_retrieval_ready": serving.get("memory_os_retrieval_ready"),
        "memory_os_retrieval_status": serving.get("memory_os_retrieval_status"),
        "retrieval_indexed_count": manifest.get("indexed_count"),
        "retrieval_source_count": manifest.get("source_count"),
    }


def _daemon_client(args: argparse.Namespace):
    from core.engramd_client import EngramDaemonClient

    return EngramDaemonClient(args.daemon_url, timeout=float(args.timeout))


def _daemon_unavailable_result(
    scenario_id: str,
    exc: Exception,
    args: argparse.Namespace,
) -> dict[str, Any]:
    result = _base_result(scenario_id)
    result["status"] = "fail" if args.require_live_daemon else "skipped"
    result["error"] = f"daemon unavailable: {exc}"
    result["details"]["daemon_url"] = args.daemon_url
    return result


def _live_daemon_disabled_result(scenario_id: str, args: argparse.Namespace) -> dict[str, Any]:
    result = _base_result(scenario_id)
    result["status"] = "fail" if args.require_live_daemon else "skipped"
    result["error"] = "pass --include-live-daemon to run live daemon benchmarks"
    result["details"]["daemon_url"] = args.daemon_url
    return result


def _benchmark_key() -> str:
    return f"_engram_benchmark_{uuid.uuid4().hex}"


def _store_fixture(client: Any, key: str, phrase: str) -> dict[str, Any]:
    return client.store_memory(
        {
            "key": key,
            "title": "Engram Benchmark Fixture",
            "content": (
                f"Engram benchmark fixture {phrase}. This memory is temporary "
                "and safe to delete."
            ),
            "tags": ["benchmark", "temporary"],
            "project": "Engram benchmark",
            "domain": "performance",
            "force": True,
        }
    )


def _compact_store_response(response: dict[str, Any]) -> dict[str, Any]:
    store_result = response.get("result") if isinstance(response.get("result"), dict) else {}
    return {
        "stored": response.get("stored") is True,
        "error": response.get("error"),
        "key": store_result.get("key"),
        "chunk_count": store_result.get("chunk_count"),
        "storage_backend": store_result.get("storage_backend"),
        "retrieval_state": store_result.get("retrieval_state"),
        "graph_state": store_result.get("graph_state"),
        "semantic_graph_job_id": store_result.get("semantic_graph_job_id"),
    }


def _store_fixture_required(result: dict[str, Any], response: dict[str, Any]) -> bool:
    result["details"]["fixture_store"] = _compact_store_response(response)
    if response.get("stored") is True:
        return True
    result["status"] = "fail"
    result["error"] = f"fixture store failed: {response.get('error') or response}"
    return False


def _cleanup_fixture(client: Any, key: str) -> None:
    response = client.delete_memory({"key": key})
    if response.get("deleted") is not True:
        raise RuntimeError(f"benchmark cleanup failed for {key}: {response}")


def _cleanup_benchmark_fixture(result: dict[str, Any], client: Any, key: str) -> None:
    try:
        _cleanup_fixture(client, key)
        result["details"]["cleanup"] = {"key": key, "status": "pass"}
    except Exception as exc:
        result["details"]["cleanup"] = {"key": key, "status": "fail", "error": str(exc)}
        result["status"] = "fail"
        result["error"] = f"cleanup failed: {exc}"


def run_daemon_direct_write(args: argparse.Namespace) -> dict[str, Any]:
    result = _base_result("daemon_direct_write")
    key = _benchmark_key()
    stored = False
    try:
        client = _daemon_client(args)
        health = _daemon_health(client)
        result["details"]["health"] = _compact_health(health)
        response, metrics = _timed(
            "store_memory",
            lambda: _store_fixture(client, key, "direct write latency"),
        )
        result["metrics"].update(metrics)
        result["details"]["fixture_store"] = _compact_store_response(response)
        stored = response.get("stored") is True
        store_result = response.get("result") if isinstance(response.get("result"), dict) else {}
        result["metrics"]["chunk_count"] = store_result.get("chunk_count")
        result["details"]["storage_backend"] = store_result.get("storage_backend")
        result["status"] = "pass" if stored else "fail"
        result["error"] = None if stored else str(response.get("error"))
    except Exception as exc:
        return _daemon_unavailable_result("daemon_direct_write", exc, args)
    finally:
        if stored and "client" in locals():
            _cleanup_benchmark_fixture(result, client, key)
    return result


def run_daemon_metadata_update(args: argparse.Namespace) -> dict[str, Any]:
    result = _base_result("daemon_metadata_update")
    key = _benchmark_key()
    stored = False
    try:
        client = _daemon_client(args)
        health = _daemon_health(client)
        result["details"]["health"] = _compact_health(health)
        response = _store_fixture(client, key, "metadata update latency")
        stored = _store_fixture_required(result, response)
        if not stored:
            return result
        response, metrics = _timed(
            "update_memory_metadata",
            lambda: client.update_memory_metadata(
                {
                    "key": key,
                    "tags": ["benchmark", "temporary", "updated"],
                    "status": "current",
                    "canonical": False,
                }
            ),
        )
        result["metrics"].update(metrics)
        result["metrics"]["updated"] = bool(response.get("updated"))
        result["status"] = "pass" if response.get("updated") else "fail"
        result["error"] = None if result["status"] == "pass" else str(response.get("error"))
    except Exception as exc:
        return _daemon_unavailable_result("daemon_metadata_update", exc, args)
    finally:
        if stored and "client" in locals():
            _cleanup_benchmark_fixture(result, client, key)
    return result


def run_daemon_search(args: argparse.Namespace) -> dict[str, Any]:
    result = _base_result("daemon_search")
    key = _benchmark_key()
    phrase = f"search latency {key}"
    stored = False
    try:
        client = _daemon_client(args)
        health = _daemon_health(client)
        result["details"]["health"] = _compact_health(health)
        response = _store_fixture(client, key, phrase)
        stored = _store_fixture_required(result, response)
        if not stored:
            return result
        response, metrics = _timed(
            "search",
            lambda: client.search_memories({"query": phrase, "limit": 5}),
        )
        result["metrics"].update(metrics)
        results = response.get("results") if isinstance(response.get("results"), list) else []
        result["metrics"]["result_count"] = len(results)
        result["details"]["backend_used"] = response.get("backend_used") or response.get("backend")
        result["details"]["fallback_used"] = response.get("fallback_used")
        found_fixture = any(item.get("key") == key for item in results if isinstance(item, dict))
        result["status"] = "pass" if found_fixture else "fail"
        result["error"] = None if found_fixture else "temporary benchmark memory not found"
    except Exception as exc:
        return _daemon_unavailable_result("daemon_search", exc, args)
    finally:
        if stored and "client" in locals():
            _cleanup_benchmark_fixture(result, client, key)
    return result


def run_daemon_retrieve_chunk(args: argparse.Namespace) -> dict[str, Any]:
    result = _base_result("daemon_retrieve_chunk")
    key = _benchmark_key()
    stored = False
    try:
        client = _daemon_client(args)
        health = _daemon_health(client)
        result["details"]["health"] = _compact_health(health)
        response = _store_fixture(client, key, "chunk retrieval latency")
        stored = _store_fixture_required(result, response)
        if not stored:
            return result
        response, metrics = _timed(
            "retrieve_chunk",
            lambda: client.retrieve_chunk({"key": key, "chunk_id": 0}),
        )
        result["metrics"].update(metrics)
        result["metrics"]["found"] = bool(response.get("found"))
        result["status"] = "pass" if response.get("found") else "fail"
        result["error"] = None if result["status"] == "pass" else str(response.get("error"))
    except Exception as exc:
        return _daemon_unavailable_result("daemon_retrieve_chunk", exc, args)
    finally:
        if stored and "client" in locals():
            _cleanup_benchmark_fixture(result, client, key)
    return result


def run_document_ingestion(args: argparse.Namespace) -> dict[str, Any]:
    result = _base_result("document_ingestion")
    try:
        from core.reliability_harness import run_document_intelligence_ingestion_check

        payload, metrics = _timed("document_ingestion", run_document_intelligence_ingestion_check)
        result["metrics"].update(metrics)
        result["metrics"]["chunk_count"] = payload.get("chunk_count")
        result["metrics"]["indexed_count"] = payload.get("indexed_count")
        result["details"]["status_values"] = payload.get("status_values")
        result["details"]["active_memory_write_performed"] = payload.get(
            "active_memory_write_performed"
        )
        result["status"] = "pass" if payload.get("status") == "pass" else "fail"
        result["error"] = None if result["status"] == "pass" else str(payload.get("findings"))
    except Exception as exc:
        result["status"] = "fail"
        result["error"] = str(exc)
    return result


def run_docker_startup(args: argparse.Namespace) -> dict[str, Any]:
    result = _base_result("docker_startup")
    if shutil.which("docker") is None:
        result["status"] = "skipped"
        result["error"] = "docker not found"
        return result
    config_result = _run_command(["docker", "compose", "config"], timeout=args.timeout)
    result["metrics"]["docker_compose_config_ms"] = config_result["duration_ms"]
    result["details"]["compose_config"] = config_result
    if config_result["status"] != "pass":
        result["status"] = "fail"
        result["error"] = "docker compose config failed"
        return result
    if not args.include_docker_live:
        result["status"] = "skipped"
        result["error"] = "pass --include-docker-live to measure isolated Compose startup"
        return result
    if _tcp_port_open("127.0.0.1", 8765):
        result["status"] = "skipped"
        result["error"] = (
            "127.0.0.1:8765 is already in use; stop the local daemon or change "
            "compose ports before Docker startup benchmarking"
        )
        return result
    project_name = f"engram-benchmark-{os.getpid()}"
    startup = _run_command(
        ["docker", "compose", "-p", project_name, "up", "-d", "--wait", "engramd-core"],
        timeout=args.timeout,
    )
    result["metrics"]["docker_compose_startup_ms"] = startup["duration_ms"]
    result["details"]["compose_startup"] = startup
    result["status"] = startup["status"]
    result["error"] = None if startup["status"] == "pass" else "docker compose startup failed"
    cleanup = _run_command(
        ["docker", "compose", "-p", project_name, "down", "-v"],
        timeout=args.timeout,
    )
    result["details"]["cleanup"] = cleanup
    if cleanup["status"] != "pass":
        result["status"] = "fail"
        result["error"] = "docker compose cleanup failed"
    return result


def _tcp_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) == 0


def run_ops_commands(args: argparse.Namespace) -> dict[str, Any]:
    result = _base_result("ops_commands")
    with contextlib.ExitStack() as stack:
        commands = [
            ("validate_self_hosting", [sys.executable, "scripts/validate_self_hosting.py"], None),
            ("server_help", [sys.executable, "server.py", "--help"], None),
        ]
        if args.include_slow_ops:
            self_test_root = stack.enter_context(
                tempfile.TemporaryDirectory(prefix="engram-benchmark-self-test-")
            )
            agent_eval_root = stack.enter_context(
                tempfile.TemporaryDirectory(prefix="engram-benchmark-agent-eval-")
            )
            commands.extend(
                [
                    ("doctor", [sys.executable, "engramd.py", "--doctor"], None),
                    ("smoke_test", [sys.executable, "engramd.py", "--smoke-test"], None),
                    (
                        "self_test",
                        [sys.executable, "server.py", "--self-test"],
                        _isolated_env(self_test_root),
                    ),
                    (
                        "agent_eval",
                        [sys.executable, "server.py", "--agent-eval"],
                        _isolated_env(agent_eval_root),
                    ),
                ]
            )
        for name, command, extra_env in commands:
            env = {**os.environ, **(extra_env or {})}
            command_result = _run_command(command, timeout=args.timeout, env=env)
            result["metrics"][f"{name}_ms"] = command_result["duration_ms"]
            result["details"][name] = command_result
            if command_result["status"] != "pass":
                result["status"] = "fail"
                result["error"] = f"{name} failed"
    return result


SCENARIO_RUNNERS: dict[str, Callable[[argparse.Namespace], dict[str, Any]]] = {
    "startup_imports": run_startup_imports,
    "daemon_search": run_daemon_search,
    "daemon_retrieve_chunk": run_daemon_retrieve_chunk,
    "daemon_direct_write": run_daemon_direct_write,
    "daemon_metadata_update": run_daemon_metadata_update,
    "document_ingestion": run_document_ingestion,
    "docker_startup": run_docker_startup,
    "ops_commands": run_ops_commands,
}


def render_text(payload: dict[str, Any]) -> str:
    if payload.get("run_performed") is False or "scenarios" in payload:
        return "\n".join(
            f"{scenario['id']}: {scenario['description']} ({scenario['command']})"
            for scenario in payload.get("scenarios", [])
        )
    lines = []
    for result in payload.get("results", []):
        lines.append(f"{result['id']}: {result['status']} {result.get('metrics', {})}")
        if result.get("error"):
            lines.append(f"  error: {result['error']}")
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run or list repeatable Engram performance benchmarks."
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--list", action="store_true", help="List benchmark scenarios.")
    action.add_argument(
        "--plan",
        action="store_true",
        help="Emit a machine-readable plan without running benchmarks.",
    )
    action.add_argument("--run", action="store_true", help="Run selected benchmark scenarios.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of human text.")
    parser.add_argument(
        "--scenario",
        action="append",
        help="Scenario id to include. May be repeated.",
    )
    parser.add_argument(
        "--daemon-url",
        default=DEFAULT_DAEMON_URL,
        help="Daemon URL for live-daemon scenarios.",
    )
    parser.add_argument(
        "--include-live-daemon",
        action="store_true",
        help="Include live-daemon scenarios when no --scenario is provided.",
    )
    parser.add_argument(
        "--require-live-daemon",
        action="store_true",
        help="Fail instead of skip when a live daemon benchmark cannot connect.",
    )
    parser.add_argument(
        "--include-docker-live",
        action="store_true",
        help="Run isolated Docker Compose startup instead of config-only checks.",
    )
    parser.add_argument(
        "--include-slow-ops",
        action="store_true",
        help="Include doctor, smoke, self-test, and agent-eval in ops_commands.",
    )
    parser.add_argument("--timeout", type=int, default=180, help="Per-command timeout in seconds.")
    args = parser.parse_args(argv)
    if not (args.list or args.plan or args.run):
        args.plan = True
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.list:
        payload = scenario_catalog()
    elif args.run:
        payload = run_benchmarks(args)
    else:
        payload = benchmark_plan(args.scenario)

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print(render_text(payload))
    return 1 if payload.get("summary", {}).get("failed", 0) else 0


if __name__ == "__main__":
    raise SystemExit(main())
