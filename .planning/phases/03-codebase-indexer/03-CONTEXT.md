# Phase 3: Codebase Indexer - Context

**Gathered:** 2026-04-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Standalone CLI tool (`engram_index.py`) that synthesizes architectural understanding from codebases into Engram memories. Three modes: bootstrap (full synthesis with interactive domain setup), evolve (incremental hash-based re-indexing), full (complete re-index). Auto-generates thin skill files for context injection. Git post-commit hook for automatic evolve.

</domain>

<decisions>
## Implementation Decisions

### Synthesis Engine — MAJOR CHANGE FROM BRIEF
- **D-01:** Use Claude Code CLI (`claude -p`) instead of Anthropic API for synthesis. User is on the Max 20x plan — no extra cost. Eliminates the need for anthropic SDK dependency entirely.
- **D-02:** Model is Sonnet via CLI. Configurable per project in `.engram/config.json` `model` field.
- **D-03:** Context assembled = planning artifacts (PROJECT.md, ROADMAP.md, AGENTS.md, plan.md from configurable `planning_paths`) + domain source files (from `file_globs`).
- **D-04:** Output format is structured markdown: ## Architecture, ## Key Decisions, ## Patterns, ## Watch Out For — mirrors /engramize content structure.
- **D-05:** Cost controls shift from "prevent API cost spiral" to "estimate CLI invocation count and preview what would be synthesized." `--dry-run` shows domain count, file count per domain, estimated context size. No `max_tokens_per_run` needed since CLI uses subscription.

### Domain Detection & Config
- **D-06:** Interactive domain setup on first run. Auto-detect candidate domains from directory structure, present to user via `claude -p` interactive session, user confirms/edits, config written to `.engram/config.json`.
- **D-07:** Standalone init command: `engram_index.py --project X --init` for just the config setup step. Bootstrap mode runs init automatically if no config exists.
- **D-08:** Config format: `{project_name, domains: {name: {file_globs, questions}}, planning_paths, model, max_file_size_kb}`. See preview in discussion log.
- **D-09:** Default synthesis questions when no custom questions configured: "What is the architecture?", "What key decisions were made?", "What patterns are used?", "What should someone watch out for?"
- **D-10:** A CLI-assisted domain setup tool as part of the init flow — not a separate skill, but a guided flow within engram_index.py itself.

### Skill File Generation
- **D-11:** Glob-based context injection. Skill description tells Claude to search Engram for domain context when editing files matching the domain's globs. `disable-model-invocation` NOT set (skill should auto-load into context).
- **D-12:** Skill files are always overwritten on re-index — they're auto-generated thin pointers, not content. No backup needed.
- **D-13:** Skill naming: `{project}-{domain}-context` installed at `~/.claude/skills/{project}-{domain}-context/SKILL.md`.
- **D-14:** Skill body instructs Claude to call search_memories and retrieve_memory with the domain's memory key, NOT to embed content.

### Git Hook & Evolve Mode
- **D-15:** Hook installed via CLI command: `engram_index.py --project X --install-hook` writes to `{project}/.git/hooks/post-commit`.
- **D-16:** Background evolve: hook spawns evolve as detached background process. Commit is NOT blocked. Output to `.engram/last_evolve.log`.
- **D-17:** Absolute venv Python path in hook script (e.g., `C:/Dev/Engram/venv/Scripts/python.exe`) — no PATH dependency on Windows.
- **D-18:** SHA256 per-file hash tracking in `.engram/index.json` manifest. Evolve compares current hashes to manifest, re-synthesizes only domains with changed files.
- **D-19:** Manual edit protection: if a memory's `updated_at` is newer than the last index run, skip re-synthesis unless `--force` is passed.

### Memory Namespace
- **D-20:** Keys follow pattern: `codebase/{project}/{domain}/architecture` (e.g., `codebase/sylvara/billing/architecture`). Note: this uses forward slashes in the key, which deviates from the underscore convention. The indexer should use underscores: `codebase_{project}_{domain}_architecture`.

### Claude's Discretion
- Exact synthesis prompt wording and system message
- How to handle files exceeding `max_file_size_kb` (truncate or skip)
- Whether to use `related_to` to link domain memories to each other
- Error handling for CLI subprocess failures
- Log formatting for `.engram/last_evolve.log`

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Core Storage
- `core/memory_manager.py` — store_memory API (with force, related_to params from Phase 2)
- `server.py` — MCP tool signatures
- `config.json` — Engram runtime config (dedup threshold, etc.)

### Skill Format
- `C:/Users/colek/.claude/skills/engramize/SKILL.md` — Reference for skill file format and frontmatter
- Phase 1 CONTEXT.md — Skill naming conventions (SKILL.md uppercase)

### Research
- `.planning/research/STACK.md` — Claude Code skill format, allowed-tools syntax
- `.planning/research/PITFALLS.md` — Windows git hook path issues, cost control requirements

### Enhancement Brief
- `.planning/PROJECT.md` — Phase 3 requirements and constraints

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `memory_manager.store_memory()` — Direct import for storing synthesized memories (sync API)
- `memory_manager.retrieve_memory()` — Check for existing memories before overwriting
- `_key_hash()` — MD5 hash helper for key → filename mapping
- Phase 2's config loading pattern — `_load_config()` in memory_manager.py

### Established Patterns
- JSON flat files as source of truth
- Sync methods for CLI tools (not async — engram_index.py is a standalone script)
- SKILL.md frontmatter format from Phase 1

### Integration Points
- `engram_index.py` is a NEW file at project root (sibling to server.py and webui.py)
- Imports `memory_manager` directly (sync API, like webui.py does)
- Writes skill files to `~/.claude/skills/{name}/SKILL.md`
- Writes per-project config to `{project}/.engram/config.json`
- Writes hook to `{project}/.git/hooks/post-commit`

</code_context>

<specifics>
## Specific Ideas

- The `--init` interactive flow should use `claude -p` to scan the project and suggest domains — a Claude-assisted setup conversation.
- The hook preview shown during discussion uses `$(git rev-parse --show-toplevel)` for project path detection inside the hook script.
- Default questions should match the "Model B" architecture from the enhancement brief: why things are the way they are, what was learned, what to watch out for.

</specifics>

<deferred>
## Deferred Ideas

- `--watch` mode for continuous indexing (listed as v2 in REQUIREMENTS.md)
- AST/call graph parsing (explicitly out of scope)
- Multi-language support (v2)

</deferred>

---

*Phase: 03-codebase-indexer*
*Context gathered: 2026-04-03*
