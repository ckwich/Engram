# Architecture Patterns: Engram Enhancement Suite

**Domain:** MCP memory server — adding codebase indexing, deduplication, relationship tracking, staleness detection, session evaluation
**Researched:** 2026-03-29
**Overall confidence:** HIGH (based on direct codebase analysis + verified external patterns)

---

## How New Features Integrate with Existing JSON+ChromaDB Storage

The existing architecture has one invariant that all new features must respect: **JSON is the source of truth; ChromaDB is a rebuildable index.** Every new feature that persists state must follow this rule.

### Storage Model Extensions

New fields added to the JSON schema are backward-compatible because `_load_json` reads with `dict.get()` defaults throughout. New fields should follow the same pattern: add to `_prepare_store()` and read with `.get(key, default)`.

**Fields added to the Memory JSON schema across phases:**

| Field | Added When | Type | Purpose |
|-------|-----------|------|---------|
| `last_accessed` | Phase 2a | ISO 8601 string | Staleness calculation, surfacing stale memories |
| `related_to` | Phase 2b | `list[str]` (keys) | Relationship tracking for `get_related_memories` |
| `potentially_stale` | Phase 4 | `bool` | Indexer-driven flag, surfaced in WebUI and MCP tool |
| `stale_reason` | Phase 4 | `str` or `null` | Which file/commit triggered the flag |
| `stale_flagged_at` | Phase 4 | ISO 8601 string or `null` | When the flag was set |

**ChromaDB metadata additions:**

The ChromaDB chunk metadata dict currently stores: `parent_key`, `chunk_id`, `title`, `tags`. New fields that support search/filtering can be added here too, but must also be written to JSON (the primary record). The `related_to` field does NOT need to be in ChromaDB metadata — relationship queries read from JSON, not from ChromaDB.

---

## Component Definitions and Boundaries

### Existing Components (unchanged)

| Component | File | Role |
|-----------|------|------|
| MCP Tool Layer | `server.py` | Exposes tools to AI agents; thin wrapper over MemoryManager |
| Web Dashboard | `webui.py` | Flask routes; no business logic, calls MemoryManager only |
| Storage Engine | `core/memory_manager.py` | All CRUD, search, JSON/ChromaDB sync |
| Embedder | `core/embedder.py` | Sentence-transformers singleton |
| Chunker | `core/chunker.py` | Stateless markdown-aware splitter |

### New Components

| Component | File | Role | Process |
|-----------|------|------|---------|
| Codebase Indexer | `indexer.py` | Scans project files, synthesizes memories via Claude API | Separate CLI process (never imported by MCP server) |
| Session Evaluator | `evaluator.py` | Reads Claude Code transcript at Stop hook, synthesizes session memories via Claude API | Short-lived subprocess (spawned by Stop hook script) |
| Stop Hook Script | `hooks/engram_stop.py` | Receives Stop hook JSON on stdin, spawns evaluator, returns to Claude quickly | Short-lived subprocess |
| Skill File | `~/.claude/skills/engram.md` | YAML frontmatter + instructions that prime Claude to use Engram tools | Static file, read by Claude Code at session start |
| Git Hook Script | `hooks/post-commit` | Shell script installed into `.git/hooks/` of target project, triggers `indexer.py --evolve` | Short-lived subprocess |

**Critical boundary rule:** `indexer.py` and `evaluator.py` both call `memory_manager` methods directly (sync API). They are CLI tools, not coroutines. Neither is imported by `server.py` or `webui.py`. This keeps the MCP server startup footprint unchanged.

---

## Data Flow for Each New Feature

### Phase 1: Engramize Skill

```
Claude session starts
  -> Claude Code reads ~/.claude/skills/engram.md
  -> YAML frontmatter activates skill (glob: ["**/*"] or similar)
  -> Skill instructions injected as context
  -> Claude now knows to call search_memories first, store_memory naturally mid-session

No code changes in Engram server. Pure skill-file configuration.
```

The skill file is written to `~/.claude/skills/engram.md` by a new CLI mode: `python server.py --install-skill`. This keeps the installation pattern consistent with existing CLI modes.

### Phase 2a: last_accessed Tracking

```
Agent calls retrieve_memory(key) or retrieve_chunk(key, chunk_id)
  -> MCP tool layer calls retrieve_memory_async() or retrieve_chunk_async()
  -> MemoryManager: after successful retrieval, patch JSON file with last_accessed=now
  -> No ChromaDB update needed (last_accessed is not indexed)
  -> Return result to agent (patch is fire-and-forget in async path, sync in CLI path)
```

**Implementation note:** The patch must be a targeted JSON field update, not a full `_prepare_store()` call (which appends an audit log and re-chunks). A lightweight `_touch_last_accessed(key)` helper reads the JSON, updates the single field, and writes it back.

### Phase 2b: Deduplication Gate

```
Agent calls store_memory(key, content, ...)
  -> MemoryManager._prepare_store() called (existing entry point)
  -> NEW: Before writing JSON, call _check_duplicate(content)
      -> embed content -> query ChromaDB for top-1 result
      -> if top score >= 0.92 AND result.key != key: return DuplicateResult
  -> If duplicate: raise DuplicateError (caught by MCP tool, returns warning string)
  -> If not duplicate: proceed with existing store flow unchanged

DuplicateResult carries: {existing_key, score, snippet}
MCP tool returns: "Near-duplicate detected (score=0.94). Existing: '{existing_key}'. Use that key to update, or call store_memory with --force to override."
```

**Threshold:** 0.92 cosine similarity (configurable in `config.json`). This is query-against-collection, so it uses the existing `embedder.embed()` + `col.query()` path already in `search_memories`. The dedup check reuses the same code path — no new ChromaDB calls.

**Force override:** The `store_memory` MCP tool gains an optional `force: bool = False` parameter. When `True`, the dedup check is skipped. Backward-compatible because the parameter defaults to False.

### Phase 2c: related_to Relationships

```
Agent calls store_memory(key, content, ..., related_to="key_a,key_b")
  -> MemoryManager._prepare_store() parses related_to into list[str]
  -> related_to stored in JSON data dict
  -> No ChromaDB change needed

Agent calls get_related_memories(key)
  -> NEW MCP tool
  -> MemoryManager.get_related(key):
      -> Load JSON for key, read related_to list
      -> For each related key, load JSON (list_memories metadata is sufficient for directory listing)
      -> Return: [{key, title, tags, snippet_of_first_chunk}]
  -> Snippets come from ChromaDB: col.get(where={"parent_key": related_key}, limit=1)
```

**ChromaDB metadata:** `related_to` is NOT stored in ChromaDB chunk metadata. Relationship queries always resolve through JSON. This keeps ChromaDB as an embedding index only, consistent with existing design.

### Phase 3: Codebase Indexer CLI

```
Developer runs: python indexer.py --project /path/to/project --mode bootstrap
  -> Load project config from .engram/config.json (or create default)
  -> Enumerate target file globs (py, ts, js, md, etc.)
  -> For each file batch:
      -> Send file contents + domain questions to Claude Sonnet API
      -> Receive structured analysis: {why_built, decisions, patterns, watch_outs}
      -> Call memory_manager.store_memory(key, synthesized_content, tags)
  -> Print summary: N memories created/updated

Git post-commit hook (installed by: python indexer.py --install-hook):
  -> .git/hooks/post-commit fires after every commit in target project
  -> Runs: python /c/Dev/Engram/indexer.py --evolve --project $(pwd)
  -> Evolve mode: git diff HEAD~1 HEAD --name-only -> changed files only
  -> For changed files, re-synthesize and update memories
  -> Existing memories for unchanged files are untouched
```

**Process separation:** The indexer runs as a standalone Python process. It imports `memory_manager` and `embedder` directly (sync API) — the same path used by `webui.py` and CLI modes. The MCP server does not need to be running for indexing. The indexer does not import `server.py` or `fastmcp`.

**Conflict resolution:** If a memory exists and `updated_at` is newer than the last indexer run timestamp (stored in `.engram/state.json`), the indexer skips it. Manual edits win. `--force` flag overrides.

**Claude API calls in indexer:** Uses `anthropic` Python SDK, Sonnet model. API key read from environment variable `ANTHROPIC_API_KEY`. Never falls back silently — fails with a clear error if the key is absent.

### Phase 4: Staleness Detection

```
Indexer evolve mode (runs after each commit):
  -> For each changed file, look up which memories reference that file
  -> Set potentially_stale=True, stale_reason="File changed: {path}", stale_flagged_at=now
  -> This is a targeted JSON patch (same pattern as _touch_last_accessed)

New MCP tool: get_stale_memories()
  -> MemoryManager.get_stale():
      -> list_memories() -> filter where potentially_stale == True
      -> Return: [{key, title, stale_reason, stale_flagged_at, last_accessed}]

WebUI: new "Stale" tab/section
  -> Calls GET /api/stale (new Flask route)
  -> Shows cards for stale memories with "Mark Reviewed" button
  -> "Mark Reviewed" calls PATCH /api/memory/{key}/reviewed
      -> Clears potentially_stale, stale_reason, stale_flagged_at from JSON
      -> Human decides — no automatic deletion

Staleness age calculation: (now - last_accessed) in days
  -> "Not accessed in 90+ days" surfaced alongside code-change staleness
  -> Threshold configurable in config.json
```

**Memory-to-file mapping:** The indexer stores file paths referenced in each memory's content (or in a separate `source_files: list[str]` JSON field). On evolve, changed files are cross-referenced against `source_files` in each memory's JSON. This is a linear scan of all JSON files on each commit — acceptable for personal-scale memory stores (hundreds, not millions).

### Phase 5: Session Evaluator

```
Claude Code session ends
  -> Stop hook fires: runs hooks/engram_stop.py
  -> engram_stop.py reads JSON from stdin (transcript_path, session_id, cwd)
  -> Quick heuristics: duration > 10min OR tool_count > 20 OR commit was made?
      -> If no: exit 0 immediately (no evaluation)
      -> If yes: spawn evaluator.py in background (subprocess, non-blocking)
  -> engram_stop.py exits 0 immediately — never blocks Claude from stopping

evaluator.py (background process):
  -> Reads transcript from transcript_path (JSONL file)
  -> Extracts: what was worked on, decisions made, patterns used, problems solved
  -> Sends to Claude Sonnet: "Given this session transcript, what memories should be stored?"
  -> Claude returns structured JSON: [{key, title, content, tags}]
  -> For each suggested memory: call memory_manager.store_memory(...)
      -> Dedup gate applies (Phase 2b) — prevents storing what already exists
  -> Write session summary to evaluator log (stderr/file, not stdout)
  -> If approval_required=True (config): write pending memories to .engram/pending/
      -> Human reviews via WebUI "Pending Approvals" tab before memories are committed
```

**Approval gate flow:**
```
evaluator.py -> .engram/pending/{session_id}.json (list of proposed memories)
WebUI /pending tab -> shows proposed memories with Approve/Reject buttons
Approve -> calls POST /api/memory (existing store endpoint)
Reject -> deletes pending file
```

**Stop hook configuration** (installed to `~/.claude/settings.json`):
```json
{
  "hooks": {
    "Stop": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "python C:/Dev/Engram/hooks/engram_stop.py",
        "timeout": 10
      }]
    }]
  }
}
```

The 10-second timeout on the Stop hook ensures Claude is never blocked waiting for Sonnet synthesis. The evaluator spawns as a detached subprocess and continues after the hook exits.

---

## Where New MCP Tools Fit in the Tool Hierarchy

Current tool set (6 tools):
1. `search_memories` — discovery tier 1
2. `list_all_memories` — browse
3. `retrieve_chunk` — discovery tier 2
4. `retrieve_memory` — discovery tier 3
5. `store_memory` — write
6. `delete_memory` — delete

New tools added to `server.py` (all follow existing async + string-return pattern):

| Tool | Phase | Tier | When Used |
|------|-------|------|-----------|
| `get_related_memories(key)` | 2c | Discovery | After finding a memory, explore its relationships |
| `get_stale_memories()` | 4 | Audit | Periodic review; surfaces memories needing validation |

**Tool count after all phases: 8.** This is intentional restraint — the indexer and evaluator are not exposed as MCP tools because they involve long-running API calls that would block the agent and exceed MCP timeout windows. They are CLI/hook-driven processes.

**store_memory signature change (Phase 2b+2c):** Backward-compatible extension:
```python
async def store_memory(
    key: str,
    content: str,
    title: str = "",
    tags: str = "",
    related_to: str = "",    # NEW: comma-separated keys
    force: bool = False,     # NEW: skip dedup gate
) -> str:
```
Old callers pass nothing for new params — behavior is identical.

---

## How the Indexer CLI Relates to the MCP Server Process

The indexer is a **sibling process**, not a child of the MCP server. The relationship:

```
[MCP Server process]         [Indexer process]
  server.py                    indexer.py
  fastmcp event loop           Plain sync Python
  async methods only           Sync methods only
       |                            |
       +--------> core/memory_manager.py <--------+
                  (shared module, different instances)
```

Both processes import `memory_manager` but each gets its own in-process instance. They do not share a live connection. ChromaDB's SQLite backend handles concurrent access via file locking — the existing `_init_lock` in `memory_manager.py` handles intra-process thread safety, but inter-process safety relies on SQLite's built-in WAL mode.

**Practical implication:** The indexer should not run concurrently with heavy MCP store operations. In practice, `post-commit` runs at human commit speed (once per few minutes), and the indexer processes one project at a time. Collision risk is negligible for personal use. If a ChromaDB timeout occurs during indexing (30-second limit), the indexer logs a warning and retries the affected memory on the next run.

**The MCP server never needs to restart** after the indexer runs. ChromaDB's HNSW index is updated on disk; the next `col.query()` from the MCP server reads the updated state.

---

## Data Flow for Deduplication Gate

```
store_memory(key, content, tags, title, force=False)
       |
       v
force == True? ──YES──> skip to _prepare_store() [existing flow]
       |
       NO
       v
embed(content[:500])     # first 500 chars to keep embedding fast
       |
       v
col.query(embedding, n_results=1)
       |
       v
top_score >= 0.92?
AND top_result.key != key?  (updating same key is always allowed)
       |
      YES
       v
return DuplicateWarning string
"Near-duplicate detected (score=X). Existing key: '{Y}'.
 To update that memory: store_memory(key='{Y}', ...).
 To store anyway: set force=True."
       |
       NO
       v
_prepare_store() [existing flow]
```

**What is NOT a duplicate:** Updating the same key (`top_result.key == key`) — this is always an update, never a duplicate. A score below 0.92 — these are related but distinct memories, which is expected and valuable.

**Embedding only 500 chars for dedup:** The full content embed used in `_index_chunks` is for retrieval quality. The dedup check only needs to determine semantic similarity at the topic level — 500 chars is sufficient and avoids a second full-content embed call.

---

## Data Flow for Relationship Queries

```
get_related_memories(key)
       |
       v
memory_manager.get_related(key)
       |
       v
_load_json(key)  -> data["related_to"]  (list of keys or [])
       |
       v
For each related_key:
  _load_json(related_key) -> {key, title, tags, updated_at}
  col.get(where={"parent_key": related_key}, limit=1) -> first chunk text
       |
       v
Return: [{key, title, tags, updated_at, first_chunk_snippet}]
```

**Why not query by embedding similarity?** Related memories are explicitly declared relationships (architectural decisions that reference each other, not semantically similar content). Semantic search already covers "find memories like this one." `get_related_memories` covers "find memories this one says are connected" — a different query type.

---

## Data Flow for Staleness Checks

```
[On each git commit in indexed project]
  post-commit hook
       |
       v
indexer.py --evolve
       |
       v
git diff HEAD~1 HEAD --name-only
       |
       v
changed_files = [list of paths]
       |
       v
For each JSON in data/memories/:
  if any(f in data.get("source_files", []) for f in changed_files):
    _patch_json(key, {
      "potentially_stale": True,
      "stale_reason": f"Files changed: {matching_files}",
      "stale_flagged_at": now
    })
       |
       v
Also: any memory where (now - last_accessed).days > STALE_AGE_DAYS
  -> surfaced by get_stale_memories() and WebUI tab
  -> NOT automatically flagged in JSON (time-based staleness is computed on read)
```

**Two staleness types distinguished:**
- **Code-change staleness** (`potentially_stale=True` in JSON): explicit flag set by indexer. The memory was created from code that has since changed. Highest urgency.
- **Access-age staleness** (computed on read from `last_accessed`): the memory hasn't been retrieved in N days. Lower urgency — may still be accurate.

The `get_stale_memories` MCP tool and WebUI tab surface both types with clear labeling.

---

## Suggested Build Order (Dependency Chain)

```
Phase 1: Engramize Skill
  -> No code dependencies. Pure skill file + --install-skill CLI mode.
  -> Builds: server.py (new CLI mode), ~/.claude/skills/engram.md

Phase 2a: last_accessed tracking
  -> Depends on: existing retrieve_memory, retrieve_chunk paths
  -> Builds: _touch_last_accessed() in memory_manager.py, called from retrieve_memory/_chunk
  -> Required by: Phase 4 (staleness age calculation)

Phase 2b: Deduplication gate
  -> Depends on: embedder.embed() (already exists), col.query() (already exists)
  -> Builds: _check_duplicate() in memory_manager.py, force param on store_memory MCP tool
  -> Required by: Phase 5 (evaluator's store calls go through dedup gate automatically)

Phase 2c: related_to relationships
  -> Depends on: Phase 2a (last_accessed) — not strictly, but same JSON-patch helper is shared
  -> Builds: related_to field in JSON schema, get_related() in memory_manager.py,
             get_related_memories MCP tool in server.py
  -> Required by: nothing downstream, but logical to bundle with 2a/2b as "core storage enhancements"

Phase 3: Codebase Indexer CLI
  -> Depends on: Phase 2a (last_accessed), Phase 2b (dedup gate protects indexer output)
  -> Builds: indexer.py, .engram/config.json schema, hooks/post-commit template,
             source_files field added to JSON schema
  -> Required by: Phase 4 (source_files mapping needed for staleness flagging)

Phase 4: Staleness Detection
  -> Depends on: Phase 2a (last_accessed), Phase 3 (source_files mapping, evolve mode)
  -> Builds: potentially_stale/stale_reason/stale_flagged_at JSON fields,
             get_stale_memories MCP tool, WebUI stale tab,
             staleness flagging in indexer.py evolve mode
  -> Required by: nothing downstream

Phase 5: Session Evaluator
  -> Depends on: Phase 2b (dedup gate), Phase 1 (skill increases session richness)
  -> Builds: evaluator.py, hooks/engram_stop.py, --install-stop-hook CLI mode,
             optional pending approvals flow in WebUI
  -> Required by: nothing downstream
```

**Phases 2a, 2b, 2c are a bundle** — they all modify `_prepare_store()` or add methods to `MemoryManager`. Building them together avoids touching the same file three times and reduces merge conflicts.

---

## Architectural Constraints for All New Components

1. **No stdout in any code path reachable from the MCP server.** `print()` must use `file=sys.stderr`. Violation breaks stdio MCP transport. The indexer and evaluator are separate processes, so they may use stdout for CLI feedback — but the habit of `sys.stderr` should be maintained.

2. **JSON first, ChromaDB second.** Any new field that needs to persist must be written to JSON before ChromaDB is updated (or the ChromaDB update is omitted entirely, as with `related_to`).

3. **Async in server.py, sync everywhere else.** `indexer.py`, `evaluator.py`, `hooks/engram_stop.py` all call sync MemoryManager methods. Only `server.py` uses `_async` methods. New MCP tools in `server.py` must follow the existing async + `await` pattern.

4. **Config lives in `.engram/config.json` per project.** The global Engram config (`config.json` at project root) handles server settings. Per-project indexer config lives inside the indexed project's directory. The indexer reads from `{project}/.engram/config.json`.

5. **Backward compatibility.** All new JSON fields must have safe defaults (`False`, `null`, `[]`). `_load_json` callers use `.get(field, default)`. Old memories without new fields work without migration.

6. **Memory size constraint unchanged.** The 5,000 char guideline (15,000 hard limit) applies to indexer-generated memories. Indexer output must be validated before store. If synthesis produces >15,000 chars, split by topic heading.

---

## Component Interaction Diagram

```
                        +------------------+
                        |  Claude Agent    |
                        +--------+---------+
                                 | MCP (stdio/SSE)
                        +--------v---------+
                        |   server.py      |  <-- 8 tools after all phases
                        | (MCP Tool Layer) |
                        +--------+---------+
                                 |
                  +--------------v--------------+
                  |     core/memory_manager.py   |
                  |  + _touch_last_accessed()    |
                  |  + _check_duplicate()        |
                  |  + get_related()             |
                  |  + get_stale()               |
                  +----+----------+-------------+
                       |          |
              +--------v---+   +--v----------+
              | JSON files |   |  ChromaDB   |
              | (source of |   |  (vector    |
              |   truth)   |   |   index)    |
              +------------+   +-------------+
                       ^
          +------------+------------+
          |                         |
+---------v--------+    +-----------v-------+
|   indexer.py     |    |  evaluator.py     |
| (CLI / git hook) |    | (Stop hook spawn) |
+---------+--------+    +-----------+-------+
          |                         |
          | Anthropic API           | Anthropic API
          | (Sonnet, batch)         | (Sonnet, per-session)
          +-------------------------+
```

```
                        +------------------+
                        |     webui.py     |
                        | (Flask Dashboard)|
                        +--------+---------+
                                 | sync methods
                  +--------------v--------------+
                  |     core/memory_manager.py   |
                  +------------------------------+
```

The WebUI and MCP server access `memory_manager` independently. They do not communicate with each other. Both processes may be running simultaneously — ChromaDB handles concurrent reads safely; concurrent writes are serialized by `_init_lock` within each process and by SQLite WAL at the inter-process level.

---

## Open Questions (Phase-Specific Research Needed)

1. **Claude Code transcript format.** The Stop hook receives `transcript_path` pointing to a `.jsonl` file. The exact schema of each JSONL line (turn type, tool calls, content blocks) needs verification against current Claude Code docs before `evaluator.py` parses it. Treat as needing research at Phase 5.

2. **FastMCP skill/hook integration.** Whether FastMCP 3.x has any native hook registration mechanism (vs. Claude Code's own hook system) needs checking before Phase 1 implementation.

3. **ChromaDB concurrent write safety.** For the specific case of indexer + MCP server both storing memories within seconds of each other (e.g., agent stores a memory while post-commit hook runs), the 30-second ChromaDB timeout and SQLite WAL should handle this. But this should be validated with a brief stress test in Phase 3.

4. **Anthropic SDK subprocess behavior.** `evaluator.py` spawned as a detached subprocess from the Stop hook needs to survive the parent process exiting. On Windows, `subprocess.Popen` with `creationflags=subprocess.DETACHED_PROCESS` is required. This is platform-specific and should be tested in Phase 5.

---

*Architecture analysis: 2026-03-29*
*Confidence: HIGH — based on direct codebase read + verified ChromaDB, Claude Code hooks, and Python subprocess patterns*
