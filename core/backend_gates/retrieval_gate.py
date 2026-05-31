from __future__ import annotations

from pathlib import Path
from typing import Any

from core.backend_gates.parity_report import build_backend_gate_report
from core.retrieval_backend_status import DependencyProbe, build_retrieval_backend_status


def build_retrieval_backend_gate(
    *,
    store_root: str | Path | None = None,
    include_rebuild_probe: bool = False,
    rebuild_batch_size: int = 128,
    dependency_probe: DependencyProbe | None = None,
    status_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Wrap retrieval_backend_status in a single executable default-switch gate."""
    status = status_payload or build_retrieval_backend_status(
        store_root=store_root,
        include_rebuild_probe=include_rebuild_probe,
        rebuild_batch_size=rebuild_batch_size,
        dependency_probe=dependency_probe,
    )
    return build_backend_gate_report(
        backend="retrieval",
        source_status=status,
        source_operation="retrieval_backend_status",
        live_changed_field="live_retrieval_changed",
        parity_probe_field="golden_comparison_probe",
    )
