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


# ── Memory key helper ────────────────────────────────────────────────────────

def memory_key(project_name: str, domain_name: str) -> str:
    """Per D-20: use underscores. codebase_{project}_{domain}_architecture"""
    safe_project = project_name.lower().replace("-", "_").replace(" ", "_")
    safe_domain = domain_name.lower().replace("-", "_").replace(" ", "_")
    return f"codebase_{safe_project}_{safe_domain}_architecture"


# ── Edit protection ──────────────────────────────────────────────────────────

def is_manually_edited(key: str, last_run: Optional[str]) -> bool:
    """
    Returns True if the memory was manually edited after the last index run.
    Per D-19: compare memory's updated_at against manifest last_run.
    If last_run is None (first run), treat all memories as not manually edited.
    """
    if last_run is None:
        return False
    from core.memory_manager import memory_manager
    existing = memory_manager.retrieve_memory(key)
    if existing is None:
        return False
    return existing.get("updated_at", "") > last_run


# ── Domain synthesis + storage ───────────────────────────────────────────────

def index_domain(
    project_root: Path,
    config: dict,
    domain_name: str,
    domain_config: dict,
    manifest: dict,
    force: bool = False,
    dry_run: bool = False,
) -> bool:
    """
    Synthesize one domain and store the result in Engram.
    Returns True if synthesis was performed, False if skipped.
    """
    project_name = config.get("project_name", project_root.name)
    key = memory_key(project_name, domain_name)
    model = config.get("model", DEFAULT_MODEL)

    if dry_run:
        # Dry-run: report what WOULD be synthesized
        max_kb = config.get("max_file_size_kb", DEFAULT_MAX_FILE_SIZE_KB)
        domain_files = collect_domain_files(project_root, domain_config, max_kb)
        total_kb = sum(f.stat().st_size / 1024 for f in domain_files)
        print(f"  [dry-run] {domain_name}: {len(domain_files)} files, ~{total_kb:.1f}KB context")
        return False

    # Lazy import — only when actually synthesizing (avoids chromadb dependency for dry-run)
    from core.memory_manager import memory_manager, DuplicateMemoryError

    # Manual edit protection (INDX-13 / D-19): skip if memory was manually edited
    last_run = manifest.get("last_run")
    if not force and is_manually_edited(key, last_run):
        print(f"  [skip] {domain_name}: memory manually edited after last run (use --force to override)")
        return False

    print(f"  Synthesizing {domain_name}...")
    prompt = assemble_context(project_root, config, domain_name, domain_config)

    try:
        synthesized = synthesize_domain(prompt, model=model)
    except RuntimeError as e:
        print(f"  [error] {domain_name}: synthesis failed — {e}")
        return False

    if not synthesized.strip():
        print(f"  [error] {domain_name}: empty synthesis result")
        return False

    title = f"{project_name.title()} — {domain_name.title()} Architecture"
    tags = [project_name.lower(), domain_name.lower(), "architecture", "codebase"]

    # Collect related domains (other domains already in manifest memories)
    related = [v for k, v in manifest.get("memories", {}).items() if k != domain_name]

    try:
        memory_manager.store_memory(
            key=key,
            content=synthesized,
            tags=tags,
            title=title,
            related_to=related[:10],
            force=force,
        )
        manifest.setdefault("memories", {})[domain_name] = key
        print(f"  [ok] {domain_name} -> {key}")
        return True
    except DuplicateMemoryError as e:
        print(f"  [dup] {domain_name}: {e}. Pass --force to overwrite.")
        return False
    except ValueError as e:
        print(f"  [error] {domain_name}: {e}")
        return False


# ── Changed-domain detection ─────────────────────────────────────────────────

def find_changed_domains(project_root: Path, config: dict, manifest: dict) -> list[str]:
    """
    Compare current file hashes to manifest. Return domain names with any changed files.
    Also updates manifest['files'] with current hashes for all domain files.
    """
    max_kb = config.get("max_file_size_kb", DEFAULT_MAX_FILE_SIZE_KB)
    changed_domains = []
    stored_hashes = manifest.get("files", {})
    new_hashes = {}

    for domain_name, domain_config in config.get("domains", {}).items():
        domain_changed = False
        for f in collect_domain_files(project_root, domain_config, max_kb):
            rel = str(f.relative_to(project_root)).replace("\\", "/")
            current_hash = sha256_file(f)
            new_hashes[rel] = current_hash
            if stored_hashes.get(rel) != current_hash:
                domain_changed = True
        if domain_changed:
            changed_domains.append(domain_name)

    manifest["files"] = new_hashes
    return changed_domains


# ── Mode runners ─────────────────────────────────────────────────────────────

def run_bootstrap(project_root: Path, config: dict, domain_filter: Optional[str], force: bool, dry_run: bool):
    """Bootstrap: synthesize all configured domains."""
    engram_dir = project_root / ".engram"
    engram_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(engram_dir)

    domains = config.get("domains", {})
    if domain_filter:
        domains = {k: v for k, v in domains.items() if k == domain_filter}
        if not domains:
            print(f"Domain '{domain_filter}' not found in config.")
            sys.exit(1)

    print(f"Bootstrap: indexing {len(domains)} domain(s) in {project_root.name}")
    success = 0
    for domain_name, domain_config in domains.items():
        if index_domain(project_root, config, domain_name, domain_config, manifest, force, dry_run):
            success += 1

    if not dry_run:
        # Update file hashes in manifest after bootstrap
        _ = find_changed_domains(project_root, config, manifest)
        save_manifest(engram_dir, manifest)
        print(f"\nDone. {success}/{len(domains)} domains synthesized.")


def run_evolve(project_root: Path, config: dict, domain_filter: Optional[str], force: bool, dry_run: bool):
    """Evolve: re-synthesize only domains with changed files."""
    engram_dir = project_root / ".engram"
    engram_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(engram_dir)

    changed = find_changed_domains(project_root, config, manifest)

    if domain_filter:
        changed = [d for d in changed if d == domain_filter]

    if not changed:
        print("Evolve: no changed domains detected.")
        if not dry_run:
            save_manifest(engram_dir, manifest)
        return

    print(f"Evolve: {len(changed)} changed domain(s): {', '.join(changed)}")
    success = 0
    for domain_name in changed:
        domain_config = config["domains"][domain_name]
        if index_domain(project_root, config, domain_name, domain_config, manifest, force, dry_run):
            success += 1

    if not dry_run:
        save_manifest(engram_dir, manifest)
        print(f"\nDone. {success}/{len(changed)} domains re-synthesized.")


def run_full(project_root: Path, config: dict, domain_filter: Optional[str], force: bool, dry_run: bool):
    """Full re-index: synthesizes everything. Treats as force=True for edit protection (INDX-10)."""
    engram_dir = project_root / ".engram"
    engram_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(engram_dir)

    domains = config.get("domains", {})
    if domain_filter:
        domains = {k: v for k, v in domains.items() if k == domain_filter}

    print(f"Full re-index: {len(domains)} domain(s) in {project_root.name}")
    success = 0
    for domain_name, domain_config in domains.items():
        # full mode always overwrites — pass force=True regardless of --force flag
        if index_domain(project_root, config, domain_name, domain_config, manifest, force=True, dry_run=dry_run):
            success += 1

    if not dry_run:
        _ = find_changed_domains(project_root, config, manifest)
        save_manifest(engram_dir, manifest)
        print(f"\nDone. {success}/{len(domains)} domains synthesized.")


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

    project_root = Path(args.project).resolve()
    if not project_root.exists():
        print(f"Error: project path does not exist: {project_root}")
        sys.exit(1)

    # --init: run interactive setup only, then exit
    if args.init:
        run_init(project_root)
        return

    # --install-hook: install git post-commit hook, then exit
    if args.install_hook:
        # Implemented in Plan 02 — stub for now
        print("--install-hook: not yet implemented (Plan 02)")
        return

    # Load config (bootstrap auto-inits if missing per D-07)
    config = load_project_config(project_root)
    if config is None:
        if args.mode == "bootstrap":
            print("No .engram/config.json found. Running interactive setup first.\n")
            config = run_init(project_root)
        else:
            print(f"Error: no .engram/config.json found in {project_root}. Run --init first.")
            sys.exit(1)

    if not args.mode:
        print("Error: --mode is required (bootstrap, evolve, full). Or use --init or --install-hook.")
        sys.exit(1)

    if args.mode == "bootstrap":
        run_bootstrap(project_root, config, args.domain, args.force, args.dry_run)
    elif args.mode == "evolve":
        run_evolve(project_root, config, args.domain, args.force, args.dry_run)
    elif args.mode == "full":
        run_full(project_root, config, args.domain, args.force, args.dry_run)


if __name__ == "__main__":
    main()
