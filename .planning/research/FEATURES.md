# Feature Landscape

**Domain:** Intelligent MCP memory server for AI agents (local-first, developer-focused)
**Researched:** 2026-03-29
**Scope:** Enhancement milestone — Engram already has core storage; this covers intelligent features

---

## Existing Baseline (Engram v0.4)

Before categorizing new features, these are already built and working:

| Feature | Status |
|---------|--------|
| Semantic search (cosine similarity, all-MiniLM-L6-v2) | Done |
| Three-tier retrieval (search → chunk → full) | Done |
| 6 MCP tools (search, list, chunk, retrieve, store, delete) | Done |
| Markdown-aware chunking (800 char max, header-aware) | Done |
| JSON flat files + ChromaDB (human-readable + fast search) | Done |
| Flask WebUI (CRUD, search, tag filtering) | Done |
| CLI modes (rebuild, export, import, migrate, health, self-test) | Done |
| SSE + stdio transport | Done |

All new features below are additions to this foundation.

---

## Table Stakes

Features that any serious AI agent memory system must have. Missing these makes the system feel incomplete or unreliable.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Deduplication gate on store** | Without it, the same decision gets stored repeatedly across sessions, degrading search quality with noise | Medium | Threshold at 0.92 cosine similarity. Every major memory system (Mem0, mcp-memory-service, Memora) implements deduplication as a core operation. The Mem0 architecture explicitly uses an LLM to choose between ADD, UPDATE, or NOOP per candidate memory. |
| **last_accessed tracking** | Enables staleness detection downstream; critical for knowing which memories are still being used vs. rotting | Low | Pure metadata — timestamp update on every retrieve_chunk/retrieve_memory call. No search-quality impact, just bookkeeping. |
| **Staleness detection and surfacing** | Memory quality degrades silently without it. Users have no way to know what's outdated. | Medium | Memora implements MEMORA_STALE_DAYS (configurable, default 14). mcp-memory-service uses last_accessed_at. Staleness surface = WebUI tab + MCP tool — not auto-deletion. |
| **Memory relationships (related_to)** | Isolated memories lose context. Relationships let agents navigate from one concept to others without repeated search. | Medium | All graph-based systems (Zep, Neo4j agent-memory, Mem0g) treat relationships as core. For Engram: a lightweight flat array field, not a full graph DB. Enables get_related_memories tool. |
| **Natural mid-session memory creation (skill)** | Agents currently need to manually invoke store_memory at the right moment. A skill file that prompts agents to Engramize during natural breaks lowers friction to near zero. | Low | This is a documentation/prompt pattern, not code. High value, minimal implementation cost. |
| **Configurable dedup threshold** | 0.92 is a default, but some projects want tighter (0.95) or looser (0.85) matching. Hard-coding it makes Engram inflexible. | Low | Config file entry. Validated range 0.7–0.99. |

---

## Differentiators

Features that set Engram apart. Not standard in other MCP memory servers, or implemented in a uniquely valuable way for the developer-workflow context.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Codebase Indexer (bootstrap/evolve/full modes)** | Other memory servers store what you tell them. Engram can bootstrap an entire project's architectural knowledge from the codebase itself — capturing why/learned/watch-out patterns, not just file descriptions. No other MCP memory server in the ecosystem does this via Claude-based synthesis. AST-based tools (codebase-memory-mcp) do structural indexing but miss the "why" layer. | High | Three modes: bootstrap (initial full index), evolve (changed files only), full (force-reindex). Triggered via CLI, git post-commit hook, or on-demand. |
| **Git post-commit hook for auto-evolve** | Memory stays synchronized with code changes passively. The developer commits, Engram automatically re-indexes changed files. Zero manual effort after setup. | Medium | Post-commit hook writes to a queue or calls evolve mode directly. Need to handle cases where embedding model isn't loaded (spawn subprocess). |
| **Session Evaluator (Claude Code Stop hook)** | After every Claude Code session, a hook fires that evaluates the transcript and proposes what should be stored in Engram. No other open MCP memory server does this in a structured way. claude-mem does automatic capture but without structured Engram integration or approval gates. | High | Uses Stop hook event + transcript_path. Sends to Claude Sonnet for extraction. Proposed memories go to approval queue, not stored directly. Always-on (no per-project toggle). |
| **Approval gate for automated memory capture** | Human decides what gets stored from session evaluator output. Prevents garbage memories from accumulating. All production memory systems (Governed Memory architecture, 2026) identify human oversight as a requirement for high-quality memory in agent workflows. | Medium | WebUI approval queue tab. Approve/edit/reject per proposed memory. Approved memories flow through normal store_memory path (dedup gate applies). |
| **Indexer-driven staleness flagging** | When the codebase indexer detects that code has changed, it marks memories that reference changed files/patterns as potentially_stale. Staleness becomes proactive (code-change triggered) rather than reactive (time-based only). No other system combines code change detection with memory staleness this way. | Medium | Requires codebase indexer (Phase 3) to be built first. Flags via metadata field, surfaced in WebUI staleness tab and get_stale_memories tool. |
| **Per-project indexer config (domain questions)** | Generic code indexers ask generic questions. Engram lets each project define the questions that matter — "what are the auth boundaries?", "what performance assumptions exist?" — so indexed memories capture project-specific architectural concerns. | Low-Medium | YAML/JSON config file per project. Passed as context to Claude Sonnet during synthesis. Allows the "Model B" approach: capture why/learned/watch-out rather than file-by-file descriptions. |
| **Auto-generated skill files (glob triggers)** | Skills at ~/.claude/skills/ fire based on file glob patterns. Working in a React file → Engram automatically retrieves relevant architectural memories. No other system has this Claude Code-specific integration. | Medium | Skill generator CLI: engram generate-skills --project <name>. Creates SKILL.md files that trigger search_memories for domain-relevant queries when matching file patterns are detected. |
| **Global skill installation (all-session context)** | Skills available in every Claude Code session regardless of cwd. Architectural knowledge travels with the developer, not the project directory. | Low | Skill files at ~/.claude/skills/. Engram install wizard adds them. Claude Code loads skills automatically at session start. |

---

## Anti-Features

Features to explicitly NOT build. Each would add complexity or undermine Engram's design philosophy.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **Auto-deletion of stale memories** | Human knowledge and architectural decisions have non-obvious value. An automated system cannot distinguish "outdated" from "deliberately historical." Auto-deletion has caused irreversible knowledge loss in production memory systems. | Surface staleness via WebUI + get_stale_memories tool. Human decides what to remove. |
| **Graph DB migration (Neo4j, etc.)** | Premature optimization. related_to as a flat array field covers 80% of graph value with 5% of the complexity. Graph DB adds deployment friction, eliminates the JSON-as-source-of-truth property, and requires schema migrations. | Revisit after related_to usage validates actual graph traversal needs. |
| **AST/call graph parsing** | 66-language AST indexers (codebase-memory-mcp) take hundreds of lines of tree-sitter configuration. For Engram's use case — capturing architectural decisions and patterns — Claude-based synthesis of relevant files delivers equal or better value at 10% of the complexity. | Claude-based synthesis in codebase indexer covers the value. |
| **Multi-user support** | Local-first, single-developer tool. Multi-user adds auth, namespacing, conflict resolution, and shared-state complexity that is orthogonal to the core problem. | Keep as single-user. X-Agent-ID scoping (seen in mcp-memory-service) is unnecessary here. |
| **Cloud sync** | Violates local-first architecture. Developer memories include proprietary code context. Cloud sync creates security surface and dependency on external services. | Export/import CLI covers backup and migration needs. |
| **Mobile or desktop app** | Claude Code is a terminal tool. Adding native app surfaces splits the maintenance burden with zero user demand in this workflow. | CLI + WebUI is sufficient for all management tasks. |
| **Emotional metadata** | Seen in mcp-memory-service (emotion, valence, arousal). Valuable for consumer chatbot memory; irrelevant for developer architectural memory. Adds schema complexity with zero benefit in the coding workflow context. | Tags serve the categorization need. |
| **Ebbinghaus/decay-based memory scoring** | Time-decay recall models (seen in some memory implementations) treat memory like human cognition. Architectural decisions don't "fade" — they remain valid until explicitly superseded. Decay scoring would incorrectly demote foundational memories. | last_accessed + potentially_stale flag covers the actual need. |
| **LLM-based contradiction detection** | MSAM and Zep detect semantic contradictions between memories (temporal supersession, value conflicts). Valuable in conversation memory; overkill for developer knowledge where humans can review. Adds API cost and latency to every store operation. | Manual staleness review covers this. If a new decision supersedes an old one, the human stores it and can delete/update the old. |
| **Automatic deduplication merge** | Mem0 and Neo4j agent-memory auto-merge similar memories. This causes silent data loss. Two similar memories about the same decision may preserve different context. | Dedup gate BLOCKS storage if above threshold (0.92) and returns the existing match for human review. No auto-merge. |
| **Per-session memory scoping / conversation threading** | mcp-memory-service supports conversation_id scoping. In Engram's use case (cross-session architectural knowledge), isolating memories per session defeats the purpose. | Global memory namespace is the feature. |

---

## Feature Dependencies

```
last_accessed tracking
  └── staleness detection (needs timestamps to calculate age)
        └── get_stale_memories MCP tool (queries by staleness flags)
        └── staleness WebUI tab

deduplication gate on store
  └── related_to field (dedup threshold determines what counts as "related" vs "duplicate")

Codebase Indexer (bootstrap/evolve)
  └── per-project indexer config (shapes what indexer synthesizes)
  └── git post-commit hook (triggers evolve mode)
  └── indexer-driven staleness flagging (indexer marks memories when code changes)
        └── staleness detection WebUI tab (surfaces these flags)

Session Evaluator (Stop hook)
  └── approval gate WebUI (proposed memories route here)
        └── deduplication gate (applies when approved memories are stored)

Engramize skill (mid-session creation)
  └── deduplication gate (duplicate blocking on store_memory)

Auto-generated skill files
  └── Codebase Indexer (indexer knows project structure to generate domain-specific triggers)
```

---

## MVP Recommendation for This Milestone

The 5 phases are already defined in PROJECT.md. This feature map confirms the correct ordering:

**Phase 1 — Engramize Skill**
Table stakes skill creation. Lowest complexity, highest agent ergonomics value. Establishes pattern for all subsequent skill files.

**Phase 2 — Core Enhancements (2a/2b/2c)**
- 2a: last_accessed tracking (enables everything staleness-related)
- 2b: Deduplication gate (protects quality before indexer starts writing)
- 2c: related_to field + get_related_memories tool

These are table stakes. They must be in place before the indexer writes large volumes of memories, or dedup/quality problems compound.

**Phase 3 — Codebase Indexer**
Differentiator. Highest complexity. Depends on Phase 2 (dedup gate must exist before bulk indexing). Per-project config and git hook are natural companions.

**Phase 4 — Staleness Detection**
Depends on last_accessed (Phase 2a) and benefits greatly from indexer-driven flagging (Phase 3). WebUI tab + MCP tool. Approval-gate pattern applies here too.

**Phase 5 — Session Evaluator**
Highest value automation. Depends on dedup gate (Phase 2b) and benefits from having rich memories to compare against. Approval gate is a prerequisite for safety.

**Defer / Out of Scope:**
- Graph DB migration: revisit after related_to usage
- AST parsing: Claude synthesis covers the value
- Multi-user: out of scope entirely

---

## Ecosystem Context

Engram's approach differs from other MCP memory servers in three ways that are genuinely differentiating:

1. **Synthesis-first indexing**: Other codebase indexers (codebase-memory-mcp, code-index-mcp) build structural call graphs. Engram's indexer will ask Claude "what did you learn, what should you watch out for?" — capturing intent and decisions, not just structure.

2. **Approval-gated automation**: Fully automatic capture (claude-mem's approach) creates memory noise. Fully manual creation (most MCP servers) creates friction. The session evaluator + approval gate is a middle path that no current implementation offers.

3. **Skill-based context injection**: Automatic retrieval triggered by file globs (via ~/.claude/skills/) means relevant architectural memory surfaces without agents needing to remember to search. This is architectural context delivered at the right moment.

---

## Confidence Assessment

| Feature Area | Confidence | Sources |
|-------------|------------|---------|
| Deduplication patterns | HIGH | Mem0 paper (arXiv:2504.19413), mcp-memory-service, Memora, Neo4j agent-memory all implement variants |
| Staleness detection | HIGH | Memora (MEMORA_STALE_DAYS), mcp-memory-service (last_accessed_at), multiple implementations confirmed |
| Session evaluator via Stop hook | HIGH | Claude Code hooks docs confirmed Stop hook receives transcript_path and last_assistant_message |
| Codebase indexer differentiation | MEDIUM | Confirmed no other MCP server does Claude-synthesis-based "why/learned" indexing; AST-based indexers are different approach |
| Skill file auto-generation | MEDIUM | Pattern used in Agent-Skills-for-Context-Engineering repo; confirmed ~/.claude/skills/ path works |
| Approval gate as differentiator | MEDIUM | Governed Memory (arXiv:2603.17787) confirms human-in-loop as production best practice; no direct competitor found doing this in MCP memory |
| Graph DB anti-feature recommendation | HIGH | Confirmed: flat related_to array is sufficient for current scale; graph DBs add deployment friction |

---

## Sources

- [Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory (arXiv:2504.19413)](https://arxiv.org/abs/2504.19413)
- [Zep: A Temporal Knowledge Graph Architecture for Agent Memory (arXiv:2501.13956)](https://arxiv.org/abs/2501.13956)
- [mcp-memory-service — features: dedup, staleness, knowledge graph, autonomous consolidation](https://github.com/doobidoo/mcp-memory-service)
- [Codebase Memory MCP — AST-based structural indexing](https://github.com/DeusData/codebase-memory-mcp)
- [claude-mem — Stop hook lifecycle, automatic session capture](https://github.com/thedotmack/claude-mem)
- [Claude Code Hooks Reference — Stop hook fields, transcript_path](https://code.claude.com/docs/en/hooks)
- [Agent-Skills-for-Context-Engineering — skill file patterns](https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering)
- [Governed Memory: A Production Architecture for Multi-Agent Workflows (arXiv:2603.17787)](https://arxiv.org/html/2603.17787)
- [Memora — stale detection, consolidation candidates](https://github.com/agentic-box/memora)
- [Neo4j Agent Memory — multi-strategy deduplication](https://github.com/neo4j-labs/agent-memory)
- [Memory for AI Agents: A New Paradigm of Context Engineering (The New Stack)](https://thenewstack.io/memory-for-ai-agents-a-new-paradigm-of-context-engineering/)
