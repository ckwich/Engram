"""Loopback JSON API surface for the Engram daemon.

The daemon owns live storage/index state. MCP stdio processes can call this
API as thin clients instead of each process trying to own embedded ChromaDB.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from core.document_intelligence import (
    list_document_extractors,
    prepare_document_draft,
    prepare_document_extraction_request,
    prepare_document_extraction_result,
    prepare_document_promotion_transaction,
    prepare_document_understanding_packet,
    prepare_visual_extraction_request,
    preview_document_extraction,
    preview_visual_extraction,
)
from core.document_extractors import prepare_document_disassembly
from core.document_intake_workflow import prepare_document_intake_review
from core.memory_manager import DuplicateMemoryError, memory_manager
from core.memory_os.runtime import MemoryOSRuntime
from core.source_connectors import preview_document_source_connector
from core.source_intake import source_intake_manager


class DocumentWorkflow:
    """Daemon-owned wrapper around existing no-write document helpers."""

    def __init__(self, document_disassembler=prepare_document_disassembly):
        self.document_disassembler = document_disassembler

    def list_document_extractors(self) -> dict[str, Any]:
        return list_document_extractors()

    def preview_document_source_connector(self, **kwargs: Any) -> dict[str, Any]:
        return preview_document_source_connector(**kwargs)

    def prepare_document_disassembly(self, **kwargs: Any) -> dict[str, Any]:
        return self.document_disassembler(**kwargs)

    def prepare_document_intake_review(self, **kwargs: Any) -> dict[str, Any]:
        return prepare_document_intake_review(
            document_disassembler=self.document_disassembler,
            **kwargs,
        )

    def prepare_document_extraction_request(self, **kwargs: Any) -> dict[str, Any]:
        return prepare_document_extraction_request(**kwargs)

    def prepare_document_extraction_result(self, **kwargs: Any) -> dict[str, Any]:
        return prepare_document_extraction_result(**kwargs)

    def preview_document_extraction(self, **kwargs: Any) -> dict[str, Any]:
        return preview_document_extraction(**kwargs)

    def prepare_visual_extraction_request(self, **kwargs: Any) -> dict[str, Any]:
        return prepare_visual_extraction_request(**kwargs)

    def preview_visual_extraction(self, **kwargs: Any) -> dict[str, Any]:
        return preview_visual_extraction(**kwargs)

    def prepare_document_understanding_packet(self, **kwargs: Any) -> dict[str, Any]:
        return prepare_document_understanding_packet(**kwargs)

    def prepare_document_draft(self, **kwargs: Any) -> dict[str, Any]:
        return prepare_document_draft(**kwargs)

    def prepare_document_promotion_transaction(self, **kwargs: Any) -> dict[str, Any]:
        return prepare_document_promotion_transaction(**kwargs)


class EngramDaemonAPI:
    """Small request dispatcher for daemon-owned memory operations."""

    def __init__(
        self,
        memory_manager=memory_manager,
        source_intake_manager=source_intake_manager,
        document_disassembler=prepare_document_disassembly,
        document_tools: Any | None = None,
        memory_os_runtime: MemoryOSRuntime | None = None,
    ):
        self.memory_manager = memory_manager
        self.source_intake_manager = source_intake_manager
        self.document_disassembler = document_disassembler
        self.document_tools = document_tools or DocumentWorkflow(document_disassembler)
        self.memory_os_runtime = memory_os_runtime

    def handle(self, method: str, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        """Handle one daemon request and return {status, body}."""
        return asyncio.run(self.handle_async(method, path, payload))

    async def handle_async(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        parsed_path = urlparse(path)
        route = parsed_path.path.rstrip("/") or "/"
        query = parse_qs(parsed_path.query)
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
            if method == "GET" and route == "/v1/memory_os/status":
                return self._ok(self._runtime().status())
            if method == "GET" and route == "/v1/memory_os/inspector":
                limit = _bounded_query_int(query, "limit", default=20, minimum=1, maximum=100)
                return self._ok(self._runtime().inspector(limit=limit))
            if method != "POST":
                return self._error(405, "method_not_allowed", f"{method} is not allowed for {route}")
            if route == "/v1/memory_os/source_import_job":
                return self._memory_os_source_import_job(request)
            if route == "/v1/query_knowledge":
                return await self._query_knowledge(request)
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
            if route == "/v1/prepare_source_memory":
                return await self._prepare_source_memory(request)
            if route == "/v1/list_document_extractors":
                return await self._document_tool(
                    "list_document_extractors",
                    request,
                    result_key="catalog",
                    include_payload=False,
                )
            if route == "/v1/preview_document_source_connector":
                return await self._document_tool(
                    "preview_document_source_connector",
                    request,
                    result_key=None,
                )
            if route == "/v1/prepare_document_disassembly":
                return await self._prepare_document_disassembly(request)
            if route == "/v1/prepare_document_intake_review":
                return await self._document_tool(
                    "prepare_document_intake_review",
                    request,
                    result_key=None,
                )
            if route == "/v1/prepare_document_extraction_request":
                return await self._document_tool(
                    "prepare_document_extraction_request",
                    request,
                    result_key="request",
                )
            if route == "/v1/prepare_document_extraction_result":
                return await self._document_tool(
                    "prepare_document_extraction_result",
                    request,
                    result_key="result",
                )
            if route == "/v1/preview_document_extraction":
                return await self._document_tool(
                    "preview_document_extraction",
                    request,
                    result_key="preview",
                )
            if route == "/v1/prepare_visual_extraction_request":
                return await self._document_tool(
                    "prepare_visual_extraction_request",
                    request,
                    result_key="request",
                )
            if route == "/v1/preview_visual_extraction":
                return await self._document_tool(
                    "preview_visual_extraction",
                    request,
                    result_key="preview",
                )
            if route == "/v1/prepare_document_understanding_packet":
                return await self._document_tool(
                    "prepare_document_understanding_packet",
                    request,
                    result_key="packet",
                )
            if route == "/v1/prepare_document_draft":
                return await self._document_tool(
                    "prepare_document_draft",
                    request,
                    result_key="draft",
                )
            if route == "/v1/prepare_document_promotion_transaction":
                return await self._document_tool(
                    "prepare_document_promotion_transaction",
                    request,
                    result_key="transaction",
                )
            if route == "/v1/apply_document_promotion_transaction":
                return await self._apply_document_promotion_transaction(request)
            if route == "/v1/prepare_document_artifact_store":
                return await self._prepare_document_artifact_store(request)
            if route == "/v1/store_document_artifact":
                return await self._store_document_artifact(request)
            if route == "/v1/list_source_drafts":
                return await self._list_source_drafts(request)
            if route == "/v1/discard_source_draft":
                return await self._discard_source_draft(request)
            if route == "/v1/store_prepared_memory":
                return await self._store_prepared_memory(request)
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

    async def _query_knowledge(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.memory_os_runtime is None:
            return self._error(
                503,
                "memory_os_unavailable",
                "query_knowledge requires daemon-owned Memory OS runtime.",
            )
        return self._ok(self.memory_os_runtime.query_knowledge(request))

    async def _prepare_document_artifact_store(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.memory_os_runtime is None:
            return self._error(
                503,
                "memory_os_unavailable",
                "prepare_document_artifact_store requires daemon-owned Memory OS runtime.",
            )
        review_packet = request.get("review_packet")
        artifact_family = str(request.get("artifact_family") or "document_evidence")
        return self._ok(
            self.memory_os_runtime.prepare_document_artifact_store(
                review_packet,
                artifact_family=artifact_family,
            )
        )

    async def _store_document_artifact(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.memory_os_runtime is None:
            return self._error(
                503,
                "memory_os_unavailable",
                "store_document_artifact requires daemon-owned Memory OS runtime.",
            )
        return self._ok(
            self.memory_os_runtime.store_document_artifact(
                str(request.get("prepared_transaction_id") or ""),
                accept=bool(request.get("accept", False)),
                review_packet=request.get("review_packet"),
            )
        )

    async def _apply_document_promotion_transaction(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.memory_os_runtime is None:
            return self._error(
                503,
                "memory_os_unavailable",
                "apply_document_promotion_transaction requires daemon-owned Memory OS runtime.",
            )
        return self._ok(
            self.memory_os_runtime.apply_document_promotion_transaction(
                request.get("document_promotion_transaction") or {},
                accept=bool(request.get("accept", False)),
                approved_by=_optional_text(request.get("approved_by")),
                selected_operation_indexes=request.get("selected_operation_indexes"),
            )
        )

    async def _search_memories(self, request: dict[str, Any]) -> dict[str, Any]:
        query = str(request.get("query") or "").strip()
        if not query:
            return self._error(400, "invalid_request", "query is required")
        if self.memory_os_runtime is not None:
            return self._ok(
                self.memory_os_runtime.search_memories(
                    query=query,
                    limit=_int_value(request.get("limit"), default=5),
                    project=_optional_text(request.get("project")),
                    domain=_optional_text(request.get("domain")),
                    tags=_string_list(request.get("tags")),
                    include_stale=bool(request.get("include_stale", True)),
                    canonical_only=bool(request.get("canonical_only", False)),
                    pinned_keys=_string_list(request.get("pinned_keys")),
                    pinned_first=bool(request.get("pinned_first", False)),
                    retrieval_mode=str(request.get("retrieval_mode") or "semantic"),
                )
            )
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
        if self.memory_os_runtime is not None:
            return self._ok(self.memory_os_runtime.retrieve_chunk(key, chunk_id))
        raw_results = await self.memory_manager.retrieve_chunks_async(
            [{"key": key, "chunk_id": chunk_id}]
        )
        result = raw_results[0] if raw_results else None
        return self._ok(_chunk_payload(result, key, chunk_id))

    async def _retrieve_chunks(self, request: dict[str, Any]) -> dict[str, Any]:
        requests = request.get("requests")
        if not isinstance(requests, list):
            return self._error(400, "invalid_request", "requests must be a list")
        if self.memory_os_runtime is not None:
            results = [
                self.memory_os_runtime.retrieve_chunk(
                    str(item.get("key") or ""),
                    _int_value(item.get("chunk_id"), default=0),
                )
                for item in requests
                if isinstance(item, dict)
            ]
            return self._ok(
                {
                    "requested_count": len(requests),
                    "found_count": sum(1 for result in results if result["found"]),
                    "results": results,
                    "error": None,
                }
            )
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
        if self.memory_os_runtime is not None:
            return self._ok(self.memory_os_runtime.retrieve_memory(key))
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
        if self.memory_os_runtime is not None:
            try:
                result = self.memory_os_runtime.store_memory(
                    key=key,
                    content=content,
                    tags=_string_list(request.get("tags")),
                    title=_optional_text(request.get("title")) or key,
                    related_to=_string_list(request.get("related_to")),
                    force=bool(request.get("force", False)),
                    project=_optional_text(request.get("project")),
                    domain=_optional_text(request.get("domain")),
                    status=_optional_text(request.get("status")),
                    canonical=request.get("canonical"),
                )
            except ValueError as exc:
                return self._error(400, "invalid_request", str(exc))
            return self._ok({"stored": True, "result": result, "error": None})
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

    async def _prepare_source_memory(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            draft = self.source_intake_manager.prepare_source_memory(
                source_text=request.get("source_text"),
                source_type=request.get("source_type"),
                source_uri=request.get("source_uri"),
                project=request.get("project"),
                domain=request.get("domain"),
                budget_chars=request.get("budget_chars", 6000),
                pipeline=request.get("pipeline", "generic"),
            )
        except ValueError as exc:
            return self._ok(
                {
                    "draft": None,
                    "error": {
                        "code": "invalid_request",
                        "message": str(exc),
                    },
                }
            )
        except RuntimeError as exc:
            return self._ok(
                {
                    "draft": None,
                    "error": {
                        "code": "runtime_error",
                        "message": str(exc),
                    },
                }
            )
        return self._ok({"draft": draft, "error": None})

    async def _document_tool(
        self,
        tool_name: str,
        request: dict[str, Any],
        *,
        result_key: str | None,
        include_payload: bool = True,
    ) -> dict[str, Any]:
        try:
            tool = getattr(self.document_tools, tool_name)
            result = tool(**request) if include_payload else tool()
        except ValueError as exc:
            if result_key is None:
                return self._ok(
                    {
                        "error": {
                            "code": "invalid_request",
                            "message": str(exc),
                        },
                    }
                )
            return self._ok(
                {
                    result_key: None,
                    "error": {
                        "code": "invalid_request",
                        "message": str(exc),
                    },
                }
            )
        except RuntimeError as exc:
            if result_key is None:
                return self._ok(
                    {
                        "error": {
                            "code": "runtime_error",
                            "message": str(exc),
                        },
                    }
                )
            return self._ok(
                {
                    result_key: None,
                    "error": {
                        "code": "runtime_error",
                        "message": str(exc),
                    },
                }
            )
        except subprocess.TimeoutExpired as exc:
            error = {
                "code": "tool_timeout",
                "category": "infrastructure",
                "message": f"{tool_name} timed out after {exc.timeout} seconds",
            }
            if result_key is None:
                return self._ok({"error": error})
            return self._ok({result_key: None, "error": error})
        if result_key is None:
            return self._ok(result)
        return self._ok({result_key: result, "error": None})

    async def _prepare_document_disassembly(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            disassembly = self.document_tools.prepare_document_disassembly(
                source_path=request.get("source_path"),
                source_type=request.get("source_type", "pdf"),
                max_pages=request.get("max_pages"),
                page_range=request.get("page_range"),
                resume_token=request.get("resume_token"),
            )
        except ValueError as exc:
            return self._ok(
                {
                    "disassembly": None,
                    "error": {
                        "code": "invalid_request",
                        "message": str(exc),
                    },
                }
            )
        except RuntimeError as exc:
            return self._ok(
                {
                    "disassembly": None,
                    "error": {
                        "code": "runtime_error",
                        "message": str(exc),
                    },
                }
            )
        except subprocess.TimeoutExpired as exc:
            return self._ok(
                {
                    "disassembly": None,
                    "error": {
                        "code": "tool_timeout",
                        "category": "infrastructure",
                        "message": f"document disassembly timed out after {exc.timeout} seconds",
                    },
                }
            )
        payload = {"disassembly": disassembly, "error": None}
        if isinstance(disassembly, dict) and disassembly.get("error") is not None:
            payload["error"] = disassembly["error"]
        if self.memory_os_runtime is not None and isinstance(disassembly, dict):
            payload["job"] = self.memory_os_runtime.record_document_disassembly_job(
                disassembly,
                request=request,
            )
        return self._ok(payload)

    def _memory_os_source_import_job(self, request: dict[str, Any]) -> dict[str, Any]:
        source_ref = request.get("source_ref")
        if not isinstance(source_ref, dict):
            return self._error(400, "invalid_request", "source_ref must be an object")
        source_type = _optional_text(request.get("source_type"))
        if not source_type:
            return self._error(400, "invalid_request", "source_type is required")
        connector_id = _optional_text(request.get("connector_id")) or "manual"
        return self._ok(
            self._runtime().prepare_source_import_job(
                source_ref=source_ref,
                source_type=source_type,
                connector_id=connector_id,
            )
        )

    async def _list_source_drafts(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            payload = self.source_intake_manager.list_source_drafts(
                project=request.get("project"),
                status=request.get("status"),
                limit=request.get("limit", 50),
                offset=request.get("offset", 0),
            )
        except RuntimeError as exc:
            payload = {
                "count": 0,
                "drafts": [],
                "error": {
                    "code": "runtime_error",
                    "message": str(exc),
                },
            }
        return self._ok(payload)

    async def _discard_source_draft(self, request: dict[str, Any]) -> dict[str, Any]:
        draft_id = str(request.get("draft_id") or "").strip()
        if not draft_id:
            return self._ok(
                {
                    "discarded": False,
                    "draft_id": draft_id,
                    "error": {
                        "code": "invalid_request",
                        "message": "draft_id is required",
                    },
                }
            )
        try:
            payload = self.source_intake_manager.discard_source_draft(draft_id)
        except RuntimeError as exc:
            payload = {
                "discarded": False,
                "draft_id": draft_id,
                "error": {
                    "code": "runtime_error",
                    "message": str(exc),
                },
            }
        return self._ok(payload)

    async def _store_prepared_memory(self, request: dict[str, Any]) -> dict[str, Any]:
        draft_id = str(request.get("draft_id") or "").strip()
        if not draft_id:
            return self._ok(
                {
                    "stored_count": 0,
                    "stored": [],
                    "skipped": [],
                    "error": {
                        "code": "invalid_request",
                        "message": "draft_id is required",
                    },
                }
            )
        draft = self.source_intake_manager.get_source_draft(draft_id)
        if draft is None:
            return self._ok(
                {
                    "stored_count": 0,
                    "stored": [],
                    "skipped": [],
                    "error": {
                        "code": "not_found",
                        "message": f"source draft not found: {draft_id}",
                    },
                }
            )
        if draft.get("status") == "rejected":
            return self._ok(
                {
                    "stored_count": 0,
                    "stored": [],
                    "skipped": [],
                    "error": {
                        "code": "invalid_state",
                        "message": "source draft is rejected and cannot be promoted",
                    },
                }
            )

        proposed_memories = draft.get("proposed_memories", [])
        requested_indices = request.get("selected_items")
        indices = (
            requested_indices
            if isinstance(requested_indices, list)
            else list(range(len(proposed_memories)))
        )
        force = bool(request.get("force", False))
        stored: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []

        for index in indices:
            if not isinstance(index, int) or index < 0 or index >= len(proposed_memories):
                skipped.append({"index": index, "reason": "invalid_index"})
                continue
            memory = proposed_memories[index]
            try:
                result = await self.memory_manager.store_memory_async(
                    key=memory["key"],
                    content=memory["content"],
                    tags=memory.get("tags", []),
                    title=memory.get("title"),
                    related_to=memory.get("related_to"),
                    force=force,
                    project=memory.get("project"),
                    domain=memory.get("domain"),
                    status=memory.get("status"),
                    canonical=memory.get("canonical"),
                )
            except DuplicateMemoryError as exc:
                skipped.append(
                    {
                        "index": index,
                        "key": memory.get("key"),
                        "reason": "duplicate",
                        "message": str(exc),
                    }
                )
                continue
            stored.append({"index": index, "key": memory["key"], "result": result})

        return self._ok(
            {
                "stored_count": len(stored),
                "stored": stored,
                "skipped": skipped,
                "error": None,
            }
        )

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
        if self.memory_os_runtime is not None:
            return self._ok(self.memory_os_runtime.check_duplicate(key, content))
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
        if self.memory_os_runtime is not None:
            try:
                return self._ok(self.memory_os_runtime.update_memory_metadata(key, **changes))
            except ValueError as exc:
                return self._error(400, "invalid_request", str(exc))
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
        if self.memory_os_runtime is not None:
            return self._ok(self.memory_os_runtime.repair_memory_metadata(keys, dry_run=dry_run))
        payload = await self.memory_manager.repair_memory_metadata_async(keys, dry_run=dry_run)
        payload["error"] = None
        return self._ok(payload)

    async def _delete_memory(self, request: dict[str, Any]) -> dict[str, Any]:
        key = str(request.get("key") or "").strip()
        if not key:
            return self._error(400, "invalid_request", "key is required")
        if self.memory_os_runtime is not None:
            return self._ok(self.memory_os_runtime.delete_memory(key))
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

    def _runtime(self) -> MemoryOSRuntime:
        if self.memory_os_runtime is None:
            self.memory_os_runtime = MemoryOSRuntime(_memory_os_root())
            self.memory_os_runtime.initialize()
        return self.memory_os_runtime


def _memory_os_root() -> Path:
    data_root = os.environ.get("ENGRAM_DATA_DIR", "").strip()
    if data_root:
        return Path(data_root) / "memory_os"
    return Path(__file__).resolve().parents[1] / "data" / "memory_os"


def _bounded_query_int(
    query: dict[str, list[str]],
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw_value = (query.get(name) or [default])[0]
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


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
