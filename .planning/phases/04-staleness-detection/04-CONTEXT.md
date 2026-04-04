# Phase 4: Staleness Detection - Context

**Gathered:** 2026-04-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Surface stale memories via WebUI tab and MCP tool. Two staleness types: time-stale (not accessed in N days) and code-stale (indexer detected file changes). No automatic deletion — surfacing only.

</domain>

<decisions>
## Implementation Decisions

### WebUI Stale Tab
- **D-01:** Unified list with type badges. Single sorted list (most stale first). Each memory shows badge: "Time stale: 143d" or "Code changed" with reason. "Mark Reviewed" button per row.
- **D-02:** "Mark Reviewed" resets last_accessed to now (time-stale) or clears potentially_stale flag (code-stale). Simple, reversible.
- **D-03:** Staleness threshold configurable in Engram config.json (default 90 days).

### Code-Stale Flagging
- **D-04:** Three metadata fields in JSON: `potentially_stale` (boolean), `stale_reason` (string, e.g. "3 files changed in billing domain"), `stale_flagged_at` (ISO timestamp).
- **D-05:** Flags cleared on: Mark Reviewed action, re-index (evolve/full that re-synthesizes the domain), or manual edit to the memory.
- **D-06:** Indexer evolve mode sets these fields when domain has changed files but before re-synthesizing (flag first, then synthesize — if synthesis fails, memory is still flagged).

### MCP Tool
- **D-07:** `get_stale_memories(days=90, type='all')` — optional type filter: 'time', 'code', or 'all'. Default returns both types with distinct labels.
- **D-08:** Return format matches search_memories pattern — list of dicts with key, title, stale_type, stale_detail (days or reason), tags.

### Claude's Discretion
- WebUI CSS styling for stale badges and tab
- Exact sorting algorithm (stalest first by days, code-stale ordered by flagged_at)
- Whether to show stale count badge on the main dashboard header
- How to handle memories with both time-stale and code-stale (show both badges)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Core Storage
- `core/memory_manager.py` — last_accessed field (Phase 2), _load_json/_save_json patterns
- `config.json` — Runtime config (add stale_days threshold)

### Indexer
- `engram_index.py` — evolve mode (add potentially_stale flagging before synthesis)

### MCP Server
- `server.py` — Existing MCP tool patterns for new get_stale_memories tool

### Web Dashboard
- `webui.py` — Flask routes, existing tab patterns
- `templates/index.html` — Dashboard template, existing tab structure
- `static/style.css` — Styling patterns

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `last_accessed` field already in JSON (Phase 2) — direct comparison against threshold
- `list_memories()` in memory_manager.py — returns all memory metadata, can filter for staleness
- WebUI tab structure in index.html — existing grid/list views to replicate
- `_load_json()` / `_save_json()` — for clearing stale flags

### Established Patterns
- MCP tools return formatted strings (not JSON) — follow same for get_stale_memories
- WebUI uses fetch() for async API calls — same pattern for stale tab
- config.json loaded by `_load_config()` in memory_manager.py — add stale_days key

### Integration Points
- `engram_index.py` evolve mode — add flagging before synthesis
- `memory_manager.py` — add get_stale_memories() method
- `server.py` — add get_stale_memories MCP tool
- `webui.py` — add /api/stale route and stale tab
- `templates/index.html` — add Stale Memories tab UI

</code_context>

<specifics>
## Specific Ideas

- The stale tab preview from discussion shows the exact layout: badge + key + detail + action button
- Mark Reviewed should be a single API call (POST /api/memory/<key>/reviewed)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 04-staleness-detection*
*Context gathered: 2026-04-03*
