#!/usr/bin/env python
"""
engram_index.py — Codebase indexer for Engram.

Synthesizes architectural understanding from codebases into Engram memories.
Three modes: bootstrap (full synthesis, auto-inits config), evolve (changed domains only),
full (complete re-index, skips edit protection).

Usage:
  python engram_index.py --project C:/Dev/MyProject --mode bootstrap
  python engram_index.py --project C:/Dev/MyProject --mode evolve
  python engram_index.py --project C:/Dev/MyProject --mode full --force
  python engram_index.py --project C:/Dev/MyProject --init
  python engram_index.py --project C:/Dev/MyProject --install-hook
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Constants ────────────────────────────────────────────────────────────────

ENGRAM_ROOT = Path(__file__).parent  # C:/Dev/Engram/
DEFAULT_MODEL = "sonnet"
DEFAULT_MAX_FILE_SIZE_KB = 100
DEFAULT_PLANNING_PATHS = ["PROJECT.md", "ROADMAP.md", "AGENTS.md"]
DEFAULT_QUESTIONS = [
    "What is the architecture of this domain?",
    "What key decisions were made and why?",
    "What patterns are established and reused?",
    "What should a developer watch out for?",
]


# ── Config functions ─────────────────────────────────────────────────────────

def load_project_config(project_root: Path) -> Optional[dict]:
    """Load per-project .engram/config.json. Returns None if missing."""
    config_path = project_root / ".engram" / "config.json"
    if not config_path.exists():
        return None
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config: {e}", file=sys.stderr)
        return None


def save_project_config(project_root: Path, config: dict) -> None:
    """Write per-project .engram/config.json. Creates .engram/ dir if needed."""
    engram_dir = project_root / ".engram"
    engram_dir.mkdir(parents=True, exist_ok=True)
    with open(engram_dir / "config.json", "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


# ── Manifest functions ───────────────────────────────────────────────────────

def sha256_file(path: Path) -> str:
    """Compute SHA256 hash of file contents. Uses 64KB chunks for memory efficiency."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(engram_dir: Path) -> dict:
    """Load .engram/index.json or return empty manifest."""
    manifest_path = engram_dir / "index.json"
    if manifest_path.exists():
        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"files": {}, "last_run": None, "memories": {}}


def save_manifest(engram_dir: Path, manifest: dict) -> None:
    """Save .engram/index.json with updated last_run timestamp."""
    manifest["last_run"] = datetime.now().astimezone().isoformat()
    engram_dir.mkdir(parents=True, exist_ok=True)
    with open(engram_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


# ── File collection ──────────────────────────────────────────────────────────

def collect_domain_files(project_root: Path, domain_config: dict, max_file_size_kb: int) -> list[Path]:
    """Collect files matching domain globs, skip oversized files with a warning."""
    files = []
    for pattern in domain_config.get("file_globs", []):
        for path in sorted(project_root.glob(pattern)):
            if not path.is_file():
                continue
            size_kb = path.stat().st_size / 1024
            if size_kb > max_file_size_kb:
                print(f"  [skip] {path.relative_to(project_root)} ({size_kb:.0f}KB > {max_file_size_kb}KB limit)")
                continue
            files.append(path)
    return files


# ── Context assembly ─────────────────────────────────────────────────────────

def assemble_context(project_root: Path, config: dict, domain_name: str, domain_config: dict) -> str:
    """Assemble synthesis prompt from planning artifacts + domain source files."""
    parts = []

    # Planning artifacts
    for rel_path in config.get("planning_paths", DEFAULT_PLANNING_PATHS):
        p = project_root / rel_path
        if p.exists():
            parts.append(f"=== {rel_path} ===\n{p.read_text(encoding='utf-8', errors='replace')}")

    # Domain source files
    max_kb = config.get("max_file_size_kb", DEFAULT_MAX_FILE_SIZE_KB)
    domain_files = collect_domain_files(project_root, domain_config, max_kb)
    for f in domain_files:
        rel = f.relative_to(project_root)
        parts.append(f"=== {rel} ===\n{f.read_text(encoding='utf-8', errors='replace')}")

    questions = domain_config.get("questions", DEFAULT_QUESTIONS)
    question_block = "\n".join(f"- {q}" for q in questions)

    prompt = (
        f"You are analyzing the '{domain_name}' domain of the "
        f"'{config.get('project_name', project_root.name)}' project.\n\n"
        f"Below is the project context (planning artifacts and source files).\n\n"
        f"{''.join(chr(10) + p for p in parts)}\n\n"
        f"---\n\n"
        f"Based on this context, answer these questions:\n{question_block}\n\n"
        f"Format your response as structured markdown with these sections "
        f"(include only those that apply):\n\n"
        f"## Architecture\n"
        f"The structural design: how components are organized, why they're organized that way.\n\n"
        f"## Key Decisions\n"
        f"Important choices made during development and the reasoning behind them.\n\n"
        f"## Patterns\n"
        f"Reusable approaches, conventions, and techniques used in this domain.\n\n"
        f"## Watch Out For\n"
        f"Edge cases, pitfalls, gotchas, and non-obvious behaviors to be aware of.\n\n"
        f"Write for a developer reading this cold, with no prior context. Explain WHY, not just WHAT."
    )
    return prompt


# ── Synthesis subprocess ─────────────────────────────────────────────────────

def synthesize_domain(prompt: str, model: str = "sonnet") -> str:
    """
    Invoke claude -p to synthesize architectural understanding.
    Returns synthesized text or raises RuntimeError on failure.

    On Windows, uses 'claude.cmd' (subprocess with shell=False requires the .cmd extension).
    """
    result = subprocess.run(
        ["claude.cmd", "-p",
         "--tools", "",
         "--no-session-persistence",
         "--output-format", "json",
         "--model", model],
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"claude -p returned non-JSON: {result.stdout[:200]}")

    if data.get("is_error"):
        raise RuntimeError(f"Synthesis failed: {data.get('result', 'unknown error')}")

    return data.get("result", "")


# ── Init flow ────────────────────────────────────────────────────────────────

def run_init(project_root: Path) -> dict:
    """Interactive domain setup via Python input() prompts. Writes .engram/config.json."""
    print(f"\n=== Engram Indexer Setup for {project_root.name} ===\n")

    project_name = input(f"Project name [{project_root.name}]: ").strip() or project_root.name

    # Auto-detect candidate domains from top-level directories
    candidates = [
        d.name for d in sorted(project_root.iterdir())
        if d.is_dir()
        and not d.name.startswith(".")
        and d.name not in ("node_modules", "__pycache__", "venv", ".git", "dist", "build")
    ]
    if candidates:
        print(f"\nDetected potential domains: {', '.join(candidates)}")

    print("\nDefine domains to index. Enter one domain per prompt. Press Enter with empty name to finish.")

    domains = {}
    while True:
        name = input("\nDomain name (or Enter to finish): ").strip().lower()
        if not name:
            break
        default_globs = f"{name}/**/*.py" if (project_root / name).is_dir() else "**/*.py"
        globs_input = input(f"  File globs (comma-separated) [{default_globs}]: ").strip()
        globs = [g.strip() for g in globs_input.split(",")] if globs_input else [default_globs]
        print(f"  Using default synthesis questions. Add custom questions? (leave blank to use defaults)")
        custom_q = input("  Custom questions (semicolon-separated, or blank): ").strip()
        questions = [q.strip() for q in custom_q.split(";")] if custom_q else DEFAULT_QUESTIONS
        domains[name] = {"file_globs": globs, "questions": questions}

    if not domains:
        print("No domains defined. Add at least one domain to use the indexer.")
        sys.exit(1)

    model = input(f"\nModel [sonnet]: ").strip() or DEFAULT_MODEL

    planning_rel = input(f"Planning paths (comma-separated) [{', '.join(DEFAULT_PLANNING_PATHS)}]: ").strip()
    planning_paths = [p.strip() for p in planning_rel.split(",")] if planning_rel else DEFAULT_PLANNING_PATHS

    config = {
        "project_name": project_name,
        "model": model,
        "max_file_size_kb": DEFAULT_MAX_FILE_SIZE_KB,
        "planning_paths": planning_paths,
        "domains": domains,
    }

    save_project_config(project_root, config)
    print(f"\nConfig written to {project_root / '.engram' / 'config.json'}")
    return config


# ── CLI argument parser ──────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Engram Codebase Indexer")
    p.add_argument("--project", required=True, help="Absolute path to project root")
    p.add_argument("--mode", choices=["bootstrap", "evolve", "full"],
                   help="Indexing mode (required unless --init or --install-hook)")
    p.add_argument("--domain", help="Limit to a single domain name")
    p.add_argument("--dry-run", action="store_true",
                   help="Show what would be synthesized without making API calls")
    p.add_argument("--force", action="store_true",
                   help="Override manual edit protection and dedup gate")
    p.add_argument("--init", action="store_true",
                   help="Run interactive domain setup only (no synthesis)")
    p.add_argument("--install-hook", action="store_true",
                   help="Install git post-commit hook in the project")
    return p


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = build_parser()
    args = parser.parse_args()
    print("Not yet implemented")


if __name__ == "__main__":
    main()
