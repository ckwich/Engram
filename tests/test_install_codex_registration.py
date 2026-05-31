from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import install
from core.memory_os.runtime_paths import default_data_root


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
    assert f"ENGRAM_DATA_DIR={default_data_root()}" in add_call


def test_register_codex_mcp_finds_macos_app_bundled_codex_cli(monkeypatch, tmp_path):
    calls = []
    codex_cli = tmp_path / "Codex.app" / "Contents" / "Resources" / "codex"
    codex_cli.parent.mkdir(parents=True)
    codex_cli.write_text("#!/bin/sh\n", encoding="utf-8")
    codex_cli.chmod(0o755)

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[:3] == [str(codex_cli), "mcp", "get"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(install.shutil, "which", lambda name: None)
    monkeypatch.setattr(install.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(install, "MACOS_CODEX_APP_CANDIDATES", (codex_cli,))
    monkeypatch.setattr(install.subprocess, "run", fake_run)

    registered = install.register_codex_mcp(
        Path("python"),
        hub_url="http://engram-hub.tailnet-name.ts.net:8767",
    )

    assert registered is True
    assert calls[0][:3] == [str(codex_cli), "mcp", "get"]
    assert calls[-1][:3] == [str(codex_cli), "mcp", "add"]
    assert "ENGRAM_HUB_URL=http://engram-hub.tailnet-name.ts.net:8767" in calls[-1]


def test_register_codex_mcp_can_use_remote_hub_without_persisting_token(monkeypatch):
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
        hub_url="http://engram-hub.tailnet-name.ts.net:8767/",
    )

    assert registered is True
    add_call = calls[-1]
    assert str(install.PROJECT_ROOT / "server_daemon_client.py") in add_call
    assert "ENGRAM_HUB_URL=http://engram-hub.tailnet-name.ts.net:8767" in add_call
    assert not any(str(arg).startswith("ENGRAM_DAEMON_URL=") for arg in add_call)
    assert not any(str(arg).startswith("ENGRAM_HUB_ACCESS_TOKEN=") for arg in add_call)


def test_register_codex_mcp_persists_hub_token_only_when_explicit(monkeypatch):
    calls = []
    token = "x" * 40

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[:3] == ["codex", "mcp", "get"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(install.shutil, "which", lambda name: "codex")
    monkeypatch.setattr(install.subprocess, "run", fake_run)

    registered = install.register_codex_mcp(
        Path("python"),
        hub_url="http://engram-hub.tailnet-name.ts.net:8767",
        persist_hub_token=True,
        hub_access_token=token,
    )

    assert registered is True
    add_call = calls[-1]
    assert f"ENGRAM_HUB_ACCESS_TOKEN={token}" in add_call


def test_register_codex_mcp_replaces_existing_entry_when_persisting_hub_token(monkeypatch):
    calls = []
    token = "x" * 40
    server_path = install.PROJECT_ROOT / "server_daemon_client.py"

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[:3] == ["codex", "mcp", "get"]:
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    f"command: python\nargs: {server_path}\n"
                    "env: ENGRAM_DATA_DIR=***, ENGRAM_HUB_URL=***, "
                    "ENGRAM_HUB_ACCESS_TOKEN=***\n"
                ),
                stderr="",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(install.shutil, "which", lambda name: "codex")
    monkeypatch.setattr(install.subprocess, "run", fake_run)

    registered = install.register_codex_mcp(
        Path("python"),
        hub_url="http://engram-hub.tailnet-name.ts.net:8767",
        persist_hub_token=True,
        hub_access_token=token,
    )

    assert registered is True
    assert any(call[:3] == ["codex", "mcp", "remove"] for call in calls)
    assert calls[-1][:3] == ["codex", "mcp", "add"]
    assert f"ENGRAM_HUB_ACCESS_TOKEN={token}" in calls[-1]


def test_mcp_env_rejects_hub_urls_with_embedded_credentials():
    with pytest.raises(ValueError, match="hub_url_must_not_include_credentials"):
        install._mcp_env(hub_url="http://secret@engram-hub.tailnet-name.ts.net:8767")


def test_pip_command_uses_python_module_invocation():
    python_path = Path("venv/Scripts/python.exe")
    command = install.pip_command(python_path, "install", "--upgrade", "pip")

    assert command == [str(python_path), "-m", "pip", "install", "--upgrade", "pip"]


def test_shell_command_quotes_hook_paths_with_metacharacters():
    command = install._shell_command([
        Path(r"C:\Tools & Apps\python.exe"),
        Path(r"C:\Repo & Hooks\hooks\engram_stop.py"),
    ])

    if install.IS_WINDOWS:
        assert command == (
            r'"C:\Tools & Apps\python.exe" '
            r'"C:\Repo & Hooks\hooks\engram_stop.py"'
        )
    else:
        assert command == (
            r"'C:\Tools & Apps\python.exe' "
            r"'C:\Repo & Hooks\hooks\engram_stop.py'"
        )
