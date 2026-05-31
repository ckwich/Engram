from __future__ import annotations

import signal
from pathlib import Path

from core.process_hygiene import (
    ProcessInfo,
    build_process_hygiene_report,
    classify_engram_process,
    stop_server_pids,
)


REPO_ROOT = Path("C:/Projects/Engram")


def _proc(pid: int, command_line: str, *, parent_pid: int = 1) -> ProcessInfo:
    return ProcessInfo(
        pid=pid,
        parent_pid=parent_pid,
        name="python.exe",
        command_line=command_line,
    )


def test_classify_engram_processes_for_this_checkout():
    server_proc = _proc(101, r'"C:\Python\python.exe" "C:\Projects\Engram\server.py"')
    daemon_proc = _proc(102, r'"C:\Python\python.exe" "C:\Projects\Engram\engramd.py"')
    health_proc = _proc(
        103,
        r'"C:\Python\python.exe" "C:\Projects\Engram\engramd.py" --health',
    )
    other_repo = _proc(104, r'"C:\Python\python.exe" "C:\Other\Engram\server.py"')

    assert classify_engram_process(server_proc, REPO_ROOT) == "mcp_server"
    assert classify_engram_process(daemon_proc, REPO_ROOT) == "daemon"
    assert classify_engram_process(health_proc, REPO_ROOT) == "daemon_cli"
    assert classify_engram_process(other_repo, REPO_ROOT) == "unrelated"


def test_process_hygiene_report_marks_explicit_stop_candidates():
    processes = [
        _proc(101, r'"C:\Python\python.exe" "C:\Projects\Engram\server.py"'),
        _proc(102, r'"C:\Python\python.exe" "C:\Projects\Engram\engramd.py"'),
        _proc(103, r'"C:\Python\python.exe" "C:\Projects\Engram\server.py"', parent_pid=101),
    ]

    report = build_process_hygiene_report(processes, REPO_ROOT, current_pid=103)

    assert report["schema_version"] == "2026-05-13.process-hygiene.v1"
    assert report["counts"]["mcp_server"] == 2
    assert report["counts"]["daemon"] == 1
    assert report["explicit_stop_candidate_pids"] == [101]
    assert report["processes"][0]["kind"] == "mcp_server"
    assert report["processes"][0]["explicit_stop_allowed"] is True
    assert report["processes"][2]["explicit_stop_allowed"] is False
    assert any("explicit" in item for item in report["recommendations"])


def test_process_hygiene_report_warns_about_multiple_daemons():
    processes = [
        _proc(101, r'"C:\Python\python.exe" "C:\Projects\Engram\engramd.py"'),
        _proc(102, r'"C:\Python\python.exe" "C:\Projects\Engram\engramd.py"'),
    ]

    report = build_process_hygiene_report(processes, REPO_ROOT, current_pid=999)

    assert report["counts"]["daemon"] == 2
    assert any("Multiple engramd.py daemon processes" in item for item in report["warnings"])
    assert any("Keep one daemon owner" in item for item in report["recommendations"])


def test_process_hygiene_collapses_windows_venv_launcher_daemon_pair():
    processes = [
        _proc(
            201,
            r'"C:\Projects\Engram\venv\Scripts\python.exe" C:\Projects\Engram\engramd.py --host 127.0.0.1 --port 8765',
            parent_pid=10,
        ),
        _proc(
            202,
            r'"C:\Programs\Python312\python.exe" C:\Projects\Engram\engramd.py --host 127.0.0.1 --port 8765',
            parent_pid=201,
        ),
    ]

    report = build_process_hygiene_report(processes, REPO_ROOT, current_pid=999)

    assert report["counts"]["daemon"] == 1
    assert report["counts"]["daemon_launcher"] == 1
    assert report["processes"][0]["kind"] == "daemon_launcher"
    assert report["processes"][1]["kind"] == "daemon"
    assert not any("Multiple engramd.py daemon processes" in item for item in report["warnings"])


def test_stop_server_pids_only_stops_exact_this_checkout_server_processes():
    processes = [
        _proc(101, r'"C:\Python\python.exe" "C:\Projects\Engram\server.py"'),
        _proc(102, r'"C:\Python\python.exe" "C:\Projects\Engram\engramd.py"'),
        _proc(103, r'"C:\Python\python.exe" "C:\Other\Engram\server.py"'),
        _proc(104, r'"C:\Python\python.exe" "C:\Projects\Engram\server.py"'),
    ]
    killed = []

    def fake_killer(pid: int, sig: int) -> None:
        killed.append((pid, sig))

    result = stop_server_pids(
        [101, 102, 103, 104, 999],
        processes,
        REPO_ROOT,
        current_pid=104,
        killer=fake_killer,
    )

    assert killed == [(101, signal.SIGTERM)]
    assert result["stopped"] == [{"pid": 101, "signal": "SIGTERM"}]
    skipped = {item["pid"]: item["reason"] for item in result["skipped"]}
    assert skipped[102] == "not_this_checkout_mcp_server"
    assert skipped[103] == "not_this_checkout_mcp_server"
    assert skipped[104] == "current_process"
    assert skipped[999] == "not_found"
