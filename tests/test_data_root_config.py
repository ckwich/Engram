from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_memory_manager_honors_engram_data_dir(tmp_path):
    data_root = tmp_path / "engram-data"
    env = os.environ.copy()
    env["ENGRAM_DATA_DIR"] = str(data_root)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; "
                "from core import memory_manager as mm; "
                "print(json.dumps({"
                "'json_dir': str(mm.JSON_DIR), "
                "'chroma_dir': str(mm.CHROMA_DIR), "
                "'process_lock': str(mm.CHROMA_PROCESS_LOCK_PATH), "
                "'owner_lock': str(mm.CHROMA_OWNER_LOCK_PATH), "
                "'json_exists': mm.JSON_DIR.exists(), "
                "'chroma_exists': mm.CHROMA_DIR.exists()"
                "}))"
            ),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )

    payload = json.loads(result.stdout)
    assert Path(payload["json_dir"]) == data_root / "memories"
    assert Path(payload["chroma_dir"]) == data_root / "chroma"
    assert Path(payload["process_lock"]) == data_root / "chroma.lock"
    assert Path(payload["owner_lock"]) == data_root / "chroma.owner.lock"
    assert payload["json_exists"] is True
    assert payload["chroma_exists"] is True
