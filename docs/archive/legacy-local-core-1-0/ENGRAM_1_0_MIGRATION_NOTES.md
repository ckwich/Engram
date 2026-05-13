# Engram 1.0 Migration Notes

Date: 2026-05-12
Status: Engram 1.0 local core migration guide

## Summary

Engram 1.0 does not require a destructive data migration for existing local
users. Existing JSON memories remain the source of truth, ChromaDB remains a
rebuildable semantic index, and graph edges remain JSON records behind the
`GraphStore` contract.

The Memory OS migration tools added for 1.0 are proof and preparation tools:
they validate legacy JSON memories, import them into a disposable migration
ledger, export/restore a bundle, and compare parity without touching active
memory JSON or the live ChromaDB index.

## What Changes

- Product identity is now `Engram 1.0.0` with product stability `stable`.
- MCP protocol identity remains `version: 2` and
  `schema_version: "2026-04-27"`.
- `memory_protocol()` is the agent discovery entry point for the current
  retrieval, source, document, graph, daemon, and migration surfaces.
- `ENGRAM_DATA_DIR` can redirect the local data root for disposable tests,
  alternate stores, daemon smoke tests, and codebase mapping job output.
- `engramd.py` provides an opt-in loopback daemon. MCP stdio servers use it
  only when `ENGRAM_DAEMON_URL` is set.
- Document intelligence is review-first: disassembly, artifact manifests,
  visual/OCR requests, understanding packets, drafts, graph proposals, and
  promotion transactions do not become active memory unless an agent explicitly
  promotes reviewed content.

## What Does Not Change

- Memory writes remain JSON-first and Chroma-second.
- Chunk IDs remain stable `{md5(key)}_{chunk_index}` references.
- `retrieve_memory()` remains the expensive third tier after search and chunk
  retrieval.
- Source intake drafts still require explicit promotion with
  `store_prepared_memory()`.
- ChromaDB is still the live vector index for 1.0.
- JSON graph storage is still the live graph backend for 1.0.
- The WebUI remains a local dashboard, not a team collaboration app.

## Recommended Upgrade Check

From the repository root:

```powershell
$py = ".\venv\Scripts\python.exe"
& $py server.py --help
& $py -c "from core.memory_manager import memory_manager; print('ok')"
& $py server.py --self-test
& $py server.py --agent-eval
& $py -m pytest -q
```

If the ChromaDB index is missing, stale, or damaged, rebuild it from JSON:

```powershell
& $py server.py --rebuild-index
```

## Migration Dry Runs

Use these commands when you want proof that the current JSON corpus can move
through the Memory OS ledger shape without changing live memory:

```powershell
& $py -m core.memory_os_migration import-legacy --legacy-dir data/memories --store-root .engram-migration/store
& $py -m core.memory_os_migration import-graph-edges --store-root .engram-migration/store --graph-path data/graph/edges.json
& $py -m core.memory_os_migration export-bundle --store-root .engram-migration/store --bundle .engram-migration/bundle.json
& $py -m core.memory_os_migration restore-bundle --store-root .engram-migration/restored --bundle .engram-migration/bundle.json
& $py -m core.memory_os_migration round-trip --legacy-dir data/memories --work-root .engram-migration/round-trip
```

Agent-facing equivalents are available through MCP:

- `migration_dry_run`
- `memory_os_round_trip_check`
- `retrieval_backend_status`
- `graph_backend_status`

These checks may write disposable migration work artifacts under the requested
work directory. They must not rewrite active memories, promote drafts, mutate
ChromaDB, or switch live retrieval/graph backends.

## Daemon Mode

Direct in-process MCP mode remains the default. To use the local daemon:

```powershell
& $py engramd.py --host 127.0.0.1 --port 8765
$env:ENGRAM_DAEMON_URL = "http://127.0.0.1:8765"
& $py server.py
```

For cross-project Codex work, register the MCP server as a daemon client and
pin `ENGRAM_DATA_DIR` to the Engram checkout:

```powershell
codex mcp remove engram
codex mcp add engram `
  --env ENGRAM_DATA_DIR=C:\Dev\Engram\data `
  --env ENGRAM_DAEMON_URL=http://127.0.0.1:8765 `
  -- C:\Dev\Engram\venv\Scripts\python.exe C:\Dev\Engram\server.py
```

Lazy discovery of the tool namespace is still controlled by the client session,
but every discovered adapter should route stable memory operations through the
same daemon instead of trying to own embedded Chroma directly.

The daemon currently routes stable memory operations, source draft lifecycle
operations, metadata updates/repair/delete, and no-write document disassembly
preparation. Mapping jobs, import/export, rebuild jobs, backend switching, and
hosted tenant isolation are not daemon-owned 1.0 guarantees.

## Document Intelligence Migration Boundary

Document disassembly can create evidence records, quality reports, visual/OCR
requests, artifact manifests, understanding packets, draft memory proposals,
graph proposals, and promotion transactions. Those records are review surfaces,
not active memory.

For large or copyrighted documents, commit and share only safe evidence such as
hashes, counts, warning names, record types, and redacted snippets. Do not
commit source PDFs, extracted copyrighted text, rendered page images, OCR
output, or table exports.

## Collaboration Boundary

Engram 1.0 is the memory substrate. Team workspaces, authentication,
permissions, shared rich pages, comments, assignments, mentions, role-aware
visibility, product workflow UI, and billing belong to a separate collaboration
product or a future hosted Engram service with a new threat model.
