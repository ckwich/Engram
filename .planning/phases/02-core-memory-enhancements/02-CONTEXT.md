# Phase 2: Core Memory Enhancements - Context

**Gathered:** 2026-04-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Add quality infrastructure to memory_manager.py: last_accessed tracking on every retrieval, deduplication gate on store_memory, and related_to relationship field with a new get_related_memories MCP tool. Update WebUI to display related memories, dedup warnings, and last_accessed timestamps.

</domain>

<decisions>
## Implementation Decisions

### Deduplication Gate
- **D-01:** Dedup is warn-and-block: store_memory returns the similar memory's key/title/score and refuses to store. Caller must pass force=True to override.
- **D-02:** Dedup compares content embedding only (not key or title similarity).
- **D-03:** Strip the audit log suffix ("---\n**timestamp | Created/Updated via Engram**") before embedding for comparison, but the stored content keeps the audit trail intact.
- **D-04:** Dedup threshold (default 0.92) is configurable via Engram config file at C:/Dev/Engram/config.json.
- **D-05:** force=True must be added as an optional parameter to both the MCP store_memory tool and the internal store_memory/store_memory_async methods.

### Relationship Model
- **D-06:** Bidirectional links via query-time resolution. Only the source memory's JSON stores the related_to list. get_related_memories scans all memories for references to the queried key (both directions).
- **D-07:** Dangling references silently skipped — get_related_memories filters out keys that no longer exist.
- **D-08:** Maximum 10 related_to links per memory. Raise ValueError if exceeded.
- **D-09:** related_to stored as comma-separated string in ChromaDB metadata (ChromaDB rejects empty arrays). Stored as a list in JSON. Empty list = no metadata entry in ChromaDB (avoid empty string).

### last_accessed Tracking
- **D-10:** Operations that update last_accessed: search_memories (all returned results), retrieve_memory, retrieve_chunk.
- **D-11:** list_all_memories does NOT update last_accessed (directory listing, not meaningful access).
- **D-12:** last_accessed updates are fire-and-forget — run in background after returning results. Don't slow down retrieval.
- **D-13:** Backward compatible: existing memories get last_accessed: null until first retrieval.

### WebUI Integration
- **D-14:** Related memories shown as "Related Memories" inline section below content on detail view, with clickable key/title links.
- **D-15:** WebUI create/edit form shows dedup warning when server returns one — displays similar memory's title and score.
- **D-16:** last_accessed visible in memory detail view only (alongside created_at and updated_at), not in list view.

### Claude's Discretion
- How to implement the config.json file (schema, loading, defaults)
- Whether to add a search_memories `exclude_self` parameter for dedup queries
- Internal implementation of fire-and-forget last_accessed updates (asyncio.create_task, background executor, etc.)
- WebUI JavaScript implementation details for the related memories section

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Core Storage
- `core/memory_manager.py` — Storage engine: _prepare_store (line 218), store_memory (line 279), retrieve_memory (line 310), search_memories_async
- `core/embedder.py` — Embedding wrapper for dedup comparison
- `core/chunker.py` — Content chunking (audit log is part of chunked content)

### MCP Server
- `server.py` — All 6 MCP tool definitions; store_memory tool handler (adds force parameter)

### Web Dashboard
- `webui.py` — Flask routes for memory CRUD and search
- `templates/index.html` — Dashboard template (detail view, create/edit form)
- `static/style.css` — Dashboard styles

### Research
- `.planning/research/PITFALLS.md` — ChromaDB empty array rejection, audit log dedup corruption
- `.planning/research/ARCHITECTURE.md` — Integration patterns for new features

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `_prepare_store()` at line 218 — Central store path; dedup gate inserts here before JSON write
- `_run_blocking()` / `_run_chroma()` — Async execution patterns to reuse for fire-and-forget
- `_parse_search_results()` — Existing result formatting to extend with last_accessed
- `_load_json()` / `_save_json()` — JSON I/O for last_accessed updates

### Established Patterns
- JSON-first write ordering (JSON before ChromaDB)
- Sync + async method pairs (store_memory / store_memory_async)
- ChromaDB metadata is flat key-value (no nested objects, no arrays)
- Audit log appended to content in _prepare_store

### Integration Points
- store_memory MCP tool in server.py — add force parameter
- get_related_memories — new MCP tool following existing @mcp.tool() pattern
- WebUI detail view — add related memories section after content display
- WebUI create/edit form — add dedup warning display on store response

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches for the implementation details.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 02-core-memory-enhancements*
*Context gathered: 2026-04-01*
