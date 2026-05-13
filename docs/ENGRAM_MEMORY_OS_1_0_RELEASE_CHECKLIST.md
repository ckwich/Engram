# Engram Memory OS 1.0 Release Checklist

Use this checklist before calling a branch or build "Engram 1.0 ready." It is
for the local-first Memory OS rebuild, not the archived legacy local-core 1.0
target.

## Scope Boundary

- Engram core is local-first and agent-facing.
- Local 1.0 includes SQLite ledger, content-addressed source artifacts,
  LanceDB retrieval, Kuzu graph storage, daemon ownership, evidence-first
  document intelligence, retrieval receipts, graph relationships,
  transactions, snapshots, firewall, skill-pack export, portable memory
  passport, and local Memory Inspector.
- Post-1.0 only: hosted sync, tenant auth, billing, hosted MCP/API gateway,
  hosted collaboration bridge, marketplace, support operations, team
  workspaces, comments, assignments, mentions, and role-aware visibility.

## Clean Working Tree

```powershell
git status --short --branch
git diff --check
```

Expected:

- Branch is the intended release branch.
- No unrelated local changes are mixed into the release commit.
- `git diff --check` reports no whitespace errors.

## Required Runtime Gates

Run these from the repo root:

```powershell
.\venv\Scripts\python.exe server.py --help
.\venv\Scripts\python.exe -c "from core.memory_manager import memory_manager; print('ok')"
.\venv\Scripts\python.exe engramd.py --doctor
.\venv\Scripts\python.exe engramd.py --smoke-test
.\venv\Scripts\python.exe -m pytest -q
```

For a disposable daemon subprocess smoke:

```powershell
$env:ENGRAM_LIVE_DAEMON_SMOKE = "1"
.\venv\Scripts\python.exe -m pytest tests\test_engramd_smoke.py::test_live_engramd_subprocess_smoke -q
Remove-Item Env:\ENGRAM_LIVE_DAEMON_SMOKE
```

If a live daemon owns the default data root, run direct `server.py` lifecycle
gates against an isolated data directory:

```powershell
$env:ENGRAM_DATA_DIR = "$PWD\.release-check-data"
.\venv\Scripts\python.exe server.py --self-test
.\venv\Scripts\python.exe server.py --agent-eval
Remove-Item Env:\ENGRAM_DATA_DIR
```

Expected:

- `server.py --help` reports Engram `1.0.0`.
- Memory manager import prints `ok`.
- `engramd.py --doctor` reports daemon health or a clear daemon-not-running
  operator action.
- `engramd.py --smoke-test` writes, searches, reads, updates, repairs, and
  deletes a temporary memory through the daemon, and reports `memory_os` as
  the storage/search backend when the rebuilt runtime owns the route.
- `server.py --agent-eval` passes the retrieval and Book Dismantling Gate
  checks.
- Full pytest passes.

## MCP Registration Gate

When the Codex CLI is available:

```powershell
codex mcp get engram
```

Expected:

- Engram is registered.
- For multi-session work, registration should prefer `server_daemon_client.py`
  with `ENGRAM_DAEMON_URL=http://127.0.0.1:8765` and `ENGRAM_DATA_DIR` pinned
  to this checkout.
- This command proves registration only. A fresh session still needs a callable
  tool check such as `memory_protocol()` or `daemon_status()`.

## Memory OS-Specific Gates

Legacy JSON import parity:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_legacy_import.py tests\test_memory_os_migration.py -q
```

SQLite export/restore and memory passport:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_bundles.py -q
```

LanceDB rebuild/search parity:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_retrieval.py tests\test_lancedb_vector_index.py -q
```

Kuzu graph import/path parity:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_graph.py tests\test_kuzu_graph_store.py -q
```

Document intelligence and Book Dismantling Gate:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_document_pipeline.py tests\test_document_disassembly.py tests\test_document_intelligence.py tests\test_document_quality.py tests\test_document_artifacts.py -q
.\venv\Scripts\python.exe server.py --agent-eval
```

Firewall quarantine fixture:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_firewall.py -q
```

Transaction rollback fixture:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_transactions.py -q
```

Local Memory Inspector:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_inspector.py tests\test_webui_inspector.py tests\test_webui_auth.py tests\test_security_defaults.py -q
```

Expected:

- All gates pass.
- Inspector routes remain read-only.
- Exposed WebUI remains fail-closed.
- No document fixture commits copyrighted book text, rendered page images, OCR
  output, or table exports.

## Manual Book-Scale Smoke

Optional local-only smoke for rich PDFs:

```powershell
.\venv\Scripts\python.exe server.py --agent-eval
```

Use local PDFs under `C:\Users\colek\Downloads\Design Books` only for manual
operator checks. Do not commit source PDFs, extracted copyrighted text, OCR
output, screenshots, page images, or table exports. Record only counts,
coverage-map fields, warning names, and validation status.

## Release Decision

The release is ready when:

- All required gates pass or have an explicit operator-only exception with
  evidence.
- The branch is clean.
- README, AGENTS, `plan.md`, rebuild spec, release checklist, and migration
  guide all describe the same local 1.0 target.
- Engram memory closeout is written through MCP or the daemon API. If both are
  unavailable, write an import-ready markdown fallback under `docs/`.
