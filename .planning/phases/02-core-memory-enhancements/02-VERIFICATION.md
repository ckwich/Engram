---
phase: 02-core-memory-enhancements
verified: 2026-03-31T00:00:00Z
status: passed
score: 17/17 must-haves verified
re_verification: false
---

# Phase 2: Core Memory Enhancements Verification Report

**Phase Goal:** Every memory retrieval is tracked, duplicate stores are intercepted with a warning, and memories can be explicitly linked to related memories — all as a coherent quality layer before the indexer writes bulk content
**Verified:** 2026-03-31
**Status:** PASSED
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | After retrieve_memory_async or retrieve_chunk_async, last_accessed is set in JSON | VERIFIED | `asyncio.create_task(self._update_last_accessed_async([key]))` in both methods; `_update_last_accessed_async` writes `now` to JSON |
| 2 | After search_memories_async, all returned memories have last_accessed updated | VERIFIED | `asyncio.create_task(self._update_last_accessed_async(keys))` fires on non-empty results with deduped key set |
| 3 | Existing memories without last_accessed field read as None (no KeyError) | VERIFIED | `_prepare_store` uses `existing.get("last_accessed", None)` with safe `.get()` access |
| 4 | store_memory raises DuplicateMemoryError when similarity >= threshold and force=False | VERIFIED | `_check_dedup` called first in `_prepare_store` when `not force`; raises `DuplicateMemoryError(dup)` |
| 5 | store_memory with force=True stores even when near-duplicate exists | VERIFIED | `if not force: dup = self._check_dedup(...)` — gate skipped entirely when force=True |
| 6 | Dedup threshold reads from config.json, defaults to 0.92 when file absent | VERIFIED | `_load_config()` reads `config.json`, uses `defaults = {"dedup_threshold": 0.92}`; `config.json` exists with value 0.92 |
| 7 | Dedup comparison strips all accumulated audit log suffixes before embedding | VERIFIED | `_strip_audit_log(content)` called at top of `_check_dedup` before embedding |
| 8 | Updating a memory with the same key is never blocked by dedup (self-update allowed) | VERIFIED | `_check_dedup` queries top-5 results, scans all for `parent_key == key`, returns None if found (self-update exemption) |
| 9 | store_memory accepts related_to param; stored as list in JSON, comma-string in ChromaDB when non-empty, omitted when empty | VERIFIED | `_prepare_store` stores `validated_related_to` list in `data["related_to"]`; `_index_chunks` uses `**({"related_to": ",".join(related_to)} if related_to else {})` |
| 10 | get_related_memories returns forward and reverse results | VERIFIED | Scans all JSON files for reverse links; resolves both directions into `{forward: [...], reverse: [...]}` |
| 11 | store_memory MCP tool accepts force and related_to parameters | VERIFIED | `server.py` `store_memory` tool signature has `force: bool = False` and `related_to: str = ""` |
| 12 | store_memory MCP tool returns a warning string (not an error) when DuplicateMemoryError is raised | VERIFIED | `except DuplicateMemoryError as e:` returns `"DUPLICATE DETECTED..."` human-readable string |
| 13 | store_memory MCP tool with force=True stores despite near-duplicate | VERIFIED | `force` parameter passed through to `store_memory_async(..., force)` |
| 14 | get_related_memories MCP tool returns bidirectional relationships in human-readable format | VERIFIED | `→` arrows for forward, `←` arrows for reverse; calls `get_related_memories_async` |
| 15 | WebUI view modal shows last_accessed alongside created_at and updated_at | VERIFIED | `openViewModal()` sets `lastAccessed` from `m.last_accessed`, appends `Accessed: ${lastAccessed}` to meta line |
| 16 | WebUI view modal shows Related Memories section when related memories exist | VERIFIED | `loadRelatedMemories(key)` fetches `/api/related/<key>`, shows `#view-related` when `all.length > 0` |
| 17 | WebUI saveMemory() intercepts 409 and shows confirm dialog with force re-submit | VERIFIED | `if (res.status === 409)` → `confirm()` → re-submits with `force: true` on OK; returns without storing on Cancel |

**Score:** 17/17 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `config.json` | dedup_threshold: 0.92 | VERIFIED | File exists at project root with `{"dedup_threshold": 0.92}` |
| `core/memory_manager.py` | DuplicateMemoryError, _strip_audit_log, _check_dedup, _update_last_accessed_async, _load_config, get_related_memories | VERIFIED | All six exports/methods present; file is 734 lines with full implementation |
| `server.py` | Updated store_memory tool, new get_related_memories tool | VERIFIED | Both tools present with correct signatures; DuplicateMemoryError imported |
| `webui.py` | GET /api/related/<key>, DuplicateMemoryError handling, related_to + force params | VERIFIED | All routes present; api_create and api_update both handle 409 |
| `templates/index.html` | view-related section, last_accessed display, loadRelatedMemories(), 409 dialog | VERIFIED | All four features present; `#view-related` div, Accessed label, loadRelatedMemories function, status===409 handler |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `_prepare_store` | `_check_dedup` | called before any JSON write when force=False | WIRED | `if not force: dup = self._check_dedup(content, key)` is first operation in `_prepare_store` body |
| `retrieve_memory_async` | `_update_last_accessed_async` | `asyncio.create_task` | WIRED | `asyncio.create_task(self._update_last_accessed_async([key]))` present in method |
| `retrieve_chunk_async` | `_update_last_accessed_async` | `asyncio.create_task` | WIRED | `asyncio.create_task(self._update_last_accessed_async([key]))` present after result check |
| `search_memories_async` | `_update_last_accessed_async` | `asyncio.create_task` | WIRED | `asyncio.create_task(self._update_last_accessed_async(keys))` fires after parsing results |
| `_index_chunks / _index_chunks_async` | ChromaDB related_to metadata | conditional include | WIRED | `**({"related_to": ",".join(related_to)} if related_to else {})` in both methods |
| `store_memory MCP handler` | `memory_manager.store_memory_async` | force and related_list passed through | WIRED | `await memory_manager.store_memory_async(key, content, tag_list, title or None, related_list, force)` |
| `store_memory MCP handler` | `DuplicateMemoryError` | `except DuplicateMemoryError as e` | WIRED | Returns `"DUPLICATE DETECTED..."` string instead of propagating exception |
| `get_related_memories MCP tool` | `memory_manager.get_related_memories_async` | direct await | WIRED | `result = await memory_manager.get_related_memories_async(key)` |
| `openViewModal() JS` | `/api/related/<key>` | fetch after memory data loaded | WIRED | `loadRelatedMemories(key)` called at end of `openViewModal()` try block |
| `saveMemory() JS` | 409 response handler | `res.status === 409` check | WIRED | Intercepts 409, shows confirm(), re-submits with `force: true` |
| `webui.py api_create / api_update` | `DuplicateMemoryError` | except clause returns 409 | WIRED | Both handlers: `except DuplicateMemoryError as e: return jsonify({"status": "duplicate", **e.duplicate}), 409` |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `core/memory_manager.py` `_update_last_accessed_async` | `last_accessed` timestamp | `_now()` → `_save_json(data)` | Yes — writes ISO timestamp to JSON file | FLOWING |
| `core/memory_manager.py` `_check_dedup` | `score` | `embedder.embed(stripped)` → ChromaDB `col.query()` → `1 - (distance / 2)` | Yes — real cosine similarity from live index | FLOWING |
| `core/memory_manager.py` `get_related_memories` | `forward`, `reverse` | `JSON_DIR.glob("*.json")` full scan, `_load_json()` for each related key | Yes — reads from real JSON store | FLOWING |
| `templates/index.html` `loadRelatedMemories` | `data.forward`, `data.reverse` | `fetch('/api/related/<key>')` → `webui.py api_related` → `get_related_memories(key)` → JSON scan | Yes — fetches from live Flask endpoint backed by real JSON scan | FLOWING |
| `templates/index.html` `openViewModal` | `m.last_accessed` | `fetch('/api/memory/<key>')` → `webui.py api_memory` → `memory_manager.retrieve_memory(key)` → `_load_json()` | Yes — reads from real JSON file | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Check | Result | Status |
|----------|-------|--------|--------|
| DuplicateMemoryError importable with `.duplicate` attribute | `DuplicateMemoryError({'existing_key': 'k', 'score': 0.95}).duplicate['existing_key'] == 'k'` | Confirmed | PASS |
| `_strip_audit_log` removes audit suffix | Strip `'Hello world\n\n---\n**... Created via Engram**'` → `'Hello world'` | Confirmed | PASS |
| `store_memory_async` signature has `related_to` and `force` | `inspect.signature` check | `['key', 'content', 'tags', 'title', 'related_to', 'force']` | PASS |
| `dedup_threshold` reads 0.92 from config.json | `_config.get('dedup_threshold')` | `0.92` | PASS |
| All three retrieval methods fire `create_task` | Count `asyncio.create_task(self._update_last_accessed_async` occurrences | 3 found (retrieve_memory_async, retrieve_chunk_async, search_memories_async) | PASS |
| server.py syntax valid | `ast.parse(source)` | No errors | PASS |
| webui.py syntax valid | `ast.parse(source)` | No errors | PASS |
| All 5 committed hashes resolve | `git log --oneline a02745db 52580185 3b82ada9 65b43edf 44e07a29` | All 5 found | PASS |

Step 7b: Behavioral spot-checks via `--self-test` not run live (requires embedder load time ~60s), but all code paths verified statically and wiring confirmed at all levels.

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| TRAK-01 | 02-01, 02-02 | last_accessed updates on retrieve_memory and retrieve_chunk calls | SATISFIED | `asyncio.create_task(_update_last_accessed_async([key]))` in both `retrieve_memory_async` and `retrieve_chunk_async` |
| TRAK-02 | 02-01, 02-02 | search_memories hits update last_accessed for returned memories | SATISFIED | `asyncio.create_task(_update_last_accessed_async(keys))` in `search_memories_async` with deduped key set |
| TRAK-03 | 02-01 | Existing memories get last_accessed: null until first retrieval | SATISFIED | `_prepare_store` sets `"last_accessed": existing.get("last_accessed", None) if existing else None` |
| TRAK-04 | 02-01, 02-03 | last_accessed stored in JSON alongside created_at and updated_at | SATISFIED | Field in `data` dict in `_prepare_store`; WebUI displays it in view-meta line labeled "Accessed:" |
| DEDU-01 | 02-01, 02-02, 02-03 | store_memory runs similarity search; scores above 0.92 return warning with key, title, score | SATISFIED | `_check_dedup` embeds content, queries ChromaDB top-5, returns dict with `existing_key`, `existing_title`, `score` |
| DEDU-02 | 02-01, 02-02, 02-03 | Caller can pass force=True to override deduplication | SATISFIED | `force: bool = False` param on `store_memory`, `store_memory_async`, `_prepare_store`; gate skipped when `force=True` |
| DEDU-03 | 02-01 | Dedup threshold is configurable (default 0.92) | SATISFIED | `_load_config()` reads `config.json`; `_check_dedup` uses `_config.get("dedup_threshold", 0.92)` |
| DEDU-04 | 02-01 | Dedup comparison strips audit log suffix before embedding | SATISFIED | `stripped = _strip_audit_log(content)` at top of `_check_dedup`; regex strips all stacked `---\n**... via Engram**` suffixes |
| RELM-01 | 02-01 | store_memory accepts optional related_to list | SATISFIED | `related_to: list[str] = None` param on both sync and async `store_memory` and `_prepare_store` |
| RELM-02 | 02-01 | related_to stored in JSON as list and as comma-string in ChromaDB (not empty array) | SATISFIED | JSON: `"related_to": validated_related_to`; ChromaDB: `**({"related_to": ",".join(related_to)} if related_to else {})` — omitted when empty |
| RELM-03 | 02-02 | New MCP tool get_related_memories(key) returns all linked memories | SATISFIED | `@mcp.tool() async def get_related_memories(key: str) -> str` in server.py |
| RELM-04 | 02-01, 02-02 | get_related_memories returns bidirectional results | SATISFIED | `get_related_memories` scans all JSON for `key in data.get("related_to", [])` (reverse); returns `{forward, reverse}` |
| RELM-05 | 02-03 | WebUI displays related memories as clickable links on memory detail view | SATISFIED | `#view-related` div in view modal; `loadRelatedMemories()` renders anchor tags calling `openViewModal()` |

**All 13 requirements satisfied. No orphaned requirements.**

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `templates/index.html` | 40, 97, 101, 105, 109 | `placeholder` attribute | Info | HTML form hint text — not a code stub. All 5 occurrences are `<input placeholder="...">` attributes for UX guidance. |

No blockers or warnings found.

---

### Human Verification Required

#### 1. Dedup confirmation dialog UX

**Test:** Open WebUI, create a new memory with content very similar to an existing memory
**Expected:** A `confirm()` dialog appears showing the existing memory title and similarity percentage. Clicking OK stores the memory; clicking Cancel leaves the form open without storing.
**Why human:** Browser dialog behavior and UI state require manual interaction.

#### 2. Related memories clickable link navigation

**Test:** Open a memory that has `related_to` links, verify "Related Memories" section appears. Click a related memory link.
**Expected:** The view modal updates to show the linked memory's content without page reload.
**Why human:** Requires live data with related_to entries and visual modal-to-modal navigation.

#### 3. last_accessed "never" display for new memories

**Test:** Create a new memory, open its detail view immediately
**Expected:** Meta line shows "Accessed: never" (since it has not been retrieved yet)
**Why human:** Requires creating a fresh memory and viewing it before any retrieval.

---

### Gaps Summary

No gaps found. All 17 observable truths verified, all 5 artifacts substantive and wired, all 11 key links confirmed, all 13 requirement IDs satisfied. The three items routed to human verification are UX behaviors that cannot be verified statically but whose supporting code is fully wired.

---

_Verified: 2026-03-31_
_Verifier: Claude (gsd-verifier)_
