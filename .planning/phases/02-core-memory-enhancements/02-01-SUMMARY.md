---
phase: 02-core-memory-enhancements
plan: 01
subsystem: memory-engine
tags: [deduplication, cosine-similarity, chromadb, relationships, tracking]

# Dependency graph
requires:
  - phase: 01-engramize-skill
    provides: stable memory_manager with store/retrieve/search API
provides:
  - DuplicateMemoryError exception class for near-duplicate detection
  - Configurable dedup_threshold via config.json (default 0.92)
  - _strip_audit_log helper for clean embedding comparison
  - last_accessed timestamp tracking on all async retrievals
  - related_to relationship field with bidirectional get_related_memories
  - config.json at project root for runtime configuration
affects: [staleness-detection, session-evaluator, codebase-indexer]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fire-and-forget async pattern via asyncio.create_task for non-critical updates"
    - "Conditional ChromaDB metadata inclusion (omit empty fields, comma-join lists)"
    - "Top-N self-update detection in dedup (check top-5 results for own key)"
    - "Windows file locking retry pattern for concurrent JSON access"

key-files:
  created:
    - config.json
  modified:
    - core/memory_manager.py
    - server.py

key-decisions:
  - "Dedup checks top-5 ChromaDB results for self-update detection, not just top-1, to handle cases where force-stored duplicates rank above the original key's own chunks"
  - "Windows PermissionError on file unlink resolved with 3-attempt retry (50ms delay) to handle fire-and-forget concurrent writes"
  - "Content under 150 chars skips dedup check (unreliable embeddings for short text)"

patterns-established:
  - "Config loader pattern: _load_config() reads config.json with safe defaults, missing file uses all defaults"
  - "Fire-and-forget pattern: asyncio.create_task(self._method()) for non-critical background updates"
  - "Conditional metadata pattern: **({key: value} if condition else {}) for optional ChromaDB fields"

requirements-completed: [TRAK-01, TRAK-02, TRAK-03, TRAK-04, DEDU-01, DEDU-02, DEDU-03, DEDU-04, RELM-01, RELM-02, RELM-04]

# Metrics
duration: 9min
completed: 2026-04-03
---

# Phase 2 Plan 1: Core Memory Quality Summary

**Dedup gate with configurable 0.92 cosine threshold, last_accessed fire-and-forget tracking on all retrievals, and bidirectional related_to relationship field with full self-test coverage**

## Performance

- **Duration:** 9 min
- **Started:** 2026-04-03T17:51:10Z
- **Completed:** 2026-04-03T18:00:12Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Deduplication gate in _prepare_store blocks near-duplicate writes (cosine >= 0.92) with DuplicateMemoryError, overridable with force=True, self-updates always allowed
- Fire-and-forget last_accessed timestamp tracking on retrieve_memory_async, retrieve_chunk_async, and search_memories_async
- related_to relationship field stored as list in JSON, comma-string in ChromaDB metadata (omitted when empty), with bidirectional get_related_memories query
- Extended self-test covers all new features: last_accessed, dedup block, force override, self-update exemption, related_to storage, bidirectional queries

## Task Commits

Each task was committed atomically:

1. **Task 1: Add config loader, DuplicateMemoryError, audit strip, and dedup gate** - `a02745db` (feat)
2. **Task 2: Extend --self-test to cover last_accessed, dedup, and related_to** - `52580185` (feat)

## Files Created/Modified
- `config.json` - Runtime configuration with dedup_threshold (0.92 default)
- `core/memory_manager.py` - Added _load_config, DuplicateMemoryError, _strip_audit_log, _check_dedup, _update_last_accessed_async, get_related_memories, get_related_memories_async; updated _prepare_store, store_memory, store_memory_async, _index_chunks, _index_chunks_async, retrieve_memory_async, retrieve_chunk_async, search_memories_async
- `server.py` - Extended _run_self_test with 6 new test assertions for dedup, tracking, and relationships

## Decisions Made
- Dedup self-update detection uses top-5 ChromaDB results instead of top-1 to prevent false blocks when force-stored duplicates rank above the original key's own chunks
- Added Windows-specific retry on file unlink (3 attempts, 50ms delay) to handle concurrent access from fire-and-forget tasks
- Content under 150 chars bypasses dedup check due to unreliable short-text embeddings

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed dedup self-update false positive with multiple near-duplicates**
- **Found during:** Task 2 (self-test verification)
- **Issue:** _check_dedup only queried n_results=1 from ChromaDB. When a force-stored duplicate existed, it could rank above the original key's own chunks, causing self-updates to be incorrectly blocked
- **Fix:** Changed to query top-5 results and scan all for matching parent_key before checking threshold
- **Files modified:** core/memory_manager.py
- **Verification:** Self-test self-update assertion passes
- **Committed in:** 52580185 (Task 2 commit)

**2. [Rule 1 - Bug] Fixed Windows PermissionError on delete after fire-and-forget write**
- **Found during:** Task 2 (self-test verification)
- **Issue:** _update_last_accessed_async fire-and-forget task could hold JSON file handle open while delete_memory tried to unlink it, causing PermissionError on Windows
- **Fix:** Added 3-attempt retry with 50ms delay on path.unlink() in delete_memory
- **Files modified:** core/memory_manager.py
- **Verification:** Self-test delete step passes without PermissionError
- **Committed in:** 52580185 (Task 2 commit)

**3. [Rule 1 - Bug] Fixed test content below 150-char dedup threshold**
- **Found during:** Task 2 (self-test verification)
- **Issue:** Self-test dedup content was 136 chars, below the 150-char minimum for reliable dedup, causing dedup check to be silently skipped
- **Fix:** Extended test content to 190 chars across all dedup test assertions
- **Files modified:** server.py
- **Verification:** Self-test dedup block assertion passes
- **Committed in:** 52580185 (Task 2 commit)

---

**Total deviations:** 3 auto-fixed (3 bugs)
**Impact on plan:** All auto-fixes necessary for correctness on Windows platform and robust self-update detection. No scope creep.

## Issues Encountered
None beyond the auto-fixed deviations above.

## User Setup Required
None - no external service configuration required.

## Known Stubs
None - all features fully wired with real data paths.

## Next Phase Readiness
- Dedup gate, last_accessed tracking, and related_to field are live and tested
- config.json provides runtime configuration foundation for future features
- Phase 3 (codebase indexer) can use store_memory with related_to for cross-memory linking
- Phase 4 (staleness) can read last_accessed from JSON for age-based scoring

---
*Phase: 02-core-memory-enhancements*
*Completed: 2026-04-03*
