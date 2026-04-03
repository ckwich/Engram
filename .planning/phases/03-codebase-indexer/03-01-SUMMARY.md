---
phase: 03-codebase-indexer
plan: 01
subsystem: cli
tags: [claude-cli, subprocess, sha256, argparse, codebase-indexer]

requires:
  - phase: 02-core-enhancements
    provides: store_memory with force/related_to params, DuplicateMemoryError
provides:
  - CLI engine (engram_index.py) with bootstrap/evolve/full modes
  - Per-project .engram/config.json configuration system
  - SHA256 manifest tracking for incremental re-indexing
  - claude.cmd subprocess synthesis pattern
  - Interactive --init domain setup flow
affects: [03-codebase-indexer, skill-generation, git-hooks]

tech-stack:
  added: [claude.cmd subprocess]
  patterns: [lazy-import for optional dependencies, SHA256 file manifest, CLI mode dispatch]

key-files:
  created: [engram_index.py]
  modified: []

key-decisions:
  - "Lazy import of memory_manager inside index_domain() to avoid chromadb dependency for dry-run mode"
  - "Memory keys use underscores per D-20: codebase_{project}_{domain}_architecture"
  - "Full mode always passes force=True to bypass edit protection (INDX-10)"
  - "Interactive --init uses Python input() prompts, not nested claude session"

patterns-established:
  - "CLI subprocess pattern: claude.cmd -p --tools '' --no-session-persistence --output-format json --model sonnet"
  - "SHA256 manifest in .engram/index.json tracks per-file hashes and last_run timestamp"
  - "Manual edit protection: skip re-synthesis if memory updated_at > manifest last_run"

requirements-completed: [INDX-01, INDX-02, INDX-03, INDX-04, INDX-07, INDX-08, INDX-09, INDX-10, INDX-13, INDX-14, INDX-15]

duration: 4min
completed: 2026-04-03
---

# Phase 03 Plan 01: Codebase Indexer CLI Engine Summary

**CLI engine with bootstrap/evolve/full synthesis modes using claude.cmd subprocess, SHA256 manifest tracking, and memory_manager storage integration**

## Performance

- **Duration:** 4 min
- **Started:** 2026-04-03T22:30:28Z
- **Completed:** 2026-04-03T22:34:17Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- Created complete engram_index.py (512 lines) with all CLI modes functional
- Implemented claude.cmd subprocess synthesis with JSON output parsing and is_error detection
- Built SHA256 manifest system for incremental evolve mode re-indexing
- Added manual edit protection (updated_at vs last_run comparison) with --force override
- Wired memory storage via memory_manager.store_memory() with dedup and related_to support

## Task Commits

Each task was committed atomically:

1. **Task 1: Create engram_index.py with CLI entry point, config system, and manifest utilities** - `4c89abf7` (feat)
2. **Task 2: Implement bootstrap, evolve, and full modes with memory storage** - `f335aae1` (feat)

## Files Created/Modified
- `engram_index.py` - Main CLI entry point with all mode implementations (512 lines)

## Functions Implemented

- `load_project_config()` - Load per-project .engram/config.json
- `save_project_config()` - Write per-project config
- `sha256_file()` - Compute SHA256 hash of file contents
- `load_manifest()` - Load .engram/index.json manifest
- `save_manifest()` - Save manifest with updated last_run
- `collect_domain_files()` - Glob-based file collection with size filtering
- `assemble_context()` - Build synthesis prompt from planning artifacts + source files
- `synthesize_domain()` - claude.cmd subprocess invocation with JSON parsing
- `run_init()` - Interactive domain setup via Python input()
- `build_parser()` - argparse CLI with 7 flags
- `memory_key()` - Generate codebase_{project}_{domain}_architecture keys
- `is_manually_edited()` - Check memory updated_at vs manifest last_run
- `index_domain()` - Orchestrate synthesis + storage for one domain
- `find_changed_domains()` - SHA256 hash diff for evolve mode
- `run_bootstrap()` - Synthesize all domains
- `run_evolve()` - Re-synthesize changed domains only
- `run_full()` - Force re-synthesis of everything
- `main()` - CLI dispatch

## Decisions Made
- Lazy import of memory_manager inside index_domain() to avoid chromadb dependency for dry-run mode (auto-fix, see below)
- Memory keys use underscores per D-20: codebase_{project}_{domain}_architecture
- Full mode always passes force=True to bypass edit protection (INDX-10)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed chromadb import failure during dry-run**
- **Found during:** Task 2 (mode implementation)
- **Issue:** Plan placed `from core.memory_manager import memory_manager` at top of index_domain(), which runs before the dry_run check. Since memory_manager imports chromadb at module level, dry-run fails in environments without chromadb installed.
- **Fix:** Moved the memory_manager import after the dry_run early-return, so dry-run never triggers the chromadb dependency.
- **Files modified:** engram_index.py
- **Verification:** `python engram_index.py --project C:/Dev/Engram --mode bootstrap --dry-run` succeeds
- **Committed in:** f335aae1 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Essential for dry-run to work without full dependency stack. No scope creep.

## Issues Encountered
None beyond the auto-fixed deviation above.

## Known Stubs
- `--install-hook` flag prints "not yet implemented (Plan 02)" -- intentional, implemented in Plan 02

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- CLI engine complete, ready for Plan 02 (skill file generation, git hooks)
- Plan 03 (dry-run display) can also proceed since --dry-run flag is wired

---
*Phase: 03-codebase-indexer*
*Completed: 2026-04-03*
