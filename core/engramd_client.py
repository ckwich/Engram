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

    def query_knowledge(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/query_knowledge", payload)

    def retrieve_chunk(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/retrieve_chunk", payload)

    def retrieve_chunks(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/retrieve_chunks", payload)

    def retrieve_memory(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/retrieve_memory", payload)

    def store_memory(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/store_memory", payload)

    def prepare_source_memory(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/prepare_source_memory", payload)

    def list_document_extractors(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/list_document_extractors", payload)

    def preview_document_source_connector(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/preview_document_source_connector", payload)

    def prepare_document_disassembly(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/prepare_document_disassembly", payload)

    def prepare_document_intake_review(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/prepare_document_intake_review", payload)

    def prepare_document_extraction_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/prepare_document_extraction_request", payload)

    def prepare_document_extraction_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/prepare_document_extraction_result", payload)

    def preview_document_extraction(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/preview_document_extraction", payload)

    def prepare_visual_extraction_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/prepare_visual_extraction_request", payload)

    def preview_visual_extraction(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/preview_visual_extraction", payload)

    def prepare_document_understanding_packet(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/prepare_document_understanding_packet", payload)

    def prepare_document_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/prepare_document_draft", payload)

    def prepare_document_promotion_transaction(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/prepare_document_promotion_transaction", payload)

    def apply_document_promotion_transaction(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/apply_document_promotion_transaction", payload)

    def prepare_document_artifact_store(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/prepare_document_artifact_store", payload)

    def store_document_artifact(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/store_document_artifact", payload)

    def memory_os_status(self) -> dict[str, Any]:
        return self._request("GET", "/v1/memory_os/status")

    def memory_os_inspector(self) -> dict[str, Any]:
        return self._request("GET", "/v1/memory_os/inspector")

    def memory_os_source_import_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/memory_os/source_import_job", payload)

    def list_source_drafts(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/list_source_drafts", payload)

    def discard_source_draft(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/discard_source_draft", payload)

    def store_prepared_memory(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/store_prepared_memory", payload)

    def check_duplicate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/check_duplicate", payload)

    def update_memory_metadata(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/update_memory_metadata", payload)

    def repair_memory_metadata(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/repair_memory_metadata", payload)

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
