import http.client
import json
import os
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from core.hub_gateway import (
    HUB_ALLOWED_DAEMON_ROUTES,
    HUB_ALLOWED_TOOL_NAMES,
    authorize_hub_gateway_route,
    make_hub_gateway_handler,
)
from core.mcp.tool_registry import DAEMON_ROUTES
from core.network_exposure import validate_hub_gateway_bind, validate_sync_listener_bind

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_hub_gateway_rejects_unknown_routes():
    result = authorize_hub_gateway_route("POST", "/v1/raw_sql", authenticated=True)

    assert result["allowed"] is False
    assert result["error"]["code"] == "hub_route_not_allowed"


def test_hub_gateway_allows_existing_memory_routes_when_authenticated():
    result = authorize_hub_gateway_route("POST", "/v1/search_memories", authenticated=True)

    assert result["allowed"] is True
    assert ("POST", "/v1/search_memories") in HUB_ALLOWED_DAEMON_ROUTES


def test_hub_gateway_rejects_allowed_routes_without_auth():
    result = authorize_hub_gateway_route("POST", "/v1/search_memories", authenticated=False)

    assert result["allowed"] is False
    assert result["error"]["code"] == "hub_authorization_required"


def test_hub_gateway_allowlist_uses_registered_daemon_routes():
    registered = {(route.method, route.path) for route in DAEMON_ROUTES.values()}

    assert HUB_ALLOWED_DAEMON_ROUTES <= registered


def test_hub_gateway_allowlist_is_explicit_and_reviewed():
    assert "search_memories" in HUB_ALLOWED_TOOL_NAMES
    assert "store_memory" in HUB_ALLOWED_TOOL_NAMES
    assert "export_sync_changeset" not in HUB_ALLOWED_TOOL_NAMES
    assert "apply_sync_changeset" not in HUB_ALLOWED_TOOL_NAMES
    assert "list_sync_inbox" in HUB_ALLOWED_TOOL_NAMES
    assert "prepare_sync_inbox_apply" in HUB_ALLOWED_TOOL_NAMES
    assert "apply_sync_inbox" in HUB_ALLOWED_TOOL_NAMES
    assert "resolve_sync_conflict" not in HUB_ALLOWED_TOOL_NAMES
    assert "push_sync_changeset" not in HUB_ALLOWED_TOOL_NAMES
    assert "configure_sync_peer_transport" not in HUB_ALLOWED_TOOL_NAMES
    assert "delete_memory" not in HUB_ALLOWED_TOOL_NAMES
    assert "apply_document_promotion_transaction" not in HUB_ALLOWED_TOOL_NAMES
    assert "run_document_ingestion" not in HUB_ALLOWED_TOOL_NAMES
    for name in HUB_ALLOWED_TOOL_NAMES:
        route = DAEMON_ROUTES[name]
        assert (route.method, route.path) in HUB_ALLOWED_DAEMON_ROUTES


def test_hub_gateway_handler_requires_auth_and_forwards_allowed_route():
    token = "x" * 40

    class FakeAPI:
        def __init__(self):
            self.calls = []

        def handle(self, method, path, payload):
            self.calls.append((method, path, payload))
            return {"status": 200, "body": {"ok": True, "path": path}}

    api = FakeAPI()
    handler = make_hub_gateway_handler(api, expected_token=token)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        unauthorized = _post_json(host, port, "/v1/search_memories", {"query": "x"}, token=None)
        authorized = _post_json(host, port, "/v1/search_memories", {"query": "x"}, token=token)
        rejected = _post_json(host, port, "/v1/raw_sql", {}, token=token)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert unauthorized[0] == 401
    assert unauthorized[1]["error"]["code"] == "hub_authorization_required"
    assert authorized == (200, {"ok": True, "path": "/v1/search_memories"})
    assert rejected[0] == 404
    assert rejected[1]["error"]["code"] == "hub_route_not_allowed"
    assert api.calls == [("POST", "/v1/search_memories", {"query": "x"})]


def test_hub_gateway_rejects_negative_content_length():
    token = "x" * 40

    class FakeAPI:
        def __init__(self):
            self.calls = []

        def handle(self, method, path, payload):
            self.calls.append((method, path, payload))
            return {"status": 200, "body": {"ok": True}}

    api = FakeAPI()
    handler = make_hub_gateway_handler(api, expected_token=token)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _post_raw(
            host,
            port,
            "/v1/search_memories",
            b'{"query":"x"}',
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Content-Length": "-1",
            },
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert status == 400
    assert body["error"]["code"] == "invalid_content_length"
    assert api.calls == []


def test_validate_hub_gateway_bind_requires_explicit_ack_for_non_loopback():
    env = {
        "ENGRAM_HUB_ACCESS_TOKEN": "x" * 40,
    }

    denied = validate_hub_gateway_bind("100.64.0.1", env=env)
    env["ENGRAM_HUB_LISTEN"] = "1"
    still_denied = validate_hub_gateway_bind("100.64.0.1", env=env)
    env["ENGRAM_HUB_PRIVATE_NETWORK_ACK"] = "1"
    ready = validate_hub_gateway_bind("100.64.0.1", env=env)

    assert denied["error"]["code"] == "hub_listen_not_acknowledged"
    assert still_denied["error"]["code"] == "hub_private_network_ack_required"
    assert ready["status"] == "ready"
    assert ready["safe_to_bind"] is True


def test_validate_hub_gateway_bind_requires_allowed_hosts_for_wildcard():
    env = {
        "ENGRAM_HUB_ACCESS_TOKEN": "x" * 40,
        "ENGRAM_HUB_LISTEN": "1",
        "ENGRAM_HUB_PRIVATE_NETWORK_ACK": "1",
    }

    denied = validate_hub_gateway_bind("0.0.0.0", env=env)
    env["ENGRAM_HUB_ALLOWED_HOSTS"] = "engram-hub.tailnet-name.ts.net"
    ready = validate_hub_gateway_bind("0.0.0.0", env=env)

    assert denied["error"]["code"] == "hub_allowed_hosts_required"
    assert ready["status"] == "ready"


def test_validate_sync_listener_bind_requires_private_network_ack_for_non_loopback():
    env = {}

    denied = validate_sync_listener_bind("100.64.0.1", env=env)
    env["ENGRAM_SYNC_LISTEN"] = "1"
    still_denied = validate_sync_listener_bind("100.64.0.1", env=env)
    env["ENGRAM_SYNC_PRIVATE_NETWORK_ACK"] = "1"
    ready = validate_sync_listener_bind("100.64.0.1", env=env)

    assert denied["error"]["code"] == "sync_listen_not_acknowledged"
    assert still_denied["error"]["code"] == "sync_private_network_ack_required"
    assert ready["status"] == "ready"
    assert ready["safe_to_bind"] is True


def test_validate_sync_listener_bind_requires_allowed_hosts_for_wildcard():
    env = {
        "ENGRAM_SYNC_LISTEN": "1",
        "ENGRAM_SYNC_PRIVATE_NETWORK_ACK": "1",
    }

    denied = validate_sync_listener_bind("0.0.0.0", env=env)
    env["ENGRAM_SYNC_ALLOWED_HOSTS"] = "engram-sync.tailnet-name.ts.net"
    ready = validate_sync_listener_bind("0.0.0.0", env=env)

    assert denied["error"]["code"] == "sync_allowed_hosts_required"
    assert ready["status"] == "ready"


def test_hub_listen_forces_raw_daemon_loopback_even_when_public_bind_allowed():
    env = {
        **os.environ,
        "ENGRAM_ALLOW_PUBLIC_BIND": "loopback-published",
        "ENGRAM_HUB_ACCESS_TOKEN": "x" * 40,
        "ENGRAM_HUB_LISTEN": "1",
        "ENGRAM_HUB_PRIVATE_NETWORK_ACK": "1",
    }

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "engramd.py"),
            "--hub-listen",
            "--host",
            "0.0.0.0",
            "--hub-host",
            "127.0.0.1",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
        check=False,
    )

    assert result.returncode == 2
    assert "raw daemon --host must remain loopback" in result.stderr


def _post_json(host, port, path, payload, *, token):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    connection = http.client.HTTPConnection(host, port, timeout=2)
    connection.request("POST", path, body=json.dumps(payload), headers=headers)
    response = connection.getresponse()
    body = json.loads(response.read().decode("utf-8"))
    connection.close()
    return response.status, body


def _post_raw(host, port, path, body, headers):
    connection = http.client.HTTPConnection(host, port, timeout=2)
    try:
        connection.putrequest("POST", path)
        for key, value in headers.items():
            connection.putheader(key, value)
        connection.endheaders()
        connection.send(body)
        response = connection.getresponse()
        parsed = json.loads(response.read().decode("utf-8"))
    finally:
        connection.close()
    return response.status, parsed
