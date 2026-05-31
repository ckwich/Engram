"""Explicit data gateway for Engram's Flask WebUI routes."""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from core.engramd_client import EngramDaemonClient
from core.memory_os.runtime import MemoryOSRuntime
from core.memory_os.runtime_paths import memory_os_root_for_data_root, resolve_data_root


_MEMORY_OS_RUNTIME: MemoryOSRuntime | None = None


def default_daemon_url() -> str:
    """Return the configured daemon URL, normalized for client calls."""
    return os.environ.get("ENGRAM_DAEMON_URL", "").strip().rstrip("/")


def default_memory_os_runtime() -> MemoryOSRuntime:
    """Return a direct Memory OS runtime for local single-process WebUI mode."""
    global _MEMORY_OS_RUNTIME
    if _MEMORY_OS_RUNTIME is None:
        root = memory_os_root_for_data_root(resolve_data_root())
        _MEMORY_OS_RUNTIME = MemoryOSRuntime(root)
        _MEMORY_OS_RUNTIME.initialize()
    return _MEMORY_OS_RUNTIME


class WebUIDataGateway:
    """Route WebUI reads/writes through explicit storage owners."""

    def __init__(
        self,
        *,
        memory_manager: Any,
        daemon_url_provider: Callable[[], str] = default_daemon_url,
        memory_os_runtime_provider: Callable[[], MemoryOSRuntime] = default_memory_os_runtime,
        daemon_client_factory: Callable[[str], EngramDaemonClient] = EngramDaemonClient,
        retrieval_eval_runner: Callable[[Any], dict[str, Any]] | None = None,
    ) -> None:
        self.memory_manager = memory_manager
        self.daemon_url_provider = daemon_url_provider
        self.memory_os_runtime_provider = memory_os_runtime_provider
        self.daemon_client_factory = daemon_client_factory
        self.retrieval_eval_runner = retrieval_eval_runner

    def create_memory(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a legacy-compatible memory through the configured manager."""
        return self.memory_manager.store_memory(
            key=data["key"],
            content=data["content"],
            tags=_normalize_list_field(data.get("tags")),
            title=data.get("title"),
            related_to=_normalize_list_field(data.get("related_to")),
            force=bool(data.get("force", False)),
        )

    def update_memory(self, key: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update a legacy-compatible memory through the configured manager."""
        return self.memory_manager.store_memory(
            key=key,
            content=data["content"],
            tags=_normalize_list_field(data.get("tags")),
            title=data.get("title"),
            related_to=_normalize_list_field(data.get("related_to")),
            force=bool(data.get("force", False)),
        )

    def delete_memory(self, key: str) -> bool:
        """Delete a memory through the configured manager."""
        return bool(self.memory_manager.delete_memory(key))

    def mark_memory_reviewed(self, key: str, *, stale_type: str) -> dict[str, Any] | None:
        """Mark a stale memory as reviewed through the configured manager."""
        return self.memory_manager.mark_memory_reviewed(key, stale_type=stale_type)

    def run_retrieval_eval(self) -> dict[str, Any]:
        """Run retrieval eval through the configured runner."""
        if self.retrieval_eval_runner is None:
            raise RuntimeError("retrieval eval runner is not configured")
        return self.retrieval_eval_runner(self.memory_manager)

    def memory_os_inspector(self, *, limit: int = 20) -> dict[str, Any]:
        """Return Memory OS inspector payload through daemon or direct runtime."""
        daemon_url = self.daemon_url_provider()
        if daemon_url:
            return self.daemon_client_factory(daemon_url).memory_os_inspector(limit=limit)
        return self.memory_os_runtime_provider().inspector(limit=limit)

    def apply_document_promotion(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Apply reviewed document promotion through daemon or direct runtime."""
        daemon_url = self.daemon_url_provider()
        if daemon_url:
            return self.daemon_client_factory(daemon_url).apply_document_promotion_transaction(payload)
        return self.memory_os_runtime_provider().apply_document_promotion_transaction(
            payload["document_promotion_transaction"],
            accept=payload.get("accept") is True,
            approved_by=payload.get("approved_by"),
            selected_operation_indexes=payload.get("selected_operation_indexes"),
        )


def _normalize_list_field(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []
