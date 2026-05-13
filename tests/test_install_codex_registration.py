from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import install


def test_register_codex_mcp_can_use_thin_daemon_client_entrypoint(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[:3] == ["codex", "mcp", "get"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(install.shutil, "which", lambda name: "codex")
    monkeypatch.setattr(install.subprocess, "run", fake_run)

    registered = install.register_codex_mcp(
        Path("python"),
        daemon_url="http://127.0.0.1:8765",
        thin_daemon_client=True,
    )

    assert registered is True
    add_call = calls[-1]
    assert str(install.PROJECT_ROOT / "server_daemon_client.py") in add_call
    assert str(install.PROJECT_ROOT / "server.py") not in add_call


def test_pip_command_uses_python_module_invocation():
    python_path = Path("venv/Scripts/python.exe")
    command = install.pip_command(python_path, "install", "--upgrade", "pip")

    assert command == [str(python_path), "-m", "pip", "install", "--upgrade", "pip"]
