from __future__ import annotations

from pathlib import Path

from core.memory_os._records import upsert_record
from core.memory_os.inspector import build_memory_os_inspector
from core.memory_os.ledger import MemoryOSLedger


class FakeRuntime:
    def __init__(self, ledger, *, retrieval_ready=True, sync_status=None):
        self.ledger = ledger
        self._retrieval_ready = retrieval_ready
        self._sync_status = sync_status or {
            "status": "ready",
            "local_device": {"device_id": "device:laptop"},
            "peer_count": 1,
            "active_peer_count": 1,
            "revoked_peer_count": 0,
            "pending_conflict_count": 1,
            "last_exported_at": "2026-05-26T10:00:00+00:00",
            "last_applied_at": "2026-05-26T10:05:00+00:00",
        }

    def status(self):
        return {
            "status": "ok",
            "components": {
                "ledger": {"path": str(self.ledger.path), "exists": True},
                "retrieval": {
                    "backend": "LanceDBVectorIndex",
                    "ready": self._retrieval_ready,
                    "state": {"status": "ready" if self._retrieval_ready else "repair_pending"},
                },
                "graph": {"backend": "KuzuGraphStore", "ready": True},
            },
        }

    def sync_status(self):
        return self._sync_status


def test_sync_inspector_panel_reports_hub_and_peer_health_without_hub_secrets(tmp_path, monkeypatch):
    ledger = MemoryOSLedger(tmp_path / "engram.sqlite")
    hub_url = "http://engram-hub.tailnet-name.ts.net:8767"
    token = "x" * 40
    monkeypatch.setenv("ENGRAM_HUB_URL", hub_url)
    monkeypatch.setenv("ENGRAM_HUB_ACCESS_TOKEN", token)
    _seed_sync_records(ledger)

    payload = build_memory_os_inspector(FakeRuntime(ledger), limit=10)
    panel = payload["sync"]["panel"]

    assert panel["active_mode"] == "hub"
    assert panel["hub"]["configured"] is True
    assert panel["hub"]["auth_ready"] is True
    assert panel["hub"]["url_fingerprint"].startswith("sha256:")
    assert panel["hub"]["reachability"]["status"] == "not_checked"
    assert hub_url not in str(panel)
    assert token not in str(panel)
    assert panel["local_device_id"] == "device:laptop"
    assert panel["peers"][0]["device_id"] == "device:desktop"
    assert panel["peer_direction_health"][0]["peer_id"] == "device:desktop"
    assert "outbound_lag" in panel["peer_direction_health"][0]
    assert "inbound_lag" in panel["peer_direction_health"][0]
    assert panel["peer_direction_health"][0]["convergence_status"] == "conflicts_pending"
    assert panel["last_export"]["exported_at"] == "2026-05-26T10:00:00+00:00"
    assert panel["last_apply"]["applied_at"] == "2026-05-26T10:05:00+00:00"
    assert panel["pending_conflicts"] == 1
    assert panel["last_snapshot_id"] == "snapshot:sync"
    assert panel["rebuild_required"] is False
    assert panel["safe_next_command"] == 'list_sync_conflicts(status="pending_review")'
    assert panel["write_performed"] is False


def test_sync_inspector_warns_when_hub_configured_but_client_is_standalone(tmp_path, monkeypatch):
    ledger = MemoryOSLedger(tmp_path / "engram.sqlite")
    monkeypatch.setenv("ENGRAM_HUB_URL", "http://engram-hub.tailnet-name.ts.net:8767")
    monkeypatch.setenv("ENGRAM_HUB_ACCESS_TOKEN", "too-short")

    payload = build_memory_os_inspector(
        FakeRuntime(
            ledger,
            sync_status={
                "status": "not_configured",
                "local_device": None,
                "peer_count": 0,
                "active_peer_count": 0,
                "revoked_peer_count": 0,
                "pending_conflict_count": 0,
                "last_exported_at": None,
                "last_applied_at": None,
            },
        ),
        limit=10,
    )
    panel = payload["sync"]["panel"]

    assert panel["active_mode"] == "standalone"
    assert panel["hub"]["auth_ready"] is False
    assert panel["warnings"][0]["code"] == "hub_configured_but_not_ready"
    assert "too-short" not in str(panel)
    assert panel["safe_next_command"] == "Set ENGRAM_HUB_ACCESS_TOKEN and run python engramd.py --doctor"


def test_sync_inspector_api_returns_read_only_sync_panel(monkeypatch):
    import webui

    def fake_memory_os_inspector_payload(*, limit=20):
        return {
            "schema_version": "2026-05-13.memory-os-inspector.v1",
            "limit": limit,
            "write_performed": False,
            "sync": {
                "status": {"status": "ready"},
                "panel": {"active_mode": "hub", "write_performed": False},
                "write_performed": False,
            },
        }

    monkeypatch.setattr(webui, "get_memory_os_inspector_payload", fake_memory_os_inspector_payload)

    response = webui.app.test_client().get("/api/inspector/sync?limit=7")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["write_performed"] is False
    assert payload["limit"] == 7
    assert payload["sync"]["panel"]["active_mode"] == "hub"
    assert payload["sync"]["panel"]["write_performed"] is False


def test_sync_panel_is_wired_into_static_inspector_assets():
    html = Path("templates/index.html").read_text(encoding="utf-8")
    js = Path("static/app.js").read_text(encoding="utf-8")

    assert 'id="inspector-sync-list"' in html
    assert "syncPanelRows" in js
    assert "memoryOS.sync" in js


def _seed_sync_records(ledger):
    upsert_record(
        ledger,
        "sync_devices",
        "sync_device:local",
        {
            "record_type": "sync_device",
            "device_id": "device:laptop",
            "device_name": "laptop",
            "status": "active",
            "sync_allowed": True,
        },
    )
    upsert_record(
        ledger,
        "sync_devices",
        "sync_device:peer:device:desktop",
        {
            "record_type": "sync_peer",
            "device_id": "device:desktop",
            "device_name": "desktop",
            "status": "active",
            "sync_allowed": True,
            "transport": {
                "url": "http://100.64.0.8:8768",
                "mode": "push",
                "allow_pull": False,
            },
        },
    )
    upsert_record(
        ledger,
        "sync_changesets",
        "sync_changeset:one",
        {
            "changeset_id": "sync_changeset:one",
            "target_device_id": "device:desktop",
            "exported_at": "2026-05-26T10:00:00+00:00",
            "row_count": 2,
        },
    )
    upsert_record(
        ledger,
        "sync_cursors",
        "sync_cursor:desktop",
        {
            "cursor_id": "sync_cursor:desktop",
            "source_device_id": "device:desktop",
            "applied_at": "2026-05-26T10:05:00+00:00",
        },
    )
    upsert_record(
        ledger,
        "sync_conflicts",
        "sync_conflict:desktop",
        {
            "conflict_id": "sync_conflict:desktop",
            "source_device_id": "device:desktop",
            "status": "pending_review",
        },
    )
    upsert_record(
        ledger,
        "snapshots",
        "snapshot:sync",
        {
            "snapshot_id": "snapshot:sync",
            "record_type": "runtime_snapshot",
            "created_at": "2026-05-26T10:04:00+00:00",
        },
    )
