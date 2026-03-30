# Project Research Summary

**Project:** Engram Enhancement Suite
**Domain:** Intelligent MCP memory server — local-first, developer-focused, AI agent context management
**Researched:** 2026-03-29
**Confidence:** HIGH

## Executive Summary

Engram is a personal MCP memory server with a solid v0.4 foundation: semantic search, three-tier retrieval, six MCP tools, and a Flask WebUI. This milestone adds intelligence and automation on top of that base — deduplication quality guards, relationship tracking, a Claude-powered codebase indexer, staleness detection, and a session evaluator that captures architectural context automatically after each Claude Code session. The research confirms this feature set is well-differentiated from the broader MCP memory ecosystem: no other server combines Claude-synthesis-based "why/learned" codebase indexing with an approval-gated session evaluator. The combination targets a specific gap — architectural memory that accumulates passively without quality degradation.

The recommended approach is a strict dependency-ordered build sequence: skill file first (zero risk, highest ergonomic payoff), then core storage quality guards (dedup, last_accessed, relationships), then the codebase indexer (the highest-complexity differentiator), then staleness detection (which depends on the indexer's source_files tracking), and finally the session evaluator (which depends on the dedup gate to be safe). All phases except Phase 3 require no new Python dependencies. Phase 3 adds only the `anthropic` SDK (likely already installed per PROJECT.md) and optionally `pathspec` for gitignore-aware file traversal. The existing JSON-as-source-of-truth / ChromaDB-as-rebuildable-index architecture must be preserved across all phases.

The primary risks are operational rather than architectural. API cost spiral on large repositories (Phase 3) must be controlled from day one with a mandatory token budget and dry-run mode — it cannot be retrofitted safely. Silent git hook failure on Windows (Phase 3) requires hardcoded absolute venv paths in the hook installer. The session evaluator Stop hook (Phase 5) must check `stop_hook_active` as its first action or risk an infinite loop that prevents Claude Code from terminating. Deduplication false positives (Phase 2) require surfacing the existing duplicate key and similarity score in the response rather than rejecting silently — and the existing audit log suffix must be stripped before embedding comparison or the dedup gate will be unreliable from day one. These are all avoidable with targeted implementation discipline; none require architectural pivots.

---

## Key Findings

### Recommended Stack

All phases build on the existing stack (fastmcp 3.1.1, sentence-transformers 5.3.0, chromadb 1.5.5, Flask 3.1.3, Python 3.12 on Windows). Only Phase 3 introduces a new dependency. The entire enhancement milestone is deliverable with minimal dependency surface growth — the correct choice for a personal tool where installation friction matters.

**Core technologies:**
- **fastmcp 3.1.1**: MCP tool layer — `@mcp.tool()` decorator pattern unchanged in v3; all new tools follow existing async pattern
- **sentence-transformers 5.3.0**: Deduplication similarity — `cos_sim()` already available; no additional library needed for cosine comparison
- **chromadb 1.5.5**: Vector index — `1 - chroma_distance` converts to cosine similarity; concurrent access safe via SQLite WAL
- **anthropic SDK >=0.86.0** (Phase 3+ only): `AsyncAnthropic().messages.create()` for indexer; sync `Anthropic()` for evaluator (different process context)
- **pathspec >=0.12.1** (optional, Phase 3): Gitignore-aware file filtering; alternative is `git ls-files` subprocess
- **Claude Code skill system**: `~/.claude/skills/engramize/SKILL.md` with `disable-model-invocation: true` for user-controlled invocation
- **Claude Code Stop hook**: `command` type in `~/.claude/settings.json`; 10-second timeout; evaluator spawned as detached subprocess

**No new dependencies for Phases 1, 2, 4, 5.** The `anthropic` SDK is the sole addition, and it is described as already present in the venv in PROJECT.md.

### Expected Features

**Must have (table stakes):**
- **Deduplication gate on store_memory** — without it, repeat sessions compound noise; threshold 0.92, configurable, with `force=True` escape hatch and informative response showing existing key
- **last_accessed tracking** — pure metadata; enables all downstream staleness logic; JSON-only write (not ChromaDB metadata)
- **Staleness detection and surfacing** — WebUI tab + `get_stale_memories` MCP tool; human decides, no auto-deletion
- **Memory relationships (related_to)** — flat `list[str]` field; `get_related_memories` tool; no graph DB
- **Engramize skill** — SKILL.md file at `~/.claude/skills/engramize/SKILL.md`; lowest cost, highest agent ergonomics value

**Should have (differentiators):**
- **Codebase Indexer** — Claude Sonnet synthesis of "why/learned/watch_out" patterns; bootstrap/evolve/full modes; separate CLI process (`indexer.py`)
- **Git post-commit hook** — triggers evolve mode automatically; installed with absolute venv Python path on Windows
- **Session Evaluator** — Stop hook + transcript synthesis + approval gate; always-on across all projects
- **Approval gate (WebUI pending tab)** — human reviews evaluator-proposed memories before commit; dedup gate applies on approval
- **Indexer-driven staleness flagging** — `potentially_stale` set when tracked files change; `source_files` metadata field enables cross-reference

**Defer (v2+):**
- Graph DB migration (Neo4j, etc.) — revisit after `related_to` usage validates actual traversal needs
- Auto-generated skill files from indexer — deliver indexer first; skill generation is an additive enhancement
- AST/call graph parsing — Claude synthesis covers the intent layer adequately
- Multi-user support, cloud sync, mobile/desktop app — explicitly out of scope

**Anti-features to avoid:**
- Auto-deletion of stale memories (surface, don't delete — human decides)
- LLM-based contradiction detection (adds API cost per store; manual review covers the need)
- Automatic dedup merge (causes silent data loss; block and surface instead)

### Architecture Approach

All new features integrate through `MemoryManager` as the single business logic layer. `server.py` and `webui.py` remain thin wrappers. Two new sibling CLI processes (`indexer.py`, `evaluator.py`) call `MemoryManager` sync methods directly — they are never imported by `server.py` and do not require the MCP server to be running. This preserves startup footprint and process isolation. The JSON-first invariant applies to all new fields; ChromaDB metadata receives only what is needed for index-time filtering.

Five new JSON fields are added across phases: `last_accessed`, `related_to`, `potentially_stale`, `stale_reason`, `stale_flagged_at`. A sixth field `source_files` is added by the indexer for staleness cross-referencing. All must be read with `.get(field, default)` for backward compatibility with existing memory files.

**Major components:**
1. **MemoryManager** (`core/memory_manager.py`) — gains `_touch_last_accessed()`, `_check_duplicate()`, `get_related()`, `get_stale()` methods
2. **server.py** — gains two new MCP tools (`get_related_memories`, `get_stale_memories`); `store_memory` gains backward-compatible `related_to` and `force` params
3. **indexer.py** (new) — standalone CLI; Anthropic SDK calls; bootstrap/evolve/full modes; writes memories via sync MemoryManager
4. **evaluator.py** (new) — Stop hook-spawned detached process; reads JSONL transcript; proposes memories to approval queue or stores directly
5. **hooks/engram_stop.py** (new) — receives Stop hook JSON on stdin; quick heuristics gate; spawns evaluator as detached subprocess; exits in <10 seconds
6. **~/.claude/skills/engramize/SKILL.md** (new) — static skill file; YAML frontmatter with `disable-model-invocation: true`
7. **webui.py** — gains Stale tab (Phase 4) and Pending Approvals tab (Phase 5); no business logic added

**Tool count after all phases: 8** (up from 6). The indexer and evaluator are deliberately NOT exposed as MCP tools — their long-running API calls would block the agent and exceed MCP timeout windows.

### Critical Pitfalls

1. **ChromaDB rejects empty arrays in metadata** (Phase 2c) — `related_to: []` crashes the ChromaDB upsert on every new memory with no relationships. Fix: store as comma-separated string in ChromaDB (`""` for empty, `"keyA,keyB"` for linked); keep list form in JSON only. `get_related_memories` reads JSON, not ChromaDB metadata.

2. **Audit log suffix poisons dedup similarity** (Phase 2b) — `_prepare_store` appends a timestamp line to content; this shifts embeddings and makes version-to-version cosine scores unreliable at 0.92. Fix: strip audit suffix before embedding for dedup comparison; ideally migrate audit log to a separate `history` JSON field (flagged in CONCERNS.md). Must be resolved at Phase 2b, not retrofitted.

3. **API cost spiral on codebase indexer** (Phase 3) — large repos can cost $5–15 per bootstrap, $30–50/day in active evolve mode with a git hook. Fix: mandatory `max_tokens_per_run` config, `--dry-run` token estimate before API calls, daily token cap in git hook, cost logging to local file. Must be in the first implementation.

4. **Git post-commit hook silent failure on Windows** (Phase 3) — Git for Windows hook environment does not inherit PATH; `python` does not resolve to the venv. Fix: hardcode absolute path `C:/Dev/Engram/venv/Scripts/python.exe` in hook installer; log every invocation to a timestamped file; provide `--verify-git-hook` self-test command.

5. **Stop hook infinite loop** (Phase 5) — not checking `stop_hook_active: true` in hook input causes Claude Code sessions to never terminate. Fix: check the flag as the absolute first action in `hooks/engram_stop.py`; always fail open (exit 0) if uncertain or on any error path.

6. **Skill description truncation kills auto-triggering** (Phase 1) — descriptions over 250 chars get cut off in Claude's skill listing, stripping trigger keywords. Fix: keep description under 200 chars; front-load "Use when..." with specific trigger keywords in the first 100 characters.

---

## Implications for Roadmap

The 5-phase structure defined in PROJECT.md is confirmed by research as the correct dependency order. No reordering is warranted.

### Phase 1: Engramize Skill
**Rationale:** No code risk, no dependencies, immediate agent ergonomics payoff. Establishes the skill file installation pattern. Must be correct from the start — a malformed skill silently fails.
**Delivers:** `~/.claude/skills/engramize/SKILL.md`; `python server.py --install-skill` CLI mode; user-invocable `/engramize` command
**Addresses:** Natural mid-session memory creation (table stakes)
**Avoids:** Description truncation (keep under 200 chars, front-load keywords); `disable-model-invocation: true` prevents auto-firing during unrelated tasks; forward-slash glob patterns for Windows compatibility (Pitfall 14)

### Phase 2: Core Storage Quality Guards (2a + 2b + 2c as bundle)
**Rationale:** Must be in place before Phase 3 writes large volumes of memories. The dedup gate without the audit-log fix will be unreliable immediately. All three sub-phases touch `_prepare_store()` — building them together avoids three sequential touches of the same file.
**Delivers:** `last_accessed` timestamp on retrieve; dedup gate at 0.92 (configurable, with `force` param and informative response); `related_to` field; `get_related_memories` MCP tool; `_touch_last_accessed()`, `_check_duplicate()`, `get_related()` in MemoryManager
**Addresses:** Deduplication (table stakes), last_accessed (table stakes), memory relationships (table stakes)
**Avoids:** ChromaDB empty-array crash (comma-string in Chroma, list in JSON only); audit log poisoning (strip suffix before embedding comparison, review CONCERNS.md for migration approach); per-retrieval write overhead (JSON only for last_accessed); backward compatibility breakage (all new fields use `.get()` defaults)

### Phase 3: Codebase Indexer + Git Hook
**Rationale:** The primary differentiator. Requires Phase 2b (dedup gate) to protect quality before bulk indexer writes. Introduces the only new dependency (anthropic SDK). Highest implementation complexity; requires the most careful Windows-specific testing.
**Delivers:** `indexer.py` CLI with bootstrap/evolve/full modes; `.engram/config.json` per-project schema with domain questions; `hooks/post-commit` installer with absolute venv paths; `source_files` JSON field; `--install-hook`, `--dry-run`, `--verify-git-hook` CLI modes; cost logging
**Addresses:** Codebase indexer (differentiator), git post-commit hook (differentiator), per-project indexer config (differentiator)
**Avoids:** API cost spiral (mandatory token budget + dry-run from day one — Pitfall 4); silent hook failure on Windows (absolute paths + hook invocation log — Pitfall 5); human edit overwrite (compare `updated_at` to indexer timestamp; skip if human-newer — Pitfall 11); config not found crash (fail loudly with actionable message — Pitfall 13)

### Phase 4: Staleness Detection
**Rationale:** Depends on `last_accessed` (Phase 2a) and `source_files` mapping (Phase 3). Completes the quality-management surface: memories can now be found, deduplicated, related, and assessed for freshness.
**Delivers:** `potentially_stale`, `stale_reason`, `stale_flagged_at` JSON fields; staleness flagging in indexer evolve mode; `get_stale_memories` MCP tool; WebUI Stale tab with "Mark Reviewed" action; age-based staleness threshold (configurable)
**Addresses:** Staleness detection (table stakes), indexer-driven staleness flagging (differentiator)
**Avoids:** Cry-wolf false positives (file-level scoping via `source_files`, minimum change threshold — Pitfall 9); confusing two staleness types (code-change vs. time-based surfaced with distinct labels)

### Phase 5: Session Evaluator
**Rationale:** Highest automation value but depends on dedup gate (Phase 2b) to prevent garbage accumulation, and benefits from a rich memory store built up over Phases 2–4.
**Delivers:** `evaluator.py`; `hooks/engram_stop.py`; `--install-stop-hook` CLI mode (modifies `~/.claude/settings.json`); WebUI Pending Approvals tab; session quality gate (minimum turn/word count); detached subprocess spawning on Windows
**Addresses:** Session evaluator (differentiator), approval gate (differentiator)
**Avoids:** Infinite loop (`stop_hook_active` check as first action, always fail open — Pitfall 6); low-quality session noise (quality gate before spawning evaluator — Pitfall 10); evaluator subprocess orphaning on Windows (`DETACHED_PROCESS` flag); hook blocking Claude stop (10-second timeout, evaluator is non-blocking)

### Phase Ordering Rationale

- Phase 1 is dependency-free and ships immediately. The skill installation pattern established here is reused in Phase 3's hook installer.
- Phases 2a/2b/2c are bundled because they all modify `_prepare_store()` or adjacent `MemoryManager` paths. The audit-log migration required for Phase 2b is a shared prerequisite discovered during research — it must be addressed in this phase.
- Phase 3 must follow Phase 2 because the dedup gate is the quality control layer for bulk indexer writes. Running the indexer without dedup risks seeding the memory store with near-duplicate content that degrades search permanently.
- Phase 4 is sequenced after Phase 3 because it requires the `source_files` mapping the indexer introduces. Bundling Phase 4 with Phase 3 is tempting but adds scope to the highest-complexity phase.
- Phase 5 is last because it is the most behaviorally invasive (always-on hook modifying Claude Code settings globally) and benefits from having a quality-controlled, well-indexed memory store before the evaluator starts writing to it.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 3 (Codebase Indexer):** Exact JSONL transcript schema (for Phase 5 prep; document while in Phase 3); ChromaDB concurrent write behavior under indexer + MCP server load (stress test before enabling git hook in production); Windows `subprocess.DETACHED_PROCESS` survival behavior
- **Phase 5 (Session Evaluator):** Stop hook JSONL transcript line schema — turn types, content block structure, tool call block format must be verified against current Claude Code docs before `evaluator.py` parsing is implemented

Phases with standard patterns (skip deeper research):
- **Phase 1 (Engramize Skill):** Skills API fully documented and verified from official source; no unknowns
- **Phase 2 (Core Guards):** Dedup threshold behavior, cosine similarity conversion, JSON schema extension patterns all confirmed from multiple sources
- **Phase 4 (Staleness Detection):** Direct extension of Phase 2a and Phase 3 outputs; no new integrations or external APIs

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Current stack verified from requirements.txt + server.py directly; anthropic SDK version from PyPI; fastmcp tool pattern from official docs |
| Features | HIGH | Dedup/staleness/relationships confirmed across multiple production memory systems (Mem0, mcp-memory-service, Memora, Neo4j agent-memory); session evaluator Stop hook confirmed from official Claude Code docs |
| Architecture | HIGH | Based on direct codebase analysis of server.py, memory_manager.py, webui.py; component boundaries verified; ChromaDB concurrent access patterns confirmed from docs |
| Pitfalls | HIGH | ChromaDB empty-array from issue tracker + source; Stop hook infinite loop from official docs; Windows git hook from multiple practitioner sources; cost spiral from token pricing math |

**Overall confidence:** HIGH

### Gaps to Address

- **JSONL transcript format:** The `transcript_path` JSONL schema (turn types, content block structure, tool call format) was not directly verified. Stop hook payload fields are confirmed, but internal JSONL line structure needs explicit verification before Phase 5 parsing is implemented. Resolve at Phase 3/5 boundary via direct doc fetch.

- **ChromaDB concurrent write behavior:** SQLite WAL mode is expected to handle indexer + MCP server concurrent writes safely at personal scale, but this is inferred from SQLite WAL documentation rather than ChromaDB-specific stress testing. Validate with a targeted test in Phase 3 before enabling the git hook in production.

- **Audit log migration scope:** CONCERNS.md flags audit log accumulation as a pre-existing concern. The dedup gate makes this non-optional (Pitfall 3 in PITFALLS.md). The exact migration approach (separate `history` field vs. strip-on-read) needs a decision before Phase 2b implementation. Read CONCERNS.md in full at Phase 2 planning.

- **Windows DETACHED_PROCESS subprocess:** `subprocess.Popen` with `creationflags=subprocess.DETACHED_PROCESS` for evaluator.py survival after Stop hook exits is the expected solution but requires Windows-specific testing. Flag as a Phase 5 research item.

- **Claude API prompt structure for synthesis:** The codebase indexer's prompts for Claude Sonnet synthesis (the "why/learned/watch_out" extraction pattern) require implementation-time iteration. No fixed prompt template is prescribed by research — this is engineering work, not research.

---

## Sources

### Primary (HIGH confidence)
- [Claude Code Skills Reference](https://code.claude.com/docs/en/skills) — skill file format, frontmatter fields, description limits, `disable-model-invocation`
- [Claude Code Hooks Reference](https://code.claude.com/docs/en/hooks) — Stop hook payload, `stop_hook_active` flag, `transcript_path`, JSON response format
- [FastMCP 3.x Tool Patterns](https://gofastmcp.com/servers/tools) — `@mcp.tool()` decorator, async pattern, unchanged in v3
- [Anthropic SDK 0.86.0](https://pypi.org/project/anthropic/) — `AsyncAnthropic().messages.create()`, sync variant for subprocesses
- [ChromaDB Metadata Filtering Docs](https://docs.trychroma.com/docs/querying-collections/metadata-filtering) — cosine distance conversion, metadata type constraints
- [ChromaDB Issue #1552](https://github.com/chroma-core/chroma/issues/1552) — empty array metadata rejection confirmed
- Direct codebase analysis — `server.py`, `core/memory_manager.py`, `webui.py`, `requirements.txt`, `.planning/PROJECT.md`, `.planning/codebase/CONCERNS.md`

### Secondary (MEDIUM confidence)
- [Mem0: Building Production-Ready AI Agents (arXiv:2504.19413)](https://arxiv.org/abs/2504.19413) — deduplication patterns, ADD/UPDATE/NOOP decision model
- [Governed Memory Architecture (arXiv:2603.17787)](https://arxiv.org/html/2603.17787) — human-in-loop approval gate as production requirement
- [mcp-memory-service](https://github.com/doobidoo/mcp-memory-service) — staleness tracking, last_accessed_at, knowledge graph patterns
- [Memora](https://github.com/agentic-box/memora) — MEMORA_STALE_DAYS configurable staleness
- [Milvus — Tuning similarity thresholds](https://milvus.io/ai-quick-reference/how-do-you-tune-similarity-thresholds-to-reduce-false-positives) — false positive behavior at 0.92
- [Git hooks on Windows pitfalls](https://medium.com/@rohitkvv/how-to-run-git-hooks-in-windows-using-c-avoiding-common-pitfalls-9166c441abef) — PATH resolution failures, venv activation
- [pathspec library](https://pypi.org/project/pathspec/) — gitignore pattern matching; used by Black and mypy

### Tertiary (MEDIUM-LOW confidence)
- [Zep: Temporal Knowledge Graph Architecture (arXiv:2501.13956)](https://arxiv.org/abs/2501.13956) — relationship tracking patterns; graph DB complexity tradeoffs
- [Agent-Skills-for-Context-Engineering](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering) — skill file glob trigger behavior
- [claude-mem](https://github.com/thedotmack/claude-mem) — automatic session capture pattern; Stop hook lifecycle

---

*Research completed: 2026-03-29*
*Ready for roadmap: yes*
