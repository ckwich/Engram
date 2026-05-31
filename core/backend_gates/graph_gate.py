from __future__ import annotations

from pathlib import Path
from typing import Any

from core.backend_gates.parity_report import build_backend_gate_report
from core.graph_backend_status import DependencyProbe, build_graph_backend_status
from core.graph_store import EDGES_PATH


def build_graph_backend_gate(
    *,
    store_root: str | Path | None = None,
    graph_path: str | Path | None = EDGES_PATH,
    dependency_probe: DependencyProbe | None = None,
    status_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Wrap graph_backend_status in a single executable default-switch gate."""
    status = status_payload or build_graph_backend_status(
        store_root=store_root,
        graph_path=graph_path,
        dependency_probe=dependency_probe,
    )
    return build_backend_gate_report(
        backend="graph",
        source_status=status,
        source_operation="graph_backend_status",
        live_changed_field="live_graph_backend_changed",
        parity_probe_field="graph_parity_probe",
    )
