from __future__ import annotations

import asyncio

import server


class HealthyDaemonClient:
    def health(self):
        return {
            "daemon": "engramd",
            "status": "ok",
            "stats": {"total_memories": 4, "total_chunks": 9},
            "error": None,
        }


class FailingDaemonClient:
    def health(self):
        raise RuntimeError("connection refused")


def test_daemon_status_reports_direct_mode_without_env(monkeypatch):
    monkeypatch.delenv("ENGRAM_DAEMON_URL", raising=False)

    payload = asyncio.run(server.daemon_status())

    assert payload["schema_version"] == "2026-05-12.daemon-status.v1"
    assert payload["mode"] == "direct"
    assert payload["daemon_enabled"] is False
    assert payload["configured_url"] is None
    assert payload["reachable"] is False
    assert payload["health"] is None
    assert payload["error"] is None


def test_daemon_status_checks_configured_daemon(monkeypatch):
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765/")
    monkeypatch.setattr(server, "_daemon_client", lambda: HealthyDaemonClient())

    payload = asyncio.run(server.daemon_status())

    assert payload["mode"] == "daemon_client"
    assert payload["daemon_enabled"] is True
    assert payload["configured_url"] == "http://127.0.0.1:8765"
    assert payload["reachable"] is True
    assert payload["health"]["status"] == "ok"
    assert payload["health"]["stats"]["total_chunks"] == 9
    assert "check_duplicate" in payload["stable_tools_routed"]
    assert "update_memory_metadata" in payload["stable_tools_routed"]
    assert "repair_memory_metadata" in payload["stable_tools_routed"]
    assert payload["error"] is None


def test_daemon_status_reports_unreachable_daemon(monkeypatch):
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: FailingDaemonClient())

    payload = asyncio.run(server.daemon_status())

    assert payload["mode"] == "daemon_client"
    assert payload["daemon_enabled"] is True
    assert payload["reachable"] is False
    assert payload["health"] is None
    assert payload["error"]["code"] == "runtime_error"
    assert "connection refused" in payload["error"]["message"]


def test_memory_protocol_advertises_daemon_status():
    payload = asyncio.run(server.memory_protocol())

    assert payload["stability"]["daemon_status"] == "beta"
    assert payload["tool_groups"]["daemon_runtime"]["tools"] == ["daemon_status"]
    assert payload["progressive_discovery"]["load_next"]["daemon status"] == "daemon_status"
    assert "daemon_status" in payload["canonical_tools"]
    assert any("ENGRAM_DAEMON_URL" in warning for warning in payload["warnings"])
