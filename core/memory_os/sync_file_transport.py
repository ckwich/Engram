"""File-bundle transport helpers for encrypted Memory OS sync changesets."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.memory_os.sync_transport import store_inbound_sync_bundle


def export_bundle_to_file(runtime: Any, bundle: bytes, destination: str | Path) -> Path:
    """Write encrypted bundle bytes to a caller-selected file path."""
    if not isinstance(bundle, bytes):
        raise TypeError("bundle must be bytes")
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bundle)
    return path


def import_bundle_from_file(runtime: Any, source: str | Path) -> dict[str, Any]:
    """Store encrypted bundle bytes from a file as inbound transport evidence."""
    path = Path(source)
    bundle = path.read_bytes()
    return store_inbound_sync_bundle(
        runtime,
        bundle,
        {"transport_type": "file_bundle", "source_path": str(path)},
    )
