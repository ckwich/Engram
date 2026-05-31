"""Restore-grade runtime snapshots for daemon-owned Memory OS state."""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.memory_os.runtime_paths import (
    LEDGER_FILENAME,
    inspect_ledger,
    validate_memory_os_preflight,
)


RUNTIME_SNAPSHOT_SCHEMA_VERSION = "2026-05-26.runtime-snapshot.v1"
SNAPSHOT_MANIFEST_FILENAME = "SNAPSHOT_MANIFEST.json"


class RuntimeSnapshotError(RuntimeError):
    """Raised when a restore-grade runtime snapshot cannot be created or verified."""


def create_verified_runtime_snapshot(
    memory_os_root: str | Path,
    *,
    snapshot_parent: str | Path | None = None,
    created_by: str,
) -> dict[str, Any]:
    """Copy the durable ledger and content objects into a verified restore-grade snapshot."""
    root = Path(memory_os_root).expanduser().resolve()
    preflight = validate_memory_os_preflight(root, allow_unsafe_paths=True)
    if preflight["ledger"]["exists"] is not True:
        raise RuntimeSnapshotError("cannot snapshot Memory OS runtime without an existing ledger")
    if preflight["ledger"].get("quick_check") != "ok":
        raise RuntimeSnapshotError("cannot snapshot malformed ledger")

    parent = (
        Path(snapshot_parent).expanduser().resolve()
        if snapshot_parent is not None
        else (root.parent / "backups" / "runtime_snapshots").resolve()
    )
    _ensure_snapshot_not_inside_runtime(root, parent)
    parent.mkdir(parents=True, exist_ok=True)

    created_at = _now_iso()
    snapshot_id = f"runtime-snapshot-{created_at.replace('-', '').replace(':', '').replace('+0000', 'Z')}"
    snapshot_dir = parent / snapshot_id
    if snapshot_dir.exists():
        raise RuntimeSnapshotError(f"snapshot already exists: {snapshot_dir}")
    snapshot_dir.mkdir(parents=True)

    try:
        ledger_dest = snapshot_dir / LEDGER_FILENAME
        _copy_sqlite_ledger(root / LEDGER_FILENAME, ledger_dest)
        ledger_report = inspect_ledger(ledger_dest)
        if ledger_report.get("quick_check") != "ok":
            raise RuntimeSnapshotError("copied runtime ledger failed quick_check")

        objects_source = root / "objects"
        objects_dest = snapshot_dir / "objects"
        if objects_source.exists():
            shutil.copytree(objects_source, objects_dest)
        else:
            objects_dest.mkdir()

        manifest = {
            "schema_version": RUNTIME_SNAPSHOT_SCHEMA_VERSION,
            "snapshot_id": snapshot_id,
            "snapshot_kind": "runtime_restore",
            "restore_grade": True,
            "rollback_supported": True,
            "created_at": created_at,
            "created_by": created_by,
            "source_memory_os_root": str(root),
            "snapshot_path": str(snapshot_dir),
            "source_preflight": preflight,
            "ledger": {
                "path": LEDGER_FILENAME,
                "size_bytes": _file_size(ledger_dest),
                "sha256": _sha256_file(ledger_dest),
                "quick_check": ledger_report.get("quick_check"),
                "tables": ledger_report.get("tables", {}),
            },
            "objects": _directory_digest(objects_dest),
            "rebuildable_indexes_excluded": ["lance", "kuzu", "chroma"],
            "restore_guidance": (
                "Restore by replacing the Memory OS ledger and objects directory from this "
                "snapshot, then rebuild LanceDB and Kuzu indexes from the ledger."
            ),
        }
        _write_json(snapshot_dir / SNAPSHOT_MANIFEST_FILENAME, manifest)
        verification = verify_runtime_snapshot(snapshot_dir)
        if verification.get("status") != "ok":
            raise RuntimeSnapshotError(f"snapshot verification failed: {verification.get('error')}")
        return _snapshot_summary(manifest, verification=verification)
    except Exception:
        shutil.rmtree(snapshot_dir, ignore_errors=True)
        raise


def verify_runtime_snapshot(snapshot_path: str | Path) -> dict[str, Any]:
    """Verify a restore-grade runtime snapshot manifest, ledger, and content tree."""
    root = Path(snapshot_path).expanduser().resolve()
    manifest_path = root / SNAPSHOT_MANIFEST_FILENAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _verification_error(root, f"invalid snapshot manifest: {exc}")
    if not isinstance(manifest, dict):
        return _verification_error(root, "snapshot manifest must be a JSON object")
    if manifest.get("schema_version") != RUNTIME_SNAPSHOT_SCHEMA_VERSION:
        return _verification_error(root, "unsupported snapshot schema version")
    if manifest.get("restore_grade") is not True:
        return _verification_error(root, "snapshot is not restore-grade")

    ledger_path = root / str((manifest.get("ledger") or {}).get("path") or LEDGER_FILENAME)
    if not ledger_path.exists():
        return _verification_error(root, "snapshot ledger is missing")
    expected_ledger_hash = (manifest.get("ledger") or {}).get("sha256")
    if expected_ledger_hash and _sha256_file(ledger_path) != expected_ledger_hash:
        return _verification_error(root, "snapshot ledger checksum mismatch")
    ledger_report = inspect_ledger(ledger_path)
    if ledger_report.get("quick_check") != "ok":
        return _verification_error(root, "snapshot ledger failed quick_check")

    expected_objects = manifest.get("objects") or {}
    current_objects = _directory_digest(root / "objects")
    if current_objects.get("tree_hash") != expected_objects.get("tree_hash"):
        return _verification_error(root, "snapshot object tree checksum mismatch")
    return {
        "schema_version": "2026-05-26.runtime-snapshot-verification.v1",
        "status": "ok",
        "snapshot_path": str(root),
        "snapshot_id": manifest.get("snapshot_id"),
        "ledger": {
            "quick_check": ledger_report.get("quick_check"),
            "sha256": expected_ledger_hash,
            "tables": ledger_report.get("tables", {}),
        },
        "objects": current_objects,
        "error": None,
    }


def _copy_sqlite_ledger(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True, timeout=30.0)
    try:
        dest_conn = sqlite3.connect(destination, timeout=30.0)
        try:
            source_conn.backup(dest_conn)
            dest_conn.commit()
        finally:
            dest_conn.close()
    finally:
        source_conn.close()


def _directory_digest(root: Path) -> dict[str, Any]:
    if not root.exists():
        return {
            "path": root.name,
            "exists": False,
            "file_count": 0,
            "total_bytes": 0,
            "tree_hash": _sha256_bytes(b""),
        }
    records: list[dict[str, Any]] = []
    total_bytes = 0
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        size = _file_size(path)
        total_bytes += size
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": size,
                "sha256": _sha256_file(path),
            }
        )
    return {
        "path": root.name,
        "exists": True,
        "file_count": len(records),
        "total_bytes": total_bytes,
        "tree_hash": _sha256_json(records),
    }


def _snapshot_summary(manifest: dict[str, Any], *, verification: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": manifest["schema_version"],
        "snapshot_id": manifest["snapshot_id"],
        "snapshot_kind": manifest["snapshot_kind"],
        "restore_grade": manifest["restore_grade"],
        "rollback_supported": manifest["rollback_supported"],
        "created_at": manifest["created_at"],
        "created_by": manifest["created_by"],
        "snapshot_path": manifest["snapshot_path"],
        "source_memory_os_root": manifest["source_memory_os_root"],
        "source_preflight": manifest.get("source_preflight"),
        "ledger": manifest["ledger"],
        "objects": manifest["objects"],
        "rebuildable_indexes_excluded": manifest["rebuildable_indexes_excluded"],
        "verification": verification,
    }


def _ensure_snapshot_not_inside_runtime(runtime_root: Path, snapshot_parent: Path) -> None:
    try:
        snapshot_parent.relative_to(runtime_root)
    except ValueError:
        return
    raise RuntimeSnapshotError("snapshot destination must not be inside the Memory OS runtime root")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp_path.replace(path)


def _verification_error(snapshot_path: Path, message: str) -> dict[str, Any]:
    return {
        "schema_version": "2026-05-26.runtime-snapshot-verification.v1",
        "status": "error",
        "snapshot_path": str(snapshot_path),
        "error": message,
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _file_size(path: Path) -> int:
    return int(path.stat().st_size)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _sha256_json(payload: Any) -> str:
    return _sha256_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()
