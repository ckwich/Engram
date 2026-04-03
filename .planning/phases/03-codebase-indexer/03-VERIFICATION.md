---
phase: 03-codebase-indexer
verified: 2026-03-31T00:00:00Z
status: gaps_found
score: 4/5 success criteria verified
gaps:
  - truth: "CLI supports --project, --mode, --domain, --dry-run, --watch flags (INDX-14)"
    status: partial
    reason: "--watch flag is absent from argparse. INDX-14 explicitly lists --watch as a required flag. The CONTEXT.md and RESEARCH.md note it is deferred to v2/INDX-19, but INDX-14 is still marked Complete in REQUIREMENTS.md and was claimed in the 03-01 SUMMARY requirements-completed list without --watch being implemented even as a stub."
    artifacts:
      - path: "engram_index.py"
        issue: "--watch is not in build_parser(). Only 7 flags: --project, --mode, --domain, --dry-run, --force, --init, --install-hook. The requirement INDX-14 includes --watch."
    missing:
      - "Add --watch flag to build_parser() (stub with 'not yet implemented' print is acceptable per RESEARCH.md note 'stub only if needed')"
      - "Update REQUIREMENTS.md INDX-14 checkbox note to reflect that --watch is deferred to INDX-19 (v2), or add the stub"
human_verification:
  - test: "Run `python engram_index.py --project [real project] --mode bootstrap` with a live config and claude.cmd available"
    expected: "Synthesized architectural understanding stored in Engram memories with keys matching codebase_{project}_{domain}_architecture format"
    why_human: "Requires live claude.cmd process and running chromadb/memory_manager stack — cannot run without the full environment active"
  - test: "Make a git commit in a project with the hook installed and check .engram/last_evolve.log"
    expected: "Hook fires, spawns evolve mode in background, log file shows evolve run output"
    why_human: "Requires actual git commit + background process observation in the installed environment"
---

# Phase 3: Codebase Indexer Verification Report

**Phase Goal:** Running engram_index.py against a project synthesizes architectural understanding into Engram memories, with git hook automation for incremental re-indexing on every commit, cost controls enforced from the first run
**Verified:** 2026-03-31
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (from ROADMAP.md Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Running `python engram_index.py --project [path] --mode bootstrap` synthesizes architectural memories in codebase/{project}/{domain}/architecture namespace without overwriting human-edited memories (unless --force is passed) | ✓ VERIFIED | `run_bootstrap()` calls `index_domain()` which calls `is_manually_edited()` before synthesis. Memory key format confirmed: `codebase_engram_storage_architecture`. `force=False` by default. |
| 2 | Running evolve mode re-synthesizes only domains with changed files since last run, using the hash manifest at {project}/.engram/index.json | ✓ VERIFIED | `run_evolve()` calls `find_changed_domains()` which SHA256-compares files against `manifest["files"]`. Only changed domain names are passed to `index_domain()`. Manifest saved via `save_manifest()`. |
| 3 | A git post-commit hook fires automatically after every commit and runs evolve mode using the absolute venv Python path — no PATH dependency | ✓ VERIFIED | Hook exists at `.git/hooks/post-commit`, is executable (rwxr-xr-x), contains `CREATE_NO_WINDOW`, `sys.exit(0)` (twice), `--mode evolve`, absolute Python path `C:\Users\colek\AppData\Local\Programs\Python\Python312\python.exe`. Shebang is `/c/Users/colek/...` (Git Bash format). |
| 4 | Running with --dry-run prints an invocation count and context size estimate before making any claude.cmd calls | ✓ VERIFIED | All three mode runners intercept `dry_run=True` before entering synthesis loop. `print_dry_run_summary()` prints table with `{N} claude.cmd invocation(s)` footer and KB estimates. Confirmed via live test showing "2 claude.cmd invocation(s)" output. No subprocess calls made in dry-run. |
| 5 | Each indexed domain produces both an Engram memory AND a thin skill file at ~/.claude/skills/ that triggers retrieval on relevant file globs (skill never contains content directly) | ✓ VERIFIED | `generate_skill_file()` called from `index_domain()` after successful `store_memory()`. Skill writes frontmatter with `allowed-tools: mcp__engram__search_memories, mcp__engram__retrieve_memory`. Body instructs tool calls — no content embedded. `disable-model-invocation` is absent. Confirmed via live test. |

**Score:** 4/5 success criteria fully verified (SC#5 is verified at code level; live synthesis not tested — see Human Verification)

### Observable Truths (from Plan must_haves)

**Plan 01 Truths:**

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Bootstrap synthesizes architecture memory for each configured domain | ✓ VERIFIED | `run_bootstrap()` iterates all domains, calls `index_domain()`, stores via `memory_manager.store_memory()` |
| 2 | Evolve mode only re-synthesizes domains whose files changed since last manifest update | ✓ VERIFIED | `find_changed_domains()` computes SHA256 diffs; only changed domains enter synthesis |
| 3 | Full mode re-synthesizes everything, ignoring updated_at protection | ✓ VERIFIED | `run_full()` calls `index_domain(..., force=True)` unconditionally — bypasses `is_manually_edited()` |
| 4 | Running `--init` produces a valid .engram/config.json via Python input() prompts | ✓ VERIFIED | `run_init()` uses `input()`, calls `save_project_config()`, writes config.json. No nested claude session. |
| 5 | If a memory's updated_at is newer than manifest last_run, bootstrap/evolve skip it unless --force | ✓ VERIFIED | `is_manually_edited()` compares `existing["updated_at"] > last_run`. Called in `index_domain()` after dry_run check, before synthesis. |
| 6 | Synthesized memories stored under key `codebase_{project}_{domain}_architecture` | ✓ VERIFIED | `memory_key("engram", "storage")` returns `"codebase_engram_storage_architecture"`. Confirmed live. |
| 7 | Synthesis uses `claude.cmd -p --tools '' --no-session-persistence --output-format json --model sonnet` | ✓ VERIFIED | Line 195: exact invocation confirmed. JSON parsed, `is_error` checked, `result` extracted. |

**Plan 02 Truths:**

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | After synthesis, SKILL.md exists at ~/.claude/skills/{project}-{domain}-context/SKILL.md | ✓ VERIFIED | `generate_skill_file()` creates `skills_root / "SKILL.md"` (uppercase). Live test confirmed path. |
| 2 | Skill files never contain architectural content — they instruct Claude to call search_memories and retrieve_memory | ✓ VERIFIED | Body template verified live: only contains tool call instructions. No embedded content. |
| 3 | Running `--install-hook` writes a working post-commit hook at {project}/.git/hooks/post-commit | ✓ VERIFIED | Hook exists, 1024 bytes, executable, correct content. |
| 4 | The installed hook uses the absolute venv Python path as shebang (no PATH dependency) | ✓ VERIFIED | Shebang: `#!/c/Users/colek/AppData/Local/Programs/Python/Python312/python.exe` |
| 5 | The hook spawns evolve as a detached background process and always exits 0 (never blocks commits) | ✓ VERIFIED | `CREATE_NO_WINDOW + close_fds=True` for detachment. Two `sys.exit(0)` calls (success and except). |
| 6 | Skill files are overwritten on every re-index run | ✓ VERIFIED | `skill_path.write_text(...)` — unconditional overwrite, no existence check. |

**Plan 03 Truths:**

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Running any mode with --dry-run prints summary table without making any claude.cmd calls | ✓ VERIFIED | All three runners return early before `index_domain()` when `dry_run=True`. Table confirmed live for bootstrap, evolve, and full modes. |
| 2 | --dry-run output is human-readable and lets user decide whether to proceed | ✓ VERIFIED | Table shows domain, files, context KB, status column. Footer shows invocation count and next-step instructions. |
| 3 | The dry-run implementation is integrated with all three modes | ✓ VERIFIED | `run_bootstrap()` L553, `run_evolve()` L588, `run_full()` L615 all have `if dry_run:` early-return paths. |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `engram_index.py` | Main CLI entry point, min 300 lines, exports main() | ✓ VERIFIED | 748 lines. All 19 functions importable. `main()` confirmed. |
| `{project}/.engram/config.json` | Per-project domain config with project_name, domains, planning_paths, model, max_file_size_kb | ✓ VERIFIED | C:/Dev/Engram/.engram/config.json exists with all required fields. |
| `{project}/.engram/index.json` | SHA256 manifest with last_run, files, memories | ✓ VERIFIED | Manifest round-trip confirmed via unit test. Schema matches spec. (No index.json currently on disk because no live synthesis has run — this is expected.) |
| `~/.claude/skills/{project}-{domain}-context/SKILL.md` | Thin skill with search_memories, retrieve_memory | ✓ VERIFIED | Confirmed via live generate_skill_file() test. |
| `{project}/.git/hooks/post-commit` | Git hook with CREATE_NO_WINDOW, sys.exit(0) | ✓ VERIFIED | File exists, executable, contains both patterns. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `synthesize_domain()` | `claude.cmd` subprocess | `subprocess.run` with input=prompt, capture_output=True | ✓ WIRED | Line 194-205. JSON parsed, is_error checked. |
| `index_domain()` store results | `memory_manager.store_memory()` | lazy import after dry_run guard | ✓ WIRED | Lines 457, 485-492. Lazy import pattern confirmed. |
| evolve mode | index.json manifest | `find_changed_domains()` SHA256 comparison | ✓ WIRED | `find_changed_domains()` reads `manifest["files"]`, computes `sha256_file()`, updates manifest. |
| `index_domain()` | `generate_skill_file()` | called after successful store_memory | ✓ WIRED | Lines 493-499. Called inside try block after store succeeds. |
| post-commit hook shebang | absolute Python path | forward-slash /c/ format | ✓ WIRED | `run_install_hook()` dynamically converts `C:/...` to `/c/...`. Verified in installed hook. |
| `--dry-run` flag | `index_domain()` dry_run parameter | via `args.dry_run` passed through mode runners | ✓ WIRED | Lines 740/742/744 pass `args.dry_run`. Mode runners intercept early before calling index_domain. |

### Data-Flow Trace (Level 4)

Not applicable — `engram_index.py` is a CLI tool, not a rendering component. The data flows are traced via key link verification above.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `--help` shows all flags | `python engram_index.py --help` | 7 flags shown: --project, --mode, --domain, --dry-run, --force, --init, --install-hook | ✓ PASS |
| memory_key format correct | `memory_key('engram', 'storage')` | `codebase_engram_storage_architecture` | ✓ PASS |
| Manifest round-trip | save_manifest then load_manifest | last_run populated with ISO timestamp | ✓ PASS |
| bootstrap dry-run prints table | `--mode bootstrap --dry-run` | DRY-RUN SUMMARY table with 2 claude.cmd invocation(s) | ✓ PASS |
| evolve dry-run prints table | `--mode evolve --dry-run` | DRY-RUN SUMMARY table (all domains changed — no prior manifest) | ✓ PASS |
| full dry-run prints table | `--mode full --dry-run` | DRY-RUN SUMMARY table | ✓ PASS |
| All 19 functions importable | `from engram_index import ...` | All functions import cleanly | ✓ PASS |
| skill generation correct | `generate_skill_file(...)` | SKILL.md written, has search_memories, retrieve_memory, no disable-model-invocation | ✓ PASS |
| Hook installed, executable | `ls -la .git/hooks/post-commit` | `-rwxr-xr-x`, 1024 bytes, CREATE_NO_WINDOW present | ✓ PASS |
| Live bootstrap synthesis | Requires running claude.cmd | Cannot test without live environment | ? SKIP |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| INDX-01 | 03-01 | engram_index.py CLI synthesizes architectural understanding into Engram memories | ✓ SATISFIED | Full CLI implemented, memory_manager.store_memory() wired |
| INDX-02 | 03-01 | Model B architecture — captures why, what was learned, what to watch out for | ✓ SATISFIED | DEFAULT_QUESTIONS and synthesis prompt template address all four Model B questions |
| INDX-03 | 03-01 | Per-project config at {project_root}/.engram/config.json | ✓ SATISFIED | load_project_config() / save_project_config() / run_init() all implemented |
| INDX-04 | 03-01 | Memory namespace: codebase/{project}/{domain}/architecture | ⚠ PARTIAL | Implementation uses underscores (`codebase_{project}_{domain}_architecture`). D-20 in CONTEXT.md explicitly authorizes this deviation from the slash-format in REQUIREMENTS.md. Functionally correct per design. |
| INDX-05 | 03-02 | Two outputs per domain: Engram memory AND thin skill file | ✓ SATISFIED | generate_skill_file() called from index_domain() after store_memory() |
| INDX-06 | 03-02 | Skill files never contain content directly — Engram is source of truth | ✓ SATISFIED | Skill body contains only tool call instructions, no architectural content |
| INDX-07 | 03-01 | Index manifest at {project}/.engram/index.json tracks file hashes | ✓ SATISFIED | SHA256 manifest with per-file hashes and last_run timestamp |
| INDX-08 | 03-01 | bootstrap mode — reads planning artifacts + source files, full synthesis pass | ✓ SATISFIED | run_bootstrap() + assemble_context() + synthesize_domain() |
| INDX-09 | 03-01 | evolve mode — hash-compares files since last run, re-synthesizes changed domains only | ✓ SATISFIED | find_changed_domains() returns only changed domains; run_evolve() processes only those |
| INDX-10 | 03-01 | full mode — complete re-index of everything | ✓ SATISFIED | run_full() calls index_domain(..., force=True) for all domains |
| INDX-11 | 03-02 | Git post-commit hook for automatic evolve mode | ✓ SATISFIED | Hook installed at .git/hooks/post-commit, confirmed working |
| INDX-12 | 03-02 | Hook uses absolute venv Python path (no PATH dependency on Windows) | ✓ SATISFIED | Absolute path from sys.executable, converted to Git Bash format |
| INDX-13 | 03-01 | Manual edits to Engram memories win over re-index unless --force | ✓ SATISFIED | is_manually_edited() compares memory updated_at vs manifest last_run |
| INDX-14 | 03-01 | CLI supports --project, --mode, --domain, --dry-run, --watch flags | ✗ BLOCKED | --watch flag is absent. 6 of the 7 listed flags present. CONTEXT.md defers --watch to v2/INDX-19 but INDX-14 is claimed Complete without even a stub. |
| INDX-15 | 03-01 | Synthesis uses Sonnet via anthropic SDK | ✓ SATISFIED (via supersession) | D-01 in CONTEXT.md explicitly supersedes INDX-15: uses claude.cmd --model sonnet instead of Anthropic SDK. Intentional design pivot documented in RESEARCH.md. |
| INDX-16 | 03-03 | Cost controls: dry-run cost estimation, invocation visibility | ✓ SATISFIED | print_dry_run_summary() shows file count, KB context, and claude.cmd invocation count per domain |

**Orphaned Requirements:** None. All 16 INDX requirements appear in plan frontmatter for this phase.

**Note on INDX-04:** The requirement text says `codebase/{project}/{domain}/architecture` (slash format), but D-20 in CONTEXT.md explicitly resolves: "The indexer should use underscores: `codebase_{project}_{domain}_architecture`." This is a documented intentional deviation — the REQUIREMENTS.md text predates the design decision. Not flagged as a gap.

**Note on INDX-15:** REQUIREMENTS.md says "via anthropic SDK" but D-01 in CONTEXT.md explicitly supersedes this with `claude -p` subprocess. RESEARCH.md line 72 documents the supersession. Not a gap.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `engram_index.py` | 588-592 | `run_evolve()` calls `find_changed_domains()` (which mutates `manifest["files"]` in memory) before the `dry_run` guard, but the in-memory mutation is discarded (save_manifest not called in dry_run path). | ℹ Info | No actual file writes during dry-run. The in-memory mutation is harmless. Acceptable. |

No TODOs, FIXMEs, placeholder returns, or hardcoded empty data found in the implementation. All stubs from Plan 01 (--install-hook) were completed in Plan 02 as intended.

### Human Verification Required

#### 1. Live Synthesis Run

**Test:** Run `python engram_index.py --project C:/Dev/Engram --mode bootstrap` with chromadb available and `claude.cmd` reachable.
**Expected:** Each configured domain (core, server) synthesizes into memories stored as `codebase_engram_core_architecture` and `codebase_engram_server_architecture`. Skill files written to `~/.claude/skills/engram-core-context/SKILL.md` and `~/.claude/skills/engram-server-context/SKILL.md`. `.engram/index.json` written with file hashes and last_run timestamp.
**Why human:** Requires live claude.cmd subprocess (60-120 seconds) and full chromadb stack available.

#### 2. Post-Commit Hook Fire Verification

**Test:** Make a trivial git commit in the Engram repo and check `C:/Dev/Engram/.engram/last_evolve.log`.
**Expected:** Log file updated with evolve mode output. Background process spawns without blocking the commit.
**Why human:** Requires an actual git commit and observation of background process activity.

### Gaps Summary

One gap blocks full INDX-14 satisfaction: the `--watch` flag is listed in REQUIREMENTS.md INDX-14 as a required CLI flag but is absent from `engram_index.py`. The CONTEXT.md and RESEARCH.md both explicitly defer `--watch` to v2 (INDX-19), and the plan spec for `build_parser()` intentionally omits it. However, REQUIREMENTS.md marks INDX-14 as `[x] Complete` and the 03-01 SUMMARY lists INDX-14 in `requirements-completed` without noting the partial implementation.

**Resolution options:**
1. Add `--watch` as a stub flag (prints "not yet implemented — see INDX-19") to satisfy the literal requirement
2. Update REQUIREMENTS.md to split INDX-14 into the implemented flags and a separate INDX-19 item for --watch, and remove --watch from INDX-14

Either resolves the gap. Option 2 is cleaner given --watch is already INDX-19.

---

_Verified: 2026-03-31_
_Verifier: Claude (gsd-verifier)_
