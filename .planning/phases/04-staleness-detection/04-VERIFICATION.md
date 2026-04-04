---
phase: 04-staleness-detection
verified: 2026-03-31T00:00:00Z
status: passed
score: 10/10 must-haves verified
re_verification: false
---

# Phase 4: Staleness Detection Verification Report

**Phase Goal:** Users can immediately see which memories are either time-stale (not accessed in 90+ days) or code-stale (source files changed since last index), with a dedicated WebUI tab and MCP tool for surfacing them
**Verified:** 2026-03-31
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | `get_stale_memories(days=0)` returns memories not accessed within the threshold | VERIFIED | Runtime confirms 2 results returned with correct shape; no `_days_since` key |
| 2  | Time-stale memories carry `days_since` in detail; code-stale carry `stale_reason` | VERIFIED | `stale_detail` field set conditionally: `"{N} days"` for time, `stale_reason` for code, combined for both |
| 3  | Evolve mode sets `potentially_stale=True`, `stale_reason`, `stale_flagged_at` before synthesis | VERIFIED | `flag_memory_stale()` called in `run_evolve()` loop before `index_domain()` at line 626 |
| 4  | No memory is ever automatically deleted — flagging is surfacing only (STAL-04) | VERIFIED | `flag_memory_stale()` only writes metadata fields; `api_reviewed` only resets fields; no delete call present in either stale route |
| 5  | `stale_days` threshold reads from `config.json` with default 90 | VERIFIED | `config.json` has `"stale_days": 90`; `_load_config()` defaults dict includes it; runtime `_config.get('stale_days')` == 90 |
| 6  | WebUI shows a Stale Memories tab button in the toolbar | VERIFIED | `<button id="btn-stale-tab" onclick="toggleStaleTab()">` present in toolbar between view-toggle and `+ New` |
| 7  | Stale tab shows badge-labeled rows (Time stale amber / Code changed blue / Time+Code purple) | VERIFIED | `loadStaleTab()` renders `.stale-badge .stale-time/.stale-code/.stale-both` with inline CSS color definitions |
| 8  | Each row shows key, title, detail, and Mark Reviewed button | VERIFIED | `loadStaleTab()` renders `stale-row` with `stale-title`, `esc(m.key)`, `stale-detail`, and `markReviewed` button |
| 9  | Clicking Mark Reviewed resets `last_accessed` (time-stale) or clears `potentially_stale` (code-stale) | VERIFIED | `api_reviewed` POST route applies conditional resets based on `stale_type`; no deletion |
| 10 | Human verification checkpoint passed | VERIFIED | Per user approval: tab loads, stale memories display with badge, Mark Reviewed fades row, no 500 errors |

**Score:** 10/10 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `config.json` | `stale_days` threshold | VERIFIED | Contains `"stale_days": 90` |
| `core/memory_manager.py` | `get_stale_memories()` sync + async | VERIFIED | Both `get_stale_memories` (line 689) and `get_stale_memories_async` (line 784) present; runtime import clean |
| `server.py` | `get_stale_memories` MCP tool | VERIFIED | `@mcp.tool()` decorator at line 243; `days` and `type` parameters confirmed |
| `engram_index.py` | `flag_memory_stale()` + evolve wiring | VERIFIED | Function defined at line 571; called in `run_evolve()` at line 626 before `index_domain()` |
| `webui.py` | `/api/stale` GET + `/api/memory/<key>/reviewed` POST | VERIFIED | Both routes defined at lines 135 and 146; `_now` imported from `core.memory_manager` |
| `templates/index.html` | Stale tab button + panel + JS functions + CSS badges | VERIFIED | All elements present: button (line 83), panel (line 118), `toggleStaleTab`, `loadStaleTab`, `markReviewed`, `.stale-time/.stale-code/.stale-both` CSS classes |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `server.py get_stale_memories` | `memory_manager.get_stale_memories_async()` | direct async call | WIRED | Line 260: `results = await memory_manager.get_stale_memories_async(days=days, type=type)` |
| `engram_index.py run_evolve()` | `memory_manager._save_json()` via `flag_memory_stale()` | helper called per changed domain | WIRED | `flag_memory_stale` imports and calls `memory_manager._load_json`/`_save_json`; invoked at line 626 |
| `core/memory_manager.py get_stale_memories()` | `JSON_DIR glob` | reads all JSON files | WIRED | Line 707: `for path in JSON_DIR.glob("*.json")` — computes time/code staleness from metadata |
| `index.html stale tab button` | `/api/stale` | `fetch('/api/stale')` in `loadStaleTab()` | WIRED | Line 259: `` const res = await fetch(`/api/stale?type=${filterType}`) `` |
| `index.html Mark Reviewed button` | `/api/memory/<key>/reviewed POST` | `fetch` in `markReviewed()` | WIRED | Line 298: `` fetch(`/api/memory/${encodeURIComponent(key)}/reviewed`, {method:'POST',...}) `` |
| `webui.py /api/stale` | `memory_manager.get_stale_memories()` | direct sync call | WIRED | Line 142: `results = memory_manager.get_stale_memories(days=days, type=filter_type)` |
| `webui.py /api/memory/<key>/reviewed` | `memory_manager._load_json()` + `_save_json()` | conditional field resets | WIRED | Lines 158-171: loads, resets fields by `stale_type`, saves — no deletion |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|-------------------|--------|
| `templates/index.html loadStaleTab()` | `items` (array) | `GET /api/stale` → `memory_manager.get_stale_memories()` → `JSON_DIR.glob("*.json")` | Yes — reads real JSON files on disk | FLOWING |
| `webui.py api_reviewed` | `data` (dict) | `memory_manager._load_json(key)` reads from `JSON_DIR/{hash}.json` | Yes — reads real JSON file, writes back | FLOWING |
| `server.py get_stale_memories` | `results` (list) | `memory_manager.get_stale_memories_async()` → same JSON glob path | Yes — runtime confirmed 2 results with `days=0` | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `get_stale_memories(days=0)` returns list with correct shape | `venv python -c "r = memory_manager.get_stale_memories(days=0); print(len(r))"` | 2 results; `structure valid: True`; no `_days_since` key | PASS |
| `_config['stale_days']` == 90 at runtime | `venv python -c "from core.memory_manager import _config; print(_config.get('stale_days'))"` | `90` | PASS |
| `server.py` imports cleanly with MCP tool registered | `venv python -c "import server; print('server ok')"` | `server ok` | PASS |
| `engram_index.py` imports cleanly with `flag_memory_stale` present | `venv python -c "import engram_index; print(flag_memory_stale)"` | function object confirmed | PASS |
| `webui.py` imports cleanly | `venv python -c "import webui; print('webui ok')"` | `webui ok` | PASS |
| Human: Stale tab visible, stale rows load, Mark Reviewed works | Manual browser test per plan 04-02 checkpoint | Approved by user | PASS |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|---------|
| STAL-01 | 04-02-PLAN.md | WebUI gets a "Stale Memories" tab showing memories not accessed in 90 days (configurable threshold) | SATISFIED | `btn-stale-tab` in toolbar; `stale-panel` with type filter; `loadStaleTab()` fetches `/api/stale`; Mark Reviewed calls `/api/memory/<key>/reviewed` |
| STAL-02 | 04-01-PLAN.md | When indexer detects file changes in a domain, memory is flagged as `potentially_stale` with `stale_reason` and `stale_flagged_at` | SATISFIED | `flag_memory_stale()` sets all three fields; called in `run_evolve()` before `index_domain()` |
| STAL-03 | 04-01-PLAN.md | New MCP tool `get_stale_memories(days=90)` returns memories past the threshold | SATISFIED | `@mcp.tool()` in `server.py` with `days` and `type` params; calls `get_stale_memories_async()`; returns formatted string with type badges |
| STAL-04 | 04-01-PLAN.md, 04-02-PLAN.md | No automatic deletion — surfacing only, human decides | SATISFIED | No delete call in any stale path; `api_reviewed` only resets metadata fields; `flag_memory_stale()` only writes to existing JSON; explicit STAL-04 comment in `api_reviewed` docstring |

**All 4 phase requirements (STAL-01, STAL-02, STAL-03, STAL-04) verified satisfied.**

No orphaned requirements: REQUIREMENTS.md traceability table lists only STAL-01 through STAL-04 for Phase 4. Both plans claim these IDs exhaustively.

---

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| None | — | — | — |

No stubs, placeholders, empty implementations, or TODO comments found in any of the four modified files. The `_days_since` internal sort key is properly stripped before returning results (line 780). The conservative `changed_count = len(domain_files)` in `run_evolve()` is a documented decision (upper bound), not a stub.

---

### Human Verification Required

Human checkpoint was approved prior to this verification. The following items are confirmed passing:

1. **Stale tab visible in toolbar** — "Stale" button appears between view toggle and `+ New`
2. **Stale panel loads correctly** — Clicking Stale hides memory cards and shows stale panel
3. **Badge colors render correctly** — Amber for Time stale, blue for Code changed, purple for Time+Code
4. **Mark Reviewed clears row** — Row fades out after POST succeeds; no 500 errors in Flask console

No outstanding human verification items remain.

---

### Gaps Summary

No gaps. All 10 truths verified, all 6 artifacts pass levels 1-4, all 7 key links wired, all 4 requirements satisfied, no anti-patterns found. Human checkpoint approved.

---

_Verified: 2026-03-31_
_Verifier: Claude (gsd-verifier)_
