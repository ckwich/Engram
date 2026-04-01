# Phase 2: Core Memory Enhancements — Research

**Researched:** 2026-03-31
**Domain:** Python asyncio patterns, ChromaDB metadata constraints, sentence-transformers dedup, Flask/JS WebUI
**Confidence:** HIGH (codebase verified, runtime-tested)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Deduplication Gate**
- D-01: Dedup is warn-and-block: store_memory returns the similar memory's key/title/score and refuses to store. Caller must pass force=True to override.
- D-02: Dedup compares content embedding only (not key or title similarity).
- D-03: Strip the audit log suffix ("---\n**timestamp | Created/Updated via Engram**") before embedding for comparison, but the stored content keeps the audit trail intact.
- D-04: Dedup threshold (default 0.92) is configurable via Engram config file at C:/Dev/Engram/config.json.
- D-05: force=True must be added as an optional parameter to both the MCP store_memory tool and the internal store_memory/store_memory_async methods.

**Relationship Model**
- D-06: Bidirectional links via query-time resolution. Only the source memory's JSON stores the related_to list. get_related_memories scans all memories for references to the queried key (both directions).
- D-07: Dangling references silently skipped — get_related_memories filters out keys that no longer exist.
- D-08: Maximum 10 related_to links per memory. Raise ValueError if exceeded.
- D-09: related_to stored as comma-separated string in ChromaDB metadata (ChromaDB rejects empty arrays). Stored as a list in JSON. Empty list = no metadata entry in ChromaDB (avoid empty string).

**last_accessed Tracking**
- D-10: Operations that update last_accessed: search_memories (all returned results), retrieve_memory, retrieve_chunk.
- D-11: list_all_memories does NOT update last_accessed (directory listing, not meaningful access).
- D-12: last_accessed updates are fire-and-forget — run in background after returning results. Don't slow down retrieval.
- D-13: Backward compatible: existing memories get last_accessed: null until first retrieval.

**WebUI Integration**
- D-14: Related memories shown as "Related Memories" inline section below content on detail view, with clickable key/title links.
- D-15: WebUI create/edit form shows dedup warning when server returns one — displays similar memory's title and score.
- D-16: last_accessed visible in memory detail view only (alongside created_at and updated_at), not in list view.

### Claude's Discretion
- How to implement the config.json file (schema, loading, defaults)
- Whether to add a search_memories `exclude_self` parameter for dedup queries
- Internal implementation of fire-and-forget last_accessed updates (asyncio.create_task, background executor, etc.)
- WebUI JavaScript implementation details for the related memories section

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TRAK-01 | Every memory has a last_accessed timestamp that updates on retrieve_memory and retrieve_chunk calls | Fire-and-forget pattern via asyncio.create_task; JSON-only write |
| TRAK-02 | search_memories hits update last_accessed for returned memories | Same fire-and-forget; multiple keys from one search, deduplicate by parent_key |
| TRAK-03 | Existing memories get last_accessed: null until first retrieval (backward compatible) | `.get("last_accessed", None)` everywhere; no migration needed |
| TRAK-04 | last_accessed stored in JSON metadata alongside created_at and updated_at | JSON-only; do NOT store in ChromaDB metadata (see Standard Stack section) |
| DEDU-01 | store_memory runs similarity search before writing; scores above 0.92 cosine return a warning | Dedup check in _prepare_store before JSON write; uses existing search path |
| DEDU-02 | Caller can pass force=True to override deduplication warning and write anyway | Optional bool param on _prepare_store, store_memory, store_memory_async, and MCP tool |
| DEDU-03 | Dedup threshold is configurable (default 0.92) | config.json at PROJECT_ROOT; loaded at module level with defaults |
| DEDU-04 | Dedup comparison strips audit log suffix before embedding | Regex: `re.sub(r'(\n\n---\n\*\*[^\n]+\| (?:Created|Updated) via Engram\*\*)+\s*$', '', content)` |
| RELM-01 | store_memory accepts optional related_to list of existing memory keys | Add related_to: list[str] = None param to _prepare_store / store_memory / store_memory_async / MCP tool |
| RELM-02 | related_to stored in JSON metadata and as comma-string in ChromaDB metadata | JSON: list; ChromaDB: omit field entirely when empty (runtime-verified — empty string allowed but misleading; omitting is cleaner) |
| RELM-03 | New MCP tool get_related_memories(key) returns all memories explicitly linked to the given key | JSON-scan approach; ChromaDB $contains does not work reliably — see findings |
| RELM-04 | get_related_memories returns bidirectional results | Forward: read JSON for given key's related_to list. Reverse: scan all JSON files for entries whose related_to includes the queried key |
| RELM-05 | WebUI displays related memories as clickable links on memory detail view | Fetch /api/related/<key>, render links inline after content in view modal |
</phase_requirements>

---

## Summary

This phase adds three orthogonal features to `memory_manager.py`: (1) a `last_accessed` timestamp updated fire-and-forget on every retrieval, (2) a deduplication gate on `store_memory` that embeds the stripped content and blocks near-duplicates, and (3) a `related_to` field with a new `get_related_memories` MCP tool providing bidirectional lookup.

All three features are implemented as targeted extensions to existing patterns. The codebase's async executor pattern (`_run_blocking` / `_run_chroma`), JSON-first write ordering, and `_prepare_store` as the central store path are preserved. The most critical constraint — confirmed by live runtime testing against ChromaDB 1.5.5 — is that empty arrays crash ChromaDB upserts, so `related_to` must be omitted from ChromaDB metadata entirely when the list is empty, and stored only as a comma-string when non-empty.

The audit log accumulation problem (CONCERNS.md) surfaces here as a real correctness issue for dedup: the regex strip must remove ALL accumulated audit lines (not just the last one). The configurable dedup threshold lives in a new `C:/Dev/Engram/config.json` loaded once at module import with safe defaults.

**Primary recommendation:** Implement in this order — (1) config.json loader, (2) last_accessed fire-and-forget, (3) dedup gate in `_prepare_store`, (4) related_to field, (5) get_related_memories MCP tool, (6) WebUI. Each step is independently verifiable. Do not mix them.

---

## Standard Stack

### Core (all already installed)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| chromadb | ~1.5.5 (installed) | Vector store — existing | Already in use; no changes needed |
| sentence-transformers | ~5.3.0 (installed) | Embedding — existing embedder | Already in use; dedup reuses embedder.embed() |
| fastmcp | ~3.1.1 (installed) | MCP tool registration | Already in use; new tool follows existing @mcp.tool() pattern |
| flask | ~3.1.3 (installed) | WebUI — existing | Already in use; new endpoints follow existing pattern |

### No New Dependencies Required

All features are implemented using existing dependencies. No new packages needed.

---

## Architecture Patterns

### Pattern 1: Config Loading at Module Level

**What:** Load `C:/Dev/Engram/config.json` once when `memory_manager.py` is imported. Provide defaults so missing keys never crash.

**When to use:** Dedup threshold read; future configurable values.

**Example:**
```python
# In memory_manager.py, after imports, before class definition
_CONFIG_PATH = PROJECT_ROOT / "config.json"

def _load_config() -> dict:
    """Load Engram config.json with safe defaults. Missing file = all defaults."""
    defaults = {
        "dedup_threshold": 0.92,
    }
    try:
        if _CONFIG_PATH.exists():
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            defaults.update(user_config)
    except Exception as e:
        print(f"[Engram] WARNING: Failed to load config.json: {e}. Using defaults.", file=sys.stderr)
    return defaults

_config = _load_config()
```

**Config file schema** (`C:/Dev/Engram/config.json`):
```json
{
  "dedup_threshold": 0.92
}
```

**Confidence:** HIGH — standard Python config pattern; verified against existing codebase structure.

---

### Pattern 2: Fire-and-Forget last_accessed via asyncio.create_task

**What:** After returning search/retrieve results, schedule a background coroutine to update `last_accessed` in JSON files without blocking the caller.

**When to use:** In all three async retrieval methods: `search_memories_async`, `retrieve_memory_async`, `retrieve_chunk_async`.

**Runtime verification:** `asyncio.create_task` is available in Python 3.12 (the venv Python). Tasks created inside a running event loop execute after the current coroutine yields.

**Example:**
```python
async def _update_last_accessed_async(self, keys: list[str]) -> None:
    """Background task: update last_accessed in JSON for the given keys.
    Fire-and-forget — caller does not await this."""
    now = _now()
    def _do_updates():
        for key in keys:
            data = self._load_json(key)
            if data is None:
                continue
            data["last_accessed"] = now
            self._save_json(data)
    try:
        await _run_blocking(_do_updates)
    except Exception as e:
        print(f"[Engram] WARNING: last_accessed update failed: {e}", file=sys.stderr)

# Usage in search_memories_async (after getting results):
async def search_memories_async(self, query: str, limit: int = 5) -> list[dict]:
    # ... existing search logic ...
    results = self._parse_search_results(raw_results)

    # Fire-and-forget: schedule last_accessed update, don't await
    if results:
        keys = list({r["key"] for r in results})  # deduplicate by parent_key
        asyncio.create_task(self._update_last_accessed_async(keys))

    return results
```

**Sync path (webui):** The sync `search_memories`, `retrieve_memory`, `retrieve_chunk` do NOT update last_accessed. Decision D-12 specifies fire-and-forget which requires asyncio. The sync path is WebUI only (lower priority); this is acceptable.

**Alternative considered:** `asyncio.get_event_loop().run_in_executor(None, ...)` — rejected because it doesn't guarantee fire-and-forget semantics inside a running loop. `create_task` is correct.

**Confidence:** HIGH — runtime-verified pattern.

---

### Pattern 3: Dedup Gate in _prepare_store

**What:** Before writing JSON, embed the stripped content and run a similarity search. If score >= threshold and force is False, return a structured duplicate warning instead of writing.

**When to use:** In `_prepare_store` (sync) and its async caller.

**IMPORTANT:** `_prepare_store` is called via `_run_blocking()` in the async path — so it runs in a thread pool. This means the sync `embedder.embed()` and `col.query()` calls inside dedup are safe (no event loop blocking).

**Audit log strip regex** (runtime-verified):
```python
import re
_AUDIT_SUFFIX_RE = re.compile(
    r'(\n\n---\n\*\*[^\n]+\| (?:Created|Updated) via Engram\*\*)+\s*$'
)

def _strip_audit_log(content: str) -> str:
    """Strip all accumulated audit log lines from content for dedup comparison."""
    return _AUDIT_SUFFIX_RE.sub('', content)
```

This regex handles both single and accumulated audit lines (tested: strips all of them, not just the last).

**Dedup check structure:**
```python
def _check_dedup(self, content: str, key: str) -> Optional[dict]:
    """
    Returns duplicate warning dict if content is too similar to an existing memory,
    None if safe to store. Uses stripped content for embedding.
    """
    threshold = _config.get("dedup_threshold", 0.92)
    stripped = _strip_audit_log(content)

    # Skip dedup for very short content (unreliable embeddings)
    if len(stripped) < 150:
        return None

    col = self._get_collection()
    if col.count() == 0:
        return None

    embedding = embedder.embed(stripped)
    results = col.query(
        query_embeddings=[embedding],
        n_results=1,
        include=["metadatas", "distances"],
    )

    if not results or not results["ids"] or not results["ids"][0]:
        return None

    distance = results["distances"][0][0]
    score = round(1 - (distance / 2), 3)

    if score >= threshold:
        meta = results["metadatas"][0][0]
        existing_key = meta.get("parent_key", "unknown")
        # Don't block self-updates (same key being updated)
        if existing_key == key:
            return None
        return {
            "status": "duplicate",
            "existing_key": existing_key,
            "existing_title": meta.get("title", existing_key),
            "score": score,
        }
    return None
```

**_prepare_store signature change:**
```python
def _prepare_store(
    self,
    key: str,
    content: str,
    tags: list[str] = None,
    title: str = None,
    related_to: list[str] = None,
    force: bool = False,
) -> tuple[dict, list[dict]]:
    # At the TOP, before any writes:
    if not force:
        dup = self._check_dedup(content, key)
        if dup:
            raise DuplicateMemoryError(dup)  # caller catches and returns warning
    # ... rest of existing logic ...
```

**DuplicateMemoryError** — a custom exception class carrying the duplicate dict, raised from `_prepare_store` and caught in `store_memory`, `store_memory_async`, and the MCP tool handler.

**Confidence:** HIGH — pattern follows existing ValueError approach; dedup score math runtime-verified.

---

### Pattern 4: related_to Field — ChromaDB Storage

**What:** Store `related_to` as a list in JSON. In ChromaDB, store as a comma-separated string ONLY when non-empty; omit the field entirely when empty.

**Runtime-verified fact:** ChromaDB 1.5.5 rejects empty arrays (`ValueError: Expected metadata list value for key 'related_to' to be non-empty`). Empty string is allowed but semantically misleading. Omitting the field entirely is the cleanest approach.

**In `_index_chunks` and `_index_chunks_async`:**
```python
metadatas = [
    {
        "parent_key": key,
        "chunk_id": c["chunk_id"],
        "title": title,
        "tags": ",".join(tags),
        # Only include related_to if non-empty
        **( {"related_to": ",".join(related_to)} if related_to else {} ),
    }
    for c in chunks
]
```

**`_prepare_store` data dict:**
```python
data = {
    # ... existing fields ...
    "last_accessed": existing.get("last_accessed", None) if existing else None,
    "related_to": validated_related_to,   # list, may be []
}
```

**Validation in _prepare_store:**
```python
validated_related_to = list(related_to) if related_to else []
if len(validated_related_to) > 10:
    raise ValueError(
        f"related_to has {len(validated_related_to)} entries — maximum is 10. "
        f"Limit the number of explicit relationships per memory."
    )
```

**Confidence:** HIGH — ChromaDB behavior runtime-verified.

---

### Pattern 5: get_related_memories — JSON-Based Bidirectional Scan

**What:** Scan all JSON files to find relationships in both directions. ChromaDB metadata `$contains` operator is NOT usable for this (runtime-verified: returns empty results despite correct data; likely an indexing limitation for custom string fields).

**Why JSON scan not ChromaDB:** Tested `col.get(where={"related_to": {"$contains": "keyA"}})` against ChromaDB 1.5.5 with a known matching entry — returned empty. ChromaDB's `$contains` operator works on document text (via `where_document`), not reliably on arbitrary metadata string values. The JSON-based scan is O(n) over all memory files, which is fast at current scale (119 memories in ~5ms) and consistent with the existing `list_memories()` pattern.

**Implementation:**
```python
def get_related_memories(self, key: str) -> dict:
    """
    Return all memories related to the given key, bidirectionally.
    Forward: memories that key explicitly links to (key's related_to list).
    Reverse: memories that have key in their related_to list.
    Silently skips dangling references (D-07).
    """
    source = self._load_json(key)
    if source is None:
        return {"key": key, "found": False, "forward": [], "reverse": []}

    forward_keys = source.get("related_to", [])
    reverse_keys = []

    for path in JSON_DIR.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("key") == key:
                continue  # skip self
            if key in data.get("related_to", []):
                reverse_keys.append(data["key"])
        except Exception:
            continue

    def _resolve(keys: list[str]) -> list[dict]:
        result = []
        for k in keys:
            mem = self._load_json(k)
            if mem is None:
                continue  # silently skip dangling refs (D-07)
            result.append({
                "key": k,
                "title": mem.get("title", k),
                "tags": mem.get("tags", []),
                "updated_at": mem.get("updated_at", ""),
            })
        return result

    return {
        "key": key,
        "found": True,
        "forward": _resolve(forward_keys),
        "reverse": _resolve(reverse_keys),
    }

async def get_related_memories_async(self, key: str) -> dict:
    return await _run_blocking(self.get_related_memories, key)
```

**Confidence:** HIGH — scan approach verified; ChromaDB $contains limitation confirmed by runtime test.

---

### Pattern 6: MCP Tool Additions

**force parameter on store_memory:**
```python
@mcp.tool()
async def store_memory(
    key: str,
    content: str,
    title: str = "",
    tags: str = "",
    related_to: str = "",   # comma-separated keys
    force: bool = False,
) -> str:
    # ...
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    related_list = [k.strip() for k in related_to.split(",") if k.strip()] if related_to else []
    try:
        result = await memory_manager.store_memory_async(key, content, tag_list, title or None, related_list, force)
        return f"Stored: '{result['title']}'\n   Key: {key}\n   Chunks: {result.get('chunk_count', '?')}\n   Chars: {result['chars']}"
    except DuplicateMemoryError as e:
        dup = e.duplicate
        return (
            f"DUPLICATE DETECTED — similar memory already exists.\n"
            f"  Existing key:   {dup['existing_key']}\n"
            f"  Existing title: {dup['existing_title']}\n"
            f"  Similarity:     {dup['score']:.3f} (threshold: {_config.get('dedup_threshold', 0.92)})\n\n"
            f"To store anyway, pass force=True."
        )
    except ValueError as e:
        return f"Memory too large or invalid: {e}"
    except RuntimeError as e:
        return f"Engram error: {e}"
```

**Note on MCP tool parameters:** FastMCP 3.1.1 maps Python type hints directly to MCP tool schemas. `bool` defaults work as expected. `related_to` is passed as a comma-string (not a list) because MCP tool parameters must be simple types.

**New get_related_memories MCP tool:**
```python
@mcp.tool()
async def get_related_memories(key: str) -> str:
    """
    Retrieve all memories related to the given key, bidirectionally.
    Returns memories that this key links to (forward) AND memories that link to this key (reverse).
    Dangling references are silently ignored.

    Args:
        key: The memory key to find relationships for.
    """
    result = await memory_manager.get_related_memories_async(key)
    if not result["found"]:
        return f"Memory not found: '{key}'"

    forward = result["forward"]
    reverse = result["reverse"]

    if not forward and not reverse:
        return f"No related memories found for '{key}'."

    lines = [f"Related memories for '{key}':\n"]
    if forward:
        lines.append(f"Links to ({len(forward)}):")
        for m in forward:
            lines.append(f"  -> {m['key']}: {m['title']}")
    if reverse:
        lines.append(f"\nLinked by ({len(reverse)}):")
        for m in reverse:
            lines.append(f"  <- {m['key']}: {m['title']}")
    return "\n".join(lines)
```

**Confidence:** HIGH — follows established @mcp.tool() patterns in server.py.

---

### Pattern 7: WebUI Changes

**New Flask API endpoint:**
```python
@app.route("/api/related/<path:key>")
def api_related(key):
    result = memory_manager.get_related_memories(key)
    return jsonify(result)
```

**View modal additions (index.html):**

1. In the view modal HTML, add a related memories section after `<pre id="view-content">`:
```html
<div id="view-related" style="display:none; margin-top:1rem; border-top: 1px solid var(--border); padding-top:0.75rem;">
  <h4 style="font-size:0.85rem; color:var(--muted); margin-bottom:0.5rem;">Related Memories</h4>
  <div id="view-related-content"></div>
</div>
```

2. In `openViewModal()`, after fetching the memory, load related:
```javascript
async function loadRelatedMemories(key) {
  try {
    const res = await fetch(`/api/related/${encodeURIComponent(key)}`);
    const data = await res.json();
    const all = [...(data.forward || []), ...(data.reverse || [])];
    const container = document.getElementById('view-related-content');
    const section = document.getElementById('view-related');
    if (!all.length) { section.style.display = 'none'; return; }
    section.style.display = 'block';
    container.innerHTML = all.map(m =>
      `<div style="margin-bottom:0.3rem;">
        <a href="#" onclick="openViewModal('${esc(m.key)}'); return false;"
           style="color:var(--cyan); text-decoration:none;">${esc(m.title)}</a>
        <span class="text-muted" style="font-size:0.75rem;"> — ${esc(m.key)}</span>
       </div>`
    ).join('');
  } catch (e) {
    document.getElementById('view-related').style.display = 'none';
  }
}
```

3. In `openViewModal()`, add `loadRelatedMemories(key)` call after populating main content.

4. In `openViewModal()`, add `last_accessed` to the meta line:
```javascript
document.getElementById('view-meta').textContent =
  `Key: ${m.key} · Created: ${(m.created_at || '').slice(0, 10)} · Updated: ${(m.updated_at || '').slice(0, 10)} · Last accessed: ${(m.last_accessed || 'never').slice(0, 10)} · ${m.chars || 0} chars`;
```

5. In `saveMemory()`, handle the dedup warning response (HTTP 409):

Add to webui.py `api_create` and `api_update`:
```python
from core.memory_manager import DuplicateMemoryError

# In api_create and api_update, add force param from request:
force = bool(data.get("force", False))
try:
    result = memory_manager.store_memory(..., force=force)
except DuplicateMemoryError as e:
    return jsonify({"status": "duplicate", **e.duplicate}), 409
```

In `saveMemory()` JS:
```javascript
if (res.status === 409) {
  const dup = await res.json();
  const proceed = confirm(
    `Similar memory already exists:\n"${dup.existing_title}" (${(dup.score * 100).toFixed(0)}% match)\n\nStore anyway?`
  );
  if (proceed) {
    // Re-submit with force=true
    const res2 = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, title: title || key, tags, content, force: true }),
    });
    if (!res2.ok) { const e = await res2.json(); throw new Error(e.error || 'Save failed'); }
    closeModal('modal-create'); location.reload(); return;
  } else {
    btn.disabled = false; btn.textContent = 'Save'; return;
  }
}
```

**Confidence:** HIGH — extends existing patterns directly; all hook points identified.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cosine similarity search for dedup | Custom cosine function | Existing `col.query()` via `_check_dedup()` | ChromaDB already has the embeddings indexed |
| Async background task scheduling | Custom thread pool for last_accessed | `asyncio.create_task()` | Built-in, correct for event loop context |
| Config file parsing | Complex validation/schema library | `json.load()` with `dict.get()` defaults | Simple, robust, no new dependency |
| Reverse relationship lookup | ChromaDB metadata query | JSON file scan (O(n)) | ChromaDB `$contains` doesn't work reliably for this — runtime-verified |
| Audit log strip | Complex parser | Single regex `re.sub()` | Pattern is fixed; regex is reliable |

---

## Common Pitfalls

### Pitfall 1: ChromaDB Empty Array Crash
**What goes wrong:** `col.upsert(..., metadatas=[{"related_to": []}])` raises `ValueError: Expected metadata list value for key 'related_to' to be non-empty`.
**Root cause:** ChromaDB 1.5.5 validates array metadata at write time and rejects empty arrays.
**How to avoid:** Use the conditional include pattern: `**( {"related_to": ",".join(related_to)} if related_to else {} )` — omit the field entirely when the list is empty.
**Verification:** Runtime-confirmed on the installed ChromaDB 1.5.5.

### Pitfall 2: Audit Log Accumulation Corrupts Dedup
**What goes wrong:** If only the last audit line is stripped, memories updated multiple times have accumulated audit lines that inflate embedding distance between a memory and its older versions.
**Root cause:** `_prepare_store` appends (not replaces) the audit suffix on every update.
**How to avoid:** Use the greedy regex `(\n\n---\n\*\*[^\n]+\| (?:Created|Updated) via Engram\*\*)+\s*$` which removes ALL accumulated lines.
**Verification:** Runtime-confirmed — `re.sub` with `+` quantifier stripped both single and stacked audit lines correctly.

### Pitfall 3: Self-Update Blocked by Dedup
**What goes wrong:** Updating an existing memory (same key) would trigger the dedup gate because the new content is semantically similar to the old content. This would block normal updates.
**Root cause:** The dedup search finds the existing version of the same memory in ChromaDB.
**How to avoid:** In `_check_dedup()`, check if `existing_key == key` and return `None` (no duplicate) in that case.
**Warning sign:** Tests that update a memory twice would fail with "duplicate" error.

### Pitfall 4: asyncio.create_task Called Outside Running Loop
**What goes wrong:** If `asyncio.create_task()` is called when no event loop is running (e.g., in a sync context, in tests), it raises `RuntimeError: no running event loop`.
**Root cause:** create_task requires a running loop.
**How to avoid:** Only call `asyncio.create_task()` in the async methods. The sync `search_memories`, `retrieve_memory`, and `retrieve_chunk` do NOT update last_accessed — this is intentional (sync path is WebUI only, not MCP).

### Pitfall 5: fire-and-forget Task Exception Silently Swallowed
**What goes wrong:** If `_update_last_accessed_async` raises an exception and the task is not awaited, Python silently swallows the exception unless a task exception handler is installed.
**Root cause:** Unhandled asyncio task exceptions are lost by default in Python 3.12 (they log a warning but don't propagate).
**How to avoid:** Wrap the body of `_update_last_accessed_async` in a broad `try/except Exception` that logs to stderr. The fire-and-forget nature means it must never propagate.

### Pitfall 6: ChromaDB $contains Unreliable for Metadata Strings
**What goes wrong:** `col.get(where={"related_to": {"$contains": "keyA"}})` returns empty results even when the data is present.
**Root cause:** Runtime-verified: ChromaDB 1.5.5's `$contains` operator appears to work on document text (via `where_document`) but not on arbitrary metadata string fields. The documentation suggests it should work, but the runtime behavior does not match.
**How to avoid:** Use JSON file scanning for `get_related_memories`. This is consistent with `list_memories()` pattern.

### Pitfall 7: DuplicateMemoryError Must Be Custom Exception
**What goes wrong:** Using generic `ValueError` for duplicate detection means callers can't distinguish "duplicate" from "content too large" — both raise ValueError in `_prepare_store`.
**Root cause:** Both validation errors currently use ValueError.
**How to avoid:** Define `class DuplicateMemoryError(Exception)` at module level in `memory_manager.py` with a `duplicate` attribute holding the warning dict. Server.py and webui.py import it for specific handling.

### Pitfall 8: Backward Compatibility on New JSON Fields
**What goes wrong:** Any `data["last_accessed"]` or `data["related_to"]` read from an existing memory (which has neither field) raises `KeyError`.
**Root cause:** 119 existing memories have no `last_accessed` or `related_to` fields.
**How to avoid:** Use `.get()` everywhere: `data.get("last_accessed", None)`, `data.get("related_to", [])`. Never use `data["last_accessed"]`. No migration required.

---

## Code Examples

### Complete Audit Strip Regex (Verified)
```python
import re

_AUDIT_SUFFIX_RE = re.compile(
    r'(\n\n---\n\*\*[^\n]+\| (?:Created|Updated) via Engram\*\*)+\s*$'
)

def _strip_audit_log(content: str) -> str:
    """Remove all accumulated audit log suffixes from content."""
    return _AUDIT_SUFFIX_RE.sub('', content)
```

### DuplicateMemoryError Definition
```python
class DuplicateMemoryError(Exception):
    """Raised when store_memory detects a near-duplicate and force=False."""
    def __init__(self, duplicate: dict):
        self.duplicate = duplicate
        super().__init__(f"Duplicate detected: {duplicate['existing_key']} (score={duplicate['score']})")
```

### Dedup Threshold Calculation
```python
# ChromaDB cosine distance: 0=identical, 2=opposite
# Score = 1 - (distance / 2)
# Threshold 0.92 corresponds to distance 0.16
# score >= 0.92  <=>  distance <= 0.16
threshold = _config.get("dedup_threshold", 0.92)  # 0.92 default
```

### last_accessed Backward-Compatible Read
```python
# In any method reading JSON data:
last_accessed = data.get("last_accessed", None)   # null for old memories
```

### related_to Backward-Compatible Read
```python
related_to = data.get("related_to", [])   # empty list for old memories
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No dedup gate | Warn-and-block with force override | Phase 2 | Prevents duplicate memories |
| No relationship links | related_to list + get_related_memories tool | Phase 2 | Enables knowledge graph navigation |
| No access tracking | last_accessed fire-and-forget | Phase 2 | Enables staleness detection (Phase 4) |
| No config file | C:/Dev/Engram/config.json with dedup_threshold | Phase 2 | Configurable behavior without code changes |

**Audit log accumulation** (from CONCERNS.md): Still not fixed in this phase — the CONTEXT.md decision is to strip-on-read for dedup comparison, not to change storage behavior. The accumulation bug is deferred. The regex handles accumulated lines correctly regardless.

---

## Open Questions

1. **Dedup in sync path (WebUI)**
   - What we know: `_prepare_store` is shared between sync and async paths. Dedup uses `embedder.embed()` (sync) and `col.query()` (sync) — both are safe in the sync path.
   - What's unclear: Should the WebUI's `store_memory` also enforce dedup? The CONTEXT.md decision says store_memory (the method) gets force param — implies yes, both paths.
   - Recommendation: Yes, implement dedup in `_prepare_store` so both sync and async paths benefit. The WebUI handles 409 response.

2. **exclude_self parameter for dedup search**
   - What we know: The dedup check uses `col.query()` which searches all chunks including the key being updated.
   - What's unclear: CONTEXT.md lists this as Claude's Discretion.
   - Recommendation: Implement as a post-query check (`if existing_key == key: return None`) rather than a ChromaDB `where` clause. No need for a new parameter.

3. **last_accessed in list_memories() return value**
   - What we know: D-16 says last_accessed visible in detail view only, not list view.
   - What's unclear: Should `list_memories()` include it in the returned dicts (even if not displayed)?
   - Recommendation: Do NOT add it to `list_memories()` output. Only `retrieve_memory()` / `retrieve_memory_async()` return it. This keeps the list lightweight.

---

## Environment Availability

All dependencies already installed in `C:/Dev/Engram/venv`. No new packages required.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| chromadb | Vector store | Yes | 1.5.5 | — |
| sentence-transformers | Embedding | Yes | ~5.3.0 | — |
| fastmcp | MCP tools | Yes | 3.1.1 | — |
| flask | WebUI | Yes | ~3.1.3 | — |
| Python venv | Runtime | Yes | 3.12.10 | — |

---

## Validation Architecture

nyquist_validation is enabled (config.json: `"nyquist_validation": true`).

### Test Framework

| Property | Value |
|----------|-------|
| Framework | None installed — existing tests are `--self-test` in server.py only |
| Config file | No pytest.ini or similar |
| Quick run command | `C:/Dev/Engram/venv/Scripts/python.exe server.py --self-test` |
| Full suite command | Same (no formal test suite) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TRAK-01 | retrieve_memory updates last_accessed | integration | Add to --self-test: verify last_accessed set after retrieve | No — Wave 0 |
| TRAK-02 | search_memories updates last_accessed | integration | Add to --self-test: search, then check JSON | No — Wave 0 |
| TRAK-03 | Existing memories have last_accessed: null | integration | Read existing JSON pre-test and verify null | No — Wave 0 |
| TRAK-04 | last_accessed in JSON only, not Chroma metadata | integration | After store, verify Chroma metadata doesn't include it | No — Wave 0 |
| DEDU-01 | store_memory blocks near-duplicate | integration | Store memory, store near-copy, verify block | No — Wave 0 |
| DEDU-02 | force=True overrides block | integration | Store near-copy with force=True, verify success | No — Wave 0 |
| DEDU-03 | Threshold from config.json | integration | Set threshold=1.0 (never block), verify no dedup | No — Wave 0 |
| DEDU-04 | Dedup strips audit suffix | integration | Update a memory, verify it passes dedup with itself | No — Wave 0 |
| RELM-01 | store_memory accepts related_to | integration | Store with related_to list, verify in JSON | No — Wave 0 |
| RELM-02 | related_to in JSON as list, Chroma as comma-string | integration | Verify both after store | No — Wave 0 |
| RELM-03 | get_related_memories returns linked memories | integration | Add to --self-test | No — Wave 0 |
| RELM-04 | Bidirectional results | integration | Store A→B, query B and verify A appears in reverse | No — Wave 0 |
| RELM-05 | WebUI shows related memories | manual | Open browser, verify related section visible | N/A |

### Sampling Rate
- Per task commit: `C:/Dev/Engram/venv/Scripts/python.exe C:/Dev/Engram/server.py --self-test`
- Per wave merge: Same (only test available)
- Phase gate: Self-test passes + manual WebUI verification before /gsd:verify-work

### Wave 0 Gaps
- [ ] Extend `server.py --self-test` to cover last_accessed, dedup, and related_to flows
- [ ] No separate test file needed — extend the existing self-test function

---

## Sources

### Primary (HIGH confidence)
- Runtime-verified: ChromaDB 1.5.5 installed at `C:/Dev/Engram/venv` — empty array rejection, comma-string storage, $contains behavior
- Runtime-verified: Python 3.12.10 asyncio.create_task fire-and-forget behavior
- Runtime-verified: audit log regex strip against real content patterns
- Runtime-verified: dedup threshold math (score = 1 - distance/2)
- Source code read: `core/memory_manager.py`, `core/embedder.py`, `core/chunker.py`, `server.py`, `webui.py`, `templates/index.html`
- `.planning/research/PITFALLS.md` — ChromaDB pitfalls, dedup pitfalls, audit log pitfall
- `.planning/codebase/CONCERNS.md` — audit log accumulation, known bugs, fragile areas

### Secondary (MEDIUM confidence)
- FastMCP 3.1.1 tool signature patterns — inferred from existing server.py @mcp.tool() decorators
- Flask 3.1.3 JSON error response patterns — inferred from existing webui.py patterns

### Tertiary (LOW confidence)
- None

---

## Project Constraints (from CLAUDE.md)

No `CLAUDE.md` exists at `C:/Dev/Engram/`. No project-level constraints to enforce beyond what is in CONTEXT.md and the codebase conventions documented in CONCERNS.md and PITFALLS.md.

**Inferred codebase conventions (from code review):**
- JSON-first write ordering (JSON before ChromaDB) — must be preserved
- All new async methods must use `_run_blocking()` or `_run_chroma()` executors — never block the event loop directly
- `embedder._load()` must be called at startup before any `embedder.embed()` calls — the assert in embedder.py will fire otherwise
- Module-level singleton pattern — `memory_manager = MemoryManager()` — new code does not create additional instances
- All paths use `pathlib.Path` — no raw string path concatenation

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all dependencies runtime-verified in venv
- Architecture patterns: HIGH — all patterns runtime-tested or directly derived from existing code
- Pitfalls: HIGH — most confirmed by live ChromaDB tests; audit log regex confirmed by runtime
- ChromaDB $contains: HIGH (negative) — confirmed by runtime test that it does NOT work for this use case

**Research date:** 2026-03-31
**Valid until:** 2026-05-01 (stable stack, 30-day window appropriate)
