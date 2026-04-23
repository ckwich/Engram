from __future__ import annotations

import importlib


def test_webui_binds_to_loopback_by_default(monkeypatch):
    monkeypatch.delenv("ENGRAM_WEBUI_HOST", raising=False)
    monkeypatch.delenv("ENGRAM_WEBUI_PORT", raising=False)

    import webui

    webui = importlib.reload(webui)

    assert webui.DEFAULT_WEBUI_HOST == "127.0.0.1"
    assert webui.DEFAULT_WEBUI_PORT == 5000
    assert webui.resolve_webui_bind() == ("127.0.0.1", 5000)


def test_webui_bind_can_be_overridden_explicitly(monkeypatch):
    import webui

    webui = importlib.reload(webui)
    monkeypatch.setenv("ENGRAM_WEBUI_HOST", "0.0.0.0")
    monkeypatch.setenv("ENGRAM_WEBUI_PORT", "5101")

    assert webui.resolve_webui_bind() == ("0.0.0.0", 5101)


def test_generated_git_hook_uses_owner_only_executable_permissions():
    import engram_index

    assert engram_index.HOOK_FILE_MODE == 0o700
