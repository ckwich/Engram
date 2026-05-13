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
from core.engramd_api import EngramDaemonAPI
from core.engramd_client import EngramDaemonClient
from core.engramd_smoke import SMOKE_MARKER, run_daemon_smoke
from core.memory_os.runtime import MemoryOSRuntime
from core.vector_index import InMemoryVectorIndex


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

    def check_duplicate(self, payload):
        self.calls.append(("check_duplicate", payload))
        return {
            "key": payload["key"],
            "duplicate": False,
            "match": None,
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

    def repair_memory_metadata(self, payload):
        self.calls.append(("repair_memory_metadata", payload))
        return {
            "requested_count": len(payload["keys"]),
            "repaired_count": 0,
            "dry_run": payload["dry_run"],
            "repairs": [{"key": payload["keys"][0], "repaired": False}],
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


class FakeStatsManager:
    def get_stats(self):
        return {"total_memories": 0, "total_chunks": 0}


class APIBackedSmokeClient:
    def __init__(self, api: EngramDaemonAPI):
        self.api = api
        self.responses: list[tuple[str, dict]] = []

    def _call(self, method: str, path: str, payload: dict | None = None) -> dict:
        envelope = self.api.handle(method, path, payload)
        body = envelope["body"]
        self.responses.append((path, body))
        return body

    def health(self):
        return self._call("GET", "/health")

    def store_memory(self, payload):
        return self._call("POST", "/v1/store_memory", payload)

    def check_duplicate(self, payload):
        return self._call("POST", "/v1/check_duplicate", payload)

    def update_memory_metadata(self, payload):
        return self._call("POST", "/v1/update_memory_metadata", payload)

    def repair_memory_metadata(self, payload):
        return self._call("POST", "/v1/repair_memory_metadata", payload)

    def search_memories(self, payload):
        return self._call("POST", "/v1/search_memories", payload)

    def retrieve_chunk(self, payload):
        return self._call("POST", "/v1/retrieve_chunk", payload)

    def retrieve_memory(self, payload):
        return self._call("POST", "/v1/retrieve_memory", payload)

    def delete_memory(self, payload):
        return self._call("POST", "/v1/delete_memory", payload)


def _embed(text):
    text = str(text).lower()
    if SMOKE_MARKER in text or "engramd smoke" in text:
        return [1.0, 0.0]
    return [0.0, 1.0]


def test_run_daemon_smoke_exercises_full_memory_cycle():
    client = FakeSmokeClient()

    payload = run_daemon_smoke(client, key="_engramd_smoke_test")

    assert payload["status"] == "ok"
    assert payload["error"] is None
    assert [call[0] for call in client.calls] == [
        "health",
        "check_duplicate",
        "store_memory",
        "update_memory_metadata",
        "repair_memory_metadata",
        "search_memories",
        "retrieve_chunk",
        "retrieve_memory",
        "delete_memory",
    ]
    assert payload["steps"][-1]["name"] == "delete_memory"


def test_run_daemon_smoke_reports_memory_os_backend_when_daemon_uses_runtime(tmp_path):
    memory_os_root = tmp_path / "memory_os"
    memory_os_root.mkdir()
    runtime = MemoryOSRuntime(
        memory_os_root,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()
    api = EngramDaemonAPI(
        memory_manager=FakeStatsManager(),
        memory_os_runtime=runtime,
    )
    client = APIBackedSmokeClient(api)

    payload = run_daemon_smoke(client, key="_engramd_memory_os_smoke")

    store_step = next(step for step in payload["steps"] if step["name"] == "store_memory")
    search_step = next(step for step in payload["steps"] if step["name"] == "search_memories")
    inspector = runtime.inspector()

    assert payload["status"] == "ok"
    assert payload["error"] is None
    assert store_step["details"]["storage_backend"] == "memory_os"
    assert search_step["details"]["backend"] == "memory_os"
    assert inspector["summary"]["transaction_count"] >= 3


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
