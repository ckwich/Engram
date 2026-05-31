"""Legacy JSON import boundary for the rebuilt Memory OS package."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.memory_os._migration_bridge import migration_kernel_for
from core.memory_os.content_store import ContentAddressedStore
from core.memory_os.ledger import MemoryOSLedger


def import_legacy_memory_dir(
    memory_dir: str | Path,
    ledger: MemoryOSLedger,
    store: ContentAddressedStore,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Import legacy JSON memories through the proven migration kernel."""
    kernel = migration_kernel_for(ledger, store)
    return kernel.import_legacy_json(memory_dir, dry_run=dry_run)
