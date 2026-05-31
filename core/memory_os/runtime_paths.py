"""Runtime path policy and startup preflight checks for Memory OS."""
from __future__ import annotations

import os
import platform
import re
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from core.memory_os.schema import TABLES


REPO_ROOT = Path(__file__).resolve().parents[2]
LEDGER_FILENAME = "ledger.sqlite3"
MEMORY_OS_DIRNAME = "memory_os"

_CONFLICT_MARKERS = ("conflict", "conflicted", "copy", "duplicate")
_NUMBERED_LEDGER_RE = re.compile(r"^ledger\s+\d+[.]sqlite3(?:-(?:wal|shm))?$", re.IGNORECASE)
_NUMBERED_MANIFEST_RE = re.compile(
    r"^[.]engram_retrieval_manifest\s+\d+[.]json$",
    re.IGNORECASE,
)
_SYNC_PATH_MARKERS = (
    "mobile documents",
    "clouddocs",
    "icloud drive",
    "dropbox",
    "onedrive",
    "google drive",
    "box sync",
)


def default_data_root(
    *,
    env: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    home: Path | None = None,
) -> Path:
    """Return Engram's per-user application data root for new runtime state."""
    active_env = os.environ if env is None else env
    system = (platform_name or platform.system()).lower()
    home_dir = Path(home) if home is not None else Path.home()

    if system == "windows":
        base = active_env.get("LOCALAPPDATA")
        if base:
            return (Path(base) / "Engram" / "default-data").expanduser().resolve()
        return (home_dir / "AppData" / "Local" / "Engram" / "default-data").expanduser().resolve()

    if system == "darwin":
        return (home_dir / "Library" / "Application Support" / "Engram" / "default-data").expanduser().resolve()

    base = active_env.get("XDG_DATA_HOME")
    if base:
        return (Path(base) / "engram" / "default-data").expanduser().resolve()
    return (home_dir / ".local" / "share" / "engram" / "default-data").expanduser().resolve()


def resolve_data_root(env: Mapping[str, str] | None = None) -> Path:
    """Resolve the configured Engram data root, defaulting outside the checkout."""
    active_env = os.environ if env is None else env
    configured = str(active_env.get("ENGRAM_DATA_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return default_data_root(env=active_env)


def memory_os_root_for_data_root(data_root: str | Path) -> Path:
    """Return the Memory OS root below an Engram data root."""
    return Path(data_root).expanduser().resolve() / MEMORY_OS_DIRNAME


def find_conflict_artifacts(memory_os_root: str | Path) -> list[dict[str, Any]]:
    """Find sibling/conflicted copies that make startup unsafe."""
    root = Path(memory_os_root).expanduser()
    candidates: list[Path] = []
    if root.exists():
        candidates.extend(_conflict_children(root))
    lance_root = root / "lance"
    if lance_root.exists():
        candidates.extend(_conflict_children(lance_root))

    payloads: list[dict[str, Any]] = []
    for path in sorted(set(candidates), key=lambda item: str(item)):
        payloads.append(
            {
                "path": str(path),
                "name": path.name,
                "relative_path": _safe_relative(path, root),
                "size_bytes": _safe_size(path),
            }
        )
    return payloads


def inspect_ledger(ledger_path: str | Path) -> dict[str, Any]:
    """Inspect a SQLite ledger without creating or mutating it."""
    path = Path(ledger_path).expanduser()
    report: dict[str, Any] = {
        "path": str(path),
        "resolved_path": str(path.resolve()),
        "exists": path.exists(),
        "size_bytes": _safe_size(path),
        "quick_check": None,
        "tables": {},
        "error": None,
    }
    if not path.exists():
        return report
    try:
        conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("PRAGMA quick_check").fetchone()
            report["quick_check"] = str(row[0]) if row is not None else "missing"
            table_names = {
                str(item["name"])
                for item in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            for table in TABLES:
                if table in table_names:
                    count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # nosec B608
                    report["tables"][table] = int(count)
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        report["quick_check"] = f"error:{type(exc).__name__}"
        report["error"] = str(exc)
    return report


def validate_memory_os_preflight(
    memory_os_root: str | Path,
    *,
    repo_root: str | Path | None = None,
    allow_unsafe_paths: bool = False,
) -> dict[str, Any]:
    """Return a fail-closed startup report for the daemon-owned runtime root."""
    root = Path(memory_os_root).expanduser()
    resolved_root = root.resolve()
    active_repo_root = Path(repo_root).expanduser().resolve() if repo_root is not None else REPO_ROOT
    risks: list[dict[str, Any]] = []

    path_risks = runtime_path_risks(resolved_root, repo_root=active_repo_root)
    if path_risks and not allow_unsafe_paths:
        risks.extend(path_risks)
    elif path_risks:
        risks.extend([{**risk, "severity": "warning"} for risk in path_risks])

    conflict_artifacts = find_conflict_artifacts(root)
    if conflict_artifacts:
        risks.append(
            {
                "code": "conflict_artifact_detected",
                "severity": "blocker",
                "message": (
                    "Conflict or duplicate runtime artifacts were found next to the active "
                    "Memory OS files. Refusing startup until an operator repairs or removes them."
                ),
            }
        )

    ledger_report = inspect_ledger(resolved_root / LEDGER_FILENAME)
    if ledger_report["exists"] and ledger_report.get("quick_check") != "ok":
        risks.append(
            {
                "code": "malformed_ledger",
                "severity": "blocker",
                "message": "The active Memory OS SQLite ledger failed read-only PRAGMA quick_check.",
            }
        )

    suspicious = _suspicious_replacement_ledger(ledger_report, conflict_artifacts)
    if suspicious is not None:
        risks.append(suspicious)

    blocked = any(risk.get("severity") == "blocker" for risk in risks)
    return {
        "schema_version": "2026-05-26.memory-os-preflight.v1",
        "status": "blocked" if blocked else "ok",
        "safe_to_start": not blocked,
        "memory_os_root": str(root),
        "resolved_memory_os_root": str(resolved_root),
        "repo_root": str(active_repo_root),
        "risks": risks,
        "conflict_artifacts": conflict_artifacts,
        "ledger": ledger_report,
        "guidance": _preflight_guidance(blocked),
    }


def runtime_path_risks(memory_os_root: str | Path, *, repo_root: str | Path | None = None) -> list[dict[str, Any]]:
    """Return path risks that should block always-on runtime state by default."""
    root = Path(memory_os_root).expanduser().resolve()
    risks: list[dict[str, Any]] = []
    active_repo_root = Path(repo_root).expanduser().resolve() if repo_root is not None else REPO_ROOT
    try:
        root.relative_to(active_repo_root)
    except ValueError:
        pass
    else:
        risks.append(
            {
                "code": "repo_checkout_runtime_path",
                "severity": "blocker",
                "message": "Memory OS runtime state resolves inside the project checkout.",
            }
        )

    lowered = str(root).lower()
    if any(marker in lowered for marker in _SYNC_PATH_MARKERS):
        risks.append(
            {
                "code": "synced_runtime_path",
                "severity": "blocker",
                "message": "Memory OS runtime state resolves inside a known synced-folder path.",
            }
        )
    return risks


def _conflict_children(root: Path) -> list[Path]:
    if not root.exists():
        return []
    candidates: list[Path] = []
    for path in root.iterdir():
        name = path.name
        lowered = name.lower()
        if _NUMBERED_LEDGER_RE.match(name) or _NUMBERED_MANIFEST_RE.match(name):
            candidates.append(path)
            continue
        if any(marker in lowered for marker in _CONFLICT_MARKERS) and _critical_artifact_name(lowered):
            candidates.append(path)
    return candidates


def _critical_artifact_name(lowered_name: str) -> bool:
    return any(
        token in lowered_name
        for token in (
            "ledger",
            ".engram_retrieval_manifest",
            "memory_os",
            "kuzu",
            "lance",
            "objects",
        )
    )


def _suspicious_replacement_ledger(
    ledger_report: dict[str, Any],
    conflict_artifacts: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not ledger_report.get("exists"):
        return None
    active_size = int(ledger_report.get("size_bytes") or 0)
    larger_conflict = any(
        str(item.get("name", "")).lower().startswith("ledger")
        and int(item.get("size_bytes") or 0) > max(active_size, 4096)
        for item in conflict_artifacts
    )
    if active_size <= 4096 and larger_conflict:
        return {
            "code": "suspicious_replacement_ledger",
            "severity": "blocker",
            "message": (
                "The active ledger is tiny while a larger duplicate ledger exists nearby. "
                "This matches a common synced-folder replacement failure mode."
            ),
        }
    return None


def _preflight_guidance(blocked: bool) -> str:
    if not blocked:
        return "Runtime preflight passed; daemon startup may proceed."
    return (
        "Do not start Engram against this runtime root. Move runtime state to the "
        "Engram application-data directory, repair or restore the SQLite ledger, "
        "and remove conflict artifacts only after an operator verifies the correct copy."
    )


def _safe_size(path: Path) -> int | None:
    try:
        return int(path.stat().st_size)
    except OSError:
        return None


def _safe_relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
