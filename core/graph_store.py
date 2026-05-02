from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Protocol

PROJECT_ROOT = Path(__file__).parent.parent
GRAPH_DIR = PROJECT_ROOT / "data" / "graph"
EDGES_PATH = GRAPH_DIR / "edges.json"
GRAPH_SCHEMA_VERSION = "2026-04-27"


class GraphStore(Protocol):
    """Persistence boundary for graph edge documents."""

    def load_graph(self) -> dict[str, Any]:
        """Load the graph document."""
        ...

    def save_graph(self, graph: dict[str, Any]) -> None:
        """Persist the graph document."""
        ...


def empty_graph() -> dict[str, Any]:
    return {"schema_version": GRAPH_SCHEMA_VERSION, "edges": []}


class JsonGraphStore:
    """JSON-backed graph store kept as the local-first default backend."""

    def __init__(self, edges_path: str | Path = EDGES_PATH) -> None:
        self.edges_path = Path(edges_path)
        self._edges_cache: dict[str, Any] | None = None

    def load_graph(self) -> dict[str, Any]:
        if self._edges_cache is not None:
            return self._edges_cache
        if not self.edges_path.exists():
            self._edges_cache = empty_graph()
            return self._edges_cache
        graph = json.loads(self.edges_path.read_text(encoding="utf-8"))
        if not isinstance(graph, dict):
            graph = empty_graph()
        graph.setdefault("schema_version", GRAPH_SCHEMA_VERSION)
        graph.setdefault("edges", [])
        self._edges_cache = graph
        return graph

    def save_graph(self, graph: dict[str, Any]) -> None:
        graph_dir = self.edges_path.parent
        graph_dir.mkdir(parents=True, exist_ok=True)
        graph["schema_version"] = GRAPH_SCHEMA_VERSION
        fd, temp_name = tempfile.mkstemp(prefix="edges.", suffix=".tmp", dir=graph_dir)
        temp_path = Path(temp_name)
        try:
            with open(fd, "w", encoding="utf-8") as handle:
                json.dump(graph, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            temp_path.replace(self.edges_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
        self._edges_cache = graph

    def clear_cache(self) -> None:
        self._edges_cache = None
