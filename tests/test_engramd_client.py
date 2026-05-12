from __future__ import annotations

import json
import subprocess
import sys

from core.engramd_client import EngramDaemonClient


class FakeTransport:
    def __init__(self):
        self.calls = []

    def request_json(self, method, url, payload=None, timeout=10.0):
        self.calls.append((method, url, payload, timeout))
        return {"ok": True, "url": url, "payload": payload}


def test_client_posts_search_to_v1_endpoint():
    transport = FakeTransport()
    client = EngramDaemonClient("http://127.0.0.1:8765/", transport=transport)

    result = client.search_memories({"query": "agent memory"})

    assert result["ok"] is True
    assert transport.calls == [
        (
            "POST",
            "http://127.0.0.1:8765/v1/search_memories",
            {"query": "agent memory"},
            10.0,
        )
    ]


def test_client_gets_health_endpoint():
    transport = FakeTransport()
    client = EngramDaemonClient("http://127.0.0.1:8765", timeout=3.5, transport=transport)

    client.health()

    assert transport.calls == [
        ("GET", "http://127.0.0.1:8765/health", None, 3.5)
    ]


def test_client_methods_map_to_daemon_routes():
    transport = FakeTransport()
    client = EngramDaemonClient("http://127.0.0.1:8765", transport=transport)

    client.retrieve_chunk({"key": "k", "chunk_id": 0})
    client.retrieve_chunks({"requests": [{"key": "k", "chunk_id": 0}]})
    client.retrieve_memory({"key": "k"})
    client.store_memory({"key": "k", "content": "body"})
    client.check_duplicate({"key": "k", "content": "body"})
    client.update_memory_metadata({"key": "k", "title": "Updated"})
    client.repair_memory_metadata({"keys": ["k"], "dry_run": False})
    client.store_prepared_memory({"draft_id": "draft-a", "selected_items": [0], "force": True})
    client.delete_memory({"key": "k"})

    assert [call[1].rsplit("/", 1)[-1] for call in transport.calls] == [
        "retrieve_chunk",
        "retrieve_chunks",
        "retrieve_memory",
        "store_memory",
        "check_duplicate",
        "update_memory_metadata",
        "repair_memory_metadata",
        "store_prepared_memory",
        "delete_memory",
    ]


def test_engramd_help_exposes_daemon_options():
    result = subprocess.run(
        [sys.executable, "engramd.py", "--help"],
        cwd=".",
        capture_output=True,
        text=True,
        check=True,
    )

    assert "--host" in result.stdout
    assert "--port" in result.stdout
    assert "--health" in result.stdout
    assert "--smoke-test" in result.stdout
