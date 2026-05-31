from pathlib import Path


def test_sync_docs_forbid_active_database_file_sync():
    text = Path("docs/SYNC_DESKTOP_LAPTOP.md").read_text(encoding="utf-8")

    assert "Personal Hub Mode is the default online path" in text
    assert "ENGRAM_HUB_URL" in text
    assert "fail closed" in text
    assert "Never sync active SQLite, WAL, LanceDB, Kuzu, Chroma, or lock files" in text
    assert "prepare_sync_changeset" in text
    assert "prepare_sync_apply" in text
    assert "restore-grade runtime snapshot" in text


def test_sync_docs_are_linked_from_operator_docs():
    readme = Path("README.md").read_text(encoding="utf-8")
    agents = Path("AGENTS.md").read_text(encoding="utf-8")

    assert "docs/SYNC_DESKTOP_LAPTOP.md" in readme
    assert "docs/SYNC_DESKTOP_LAPTOP.md" in agents
