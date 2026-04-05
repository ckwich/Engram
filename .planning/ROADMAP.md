# Roadmap: Engram Enhancement Suite

## Overview

Engram v0.4 is a solid local MCP memory server. This milestone adds intelligence and automation on top of that base: a skill for natural mid-session memory creation, core storage quality guards (access tracking, deduplication, relationships), a Claude-powered codebase indexer with git hook automation, staleness detection surfacing, and an always-on session evaluator that captures architectural context after each Claude Code session. Each phase builds directly on the last — skill first (zero risk, immediate value), then quality guards (protecting against noise before bulk writes), then the indexer (the primary differentiator), then staleness (which needs the indexer's file tracking), then the evaluator (which needs all quality guards in place).

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Engramize Skill** - Install a global Claude Code skill enabling natural mid-session memory creation via "engramize [description]"
- [ ] **Phase 2: Core Memory Enhancements** - Add last_accessed tracking, deduplication gate, and relationship fields to memory_manager.py as a bundled quality layer
- [ ] **Phase 3: Codebase Indexer** - Build engram_index.py CLI with bootstrap/evolve/full modes, per-project config, and git post-commit hook automation
- [ ] **Phase 4: Staleness Detection** - Surface stale memories via WebUI tab and MCP tool using access timestamps and indexer-driven code-change flagging
- [ ] **Phase 5: Session Evaluator** - Implement always-on Claude Code Stop hook that evaluates sessions and routes high-value captures through an approval gate

## Phase Details

### Phase 1: Engramize Skill
**Goal**: Users can say "engramize [description]" in any Claude Code session and get a properly formatted, convention-compliant memory stored in Engram automatically
**Depends on**: Nothing (first phase)
**Requirements**: SKIL-01, SKIL-02, SKIL-03, SKIL-04, SKIL-05, SKIL-06
**Success Criteria** (what must be TRUE):
  1. User can type "engramize [description]" in any session and Claude creates a memory with underscore key, lowercase naming, and descriptive title format ("Project — Topic Pattern")
  2. Skill enforces tagging standards (project name, domain, type tag from decision/pattern/constraint/gotcha/architecture)
  3. Skill rejects or truncates content over 3000 characters before storing
  4. Skill file exists at ~/.claude/skills/engramize/skill.md and is available in all sessions regardless of working directory
**Plans**: 1 plan
Plans:
- [ ] 01-PLAN.md — Create ~/.claude/skills/engramize/SKILL.md with infer-then-confirm workflow and all convention enforcement

### Phase 2: Core Memory Enhancements
**Goal**: Every memory retrieval is tracked, duplicate stores are intercepted with a warning, and memories can be explicitly linked to related memories — all as a coherent quality layer before the indexer writes bulk content
**Depends on**: Phase 1
**Requirements**: TRAK-01, TRAK-02, TRAK-03, TRAK-04, DEDU-01, DEDU-02, DEDU-03, DEDU-04, RELM-01, RELM-02, RELM-03, RELM-04, RELM-05
**Success Criteria** (what must be TRUE):
  1. After any retrieve_memory, retrieve_chunk, or search_memories call, the returned memory's last_accessed timestamp is updated in its JSON file
  2. Calling store_memory with content nearly identical to an existing memory (cosine similarity >= 0.92) returns a warning with the existing key, title, and score instead of silently storing a duplicate
  3. Caller can pass force=True to override the deduplication warning and write anyway; dedup threshold is configurable in config
  4. Calling get_related_memories(key) returns all memories explicitly linked to or from that key (bidirectional)
  5. WebUI memory detail view shows related memories as clickable links
**Plans**: 3 plans
Plans:
- [x] 02-01-PLAN.md — Extend memory_manager.py: config loader, DuplicateMemoryError, audit strip, dedup gate, last_accessed fire-and-forget, related_to field, get_related_memories; extend --self-test
- [x] 02-02-PLAN.md — Update server.py: add force/related_to to store_memory MCP tool, add get_related_memories MCP tool
- [x] 02-03-PLAN.md — Update webui.py and index.html: /api/related endpoint, dedup 409 handling, last_accessed and related memories in view modal
**Research flags**:
  - Audit log suffix must be stripped before embedding comparison (DEDU-04) — read CONCERNS.md before planning
  - ChromaDB rejects empty arrays — related_to must be stored as comma-string in ChromaDB metadata, list in JSON only (RELM-02)

### Phase 3: Codebase Indexer
**Goal**: Running engram_index.py against a project synthesizes architectural understanding into Engram memories, with git hook automation for incremental re-indexing on every commit, cost controls enforced from the first run
**Depends on**: Phase 2
**Requirements**: INDX-01, INDX-02, INDX-03, INDX-04, INDX-05, INDX-06, INDX-07, INDX-08, INDX-09, INDX-10, INDX-11, INDX-12, INDX-13, INDX-14, INDX-15, INDX-16
**Success Criteria** (what must be TRUE):
  1. Running `python engram_index.py --project [path] --mode bootstrap` synthesizes architectural memories in the codebase/{project}/{domain}/architecture namespace without overwriting human-edited memories (unless --force is passed)
  2. Running evolve mode re-synthesizes only domains with changed files since last run, using the hash manifest at {project}/.engram/index.json
  3. A git post-commit hook fires automatically after every commit and runs evolve mode using the absolute venv Python path — no PATH dependency
  4. Running with --dry-run prints an invocation count and context size estimate before making any claude.cmd calls
  5. Each indexed domain produces both an Engram memory and a thin skill file at ~/.claude/skills/ that triggers retrieval on relevant file globs (skill never contains content directly)
**Plans**: 3 plans
Plans:
- [x] 03-01-PLAN.md — Core indexer engine: CLI entry point, config system, manifest utilities, synthesis subprocess, bootstrap/evolve/full modes, memory storage with edit protection
- [x] 03-02-PLAN.md — Skill file generation + git hook installer: generate_skill_file() called after synthesis, --install-hook writes detached post-commit hook
- [x] 03-03-PLAN.md — Dry-run + cost controls: print_dry_run_summary() table showing domain count, file count, KB context estimate per mode
**Research flags**:
  - Windows git hook requires absolute venv Python path (C:/Dev/Engram/venv/Scripts/python.exe) — no PATH inheritance (INDX-12)
  - Cost controls shift to invocation visibility: dry-run shows claude.cmd call count + context size (D-05, INDX-16)

### Phase 4: Staleness Detection
**Goal**: Users can immediately see which memories are either time-stale (not accessed in 90+ days) or code-stale (source files changed since last index), with a dedicated WebUI tab and MCP tool for surfacing them
**Depends on**: Phase 3
**Requirements**: STAL-01, STAL-02, STAL-03, STAL-04
**Success Criteria** (what must be TRUE):
  1. WebUI shows a "Stale Memories" tab listing memories not accessed within the configurable threshold (default 90 days), with "Mark Reviewed" action that clears the flag without deleting the memory
  2. When indexer evolve mode detects file changes in a domain, the corresponding memory is flagged as potentially_stale with a stale_reason and stale_flagged_at timestamp in its JSON
  3. Calling get_stale_memories(days=90) MCP tool returns memories past the access threshold — time-stale and code-stale surfaced with distinct labels
  4. No memory is ever automatically deleted — all staleness operations surface only, human decides
**Plans**: 2 plans
Plans:
- [x] 04-01-PLAN.md — Backend: get_stale_memories() in memory_manager.py, MCP tool in server.py, potentially_stale flagging in engram_index.py evolve mode, stale_days in config.json
- [x] 04-02-PLAN.md — WebUI: /api/stale and /api/memory/key/reviewed routes in webui.py, Stale tab with badge rows and Mark Reviewed in index.html

### Phase 5: Session Evaluator
**Goal**: Every Claude Code session is evaluated against configurable criteria after it ends; sessions meeting the bar produce a memory draft that is presented for human approval before being stored — completely non-blocking, with no risk of infinite loops or orphaned processes
**Depends on**: Phase 4
**Requirements**: EVAL-01, EVAL-02, EVAL-03, EVAL-04, EVAL-05, EVAL-06, EVAL-07, EVAL-08, EVAL-09, EVAL-10
**Success Criteria** (what must be TRUE):
  1. After any Claude Code session ends, if session criteria are met (bug resolved, new capability, architectural decision, etc.), a memory draft appears for approval before anything is stored
  2. The deduplication gate (Phase 2) runs automatically before the approval prompt — no duplicate is ever committed through the evaluator
  3. The Stop hook exits in under 10 seconds regardless of evaluator duration (evaluator spawns as detached subprocess)
  4. If stop_hook_active is true in the hook payload, the hook exits immediately with no action, preventing infinite evaluation loops
  5. Evaluation criteria and auto_approve_threshold are configurable per-project in .engram/config.json session_evaluator section
**Plans**: 3 plans
Plans:
- [x] 05-01-PLAN.md — Stop hook entry point (hooks/engram_stop.py) + detached evaluator subprocess (hooks/engram_evaluator.py) with claude.cmd evaluation, dedup gate, pending file writer
- [x] 05-02-PLAN.md — Pending memories approval skill (~/.claude/skills/engram-pending/SKILL.md) that auto-loads and surfaces drafts at session start
- [ ] 05-03-PLAN.md — Config defaults (config.json session_evaluator section) + settings.json hook registration
**Research flags**:
  - stop_hook_active check is mandatory as the absolute first action in hooks/engram_stop.py (EVAL-08)
  - Evaluator must be a detached subprocess — hook must not block (EVAL-09); Windows DETACHED_PROCESS flag requires explicit testing

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Engramize Skill | 0/1 | Not started | - |
| 2. Core Memory Enhancements | 2/3 | In Progress|  |
| 3. Codebase Indexer | 0/3 | Not started | - |
| 4. Staleness Detection | 0/2 | Not started | - |
| 5. Session Evaluator | 0/3 | Not started | - |
