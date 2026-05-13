# Engram Memory Fallback - 2026-05-13

Use this as an import-ready closeout memory if Engram MCP or the daemon-backed
Memory OS write path is unavailable.

## Key

engram_memory_os_rebuild_1_0_gate_2026_05_13

## Title

Engram Memory OS rebuild 1.0 gate and daemon runtime handoff

## Tags

engram, memory-os, 1.0, daemon, lancedb, kuzu, migration, release-gate

## Project

Engram

## Domain

memory-os

## Status

active

## Content

Branch `codex/backend-promotion-single-owner` now has the Memory OS 1.0 rebuild
gate committed through `cabd6f77`.

Committed slices:

- `2a77efa8 feat: route daemon memory ops through Memory OS`
  - `engramd` stable memory routes use `MemoryOSRuntime` when the daemon owns
    it: duplicate checks, store, search, chunk/full read, metadata update,
    metadata repair, and delete.
  - Memory OS stores reviewed memories in SQLite ledger records plus
    content-addressed artifacts and rebuilds LanceDB chunks from ledger rows.
  - Daemon smoke output now reports storage/search backend details.
  - Metadata updates now produce distinct transaction receipts instead of
    reusing content-only store receipts.
- `5faa524b docs: prepare Memory OS rebuild 1.0 gate`
  - README, AGENTS, `plan.md`, rebuild spec, active implementation plan,
    release checklist, and migration guide now describe local 1.0 as the
    rebuilt daemon-owned Memory OS.
  - Added `docs/ENGRAM_MEMORY_OS_1_0_RELEASE_CHECKLIST.md`.
  - Added `docs/ENGRAM_MEMORY_OS_1_0_MIGRATION_GUIDE.md`.
- `cabd6f77 fix: warn on duplicate Engram daemons`
  - Process hygiene now warns when multiple `engramd.py` daemon processes are
    present for this checkout and recommends keeping one daemon owner after
    confirming which PID owns the active `ENGRAM_DAEMON_URL`.

Validation completed:

- `python server.py --help` reports Engram 1.0.0.
- `python -c "from core.memory_manager import memory_manager; print('ok')"`
  printed `ok`.
- `codex mcp get engram` reports enabled stdio registration using
  `server_daemon_client.py` with `ENGRAM_DAEMON_URL` and `ENGRAM_DATA_DIR`.
- `python engramd.py --doctor` reports daemon health `ok`; it also reports two
  daemon processes and two MCP adapter processes for this checkout.
- `python engramd.py --smoke-test` against the currently running daemon passed
  functionally, but backend details were `null`, which means the live daemon is
  still an older legacy-backed process and must be restarted to pick up the new
  Memory OS route code.
- Disposable fresh-daemon smoke passed:
  `ENGRAM_LIVE_DAEMON_SMOKE=1 pytest tests/test_engramd_smoke.py::test_live_engramd_subprocess_smoke -q`.
- Focused runtime/process tests passed:
  `pytest tests/test_process_hygiene.py tests/test_engramd_smoke.py tests/memory_os/test_runtime.py tests/test_engramd_api.py -q`.
- Full suite passed: `481 passed, 2 skipped`.
- Isolated direct lifecycle/eval gates passed under a temp `ENGRAM_DATA_DIR`:
  `server.py --self-test` and `server.py --agent-eval`; the agent eval summary
  passed all 3 retrieval scenarios, both workflow checks, and the Book
  Dismantling Gate with 7/7 required fixtures.
- `git diff --check` passed.
- Working tree was clean before writing this fallback memory.

Operational handoff:

- Restart the live app/daemon before relying on Memory OS-backed MCP writes.
  The active daemon smoke showed backend `null`, proving the running daemon has
  not picked up `2a77efa8`.
- After restart, run `python engramd.py --doctor` and
  `python engramd.py --smoke-test`; the smoke store/search details should report
  `memory_os`.
- If duplicate daemon processes remain, keep one daemon owner only after
  confirming the PID that owns the active `ENGRAM_DAEMON_URL`.
- Import this fallback memory into Engram once the rebuilt Memory OS write path
  is live.
