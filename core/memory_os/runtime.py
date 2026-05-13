"""Daemon-owned Memory OS service container."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from core.memory_os.content_store import ContentAddressedStore
from core.memory_os.firewall import MemoryFirewall
from core.memory_os.graph import MemoryOSGraph
from core.memory_os.inspector import build_memory_os_inspector
from core.memory_os.jobs import JobQueue
from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.retrieval import MemoryOSRetrievalIndex
from core.memory_os.snapshots import SnapshotService
from core.memory_os.transactions import MemoryTransactionService


class MemoryOSRuntime:
    """Container for daemon-owned Memory OS stores, indexes, and services."""

    def __init__(
        self,
        root: str | Path,
        *,
        embed_text: Callable[[str], list[float]] | None = None,
        vector_index: Any | None = None,
        graph_store: Any | None = None,
    ) -> None:
        self.root = Path(root)
        self.ledger = MemoryOSLedger(self.root / "ledger.sqlite3")
        self.content_store = ContentAddressedStore(self.root / "objects")
        self.jobs = JobQueue(self.ledger)
        self.transactions = MemoryTransactionService(self.ledger)
        self.snapshots = SnapshotService(self.ledger)
        self.firewall = MemoryFirewall(self.ledger)
        self.retrieval = MemoryOSRetrievalIndex(
            self.ledger,
            self.root / "lance",
            embed_text=embed_text or _default_embed_text,
            vector_index=vector_index,
        )
        self.graph = MemoryOSGraph(
            self.ledger,
            graph_store=graph_store,
            database_path=self.root / "kuzu",
        )

    def initialize(self) -> dict[str, Any]:
        """Initialize durable Memory OS stores and return a status payload."""
        self.ledger.initialize()
        self.content_store.root.mkdir(parents=True, exist_ok=True)
        self.graph.load_edges()
        return self.status()

    def status(self) -> dict[str, Any]:
        """Return a compact Memory OS component status."""
        return {
            "status": "ok",
            "root": str(self.root),
            "components": {
                "ledger": {
                    "path": str(self.ledger.path),
                    "exists": self.ledger.path.exists(),
                },
                "content_store": {
                    "path": str(self.content_store.root),
                    "exists": self.content_store.root.exists(),
                },
                "retrieval": {
                    "backend": type(self.retrieval.vector_index).__name__,
                    "path": str(self.root / "lance"),
                },
                "graph": {
                    "backend": type(self.graph.graph_store).__name__,
                    "path": str(self.root / "kuzu"),
                },
                "jobs": {"status": "ready"},
                "transactions": {"status": "ready"},
                "snapshots": {"status": "ready"},
                "firewall": {"status": "ready"},
            },
        }

    def inspector(self, *, limit: int = 20) -> dict[str, Any]:
        """Return a read-only Memory OS inspector payload."""
        return build_memory_os_inspector(self, limit=limit)

    def prepare_source_import_job(
        self,
        *,
        source_ref: dict[str, Any],
        source_type: str,
        connector_id: str = "manual",
    ) -> dict[str, Any]:
        """Create a queued source import job without blocking an MCP process."""
        return self.jobs.enqueue(
            "source_import",
            {
                "source_ref": source_ref,
                "source_type": source_type,
                "connector_id": connector_id,
            },
        )


def _default_embed_text(text: str) -> list[float]:
    from core.embedder import embedder

    return list(embedder.embed(text))
