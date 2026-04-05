---
phase: 05-session-evaluator
plan: 01
subsystem: hooks
tags: [claude-code, stop-hook, subprocess, session-evaluation, pending-memories]

# Dependency graph
requires:
  - phase: 02-core-enhancements
    provides: dedup gate (_check_dedup), store_memory with force param
  - phase: 03-codebase-indexer
    provides: claude.cmd -p subprocess pattern, CREATE_NO_WINDOW Popen pattern
provides:
  - Stop hook entry point (hooks/engram_stop.py) with stop_hook_active safety check
  - Detached evaluator (hooks/engram_evaluator.py) with claude.cmd -p structured evaluation
  - Pending memory file output to .engram/pending_memories/
  - Auto-store path when confidence >= auto_approve_threshold
affects: [05-02-pending-skill, 05-03-settings-registration]

# Tech tracking
tech-stack:
  added: [pytest]
  patterns: [detached subprocess evaluator, pending file approval flow, json-schema structured output]

key-files:
  created:
    - hooks/engram_stop.py
    - hooks/engram_evaluator.py
    - hooks/test_engram_evaluator.py
    - hooks/__init__.py
  modified:
    - .gitignore

key-decisions:
  - "Payload passed as sys.argv[1] JSON string to avoid stdin pipe issues with detached processes"
  - "auto_approve_threshold=0.0 default means always write pending file (never auto-store unless configured)"
  - "Dedup gate runs before both auto-store and pending file write paths"

patterns-established:
  - "Stop hook pattern: stdin parse, stop_hook_active check first, detached Popen, always exit 0"
  - "Evaluator pattern: importable functions for testability, lazy core imports, fail-open on all errors"
  - "Pending file pattern: {cwd}/.engram/pending_memories/{YYYYMMDD}_{key}.json with dedup_warning field"

requirements-completed: [EVAL-01, EVAL-02, EVAL-03, EVAL-05, EVAL-06, EVAL-07, EVAL-08, EVAL-09, EVAL-10]

# Metrics
duration: 3min
completed: 2026-04-05
---

# Phase 5 Plan 1: Stop Hook and Evaluator Summary

**Claude Code Stop hook with detached evaluator subprocess using claude.cmd --json-schema for structured session evaluation and pending memory file output**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-05T04:18:41Z
- **Completed:** 2026-04-05T04:21:49Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Stop hook entry point that reads stdin, checks stop_hook_active first, spawns detached evaluator, always exits 0
- Detached evaluator with config loading, claude.cmd -p evaluation, dedup gate, auto-store/pending file decision
- 8 unit tests covering config loading, prompt building, and pending file creation

## Task Commits

Each task was committed atomically:

1. **Task 1: Create hooks/engram_stop.py** - `6d454661` (feat)
2. **Task 2: Create hooks/engram_evaluator.py (RED)** - `70c51b26` (test)
3. **Task 2: Create hooks/engram_evaluator.py (GREEN)** - `bc9eeecf` (feat)
4. **.gitignore update** - `e3067409` (chore)

## Files Created/Modified
- `hooks/engram_stop.py` - Stop hook entry point: stdin parse, stop_hook_active check, detached Popen spawn
- `hooks/engram_evaluator.py` - Detached evaluator: config load, claude.cmd call, dedup gate, pending file or auto-store
- `hooks/test_engram_evaluator.py` - 8 behavior tests for evaluator functions
- `hooks/__init__.py` - Package init for test imports
- `.gitignore` - Added .engram/ runtime directory

## Decisions Made
- Payload passed as sys.argv[1] JSON string (not env var or stdin) to avoid pipe issues with detached processes
- auto_approve_threshold=0.0 means always write pending file by default
- Dedup gate runs before both auto-store and pending file write, with dup_info included in pending file for approval display

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Installed pytest dependency**
- **Found during:** Task 2 (TDD RED phase)
- **Issue:** pytest not installed in venv
- **Fix:** pip install pytest
- **Verification:** All 8 tests run and pass
- **Committed in:** N/A (runtime dependency, not in committed files)

**2. [Rule 2 - Missing Critical] Added .engram/ to .gitignore**
- **Found during:** Post-verification
- **Issue:** Smoke test created .engram/evaluator.log at project root, would show as untracked
- **Fix:** Added .engram/ to .gitignore
- **Files modified:** .gitignore
- **Committed in:** e3067409

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 missing critical)
**Impact on plan:** Both necessary for clean execution. No scope creep.

## Issues Encountered
None

## Known Stubs
None - all functions are fully implemented with real logic.

## User Setup Required
None - hook registration in settings.json is covered by a later plan (05-03).

## Next Phase Readiness
- Stop hook and evaluator are complete and tested
- Ready for Plan 02 (pending-memories skill) to surface drafts at session start
- Ready for Plan 03 (settings.json registration) to activate the hook

## Self-Check: PASSED

All 5 files exist. All 4 commits verified.

---
*Phase: 05-session-evaluator*
*Completed: 2026-04-05*
