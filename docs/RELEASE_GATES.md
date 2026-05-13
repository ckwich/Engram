# Engram Release Gates

This file is the short, executable gate map for Engram maintenance work. Use it
before building EKC on top of the repo, and use the longer
`docs/ENGRAM_MEMORY_OS_1_0_RELEASE_CHECKLIST.md` before calling a branch
Engram 1.0 ready.

## Gate Levels

| Gate | Use When | Required Outcome |
|---|---|---|
| Pre-EKC Readiness Gate | Before implementing EKC or other agent-contract features | Architecture boundaries, thin daemon-client safety, no-write policy metadata, backend readiness wrappers, and runtime smoke checks pass. |
| Full 1.0 Release Gate | Before tagging or announcing Engram 1.0 | All Pre-EKC gates plus full pytest, isolated self-test, isolated agent-eval, daemon doctor/smoke, and release checklist evidence pass. |

## Pre-EKC Readiness Gate

Run these from the repo root:

```powershell
.\venv\Scripts\python.exe server.py --help
.\venv\Scripts\python.exe -c "from core.memory_manager import memory_manager; print('ok')"
.\venv\Scripts\python.exe engramd.py --doctor
.\venv\Scripts\python.exe engramd.py --smoke-test
.\venv\Scripts\python.exe -m pytest tests\architecture tests\test_server_daemon_client_entrypoint.py tests\policy tests\mcp\test_no_write_tool_contracts.py tests\backend_gates -q
git diff --check
```

Expected:

- `server_daemon_client.py` remains the recommended multi-session MCP entrypoint
  and does not import `server.py`, `core.memory_manager`, ChromaDB, LanceDB,
  Kuzu, sentence-transformers, or document extraction modules.
- Direct `server.py` mode remains available only for local debug,
  compatibility checks, and deliberate single-process development.
- No-write surfaces report explicit `write_policy`, `write_performed=False`,
  and `active_memory_write_performed=False`.
- `preview_memory_chunks`, `preview_source_connector`,
  `prepare_document_disassembly`, `preview_document_extraction`,
  `prepare_document_draft`, `prepare_document_promotion_transaction`,
  `prepare_visual_extraction_request`, and `preview_visual_extraction` remain
  review surfaces, not active memory promotion paths.
- Review-first promotion stays explicit: source/document evidence may become
  durable memory or graph edges only through a later reviewed promotion path.
- `build_retrieval_backend_gate` and `build_graph_backend_gate` wrap the
  existing backend status reports without changing the live backend.
- Backend gate decisions remain `not_ready` until real corpus parity,
  metadata filtering, Windows path/restart reliability, daemon ownership, and
  live-switch gates are proven.

## Full 1.0 Release Gate

Run the Pre-EKC gate, then run the full release checks:

```powershell
.\venv\Scripts\python.exe server.py --help
.\venv\Scripts\python.exe -c "from core.memory_manager import memory_manager; print('ok')"
.\venv\Scripts\python.exe engramd.py --doctor
.\venv\Scripts\python.exe engramd.py --smoke-test
$env:ENGRAM_DATA_DIR = Join-Path $env:TEMP ("engram-self-test-" + [guid]::NewGuid())
.\venv\Scripts\python.exe server.py --self-test
$env:ENGRAM_DATA_DIR = Join-Path $env:TEMP ("engram-agent-eval-" + [guid]::NewGuid())
.\venv\Scripts\python.exe server.py --agent-eval
Remove-Item Env:\ENGRAM_DATA_DIR
.\venv\Scripts\python.exe -m pytest -q
git diff --check
```

Expected:

- `server.py --self-test` proves direct store, search, retrieve, and delete in
  an isolated `ENGRAM_DATA_DIR`.
- `server.py --agent-eval` passes retrieval/source/document workflow checks and
  the Book Dismantling Gate.
- The full pytest suite passes.
- `docs/ENGRAM_MEMORY_OS_1_0_RELEASE_CHECKLIST.md`, README, AGENTS, `plan.md`,
  and the rebuild spec still describe the same local-first Memory OS target.

## Backend Promotion Rule

Backend readiness gates are reports, not switches. A retrieval or graph backend
cannot become default because an environment variable changed or because an
optional dependency imports. Default promotion requires passing wrapper reports
from `core.backend_gates` and an explicit implementation slice that changes the
live daemon-owned backend path.

Skipped parity is a blocker. A gate that has not run is not evidence.

