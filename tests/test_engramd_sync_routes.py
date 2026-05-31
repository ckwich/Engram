from __future__ import annotations

import base64
import http.client
import json
import os
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from core.engramd_api import EngramDaemonAPI
from core.memory_os.runtime import MemoryOSRuntime
from core.memory_os.sync_identity import ensure_device_identity, export_local_sync_identity, register_sync_peer
from core.memory_os.sync_peer_transport import build_signed_sync_request
from core.mcp.tool_registry import DAEMON_ROUTES
from engramd import EngramDaemonRequestHandler, make_sync_gateway_handler

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_sync_peer_routes_are_sidecar_only_not_daemon_tool_routes():
    route_paths = {route.path for route in DAEMON_ROUTES.values()}

    assert "/v1/sync/hello" not in route_paths
    assert "/v1/sync/inbox" not in route_paths
    assert "/v1/sync/state" not in route_paths
    assert "/v1/sync/pull_bundle" not in route_paths


def test_raw_daemon_api_rejects_sync_peer_routes(tmp_path):
    runtime = MemoryOSRuntime(tmp_path / "memory_os", embed_text=lambda text: [0.1, 0.2])
    runtime.initialize(rebuild_retrieval=False)
    api = EngramDaemonAPI(memory_os_runtime=runtime)

    response = api.handle("POST", "/v1/sync/hello", {"peer_id": "device:laptop"})

    assert response["status"] == 404
    assert response["body"]["error"]["code"] == "sync_route_not_available"


def test_raw_daemon_http_rejects_sync_peer_routes(tmp_path):
    runtime = MemoryOSRuntime(tmp_path / "memory_os", embed_text=lambda text: [0.1, 0.2])
    runtime.initialize(rebuild_retrieval=False)
    previous_api = EngramDaemonRequestHandler.api
    EngramDaemonRequestHandler.api = EngramDaemonAPI(memory_os_runtime=runtime)
    server = ThreadingHTTPServer(("127.0.0.1", 0), EngramDaemonRequestHandler)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post_json(host, port, "/v1/sync/hello", {"peer_id": "device:laptop"})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        EngramDaemonRequestHandler.api = previous_api

    assert status == 404
    assert body["error"]["code"] == "sync_route_not_available"


def test_raw_daemon_rejects_browser_style_text_plain_post(tmp_path):
    runtime = MemoryOSRuntime(tmp_path / "memory_os", embed_text=lambda text: [0.1, 0.2])
    runtime.initialize(rebuild_retrieval=False)
    previous_api = EngramDaemonRequestHandler.api
    EngramDaemonRequestHandler.api = EngramDaemonAPI(memory_os_runtime=runtime)
    server = ThreadingHTTPServer(("127.0.0.1", 0), EngramDaemonRequestHandler)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post_raw(
            host,
            port,
            "/v1/store_memory",
            b'{"key":"csrf","content":"poison"}',
            {
                "Content-Type": "text/plain",
                "Origin": "https://attacker.example",
                "Sec-Fetch-Site": "cross-site",
            },
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        EngramDaemonRequestHandler.api = previous_api

    assert status == 415
    assert body["error"]["code"] == "unsupported_content_type"


def test_raw_daemon_rejects_negative_content_length(tmp_path):
    runtime = MemoryOSRuntime(tmp_path / "memory_os", embed_text=lambda text: [0.1, 0.2])
    runtime.initialize(rebuild_retrieval=False)
    previous_api = EngramDaemonRequestHandler.api
    EngramDaemonRequestHandler.api = EngramDaemonAPI(memory_os_runtime=runtime)
    server = ThreadingHTTPServer(("127.0.0.1", 0), EngramDaemonRequestHandler)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post_raw(
            host,
            port,
            "/v1/store_memory",
            b'{"key":"too-big","content":"body"}',
            {"Content-Type": "application/json", "Content-Length": "-1"},
            skip_content_length=True,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        EngramDaemonRequestHandler.api = previous_api

    assert status == 400
    assert body["error"]["code"] == "invalid_content_length"


def test_sync_listener_handler_forwards_only_sync_peer_routes(tmp_path):
    runtime = MemoryOSRuntime(tmp_path / "memory_os", embed_text=lambda text: [0.1, 0.2])
    runtime.initialize(rebuild_retrieval=False)
    handler = make_sync_gateway_handler(EngramDaemonAPI(memory_os_runtime=runtime))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        sync_status, sync_body = _post_json(host, port, "/v1/sync/hello", {"peer_id": "device:laptop"})
        raw_status, raw_body = _post_json(host, port, "/v1/search_memories", {"query": "x"})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert sync_status == 401
    assert sync_body["error"]["code"] == "sync_peer_signature_required"
    assert raw_status == 404
    assert raw_body["error"]["code"] == "sync_route_not_allowed"


def test_sync_listener_rejects_negative_content_length(tmp_path):
    runtime = MemoryOSRuntime(tmp_path / "memory_os", embed_text=lambda text: [0.1, 0.2])
    runtime.initialize(rebuild_retrieval=False)
    handler = make_sync_gateway_handler(EngramDaemonAPI(memory_os_runtime=runtime))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post_raw(
            host,
            port,
            "/v1/sync/hello",
            b'{"peer_id":"device:laptop"}',
            {"Content-Type": "application/json", "Content-Length": "-1"},
            skip_content_length=True,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert status == 400
    assert body["error"]["code"] == "invalid_content_length"


def test_sync_hello_requires_signed_peer_challenge(tmp_path):
    runtime = MemoryOSRuntime(tmp_path / "memory_os", embed_text=lambda text: [0.1, 0.2])
    runtime.initialize(rebuild_retrieval=False)
    api = EngramDaemonAPI(memory_os_runtime=runtime)

    response = api.handle_sync_peer("POST", "/v1/sync/hello", {"peer_id": "device:laptop"})

    assert response["status"] == 401
    assert response["body"]["error"]["code"] == "sync_peer_signature_required"


def test_sync_inbox_rejects_unregistered_peer(tmp_path):
    runtime = MemoryOSRuntime(tmp_path / "memory_os", embed_text=lambda text: [0.1, 0.2])
    runtime.initialize(rebuild_retrieval=False)
    api = EngramDaemonAPI(memory_os_runtime=runtime)

    response = api.handle_sync_peer(
        "POST",
        "/v1/sync/inbox",
        {
            "peer_id": "device:unknown",
            "target_device_id": "device:local",
            "bundle": "eyJjaXBoZXJ0ZXh0IjoiYWJjIn0=",
            "signature": "ed25519:test",
            "nonce": "test-nonce",
            "timestamp": "2026-05-26T00:00:00+00:00",
            "body_hash": "sha256:test",
        },
    )

    assert response["status"] == 403
    assert response["body"]["error"]["code"] == "sync_peer_not_registered"


def test_sync_peer_routes_use_exact_allowlist(tmp_path):
    runtime = MemoryOSRuntime(tmp_path / "memory_os", embed_text=lambda text: [0.1, 0.2])
    runtime.initialize(rebuild_retrieval=False)
    api = EngramDaemonAPI(memory_os_runtime=runtime)

    response = api.handle_sync_peer("POST", "/v1/sync/anything/inbox", {"peer_id": "device:laptop"})

    assert response["status"] == 404
    assert response["body"]["error"]["code"] == "sync_route_not_found"


def test_sync_inbox_stores_signed_bundle_without_apply(tmp_path):
    laptop = MemoryOSRuntime(tmp_path / "laptop" / "memory_os", embed_text=lambda text: [0.1, 0.2])
    desktop = MemoryOSRuntime(tmp_path / "desktop" / "memory_os", embed_text=lambda text: [0.1, 0.2])
    laptop.initialize(rebuild_retrieval=False)
    desktop.initialize(rebuild_retrieval=False)
    ensure_device_identity(laptop.ledger, device_name="laptop")
    ensure_device_identity(desktop.ledger, device_name="desktop")
    register_sync_peer(laptop.ledger, export_local_sync_identity(desktop.ledger), accept=True, approved_by="tester")
    register_sync_peer(desktop.ledger, export_local_sync_identity(laptop.ledger), accept=True, approved_by="tester")
    desktop_identity = export_local_sync_identity(desktop.ledger)
    bundle_b64 = base64.urlsafe_b64encode(b'{"ciphertext":"abc"}').decode("ascii")
    signed = build_signed_sync_request(
        laptop,
        target_device_id=desktop_identity["device_id"],
        method="POST",
        route="/v1/sync/inbox",
        body_payload={"bundle": bundle_b64},
    )
    api = EngramDaemonAPI(memory_os_runtime=desktop)

    response = api.handle_sync_peer("POST", "/v1/sync/inbox", {**signed, "bundle": bundle_b64})

    assert response["status"] == 200
    assert response["body"]["status"] == "received"
    assert response["body"]["apply_performed"] is False
    assert response["body"]["artifact_id"].startswith("sha256:")


def test_body_hash_mismatch_does_not_consume_nonce(tmp_path):
    laptop = MemoryOSRuntime(tmp_path / "laptop" / "memory_os", embed_text=lambda text: [0.1, 0.2])
    desktop = MemoryOSRuntime(tmp_path / "desktop" / "memory_os", embed_text=lambda text: [0.1, 0.2])
    laptop.initialize(rebuild_retrieval=False)
    desktop.initialize(rebuild_retrieval=False)
    ensure_device_identity(laptop.ledger, device_name="laptop")
    ensure_device_identity(desktop.ledger, device_name="desktop")
    register_sync_peer(laptop.ledger, export_local_sync_identity(desktop.ledger), accept=True, approved_by="tester")
    register_sync_peer(desktop.ledger, export_local_sync_identity(laptop.ledger), accept=True, approved_by="tester")
    desktop_identity = export_local_sync_identity(desktop.ledger)
    bundle_b64 = base64.urlsafe_b64encode(b'{"ciphertext":"abc"}').decode("ascii")
    tampered_b64 = base64.urlsafe_b64encode(b'{"ciphertext":"tampered"}').decode("ascii")
    signed = build_signed_sync_request(
        laptop,
        target_device_id=desktop_identity["device_id"],
        method="POST",
        route="/v1/sync/inbox",
        body_payload={"bundle": bundle_b64},
    )
    api = EngramDaemonAPI(memory_os_runtime=desktop)

    tampered = api.handle_sync_peer("POST", "/v1/sync/inbox", {**signed, "bundle": tampered_b64})
    original = api.handle_sync_peer("POST", "/v1/sync/inbox", {**signed, "bundle": bundle_b64})

    assert tampered["status"] == 401
    assert tampered["body"]["error"]["code"] == "sync_body_hash_mismatch"
    assert original["status"] == 200
    assert original["body"]["status"] == "received"


def test_sync_listener_startup_fails_closed_without_peer_or_bootstrap_ack(tmp_path):
    env = {
        **os.environ,
        "ENGRAM_DATA_DIR": str(tmp_path / "data"),
    }

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "engramd.py"),
            "--sync-listen",
            "--sync-host",
            "0.0.0.0",
            "--sync-port",
            "8766",
            "--doctor",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
        check=False,
    )

    assert result.returncode == 2
    assert "sync listener" in result.stderr.lower()


def _post_json(host: str, port: int, path: str, payload: dict) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8")
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.request("POST", path, body=body, headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        raw = response.read().decode("utf-8")
    finally:
        conn.close()
    return response.status, json.loads(raw)


def _post_raw(
    host: str,
    port: int,
    path: str,
    body: bytes,
    headers: dict[str, str],
    *,
    skip_content_length: bool = False,
) -> tuple[int, dict]:
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.putrequest("POST", path)
        for key, value in headers.items():
            conn.putheader(key, value)
        if not skip_content_length and "Content-Length" not in headers:
            conn.putheader("Content-Length", str(len(body)))
        conn.endheaders()
        conn.send(body)
        response = conn.getresponse()
        raw = response.read().decode("utf-8")
    finally:
        conn.close()
    return response.status, json.loads(raw)
