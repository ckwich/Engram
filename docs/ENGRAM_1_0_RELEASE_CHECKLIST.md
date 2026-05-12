# Engram 1.0 Release Checklist

Date: 2026-05-06
Status: Active release checklist
Scope: Public Engram core release gates

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
