"""Narrow authenticated gateway for Engram Personal Hub Mode."""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler
from typing import Any

from core.hub_auth import authorize_hub_request
from core.mcp.tool_registry import DAEMON_ROUTES


HUB_ALLOWED_TOOL_NAMES = frozenset(
    {
        "memory_os_status",
        "discover_memory_capabilities",
        "query_knowledge",
        "search_memories",
        "retrieve_chunk",
        "retrieve_chunks",
        "retrieve_memory",
        "store_memory",
        "prepare_source_memory",
        "list_source_drafts",
        "store_prepared_memory",
        "discard_source_draft",
        "check_duplicate",
        "update_memory_metadata",
        "repair_memory_metadata",
        "list_memory_benchmark_suites",
        "run_memory_benchmark",
        "inspect_benchmark_run",
        "ensure_sync_device_identity",
        "export_local_sync_identity",
        "register_sync_peer",
        "list_sync_inbox",
        "prepare_sync_inbox_apply",
        "apply_sync_inbox",
    }
)
HUB_ALLOWED_DAEMON_ROUTES = frozenset(
    {("GET", "/health")}
    | {
        (DAEMON_ROUTES[name].method, DAEMON_ROUTES[name].path)
        for name in HUB_ALLOWED_TOOL_NAMES
    }
)


def authorize_hub_gateway_route(method: str, route: str, *, authenticated: bool) -> dict[str, Any]:
    """Authorize a request path against the Personal Hub route allowlist."""
    normalized = (str(method or "").upper(), str(route or "").split("?", 1)[0])
    if not authenticated:
        return {"allowed": False, "error": {"code": "hub_authorization_required"}}
    if normalized not in HUB_ALLOWED_DAEMON_ROUTES:
        return {"allowed": False, "error": {"code": "hub_route_not_allowed"}}
    return {"allowed": True, "route": {"method": normalized[0], "path": normalized[1]}}


def make_hub_gateway_handler(
    daemon_api: Any,
    *,
    expected_token: str,
    allowed_hosts: set[str] | None = None,
    max_content_length: int = 16 * 1024 * 1024,
) -> type[BaseHTTPRequestHandler]:
    """Build an authenticated HTTP handler that forwards only allowlisted routes."""

    class EngramHubGatewayRequestHandler(BaseHTTPRequestHandler):
        server_version = "EngramHub/1.0"

        def do_GET(self) -> None:
            self._handle_hub_request("GET")

        def do_POST(self) -> None:
            self._handle_hub_request("POST")

        def _handle_hub_request(self, method: str) -> None:
            host_check = _authorize_host_header(
                self.headers.get("Host", ""),
                allowed_hosts=allowed_hosts,
            )
            if host_check.get("allowed") is not True:
                self._send_json(403, {"error": host_check["error"]})
                _log_hub_receipt(self, method, 403, authenticated=False, route_allowed=False)
                return

            auth = authorize_hub_request(
                {str(key): str(value) for key, value in self.headers.items()},
                expected_token=expected_token,
            )
            authenticated = auth.get("authorized") is True
            route_auth = authorize_hub_gateway_route(method, self.path, authenticated=authenticated)
            if not authenticated:
                self._send_json(401, {"error": auth.get("error")})
                _log_hub_receipt(
                    self,
                    method,
                    401,
                    authenticated=False,
                    route_allowed=False,
                    token_fingerprint=auth.get("token_fingerprint"),
                )
                return
            if route_auth.get("allowed") is not True:
                self._send_json(404, {"error": route_auth.get("error")})
                _log_hub_receipt(
                    self,
                    method,
                    404,
                    authenticated=True,
                    route_allowed=False,
                    token_fingerprint=auth.get("token_fingerprint"),
                )
                return

            payload = self._read_json_payload(method)
            if isinstance(payload, _HubReadError):
                self._send_json(payload.status_code, {"error": payload.error})
                _log_hub_receipt(
                    self,
                    method,
                    payload.status_code,
                    authenticated=True,
                    route_allowed=True,
                    token_fingerprint=auth.get("token_fingerprint"),
                )
                return

            response = daemon_api.handle(method, self.path, payload)
            status = int(response.get("status") or 500)
            body = response.get("body") if isinstance(response.get("body"), dict) else {}
            self._send_json(status, body)
            _log_hub_receipt(
                self,
                method,
                status,
                authenticated=True,
                route_allowed=True,
                token_fingerprint=auth.get("token_fingerprint"),
            )

        def _read_json_payload(self, method: str) -> dict[str, Any] | _HubReadError | None:
            if method != "POST":
                return None
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except ValueError:
                return _HubReadError(
                    400,
                    {"code": "invalid_content_length", "message": "Content-Length must be an integer."},
                )
            if length < 0:
                return _HubReadError(
                    400,
                    {
                        "code": "invalid_content_length",
                        "message": "Content-Length must be a non-negative integer.",
                    },
                )
            if length > max_content_length:
                return _HubReadError(
                    413,
                    {"code": "request_body_too_large", "message": "Request body exceeds hub gateway limit."},
                )
            raw = self.rfile.read(length) if length else b"{}"
            try:
                decoded = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                return _HubReadError(
                    400,
                    {"code": "invalid_json", "message": "Request body must be valid JSON."},
                )
            if decoded is not None and not isinstance(decoded, dict):
                return _HubReadError(
                    400,
                    {"code": "invalid_json", "message": "Request body must be a JSON object."},
                )
            return decoded

        def _send_json(self, status: int, body: dict[str, Any]) -> None:
            raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args: Any) -> None:
            print(f"[engram-hub] {self.address_string()} - {format % args}", file=sys.stderr)

    return EngramHubGatewayRequestHandler


class _HubReadError:
    def __init__(self, status_code: int, error: dict[str, Any]) -> None:
        self.status_code = status_code
        self.error = error


def build_hub_access_receipt(
    *,
    method: str,
    route: str,
    status_code: int,
    authenticated: bool,
    route_allowed: bool,
    remote_addr: str,
    token_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Return a compact access receipt that never includes request or response bodies."""
    return {
        "schema_version": "2026-05-26.hub-access-receipt.v1",
        "surface": "personal_hub_gateway",
        "method": str(method or "").upper(),
        "route": str(route or "").split("?", 1)[0],
        "status_code": int(status_code),
        "authenticated": bool(authenticated),
        "route_allowed": bool(route_allowed),
        "remote_addr": remote_addr,
        "token_fingerprint": token_fingerprint,
    }


def _authorize_host_header(host_header: str, *, allowed_hosts: set[str] | None) -> dict[str, Any]:
    if not allowed_hosts:
        return {"allowed": True}
    host = str(host_header or "").split(":", 1)[0].strip().lower()
    if host in allowed_hosts:
        return {"allowed": True}
    return {"allowed": False, "error": {"code": "hub_host_not_allowed"}}


def _log_hub_receipt(
    handler: BaseHTTPRequestHandler,
    method: str,
    status_code: int,
    *,
    authenticated: bool,
    route_allowed: bool,
    token_fingerprint: str | None = None,
) -> None:
    receipt = build_hub_access_receipt(
        method=method,
        route=handler.path,
        status_code=status_code,
        authenticated=authenticated,
        route_allowed=route_allowed,
        remote_addr=str(handler.client_address[0] if handler.client_address else ""),
        token_fingerprint=token_fingerprint,
    )
    print(f"[engram-hub] access {json.dumps(receipt, sort_keys=True)}", file=sys.stderr)
