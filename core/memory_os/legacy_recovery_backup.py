"""Legacy JSON/Chroma recovery backup helpers for Memory OS cutover."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "2026-05-15.legacy_recovery_backup.v1"
MANIFEST_MEMBER = "legacy_recovery_manifest.json"


def prepare_legacy_recovery_backup(
    *,
    memory_dir: str | Path,
    chroma_dir: str | Path,
    backup_dir: str | Path | None = None,
    graph_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Return a no-write checksum manifest for legacy rollback inputs."""
    stores = _collect_stores(
        memory_dir=memory_dir,
        chroma_dir=chroma_dir,
        graph_dir=graph_dir,
    )
    missing_required = [
        name for name in ("memories", "chroma") if stores[name]["missing"]
    ]
    files = [
        file_entry
        for store in ("memories", "chroma", "graph")
        for file_entry in stores[store]["files"]
    ]
    manifest = _manifest_payload(
        memory_dir=memory_dir,
        chroma_dir=chroma_dir,
        graph_dir=graph_dir,
        stores=stores,
        files=files,
    )
    return _backup_response(
        operation="prepare_legacy_recovery_backup",
        status="blocked" if missing_required else "ready",
        manifest=manifest,
        stores=stores,
        missing_required_stores=missing_required,
        backup_dir=backup_dir,
        write_performed=False,
        archive_path=None,
        manifest_path=None,
        archive_sha256=None,
    )


def write_legacy_recovery_backup(
    *,
    memory_dir: str | Path,
    chroma_dir: str | Path,
    backup_dir: str | Path,
    graph_dir: str | Path | None = None,
    accept: bool = False,
    approved_by: str | None = None,
) -> dict[str, Any]:
    """Write a legacy recovery tarball only after explicit operator acceptance."""
    prepared = prepare_legacy_recovery_backup(
        memory_dir=memory_dir,
        chroma_dir=chroma_dir,
        graph_dir=graph_dir,
        backup_dir=backup_dir,
    )
    if not accept:
        return _denied_response(prepared, "accept=True is required")
    reviewer = _optional_text(approved_by)
    if reviewer is None:
        return _denied_response(prepared, "approved_by is required")
    if prepared["status"] != "ready":
        return {
            **prepared,
            "operation": "write_legacy_recovery_backup",
            "status": "blocked",
            "denial_reason": "required legacy stores are missing",
        }

    manifest = prepared["manifest"]
    output_dir = Path(backup_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"legacy-recovery-{_timestamp_slug()}-{manifest['manifest_sha256'][:12]}"
    archive_path = output_dir / f"{stem}.tar"
    manifest_path = output_dir / f"{stem}.manifest.json"
    manifest = {
        **manifest,
        "created_at": _now_iso(),
        "approved_by": reviewer,
    }
    manifest_bytes = _pretty_json_bytes(manifest)
    _write_tar(archive_path, manifest=manifest, files=manifest["files"])
    manifest_path.write_bytes(manifest_bytes)
    archive_sha256 = _sha256_file(archive_path)
    return {
        **prepared,
        "operation": "write_legacy_recovery_backup",
        "status": "written",
        "write_performed": True,
        "archive_path": str(archive_path),
        "manifest_path": str(manifest_path),
        "archive_sha256": archive_sha256,
        "manifest": manifest,
        "approved_by": reviewer,
    }


def verify_legacy_recovery_backup(
    archive_path: str | Path,
    *,
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    """Verify a legacy recovery tarball against its checksum manifest."""
    archive = Path(archive_path)
    manifest = _load_manifest(archive, manifest_path=manifest_path)
    expected = {entry["archive_path"]: entry for entry in manifest["files"]}
    missing: list[str] = []
    mismatched: list[dict[str, str]] = []
    extra: list[str] = []
    with tarfile.open(archive, "r") as tar:
        members = {
            member.name: member
            for member in tar.getmembers()
            if member.isfile() and member.name != MANIFEST_MEMBER
        }
        for archive_member, entry in expected.items():
            member = members.get(archive_member)
            if member is None:
                missing.append(archive_member)
                continue
            raw = tar.extractfile(member)
            if raw is None:
                missing.append(archive_member)
                continue
            digest = _sha256_bytes(raw.read())
            if digest != entry["sha256"]:
                mismatched.append(
                    {
                        "archive_path": archive_member,
                        "expected_sha256": entry["sha256"],
                        "actual_sha256": digest,
                    }
                )
        extra = sorted(name for name in members if name not in expected)
    status = "verified" if not missing and not mismatched and not extra else "failed"
    return {
        "schema_version": SCHEMA_VERSION,
        "operation": "verify_legacy_recovery_backup",
        "status": status,
        "archive_path": str(archive),
        "manifest_path": str(manifest_path) if manifest_path is not None else None,
        "archive_sha256": _sha256_file(archive),
        "manifest_sha256": manifest.get("manifest_sha256"),
        "file_count": len(expected),
        "missing_entries": missing,
        "mismatched_entries": mismatched,
        "extra_entries": extra,
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
    }


def restore_legacy_recovery_backup(
    archive_path: str | Path,
    *,
    restore_root: str | Path,
    manifest_path: str | Path | None = None,
    accept: bool = False,
    approved_by: str | None = None,
) -> dict[str, Any]:
    """Restore a verified legacy recovery tarball into an empty scratch root."""
    archive = Path(archive_path)
    root = Path(restore_root)
    if not accept:
        return _restore_denied_response(archive, root, "accept=True is required")
    reviewer = _optional_text(approved_by)
    if reviewer is None:
        return _restore_denied_response(archive, root, "approved_by is required")
    if root.exists() and any(root.iterdir()):
        return _restore_denied_response(archive, root, "restore_root must be empty")

    verified = verify_legacy_recovery_backup(archive, manifest_path=manifest_path)
    if verified["status"] != "verified":
        return {
            **verified,
            "operation": "restore_legacy_recovery_backup",
            "status": "blocked",
            "restore_root": str(root),
            "denial_reason": "archive verification failed",
            "write_performed": False,
        }

    manifest = _load_manifest(archive, manifest_path=manifest_path)
    root.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r") as tar:
        for entry in manifest["files"]:
            member_name = entry["archive_path"]
            target = _safe_restore_target(root, member_name)
            target.parent.mkdir(parents=True, exist_ok=True)
            raw = tar.extractfile(member_name)
            if raw is None:
                raise ValueError(f"missing archive member during restore: {member_name}")
            target.write_bytes(raw.read())

    restored = _verify_restored_files(root, manifest["files"])
    return {
        "schema_version": SCHEMA_VERSION,
        "operation": "restore_legacy_recovery_backup",
        "status": "restored" if not restored["mismatched_entries"] else "failed",
        "archive_path": str(archive),
        "restore_root": str(root),
        "approved_by": reviewer,
        "restored_file_count": restored["restored_file_count"],
        "mismatched_entries": restored["mismatched_entries"],
        "write_performed": True,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
    }


def _collect_stores(
    *,
    memory_dir: str | Path,
    chroma_dir: str | Path,
    graph_dir: str | Path | None,
) -> dict[str, dict[str, Any]]:
    configured = {
        "memories": Path(memory_dir),
        "chroma": Path(chroma_dir),
        "graph": Path(graph_dir) if graph_dir is not None else None,
    }
    stores: dict[str, dict[str, Any]] = {}
    for name, path in configured.items():
        if path is None:
            stores[name] = _store_report(name, None, [])
            continue
        files = _file_entries(name, path)
        stores[name] = _store_report(name, path, files)
    return stores


def _store_report(
    name: str,
    path: Path | None,
    files: list[dict[str, Any]],
) -> dict[str, Any]:
    exists = path is not None and path.is_dir()
    return {
        "name": name,
        "path": str(path) if path is not None else None,
        "exists": exists,
        "missing": not exists,
        "file_count": len(files),
        "json_file_count": sum(1 for entry in files if entry["relative_path"].endswith(".json")),
        "total_bytes": sum(int(entry["size"]) for entry in files),
        "files": files,
    }


def _file_entries(store: str, root: Path) -> list[dict[str, Any]]:
    if not root.is_dir():
        return []
    entries: list[dict[str, Any]] = []
    resolved_root = root.resolve()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if not _safe_store_file(resolved_root, path):
            continue
        relative_path = path.relative_to(root).as_posix()
        entries.append(
            {
                "store": store,
                "source_path": str(path),
                "relative_path": relative_path,
                "archive_path": f"{store}/{relative_path}",
                "size": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return entries


def _manifest_payload(
    *,
    memory_dir: str | Path,
    chroma_dir: str | Path,
    graph_dir: str | Path | None,
    stores: dict[str, dict[str, Any]],
    files: list[dict[str, Any]],
) -> dict[str, Any]:
    compact_files = [
        {
            "store": entry["store"],
            "relative_path": entry["relative_path"],
            "archive_path": entry["archive_path"],
            "size": entry["size"],
            "sha256": entry["sha256"],
            "source_path": entry["source_path"],
        }
        for entry in files
    ]
    manifest_core = {
        "schema_version": SCHEMA_VERSION,
        "operation": "legacy_recovery_backup",
        "source_stores": {
            "memories": str(Path(memory_dir)),
            "chroma": str(Path(chroma_dir)),
            "graph": str(Path(graph_dir)) if graph_dir is not None else None,
        },
        "store_counts": {
            name: {
                "exists": report["exists"],
                "file_count": report["file_count"],
                "json_file_count": report["json_file_count"],
                "total_bytes": report["total_bytes"],
            }
            for name, report in stores.items()
        },
        "file_count": len(compact_files),
        "total_bytes": sum(int(entry["size"]) for entry in compact_files),
        "files": compact_files,
    }
    return {
        **manifest_core,
        "manifest_sha256": _sha256_json(manifest_core),
    }


def _backup_response(
    *,
    operation: str,
    status: str,
    manifest: dict[str, Any],
    stores: dict[str, dict[str, Any]],
    missing_required_stores: list[str],
    backup_dir: str | Path | None,
    write_performed: bool,
    archive_path: str | None,
    manifest_path: str | None,
    archive_sha256: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "operation": operation,
        "status": status,
        "write_policy": "explicit_acceptance" if operation.startswith("write") else "no_write",
        "backup_dir": str(backup_dir) if backup_dir is not None else None,
        "archive_path": archive_path,
        "manifest_path": manifest_path,
        "archive_sha256": archive_sha256,
        "manifest_sha256": manifest["manifest_sha256"],
        "file_count": manifest["file_count"],
        "total_bytes": manifest["total_bytes"],
        "stores": {
            name: {key: value for key, value in report.items() if key != "files"}
            for name, report in stores.items()
        },
        "missing_required_stores": missing_required_stores,
        "manifest": manifest,
        "write_performed": write_performed,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
    }


def _denied_response(prepared: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        **prepared,
        "operation": "write_legacy_recovery_backup",
        "status": "denied",
        "write_policy": "explicit_acceptance",
        "denial_reason": reason,
        "write_performed": False,
    }


def _restore_denied_response(archive: Path, root: Path, reason: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "operation": "restore_legacy_recovery_backup",
        "status": "denied",
        "archive_path": str(archive),
        "restore_root": str(root),
        "denial_reason": reason,
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
    }


def _write_tar(
    archive_path: Path,
    *,
    manifest: dict[str, Any],
    files: list[dict[str, Any]],
) -> None:
    manifest_bytes = _pretty_json_bytes(manifest)
    with tarfile.open(archive_path, "w") as tar:
        _add_bytes_member(tar, MANIFEST_MEMBER, manifest_bytes)
        for entry in sorted(files, key=lambda item: item["archive_path"]):
            _add_file_member(tar, entry["archive_path"], Path(entry["source_path"]))


def _add_file_member(tar: tarfile.TarFile, archive_name: str, source: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"refusing to archive non-regular legacy backup source: {source}")
    info = tarfile.TarInfo(archive_name)
    info.size = source.stat().st_size
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    with source.open("rb") as handle:
        tar.addfile(info, handle)


def _add_bytes_member(tar: tarfile.TarFile, archive_name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(archive_name)
    info.size = len(payload)
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    tar.addfile(info, io.BytesIO(payload))


def _load_manifest(
    archive_path: Path,
    *,
    manifest_path: str | Path | None,
) -> dict[str, Any]:
    if manifest_path is not None:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    else:
        with tarfile.open(archive_path, "r") as tar:
            raw = tar.extractfile(MANIFEST_MEMBER)
            if raw is None:
                raise ValueError("backup archive is missing legacy recovery manifest")
            manifest = json.loads(raw.read().decode("utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported legacy recovery backup manifest")
    return manifest


def _verify_restored_files(
    restore_root: Path,
    files: list[dict[str, Any]],
) -> dict[str, Any]:
    mismatched: list[dict[str, str]] = []
    restored = 0
    for entry in files:
        target = _safe_restore_target(restore_root, entry["archive_path"])
        if not target.is_file():
            mismatched.append(
                {
                    "archive_path": entry["archive_path"],
                    "expected_sha256": entry["sha256"],
                    "actual_sha256": "<missing>",
                }
            )
            continue
        restored += 1
        digest = _sha256_file(target)
        if digest != entry["sha256"]:
            mismatched.append(
                {
                    "archive_path": entry["archive_path"],
                    "expected_sha256": entry["sha256"],
                    "actual_sha256": digest,
                }
            )
    return {"restored_file_count": restored, "mismatched_entries": mismatched}


def _safe_restore_target(root: Path, archive_member: str) -> Path:
    target = root / archive_member
    resolved_root = root.resolve()
    resolved_target = target.resolve()
    if resolved_root != resolved_target and resolved_root not in resolved_target.parents:
        raise ValueError(f"unsafe archive path: {archive_member}")
    return target


def _safe_store_file(resolved_root: Path, path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    try:
        path.resolve().relative_to(resolved_root)
    except ValueError:
        return False
    return True


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _pretty_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_report(report_path: str | Path | None, payload: dict[str, Any]) -> None:
    if report_path is None:
        return
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_pretty_json_bytes(payload))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare, write, verify, and restore legacy JSON/Chroma recovery backups.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    _add_source_args(prepare)

    write = subparsers.add_parser("write")
    _add_source_args(write)
    write.add_argument("--accept", action="store_true")
    write.add_argument("--approved-by")

    verify = subparsers.add_parser("verify")
    verify.add_argument("--archive", required=True)
    verify.add_argument("--manifest")
    verify.add_argument("--report")

    restore = subparsers.add_parser("restore")
    restore.add_argument("--archive", required=True)
    restore.add_argument("--manifest")
    restore.add_argument("--restore-root", required=True)
    restore.add_argument("--accept", action="store_true")
    restore.add_argument("--approved-by")
    restore.add_argument("--report")

    return parser


def _add_source_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--memory-dir", required=True)
    parser.add_argument("--chroma-dir", required=True)
    parser.add_argument("--graph-dir")
    parser.add_argument("--backup-dir", required=True)
    parser.add_argument("--report")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "prepare":
        payload = prepare_legacy_recovery_backup(
            memory_dir=args.memory_dir,
            chroma_dir=args.chroma_dir,
            graph_dir=args.graph_dir,
            backup_dir=args.backup_dir,
        )
    elif args.command == "write":
        payload = write_legacy_recovery_backup(
            memory_dir=args.memory_dir,
            chroma_dir=args.chroma_dir,
            graph_dir=args.graph_dir,
            backup_dir=args.backup_dir,
            accept=args.accept,
            approved_by=args.approved_by,
        )
    elif args.command == "verify":
        payload = verify_legacy_recovery_backup(
            args.archive,
            manifest_path=args.manifest,
        )
    elif args.command == "restore":
        payload = restore_legacy_recovery_backup(
            args.archive,
            restore_root=args.restore_root,
            manifest_path=args.manifest,
            accept=args.accept,
            approved_by=args.approved_by,
        )
    else:  # pragma: no cover - argparse enforces commands
        raise AssertionError(args.command)
    _write_report(getattr(args, "report", None), payload)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if payload.get("status") not in {"blocked", "denied", "failed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
