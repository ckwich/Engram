# Phase 5: Session Evaluator - Research

**Researched:** 2026-03-31
**Domain:** Claude Code Stop hook, detached subprocess, pending approval flow, skill auto-load
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Hook script at `C:/Dev/Engram/hooks/engram_stop.py`. Claude Code settings.json points to it with absolute venv Python path.
- **D-02:** Hook reads stdin JSON, checks `stop_hook_active` as absolute first action (exit immediately if true), then spawns evaluator as detached subprocess with `CREATE_NO_WINDOW` flag.
- **D-03:** Evaluator uses `claude.cmd -p` for evaluation (same pattern as Phase 3 indexer). Uses Max plan, zero cost.
- **D-04:** Hook must exit in under 10 seconds. All heavy work happens in the detached subprocess.
- **D-05:** Primary context = `last_assistant_message` from hook payload. Fastest, cheapest, usually contains session outcome.
- **D-06:** Single `claude -p` call with session context + configured criteria. Claude returns structured JSON: `{worth_capturing: bool, confidence: float, draft_key: str, draft_title: str, draft_content: str, draft_tags: list, reasoning: str}`.
- **D-07:** Evaluation prompt includes configured `logic_win_triggers` and `milestone_triggers` from project config.
- **D-08:** Pending file pattern. Evaluator writes draft to `.engram/pending_memories/{date}_{key}.json`. At next session start, a skill checks for pending drafts and presents them for approval.
- **D-09:** Need a `pending-memories` skill at `~/.claude/skills/engram-pending/SKILL.md` that auto-loads on session start and checks for pending drafts.
- **D-10:** Dedup gate (Phase 2) runs before writing the pending file. If near-duplicate exists, include the similar memory info in the pending file so the approval prompt shows it.
- **D-11:** `auto_approve_threshold` is confidence-based. If Claude's confidence >= threshold, store immediately without writing a pending file. Default 0.0 = always ask.
- **D-12:** Pending drafts persist indefinitely until approved or manually deleted. Surface in next session via the pending-memories skill.
- **D-13:** Config lives in per-project `.engram/config.json` `session_evaluator` section. Falls back to Engram global defaults if no project config exists.
- **D-14:** Default criteria: `logic_win_triggers = ["bug resolved", "new capability added", "architectural decision made"]`; `milestone_triggers = ["phase completed", "feature shipped", "significant refactor done"]`; `auto_approve_threshold = 0.0`.

### Claude's Discretion

- Exact evaluation prompt wording and system message
- How to format the pending draft approval presentation in the skill
- Whether to log evaluation results to a file for debugging
- How to handle Claude CLI failures during evaluation (retry once? skip?)
- Pending file naming convention details

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| EVAL-01 | Claude Code Stop hook evaluates completed sessions against configurable criteria | Stop hook stdin JSON schema documented; settings.json registration pattern confirmed from live settings.json |
| EVAL-02 | "Logic Win" triggers: bug resolved, new capability added, architectural decision made (configurable) | D-14 specifies defaults; evaluator prompt must include these from config |
| EVAL-03 | "Milestone" triggers: phase completed, feature shipped, significant refactor done (configurable) | D-14 specifies defaults; same config section as EVAL-02 |
| EVAL-04 | If criteria met, drafts a memory and presents for approval before storing | Pending file pattern (D-08); pending-memories skill (D-09) surfaces at next session start |
| EVAL-05 | Deduplication gate (DEDU-01) runs automatically before approval prompt | `memory_manager._check_dedup()` is sync, callable from evaluator subprocess; returns dict or None |
| EVAL-06 | Criteria configurable per project in `.engram/config.json` session_evaluator section | `load_project_config()` pattern from `engram_index.py` is reusable; falls back to global config.json |
| EVAL-07 | `auto_approve_threshold` of 0.0 = always ask; higher values auto-approve | Confidence field in Claude's JSON response compared to threshold before pending file decision |
| EVAL-08 | Stop hook checks `stop_hook_active` flag to prevent infinite evaluation loops | Confirmed as first-action pattern (D-02); PITFALLS.md Pitfall 6 documents the loop scenario |
| EVAL-09 | Evaluator spawns as detached subprocess — hook exits in under 10 seconds | `CREATE_NO_WINDOW` + `subprocess.Popen` pattern confirmed from `engram_index.py` git hook template |
| EVAL-10 | Always-on for every session (not gated to indexed projects) | Hook registered in `~/.claude/settings.json` (user-level, not project-level); `cwd` from payload used to find per-project config |
</phase_requirements>

---

## Summary

Phase 5 builds three tightly integrated components: (1) a Stop hook entry script (`hooks/engram_stop.py`) that reads stdin JSON, safety-checks `stop_hook_active`, and spawns a detached evaluator subprocess in under 10 seconds; (2) a detached evaluator script (`hooks/engram_evaluator.py`) that calls `claude.cmd -p` with the session context and writes a pending draft file or auto-stores depending on confidence; (3) a `pending-memories` skill at `~/.claude/skills/engram-pending/SKILL.md` that surfaces pending drafts at next session start for human approval.

All patterns needed are already established in the codebase. The `synthesize_domain()` function in `engram_index.py` provides the exact `claude.cmd -p` subprocess pattern with `--output-format json`. The git hook template in the same file provides the `CREATE_NO_WINDOW` detached Popen pattern. The `memory_manager._check_dedup()` and `memory_manager.store_memory()` sync APIs are callable directly from the evaluator subprocess. The `pending-memories` skill differs from the `engramize` skill only in not having `disable-model-invocation: true` — it must auto-load to surface pending drafts without the user invoking it.

**Primary recommendation:** Implement `hooks/engram_stop.py` and `hooks/engram_evaluator.py` as two separate Python scripts. The stop hook is minimal (stdin parse, stop_hook_active check, Popen, exit 0). The evaluator is heavyweight (config load, claude.cmd call, dedup check, file write or store). Registration in `~/.claude/settings.json` requires adding to the existing `Stop` hooks array alongside the current `require_summary.py` hook.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib (`json`, `sys`, `subprocess`, `pathlib`, `datetime`, `os`) | 3.12 (venv) | Hook I/O, subprocess spawn, file paths, JSON parsing | No new deps needed; all existing patterns use stdlib |
| `claude.cmd` | Current npm install | Evaluation inference via Max plan | Already used in `synthesize_domain()` — zero additional cost |
| `core.memory_manager` | Project internal | `store_memory`, `_check_dedup` for dedup gate and auto-approve storage | Sync API; directly importable from evaluator subprocess |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `subprocess.Popen` with `CREATE_NO_WINDOW = 0x08000000` | stdlib | Detached background process on Windows | Always — used by stop hook to spawn evaluator |
| `engram_index.load_project_config()` | Project internal | Load per-project `.engram/config.json` | Evaluator reads session_evaluator section from cwd |
| `json.load(sys.stdin)` | stdlib | Parse Stop hook payload | Always — hook receives JSON on stdin |

### No New Dependencies Required

This phase adds zero new packages to `requirements.txt`. All needed libraries are stdlib or already in the project. The `anthropic` SDK is NOT used — `claude.cmd -p` is used instead (same as Phase 3).

**Installation:** Nothing to install.

**Version verification:**
```bash
C:/Dev/Engram/venv/Scripts/python.exe --version
# Expected: Python 3.12.10
claude.cmd --version
```

---

## Architecture Patterns

### Files to Create

```
C:/Dev/Engram/
├── hooks/
│   ├── engram_stop.py          # Stop hook entry point (minimal, fast exit)
│   └── engram_evaluator.py     # Detached evaluator (heavyweight, background)
~/.claude/skills/
└── engram-pending/
    └── SKILL.md                # Pending memories approval skill
```

Per project (created at runtime by evaluator):
```
{project_root}/.engram/
├── config.json                 # Add session_evaluator section
└── pending_memories/
    └── {date}_{key}.json       # Draft pending approval
```

### Pattern 1: Stop Hook Entry Script

**What:** Reads Stop hook stdin JSON, checks `stop_hook_active` first, spawns detached evaluator, exits 0.
**When to use:** Always — this is the hook entry point.
**Timing constraint:** Must complete in under 10 seconds (D-04). In practice, stdin parse + Popen takes < 1 second.

```python
# Source: engram_index.py HOOK_TEMPLATE + PITFALLS.md Pitfall 6
import json
import os
import subprocess
import sys
from pathlib import Path

def main():
    # CRITICAL: check stop_hook_active FIRST — prevents infinite loop (D-02, PITFALLS Pitfall 6)
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)  # malformed payload — always allow stop

    if payload.get("stop_hook_active"):
        sys.exit(0)  # Claude is already in forced-continuation state — do not block

    # Spawn evaluator as detached subprocess (D-02, D-04)
    VENV_PYTHON = r"C:/Dev/Engram/venv/Scripts/python.exe"
    EVALUATOR = str(Path(__file__).parent / "engram_evaluator.py")
    LOG_FILE = str(Path(__file__).parent.parent / ".engram" / "evaluator.log")

    CREATE_NO_WINDOW = 0x08000000

    try:
        Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as log:
            subprocess.Popen(
                [VENV_PYTHON, EVALUATOR, json.dumps(payload)],
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW,
                close_fds=True,
            )
    except Exception as e:
        pass  # never block the session — fail open

    sys.exit(0)  # always allow Claude to stop

if __name__ == "__main__":
    main()
```

### Pattern 2: Detached Evaluator Script

**What:** Receives payload as argv[1] JSON string. Loads config, calls `claude.cmd -p`, writes pending file or auto-stores.
**When to use:** Always called by `engram_stop.py` as a detached subprocess.
**Key:** Does NOT import chromadb at top level — uses lazy import to avoid startup delays if venv is slow.

```python
# Source: synthesize_domain() in engram_index.py — exact pattern reused
import subprocess, json, sys

def call_evaluator_claude(prompt: str, json_schema: dict) -> dict:
    """Call claude.cmd -p with --json-schema for structured output."""
    result = subprocess.run(
        ["claude.cmd", "-p",
         "--tools", "",
         "--no-session-persistence",
         "--output-format", "json",
         "--json-schema", json.dumps(json_schema),
         "--model", "sonnet"],
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    data = json.loads(result.stdout)
    if data.get("is_error"):
        raise RuntimeError(data.get("result", "unknown error"))
    # result field contains the structured JSON string when --json-schema is used
    return json.loads(data.get("result", "{}"))
```

### Pattern 3: `--json-schema` for Structured Output

**What:** `claude.cmd -p` supports `--json-schema` flag for validated structured output. The `result` field in the `--output-format json` response contains the schema-validated JSON string.
**Confirmed from:** `claude.cmd --help` output (fetched live), which shows:
```
--json-schema <schema>   JSON Schema for structured output validation.
                         Example: {"type":"object","properties":{"name":{"type":"string"}},"required":["name"]}
```

**Evaluation JSON schema to pass:**
```json
{
  "type": "object",
  "properties": {
    "worth_capturing": {"type": "boolean"},
    "confidence": {"type": "number"},
    "draft_key": {"type": "string"},
    "draft_title": {"type": "string"},
    "draft_content": {"type": "string"},
    "draft_tags": {"type": "array", "items": {"type": "string"}},
    "reasoning": {"type": "string"}
  },
  "required": ["worth_capturing", "confidence", "draft_key", "draft_title", "draft_content", "draft_tags", "reasoning"]
}
```

### Pattern 4: Settings.json Hook Registration

**What:** Existing `~/.claude/settings.json` already has a `Stop` hooks array with one entry (`require_summary.py`). The Engram stop hook must be APPENDED to this array, not replace it.

**Confirmed from:** Live read of `C:/Users/colek/.claude/settings.json`.

**Current Stop hooks array:**
```json
"Stop": [
  {
    "matcher": "",
    "hooks": [
      {
        "type": "command",
        "command": "python C:/Users/colek/.claude/Hooks/require_summary.py"
      }
    ]
  }
]
```

**Updated Stop hooks array (append Engram hook):**
```json
"Stop": [
  {
    "matcher": "",
    "hooks": [
      {
        "type": "command",
        "command": "python C:/Users/colek/.claude/Hooks/require_summary.py"
      }
    ]
  },
  {
    "matcher": "",
    "hooks": [
      {
        "type": "command",
        "command": "C:/Dev/Engram/venv/Scripts/python.exe C:/Dev/Engram/hooks/engram_stop.py"
      }
    ]
  }
]
```

**Critical:** Use absolute venv Python path (`C:/Dev/Engram/venv/Scripts/python.exe`) not bare `python`. The Stop hook environment does not guarantee PATH resolution. This is the same lesson as PITFALLS.md Pitfall 5 for git hooks.

**Note:** The existing `require_summary.py` hook runs first (array order). If it blocks, `engram_stop.py` does not run. Both hooks must exit 0 for the session to end normally. The Engram hook always exits 0 (fail-open).

### Pattern 5: Pending File Format

**What:** JSON draft written to `{project_cwd}/.engram/pending_memories/{date}_{key}.json`.
**When:** Evaluator determines `worth_capturing=true` AND confidence < `auto_approve_threshold`.

```python
# Pending file format (D-08, D-10)
pending = {
    "draft_key": result["draft_key"],
    "draft_title": result["draft_title"],
    "draft_content": result["draft_content"],
    "draft_tags": result["draft_tags"],
    "confidence": result["confidence"],
    "reasoning": result["reasoning"],
    "session_id": payload.get("session_id", ""),
    "evaluated_at": datetime.now().astimezone().isoformat(),
    "cwd": payload.get("cwd", ""),
    # Include dedup info if near-duplicate found (D-10)
    "dedup_warning": dup_info,  # None or {"existing_key": ..., "score": ...}
}

# Filename: YYYYMMDD_{key}.json
date_str = datetime.now().strftime("%Y%m%d")
filename = f"{date_str}_{result['draft_key']}.json"
pending_dir = Path(payload["cwd"]) / ".engram" / "pending_memories"
pending_dir.mkdir(parents=True, exist_ok=True)
(pending_dir / filename).write_text(json.dumps(pending, indent=2), encoding="utf-8")
```

### Pattern 6: Pending Memories Skill

**What:** Skill file at `~/.claude/skills/engram-pending/SKILL.md` that auto-loads at session start and checks for pending drafts in the current project's `.engram/pending_memories/` directory.

**Key difference from `engramize` skill:** Does NOT have `disable-model-invocation: true`. Must auto-load so Claude checks for pending drafts without user invocation.

**Does NOT use `paths` field** (not gated to specific file types — should check at session start regardless of what files are open).

```yaml
---
name: engram-pending
description: Check for pending Engram memory drafts at session start. Auto-reviews drafts from previous session evaluations.
allowed-tools: mcp__engram__store_memory
---

[instructions for checking .engram/pending_memories/ and presenting drafts]
```

**CRITICAL:** The skill's `description` must be under 200 characters. Auto-trigger happens when Claude reads the description during context window assembly. The description above is 155 characters.

### Pattern 7: Config Loading with Fallback

**What:** Evaluator reads `session_evaluator` config from `{cwd}/.engram/config.json`, falls back to Engram global defaults (D-13, D-14).

```python
# Reuse load_project_config() pattern from engram_index.py
def load_evaluator_config(cwd: str) -> dict:
    defaults = {
        "logic_win_triggers": [
            "bug resolved", "new capability added", "architectural decision made"
        ],
        "milestone_triggers": [
            "phase completed", "feature shipped", "significant refactor done"
        ],
        "auto_approve_threshold": 0.0,
    }
    config_path = Path(cwd) / ".engram" / "config.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                project_config = json.load(f)
            eval_config = project_config.get("session_evaluator", {})
            defaults.update(eval_config)
        except Exception:
            pass  # fallback to defaults on malformed config
    return defaults
```

### Pattern 8: Dedup Integration in Evaluator

**What:** Before writing a pending file (or auto-storing), evaluator calls `memory_manager._check_dedup()` to detect near-duplicates (EVAL-05, D-10).

**How:** The evaluator subprocess imports from `core.memory_manager` using sys.path manipulation to reach the Engram root.

```python
# Add Engram root to sys.path so evaluator can import core modules
ENGRAM_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ENGRAM_ROOT))

from core.memory_manager import memory_manager, DuplicateMemoryError

# Check dedup before writing pending file
dup_info = memory_manager._check_dedup(draft_content, draft_key)
# dup_info is None (safe to store) or {"status": "duplicate", "existing_key": ..., "score": ...}
```

**Note:** `_check_dedup` is a sync method, appropriate for the evaluator subprocess (not async context).

### Anti-Patterns to Avoid

- **Blocking the stop hook with heavy work:** The hook must Popen and exit in < 10 seconds. Never call `claude.cmd` directly from `engram_stop.py`.
- **Using `python` instead of absolute venv path:** Without the absolute venv Python path, the hook silently fails on Windows because PATH is not inherited from the user shell.
- **Setting `decision: "block"` from the stop hook:** Engram's hook should NEVER return a block decision. It always exits 0. The pending file mechanism is non-blocking by design.
- **Importing chromadb at top of evaluator:** Chromadb startup takes 1-3 seconds. Use lazy import inside the function that needs it.
- **Using `user-invocable: false` on the pending-memories skill:** This would prevent users from invoking it manually. Omit this field entirely.
- **Writing pending files to a fixed path instead of `cwd`:** Each project needs its own `.engram/pending_memories/` to avoid cross-project draft collisions (EVAL-10 requires always-on across all projects).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Structured JSON from claude.cmd | Custom prompt + regex parsing | `--json-schema` flag | Built-in schema validation; confirmed available in live claude.cmd |
| Claude API calls | `anthropic` SDK import | `claude.cmd -p` subprocess | Zero cost (Max plan); same pattern as synthesize_domain() in Phase 3; no SDK dependency |
| Similarity checking | Custom cosine similarity | `memory_manager._check_dedup()` | Already implemented, tested, handles audit log stripping |
| Memory storage | Custom JSON writer | `memory_manager.store_memory()` | Handles chunking, ChromaDB indexing, dedup, audit log |
| Detached subprocess | `threading.Thread` or `asyncio` | `subprocess.Popen` with `CREATE_NO_WINDOW` | Proven pattern from git hook template in `engram_index.py` |
| Config loading | New config system | `load_project_config()` pattern from `engram_index.py` | Established pattern with safe fallback |

**Key insight:** Every heavyweight concern (LLM inference, dedup, storage, structured output) is already solved. This phase is primarily wiring existing components together with correct subprocess lifecycle management.

---

## Common Pitfalls

### Pitfall 1: Stop Hook Infinite Loop (Critical)

**What goes wrong:** Hook calls `claude.cmd -p`, which starts a new Claude session, which triggers the Stop hook again when it finishes, creating infinite recursion.
**Why it happens:** The Stop hook fires on EVERY Claude Code session end, including sessions spawned by subprocesses.
**How to avoid:** Check `stop_hook_active` as the absolute first action — before any other logic, before any logging. If `True`, call `sys.exit(0)` immediately (D-02, PITFALLS Pitfall 6).
**Warning signs:** Sessions that never terminate; increasing log file entries.

### Pitfall 2: Detached Subprocess Dies on Windows Before Completing

**What goes wrong:** The evaluator subprocess is killed by Windows before finishing because the parent process (the hook) has exited.
**Why it happens:** Windows process group inheritance. If the subprocess inherits the parent's process group, it may be killed when the parent exits.
**How to avoid:** Use `CREATE_NO_WINDOW = 0x08000000` combined with `close_fds=True`. This is the established pattern from `engram_index.py` HOOK_TEMPLATE. Do NOT use `DETACHED_PROCESS` (0x00000008) alone — `CREATE_NO_WINDOW` is sufficient and more reliable on Windows for GUI-less subprocesses.
**Testing:** After hook fires, check evaluator.log to confirm the subprocess completed its work.
**Warning signs:** Log file has partial output or no output at all after hook fires.

### Pitfall 3: absolute venv path missing in settings.json registration

**What goes wrong:** Hook registered as `python C:/Dev/Engram/hooks/engram_stop.py` — the `python` command resolves to system Python (3.x without venv packages) or fails entirely.
**Why it happens:** Claude Code launches hooks in its own process environment. The user's shell PATH is not inherited.
**How to avoid:** Register as `C:/Dev/Engram/venv/Scripts/python.exe C:/Dev/Engram/hooks/engram_stop.py`. Same principle as PITFALLS.md Pitfall 5.
**Warning signs:** Hook silently does nothing; no log file entries.

### Pitfall 4: Pending File Written to Wrong Directory

**What goes wrong:** Evaluator uses a hardcoded path for `.engram/pending_memories/` instead of `payload["cwd"]`.
**Why it happens:** Evaluator is always-on across all projects (EVAL-10). The pending file must go into the project that was being worked on, not the Engram project root.
**How to avoid:** Always construct pending directory as `Path(payload["cwd"]) / ".engram" / "pending_memories"`. If `cwd` is missing from payload, fall back to `Path(ENGRAM_ROOT) / ".engram" / "pending_memories"` with a warning in the log.
**Warning signs:** Pending files not found by the skill; drafts accumulating in the wrong project directory.

### Pitfall 5: Low-Quality Session Capture (Noise)

**What goes wrong:** Evaluator captures short Q&A sessions or sessions where the user gave up mid-way.
**Why it happens:** Hook fires for EVERY session, including one-line exchanges.
**How to avoid:** Evaluate `last_assistant_message` length — skip sessions with fewer than 150 words in the message (configurable). Include a minimum quality gate in the evaluation prompt itself: ask Claude to return `worth_capturing: false` for trivial sessions. (PITFALLS Pitfall 10)

### Pitfall 6: Skill Triggers at Wrong Time (or Never)

**What goes wrong (never-triggers):** The `pending-memories` skill description is over 200 chars or is back-loaded with key trigger phrases — Claude truncates the description and the skill never auto-activates.
**What goes wrong (wrong-time):** The skill has `paths` field set, limiting it to specific file types and preventing it from loading when the user opens Claude in a new session.
**How to avoid:** Keep description under 200 chars, front-loaded. Omit the `paths` field entirely — the skill should load based on description match, not file context. (PITFALLS Pitfall 7)

### Pitfall 7: `--json-schema` Output Parsing

**What goes wrong:** When `--json-schema` is used with `--output-format json`, the `result` field in the outer JSON is a JSON string (not a parsed object). Callers that do `data["result"]["worth_capturing"]` get a `TypeError`.
**How to avoid:** Parse in two steps: `outer = json.loads(result.stdout)` then `inner = json.loads(outer["result"])`. This is confirmed from the `--output-format json` structure already used in `synthesize_domain()`.

### Pitfall 8: Dedup Check Blocks Auto-Store Silently

**What goes wrong:** A session produces a genuinely new memory, but `_check_dedup()` returns a near-duplicate warning (score >= 0.92), and the evaluator silently drops the draft without writing a pending file.
**Why it happens:** Dedup is a hard gate in `_prepare_store`. If the evaluator calls `store_memory()` with `force=False`, a `DuplicateMemoryError` is raised.
**How to avoid:** When dedup fires, always write a pending file (never silently drop). Include the duplicate info in the pending file (D-10) so the human can decide. The `force=True` path is then available if the user approves despite the warning.

---

## Code Examples

### Stop Hook Entry (complete minimal implementation)

```python
# Source: CONTEXT.md D-02 + engram_index.py HOOK_TEMPLATE + PITFALLS.md Pitfall 6
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

CREATE_NO_WINDOW = 0x08000000
VENV_PYTHON = r"C:/Dev/Engram/venv/Scripts/python.exe"
ENGRAM_ROOT = Path(__file__).parent.parent
EVALUATOR = str(Path(__file__).parent / "engram_evaluator.py")
LOG_FILE = str(ENGRAM_ROOT / ".engram" / "evaluator.log")


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    # MUST be first — prevents infinite loop
    if payload.get("stop_hook_active"):
        sys.exit(0)

    try:
        Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as log:
            log.write(f"[{datetime.now().isoformat()}] Spawning evaluator for session {payload.get('session_id', '?')}\n")
            subprocess.Popen(
                [VENV_PYTHON, EVALUATOR, json.dumps(payload)],
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW,
                close_fds=True,
            )
    except Exception as e:
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as log:
                log.write(f"[{datetime.now().isoformat()}] Hook spawn error: {e}\n")
        except Exception:
            pass

    sys.exit(0)


if __name__ == "__main__":
    main()
```

### Evaluator: Load Config with Fallback

```python
# Source: load_project_config() in engram_index.py + CONTEXT.md D-13, D-14
def load_evaluator_config(cwd: str) -> dict:
    defaults = {
        "logic_win_triggers": [
            "bug resolved", "new capability added", "architectural decision made"
        ],
        "milestone_triggers": [
            "phase completed", "feature shipped", "significant refactor done"
        ],
        "auto_approve_threshold": 0.0,
    }
    config_path = Path(cwd) / ".engram" / "config.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                project_config = json.load(f)
            defaults.update(project_config.get("session_evaluator", {}))
        except Exception as e:
            print(f"[evaluator] Config load error: {e}. Using defaults.")
    return defaults
```

### Evaluator: claude.cmd call with --json-schema

```python
# Source: synthesize_domain() in engram_index.py — adapted for structured output
EVAL_SCHEMA = {
    "type": "object",
    "properties": {
        "worth_capturing": {"type": "boolean"},
        "confidence": {"type": "number"},
        "draft_key": {"type": "string"},
        "draft_title": {"type": "string"},
        "draft_content": {"type": "string"},
        "draft_tags": {"type": "array", "items": {"type": "string"}},
        "reasoning": {"type": "string"},
    },
    "required": ["worth_capturing", "confidence", "draft_key", "draft_title",
                 "draft_content", "draft_tags", "reasoning"],
}


def evaluate_session(prompt: str) -> dict:
    result = subprocess.run(
        ["claude.cmd", "-p",
         "--tools", "",
         "--no-session-persistence",
         "--output-format", "json",
         "--json-schema", json.dumps(EVAL_SCHEMA),
         "--model", "sonnet"],
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    try:
        outer = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"claude -p returned non-JSON: {result.stdout[:200]}")
    if outer.get("is_error"):
        raise RuntimeError(f"Evaluation failed: {outer.get('result', 'unknown error')}")
    # result field is a JSON string when --json-schema is used
    return json.loads(outer.get("result", "{}"))
```

### Pending-Memories Skill Frontmatter

```yaml
---
name: engram-pending
description: Check for pending Engram memory drafts waiting for approval from recent sessions.
allowed-tools: mcp__engram__store_memory, mcp__engram__search_memories
---
```

Description is 98 characters — well within the 200-character limit. No `paths` field (loads at session start regardless of file context). No `disable-model-invocation` (must auto-load). No `argument-hint` (no arguments needed).

---

## Stop Hook Payload — Confirmed Fields

**Confidence: HIGH** — Verified from STACK.md which cites the official hooks docs directly.

| Field | Type | Description | Use in Phase 5 |
|-------|------|-------------|----------------|
| `session_id` | string | Unique session identifier | Stored in pending file for traceability |
| `transcript_path` | string | Absolute path to JSONL transcript file | Available for deeper analysis (D-05 says `last_assistant_message` is preferred, but transcript is available as fallback) |
| `cwd` | string | Working directory of the Claude Code session | Used to find per-project `.engram/config.json` and write pending file to correct project |
| `stop_hook_active` | bool | True if Claude is in forced-continuation state | Must be checked FIRST — exit 0 immediately if true |
| `last_assistant_message` | string | Content of Claude's final response | Primary evaluation context (D-05) — fastest, cheapest |

**Transcript file persistence:** The `transcript_path` JSONL file persists on disk after the session ends. It is not deleted when Claude Code stops. The evaluator subprocess (running after the hook exits) can safely read this file.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Using `anthropic` SDK for synthesis | `claude.cmd -p` subprocess | Phase 3 D-01 pivot | Zero cost on Max plan; eliminates SDK dependency |
| Sync subprocess in hook | Detached Popen (non-blocking) | Phase 3 git hook pattern | Hook exits in < 1 second regardless of evaluator duration |
| Global skill triggering via `paths` | Description-based auto-load | Phase 1 skill research | Skill auto-loads on session start without file-type gating |

**Deprecated/outdated:**
- `anthropic.Anthropic().messages.create()` for this phase: Not used — `claude.cmd -p` is the established pattern.
- `DETACHED_PROCESS` flag (0x00000008): `CREATE_NO_WINDOW` (0x08000000) is preferred and confirmed working in engram_index.py.

---

## Open Questions

1. **Does `require_summary.py` block if it fails?**
   - What we know: It's in the Stop hooks array as the first hook. If it returns a non-zero exit or a block decision, our hook never runs.
   - What's unclear: The exact behavior of `require_summary.py` — whether it ever blocks sessions.
   - Recommendation: Test hook order in a real session before assuming our hook fires every time. Consider adding a note in the registration step to verify both hooks fire.

2. **Transcript file path on Windows — forward slashes or backslashes?**
   - What we know: `transcript_path` is provided by Claude Code in the hook payload. Claude Code runs on Windows.
   - What's unclear: Whether the path uses Windows backslashes or forward slashes.
   - Recommendation: Use `Path(payload["transcript_path"])` (pathlib normalizes separators) rather than string splitting. This is defensive coding, not a blocker.

3. **Skill auto-load timing: does `engram-pending` load BEFORE or AFTER the user's first message?**
   - What we know: Skills without `paths` load based on description matching in the context assembly phase. Sessions start with skill listing.
   - What's unclear: Whether the skill fires at session initialization or after the first user message.
   - Recommendation: The skill body should instruct Claude to check for pending files immediately and present them — the auto-load description should say "at session start" to make the trigger clear. If timing is unreliable, the user can always say "check pending memories" as a fallback.

4. **Does `--json-schema` in `claude.cmd` guarantee the result is valid JSON matching the schema?**
   - What we know: The `--json-schema` flag is confirmed in the live `claude.cmd --help` output. It "validates" the output.
   - What's unclear: Whether validation failures cause an error response or silently return malformed output.
   - Recommendation: Always wrap `json.loads(outer["result"])` in a try/except and fall back to `worth_capturing: false` on parse failure. Never crash the evaluator on a malformed LLM response.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.12 (venv) | Both hook scripts | Yes | 3.12.10 at `C:/Dev/Engram/venv/Scripts/python.exe` | — |
| `claude.cmd` | Evaluator inference | Yes | npm global install at `/c/Users/colek/AppData/Roaming/npm/claude.cmd` | — |
| `core.memory_manager` | Dedup + auto-store | Yes | Project internal; importable via sys.path | — |
| `~/.claude/settings.json` | Hook registration | Yes | Exists; has existing Stop hooks array | — |
| `anthropic` SDK | — | Not installed in venv | — | Not needed (claude.cmd used instead) |

**Missing dependencies with no fallback:** None — all required components confirmed available.

**Missing dependencies with fallback:** None.

**Manual step required:** Registration in `~/.claude/settings.json` must append to existing `Stop` hooks array (not replace). This is a manual task in the plan — the evaluator cannot register itself.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (project existing) |
| Config file | None detected — see Wave 0 |
| Quick run command | `C:/Dev/Engram/venv/Scripts/python.exe -m pytest tests/test_evaluator.py -x -q` |
| Full suite command | `C:/Dev/Engram/venv/Scripts/python.exe -m pytest tests/ -q` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| EVAL-08 | `stop_hook_active: true` causes immediate exit 0 | unit | `pytest tests/test_engram_stop.py::test_stop_hook_active_exits -x` | No — Wave 0 |
| EVAL-09 | Hook exits in < 10s even when evaluator is slow | unit | `pytest tests/test_engram_stop.py::test_hook_exits_fast -x` | No — Wave 0 |
| EVAL-01 | Hook reads stdin JSON and spawns evaluator subprocess | unit | `pytest tests/test_engram_stop.py::test_hook_spawns_evaluator -x` | No — Wave 0 |
| EVAL-06 | Evaluator reads per-project config with correct fallback | unit | `pytest tests/test_engram_evaluator.py::test_config_load_fallback -x` | No — Wave 0 |
| EVAL-07 | `auto_approve_threshold=0.0` always writes pending file | unit | `pytest tests/test_engram_evaluator.py::test_auto_approve_threshold -x` | No — Wave 0 |
| EVAL-05 | Dedup gate runs; near-duplicate included in pending file | unit | `pytest tests/test_engram_evaluator.py::test_dedup_gate -x` | No — Wave 0 |
| EVAL-04 | Pending file written with correct structure and fields | unit | `pytest tests/test_engram_evaluator.py::test_pending_file_written -x` | No — Wave 0 |
| EVAL-10 | Pending file written to cwd/.engram/pending_memories/ | unit | `pytest tests/test_engram_evaluator.py::test_pending_file_location -x` | No — Wave 0 |
| EVAL-02/03 | Triggers present in evaluation prompt | unit | `pytest tests/test_engram_evaluator.py::test_prompt_includes_triggers -x` | No — Wave 0 |
| EVAL-01 (e2e) | Full stop hook fires in real Claude session | manual | Manual — run a test session and check evaluator.log | — |

### Sampling Rate

- **Per task commit:** `pytest tests/test_engram_stop.py tests/test_engram_evaluator.py -x -q`
- **Per wave merge:** `pytest tests/ -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_engram_stop.py` — covers EVAL-01, EVAL-08, EVAL-09
- [ ] `tests/test_engram_evaluator.py` — covers EVAL-02 through EVAL-07, EVAL-10
- [ ] `tests/conftest.py` — shared fixtures (sample payload dict, temp pending_memories dir)
- [ ] No framework install needed — pytest already used in prior phases

---

## Project Constraints (from CLAUDE.md)

No `CLAUDE.md` found at `C:/Dev/Engram/CLAUDE.md`. Applying project-level constraints from STATE.md accumulated decisions:

- All phases: Sonnet for all Claude API synthesis calls (applies here — `--model sonnet` in evaluator).
- Phase 3: Cost controls (token budget, dry-run) are non-optional — evaluator logs every claude.cmd invocation.
- Phase 5 (carried forward): `stop_hook_active` check is absolute first action in `engram_stop.py`.
- All phases: Absolute venv Python paths — no PATH dependency on Windows.
- All phases: Forward slashes in paths and glob patterns.
- Phase 3: Skill frontmatter `paths` uses forward slashes via `.replace("\\", "/")` — applies to `engram-pending` skill if `paths` is ever added.

---

## Sources

### Primary (HIGH confidence)

- **Live `~/.claude/settings.json`** — Confirmed existing Stop hooks array format; confirmed `matcher: ""` syntax; confirmed absolute paths used for other hooks; confirmed Engram hook must be appended not replacing.
- **`engram_index.py` (project codebase)** — `synthesize_domain()` confirms exact `claude.cmd -p --output-format json --tools "" --no-session-persistence` pattern; HOOK_TEMPLATE confirms `CREATE_NO_WINDOW` + `Popen` + `close_fds=True` detached subprocess pattern.
- **`core/memory_manager.py` (project codebase)** — `_check_dedup()` sync signature and return format confirmed; `store_memory()` sync API confirmed; `DuplicateMemoryError` structure confirmed.
- **`.planning/research/STACK.md`** — Stop hook payload fields (`session_id`, `transcript_path`, `cwd`, `stop_hook_active`, `last_assistant_message`) confirmed from official docs with HIGH confidence label.
- **`.planning/research/PITFALLS.md`** — Pitfall 6 (infinite loop) confirmed with prevention pattern; Pitfall 7 (skill truncation) confirmed with 200-char limit.
- **`~/.claude/skills/engramize/SKILL.md`** — Confirmed skill frontmatter format, `disable-model-invocation: true` vs omitted for auto-load, `allowed-tools` syntax.
- **Live `claude.cmd --help` output** — Confirmed `--json-schema` flag availability, `--output-format json` behavior, `--tools ""` and `--no-session-persistence` flags.

### Secondary (MEDIUM confidence)

- **STATE.md accumulated decisions** — Confirmed `stop_hook_active` first-action convention; confirmed absolute venv Python path requirement.
- **`.engram/config.json` (live file)** — Confirmed project config format for `domains` section; `session_evaluator` section does not exist yet (needs to be added in Phase 5).

### Tertiary (LOW confidence)

- **Skill auto-load timing at session start** — Behavior when `paths` field is omitted and description triggers auto-load is inferred from STACK.md / PITFALLS.md documentation but not directly tested in this project. Flag as needing session-level verification.

---

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — all components verified in live codebase and running environment
- Architecture patterns: HIGH — exact code patterns confirmed from `engram_index.py` and `memory_manager.py`
- Stop hook payload: HIGH — verified from STACK.md citing official docs; confirmed via settings.json live read
- `--json-schema` flag: HIGH — confirmed from live `claude.cmd --help` output
- Skill auto-load behavior: MEDIUM — consistent with docs but not tested in this project
- Subprocess survival on Windows: MEDIUM — `CREATE_NO_WINDOW` pattern confirmed from codebase; full survival test recommended during implementation (flagged in STATE.md blockers)

**Research date:** 2026-03-31
**Valid until:** 2026-04-30 (stable domain — Claude Code hooks API changes slowly)
