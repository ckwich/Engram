"""Content-addressed artifact store for Memory OS evidence."""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

_ARTIFACT_RE = re.compile(r"^sha256:([a-f0-9]{64})([.][A-Za-z0-9._-]+)?$")


class ContentAddressedStore:
    """Store immutable bytes under deterministic SHA-256 artifact ids."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def put_bytes(self, data: bytes, *, suffix: str = "") -> str:
        if not isinstance(data, bytes):
            raise TypeError("data must be bytes")
        safe_suffix = _safe_suffix(suffix)
        digest = hashlib.sha256(data).hexdigest()
        artifact_id = f"sha256:{digest}{safe_suffix}"
        path = self.path_for(artifact_id)
        if path.exists():
            return artifact_id

        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            temp_path.replace(path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        return artifact_id

    def read_bytes(self, artifact_id: str) -> bytes:
        return self.path_for(artifact_id).read_bytes()

    def path_for(self, artifact_id: str) -> Path:
        match = _ARTIFACT_RE.match(str(artifact_id))
        if match is None:
            raise ValueError("invalid artifact id")
        digest, suffix = match.groups()
        suffix = suffix or ""
        path = self.root / "sha256" / digest[:2] / digest[2:4] / f"{digest}{suffix}"
        _ensure_under_root(self.root, path)
        return path


def _safe_suffix(suffix: str) -> str:
    if suffix == "":
        return ""
    text = str(suffix)
    if not text.startswith(".") or "/" in text or "\\" in text or ".." in text:
        raise ValueError("unsafe suffix")
    if not re.fullmatch(r"[.][A-Za-z0-9._-]+", text):
        raise ValueError("unsafe suffix")
    return text


def _ensure_under_root(root: Path, path: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("artifact path escapes content store root") from exc
