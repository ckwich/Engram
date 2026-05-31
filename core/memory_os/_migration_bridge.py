"""Compatibility bridge from Memory OS package APIs to the proven migration kernel."""
from __future__ import annotations

from pathlib import Path

from core.memory_os.content_store import ContentAddressedStore
from core.memory_os.ledger import MemoryOSLedger
from core.memory_os_migration import LEDGER_FILENAME, MemoryOSMigrationKernel


def migration_kernel_for(
    ledger: MemoryOSLedger,
    store: ContentAddressedStore,
) -> MemoryOSMigrationKernel:
    """Return the migration kernel that owns the supplied ledger/store pair."""
    expected_ledger = ledger.path.parent / LEDGER_FILENAME
    expected_objects = ledger.path.parent / "objects"
    if ledger.path.resolve() != expected_ledger.resolve():
        raise ValueError(f"ledger path must end with {LEDGER_FILENAME}")
    if store.root.resolve() != expected_objects.resolve():
        raise ValueError("content store root must be the ledger sibling 'objects' directory")
    return MemoryOSMigrationKernel(ledger.path.parent)


def bundle_file_path(target: str | Path) -> Path:
    """Resolve a passport target path, accepting either a directory or JSON file."""
    path = Path(target)
    if path.suffix.lower() == ".json":
        return path
    return path / "memory_passport.json"
