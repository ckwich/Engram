"""Portable Memory OS passport export and restore helpers."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from core.memory_os._migration_bridge import bundle_file_path, migration_kernel_for
from core.memory_os.content_store import ContentAddressedStore
from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.schema import SCHEMA_VERSION
from core.memory_os_migration import MemoryOSMigrationKernel


def export_memory_passport(
    ledger: MemoryOSLedger,
    store: ContentAddressedStore,
    target: str | Path,
) -> dict[str, Any]:
    """Export a portable Memory OS passport from the migration-compatible store."""
    kernel = migration_kernel_for(ledger, store)
    bundle = kernel.export_bundle()
    path = bundle_file_path(target)
    _write_json(path, bundle)
    artifact_ids = [
        str(item["artifact_sha256"])
        for item in bundle.get("memories", [])
        if isinstance(item, dict) and item.get("artifact_sha256")
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "bundle_schema_version": bundle.get("schema_version"),
        "bundle_path": str(path),
        "memory_count": int(bundle.get("memory_count", 0)),
        "graph_edge_count": len(bundle.get("graph_edges", [])),
        "document_evidence_count": int(bundle.get("document_evidence_count", 0)),
        "artifact_ids": artifact_ids,
    }


def restore_memory_passport(bundle: str | Path, target_root: str | Path) -> dict[str, Any]:
    """Restore a Memory OS passport into a clean migration-compatible store root."""
    path = bundle_file_path(bundle)
    payload = json.loads(path.read_text(encoding="utf-8"))
    report = MemoryOSMigrationKernel(target_root).restore_bundle(payload)
    return {
        **report,
        "schema_version": SCHEMA_VERSION,
        "migration_schema_version": report.get("schema_version"),
        "bundle_schema_version": payload.get("schema_version"),
        "bundle_path": str(path),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    encoded = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
