---
phase: 02
slug: core-memory-enhancements
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-01
---

# Phase 02 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Built-in `--self-test` integration test in server.py |
| **Config file** | None — tests embedded in server.py CLI |
| **Quick run command** | `C:/Dev/Engram/venv/Scripts/python.exe server.py --self-test` |
| **Full suite command** | Same (extended in Plan 02-01 Task 2) |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python server.py --self-test`
- **After Plan 02-01:** Full self-test validates dedup, last_accessed, related_to
- **After Plan 02-02:** Self-test validates MCP tool signatures
- **After Plan 02-03:** Manual WebUI check (automated UI tests not available)

---

## Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command |
|--------|----------|-----------|-------------------|
| TRAK-01 | retrieve_memory updates last_accessed | integration | --self-test: verify last_accessed set after retrieve |
| TRAK-02 | search_memories updates last_accessed for all results | integration | --self-test: search, check JSON |
| TRAK-03 | Existing memories have last_accessed: null | integration | Read existing JSON, verify null |
| TRAK-04 | last_accessed in JSON metadata | integration | After store, verify field present |
| DEDU-01 | store_memory blocks near-duplicate (>=0.92) | integration | Store memory, store near-copy, verify DuplicateMemoryError |
| DEDU-02 | force=True overrides block | integration | Store near-copy with force=True, verify success |
| DEDU-03 | Threshold reads from config.json | integration | Set threshold=1.0, verify no dedup |
| DEDU-04 | Dedup strips audit suffix before comparison | integration | Update same key, verify passes dedup |
| RELM-01 | store_memory accepts related_to list | integration | Store with related_to, verify JSON |
| RELM-02 | related_to as list in JSON, comma-string in ChromaDB | integration | Verify both after store |
| RELM-03 | get_related_memories returns linked memories | integration | --self-test: store A→B, query A |
| RELM-04 | Bidirectional: query B returns A | integration | --self-test: query B after A→B link |
| RELM-05 | WebUI shows related memories as clickable links | manual | Browser check — inline section visible |

---

## Gaps

- No formal pytest suite — all validation via extended --self-test
- RELM-05 (WebUI) requires manual verification
- No automated browser/E2E tests for WebUI changes
