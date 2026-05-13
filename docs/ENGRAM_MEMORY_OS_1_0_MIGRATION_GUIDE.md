# Engram Memory OS 1.0 Migration Guide

This guide moves legacy Engram JSON/Chroma data into the rebuilt local Memory
OS without deleting the legacy store. It is for local 1.0 only; hosted sync,
tenant auth, billing, and collaboration are post-1.0 work.

## Safety Rules

- Legacy `data/memories/` JSON remains recoverable until import, export,
  restore, retrieval, graph, and daemon smoke gates pass.
- ChromaDB is a legacy rebuildable index, not the migration source of truth.
- Do not delete `data/memories/`, `data/chroma/`, or graph files as part of
  migration.
- Use `engramd` as the single owner for rebuilt Memory OS stores.
- Do not commit local memory data, PDF source files, extracted copyrighted book
  text, OCR output, page images, or table exports.

## Preflight

Run from the repo root:

```powershell
git status --short --branch
.\venv\Scripts\python.exe engramd.py --doctor
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_legacy_import.py tests\test_memory_os_migration.py -q
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_retrieval.py tests\memory_os\test_graph.py -q
```

Expected:

- No unrelated changes are mixed into the migration work.
- The doctor report either shows a healthy daemon or clear operator action.
- Legacy import, bundle parity, retrieval, and graph tests pass.

## Dry Run Legacy JSON

No-write validation through the MCP tool:

```text
migration_dry_run(legacy_dir="data/memories")
```

CLI equivalent:

```powershell
.\venv\Scripts\python.exe -m core.memory_os_migration import-legacy --legacy-dir data\memories --store-root .engram\migration-dry-run --dry-run --report .engram\migration-dry-run-report.json
```

Expected:

- `invalid_count` is `0`, or every invalid record has an understood fix.
- `write_performed` is false for the MCP dry run.
- Chunk-count mismatches are reviewed before promotion.

## Round Trip Check

Run import, export, restore parity in a disposable work directory:

```powershell
.\venv\Scripts\python.exe -m core.memory_os_migration round-trip --legacy-dir data\memories --work-root .engram\migration-round-trip-check --report .engram\migration-round-trip-report.json
```

Expected:

- Report status is `pass`.
- Imported count, bundle memory count, and restored count match.
- Restore does not require the old Chroma directory.

## Import Into Memory OS Store

After dry-run and round-trip gates pass:

```powershell
.\venv\Scripts\python.exe -m core.memory_os_migration import-legacy --legacy-dir data\memories --store-root data\memory_os --report data\memory_os\legacy-import-report.json
```

If legacy graph edges exist:

```powershell
.\venv\Scripts\python.exe -m core.memory_os_migration import-graph-edges --store-root data\memory_os --graph-path data\graph\edges.json --report data\memory_os\legacy-graph-import-report.json
```

Expected:

- JSON memories import into the SQLite ledger.
- Content bodies are represented through content-addressed artifact refs.
- Graph edges preserve stable edge fields and evidence refs.

## Rebuild Runtime Indexes

Start or restart the daemon after import:

```powershell
.\venv\Scripts\python.exe engramd.py --doctor
.\venv\Scripts\python.exe engramd.py --smoke-test
```

Expected:

- The daemon initializes `data/memory_os/ledger.sqlite3`, `objects/`, `lance/`,
  and `kuzu/`.
- Smoke output reports `storage_backend: memory_os` for the store step and
  `backend: memory_os` for the search step.
- The temporary smoke memory is deleted at the end.

## Export A Portable Memory Passport

Create a portable bundle before destructive maintenance or machine moves:

```powershell
.\venv\Scripts\python.exe -m core.memory_os_migration export-bundle --store-root data\memory_os --bundle .engram\memory-passport.json
```

Restore proof into a disposable directory:

```powershell
.\venv\Scripts\python.exe -m core.memory_os_migration restore-bundle --store-root .engram\memory-passport-restore --bundle .engram\memory-passport.json --report .engram\memory-passport-restore-report.json
```

Expected:

- The bundle preserves memory keys, metadata, chunk refs, graph edges, and
  document-evidence records.
- Restore works without the legacy Chroma directory.

## Rollback

Rollback is intentionally boring:

- Stop the daemon.
- Point MCP registration back at legacy direct mode or a prior daemon data dir.
- Keep `data/memories/` and `data/chroma/` intact until the rebuilt runtime has
  passed release gates across real sessions.

Do not delete Memory OS artifacts during rollback unless a separate backup has
been verified.
