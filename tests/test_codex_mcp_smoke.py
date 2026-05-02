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
    assert Path(args).resolve() == (REPO_ROOT / "server.py").resolve()
    assert Path(command).exists() or shutil.which(command) is not None
