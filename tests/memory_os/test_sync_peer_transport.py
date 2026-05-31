from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

from core.memory_os.runtime import MemoryOSRuntime
from core.memory_os.sync_identity import ensure_device_identity, export_local_sync_identity, register_sync_peer
from core.memory_os.sync_peer_transport import (
    build_signed_sync_request,
    configure_sync_peer_transport,
    inspect_sync_peer,
    push_sync_bundle,
    verify_sync_request_signature,
)


def _paired_runtimes(tmp_path):
    laptop = MemoryOSRuntime(tmp_path / "laptop" / "memory_os", embed_text=lambda text: [0.1, 0.2])
    desktop = MemoryOSRuntime(tmp_path / "desktop" / "memory_os", embed_text=lambda text: [0.1, 0.2])
    laptop.initialize(rebuild_retrieval=False)
    desktop.initialize(rebuild_retrieval=False)
    ensure_device_identity(laptop.ledger, device_name="laptop")
    ensure_device_identity(desktop.ledger, device_name="desktop")
    register_sync_peer(laptop.ledger, export_local_sync_identity(desktop.ledger), accept=True, approved_by="tester")
    register_sync_peer(desktop.ledger, export_local_sync_identity(laptop.ledger), accept=True, approved_by="tester")
    return laptop, desktop


def _start_test_server(handler_type):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_type)
    server.hits = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_signed_sync_request_verifies_once_and_rejects_nonce_replay(tmp_path):
    laptop, desktop = _paired_runtimes(tmp_path)
    desktop_id = export_local_sync_identity(desktop.ledger)["device_id"]
    request = build_signed_sync_request(
        laptop,
        target_device_id=desktop_id,
        method="POST",
        route="/v1/sync/inbox",
        body_payload={"bundle": "abc"},
    )

    verified = verify_sync_request_signature(
        desktop,
        peer_id=request["peer_id"],
        nonce=request["nonce"],
        timestamp=request["timestamp"],
        body_hash=request["body_hash"],
        signature=request["signature"],
        method="POST",
        route="/v1/sync/inbox",
        target_device_id=request["target_device_id"],
    )
    replay = verify_sync_request_signature(
        desktop,
        peer_id=request["peer_id"],
        nonce=request["nonce"],
        timestamp=request["timestamp"],
        body_hash=request["body_hash"],
        signature=request["signature"],
        method="POST",
        route="/v1/sync/inbox",
        target_device_id=request["target_device_id"],
    )

    assert verified["status"] == "ok"
    assert verified["write_performed"] is True
    assert replay["status"] == "policy_denied"
    assert replay["error"]["code"] == "sync_nonce_replay"


def test_configure_and_inspect_sync_peer_transport(tmp_path):
    laptop, desktop = _paired_runtimes(tmp_path)
    desktop_id = export_local_sync_identity(desktop.ledger)["device_id"]

    configured = configure_sync_peer_transport(
        laptop,
        peer_id=desktop_id,
        url="http://100.64.0.10:8766",
        mode="manual",
        accept=True,
        approved_by="tester",
    )
    inspected = inspect_sync_peer(laptop, peer_id=desktop_id)

    assert configured["status"] == "configured"
    assert configured["write_performed"] is True
    assert inspected["peer"]["transport"]["url"] == "http://100.64.0.10:8766"
    assert inspected["peer"]["transport"]["mode"] == "manual"
    assert inspected["peer"]["transport"]["url_trust"]["classification"] == "private_network"


def test_configure_sync_peer_transport_rejects_public_url_without_ack(tmp_path, monkeypatch):
    laptop, desktop = _paired_runtimes(tmp_path)
    desktop_id = export_local_sync_identity(desktop.ledger)["device_id"]
    monkeypatch.delenv("ENGRAM_SYNC_PRIVATE_NETWORK_ACK", raising=False)
    monkeypatch.delenv("ENGRAM_ALLOW_PUBLIC_BIND", raising=False)

    denied = configure_sync_peer_transport(
        laptop,
        peer_id=desktop_id,
        url="https://example.com:8766",
        mode="manual",
        accept=True,
        approved_by="tester",
    )
    monkeypatch.setenv("ENGRAM_SYNC_PRIVATE_NETWORK_ACK", "1")
    configured = configure_sync_peer_transport(
        laptop,
        peer_id=desktop_id,
        url="https://example.com:8766",
        mode="manual",
        accept=True,
        approved_by="tester",
    )

    assert denied["status"] == "policy_denied"
    assert denied["error"]["code"] == "sync_peer_url_private_ack_required"
    assert configured["status"] == "configured"
    assert configured["peer"]["transport"]["url_trust"]["classification"] == "public_or_proxy_acknowledged"


def test_configure_sync_peer_transport_rejects_url_credentials(tmp_path):
    laptop, desktop = _paired_runtimes(tmp_path)
    desktop_id = export_local_sync_identity(desktop.ledger)["device_id"]

    denied = configure_sync_peer_transport(
        laptop,
        peer_id=desktop_id,
        url="http://token@100.64.0.10:8766",
        mode="manual",
        accept=True,
        approved_by="tester",
    )

    assert denied["status"] == "policy_denied"
    assert denied["error"]["code"] == "invalid_sync_peer_url"


def test_push_sync_bundle_accepts_direct_peer_success(tmp_path):
    laptop, desktop = _paired_runtimes(tmp_path)
    desktop_id = export_local_sync_identity(desktop.ledger)["device_id"]

    class PeerHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length else b""
            self.server.hits.append(("POST", self.path, body))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        def log_message(self, format, *args):
            return

    peer_server = _start_test_server(PeerHandler)
    try:
        configured = configure_sync_peer_transport(
            laptop,
            peer_id=desktop_id,
            url=f"http://127.0.0.1:{peer_server.server_port}",
            mode="manual",
            accept=True,
            approved_by="tester",
        )

        result = push_sync_bundle(
            laptop,
            configured["peer"],
            b"encrypted-bundle",
            approved_by="tester",
            timeout=2,
        )

        assert result["status"] == "pushed"
        assert result["http_status"] == 200
        assert result["peer_response"] == {"status": "ok"}
        assert len(peer_server.hits) == 1
        assert peer_server.hits[0][0:2] == ("POST", "/v1/sync/inbox")
    finally:
        peer_server.shutdown()
        peer_server.server_close()


def test_push_sync_bundle_does_not_follow_peer_redirects(tmp_path):
    laptop, desktop = _paired_runtimes(tmp_path)
    desktop_id = export_local_sync_identity(desktop.ledger)["device_id"]

    class RedirectTargetHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.server.hits.append(("GET", self.path))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        def do_POST(self):
            self.server.hits.append(("POST", self.path))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        def log_message(self, format, *args):
            return

    target_server = _start_test_server(RedirectTargetHandler)

    class RedirectingPeerHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            if length:
                self.rfile.read(length)
            self.send_response(302)
            self.send_header(
                "Location",
                f"http://127.0.0.1:{target_server.server_port}/v1/sync/inbox",
            )
            self.end_headers()

        def log_message(self, format, *args):
            return

    peer_server = _start_test_server(RedirectingPeerHandler)
    try:
        configured = configure_sync_peer_transport(
            laptop,
            peer_id=desktop_id,
            url=f"http://127.0.0.1:{peer_server.server_port}",
            mode="manual",
            accept=True,
            approved_by="tester",
        )

        result = push_sync_bundle(
            laptop,
            configured["peer"],
            b"encrypted-bundle",
            approved_by="tester",
            timeout=2,
        )

        assert result["status"] == "peer_rejected"
        assert result["http_status"] == 302
        assert target_server.hits == []
    finally:
        peer_server.shutdown()
        peer_server.server_close()
        target_server.shutdown()
        target_server.server_close()
