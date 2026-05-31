from __future__ import annotations

import engramd


def test_doctor_payload_lifts_graph_reconciliation_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("ENGRAM_DATA_DIR", str(tmp_path / "safe-data"))
    graph_state = {
        "status": "drift",
        "trusted_for_evidence": False,
        "repair_required": True,
        "ledger": {"edge_count": 2},
        "graph_store": {"edge_count": 1},
        "drift": {"missing_in_store_sample": ["edge:missing"]},
        "repair_guidance": {"message": "Replay ledger graph edges."},
    }

    class FakeClient:
        def __init__(self, url):
            self.url = url

        def health(self):
            return {
                "status": "ok",
                "memory_os": {
                    "components": {
                        "graph": {
                            "state": graph_state,
                        }
                    }
                },
            }

    monkeypatch.setattr(engramd, "EngramDaemonClient", FakeClient)
    monkeypatch.setattr(
        engramd,
        "build_process_hygiene_report",
        lambda processes, repo_root: {"status": "ok"},
    )
    monkeypatch.setattr(engramd, "discover_processes", lambda: [])

    payload = engramd.build_doctor_payload("127.0.0.1", 8765)

    assert payload["runtime_preflight"]["safe_to_start"] is True
    assert payload["graph_reconciliation"] == {
        "status": "drift",
        "trusted_for_evidence": False,
        "repair_required": True,
        "ledger_edge_count": 2,
        "graph_store_edge_count": 1,
        "drift": {"missing_in_store_sample": ["edge:missing"]},
        "repair_guidance": {"message": "Replay ledger graph edges."},
    }


def test_doctor_payload_graph_reconciliation_unknown_without_daemon_health(tmp_path, monkeypatch):
    monkeypatch.setenv("ENGRAM_DATA_DIR", str(tmp_path / "safe-data"))
    class FakeClient:
        def __init__(self, url):
            self.url = url

        def health(self):
            raise RuntimeError("daemon unavailable")

    monkeypatch.setattr(engramd, "EngramDaemonClient", FakeClient)
    monkeypatch.setattr(
        engramd,
        "build_process_hygiene_report",
        lambda processes, repo_root: {"status": "ok"},
    )
    monkeypatch.setattr(engramd, "discover_processes", lambda: [])

    payload = engramd.build_doctor_payload("127.0.0.1", 8765)

    assert payload["graph_reconciliation"]["status"] == "unknown"
    assert payload["graph_reconciliation"]["trusted_for_evidence"] is False
    assert payload["graph_reconciliation"]["repair_required"] is True


def test_preflight_cli_returns_blocked_for_checkout_runtime_path(tmp_path, monkeypatch, capsys):
    data_root = tmp_path / "Engram" / "data"
    monkeypatch.setenv("ENGRAM_DATA_DIR", str(data_root))
    monkeypatch.setattr(engramd, "__file__", str(tmp_path / "Engram" / "engramd.py"))

    status = engramd.main(["--preflight"])
    output = capsys.readouterr().out

    assert status == 2
    assert "repo_checkout_runtime_path" in output
