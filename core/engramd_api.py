"""Loopback JSON API surface for the Engram daemon.

The daemon owns live storage/index state. MCP stdio processes can call this
API as thin clients instead of each process trying to own embedded ChromaDB.
"""
from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlparse

from core.memory_manager import DuplicateMemoryError, memory_manager


class EngramDaemonAPI:
    """Small request dispatcher for daemon-owned memory operations."""

    def __init__(self, memory_manager=memory_manager):
        self.memory_manager = memory_manager

    def handle(self, method: str, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        """Handle one daemon request and return {status, body}."""
        return asyncio.run(self.handle_async(method, path, payload))

    async def handle_async(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        route = urlparse(path).path.rstrip("/") or "/"
        request = payload if isinstance(payload, dict) else {}
        method = method.upper()

        try:
            if method == "GET" and route == "/health":
                return self._ok(
                    {
                        "daemon": "engramd",
                        "status": "ok",
                        "stats": self.memory_manager.get_stats(),
                        "error": None,
                    }
                )
            if method != "POST":
                return self._error(405, "method_not_allowed", f"{method} is not allowed for {route}")
            if route == "/v1/search_memories":
                return await self._search_memories(request)
            if route == "/v1/retrieve_chunk":
                return await self._retrieve_chunk(request)
            if route == "/v1/retrieve_chunks":
                return await self._retrieve_chunks(request)
            if route == "/v1/retrieve_memory":
                return await self._retrieve_memory(request)
            if route == "/v1/store_memory":
                return await self._store_memory(request)
            if route == "/v1/check_duplicate":
                return await self._check_duplicate(request)
            if route == "/v1/update_memory_metadata":
                return await self._update_memory_metadata(request)
            if route == "/v1/repair_memory_metadata":
                return await self._repair_memory_metadata(request)
            if route == "/v1/delete_memory":
                return await self._delete_memory(request)
            return self._error(404, "not_found", f"Unknown daemon route: {route}")
        except Exception as exc:
            return self._error(500, "runtime_error", f"Engram daemon error: {exc}")

    async def _search_memories(self, request: dict[str, Any]) -> dict[str, Any]:
        query = str(request.get("query") or "").strip()
        if not query:
            return self._error(400, "invalid_request", "query is required")
        payload = await self.memory_manager.search_memories_structured_async(
            query,
            limit=_int_value(request.get("limit"), default=5),
            project=_optional_text(request.get("project")),
            domain=_optional_text(request.get("domain")),
            tags=request.get("tags"),
            include_stale=bool(request.get("include_stale", True)),
            canonical_only=bool(request.get("canonical_only", False)),
            pinned_keys=_string_list(request.get("pinned_keys")),
            pinned_first=bool(request.get("pinned_first", False)),
            retrieval_mode=str(request.get("retrieval_mode") or "semantic"),
        )
        payload["error"] = payload.get("error")
        return self._ok(payload)

    async def _retrieve_chunk(self, request: dict[str, Any]) -> dict[str, Any]:
        key = str(request.get("key") or "").strip()
        if not key:
            return self._error(400, "invalid_request", "key is required")
        chunk_id = _int_value(request.get("chunk_id"), default=0)
        raw_results = await self.memory_manager.retrieve_chunks_async(
            [{"key": key, "chunk_id": chunk_id}]
        )
        result = raw_results[0] if raw_results else None
        return self._ok(_chunk_payload(result, key, chunk_id))

    async def _retrieve_chunks(self, request: dict[str, Any]) -> dict[str, Any]:
        requests = request.get("requests")
        if not isinstance(requests, list):
            return self._error(400, "invalid_request", "requests must be a list")
        raw_results = await self.memory_manager.retrieve_chunks_async(requests)
        results = [
            _chunk_payload(result, result.get("key", ""), result.get("chunk_id", -1))
            for result in raw_results
        ]
        return self._ok(
            {
                "requested_count": len(requests),
                "found_count": sum(1 for result in results if result["found"]),
                "results": results,
                "error": None,
            }
        )

    async def _retrieve_memory(self, request: dict[str, Any]) -> dict[str, Any]:
        key = str(request.get("key") or "").strip()
        if not key:
            return self._error(400, "invalid_request", "key is required")
        result = await self.memory_manager.retrieve_memory_async(key)
        return self._ok(
            {
                "key": key,
                "found": result is not None,
                "memory": result,
                "error": None,
            }
        )

    async def _store_memory(self, request: dict[str, Any]) -> dict[str, Any]:
        key = str(request.get("key") or "").strip()
        content = request.get("content")
        if not key:
            return self._error(400, "invalid_request", "key is required")
        if not isinstance(content, str) or not content.strip():
            return self._error(400, "invalid_request", "content is required")
        try:
            result = await self.memory_manager.store_memory_async(
                key=key,
                content=content,
                tags=_string_list(request.get("tags")),
                title=_optional_text(request.get("title")),
                related_to=_string_list(request.get("related_to")),
                force=bool(request.get("force", False)),
                project=_optional_text(request.get("project")),
                domain=_optional_text(request.get("domain")),
                status=_optional_text(request.get("status")),
                canonical=request.get("canonical"),
            )
        except DuplicateMemoryError as exc:
            return self._ok(
                {
                    "stored": False,
                    "duplicate": exc.duplicate,
                    "error": {
                        "code": "duplicate",
                        "message": "Similar memory already exists.",
                    },
                }
            )
        except ValueError as exc:
            return self._error(400, "invalid_request", str(exc))
        return self._ok({"stored": True, "result": result, "error": None})

    async def _check_duplicate(self, request: dict[str, Any]) -> dict[str, Any]:
        key = str(request.get("key") or "").strip()
        content = request.get("content")
        if not key:
            return self._ok(
                {
                    "key": key,
                    "duplicate": False,
                    "match": None,
                    "error": {
                        "code": "invalid_request",
                        "message": "key is required",
                    },
                }
            )
        if not isinstance(content, str) or not content.strip():
            return self._ok(
                {
                    "key": key,
                    "duplicate": False,
                    "match": None,
                    "error": {
                        "code": "invalid_request",
                        "message": "content is required",
                    },
                }
            )
        result = await self.memory_manager.check_duplicate_async(key, content)
        return self._ok(
            {
                "key": result.get("key", key),
                "duplicate": bool(result.get("duplicate", False)),
                "match": result.get("match"),
                "error": None,
            }
        )

    async def _update_memory_metadata(self, request: dict[str, Any]) -> dict[str, Any]:
        key = str(request.get("key") or "").strip()
        if not key:
            return self._error(400, "invalid_request", "key is required")
        changes = {
            name: value
            for name, value in {
                "title": request.get("title") if "title" in request else None,
                "tags": _string_list(request.get("tags")) if "tags" in request else None,
                "related_to": _string_list(request.get("related_to")) if "related_to" in request else None,
                "project": request.get("project") if "project" in request else None,
                "domain": request.get("domain") if "domain" in request else None,
                "status": request.get("status") if "status" in request else None,
                "canonical": request.get("canonical") if "canonical" in request else None,
            }.items()
            if value is not None
        }
        try:
            memory = await self.memory_manager.update_memory_metadata_async(key, **changes)
        except KeyError:
            return self._ok(
                {
                    "key": key,
                    "updated": False,
                    "memory": None,
                    "error": {
                        "code": "not_found",
                        "message": f"❌ Memory not found: '{key}'",
                    },
                }
            )
        except ValueError as exc:
            return self._ok(
                {
                    "key": key,
                    "updated": False,
                    "memory": None,
                    "error": {
                        "code": "invalid_metadata",
                        "message": str(exc),
                    },
                }
            )
        return self._ok({"key": key, "updated": True, "memory": memory, "error": None})

    async def _repair_memory_metadata(self, request: dict[str, Any]) -> dict[str, Any]:
        keys = _string_list(request.get("keys"))
        dry_run = bool(request.get("dry_run", True))
        if not keys:
            return self._ok(
                {
                    "requested_count": 0,
                    "repaired_count": 0,
                    "dry_run": dry_run,
                    "repairs": [],
                    "error": {
                        "code": "invalid_keys",
                        "message": "keys must include at least one memory key.",
                    },
                }
            )
        payload = await self.memory_manager.repair_memory_metadata_async(keys, dry_run=dry_run)
        payload["error"] = None
        return self._ok(payload)

    async def _delete_memory(self, request: dict[str, Any]) -> dict[str, Any]:
        key = str(request.get("key") or "").strip()
        if not key:
            return self._error(400, "invalid_request", "key is required")
        deleted = await self.memory_manager.delete_memory_async(key)
        return self._ok({"key": key, "deleted": bool(deleted), "error": None})

    @staticmethod
    def _ok(body: dict[str, Any]) -> dict[str, Any]:
        return {"status": 200, "body": body}

    @staticmethod
    def _error(status: int, code: str, message: str) -> dict[str, Any]:
        return {
            "status": status,
            "body": {
                "error": {
                    "code": code,
                    "message": message,
                }
            },
        }


def _chunk_payload(result: dict[str, Any] | None, key: str, chunk_id: int) -> dict[str, Any]:
    if not result:
        return {
            "key": key,
            "chunk_id": chunk_id,
            "found": False,
            "chunk": None,
            "error": None,
        }
    found = bool(result.get("found", True))
    chunk = None
    if found:
        chunk = {
            "title": result.get("title", key),
            "text": result.get("text"),
            "section_title": result.get("section_title"),
            "heading_path": result.get("heading_path", []),
            "chunk_kind": result.get("chunk_kind"),
        }
    return {
        "key": result.get("key", key),
        "chunk_id": result.get("chunk_id", chunk_id),
        "found": found,
        "chunk": chunk,
        "error": result.get("error"),
    }


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    raw_items = value.split(",") if isinstance(value, str) else list(value)
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _int_value(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
