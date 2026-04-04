---
phase: 04-staleness-detection
plan: 01
subsystem: api
tags: [staleness, mcp, indexer, memory-management]

# Dependency graph
requires:
  - phase: 02-core-features
    provides: last_accessed tracking on memory retrieval
  - phase: 03-codebase-indexer
    provides: engram_index.py evolve mode with domain change detection
provides:
  - get_stale_memories() sync and async methods on MemoryManager
  - get_stale_memories MCP tool with days/type parameters
  - flag_memory_stale() helper for indexer evolve mode
  - stale_days configurable threshold in config.json
affects: [04-02-webui-stale-tab]

# Tech tracking
tech-stack:
  added: []
  patterns: [time-stale detection via last_accessed delta, code-stale flagging via potentially_stale/stale_reason/stale_flagged_at fields]

key-files:
  created: []
  modified: [config.json, core/memory_manager.py, server.py, engram_index.py]

key-decisions:
  - "None last_accessed means never accessed, treated as NOT stale (insufficient data)"
  - "Code-stale entries sorted first in results, then time-stale by days descending"
  - "Evolve mode uses domain file count as conservative upper bound for changed_count"

patterns-established:
  - "Stale flagging pattern: flag before synthesis, clear on success (D-05/D-06)"
  - "Three stale metadata fields: potentially_stale (bool), stale_reason (str), stale_flagged_at (ISO timestamp)"

requirements-completed: [STAL-02, STAL-03, STAL-04]

# Metrics
duration: 2min
completed: 2026-04-04
---

# Phase 04 Plan 01: Staleness Detection Backend Summary

**get_stale_memories MCP tool with time/code staleness detection and evolve-mode pre-synthesis flagging**

## Performance

- **Duration:** 2 min
- **Started:** 2026-04-04T04:31:03Z
- **Completed:** 2026-04-04T04:33:07Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Added stale_days=90 configurable threshold to config.json and memory_manager defaults
- Implemented get_stale_memories() with dual staleness detection (time-based via last_accessed, code-based via potentially_stale flag)
- Added get_stale_memories MCP tool to server.py with days and type filter parameters
- Added flag_memory_stale() to engram_index.py with D-06 flag-before-synthesis and D-05 clear-on-success semantics

## Task Commits

Each task was committed atomically:

1. **Task 1: Add stale_days to config and get_stale_memories() to memory_manager.py** - `5c25b9d9` (feat)
2. **Task 2: Add get_stale_memories MCP tool to server.py and potentially_stale flagging to engram_index.py** - `6aa6efd3` (feat)

## Files Created/Modified
- `config.json` - Added stale_days=90 threshold
- `core/memory_manager.py` - Added get_stale_memories() and get_stale_memories_async() methods
- `server.py` - Added get_stale_memories MCP tool with days/type params
- `engram_index.py` - Added flag_memory_stale() helper and evolve-mode stale flagging with clear-on-success

## Decisions Made
- None last_accessed treated as NOT stale (insufficient data to determine staleness)
- Code-stale entries sorted before time-stale entries in results
- Domain file count used as conservative upper bound for changed_count in stale_reason

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Backend staleness detection complete; get_stale_memories MCP tool operational
- Ready for 04-02 WebUI stale tab implementation
- All three stale metadata fields (potentially_stale, stale_reason, stale_flagged_at) established

---
*Phase: 04-staleness-detection*
*Completed: 2026-04-04*
