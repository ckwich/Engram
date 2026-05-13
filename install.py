#!/usr/bin/env python3
"""
Engram install.py — Setup wizard.
Creates a virtual environment, installs dependencies, pre-downloads the embedding model,
installs Claude Code skills, registers the session evaluator hook, registers Codex MCP when
available, and generates MCP config for manual client setup.
"""
import json
import os
import platform
import shutil
# The installer invokes trusted local setup CLIs with shell=False.
import subprocess  # nosec B404
import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
VENV_DIR = PROJECT_ROOT / "venv"
IS_WINDOWS = platform.system() == "Windows"
DEFAULT_DAEMON_URL = "http://127.0.0.1:8765"


def run(cmd: list, **kwargs):
    # Setup helper receives trusted installer argv and keeps shell=False.
    result = subprocess.run(cmd, **kwargs)  # nosec B603
    if result.returncode != 0:
        print(f"  FAILED: {' '.join(str(c) for c in cmd)}")
        sys.exit(1)
    return result


def get_venv_paths():
    """Return (pip, python) paths for the venv."""
    scripts = "Scripts" if IS_WINDOWS else "bin"
    pip_name = "pip.exe" if IS_WINDOWS else "pip"
    python_name = "python.exe" if IS_WINDOWS else "python"
    return VENV_DIR / scripts / pip_name, VENV_DIR / scripts / python_name


def install_skill(skill_name: str, source_dir: Path, dest_dir: Path):
    """Copy a SKILL.md file to ~/.claude/skills/{skill_name}/."""
    skill_src = source_dir / "SKILL.md"
    if not skill_src.exists():
        print(f"  [skip] {skill_name}: source SKILL.md not found at {skill_src}")
        return False

    skill_dest = dest_dir / skill_name
    skill_dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(skill_src, skill_dest / "SKILL.md")
    print(f"  [ok] {skill_name} -> {skill_dest / 'SKILL.md'}")
    return True


def _normalize_daemon_url(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().rstrip("/")
    return normalized or None


def _mcp_env(daemon_url: str | None = None) -> dict[str, str]:
    env = {"ENGRAM_DATA_DIR": str((PROJECT_ROOT / "data").resolve())}
    normalized_daemon_url = _normalize_daemon_url(daemon_url)
    if normalized_daemon_url is not None:
        env["ENGRAM_DAEMON_URL"] = normalized_daemon_url
    return env


def _codex_env_args(env: dict[str, str]) -> list[str]:
    args: list[str] = []
    for key, value in env.items():
        args.extend(["--env", f"{key}={value}"])
    return args


def _entrypoint_path(*, thin_daemon_client: bool = False) -> Path:
    return PROJECT_ROOT / ("server_daemon_client.py" if thin_daemon_client else "server.py")


def register_codex_mcp(
    python_path: Path,
    *,
    daemon_url: str | None = None,
    thin_daemon_client: bool = False,
):
    """Register Engram with Codex when the CLI is available."""
    codex_path = shutil.which("codex")
    if not codex_path:
        print("  [info] Codex CLI not found — skipping Codex MCP registration")
        return False

    server_name = "engram"
    server_path = _entrypoint_path(thin_daemon_client=thin_daemon_client)
    env = _mcp_env(daemon_url)

    # codex path is resolved locally and invoked with shell=False.
    existing = subprocess.run(  # nosec B603
        [codex_path, "mcp", "get", server_name],
        capture_output=True,
        text=True,
    )
    if existing.returncode == 0:
        output = existing.stdout
        # `codex mcp get` redacts environment values, so key presence is the
        # stable verification signal here.
        env_matches = all(f"{key}=" in output or f"{key}:" in output for key in env)
        if str(python_path) in output and str(server_path) in output and env_matches:
            print("  [ok] Codex MCP server already registered")
            return True

        # codex path is resolved locally and invoked with shell=False.
        remove_result = subprocess.run(  # nosec B603
            [codex_path, "mcp", "remove", server_name],
            capture_output=True,
            text=True,
        )
        if remove_result.returncode != 0:
            print("  [warn] Could not replace existing Codex MCP server entry")
            return False
        print("  [info] Replaced existing Codex MCP server entry")

    # codex path is resolved locally and invoked with shell=False.
    add_result = subprocess.run(  # nosec B603
        [
            codex_path,
            "mcp",
            "add",
            server_name,
            *_codex_env_args(env),
            "--",
            str(python_path),
            str(server_path),
        ],
        capture_output=True,
        text=True,
    )
    if add_result.returncode != 0:
        print("  [warn] Codex MCP registration failed")
        stderr = (add_result.stderr or "").strip()
        if stderr:
            print(f"         {stderr}")
        return False

    mode = "thin daemon-client" if thin_daemon_client else ("daemon-client" if daemon_url else "direct")
    print(f"  [ok] Codex MCP server registered ({mode})")
    return True


def register_stop_hook(python_path: Path):
    """Add the Engram Stop hook to Claude Code settings.json (if not already present)."""
    settings_path = Path.home() / ".claude" / "settings.json"

    hook_command = f"{python_path} {PROJECT_ROOT / 'hooks' / 'engram_stop.py'}"

    if settings_path.exists():
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except Exception:
            print("  [warn] Could not parse settings.json — skipping hook registration")
            return False
    else:
        settings = {}

    # Check if hook already registered
    hooks = settings.setdefault("hooks", {})
    stop_hooks = hooks.setdefault("Stop", [])

    for entry in stop_hooks:
        inner = entry.get("hooks", [])
        for h in inner:
            if "engram_stop" in h.get("command", ""):
                print("  [ok] Stop hook already registered")
                return True

    # Append new hook entry
    stop_hooks.append({
        "matcher": "",
        "hooks": [{
            "type": "command",
            "command": str(hook_command).replace("\\", "/"),
        }]
    })

    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)

    print(f"  [ok] Stop hook registered in {settings_path}")
    return True


def create_default_config():
    """Create config.json with sensible defaults if it doesn't exist."""
    config_path = PROJECT_ROOT / "config.json"
    if config_path.exists():
        print("  [ok] config.json already exists")
        return

    config = {
        "dedup_threshold": 0.92,
        "stale_days": 90,
        "session_evaluator": {
            "logic_win_triggers": [
                "bug resolved",
                "new capability added",
                "architectural decision made"
            ],
            "milestone_triggers": [
                "phase completed",
                "feature shipped",
                "significant refactor done"
            ],
            "auto_approve_threshold": 0.0
        }
    }

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    print("  [ok] config.json created with defaults")


def parse_args(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Install Engram locally")
    parser.add_argument(
        "--daemon-url",
        default=None,
        help=(
            "Register Codex MCP in daemon-client mode using this engramd URL "
            f"(common local value: {DEFAULT_DAEMON_URL})"
        ),
    )
    parser.add_argument(
        "--thin-daemon-client",
        action="store_true",
        help=(
            "Register Codex against server_daemon_client.py so Codex sessions "
            "talk only to engramd and never import local storage/index modules."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None):
    args = parse_args(argv)
    daemon_url = _normalize_daemon_url(args.daemon_url)
    if args.thin_daemon_client and daemon_url is None:
        daemon_url = DEFAULT_DAEMON_URL
    print("Engram Setup Wizard\n")

    # ── Python version check ───────────────────────────────────────────────
    if sys.version_info < (3, 10):
        print("ERROR: Python 3.10 or higher required.")
        sys.exit(1)

    print(f"[ok] Python {sys.version.split()[0]} detected")

    # ── Create venv ────────────────────────────────────────────────────────
    if not VENV_DIR.exists():
        print("\n[1/7] Creating virtual environment...")
        run([sys.executable, "-m", "venv", str(VENV_DIR)])
        print("  [ok] Virtual environment created")
    else:
        print("\n[1/7] Virtual environment already exists")

    pip, python = get_venv_paths()

    # ── Install dependencies ───────────────────────────────────────────────
    print("\n[2/7] Installing dependencies (this may take a minute)...")
    run([str(pip), "install", "--upgrade", "pip"], capture_output=True)
    run([str(pip), "install", "-r", str(PROJECT_ROOT / "requirements.txt")])
    print("  [ok] Dependencies installed")

    # ── Pre-download embedding model ───────────────────────────────────────
    print("\n[3/7] Pre-downloading embedding model (all-MiniLM-L6-v2, ~80MB)...")
    run([
        str(python), "-c",
        "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2'); print('  [ok] Model ready.')"
    ])

    # ── Install skills ─────────────────────────────────────────────────────
    print("\n[4/7] Installing Claude Code skills...")
    skills_dest = Path.home() / ".claude" / "skills"

    # Engramize skill (bundled in repo)
    engramize_src = PROJECT_ROOT / "skills" / "engramize"
    if engramize_src.exists():
        install_skill("engramize", engramize_src, skills_dest)
    else:
        # Fall back to creating from template
        engramize_dest = skills_dest / "engramize"
        engramize_dest.mkdir(parents=True, exist_ok=True)
        print(f"  [info] Engramize skill source not found in repo. Check ~/.claude/skills/engramize/SKILL.md")

    # Engram-pending skill (bundled in repo)
    pending_src = PROJECT_ROOT / "skills" / "engram-pending"
    if pending_src.exists():
        install_skill("engram-pending", pending_src, skills_dest)
    else:
        print(f"  [info] Engram-pending skill source not found in repo.")

    # Engram-index skill (bundled in repo)
    index_src = PROJECT_ROOT / "skills" / "engram-index"
    if index_src.exists():
        install_skill("engram-index", index_src, skills_dest)
    else:
        print(f"  [info] Engram-index skill source not found in repo.")

    # ── Register Stop hook ─────────────────────────────────────────────────
    print("\n[5/7] Registering session evaluator hook...")
    register_stop_hook(python)

    # ── Create default config ──────────────────────────────────────────────
    print("\n[6/7] Setting up configuration...")
    create_default_config()

    # ── Register MCP clients / emit config ─────────────────────────────────
    print("\n[7/7] Registering MCP clients...")
    register_codex_mcp(
        python,
        daemon_url=daemon_url,
        thin_daemon_client=args.thin_daemon_client,
    )
    entrypoint_path = _entrypoint_path(thin_daemon_client=args.thin_daemon_client)

    mcp_config = {
        "mcpServers": {
            "engram": {
                "command": str(python),
                "args": [str(entrypoint_path)],
                "env": _mcp_env(daemon_url),
            }
        }
    }

    config_path = PROJECT_ROOT / "mcp_config.json"
    with open(config_path, "w") as f:
        json.dump(mcp_config, f, indent=2)

    print(f"  [ok] MCP config written to: {config_path}")

    # ── Done ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Engram is ready!\n")
    print("1. Codex registration:")
    print("   If the Codex CLI was installed, Engram was registered automatically.")
    if daemon_url:
        print(f"   Registered in daemon-client mode: ENGRAM_DAEMON_URL={daemon_url}")
    if args.thin_daemon_client:
        print(f"   Thin daemon-client entrypoint: {entrypoint_path}")
    print("   Manual fallback:")
    env_flags = " ".join(f"--env {key}={value}" for key, value in _mcp_env(daemon_url).items())
    print(f"   codex mcp add engram {env_flags} -- \\\n     {python} \\\n     {entrypoint_path}\n")
    print("2. Claude Code manual registration:")
    print(f"   claude mcp add engram --scope user \\\n     {python} \\\n     {PROJECT_ROOT / 'server.py'}\n")
    print("3. Start the web dashboard:")
    print(f"   {python} {PROJECT_ROOT / 'webui.py'}\n")
    print("4. Index a codebase:")
    print(f"   {python} {PROJECT_ROOT / 'engram_index.py'} --project /path/to/project --init\n")
    print("5. Skills installed: /engramize, /engram-index, engram-pending")
    print("6. Session evaluator hook registered (evaluates sessions automatically)")
    print("=" * 60)


if __name__ == "__main__":
    main()
