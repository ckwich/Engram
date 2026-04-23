from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_generate_config_uses_active_python_interpreter():
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "server.py"), "--generate-config"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )

    config = json.loads(result.stdout)
    engram = config["mcpServers"]["engram"]

    assert engram["command"] == sys.executable
    assert Path(engram["args"][0]).resolve() == (REPO_ROOT / "server.py").resolve()
