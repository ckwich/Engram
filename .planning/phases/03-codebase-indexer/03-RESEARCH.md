# Phase 3: Codebase Indexer — Research

**Researched:** 2026-03-31
**Domain:** Python CLI tool + Claude Code CLI subprocess + git post-commit hook (Windows)
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Use Claude Code CLI (`claude -p`) instead of Anthropic API for synthesis. User is on Max 20x plan — no extra cost. Eliminates anthropic SDK dependency entirely.
- **D-02:** Model is Sonnet via CLI. Configurable per project in `.engram/config.json` `model` field.
- **D-03:** Context assembled = planning artifacts (PROJECT.md, ROADMAP.md, AGENTS.md, plan.md from configurable `planning_paths`) + domain source files (from `file_globs`).
- **D-04:** Output format is structured markdown: ## Architecture, ## Key Decisions, ## Patterns, ## Watch Out For.
- **D-05:** Cost controls = estimate CLI invocation count and preview what would be synthesized. `--dry-run` shows domain count, file count per domain, estimated context size. No `max_tokens_per_run` needed.
- **D-06:** Interactive domain setup on first run. Auto-detect candidates from directory structure, present via `claude -p` interactive session, user confirms/edits, config written to `.engram/config.json`.
- **D-07:** Standalone init command: `engram_index.py --project X --init` for just the config setup step. Bootstrap mode runs init automatically if no config exists.
- **D-08:** Config format: `{project_name, domains: {name: {file_globs, questions}}, planning_paths, model, max_file_size_kb}`.
- **D-09:** Default synthesis questions: "What is the architecture?", "What key decisions were made?", "What patterns are used?", "What should someone watch out for?"
- **D-10:** CLI-assisted domain setup is part of the init flow within `engram_index.py` itself.
- **D-11:** Glob-based context injection. Skill description tells Claude to search Engram for domain context when editing files matching the domain's globs. `disable-model-invocation` NOT set (skill auto-loads into context).
- **D-12:** Skill files always overwritten on re-index — auto-generated thin pointers, no backup needed.
- **D-13:** Skill naming: `{project}-{domain}-context` installed at `~/.claude/skills/{project}-{domain}-context/SKILL.md`.
- **D-14:** Skill body instructs Claude to call `search_memories` and `retrieve_memory` with the domain's memory key, NOT to embed content.
- **D-15:** Hook installed via: `engram_index.py --project X --install-hook` writes to `{project}/.git/hooks/post-commit`.
- **D-16:** Background evolve: hook spawns evolve as detached background process. Commit is NOT blocked. Output to `.engram/last_evolve.log`.
- **D-17:** Absolute venv Python path in hook script — no PATH dependency on Windows.
- **D-18:** SHA256 per-file hash tracking in `.engram/index.json` manifest. Evolve compares current hashes to manifest, re-synthesizes only domains with changed files.
- **D-19:** Manual edit protection: if a memory's `updated_at` is newer than the last index run, skip re-synthesis unless `--force` is passed.
- **D-20:** Memory keys use underscores: `codebase_{project}_{domain}_architecture`.

### Claude's Discretion

- Exact synthesis prompt wording and system message
- How to handle files exceeding `max_file_size_kb` (truncate or skip)
- Whether to use `related_to` to link domain memories to each other
- Error handling for CLI subprocess failures
- Log formatting for `.engram/last_evolve.log`

### Deferred Ideas (OUT OF SCOPE)

- `--watch` mode for continuous indexing (v2)
- AST/call graph parsing (explicitly out of scope)
- Multi-language support (v2)

</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| INDX-01 | `engram_index.py` CLI tool synthesizes architectural understanding from codebases into Engram memories | CLI entry point with argparse, imports `memory_manager` directly |
| INDX-02 | Model B architecture — captures why, what was learned, what to watch out for | D-04 synthesis output format + D-09 default questions |
| INDX-03 | Per-project config at `{project_root}/.engram/config.json` with configurable domain questions | Config schema from D-08; `_load_config()` pattern from `memory_manager.py` |
| INDX-04 | Memory namespace: `codebase/{project}/{domain}/architecture` | D-20 clarifies: use underscores → `codebase_{project}_{domain}_architecture` |
| INDX-05 | Two outputs per domain: Engram memory AND thin skill file at `~/.claude/skills/` triggering retrieval | Skill format verified against official docs; `paths` field drives auto-load |
| INDX-06 | Skill files never contain content directly — Engram is always source of truth | D-14 — skill body calls `search_memories`, not embedding content |
| INDX-07 | Index manifest at `{project}/.engram/index.json` tracks file hashes for incremental re-indexing | SHA256 via `hashlib` (stdlib); verified working pattern |
| INDX-08 | Bootstrap mode — reads planning artifacts + source files, full synthesis pass | `claude -p` subprocess with assembled context via stdin |
| INDX-09 | Evolve mode — hash-compares files since last run, re-synthesizes only changed domains | SHA256 manifest diff; `git diff --name-only HEAD~1 HEAD` for changed files |
| INDX-10 | Full mode — complete re-index of everything | Same as bootstrap but skips init; always overwrites regardless of `updated_at` |
| INDX-11 | Git post-commit hook for automatic evolve mode on changed files only | Python-shebang hook verified working on Windows Git for Windows 2.53 |
| INDX-12 | Hook uses absolute venv Python path (no PATH dependency on Windows) | Verified: `/c/Dev/Engram/venv/Scripts/python.exe` shebang works in Git Bash |
| INDX-13 | Manual edits to Engram memories win over re-index unless `--force` is passed | D-19 — compare `updated_at` vs last-run timestamp from `index.json` |
| INDX-14 | CLI supports `--project`, `--mode`, `--domain`, `--dry-run`, `--watch` flags | `argparse` standard pattern; `--watch` is deferred (stub only if needed) |
| INDX-15 | ~~Synthesis uses Sonnet via anthropic SDK~~ → **SUPERSEDED by D-01**: use `claude -p --model sonnet` | No anthropic SDK; CLI subprocess confirmed working |
| INDX-16 | ~~Cost controls: token budget per run~~ → **SUPERSEDED by D-05**: `--dry-run` shows invocation count + context size estimate | File size sum in KB is the dry-run metric; no token counting API needed |

</phase_requirements>

---

## Summary

Phase 3 builds `engram_index.py`, a standalone Python CLI that synthesizes architectural understanding from codebases and stores it as Engram memories. The major architectural pivot (D-01) eliminates the Anthropic SDK dependency in favor of the Claude Code CLI (`claude -p`), which the user can invoke at no marginal cost on their Max 20x subscription.

The synthesis flow is: collect domain files via glob patterns from `.engram/config.json`, assemble context (planning artifacts + source files) into a single stdin prompt, invoke `claude -p --model sonnet --tools "" --no-session-persistence` as a subprocess, capture stdout as structured markdown, and store via `memory_manager.store_memory()`. The JSON output format (`--output-format json`) is preferred over text for reliable error detection via the `is_error` field, since `claude -p` always exits with code 0 even on errors.

The git hook is a Python script with a `/c/Dev/Engram/venv/Scripts/python.exe` shebang (verified working on Windows Git 2.53). The hook spawns `engram_index.py --mode evolve` as a detached background process via `subprocess.Popen` with `CREATE_NO_WINDOW = 0x08000000` and immediately exits 0 to never block commits.

**Primary recommendation:** Use `subprocess.run(['claude.cmd', '-p', '--tools', '', '--no-session-persistence', '--output-format', 'json', '--model', model], input=prompt, capture_output=True, text=True, encoding='utf-8')` for synthesis. Parse `result.stdout` as JSON; check `data['is_error']` for failure; extract `data['result']` as the synthesized text.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `subprocess` | 3.12 (stdlib) | Invoke `claude -p` for synthesis | No new dependency; subprocess.run + capture_output=True is the pattern |
| Python stdlib `hashlib` | 3.12 (stdlib) | SHA256 per-file hashing for manifest | Already used in `memory_manager.py` (`_key_hash`); sha256 is more collision-resistant than md5 |
| Python stdlib `pathlib` | 3.12 (stdlib) | File discovery via `glob()` and `rglob()` | Already used throughout project; cross-platform |
| Python stdlib `argparse` | 3.12 (stdlib) | CLI argument parsing | Used in `server.py`; consistent project pattern |
| Python stdlib `json` | 3.12 (stdlib) | `index.json` manifest + config parsing | Consistent with JSON flat file storage pattern |
| `core.memory_manager` | project-local | `store_memory()` / `retrieve_memory()` | Direct import (sync API); no MCP round-trip needed |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pathspec` | `>=0.12.1` | Gitignore-aware file filtering | Optional; use if glob-only approach proves insufficient. NOT installed in venv — install if needed. |
| `subprocess` git commands | stdlib | `git diff --name-only`, `git ls-files` | Use for evolve mode changed-file detection; simpler than pathspec for gitignore awareness |

### No New Dependencies Required

This phase requires **zero new packages** added to `requirements.txt`. All synthesis work is done via the already-installed `claude` CLI. The `pathspec` library is optional if `git ls-files` proves sufficient.

**Current `requirements.txt`:**
```
fastmcp~=3.1.1
sentence-transformers~=5.3.0
chromadb~=1.5.5
flask~=3.1.3
```

**Optional addition if needed:**
```bash
# Only if git ls-files proves insufficient for gitignore handling:
venv/Scripts/python.exe -m pip install "pathspec>=0.12.1"
```

---

## Architecture Patterns

### Recommended Project Structure

```
C:/Dev/Engram/
├── engram_index.py          # NEW: main CLI entry point (sibling of server.py)
├── core/
│   └── memory_manager.py    # Reuse: store_memory (sync), retrieve_memory
├── .engram/                 # Created per-project (in each indexed project, not Engram root)
│   ├── config.json          # Domain config: project_name, domains, planning_paths, model
│   ├── index.json           # Manifest: {file_path: sha256, last_run: ISO timestamp, memories: {domain: key}}
│   └── last_evolve.log      # Hook output log (append-only)
└── [indexed project]/
    ├── .engram/             # Per-project config lives here
    ├── .git/hooks/
    │   └── post-commit      # Auto-generated Python hook script
    └── ...
```

### Pattern 1: claude -p Synthesis Subprocess

**What:** Assemble domain context as a single string, pipe to `claude -p` via stdin, capture stdout as JSON, extract `.result` field as synthesized markdown.

**When to use:** Every synthesis call (bootstrap, evolve, full modes).

**Verified invocation (Windows — must use `claude.cmd`):**
```python
# Source: verified by running against claude 2.1.91 on Windows
import subprocess, json

def synthesize_domain(prompt: str, model: str = "sonnet") -> str:
    """
    Invoke claude -p to synthesize architectural understanding.
    Returns synthesized text or raises RuntimeError on failure.

    IMPORTANT: On Windows, use 'claude.cmd' not 'claude'.
    shutil.which('claude') returns the .cmd path on Windows.
    subprocess with shell=False requires 'claude.cmd' explicitly.
    """
    result = subprocess.run(
        ["claude.cmd", "-p",
         "--tools", "",                    # disable all tools — text synthesis only
         "--no-session-persistence",       # isolated run, no history accumulation
         "--output-format", "json",        # structured output for reliable error detection
         "--model", model],
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,                       # 2-minute timeout per synthesis call
    )
    # NOTE: claude -p ALWAYS exits 0, even on error. Must check is_error in JSON.
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"claude -p returned non-JSON: {result.stdout[:200]}")

    if data.get("is_error"):
        raise RuntimeError(f"Synthesis failed: {data.get('result', 'unknown error')}")

    return data.get("result", "")
```

**Key findings from live testing:**
- `claude -p` always exits with code 0, even for invalid models or auth errors
- `is_error: true` in JSON output signals failure; `result` field contains the error message
- `--output-format text` gives clean stdout with no extra noise; JSON format wraps in structured object
- `--tools ""` disables all tools (file access, bash, etc.) — required for safe synthesis-only use
- `--no-session-persistence` prevents context accumulation across synthesis runs
- Default model is `claude-opus-4-6`; must pass `--model sonnet` to get `claude-sonnet-4-6`
- Large stdin (~29KB) works reliably — tested with no truncation or timeout issues
- stderr is completely silent on successful runs

### Pattern 2: SHA256 Manifest for Incremental Re-indexing

**What:** Track per-file SHA256 hashes in `.engram/index.json`. Evolve mode computes current hashes, diffs against manifest, identifies changed domains.

**When to use:** Every evolve mode run (and to update manifest after any synthesis).

```python
# Source: verified Python 3.12 stdlib pattern
import hashlib
from pathlib import Path

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
    manifest["last_run"] = datetime.now().astimezone().isoformat()
    with open(engram_dir / "index.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
```

**Manifest schema:**
```json
{
  "last_run": "2026-03-31T10:00:00+00:00",
  "files": {
    "core/memory_manager.py": "abc123...",
    "server.py": "def456..."
  },
  "memories": {
    "storage": "codebase_engram_storage_architecture",
    "api": "codebase_engram_api_architecture"
  }
}
```

### Pattern 3: Git Post-Commit Hook (Windows)

**What:** Python script with absolute venv shebang. Spawns evolve as detached background process. Always exits 0 to never block commits.

**When to use:** Written by `--install-hook` command; Git triggers it automatically on every commit.

```python
# Source: verified working on Windows Git 2.53 / Git Bash
# Written to: {project}/.git/hooks/post-commit (no .py extension, must be executable)

HOOK_TEMPLATE = """\
#!/c/Dev/Engram/venv/Scripts/python.exe
\"\"\"Engram post-commit hook: run evolve mode in background after each commit.\"\"\"
import subprocess, sys, os
from pathlib import Path

VENV_PYTHON = r"{venv_python}"
ENGRAM_INDEX = r"{engram_index}"
PROJECT_ROOT = r"{project_root}"
ENGRAM_DIR = Path(PROJECT_ROOT) / ".engram"
ENGRAM_DIR.mkdir(exist_ok=True)
LOG_FILE = str(ENGRAM_DIR / "last_evolve.log")

CREATE_NO_WINDOW = 0x08000000  # Windows flag: no console window

try:
    with open(LOG_FILE, "a", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [VENV_PYTHON, ENGRAM_INDEX, "--mode", "evolve", "--project", PROJECT_ROOT],
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW,
            close_fds=True,
        )
    sys.exit(0)
except Exception as e:
    with open(LOG_FILE, "a", encoding="utf-8") as log:
        log.write(f"Hook spawn error: {{e}}\\n")
    sys.exit(0)  # NEVER block commits — fail open
"""
```

**Critical details:**
- The shebang must use forward slashes and `/c/` not `C:/`: `#!/c/Dev/Engram/venv/Scripts/python.exe`
- The hook file must have executable permission (set via `os.chmod(hook_path, 0o755)` from the installer)
- `CREATE_NO_WINDOW = 0x08000000` prevents a console window flash on Windows
- The hook body is a format string; `venv_python`, `engram_index`, `project_root` are filled at install time
- Verified: Python-shebang hooks execute correctly in Git Bash on Windows Git 2.53

### Pattern 4: Skill File Generation

**What:** Write thin SKILL.md files to `~/.claude/skills/{project}-{domain}-context/SKILL.md`. Skill auto-loads into Claude's context when the user edits files matching the `paths` glob patterns.

**When to use:** After every domain synthesis (bootstrap, full, evolve for changed domains).

**Verified skill frontmatter fields** (from official Claude Code skills docs, fetched 2026-03-31):

```yaml
---
name: {project}-{domain}-context
description: "{project} {domain} architectural context. Use when editing {domain} files to get current architecture, decisions, and patterns."
paths: {comma-separated glob patterns from domain config}
allowed-tools: mcp__engram__search_memories, mcp__engram__retrieve_memory
---

When working with {domain} files in the {project} project, search Engram for architectural context:

1. Call mcp__engram__search_memories with query "{domain} architecture patterns decisions" to find relevant memories
2. If results include key `{memory_key}`, call mcp__engram__retrieve_memory(key="{memory_key}") for full context
3. Use this architectural context to inform your work — patterns, decisions, and known pitfalls

The authoritative architecture memory for this domain is: `{memory_key}`
```

**Key frontmatter facts (verified from official docs):**
- `disable-model-invocation` defaults to `false` — do NOT set it to `true` for auto-loading context skills (D-11)
- `paths` field accepts comma-separated glob patterns; limits when skill auto-activates to matching files
- `paths` uses forward slashes even on Windows (PITFALLS.md Pitfall 14)
- `user-invocable` defaults to `true` — keep default (user can also invoke `/project-domain-context` manually)
- `allowed-tools` grants the listed tools without per-use approval during skill execution
- Description is front-loaded with trigger keywords; kept under 200 chars to avoid truncation
- Full skill content only loads when invoked; description is always in context

### Anti-Patterns to Avoid

- **Never use `claude` (without `.cmd`) in subprocess on Windows:** `subprocess.run(['claude', ...])` raises `FileNotFoundError` on Windows. Use `['claude.cmd', ...]` or detect via `shutil.which('claude')` which returns the `.cmd` path.
- **Never trust exit code from `claude -p`:** It always exits 0. Use `--output-format json` and check `data['is_error']`.
- **Never use `#!/usr/bin/env python` in git hooks on Windows:** The git hook environment's PATH does not include the venv. Use the absolute venv python path as the shebang.
- **Never block commits in post-commit hook:** Wrap all hook logic in `try/except` and always `sys.exit(0)`.
- **Never store skill content directly:** Skill body must call `search_memories` / `retrieve_memory` — Engram is the source of truth (D-14, INDX-06).
- **Never use backslashes in `paths` glob patterns:** Always forward slashes, even on Windows (PITFALLS.md Pitfall 14).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| LLM synthesis | Custom Anthropic SDK client | `claude -p` subprocess | User is on Max plan; no marginal API cost; CLI handles auth, retries, model selection |
| File change detection | Custom watcher / inotify | SHA256 hash comparison against `index.json` manifest | Simpler, works offline, no new dependency, cross-platform |
| Gitignore filtering | Custom `.gitignore` parser | `git ls-files --cached` or `pathlib.glob()` with exclusion patterns | `git ls-files` uses git's own parser; glob with explicit excludes (`.git`, `venv`) covers most cases |
| Git hook framework | Shell script orchestration | Simple Python script with absolute shebang | One hook, one repo; no `pre-commit`, no `husky`; verified pattern for Windows |
| Token counting | Anthropic token count API | Character/file size estimation for `--dry-run` | No API cost; file size in KB is a good enough proxy for dry-run estimates |
| Cosine similarity for dedup | Custom embedding comparison | `memory_manager._check_dedup()` already exists | Already implemented in Phase 2; indexer just calls `store_memory(force=False)` |
| Config validation | Custom JSON schema library | `dict.get()` with defaults (existing project pattern) | Consistent with `_load_config()` in `memory_manager.py` |

**Key insight:** The project deliberately minimizes dependencies (zero new packages in phases 1, 2, 4, 5, 6). Phase 3 follows this pattern — the claude CLI is pre-existing infrastructure, not an added dependency.

---

## Common Pitfalls

### Pitfall 1: `claude` Not Found as Subprocess on Windows

**What goes wrong:** `subprocess.run(['claude', '-p', ...])` raises `FileNotFoundError: [WinError 2]` because `claude` is a `.cmd` file on Windows, not a `.exe`.

**Why it happens:** On Windows, npm installs `claude` as `claude.cmd` in `C:\Users\{user}\AppData\Roaming\npm\`. The `.cmd` extension is not executable directly via `CreateProcess` without the shell.

**How to avoid:**
```python
import shutil
CLAUDE_CMD = shutil.which("claude") or "claude.cmd"
# shutil.which("claude") returns the .cmd path on Windows
result = subprocess.run([CLAUDE_CMD, "-p", ...], ...)
```

**Warning signs:** `FileNotFoundError` on first synthesis call.

---

### Pitfall 2: Exit Code Always 0 — Cannot Detect Failure Without JSON Parsing

**What goes wrong:** `result.returncode == 0` even when claude fails (invalid model, auth error, quota exceeded). Code treats failed synthesis as success.

**Why it happens:** `claude -p` is designed for scripting and always returns 0. The error information is in the JSON payload.

**How to avoid:** Always use `--output-format json` and check `data['is_error']`:
```python
data = json.loads(result.stdout)
if data.get("is_error"):
    raise RuntimeError(f"Synthesis failed: {data['result']}")
```

**Warning signs:** Empty or error-message memories stored to Engram silently.

---

### Pitfall 3: Git Hook PATH Does Not Include venv (Windows)

**What goes wrong:** `python engram_index.py` in the hook script resolves to system Python (not venv), which cannot import `chromadb`, `sentence_transformers`, or other venv-only packages.

**Why it happens:** Git for Windows executes hooks in a minimal bash environment. `PATH` inside git hooks does not include the venv's `Scripts/` directory.

**How to avoid:**
- Use the absolute venv Python path as the shebang: `#!/c/Dev/Engram/venv/Scripts/python.exe`
- This is the shebang path format for Git Bash on Windows (forward slashes, `/c/` not `C:/`)
- Verified working on Git 2.53.0.windows.1

**Warning signs:** Hook runs (log file gets created) but Python import errors appear in the log.

---

### Pitfall 4: Memory `updated_at` vs. Last-Run Comparison for Manual Edit Protection

**What goes wrong:** Evolve mode overwrites memories that the user has manually edited, discarding human refinements.

**Why it happens:** Without a timestamp check, every evolve run calls `store_memory(force=True)` unconditionally.

**How to avoid (D-19):**
```python
# Check before synthesizing
existing = memory_manager.retrieve_memory(memory_key)
last_run = manifest.get("last_run")
if existing and last_run:
    if existing["updated_at"] > last_run:
        print(f"[Engram] Skipping {domain}: memory was manually edited after last index run.")
        continue
# Only synthesize if not manually edited (or --force was passed)
```

**Warning signs:** Users complain that their memory edits don't persist.

---

### Pitfall 5: Large Files Cause Context Window Issues

**What goes wrong:** Assembling all domain files into a single stdin prompt exceeds the practical context window, or synthesis quality degrades with too much code.

**Why it happens:** A domain might include large files (e.g., a 5,000-line generated file, or binary files accidentally matched by glob).

**How to avoid:**
- Apply `max_file_size_kb` threshold from config (default recommendation: 100KB); skip or truncate files over the limit
- Log which files were skipped so the user can tune their globs
- For truncation: include first N characters with `# [TRUNCATED at {max_size}KB — {file_size}KB total]` marker
- For dry-run: report total context size estimate so user can tune before running

---

### Pitfall 6: `.engram/` Directory in Wrong Location

**What goes wrong:** `engram_index.py --project /path/to/project` creates `.engram/` inside the Engram tool's own directory instead of inside the indexed project's directory.

**Why it happens:** Relative path resolution if `--project` is not converted to an absolute Path immediately.

**How to avoid:**
```python
project_root = Path(args.project).resolve()  # absolute, resolves symlinks
engram_dir = project_root / ".engram"
engram_dir.mkdir(exist_ok=True)
```

---

### Pitfall 7: Hook Installation Requires Executable Permission on Windows

**What goes wrong:** `post-commit` file is written but git does not execute it because the file is not marked executable.

**Why it happens:** Windows NTFS does not use Unix permissions, but Git for Windows tracks the executable bit in the index. The file must have its executable bit set for git to recognize it as a hook.

**How to avoid:**
```python
import os, stat
hook_path.write_text(hook_content, encoding="utf-8")
# Set executable bit so git recognizes it as a hook
hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
```

---

## Code Examples

Verified patterns from live testing.

### 1. Detecting and Invoking Claude CLI

```python
# Source: verified against Claude Code 2.1.91 on Windows
import shutil, subprocess, json

def get_claude_cmd() -> str:
    """Find the claude CLI command. On Windows, must use claude.cmd."""
    cmd = shutil.which("claude")
    if not cmd:
        raise RuntimeError(
            "claude CLI not found. Install from: https://claude.ai/code\n"
            "Ensure npm is in PATH and Claude Code is installed globally."
        )
    return cmd  # returns full path including .cmd extension on Windows

def run_synthesis(prompt: str, model: str = "sonnet", timeout: int = 120) -> str:
    """
    Run synthesis via claude -p. Returns synthesized text.
    Raises RuntimeError on failure (is_error=true in JSON response).
    """
    claude_cmd = get_claude_cmd()
    result = subprocess.run(
        [claude_cmd, "-p",
         "--tools", "",
         "--no-session-persistence",
         "--output-format", "json",
         "--model", model],
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )
    data = json.loads(result.stdout)
    if data.get("is_error"):
        raise RuntimeError(f"claude -p error: {data.get('result', 'unknown')}")
    return data["result"]
```

### 2. File Collection for Domain Context

```python
# Source: verified with pathlib on Python 3.12, Windows
from pathlib import Path

def collect_domain_files(
    project_root: Path,
    file_globs: list[str],
    max_file_size_kb: int = 100,
    exclude_dirs: set = None,
) -> list[Path]:
    """Collect files matching domain globs, respecting size and exclusion limits."""
    if exclude_dirs is None:
        exclude_dirs = {".git", "venv", "__pycache__", "node_modules", ".engram"}

    found = set()
    for pattern in file_globs:
        # Support both 'src/*.py' (relative) and '**/*.py' (recursive)
        if "**" in pattern:
            matches = project_root.rglob(pattern.lstrip("**/"))
        else:
            matches = project_root.glob(pattern)
        for match in matches:
            # Exclude dirs
            if any(part in exclude_dirs for part in match.parts):
                continue
            if not match.is_file():
                continue
            size_kb = match.stat().st_size / 1024
            if size_kb > max_file_size_kb:
                print(f"[Engram] Skipping {match.name} ({size_kb:.0f}KB > {max_file_size_kb}KB limit)")
                continue
            found.add(match)
    return sorted(found)
```

### 3. Assembling Synthesis Prompt

```python
# Source: verified pattern for claude -p stdin context assembly
def build_synthesis_prompt(
    project_name: str,
    domain: str,
    questions: list[str],
    planning_files: list[Path],
    source_files: list[Path],
) -> str:
    """Assemble the full synthesis prompt as a single string for stdin."""
    sections = [
        f"# Codebase Synthesis Task\n\n"
        f"Project: {project_name}\n"
        f"Domain: {domain}\n\n"
        "You are analyzing a codebase to create architectural documentation. "
        "Respond with structured markdown covering the questions below. "
        "Focus on WHY decisions were made, not just WHAT the code does.\n\n"
        "## Questions to Answer\n\n"
    ]
    for q in questions:
        sections.append(f"- {q}\n")

    sections.append("\n## Output Format\n\n"
        "Use exactly these section headers:\n\n"
        "## Architecture\n## Key Decisions\n## Patterns\n## Watch Out For\n\n")

    if planning_files:
        sections.append("## Planning Artifacts\n\n")
        for path in planning_files:
            content = path.read_text(encoding="utf-8", errors="replace")
            sections.append(f"### {path.name}\n\n{content}\n\n")

    if source_files:
        sections.append("## Source Files\n\n")
        for path in source_files:
            content = path.read_text(encoding="utf-8", errors="replace")
            sections.append(f"### {path.relative_to(path.parent.parent)}\n\n```\n{content}\n```\n\n")

    return "".join(sections)
```

### 4. Memory Key Convention

```python
# Source: D-20 — underscores throughout
def make_memory_key(project: str, domain: str) -> str:
    """
    Generate canonical memory key per D-20.
    Format: codebase_{project}_{domain}_architecture
    All lowercase, underscores only, no hyphens.
    """
    project = project.lower().replace("-", "_").replace(" ", "_")
    domain = domain.lower().replace("-", "_").replace(" ", "_")
    return f"codebase_{project}_{domain}_architecture"

def make_memory_title(project: str, domain: str) -> str:
    """Generate human-readable title per engramize skill conventions."""
    return f"{project.title()} — {domain.title()} Architecture"
```

### 5. Storing Synthesized Memory

```python
# Source: memory_manager.py store_memory signature (verified from codebase)
# Use force=True because indexer overwrites are intentional (not duplicate content)
def store_domain_memory(
    memory_manager,  # imported singleton from core.memory_manager
    key: str,
    content: str,
    project: str,
    domain: str,
) -> dict:
    """Store synthesized domain memory. Returns stored memory metadata."""
    return memory_manager.store_memory(
        key=key,
        content=content,
        title=make_memory_title(project, domain),
        tags=[project, domain, "architecture", "indexer"],
        force=True,  # indexer writes always override dedup gate
    )
```

---

## State of the Art

| Old Approach (STACK.md) | Current Approach (CONTEXT.md D-01) | When Changed | Impact |
|-------------------------|-------------------------------------|--------------|--------|
| `anthropic` SDK + `AsyncAnthropic().messages.create()` | `claude -p` subprocess | 2026-04-03 (CONTEXT.md) | No new dependency; subscription-based; no cost tracking needed |
| `max_tokens_per_run` cost control | `--dry-run` invocation count estimate | 2026-04-03 | Simpler; no token counting API call |
| `asyncio` synthesis loop | Synchronous `subprocess.run()` | 2026-04-03 | `engram_index.py` is a standalone CLI script, not an async server |

**Superseded items from STACK.md Phase 3 section:**
- "New dependency: anthropic SDK" — SUPERSEDED by D-01
- "`AsyncAnthropic().messages.create()`" — SUPERSEDED by D-01
- "Rate limiting: `asyncio.sleep(0.5)` between calls" — not needed; CLI handles this internally

---

## Open Questions

1. **How does `--init` interactive flow work via `claude -p`?**
   - What we know: D-06 says "present to user via `claude -p` interactive session, user confirms/edits"
   - What's unclear: `claude -p` is non-interactive (print mode). The init flow may need to be a regular interactive `claude` session, or a simpler Python `input()` prompt loop.
   - Recommendation: Implement init as a Python-driven Q&A: enumerate candidate domains from directory structure, print them, use `input()` for user confirmation, write config. Reserve `claude -p` for synthesis only, not interactive flows. This is simpler and more reliable than a nested `claude` session.

2. **How to handle the `--project` path for the Engram repo itself?**
   - What we know: `engram_index.py` will be at `C:/Dev/Engram/engram_index.py`. Running `--project C:/Dev/Engram` would index the Engram codebase itself.
   - What's unclear: Whether this self-indexing scenario needs special handling.
   - Recommendation: No special case needed. The tool is project-agnostic; self-indexing is a valid use case.

3. **JSONL transcript format for Phase 5 evaluator**
   - What we know: STATE.md flags this as a blocker: "JSONL transcript format for Phase 5 evaluator parsing should be documented while implementing Phase 3. Verify against Claude Code docs before Phase 5."
   - What's unclear: The exact JSONL format of the session transcript file provided to stop hooks.
   - Recommendation: This is Phase 5 research scope. Flag as a Phase 3 deliverable: add a note to `last_evolve.log` that the JSONL format is pending research for Phase 5.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python (venv) | `engram_index.py` runtime | Yes | 3.12.10 at `C:/Dev/Engram/venv/Scripts/python.exe` | — |
| `claude` CLI | Synthesis subprocess | Yes | 2.1.91 (Claude Code) at `C:\Users\colek\AppData\Roaming\npm\claude.cmd` | — |
| `git` | Evolve mode changed-file detection | Yes | 2.53.0.windows.1 | Fall back to full manifest diff if git unavailable |
| `hashlib` | SHA256 manifest | Yes | stdlib 3.12 | — |
| `subprocess` | CLI invocation, hook spawn | Yes | stdlib 3.12 | — |
| `pathlib` | File discovery | Yes | stdlib 3.12 | — |
| `core.memory_manager` | Memory storage | Yes | Phase 2 complete | — |
| `pathspec` | Gitignore-aware filtering | No | NOT installed | Use `git ls-files` or `pathlib.glob` with explicit excludes |
| `pytest` | Test framework | No | NOT installed | Install: `venv/Scripts/python.exe -m pip install pytest` |

**Missing dependencies with no fallback:**
- None — all required dependencies are available.

**Missing dependencies with fallback:**
- `pathspec`: Use `git ls-files --cached` + `pathlib.glob()` with `exclude_dirs` set instead. Only install if gitignore accuracy becomes a problem.
- `pytest`: Install before Wave 0 test creation: `venv/Scripts/python.exe -m pip install pytest`

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (not yet installed) |
| Config file | None — Wave 0 creates `pytest.ini` |
| Quick run command | `venv/Scripts/python.exe -m pytest tests/ -x -q` |
| Full suite command | `venv/Scripts/python.exe -m pytest tests/ -v` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| INDX-01 | `engram_index.py` is importable and has `main()` | unit | `pytest tests/test_indexer.py::test_cli_import -x` | No — Wave 0 |
| INDX-02 | Synthesis output contains required sections | unit | `pytest tests/test_indexer.py::test_synthesis_output_format -x` | No — Wave 0 |
| INDX-03 | Config loads from `.engram/config.json` with correct defaults | unit | `pytest tests/test_indexer.py::test_config_load -x` | No — Wave 0 |
| INDX-04 | `make_memory_key("engram", "storage")` → `"codebase_engram_storage_architecture"` | unit | `pytest tests/test_indexer.py::test_memory_key_format -x` | No — Wave 0 |
| INDX-05 | Skill file written to correct path with correct frontmatter | unit | `pytest tests/test_indexer.py::test_skill_file_written -x` | No — Wave 0 |
| INDX-06 | Skill file body does not contain synthesized content | unit | `pytest tests/test_indexer.py::test_skill_no_content -x` | No — Wave 0 |
| INDX-07 | SHA256 hash correctly computed and stored in manifest | unit | `pytest tests/test_indexer.py::test_sha256_manifest -x` | No — Wave 0 |
| INDX-08 | Bootstrap mode runs synthesis and stores memory | integration | `pytest tests/test_indexer.py::test_bootstrap_mode -x -s` | No — Wave 0 |
| INDX-09 | Evolve mode re-synthesizes only changed domains | unit | `pytest tests/test_indexer.py::test_evolve_only_changed -x` | No — Wave 0 |
| INDX-10 | Full mode re-synthesizes all domains regardless of hashes | unit | `pytest tests/test_indexer.py::test_full_mode -x` | No — Wave 0 |
| INDX-11 | Hook file written to `.git/hooks/post-commit` | unit | `pytest tests/test_indexer.py::test_hook_installed -x` | No — Wave 0 |
| INDX-12 | Hook file contains absolute venv Python path as shebang | unit | `pytest tests/test_indexer.py::test_hook_shebang -x` | No — Wave 0 |
| INDX-13 | Evolve skips domain if memory `updated_at` > `last_run` | unit | `pytest tests/test_indexer.py::test_manual_edit_protection -x` | No — Wave 0 |
| INDX-14 | `--dry-run` prints domain/file counts but does not synthesize | unit | `pytest tests/test_indexer.py::test_dry_run -x` | No — Wave 0 |
| INDX-15 | CLI subprocess uses `--model sonnet` flag | unit | `pytest tests/test_indexer.py::test_model_flag -x` | No — Wave 0 |
| INDX-16 | `--dry-run` shows estimated context size in KB | unit | `pytest tests/test_indexer.py::test_dry_run_context_size -x` | No — Wave 0 |

### Sampling Rate

- **Per task commit:** `venv/Scripts/python.exe -m pytest tests/test_indexer.py -x -q`
- **Per wave merge:** `venv/Scripts/python.exe -m pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_indexer.py` — all 16 test functions listed above
- [ ] `tests/conftest.py` — shared fixtures: temp project dir, mock memory_manager, mock synthesis subprocess
- [ ] `pytest.ini` — minimal config (testpaths, addopts)
- [ ] Framework install: `venv/Scripts/python.exe -m pip install pytest`

**Note on integration tests:** `test_bootstrap_mode` requires a live `claude -p` call. Mark with `@pytest.mark.integration` and skip by default. Run explicitly with `pytest -m integration` only when validating end-to-end behavior.

---

## Project Constraints (from CLAUDE.md)

No project-specific `CLAUDE.md` found at `C:/Dev/Engram/CLAUDE.md`. Applying global constraints.

**From global `~/.claude/CLAUDE.md`:**
- Search Engram for context at session start (done — no Phase 3-specific memories found yet)
- Store session digests after significant work
- Store memories after each change and decision

**From `.planning/research/PITFALLS.md` (project conventions, treated as constraints):**
- All paths must use forward slashes or `os.path.join`
- Windows: absolute venv Python path for any subprocess that imports project packages
- `paths` glob patterns in skill frontmatter must use forward slashes (Pitfall 14)

---

## Sources

### Primary (HIGH confidence)

- **Claude Code Skills docs** (`https://code.claude.com/docs/en/skills`) — fetched 2026-03-31. Frontmatter reference table, invocation control semantics, `paths` field behavior, `disable-model-invocation` semantics.
- **Live `claude --help` output** — verified 2026-03-31 against Claude Code 2.1.91. All flags and output formats confirmed.
- **Live subprocess testing** — verified 2026-03-31: `claude.cmd` invocation, JSON output format, `is_error` field, `--tools ""`, `--no-session-persistence`, `--model sonnet`, large stdin handling (~29KB), clean stdout/stderr.
- **`core/memory_manager.py`** — `store_memory()` signature, `_key_hash()` pattern, sync API confirmed for CLI use.
- **`C:/Dev/Engram/venv/Scripts/python.exe`** — exists, Python 3.12.10, can serve as hook shebang.
- **Git 2.53.0.windows.1** — Python-shebang hooks execute correctly in Git Bash (verified).

### Secondary (MEDIUM confidence)

- **`.planning/research/PITFALLS.md`** — Windows git hook pitfalls, skill file format pitfalls (researched 2026-03-29, still applicable)
- **`.planning/research/STACK.md`** — existing Phase 3 stack section (partially superseded by D-01 pivot; hashlib, pathlib, subprocess patterns remain valid)

### Tertiary (LOW confidence — needs validation at implementation time)

- **`subprocess.Popen` with `CREATE_NO_WINDOW`** — tested with a proxy process; not tested with actual `engram_index.py` (doesn't exist yet). Pattern is correct but the specific flag may need verification on the target machine.

---

## Metadata

**Confidence breakdown:**
- `claude -p` invocation mechanics: HIGH — live tested with actual Claude Code 2.1.91
- Skill frontmatter `paths` field: HIGH — official docs fetched 2026-03-31
- Git hook Python shebang on Windows: HIGH — verified working in Git Bash 2.53
- `CREATE_NO_WINDOW` detached subprocess: HIGH — verified with proxy process
- Memory key convention: HIGH — from D-20 (CONTEXT.md)
- Synthesis prompt format: MEDIUM — pattern is sound but exact wording is Claude's Discretion

**Research date:** 2026-03-31
**Valid until:** 2026-04-30 (stable — stdlib + verified CLI; skill docs may change faster)
