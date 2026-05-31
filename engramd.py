#!/usr/bin/env python3
"""Run the local Engram daemon."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from core.memory_os.runtime_paths import (
    memory_os_root_for_data_root,
    resolve_data_root,
    validate_memory_os_preflight,
)

os.environ.setdefault("ENGRAM_DATA_DIR", str(resolve_data_root()))

from core.embedder import embedder
from core.engramd_api import EngramDaemonAPI
from core.engramd_client import EngramDaemonClient
from core.engramd_smoke import run_daemon_smoke
from core.hub_auth import load_hub_access_token
from core.hub_gateway import make_hub_gateway_handler
from core.memory_limits import (
    DAEMON_MAX_CONTENT_LENGTH_ENV,
    DEFAULT_DAEMON_MAX_CONTENT_LENGTH,
)
from core.memory_manager import memory_manager
from core.memory_os.runtime import MemoryOSRuntime
from core.memory_os.runtime_snapshots import (
    RuntimeSnapshotError,
    create_verified_runtime_snapshot,
    verify_runtime_snapshot,
)
from core.network_exposure import (
    HUB_ALLOWED_HOSTS_ENV,
    SYNC_ALLOWED_HOSTS_ENV,
    PublicBindDenied,
    is_loopback_host,
    validate_hub_gateway_bind,
    validate_raw_service_bind,
    validate_sync_listener_bind,
)
from core.process_hygiene import (
    build_process_hygiene_report,
    discover_processes,
    stop_server_pids,
)

DEFAULT_DAEMON_HOST = os.environ.get("ENGRAM_DAEMON_HOST", "127.0.0.1")
DEFAULT_DAEMON_PORT = int(os.environ.get("ENGRAM_DAEMON_PORT", "8765"))
DEFAULT_HUB_HOST = os.environ.get("ENGRAM_HUB_HOST", "127.0.0.1")
DEFAULT_HUB_PORT = int(os.environ.get("ENGRAM_HUB_PORT", "8767"))
DEFAULT_SYNC_HOST = os.environ.get("ENGRAM_SYNC_HOST", "127.0.0.1")
DEFAULT_SYNC_PORT = int(os.environ.get("ENGRAM_SYNC_PORT", "8766"))
DEFAULT_SMOKE_TIMEOUT_SECONDS = float(os.environ.get("ENGRAM_DAEMON_SMOKE_TIMEOUT", "90"))
DAEMON_ALLOWED_HOSTS_ENV = "ENGRAM_DAEMON_ALLOWED_HOSTS"


def daemon_max_content_length() -> int:
    raw_value = os.environ.get(DAEMON_MAX_CONTENT_LENGTH_ENV, "").strip()
    if not raw_value:
        return DEFAULT_DAEMON_MAX_CONTENT_LENGTH
    try:
        return max(int(raw_value), 1024)
    except ValueError:
        return DEFAULT_DAEMON_MAX_CONTENT_LENGTH


class EngramDaemonRequestHandler(BaseHTTPRequestHandler):
    """HTTP handler that delegates requests to EngramDaemonAPI."""

    server_version = "Engramd/1.0"
    api = EngramDaemonAPI(memory_manager=memory_manager)

    def do_GET(self) -> None:
        self._handle_json_request("GET")

    def do_POST(self) -> None:
        self._handle_json_request("POST")

    def _handle_json_request(self, method: str) -> None:
        payload: dict[str, Any] | None = None
        if method == "POST":
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except ValueError:
                self._send_json(
                    400,
                    {
                        "error": {
                            "code": "invalid_content_length",
                            "message": "Content-Length must be an integer.",
                        }
                    },
                )
                self.close_connection = True
                return
            trust_error = _raw_daemon_post_trust_error(self.headers)
            if trust_error is not None:
                self._send_json(trust_error[0], {"error": trust_error[1]})
                self.close_connection = True
                return
            max_length = daemon_max_content_length()
            if length < 0:
                self._send_json(
                    400,
                    {
                        "error": {
                            "code": "invalid_content_length",
                            "message": "Content-Length must be a non-negative integer.",
                        }
                    },
                )
                self.close_connection = True
                return
            if length > max_length:
                self._send_json(
                    413,
                    {
                        "error": {
                            "code": "request_body_too_large",
                            "message": (
                                f"Request body is {length:,} bytes - exceeds the "
                                f"{max_length:,} byte daemon request limit."
                            ),
                        }
                    },
                )
                self.close_connection = True
                return
            raw = self.rfile.read(length) if length else b"{}"
            try:
                decoded = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                self._send_json(
                    400,
                    {
                        "error": {
                            "code": "invalid_json",
                            "message": "Request body must be valid JSON.",
                        }
                    },
                )
                return
            if decoded is not None and not isinstance(decoded, dict):
                self._send_json(
                    400,
                    {
                        "error": {
                            "code": "invalid_json",
                            "message": "Request body must be a JSON object.",
                        }
                    },
                )
                return
            payload = decoded

        response = self.api.handle(method, self.path, payload)
        self._send_json(response["status"], response["body"])

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[engramd] {self.address_string()} - {format % args}", file=sys.stderr)


def make_sync_gateway_handler(
    api: EngramDaemonAPI,
    *,
    allowed_hosts: set[str] | None = None,
    max_content_length: int = DEFAULT_DAEMON_MAX_CONTENT_LENGTH,
) -> type[BaseHTTPRequestHandler]:
    """Build a sync-only sidecar handler that forwards only signed peer routes."""

    class EngramSyncGatewayRequestHandler(BaseHTTPRequestHandler):
        server_version = "EngramSync/1.0"

        def do_GET(self) -> None:
            self._send_json(
                405,
                {
                    "error": {
                        "code": "method_not_allowed",
                        "message": "Sync listener accepts signed POST requests only.",
                    }
                },
            )

        def do_POST(self) -> None:
            if not self.path.startswith("/v1/sync/"):
                self._send_json(
                    404,
                    {
                        "error": {
                            "code": "sync_route_not_allowed",
                            "message": "Sync listener serves only /v1/sync/* routes.",
                        }
                    },
                )
                return
            if not _sync_host_allowed(self.headers.get("Host"), allowed_hosts):
                self._send_json(
                    403,
                    {
                        "error": {
                            "code": "sync_host_not_allowed",
                            "message": "Host header is not trusted for this sync listener.",
                        }
                    },
                )
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except ValueError:
                self._send_json(
                    400,
                    {
                        "error": {
                            "code": "invalid_content_length",
                            "message": "Content-Length must be an integer.",
                        }
                    },
                )
                return
            if length < 0:
                self._send_json(
                    400,
                    {
                        "error": {
                            "code": "invalid_content_length",
                            "message": "Content-Length must be a non-negative integer.",
                        }
                    },
                )
                self.close_connection = True
                return
            if length > max_content_length:
                self._send_json(
                    413,
                    {
                        "error": {
                            "code": "request_body_too_large",
                            "message": "Sync request body exceeds the daemon request limit.",
                        }
                    },
                )
                return
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                self._send_json(
                    400,
                    {
                        "error": {
                            "code": "invalid_json",
                            "message": "Request body must be valid JSON.",
                        }
                    },
                )
                return
            if not isinstance(payload, dict):
                self._send_json(
                    400,
                    {
                        "error": {
                            "code": "invalid_json",
                            "message": "Request body must be a JSON object.",
                        }
                    },
                )
                return
            response = api.handle_sync_peer("POST", self.path, payload)
            self._send_json(response["status"], response["body"])

        def _send_json(self, status: int, body: dict[str, Any]) -> None:
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args: Any) -> None:
            print(f"[engram-sync] {self.address_string()} - {format % args}", file=sys.stderr)

    return EngramSyncGatewayRequestHandler


def _raw_daemon_post_trust_error(headers: Any) -> tuple[int, dict[str, str]] | None:
    content_type = str(headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return (
            415,
            {
                "code": "unsupported_content_type",
                "message": "POST requests to the raw daemon must use application/json.",
            },
        )
    sec_fetch_site = str(headers.get("Sec-Fetch-Site") or "").strip().lower()
    if sec_fetch_site == "cross-site":
        return (
            403,
            {
                "code": "browser_cross_site_request_denied",
                "message": "Cross-site browser requests are not accepted by the raw daemon.",
            },
        )
    origin = str(headers.get("Origin") or "").strip()
    if origin and not _origin_matches_raw_daemon_host(origin, str(headers.get("Host") or "")):
        return (
            403,
            {
                "code": "browser_origin_not_allowed",
                "message": "Origin is not trusted for this raw daemon host.",
            },
        )
    if not _raw_daemon_host_allowed(str(headers.get("Host") or "")):
        return (
            403,
            {
                "code": "daemon_host_not_allowed",
                "message": "Host header is not trusted for this raw daemon.",
            },
        )
    return None


def _origin_matches_raw_daemon_host(origin: str, host_header: str) -> bool:
    from urllib.parse import urlparse

    parsed = urlparse(origin)
    origin_host = str(parsed.hostname or "").strip().lower()
    if not origin_host:
        return False
    request_host = str(host_header or "").split(":", 1)[0].strip().lower()
    return origin_host == request_host and _raw_daemon_host_allowed(host_header)


def _raw_daemon_host_allowed(host_header: str) -> bool:
    host = str(host_header or "").split(":", 1)[0].strip().lower()
    if not host:
        return True
    if is_loopback_host(host):
        return True
    allowed = {
        item.strip().lower()
        for item in os.environ.get(DAEMON_ALLOWED_HOSTS_ENV, "").split(",")
        if item.strip()
    }
    return host in allowed


def _memory_os_root() -> Path:
    return memory_os_root_for_data_root(resolve_data_root())


def _allow_unsafe_runtime_paths() -> bool:
    configured = os.environ.get("ENGRAM_ALLOW_UNSAFE_DATA_DIR", "").strip().lower()
    return configured in {"1", "true", "yes", "on"}


def _memory_os_preflight_report() -> dict[str, Any]:
    return validate_memory_os_preflight(
        _memory_os_root(),
        repo_root=Path(__file__).resolve().parent,
        allow_unsafe_paths=_allow_unsafe_runtime_paths(),
    )


def _ensure_memory_os_preflight_safe() -> dict[str, Any]:
    report = _memory_os_preflight_report()
    if report.get("safe_to_start") is not True:
        print("[engramd] Memory OS runtime preflight blocked startup.", file=sys.stderr)
        print(json.dumps(report, indent=2, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
    return report


def run_daemon(
    host: str,
    port: int,
    *,
    hub_listen: bool = False,
    hub_host: str = DEFAULT_HUB_HOST,
    hub_port: int = DEFAULT_HUB_PORT,
    sync_listen: bool = False,
    sync_host: str = DEFAULT_SYNC_HOST,
    sync_port: int = DEFAULT_SYNC_PORT,
) -> None:
    """Start the local daemon and own live storage/index state."""
    preflight = _ensure_memory_os_preflight_safe()
    print(
        f"[engramd] Memory OS preflight ok: {preflight['resolved_memory_os_root']}",
        file=sys.stderr,
    )
    print("[engramd] Pre-loading embedding model...", file=sys.stderr)
    embedder._load()
    print("[engramd] Initializing memory store...", file=sys.stderr)
    memory_manager._ensure_initialized()
    print("[engramd] Initializing Memory OS runtime...", file=sys.stderr)
    memory_os_runtime = MemoryOSRuntime(_memory_os_root())
    memory_os_runtime.preflight_report = preflight
    memory_os_runtime.initialize(rebuild_retrieval=False)
    _refresh_retrieval_manifest_if_possible(memory_os_runtime)
    EngramDaemonRequestHandler.api = EngramDaemonAPI(
        memory_manager=memory_manager,
        memory_os_runtime=memory_os_runtime,
    )
    server = ThreadingHTTPServer((host, port), EngramDaemonRequestHandler)
    hub_server: ThreadingHTTPServer | None = None
    sync_server: ThreadingHTTPServer | None = None
    if hub_listen:
        hub_server = _start_hub_gateway(
            hub_host,
            hub_port,
            api=EngramDaemonRequestHandler.api,
        )
    if sync_listen:
        sync_server = _start_sync_gateway(
            sync_host,
            sync_port,
            api=EngramDaemonRequestHandler.api,
        )
    if memory_os_runtime.retrieval_ready:
        print("[engramd] Using existing Memory OS retrieval index.", file=sys.stderr)
    else:
        retrieval_thread = threading.Thread(
            target=_rebuild_memory_os_retrieval,
            args=(memory_os_runtime,),
            name="engramd-memory-os-retrieval-rebuild",
            daemon=True,
        )
        retrieval_thread.start()
    print(f"[engramd] Listening on http://{host}:{port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[engramd] Shutdown requested.", file=sys.stderr)
    finally:
        if hub_server is not None:
            hub_server.shutdown()
            hub_server.server_close()
        if sync_server is not None:
            sync_server.shutdown()
            sync_server.server_close()
        server.server_close()


def _start_hub_gateway(host: str, port: int, *, api: EngramDaemonAPI) -> ThreadingHTTPServer:
    """Start the authenticated Personal Hub gateway listener."""
    validation = validate_hub_gateway_bind(host)
    if validation.get("safe_to_bind") is not True:
        raise PublicBindDenied(
            f"Personal Hub gateway refuses to bind {host!r}: "
            f"{(validation.get('error') or {}).get('code')}"
        )
    token_result = load_hub_access_token()
    token = str(token_result.get("token") or "")
    allowed_hosts = _hub_allowed_hosts()
    handler = make_hub_gateway_handler(
        api,
        expected_token=token,
        allowed_hosts=allowed_hosts,
        max_content_length=daemon_max_content_length(),
    )
    server = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(
        target=server.serve_forever,
        name="engram-personal-hub-gateway",
        daemon=True,
    )
    thread.start()
    print(f"[engramd] Personal Hub gateway listening on http://{host}:{port}", file=sys.stderr)
    return server


def _start_sync_gateway(host: str, port: int, *, api: EngramDaemonAPI) -> ThreadingHTTPServer:
    """Start the signed sync-only LAN/Tailscale listener."""
    _validate_sync_listener_startup(host)
    allowed_hosts = _sync_allowed_hosts()
    handler = make_sync_gateway_handler(
        api,
        allowed_hosts=allowed_hosts,
        max_content_length=daemon_max_content_length(),
    )
    server = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(
        target=server.serve_forever,
        name="engram-sync-listener",
        daemon=True,
    )
    thread.start()
    print(f"[engramd] Sync listener serving /v1/sync/* on http://{host}:{port}", file=sys.stderr)
    return server


def _validate_sync_listener_startup(host: str) -> None:
    validation = validate_sync_listener_bind(host)
    if validation.get("safe_to_bind") is not True:
        raise PublicBindDenied(
            f"sync listener refuses to bind {host!r}: "
            f"{(validation.get('error') or {}).get('code')}"
        )
    if _registered_sync_peer_count() <= 0 and not _sync_bootstrap_pairing_enabled():
        raise PublicBindDenied(
            "sync listener refuses to start without a registered peer or "
            "ENGRAM_SYNC_BOOTSTRAP_PAIRING=1. Pair devices first with "
            "register_sync_peer, or explicitly enable bootstrap pairing for the first exchange."
        )


def _hub_allowed_hosts() -> set[str] | None:
    raw = os.environ.get(HUB_ALLOWED_HOSTS_ENV, "").strip()
    if not raw:
        return None
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _sync_allowed_hosts() -> set[str] | None:
    raw = os.environ.get(SYNC_ALLOWED_HOSTS_ENV, "").strip()
    if not raw:
        return None
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _sync_host_allowed(host_header: str | None, allowed_hosts: set[str] | None) -> bool:
    if not allowed_hosts:
        return True
    host = str(host_header or "").split(":", 1)[0].strip().lower()
    return host in allowed_hosts


def _sync_bootstrap_pairing_enabled() -> bool:
    return os.environ.get("ENGRAM_SYNC_BOOTSTRAP_PAIRING", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _registered_sync_peer_count() -> int:
    ledger_path = _memory_os_root() / "ledger.sqlite3"
    if not ledger_path.exists():
        return 0
    try:
        with sqlite3.connect(ledger_path) as conn:
            rows = conn.execute("SELECT payload_json FROM sync_devices").fetchall()
    except sqlite3.DatabaseError:
        return 0
    count = 0
    for (payload_json,) in rows:
        try:
            payload = json.loads(payload_json)
        except (TypeError, json.JSONDecodeError):
            continue
        if (
            isinstance(payload, dict)
            and payload.get("record_type") == "sync_peer"
            and payload.get("status") == "active"
            and payload.get("sync_allowed") is True
        ):
            count += 1
    return count


def _rebuild_memory_os_retrieval(memory_os_runtime: MemoryOSRuntime) -> None:
    """Refresh the Memory OS retrieval index without blocking daemon listen."""
    print("[engramd] Rebuilding Memory OS retrieval index...", file=sys.stderr)
    try:
        manifest = memory_os_runtime.rebuild_retrieval_from_ledger()
    except Exception:
        print("[engramd] Memory OS retrieval rebuild failed.", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return
    print(
        "[engramd] Memory OS retrieval index ready "
        f"({manifest.get('indexed_count', 0)} chunks).",
        file=sys.stderr,
    )


def _refresh_retrieval_manifest_if_possible(memory_os_runtime: MemoryOSRuntime) -> None:
    """Repair manifest-only retrieval drift without forcing a full rebuild."""
    state = memory_os_runtime.retrieval_state()
    if state.get("status") != "stale_manifest":
        return
    mismatches = set(((state.get("diagnostics") or {}).get("mismatches")) or [])
    if "indexed_count" in mismatches or "vector_index_empty" in mismatches:
        return
    print("[engramd] Refreshing Memory OS retrieval manifest.", file=sys.stderr)
    try:
        manifest = memory_os_runtime.refresh_retrieval_manifest_from_ledger()
    except Exception:
        print("[engramd] Memory OS retrieval manifest refresh failed.", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return
    print(
        "[engramd] Memory OS retrieval manifest refreshed "
        f"({manifest.get('indexed_count', 0)} chunks).",
        file=sys.stderr,
    )


def build_doctor_payload(host: str, port: int) -> dict[str, Any]:
    """Build a no-write daemon/process hygiene report for operators."""
    url = f"http://{host}:{port}"
    daemon_health: dict[str, Any] | None = None
    daemon_error: dict[str, str] | None = None
    try:
        daemon_health = EngramDaemonClient(url).health()
    except Exception as exc:
        daemon_error = {"code": "runtime_error", "message": str(exc)}

    repo_root = Path(__file__).resolve().parent
    try:
        process_report = build_process_hygiene_report(discover_processes(), repo_root)
        process_error = None
    except Exception as exc:
        process_report = None
        process_error = {"code": "runtime_error", "message": str(exc)}

    return {
        "schema_version": "2026-05-13.engramd-doctor.v1",
        "daemon_url": url,
        "daemon_health": daemon_health,
        "daemon_error": daemon_error,
        "runtime_preflight": _memory_os_preflight_report(),
        "graph_reconciliation": _doctor_graph_reconciliation(daemon_health),
        "process_hygiene": process_report,
        "process_error": process_error,
    }


def _doctor_graph_reconciliation(daemon_health: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(daemon_health, dict):
        return {
            "status": "unknown",
            "trusted_for_evidence": False,
            "repair_required": True,
            "message": "Daemon health was unavailable; graph reconciliation could not be checked.",
        }
    graph_state = (
        daemon_health.get("memory_os", {})
        .get("components", {})
        .get("graph", {})
        .get("state")
    )
    if not isinstance(graph_state, dict):
        return {
            "status": "unknown",
            "trusted_for_evidence": False,
            "repair_required": True,
            "message": "Daemon health did not include Memory OS graph reconciliation state.",
        }
    return {
        "status": graph_state.get("status") or "unknown",
        "trusted_for_evidence": bool(graph_state.get("trusted_for_evidence")),
        "repair_required": bool(graph_state.get("repair_required")),
        "ledger_edge_count": (graph_state.get("ledger") or {}).get("edge_count"),
        "graph_store_edge_count": (graph_state.get("graph_store") or {}).get("edge_count"),
        "drift": graph_state.get("drift"),
        "repair_guidance": graph_state.get("repair_guidance"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Engram local daemon")
    parser.add_argument("--host", default=DEFAULT_DAEMON_HOST, help=f"Host (default: {DEFAULT_DAEMON_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_DAEMON_PORT, help=f"Port (default: {DEFAULT_DAEMON_PORT})")
    parser.add_argument(
        "--hub-listen",
        action="store_true",
        help="Start the authenticated Personal Hub gateway alongside the loopback daemon.",
    )
    parser.add_argument("--hub-host", default=DEFAULT_HUB_HOST, help=f"Hub gateway host (default: {DEFAULT_HUB_HOST})")
    parser.add_argument("--hub-port", type=int, default=DEFAULT_HUB_PORT, help=f"Hub gateway port (default: {DEFAULT_HUB_PORT})")
    parser.add_argument(
        "--sync-listen",
        action="store_true",
        help="Start the signed sync-only peer listener alongside the loopback daemon.",
    )
    parser.add_argument("--sync-host", default=DEFAULT_SYNC_HOST, help=f"Sync listener host (default: {DEFAULT_SYNC_HOST})")
    parser.add_argument("--sync-port", type=int, default=DEFAULT_SYNC_PORT, help=f"Sync listener port (default: {DEFAULT_SYNC_PORT})")
    check_group = parser.add_mutually_exclusive_group()
    check_group.add_argument("--health", action="store_true", help="Query daemon health and exit")
    check_group.add_argument(
        "--smoke-test",
        action="store_true",
        help="Run a duplicate/write/update/repair/search/read/delete smoke test against a running daemon and exit",
    )
    check_group.add_argument(
        "--doctor",
        action="store_true",
        help="Print daemon health plus Engram process hygiene diagnostics and exit",
    )
    check_group.add_argument(
        "--preflight",
        action="store_true",
        help="Run Memory OS runtime startup preflight checks and exit",
    )
    check_group.add_argument(
        "--runtime-snapshot",
        action="store_true",
        help="Create a verified restore-grade runtime snapshot and exit",
    )
    check_group.add_argument(
        "--prepare-sync-inbox-apply",
        action="store_true",
        help="Preview staged sync inbox bundles that are ready to apply and exit",
    )
    check_group.add_argument(
        "--apply-sync-inbox",
        action="store_true",
        help="Apply staged sync inbox bundles through the running loopback daemon and exit",
    )
    check_group.add_argument(
        "--prune-applied-sync-inbox-artifacts",
        action="store_true",
        help="Prune encrypted artifact bytes for already-applied staged sync inbox bundles and exit",
    )
    check_group.add_argument(
        "--verify-runtime-snapshot",
        metavar="PATH",
        help="Verify a restore-grade runtime snapshot manifest and exit",
    )
    check_group.add_argument(
        "--stop-server-pid",
        type=int,
        nargs="+",
        metavar="PID",
        help="Stop explicit PIDs only if they are this checkout's server.py MCP adapter processes",
    )
    parser.add_argument(
        "--snapshot-dir",
        default=None,
        help="Destination parent directory for --runtime-snapshot",
    )
    parser.add_argument(
        "--sync-peer-id",
        default=None,
        help="Optional peer device id for staged sync inbox commands",
    )
    parser.add_argument(
        "--sync-inbox-limit",
        type=int,
        default=0,
        help="Maximum staged bundles to inspect/apply; 0 means all pending bundles",
    )
    parser.add_argument(
        "--accept",
        action="store_true",
        help="Required with --apply-sync-inbox to perform writes",
    )
    parser.add_argument(
        "--approved-by",
        default=None,
        help="Reviewer/operator id required with accepted staged sync inbox writes",
    )
    args = parser.parse_args(argv)

    url = f"http://{args.host}:{args.port}"
    try:
        if args.sync_listen:
            if not is_loopback_host(args.host):
                raise PublicBindDenied(
                    "Sync listener Mode keeps the raw daemon loopback-only: "
                    "raw daemon --host must remain loopback; use --sync-host "
                    "for the signed Tailscale/LAN sync listener."
                )
            _validate_sync_listener_startup(args.sync_host)
    except PublicBindDenied as exc:
        print(f"[engramd] {exc}", file=sys.stderr)
        return 2

    if args.health:
        client = EngramDaemonClient(url)
        payload = client.health()
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        return 0 if payload.get("status") == "ok" and payload.get("error") is None else 1

    if args.doctor:
        payload = build_doctor_payload(args.host, args.port)
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        return 0

    if args.preflight:
        payload = _memory_os_preflight_report()
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        return 0 if payload.get("safe_to_start") is True else 2

    if args.runtime_snapshot:
        try:
            payload = create_verified_runtime_snapshot(
                _memory_os_root(),
                snapshot_parent=args.snapshot_dir,
                created_by="engramd_cli",
            )
        except RuntimeSnapshotError as exc:
            sys.stderr.write(f"[engramd] {exc}\n")
            return 2
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        return 0

    if args.verify_runtime_snapshot:
        payload = verify_runtime_snapshot(args.verify_runtime_snapshot)
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        return 0 if payload.get("status") == "ok" else 2

    if args.prepare_sync_inbox_apply:
        client = EngramDaemonClient(url, timeout=DEFAULT_SMOKE_TIMEOUT_SECONDS)
        payload = client.prepare_sync_inbox_apply(
            {
                "peer_id": args.sync_peer_id,
                "limit": args.sync_inbox_limit,
            }
        )
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        return 0 if payload.get("status") in {"ready", "empty"} and payload.get("error") is None else 1

    if args.apply_sync_inbox:
        client = EngramDaemonClient(url, timeout=max(DEFAULT_SMOKE_TIMEOUT_SECONDS, 900))
        payload = client.apply_sync_inbox(
            {
                "peer_id": args.sync_peer_id,
                "limit": args.sync_inbox_limit,
                "accept": args.accept,
                "approved_by": args.approved_by,
                "stop_on_error": True,
            }
        )
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        return 0 if payload.get("status") in {"applied", "empty"} and payload.get("error") is None else 1

    if args.prune_applied_sync_inbox_artifacts:
        client = EngramDaemonClient(url, timeout=max(DEFAULT_SMOKE_TIMEOUT_SECONDS, 900))
        payload = client.prune_applied_sync_inbox_artifacts(
            {
                "peer_id": args.sync_peer_id,
                "limit": args.sync_inbox_limit,
                "accept": args.accept,
                "approved_by": args.approved_by,
            }
        )
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        return 0 if payload.get("status") in {"ready", "pruned", "empty"} and payload.get("error") is None else 1

    if args.stop_server_pid:
        repo_root = Path(__file__).resolve().parent
        payload = stop_server_pids(args.stop_server_pid, discover_processes(), repo_root)
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        kill_failed = any(item.get("reason") == "kill_failed" for item in payload["skipped"])
        return 2 if kill_failed else 0

    if args.smoke_test:
        client = EngramDaemonClient(url, timeout=DEFAULT_SMOKE_TIMEOUT_SECONDS)
        payload = run_daemon_smoke(client)
        payload["url"] = url
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        return 0 if payload.get("status") == "ok" and payload.get("error") is None else 1

    try:
        if args.hub_listen:
            if not is_loopback_host(args.host):
                raise PublicBindDenied(
                    "Personal Hub Mode keeps the raw daemon loopback-only: "
                    "raw daemon --host must remain loopback; use --hub-host "
                    "for the authenticated Tailscale/LAN gateway."
                )
            validation = validate_hub_gateway_bind(args.hub_host)
            if validation.get("safe_to_bind") is not True:
                raise PublicBindDenied(
                    f"Personal Hub gateway refuses to bind {args.hub_host!r}: "
                    f"{(validation.get('error') or {}).get('code')}"
                )
        if args.sync_listen and not is_loopback_host(args.host):
            raise PublicBindDenied(
                "Sync listener Mode keeps the raw daemon loopback-only: "
                "raw daemon --host must remain loopback; use --sync-host "
                "for the signed Tailscale/LAN sync listener."
            )
    except PublicBindDenied as exc:
        print(f"[engramd] {exc}", file=sys.stderr)
        return 2

    try:
        validate_raw_service_bind(args.host, surface="engramd raw daemon")
    except PublicBindDenied as exc:
        print(f"[engramd] {exc}", file=sys.stderr)
        return 2

    run_daemon(
        args.host,
        args.port,
        hub_listen=args.hub_listen,
        hub_host=args.hub_host,
        hub_port=args.hub_port,
        sync_listen=args.sync_listen,
        sync_host=args.sync_host,
        sync_port=args.sync_port,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
