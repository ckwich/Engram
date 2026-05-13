from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def _parse_codex_mcp_get(output: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if ": " not in line:
            continue
        key, value = line.split(": ", 1)
        fields[key] = value
    return fields


def _git_common_dir(path: Path) -> Path | None:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return None
    common_dir = Path(result.stdout.strip())
    if not common_dir.is_absolute():
        common_dir = path / common_dir
    return common_dir.resolve()


def _is_same_repo_checkout(server_path: Path) -> bool:
    current_common_dir = _git_common_dir(REPO_ROOT)
    registered_common_dir = _git_common_dir(server_path.parent)
    return (
        current_common_dir is not None
        and registered_common_dir is not None
        and current_common_dir == registered_common_dir
    )


def test_codex_engram_registration_smoke():
    codex = shutil.which("codex")
    if codex is None:
        pytest.skip("Codex CLI is not installed")

    result = subprocess.run(
        [codex, "mcp", "get", "engram"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        pytest.skip("Engram is not registered with Codex")

    fields = _parse_codex_mcp_get(result.stdout)
    command = fields.get("command")
    args = fields.get("args")

    assert fields.get("enabled") == "true"
    assert fields.get("transport") == "stdio"
    assert command
    assert args
    server_path = Path(args).resolve()
    assert server_path.name in {"server.py", "server_daemon_client.py"}
    if server_path.name == "server_daemon_client.py":
        assert "ENGRAM_DAEMON_URL=" in fields.get("env", "")
    assert server_path == (REPO_ROOT / server_path.name).resolve() or _is_same_repo_checkout(server_path)
    assert Path(command).exists() or shutil.which(command) is not None
