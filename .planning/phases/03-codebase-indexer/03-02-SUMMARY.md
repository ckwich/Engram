---
phase: 03-codebase-indexer
plan: 02
subsystem: cli
tags: [skill-files, git-hooks, claude-code-skills, engram-mcp]

# Dependency graph
requires:
  - phase: 03-01
    provides: "engram_index.py with index_domain(), store_memory integration, manifest tracking"
provides:
  - "generate_skill_file() — writes thin SKILL.md to ~/.claude/skills/{project}-{domain}-context/"
  - "run_install_hook() — writes post-commit hook to {project}/.git/hooks/post-commit"
  - "--install-hook CLI command wired in main()"
affects: [03-codebase-indexer, 04-staleness, 05-evaluator]

# Tech tracking
tech-stack:
  added: []
  patterns: [thin-skill-pointer, detached-background-hook, git-bash-shebang-format]

key-files:
  created: []
  modified: [engram_index.py]

key-decisions:
  - "Skill frontmatter uses paths field with forward-slash globs for cross-platform compatibility"
  - "Hook shebang dynamically converts Windows drive path to Git Bash format (/c/ prefix)"

patterns-established:
  - "Thin skill pattern: SKILL.md contains only Engram tool calls, never embedded content"
  - "Hook detachment: CREATE_NO_WINDOW + close_fds for non-blocking background process spawn"

requirements-completed: [INDX-05, INDX-06, INDX-11, INDX-12]

# Metrics
duration: 4min
completed: 2026-04-03
---

# Phase 03 Plan 02: Skill Files & Git Hook Summary

**Thin skill file generation after domain synthesis and detached post-commit hook for automatic evolve mode**

## Performance

- **Duration:** 4 min
- **Started:** 2026-04-03T22:36:27Z
- **Completed:** 2026-04-03T22:42:00Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- generate_skill_file() writes SKILL.md with correct frontmatter (name, description, paths, allowed-tools) and body instructing Claude to call search_memories/retrieve_memory
- Skill files auto-generated after every successful domain synthesis in index_domain()
- run_install_hook() writes executable post-commit hook with absolute Python path, Git Bash shebang, CREATE_NO_WINDOW detachment
- Hook always exits 0, never blocks commits, logs to .engram/last_evolve.log

## Task Commits

Each task was committed atomically:

1. **Task 1: Add generate_skill_file() and wire into index_domain()** - `daddd09a` (feat)
2. **Task 2: Implement run_install_hook() and wire --install-hook in main()** - `df134061` (feat)

## Files Created/Modified
- `engram_index.py` - Added generate_skill_file(), HOOK_TEMPLATE constant, run_install_hook(), replaced --install-hook stub

## Decisions Made
- Skill paths field uses forward slashes via .replace("\\", "/") for Windows compatibility
- Hook shebang is dynamically derived from sys.executable, converting C:/... to /c/... format
- No disable-model-invocation in skill frontmatter (D-11: skills auto-load into context)

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None - all functionality is fully implemented.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Skill generation and hook installation are complete
- Plan 03 (dry-run, cost controls, final verification) can proceed
- The post-commit hook is installed at C:/Dev/Engram/.git/hooks/post-commit for this repo

---
*Phase: 03-codebase-indexer*
*Completed: 2026-04-03*
