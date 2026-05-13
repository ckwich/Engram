#!/usr/bin/env python3
"""Run the local Engram daemon."""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from core.embedder import embedder
from core.engramd_api import EngramDaemonAPI
from core.engramd_client import EngramDaemonClient
from core.engramd_smoke import run_daemon_smoke
from core.memory_manager import memory_manager
from core.process_hygiene import (
    build_process_hygiene_report,
    discover_processes,
    stop_server_pids,
)

DEFAULT_DAEMON_HOST = os.environ.get("ENGRAM_DAEMON_HOST", "127.0.0.1")
DEFAULT_DAEMON_PORT = int(os.environ.get("ENGRAM_DAEMON_PORT", "8765"))


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
            length = int(self.headers.get("Content-Length", "0") or "0")
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


def run_daemon(host: str, port: int) -> None:
    """Start the local daemon and own live storage/index state."""
    print("[engramd] Pre-loading embedding model...", file=sys.stderr)
    embedder._load()
    print("[engramd] Initializing memory store...", file=sys.stderr)
    memory_manager._ensure_initialized()
    server = ThreadingHTTPServer((host, port), EngramDaemonRequestHandler)
    print(f"[engramd] Listening on http://{host}:{port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("[engramd] Shutdown requested.", file=sys.stderr)
    finally:
        server.server_close()


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
        "process_hygiene": process_report,
        "process_error": process_error,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Engram local daemon")
    parser.add_argument("--host", default=DEFAULT_DAEMON_HOST, help=f"Host (default: {DEFAULT_DAEMON_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_DAEMON_PORT, help=f"Port (default: {DEFAULT_DAEMON_PORT})")
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
        "--stop-server-pid",
        type=int,
        nargs="+",
        metavar="PID",
        help="Stop explicit PIDs only if they are this checkout's server.py MCP adapter processes",
    )
    args = parser.parse_args(argv)

    url = f"http://{args.host}:{args.port}"
    if args.health:
        client = EngramDaemonClient(url)
        payload = client.health()
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        return 0 if payload.get("status") == "ok" and payload.get("error") is None else 1

    if args.doctor:
        payload = build_doctor_payload(args.host, args.port)
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        return 0

    if args.stop_server_pid:
        repo_root = Path(__file__).resolve().parent
        payload = stop_server_pids(args.stop_server_pid, discover_processes(), repo_root)
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        kill_failed = any(item.get("reason") == "kill_failed" for item in payload["skipped"])
        return 2 if kill_failed else 0

    if args.smoke_test:
        client = EngramDaemonClient(url)
        payload = run_daemon_smoke(client)
        payload["url"] = url
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        return 0 if payload.get("status") == "ok" and payload.get("error") is None else 1

    run_daemon(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
