"""Process diagnostics for local Engram daemon/MCP ownership."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from typing import Any, Callable, Iterable


PROCESS_HYGIENE_SCHEMA_VERSION = "2026-05-13.process-hygiene.v1"


@dataclass(frozen=True)
class ProcessInfo:
    """Small cross-platform process record used by process hygiene checks."""

    pid: int
    parent_pid: int | None
    name: str | None
    command_line: str


def _normalize_command_text(value: str) -> str:
    return " ".join(value.replace("\\", "/").lower().split())


def _script_marker(repo_root: Path, script_name: str) -> str:
    return str((repo_root / script_name).resolve()).replace("\\", "/").lower()


def _has_any_flag(command: str, flags: Iterable[str]) -> bool:
    return any(flag in command for flag in flags)


def classify_engram_process(process: ProcessInfo, repo_root: Path) -> str:
    """Classify only processes that clearly belong to this Engram checkout."""
    command = _normalize_command_text(process.command_line or "")
    server_marker = _script_marker(repo_root, "server.py")
    daemon_marker = _script_marker(repo_root, "engramd.py")

    if daemon_marker in command:
        if _has_any_flag(
            command,
            [
                "--health",
                "--smoke-test",
                "--doctor",
                "--stop-server-pid",
            ],
        ):
            return "daemon_cli"
        return "daemon"

    if server_marker in command:
        if _has_any_flag(
            command,
            [
                "--health",
                "--self-test",
                "--agent-eval",
                "--generate-config",
                "--rebuild-index",
                "--export",
                "--import-file",
                "--migrate",
            ],
        ):
            return "server_cli"
        return "mcp_server"

    return "unrelated"


def _process_payload(
    process: ProcessInfo,
    *,
    repo_root: Path,
    current_pid: int | None,
) -> dict[str, Any] | None:
    kind = classify_engram_process(process, repo_root)
    if kind == "unrelated":
        return None
    explicit_stop_allowed = kind == "mcp_server" and process.pid != current_pid
    return {
        "pid": process.pid,
        "parent_pid": process.parent_pid,
        "name": process.name,
        "kind": kind,
        "command_line": process.command_line,
        "explicit_stop_allowed": explicit_stop_allowed,
    }


def build_process_hygiene_report(
    processes: Iterable[ProcessInfo],
    repo_root: Path,
    *,
    current_pid: int | None = None,
) -> dict[str, Any]:
    """Build a no-write report for Engram daemon/MCP process hygiene."""
    if current_pid is None:
        current_pid = os.getpid()

    process_payloads: list[dict[str, Any]] = []
    counts: dict[str, int] = {
        "daemon": 0,
        "daemon_cli": 0,
        "mcp_server": 0,
        "server_cli": 0,
    }

    for process in sorted(processes, key=lambda item: item.pid):
        payload = _process_payload(process, repo_root=repo_root, current_pid=current_pid)
        if payload is None:
            continue
        counts[payload["kind"]] = counts.get(payload["kind"], 0) + 1
        process_payloads.append(payload)

    stop_candidates = [
        item["pid"] for item in process_payloads if item["explicit_stop_allowed"]
    ]
    warnings: list[str] = []
    recommendations: list[str] = []

    if counts["daemon"] == 0:
        warnings.append("No live engramd.py daemon process was identified for this checkout.")
        recommendations.append(
            "Start engramd.py or use daemon-client MCP autostart with ENGRAM_DAEMON_URL."
        )
    elif counts["daemon"] > 1:
        warnings.append(
            "Multiple engramd.py daemon processes were identified for this checkout."
        )
        recommendations.append(
            "Keep one daemon owner for this checkout; stop duplicate daemon processes "
            "manually only after confirming which PID owns the active ENGRAM_DAEMON_URL."
        )
    if counts["mcp_server"] > 1:
        warnings.append(
            "Multiple server.py MCP adapter processes were identified for this checkout."
        )
    if stop_candidates:
        recommendations.append(
            "Stop stale MCP adapters only by explicit PID, for example: "
            "python engramd.py --stop-server-pid " + " ".join(str(pid) for pid in stop_candidates)
        )

    return {
        "schema_version": PROCESS_HYGIENE_SCHEMA_VERSION,
        "repo_root": str(repo_root.resolve()),
        "current_pid": current_pid,
        "counts": counts,
        "processes": process_payloads,
        "explicit_stop_candidate_pids": stop_candidates,
        "warnings": warnings,
        "recommendations": recommendations,
    }


def _process_from_mapping(payload: dict[str, Any]) -> ProcessInfo:
    return ProcessInfo(
        pid=int(payload.get("ProcessId") or payload.get("pid") or 0),
        parent_pid=(
            int(payload["ParentProcessId"])
            if payload.get("ParentProcessId") is not None
            else None
        ),
        name=payload.get("Name") or payload.get("name"),
        command_line=str(payload.get("CommandLine") or payload.get("command_line") or ""),
    )


def _discover_windows_processes(timeout: float) -> list[ProcessInfo]:
    command = (
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ParentProcessId,Name,CommandLine | "
        "ConvertTo-Json -Compress"
    )
    result = subprocess.run(  # nosec B603
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "failed to list Windows processes")
    text = result.stdout.strip()
    if not text:
        return []
    decoded = json.loads(text)
    if isinstance(decoded, dict):
        decoded = [decoded]
    return [_process_from_mapping(item) for item in decoded]


def _discover_posix_processes(timeout: float) -> list[ProcessInfo]:
    result = subprocess.run(  # nosec B603
        ["ps", "-eo", "pid=,ppid=,comm=,args="],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "failed to list processes")

    processes: list[ProcessInfo] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        pid_text, ppid_text, name, command_line = parts
        processes.append(
            ProcessInfo(
                pid=int(pid_text),
                parent_pid=int(ppid_text),
                name=name,
                command_line=command_line,
            )
        )
    return processes


def discover_processes(timeout: float = 10.0) -> list[ProcessInfo]:
    """Return process records using the host platform's process-list command."""
    if sys.platform.startswith("win"):
        return _discover_windows_processes(timeout)
    return _discover_posix_processes(timeout)


def stop_server_pids(
    pids: Iterable[int],
    processes: Iterable[ProcessInfo],
    repo_root: Path,
    *,
    current_pid: int | None = None,
    killer: Callable[[int, int], None] = os.kill,
) -> dict[str, Any]:
    """Stop explicit PIDs only when they are this checkout's server.py process."""
    if current_pid is None:
        current_pid = os.getpid()
    requested_pids = [int(pid) for pid in pids]
    process_by_pid = {process.pid: process for process in processes}
    stopped: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    seen: set[int] = set()
    for pid in requested_pids:
        if pid in seen:
            continue
        seen.add(pid)
        process = process_by_pid.get(pid)
        if process is None:
            skipped.append({"pid": pid, "reason": "not_found"})
            continue
        if pid == current_pid:
            skipped.append({"pid": pid, "reason": "current_process"})
            continue
        if classify_engram_process(process, repo_root) != "mcp_server":
            skipped.append({"pid": pid, "reason": "not_this_checkout_mcp_server"})
            continue
        try:
            killer(pid, signal.SIGTERM)
        except Exception as exc:
            skipped.append({"pid": pid, "reason": "kill_failed", "error": str(exc)})
            continue
        stopped.append({"pid": pid, "signal": "SIGTERM"})

    return {
        "schema_version": PROCESS_HYGIENE_SCHEMA_VERSION,
        "repo_root": str(repo_root.resolve()),
        "requested_pids": requested_pids,
        "stopped": stopped,
        "skipped": skipped,
    }
