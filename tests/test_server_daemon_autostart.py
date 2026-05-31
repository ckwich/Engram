from __future__ import annotations

import sys
from pathlib import Path

import pytest

import server
from core.engramd_client import EngramDaemonClientError


def test_ensure_daemon_available_autostarts_loopback_daemon(monkeypatch, tmp_path):
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:9876")
    monkeypatch.setenv("ENGRAM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ENGRAM_DAEMON_AUTOSTART_TIMEOUT", "0.1")

    probes = []
    starts = []

    def fake_probe():
        probes.append("probe")
        if len(probes) == 1:
            raise EngramDaemonClientError("Daemon request failed: refused")
        return {"daemon": "engramd", "status": "ok", "error": None}

    def fake_start(url):
        starts.append(url)
        return {"pid": 1234, "log_path": str(tmp_path / "engramd-autostart.log")}

    monkeypatch.setattr(server, "_probe_daemon_health", fake_probe)
    monkeypatch.setattr(server, "_start_local_daemon_process", fake_start)
    monkeypatch.setattr(server, "_sleep_for_daemon_start", lambda seconds: None)

    payload = server._ensure_daemon_available_for_mcp()

    assert payload["mode"] == "daemon_client"
    assert payload["reachable"] is True
    assert payload["health"]["status"] == "ok"
    assert payload["autostart"]["attempted"] is True
    assert payload["autostart"]["started"] is True
    assert payload["autostart"]["pid"] == 1234
    assert starts == ["http://127.0.0.1:9876"]
    assert len(probes) >= 2


def test_ensure_daemon_available_does_not_autostart_remote_daemon(monkeypatch):
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://192.168.1.10:8765")
    monkeypatch.delenv("ENGRAM_DAEMON_AUTOSTART", raising=False)

    monkeypatch.setattr(
        server,
        "_probe_daemon_health",
        lambda: (_ for _ in ()).throw(EngramDaemonClientError("connection refused")),
    )
    monkeypatch.setattr(
        server,
        "_start_local_daemon_process",
        lambda url: pytest.fail("remote daemon URLs must not be autostarted"),
    )

    payload = server._ensure_daemon_available_for_mcp()

    assert payload["mode"] == "daemon_client"
    assert payload["reachable"] is False
    assert payload["autostart"]["attempted"] is False
    assert payload["autostart"]["reason"] == "not_loopback_url"
    assert payload["error"]["code"] == "runtime_error"


def test_ensure_daemon_available_respects_disabled_autostart(monkeypatch):
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("ENGRAM_DAEMON_AUTOSTART", "0")

    monkeypatch.setattr(
        server,
        "_probe_daemon_health",
        lambda: (_ for _ in ()).throw(EngramDaemonClientError("connection refused")),
    )
    monkeypatch.setattr(
        server,
        "_start_local_daemon_process",
        lambda url: pytest.fail("autostart was disabled explicitly"),
    )

    payload = server._ensure_daemon_available_for_mcp()

    assert payload["reachable"] is False
    assert payload["autostart"]["attempted"] is False
    assert payload["autostart"]["reason"] == "disabled"
    assert payload["error"]["code"] == "runtime_error"


def test_start_local_daemon_process_uses_current_python_and_pinned_data_dir(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("ENGRAM_DATA_DIR", str(tmp_path))

    calls = []

    class FakeProcess:
        pid = 9876

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setattr(server.subprocess, "Popen", fake_popen)

    payload = server._start_local_daemon_process("http://127.0.0.1:9876")

    assert payload["pid"] == 9876
    assert payload["log_path"].endswith("engramd-autostart.log")
    args, kwargs = calls[0]
    assert args == [
        sys.executable,
        str((Path(server.__file__).resolve().parent / "engramd.py").resolve()),
        "--host",
        "127.0.0.1",
        "--port",
        "9876",
    ]
    assert Path(kwargs["cwd"]).resolve() == Path(server.__file__).resolve().parent
    assert Path(kwargs["env"]["ENGRAM_DATA_DIR"]).resolve() == tmp_path
    assert kwargs["stdin"] is server.subprocess.DEVNULL


def test_prepare_mcp_runtime_skips_local_embedder_when_daemon_mode(monkeypatch):
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(
        server,
        "_ensure_daemon_available_for_mcp",
        lambda: {
            "mode": "daemon_client",
            "reachable": True,
            "health": {"status": "ok", "error": None},
            "autostart": {"attempted": False, "reason": "already_running"},
            "error": None,
        },
    )
    monkeypatch.setattr(
        server.embedder,
        "_load",
        lambda: pytest.fail("daemon-client MCP startup must not load local embeddings"),
    )

    payload = server._prepare_mcp_runtime_before_start()

    assert payload["mode"] == "daemon_client"
    assert payload["reachable"] is True
