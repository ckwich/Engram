from __future__ import annotations

import importlib
from pathlib import Path


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


def test_start_script_points_remote_users_to_safe_required_configuration():
    script = Path("start_engram.bat").read_text(encoding="utf-8")

    assert "ENGRAM_WEBUI_HOST" in script
    assert "ENGRAM_WEBUI_ACCESS_TOKEN" in script
    assert "ENGRAM_WEBUI_WRITE_TOKEN" in script
    assert "ENGRAM_WEBUI_ALLOWED_HOSTS" in script
    assert "secrets.token_urlsafe" in script
    assert "server.py --health" in script


def test_remote_webui_guide_documents_tailscale_configuration():
    guide = Path("docs/REMOTE_WEBUI.md")

    assert guide.exists()
    text = guide.read_text(encoding="utf-8")
    assert "Tailscale" in text
    assert "ENGRAM_WEBUI_HOST" in text
    assert "ENGRAM_WEBUI_ACCESS_TOKEN" in text
    assert "ENGRAM_WEBUI_WRITE_TOKEN" in text
    assert "ENGRAM_WEBUI_ALLOWED_HOSTS" in text
    assert "python -c \"import secrets; print(secrets.token_urlsafe(32))\"" in text
    assert "python server.py --health" in text


def test_generated_git_hook_uses_owner_only_executable_permissions():
    import engram_index

    assert engram_index.HOOK_FILE_MODE == 0o700


def test_indexer_skips_generated_dependency_and_secret_paths(tmp_path):
    import engram_index

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('ok')", encoding="utf-8")
    (tmp_path / ".env").write_text("SECRET=value", encoding="utf-8")
    (tmp_path / ".engram").mkdir()
    (tmp_path / ".engram" / "config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "venv").mkdir()
    (tmp_path / "venv" / "activate.py").write_text("token='secret'", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.js").write_text("module.exports = {}", encoding="utf-8")

    files = engram_index.collect_domain_files(
        tmp_path,
        {"file_globs": ["**/*"]},
        max_file_size_kb=100,
    )

    assert [path.relative_to(tmp_path).as_posix() for path in files] == ["src/app.py"]


def test_indexer_skips_symlinked_files_outside_project(tmp_path):
    import engram_index

    outside = tmp_path.parent / "outside-secret.py"
    outside.write_text("SECRET = 'outside'", encoding="utf-8")
    link = tmp_path / "linked_secret.py"
    try:
        link.symlink_to(outside)
    except OSError:
        return

    files = engram_index.collect_domain_files(
        tmp_path,
        {"file_globs": ["**/*.py"]},
        max_file_size_kb=100,
    )

    assert link not in files
