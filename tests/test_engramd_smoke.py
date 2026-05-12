from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

import engramd
from core.engramd_client import EngramDaemonClient
from core.engramd_smoke import SMOKE_MARKER, run_daemon_smoke


REPO_ROOT = Path(__file__).resolve().parents[1]


class FakeSmokeClient:
    def __init__(self):
        self.calls: list[tuple[str, dict | None]] = []
        self.stored_key = "_engramd_smoke_test"

    def health(self):
        self.calls.append(("health", None))
        return {"daemon": "engramd", "status": "ok", "error": None}

    def store_memory(self, payload):
        self.calls.append(("store_memory", payload))
        self.stored_key = payload["key"]
        return {
            "stored": True,
            "result": {
                "key": payload["key"],
                "title": payload["title"],
                "chunk_count": 1,
                "chars": len(payload["content"]),
            },
            "error": None,
        }

    def update_memory_metadata(self, payload):
        self.calls.append(("update_memory_metadata", payload))
        return {
            "key": payload["key"],
            "updated": True,
            "memory": {
                "key": payload["key"],
                "title": payload["title"],
                "tags": payload["tags"],
            },
            "error": None,
        }

    def search_memories(self, payload):
        self.calls.append(("search_memories", payload))
        return {
            "query": payload["query"],
            "count": 1,
            "results": [
                {
                    "key": self.stored_key,
                    "chunk_id": 0,
                    "title": "Engramd Smoke Test",
                    "score": 0.99,
                }
            ],
            "error": None,
        }

    def retrieve_chunk(self, payload):
        self.calls.append(("retrieve_chunk", payload))
        return {
            "key": payload["key"],
            "chunk_id": payload["chunk_id"],
            "found": True,
            "chunk": {"title": "Engramd Smoke Test", "text": SMOKE_MARKER},
            "error": None,
        }

    def retrieve_memory(self, payload):
        self.calls.append(("retrieve_memory", payload))
        return {
            "key": payload["key"],
            "found": True,
            "memory": {"key": payload["key"], "content": SMOKE_MARKER},
            "error": None,
        }

    def delete_memory(self, payload):
        self.calls.append(("delete_memory", payload))
        return {"key": payload["key"], "deleted": True, "error": None}


def test_run_daemon_smoke_exercises_full_memory_cycle():
    client = FakeSmokeClient()

    payload = run_daemon_smoke(client, key="_engramd_smoke_test")

    assert payload["status"] == "ok"
    assert payload["error"] is None
    assert [call[0] for call in client.calls] == [
        "health",
        "store_memory",
        "update_memory_metadata",
        "search_memories",
        "retrieve_chunk",
        "retrieve_memory",
        "delete_memory",
    ]
    assert payload["steps"][-1]["name"] == "delete_memory"


def test_engramd_smoke_test_cli_prints_json(monkeypatch, capsys):
    fake_client = FakeSmokeClient()

    monkeypatch.setattr(engramd, "EngramDaemonClient", lambda url: fake_client)

    exit_code = engramd.main(["--smoke-test", "--host", "127.0.0.1", "--port", "8765"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["status"] == "ok"
    assert payload["url"] == "http://127.0.0.1:8765"


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.mark.skipif(
    os.environ.get("ENGRAM_LIVE_DAEMON_SMOKE") != "1",
    reason="set ENGRAM_LIVE_DAEMON_SMOKE=1 to start a real disposable engramd subprocess",
)
def test_live_engramd_subprocess_smoke(tmp_path):
    port = _free_loopback_port()
    data_root = tmp_path / "daemon-data"
    env = os.environ.copy()
    env["ENGRAM_DATA_DIR"] = str(data_root)

    process = subprocess.Popen(
        [
            sys.executable,
            str(REPO_ROOT / "engramd.py"),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        client = EngramDaemonClient(f"http://127.0.0.1:{port}", timeout=2.0)
        deadline = time.time() + 90
        last_error = None
        while time.time() < deadline:
            if process.poll() is not None:
                stdout, stderr = process.communicate(timeout=5)
                pytest.fail(
                    f"engramd exited before health check passed\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}"
                )
            try:
                health = client.health()
            except Exception as exc:  # noqa: BLE001 - diagnostic for optional live smoke
                last_error = exc
                time.sleep(0.5)
                continue
            if health.get("status") == "ok" and health.get("error") is None:
                break
            last_error = health
            time.sleep(0.5)
        else:
            pytest.fail(f"engramd did not become healthy: {last_error}")

        payload = run_daemon_smoke(
            client,
            key=f"_engramd_live_smoke_{uuid.uuid4().hex}",
        )

        assert payload["status"] == "ok"
        assert payload["error"] is None
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
