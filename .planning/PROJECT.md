# Engram Enhancement Suite

## What This Is

Engram is a local-first MCP semantic memory server for Claude Code. It stores structured memories (key/title/content/tags), chunks them via sentence-transformers, indexes with ChromaDB, and exposes 6 MCP tools for AI agents. A Flask WebUI provides human memory management. This milestone transforms Engram from a manual memory store into an intelligent, self-maintaining architectural knowledge system.

## Core Value

AI agents working on any indexed project should automatically receive relevant architectural context, create memories naturally mid-session, and never lose important decisions or patterns learned during development.

## Requirements

### Validated

- ✓ Semantic memory storage with key/title/content/tags — existing
- ✓ Markdown-aware chunking (800 char max) — existing
- ✓ Local embeddings via all-MiniLM-L6-v2 — existing
- ✓ ChromaDB vector search with cosine similarity — existing
- ✓ Three-tier retrieval (search → chunk → full) — existing
- ✓ 6 MCP tools (search, list, retrieve_chunk, retrieve_memory, store, delete) — existing
- ✓ Flask WebUI with full CRUD, search, tag filtering — existing
- ✓ JSON flat files as source of truth with ChromaDB rebuild — existing
- ✓ Async MCP server with dedicated executors — existing
- ✓ CLI modes (rebuild-index, export, import, migrate, health, self-test) — existing
- ✓ SSE remote transport support — existing
- ✓ Engramize skill for natural mid-session memory creation — Phase 1
- ✓ last_accessed tracking on every retrieval — Phase 2
- ✓ Deduplication gate on store_memory (0.92 cosine threshold, configurable) — Phase 2
- ✓ related_to relationship field with get_related_memories MCP tool — Phase 2

### Active
- [ ] Codebase Indexer CLI (bootstrap/evolve/full modes)
- [ ] Per-project config for indexer domain questions
- [ ] Auto-generated skill files triggering Engram retrieval on file globs
- [ ] Git post-commit hook for automatic evolve mode
- [ ] Staleness detection and surfacing (WebUI tab + MCP tool)
- [ ] Indexer-driven potentially_stale flagging on code changes
- [ ] Session evaluator via Claude Code Stop hook
- [ ] Approval gate for automated memory capture
- [ ] Configurable session evaluation criteria per project

### Out of Scope

- Graph DB migration — revisit after related_to usage validates the need
- AST/call graph parsing — too complex, Claude-based synthesis covers the value
- Multi-user support — local-first, single user
- Cloud sync — local-first architecture
- Mobile app or desktop client — CLI + WebUI only
- Automatic memory deletion — staleness surfaces only, human decides

## Context

Engram is at v0.4 (stable with web UI, full CRUD, recovery tools). The codebase is ~1,300 lines of Python across 6 files plus HTML/CSS. ChromaDB and sentence-transformers are already installed in venv. The anthropic Python SDK is available for Phase 3/5 API calls.

The enhancement brief was provided as a complete design document with 5 phases, each independent but building on foundations from earlier phases. The natural dependency order is 1 → 2 → 3 → 4 → 5, though Phase 1 and Phase 2 could theoretically run in parallel.

Engram is used across multiple projects (Sylvara, Lumen, Soravelon, Iron Tree) and the Obsidian vault at C:\Obsidian serves as the primary knowledge source for memory loading.

## Constraints

- **Platform**: Python 3.12, Windows 10/11 primary environment
- **Paths**: All paths must use forward slashes or os.path.join — no hardcoded backslashes
- **Python**: Invoked as `python` not `python3`
- **Location**: Engram runs at C:\Dev\Engram
- **Memory size**: Individual memories stay under 5000 characters
- **Memory keys**: Use underscores not slashes
- **Backward compatibility**: Existing MCP tools must remain backward compatible throughout all phases
- **Synthesis model**: Sonnet for Claude API synthesis calls (Phase 3)
- **Skill location**: Global skill files at ~/.claude/skills/ (not per-project)
- **Session evaluation**: Always-on hook, fires for every session
- **Dependencies**: ChromaDB, sentence-transformers, anthropic SDK already in venv

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Sonnet for codebase synthesis | Good quality/cost ratio for code analysis, fast enough for evolve mode | — Pending |
| Global skill file installation | Skills available in all sessions regardless of working directory | — Pending |
| Always-on session evaluator | Every session gets evaluated — small API cost per session | — Pending |
| 5 phases matching enhancement brief | Natural grouping: Skill, Core (2a/2b/2c), Indexer, Staleness, Evaluator | — Pending |
| Model B indexer architecture | Capture why/learned/watch-out, not file-by-file descriptions | — Pending |
| Manual edits win over re-index | Conflict resolution: human knowledge takes priority unless --force | — Pending |
| No auto-deletion of stale memories | Surfacing only — human decides what to remove | — Pending |
| Dedup threshold 0.92 configurable | High enough to catch near-duplicates, low enough to allow related memories | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-03 after Phase 2 completion*
