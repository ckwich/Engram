---
phase: 02-core-memory-enhancements
plan: 02
subsystem: api
tags: [mcp, dedup, relationships, fastmcp]

# Dependency graph
requires:
  - phase: 02-core-memory-enhancements plan 01
    provides: DuplicateMemoryError, store_memory_async with force/related_to, get_related_memories_async
provides:
  - store_memory MCP tool with force and related_to parameters
  - get_related_memories MCP tool with bidirectional output
  - DuplicateMemoryError caught and returned as human-readable warning
affects: [03-codebase-indexer, 04-staleness-detection]

# Tech tracking
tech-stack:
  added: []
  patterns: [MCP tool catches domain exceptions and returns warning strings instead of propagating errors]

key-files:
  created: []
  modified: [server.py]

key-decisions:
  - "DuplicateMemoryError returns warning string (not error) to MCP caller — agents see it as guidance, not failure"
  - "related_to accepts comma-separated string at MCP layer, converted to list for memory_manager"

patterns-established:
  - "MCP tool parameter pattern: comma-separated strings for list inputs (tags, related_to) parsed in tool handler"
  - "Domain exception to user message pattern: catch DuplicateMemoryError, format with threshold context"

requirements-completed: [RELM-03, RELM-04, DEDU-01, DEDU-02, TRAK-01, TRAK-02]

# Metrics
duration: 3min
completed: 2026-04-03
---

# Phase 02 Plan 02: MCP Tool Surface Summary

**Extended store_memory with force/related_to params and added get_related_memories tool exposing dedup gate and relationship graph to MCP agents**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-03T18:02:00Z
- **Completed:** 2026-04-03T18:05:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- store_memory MCP tool now accepts `force` (bool) and `related_to` (comma-separated string) parameters
- DuplicateMemoryError caught and returned as human-readable warning with similarity score and threshold
- New get_related_memories MCP tool formats bidirectional links (forward/reverse) with keys, titles, and tags
- Self-test passes with all 11 checks including dedup, force override, related_to, and bidirectional queries

## Task Commits

Each task was committed atomically:

1. **Task 1: Update store_memory tool with force/related_to params and DuplicateMemoryError handling** - `3b82ada9` (feat)

## Files Created/Modified
- `server.py` - Updated import line, extended store_memory tool signature and handler, added get_related_memories tool

## Decisions Made
- DuplicateMemoryError returns a warning string (not an MCP error) so agents see it as guidance to retry with force=True
- related_to uses comma-separated string at MCP boundary (consistent with existing tags parameter pattern)

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None - all functionality is fully wired.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All Phase 2 core memory enhancements now exposed via MCP (Plan 01: engine, Plan 02: tool surface)
- Plan 03 (WebUI updates) can proceed to surface these features in the browser interface
- Phase 3 (Codebase Indexer) can use store_memory with related_to to link indexed memories

---
*Phase: 02-core-memory-enhancements*
*Completed: 2026-04-03*
