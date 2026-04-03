---
phase: 03-codebase-indexer
plan: 03
subsystem: cli
tags: [dry-run, cost-control, cli-output, summary-table]

# Dependency graph
requires:
  - phase: 03-01
    provides: "index_domain() with basic dry-run one-liner, mode runners, collect_domain_files()"
provides:
  - "collect_dry_run_stats() — domain stats collection without synthesis"
  - "print_dry_run_summary() — structured table output for cost visibility"
  - "INDX-16 satisfied — invocation count + context size displayed before synthesis"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns: ["early-return dry-run pattern in mode runners", "graceful degradation when chromadb unavailable"]

key-files:
  created: []
  modified: ["engram_index.py"]

key-decisions:
  - "Graceful chromadb fallback in collect_dry_run_stats — dry-run works without chromadb installed"
  - "Early dry-run interception in mode runners — index_domain() dry-run path becomes unreachable safety fallback"

patterns-established:
  - "Early-return dry-run: mode runners catch dry_run before entering domain loop, collect stats separately"
  - "Graceful dependency handling: try/except import for optional heavy dependencies"

requirements-completed: [INDX-16]

# Metrics
duration: 3min
completed: 2026-04-03
---

# Phase 03 Plan 03: Dry-Run Summary Table

**Structured dry-run summary with per-domain file count, context KB, and claude.cmd invocation count for all three modes**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-03T22:41:23Z
- **Completed:** 2026-04-03T22:45:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Added collect_dry_run_stats() to gather per-domain statistics without synthesis
- Added print_dry_run_summary() for formatted table output showing domain, files, context KB, status
- Upgraded all three mode runners (bootstrap, evolve, full) to intercept dry-run early and print summary table
- Graceful handling when chromadb is not importable — dry-run still works with degraded status info

## Task Commits

Each task was committed atomically:

1. **Task 1: Add print_dry_run_summary() and upgrade mode runners** - `487ba19a` (feat)

## Dry-Run Output Example

```
Bootstrap: 2 domain(s) in Engram

============================================================
DRY-RUN SUMMARY -- mode: bootstrap
============================================================
Domain                Files    Context Status
-------------------- ------ ---------- ------------------------------
core                      4     34.2KB new (memory check unavailable)
server                    1     22.1KB new (memory check unavailable)
-------------------- ------ ---------- ------------------------------
TOTAL                     5     56.2KB 2 claude.cmd invocation(s)
============================================================

To proceed: remove --dry-run from the command.
To synthesize only one domain: add --domain <name>
```

## Files Created/Modified
- `engram_index.py` - Added collect_dry_run_stats(), print_dry_run_summary(), refactored mode runners

## Decisions Made
- Graceful chromadb fallback: collect_dry_run_stats wraps memory_manager import in try/except so dry-run works even without chromadb installed. Status shows "memory check unavailable" instead of failing.
- Early interception pattern: dry_run is caught at the mode runner level before entering the domain synthesis loop. The per-domain dry-run path in index_domain() remains as a safety fallback but is no longer reached in standard flow.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Graceful chromadb import fallback in collect_dry_run_stats**
- **Found during:** Task 1 (verification)
- **Issue:** Plan's collect_dry_run_stats() unconditionally imports memory_manager which requires chromadb. Dry-run failed with ModuleNotFoundError when chromadb is not installed.
- **Fix:** Wrapped memory_manager import in try/except. When unavailable, skip memory existence check and report "memory check unavailable" in status column.
- **Files modified:** engram_index.py
- **Verification:** All three modes run successfully without chromadb
- **Committed in:** 487ba19a (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Essential fix — dry-run must work without heavy dependencies. No scope creep.

## Issues Encountered
None beyond the chromadb import issue documented above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 03 (codebase-indexer) is now complete with all 3 plans executed
- All CLI modes (bootstrap, evolve, full) functional with dry-run support
- Ready for Phase 04 (staleness detection) or Phase 05 (session evaluator)

---
*Phase: 03-codebase-indexer*
*Completed: 2026-04-03*
