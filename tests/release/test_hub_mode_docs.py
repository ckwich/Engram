from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_hub_mode_runbook_documents_private_gateway_not_raw_daemon():
    doc = (REPO_ROOT / "docs" / "HUB_MODE_TAILSCALE.md").read_text(encoding="utf-8")

    assert "Personal Hub Mode" in doc
    assert "Tailscale" in doc
    assert "ENGRAM_HUB_ACCESS_TOKEN" in doc
    assert "--hub-listen" in doc
    assert "Do not expose the raw daemon" in doc
    assert "Dropbox" in doc
    assert "iCloud" in doc
    assert "OneDrive" in doc
