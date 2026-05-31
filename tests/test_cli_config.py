from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from core.memory_os.runtime_paths import default_data_root


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
    assert Path(engram["env"]["ENGRAM_DATA_DIR"]).resolve() == default_data_root()
    assert "ENGRAM_DAEMON_URL" not in engram["env"]


def test_generate_config_can_emit_daemon_client_environment():
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "server.py"),
            "--generate-config",
            "--daemon-url",
            "http://127.0.0.1:8765/",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )

    config = json.loads(result.stdout)
    engram = config["mcpServers"]["engram"]

    assert engram["command"] == sys.executable
    assert Path(engram["args"][0]).resolve() == (REPO_ROOT / "server.py").resolve()
    assert engram["env"]["ENGRAM_DAEMON_URL"] == "http://127.0.0.1:8765"
    assert Path(engram["env"]["ENGRAM_DATA_DIR"]).resolve() == default_data_root()


def test_daemon_url_rejects_blank_value():
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "server.py"),
            "--generate-config",
            "--daemon-url",
            "   ",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode != 0
    assert "--daemon-url cannot be blank" in result.stderr


def test_sse_help_documents_loopback_default():
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "server.py"), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )

    assert "--host HOST" in result.stdout
    assert "SSE host (default: 127.0.0.1)" in result.stdout


def test_help_documents_daemon_config_generation():
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "server.py"), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )

    assert "--daemon-url DAEMON_URL" in result.stdout
    assert "Include ENGRAM_DAEMON_URL" in result.stdout


def test_help_documents_agent_reliability_eval():
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "server.py"), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )

    assert "--agent-eval" in result.stdout
    assert "Run deterministic agent reliability harness" in result.stdout


def test_help_uses_current_product_version_identity():
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "server.py"), "--help"],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )

    combined_output = result.stdout + result.stderr

    assert "Engram 1.0.0 — Semantic Memory MCP Server" in result.stdout
    assert "Engram v0.1" not in combined_output


def test_codebase_indexer_dry_run_is_agent_native(tmp_path):
    project = tmp_path / "example_game_0"
    (project / ".engram").mkdir(parents=True)
    (project / "src").mkdir()
    (project / "src" / "game.py").write_text("class GameMode:\n    pass\n", encoding="utf-8")
    (project / ".engram" / "config.json").write_text(
        json.dumps(
            {
                "project_name": "example_game_0",
                "planning_paths": [],
                "domains": {
                    "gameplay": {
                        "file_globs": ["src/**/*.py"],
                        "questions": ["What is the gameplay architecture?"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "engram_index.py"),
            "--project",
            str(project),
            "--mode",
            "bootstrap",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )

    assert "agent synthesis task(s)" in result.stdout
    assert "claude" not in result.stdout.lower()
