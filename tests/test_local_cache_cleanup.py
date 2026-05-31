from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "clean_local_caches.sh"


def test_local_cache_cleaner_skips_stateful_ignored_directories(tmp_path: Path) -> None:
    if shutil.which("bash") is None:
        pytest.skip("clean_local_caches.sh requires bash")
    bash_probe = subprocess.run(
        ["bash", "--version"],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    if bash_probe.returncode != 0:
        pytest.skip("clean_local_caches.sh requires a runnable bash")

    removable_dirs = [
        tmp_path / "src" / "__pycache__",
        tmp_path / ".pytest_cache",
        tmp_path / ".pytest_tmp",
    ]
    protected_dirs = [
        tmp_path / "venv" / "__pycache__",
        tmp_path / "data" / "__pycache__",
        tmp_path / ".engram" / "__pycache__",
        tmp_path / ".claude" / "__pycache__",
        tmp_path / ".planning" / "__pycache__",
        tmp_path / ".git" / "__pycache__",
        tmp_path / "docs" / "superpowers" / "__pycache__",
    ]

    for path in removable_dirs + protected_dirs:
        path.mkdir(parents=True)
        (path / "cache.pyc").write_bytes(b"cache")
    orphan_pyc = tmp_path / "src" / "orphan.pyc"
    orphan_pyc.write_bytes(b"cache")

    env = os.environ.copy()
    env["ENGRAM_CACHE_CLEAN_ROOT"] = str(tmp_path)

    dry_run = subprocess.run(
        ["bash", str(SCRIPT), "--dry-run"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "./src/__pycache__" in dry_run.stdout
    assert "./.pytest_cache" in dry_run.stdout
    assert "./.pytest_tmp" in dry_run.stdout
    assert "./src/orphan.pyc" in dry_run.stdout
    assert "venv" not in dry_run.stdout
    assert "data" not in dry_run.stdout
    assert ".engram" not in dry_run.stdout
    assert "docs/superpowers" not in dry_run.stdout

    subprocess.run(
        ["bash", str(SCRIPT), "--apply"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    for path in removable_dirs:
        assert not path.exists()
    assert not orphan_pyc.exists()
    for path in protected_dirs:
        assert path.exists()
