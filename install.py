#!/usr/bin/env python3
"""
Engram install.py — Setup wizard.
Creates a virtual environment, installs dependencies, and generates MCP config.
"""
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
VENV_DIR = PROJECT_ROOT / "venv"


def run(cmd: list, **kwargs):
    result = subprocess.run(cmd, **kwargs)
    if result.returncode != 0:
        print(f"❌ Command failed: {' '.join(str(c) for c in cmd)}")
        sys.exit(1)
    return result


def main():
    print("🧠 Engram Setup Wizard\n")

    # Python version check
    if sys.version_info < (3, 10):
        print("❌ Python 3.10 or higher required.")
        sys.exit(1)

    print(f"✅ Python {sys.version.split()[0]} detected")

    # Create venv
    if not VENV_DIR.exists():
        print("\n📦 Creating virtual environment...")
        run([sys.executable, "-m", "venv", str(VENV_DIR)])
        print("✅ Virtual environment created")
    else:
        print("✅ Virtual environment already exists")

    # Platform-specific pip path
    is_windows = platform.system() == "Windows"
    pip = VENV_DIR / ("Scripts" if is_windows else "bin") / ("pip.exe" if is_windows else "pip")
    python = VENV_DIR / ("Scripts" if is_windows else "bin") / ("python.exe" if is_windows else "python")

    # Install dependencies
    print("\n📦 Installing dependencies (this may take a minute)...")
    run([str(pip), "install", "--upgrade", "pip"], capture_output=True)
    run([str(pip), "install", "-r", str(PROJECT_ROOT / "requirements.txt")])
    print("✅ Dependencies installed")

    # Pre-download embedding model
    print("\n🧠 Pre-downloading embedding model (all-MiniLM-L6-v2, ~80MB)...")
    run([
        str(python), "-c",
        "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2'); print('Model ready.')"
    ])
    print("✅ Embedding model ready")

    # Generate MCP config
    config = {
        "mcpServers": {
            "engram": {
                "command": str(python),
                "args": [str(PROJECT_ROOT / "server.py")]
            }
        }
    }

    config_path = PROJECT_ROOT / "mcp_config.json"
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    print(f"\n✅ MCP config written to: {config_path}")
    print("\n" + "="*50)
    print("🧠 Engram is ready!\n")
    print("Add this to your Claude Desktop / Claude Code config:")
    print(json.dumps(config, indent=2))
    print("\nOr for SSE mode:")
    print(f"  {python} {PROJECT_ROOT / 'server.py'} --transport sse")
    print("\nTo rebuild the search index from JSON files:")
    print(f"  {python} {PROJECT_ROOT / 'server.py'} --rebuild-index")


if __name__ == "__main__":
    main()
