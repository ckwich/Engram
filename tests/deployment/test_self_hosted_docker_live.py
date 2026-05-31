from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_live_self_host_docker_smoke() -> None:
    if os.environ.get("ENGRAM_LIVE_DOCKER_SMOKE") != "1":
        pytest.skip("set ENGRAM_LIVE_DOCKER_SMOKE=1 to run the live Docker smoke gate")

    subprocess.run(
        [str(ROOT / "scripts" / "self_host_smoke.sh")],
        cwd=ROOT,
        check=True,
        timeout=int(os.environ.get("ENGRAM_LIVE_DOCKER_SMOKE_TIMEOUT", "1800")),
    )
