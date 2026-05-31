# Engram Agent Guide

This file describes how automated agents should work in this repository.

## Core Rules

- Build and debug the project through the real runtime path whenever possible.
- Prefer evidence-led debugging over speculative patches.
- Keep changes small, focused, and easy to validate.
- Do not commit local runtime data, memory stores, sync bundles, model caches,
  credentials, private document artifacts, or machine-specific paths.

## Debugging Process

1. Lock the symptom.
2. Inspect live runtime state.
3. Prove the failing gate.
4. Change one thing.
5. Re-verify the same gate.

Useful daemon checks:

```powershell
.\venv\Scripts\python.exe engramd.py --preflight
.\venv\Scripts\python.exe engramd.py --doctor
.\venv\Scripts\python.exe engramd.py --smoke-test
```

## Architecture Boundaries

- `engramd.py` owns the daemon process.
- `server_daemon_client.py` is the normal thin MCP entrypoint for multi-session
  agent use.
- `server.py` exposes the full local MCP surface and direct-mode validation.
- `core/memory_os/` owns the daemon-backed Memory OS runtime.
- `core/memory_manager.py` is legacy JSON/Chroma compatibility and recovery
  logic.
- Document and source workflows are review-first. Preview and prepare helpers
  must not promote active memory unless an explicit accepted write tool is used.
- The Web Inspector is a local review surface. Keep exposed-host auth checks
  fail-closed.

## Retrieval Pattern

Agents should use the smallest useful context:

```text
search_memories(query, limit=5)
retrieve_chunk(key, chunk_id)
retrieve_memory(key)
```

Use full-memory retrieval only when chunk-level evidence is insufficient.

## Completion Checks

Before marking a code change complete, run the checks relevant to the files you
touched. For broad runtime changes, use:

```powershell
.\venv\Scripts\python.exe server.py --help
.\venv\Scripts\python.exe -c "from core.memory_manager import memory_manager; print('ok')"
.\venv\Scripts\python.exe engramd.py --preflight
.\venv\Scripts\python.exe engramd.py --doctor
.\venv\Scripts\python.exe engramd.py --smoke-test
```

For isolated direct-mode validation:

```powershell
$env:ENGRAM_DATA_DIR = Join-Path $env:TEMP "engram-self-test"
.\venv\Scripts\python.exe server.py --self-test
.\venv\Scripts\python.exe server.py --agent-eval
Remove-Item Env:\ENGRAM_DATA_DIR
```

## Public Repository Hygiene

The repository should contain source code, tests, synthetic fixtures, and public
documentation. It should not contain personal memories, private handoffs,
business plans, local paths, runtime stores, sync payloads, SQLite ledgers,
vector indexes, graph stores, Chroma data, PDFs, OCR output, exported bundles,
or credentials.

For desktop/laptop sync behavior, see `docs/SYNC_DESKTOP_LAPTOP.md`.
