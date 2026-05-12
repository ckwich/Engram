"""Client helpers for talking to a local Engram daemon."""
from __future__ import annotations

import json
from typing import Any
from urllib import error, request


class EngramDaemonClientError(RuntimeError):
    """Raised when an Engram daemon request fails before returning JSON."""


class UrllibJSONTransport:
    """Standard-library JSON transport for daemon calls."""

    def request_json(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = request.Request(url, data=data, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            raw_error = exc.read().decode("utf-8", errors="replace")
            try:
                return json.loads(raw_error)
            except json.JSONDecodeError as decode_exc:
                raise EngramDaemonClientError(
                    f"Daemon HTTP {exc.code} returned non-JSON error"
                ) from decode_exc
        except error.URLError as exc:
            raise EngramDaemonClientError(f"Daemon request failed: {exc}") from exc

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EngramDaemonClientError("Daemon returned non-JSON response") from exc


class EngramDaemonClient:
    """Small JSON client for daemon-owned memory operations."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 10.0,
        transport: Any | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport or UrllibJSONTransport()

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def search_memories(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/search_memories", payload)

    def retrieve_chunk(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/retrieve_chunk", payload)

    def retrieve_chunks(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/retrieve_chunks", payload)

    def retrieve_memory(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/retrieve_memory", payload)

    def store_memory(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/store_memory", payload)

    def delete_memory(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/delete_memory", payload)

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.transport.request_json(
            method,
            f"{self.base_url}{path}",
            payload,
            self.timeout,
        )
