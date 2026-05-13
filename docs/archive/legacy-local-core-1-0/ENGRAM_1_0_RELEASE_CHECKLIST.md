# Engram 1.0 Release Checklist

Date: 2026-05-12
Status: Engram 1.0 local core release checklist
Scope: Public Engram core release gates; hosted, tenant, and collaboration product gates are post-1.0

## Operator Rules

- Run commands from the repository root.
- Use the project virtual environment.
- Treat JSON files in `data/memories/` as authoritative.
- Treat ChromaDB in `data/chroma/` as rebuildable.
- Run import tests on a disposable copy unless intentionally overwriting matching memory keys.

PowerShell setup:

```powershell
$py = ".\venv\Scripts\python.exe"
```

## Core Health Gate

```powershell
& $py server.py --help
& $py -c "from core.memory_manager import memory_manager; print('ok')"
& $py server.py --self-test
& $py server.py --agent-eval
& $py -m pytest -q
git diff --check
```

Expected result: help output names `Engram 1.0.0`, `memory_protocol()`
reports product stability `stable`, self-test proves the store/search/read/delete
cycle, and agent eval includes the deterministic Book Dismantling Gate.

When MCP registration or installer behavior changed:

```powershell
codex mcp get engram
```

## Storage, Rebuild, and Repair Gate

Focused tests:

```powershell
& $py -m pytest tests/test_storage_invariants.py tests/test_write_helpers.py tests/test_graph_manager.py -q
```

Rebuild ChromaDB from JSON:

```powershell
& $py server.py --rebuild-index
```

Expected result: the command reports the count rebuilt from JSON. Search should
work again because ChromaDB is an index, not the source of truth.

Export all memories:

```powershell
& $py server.py --export
```

Expected result: `engram_export_YYYY-MM-DD.json` is created in the current
directory. The export contains full JSON memory records, including lifecycle and
scoping metadata.

Import a bundle:

```powershell
& $py server.py --import-file .\engram_export_YYYY-MM-DD.json
```

Expected result: matching keys are overwritten intentionally, JSON records are
written before Chroma indexing, and required metadata is preserved from the
bundle.

Audit metadata without writes:

```powershell
@'
from core.memory_manager import memory_manager
import json
print(json.dumps(memory_manager.audit_memory_metadata(limit=100), indent=2))
'@ | & $py -
```

Dry-run repair:

```powershell
@'
from core.memory_manager import memory_manager
import json
keys = ["example_memory_key"]
print(json.dumps(memory_manager.repair_memory_metadata(keys, dry_run=True), indent=2))
'@ | & $py -
```

Apply repair after reviewing the dry-run:

```powershell
@'
from core.memory_manager import memory_manager
import json
keys = ["example_memory_key"]
print(json.dumps(memory_manager.repair_memory_metadata(keys, dry_run=False), indent=2))
'@ | & $py -
```

Expected result: each changed memory gets a pre-write backup under
`data/backups/metadata_repair/` before normalized JSON is saved and chunks are
reindexed.

Graph audit:

```powershell
@'
from core.graph_manager import graph_manager
import json
print(json.dumps(graph_manager.audit_graph(), indent=2))
'@ | & $py -
```

Expected result: malformed edge records are reported by edge index and field
without loading memory bodies.

## Document Intelligence Gate

Run the deterministic Book Dismantling Gate:

```powershell
& $py -m pytest tests/test_document_disassembly.py tests/test_reliability_harness.py -q
& $py server.py --agent-eval
```

Expected result: the synthetic fixture manifests cover `clean_text_pdf`,
`book_style_pdf`, `image_only_pdf`, `table_heavy_page`,
`figure_caption_page`, `rotated_page`, and `ocr_noise_page`. The gate must
report page inventory, text coverage, visual-needed pages, quality warnings,
chunk provenance, and reviewable draft proposals without active memory writes.

Optional local large-book smoke:

```powershell
$env:ENGRAM_DOCUMENT_FIXTURE_DIR = "C:\Users\colek\Downloads\Design Books"
& $py -m pytest tests/test_document_disassembly.py::test_optional_local_design_book_smoke_is_env_gated -q
Remove-Item Env:\ENGRAM_DOCUMENT_FIXTURE_DIR
```

Expected result: the smoke skips cleanly when the directory, PDFs, or local PDF
tools are unavailable. When available, it runs `prepare_document_disassembly`
against the first local PDF with `max_pages=5`, returns no active writes, and
does not commit source PDFs or extracted copyrighted text.

Manual release smoke may also target a known large PDF in the same directory
with `max_pages` set low enough to prove page inventory and quality reporting
without exporting copyrighted content. Record only counts, warning names,
artifact record types, and whether visual candidates were produced.

## Final Release Gate

Before tagging or announcing a 1.0 build, run:

```powershell
& $py server.py --help
& $py -c "from core.memory_manager import memory_manager; print('ok')"
& $py server.py --self-test
& $py server.py --agent-eval
& $py -m pytest -q
git diff --check
```

Then verify docs do not present the separate collaboration product as part of
Engram core.

Latest local validation, 2026-05-12:

- `server.py --help`: reports `Engram 1.0.0`.
- Memory manager import: reports `ok`.
- `server.py --self-test`: passed store/search/chunk/context/delete, graph,
  source drafts, usage meter, operation log, and protocol checks.
- `server.py --agent-eval`: passed 3 scenarios and 2 workflow checks,
  including the Book Dismantling Gate with 7 required fixture manifests passed
  and 0 failed.
- `pytest -q`: 402 passed, 2 skipped.
- Manual local PDF smoke, not reproducible from committed fixtures, with
  `max_pages=5`: two local design-book PDFs, including one large 76.92 MB file,
  returned no active writes, page inventory, warning codes, visual candidates,
  artifact manifests, and `pdfinfo`/`pdftotext`/`pdfimages` receipts. Treat
  this as machine-local operator evidence; the committed reproducible gate is
  the synthetic Book Dismantling Gate.

1.0 does not require hosted tenant auth, billing, live LanceDB/Kuzu switching,
team workspaces, rich pages, comments, assignments, mentions, or role-aware
visibility. Those remain post-1.0 or separate collaboration-product work.
