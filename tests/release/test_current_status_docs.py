from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STATUS_DOC = ROOT / "docs" / "ENGRAM_CURRENT_STATUS.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_current_status_document_names_runtime_stability_tiers() -> None:
    assert STATUS_DOC.exists(), "docs/ENGRAM_CURRENT_STATUS.md must exist"

    status = _read(STATUS_DOC)

    for heading in (
        "## Stable",
        "## Beta",
        "## Legacy Compatibility",
        "## Deferred",
    ):
        assert heading in status


def test_current_status_document_mentions_agent_operating_boundaries() -> None:
    assert STATUS_DOC.exists(), "docs/ENGRAM_CURRENT_STATUS.md must exist"

    status = _read(STATUS_DOC)

    for required in (
        "server_daemon_client.py",
        "engramd",
        "query_knowledge",
        "document intake",
        "legacy JSON/Chroma",
        "hosted scope",
    ):
        assert required in status


def test_current_status_document_has_no_placeholder_language() -> None:
    assert STATUS_DOC.exists(), "docs/ENGRAM_CURRENT_STATUS.md must exist"

    status = _read(STATUS_DOC).lower()

    for marker in ("todo", "tbd", "not yet sure", "fill in", "implement later"):
        assert marker not in status
