# Engram 1.0 Memory OS and Document Disassembly Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Engram 1.0 as a local-first, daemon-backed, agent-facing memory OS that can dismantle large rich documents into reviewable evidence, chunks, graph proposals, and explicit promotion transactions.

**Architecture:** Keep active memory writes explicit and JSON-first while moving live mutable operations behind `engramd`. Add a document disassembly lane that stores content-addressed source/page/artifact evidence, produces quality reports, and lets the connected agent synthesize memories and graph edges without automatic promotion.

**Tech Stack:** Python 3.10+, FastMCP, Flask, pytest, local JSON/SQLite-style migration artifacts, Poppler-compatible local PDF tooling where available, optional OCR/vision adapters, Chroma legacy retrieval, optional LanceDB/Kuzu probes. Manual large-document smoke runs may point at `C:\Users\colek\Downloads\Design Books`; committed tests must use deterministic fixtures or manifests.

---

## File Responsibilities

- `plan.md`: current routing document for agents.
- `docs/superpowers/specs/2026-05-12-engram-1-0-memory-os-document-disassembly-design.md`: binding 1.0 design and Book Dismantling Gate.
- `docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md`: durable product architecture; keep aligned with this plan.
- `core/codebase_mapper.py`: agent-native codebase mapping jobs and source drift protection.
- `core/document_intelligence.py`: provider-neutral document, page, visual, table, quality, draft, and promotion primitives.
- `core/document_disassembly.py`: new local document disassembly planner and evidence manifest builder.
- `core/document_extractors.py`: new local extractor adapters for PDF/text/HTML/DOCX discovery and no-write extraction receipts.
- `core/document_quality.py`: new quality report scoring and warnings for book-scale imports.
- `core/memory_os_migration.py`: migration ledger and artifact round-trip support for document evidence.
- `core/engramd_api.py`, `core/engramd_client.py`, `server.py`: daemon and MCP routes for document jobs, mapping jobs, and status.
- `tests/test_document_disassembly.py`: new document disassembly fixtures and Book Dismantling Gate unit coverage.
- `tests/test_document_quality.py`: quality scoring and warning coverage.
- `tests/test_codebase_mapper.py`: Memory OS mapping config and data-root coverage.
- `tests/test_engramd_api.py`, `tests/test_server_daemon_client.py`: daemon route coverage.
- `README.md`, `AGENTS.md`, `docs/ENGRAM_1_0_RELEASE_CHECKLIST.md`: release/user/operator docs.

## Task 1: Refresh The Live 1.0 Plan

**Files:**
- Modify: `plan.md`
- Modify: `docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md`
- Create: `docs/superpowers/specs/2026-05-12-engram-1-0-memory-os-document-disassembly-design.md`
- Create: `docs/superpowers/plans/2026-05-12-engram-1-0-memory-os-document-disassembly-plan.md`

- [x] **Step 1: Add the binding spec.**

Create the design document with consolidated tracks, Book Dismantling Gate,
steelman review, and addendums.

- [x] **Step 2: Add this implementation plan.**

Create this file with ordered, verifiable slices.

- [x] **Step 3: Route `plan.md` to this plan.**

Update the Engram 1.0 section so future agents treat this plan as current.

- [x] **Step 4: Align the rebuild spec.**

Add a short "Book Dismantling Gate" pointer under Document Intelligence Intake.

- [x] **Step 5: Validate documentation.**

Run:

```powershell
$terms = @("TO" + "DO", "TB" + "D", "fill" + " in", "implement" + " later")
Select-String -Path docs/superpowers/specs/2026-05-12-engram-1-0-memory-os-document-disassembly-design.md,docs/superpowers/plans/2026-05-12-engram-1-0-memory-os-document-disassembly-plan.md -Pattern ($terms -join "|")
git diff --check
```

Expected: `Select-String` returns no matches; `git diff --check` exits 0.

- [x] **Step 6: Commit.**

```powershell
git add plan.md docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md docs/ENGRAM_1_0_IMPLEMENTATION_PLAN.md
git add -f docs/superpowers/specs/2026-05-12-engram-1-0-memory-os-document-disassembly-design.md docs/superpowers/plans/2026-05-12-engram-1-0-memory-os-document-disassembly-plan.md
git commit -m "docs: define Memory OS 1.0 document disassembly plan"
```

## Task 2: Modernize Codebase Mapping For Memory OS

**Files:**
- Modify: `core/codebase_mapper.py`
- Modify: `tests/test_codebase_mapper.py`
- Modify: `README.md`
- Regenerate local ignored operator file after merge: `.engram/config.json`

- [x] **Step 1: Write failing tests for data-root jobs.**

Add a test that sets `ENGRAM_DATA_DIR` before importing or constructing the
mapping manager and expects prepared jobs to be written under that data root,
not `C:\Dev\Engram\data`.

- [x] **Step 2: Verify red.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_codebase_mapper.py -q
```

Expected: the new data-root test fails because `CODEBASE_MAPPING_DIR` is still
project-root based.

- [x] **Step 3: Implement data-root mapping job storage.**

Move mapping job path resolution behind a function that honors
`ENGRAM_DATA_DIR` and defaults to `PROJECT_ROOT / "data"`.

- [x] **Step 4: Update config domains.**

Update the Engram draft mapping template and regenerate local `.engram/config.json`
with domains for `daemon_runtime`,
`document_intelligence`, `memory_os_migration`, `backend_status`,
`graph`, `webui`, `reliability`, and `codebase_mapping`. Raise
`max_file_size_kb` high enough to include `server.py` and `memory_manager.py`.

- [x] **Step 5: Verify green and preview.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_codebase_mapper.py -q
.\venv\Scripts\python.exe -m pytest tests/test_server_structured_tools.py::test_memory_protocol_advertises_agent_native_codebase_mapping -q
```

Then call `preview_codebase_mapping(project_root="C:\\Dev\\Engram")` and confirm
the new domains include daemon and document intelligence files.

- [x] **Step 6: Commit.**

```powershell
git add core/codebase_mapper.py tests/test_codebase_mapper.py README.md docs/superpowers/plans/2026-05-12-engram-1-0-memory-os-document-disassembly-plan.md
git commit -m "feat: modernize codebase mapping for Memory OS"
```

## Task 3: Add Local PDF Inventory And Text Extraction

**Files:**
- Create: `core/document_extractors.py`
- Modify: `core/document_intelligence.py`
- Modify: `core/source_connectors.py`
- Modify: `server.py`
- Test: `tests/test_document_disassembly.py`
- Test: `tests/test_document_source_connectors.py`
- Test: `tests/test_agent_protocol_tools.py`
- Test: `tests/test_server_structured_tools.py`
- Modify: `docs/ENGRAM_1_0_MCP_CONTRACT.md`
- Modify: `AGENTS.md`
- Modify: `README.md`

- [x] **Step 1: Write failing tests for PDF inventory.**

Create tests using a tiny fixture PDF or a synthetic extractor fixture that
expects page count, file hash, media type, text coverage, and image count
fields in a no-write extraction result.

- [x] **Step 2: Verify red.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_document_disassembly.py -q
```

Expected: tests fail because `core.document_extractors` does not exist.

- [x] **Step 3: Implement local extractor capability detection.**

Add adapter discovery for Poppler CLI tools already present on Windows:
`pdfinfo`, `pdftotext`, and `pdfimages`. If unavailable, return a structured
capability warning rather than raising.

- [x] **Step 4: Implement no-write PDF inventory.**

Expose a function that returns `source`, `document`, `pages`, `receipts`, and
`quality_seed` without writing active memory.

- [x] **Step 5: Add MCP helper.**

Add `prepare_document_disassembly` or equivalent MCP route with docstrings that
state it is no-write and review-first.

- [x] **Step 6: Verify.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_document_disassembly.py tests/test_document_intelligence.py tests/test_server_structured_tools.py -q
```

- [x] **Step 7: Commit.**

```powershell
git add core/document_extractors.py core/document_intelligence.py server.py tests/test_document_disassembly.py tests/test_server_structured_tools.py README.md
git commit -m "feat: add no-write PDF disassembly inventory"
```

## Task 4: Add Document Quality Reports

**Files:**
- Create: `core/document_quality.py`
- Modify: `core/document_extractors.py`
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `docs/ENGRAM_1_0_MCP_CONTRACT.md`
- Modify: `docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md`
- Test: `tests/test_document_quality.py`
- Test: `tests/test_document_disassembly.py`

- [x] **Step 1: Write failing tests for quality warnings.**

Cover empty pages, low text coverage, image-heavy pages, missing OCR,
table-candidate pages, duplicate chunks, failed pages, and unsupported
extractor capabilities.

- [x] **Step 2: Verify red.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_document_quality.py -q
```

- [x] **Step 3: Implement quality scoring.**

Return a deterministic quality report with page counts, coverage percentages,
warning codes, and recommended next tools.

- [x] **Step 4: Verify.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_document_quality.py tests/test_document_disassembly.py -q
```

- [x] **Step 5: Commit.**

```powershell
git add core/document_quality.py core/document_extractors.py tests/test_document_quality.py tests/test_document_disassembly.py AGENTS.md README.md docs/ENGRAM_1_0_MCP_CONTRACT.md docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md docs/superpowers/plans/2026-05-12-engram-1-0-memory-os-document-disassembly-plan.md
git commit -m "feat: add document import quality reports"
```

## Task 5: Add Artifact Manifest And Resumable Jobs

**Files:**
- Create: `core/document_artifacts.py`
- Modify: `core/document_extractors.py`
- Modify: `core/operation_log.py`
- Test: `tests/test_document_artifacts.py`

- [ ] **Step 1: Write failing tests for content-addressed artifact paths.**

Assert raw source, page text, rendered page, image, table, and manifest refs are
deduplicated by hash and safe under `ENGRAM_DATA_DIR`.

- [ ] **Step 2: Verify red.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_document_artifacts.py -q
```

- [ ] **Step 3: Implement artifact path builder.**

Use content hashes and relative refs, not absolute machine-local paths, in
portable manifests.

- [ ] **Step 4: Implement resume manifest.**

Record per-page state: `pending`, `text_extracted`, `visual_needed`,
`visual_complete`, `failed`, or `skipped`.

- [ ] **Step 5: Verify.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_document_artifacts.py tests/test_document_disassembly.py -q
```

- [ ] **Step 6: Commit.**

```powershell
git add core/document_artifacts.py core/document_extractors.py core/operation_log.py tests/test_document_artifacts.py
git commit -m "feat: add resumable document artifact manifests"
```

## Task 6: Add Visual And Table Evidence Flow

**Files:**
- Modify: `core/document_intelligence.py`
- Modify: `core/document_extractors.py`
- Test: `tests/test_document_intelligence.py`
- Test: `tests/test_document_disassembly.py`

- [ ] **Step 1: Write failing tests for visual/table artifacts.**

Assert figure, table, caption, OCR block, page crop, and diagram refs retain
page number, coordinates when available, extractor id, confidence, and source
artifact id.

- [ ] **Step 2: Verify red.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_document_intelligence.py tests/test_document_disassembly.py -q
```

- [ ] **Step 3: Implement visual/table candidate records.**

Return candidate records from local inventory and route low/no-text pages into
`prepare_visual_extraction_request`.

- [ ] **Step 4: Verify.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_document_intelligence.py tests/test_document_disassembly.py -q
```

- [ ] **Step 5: Commit.**

```powershell
git add core/document_intelligence.py core/document_extractors.py tests/test_document_intelligence.py tests/test_document_disassembly.py
git commit -m "feat: preserve visual and table evidence"
```

## Task 7: Add Document Understanding Packets And Graph Proposals

**Files:**
- Modify: `core/document_intelligence.py`
- Modify: `core/graph_manager.py`
- Test: `tests/test_document_intelligence.py`
- Test: `tests/test_memory_os_migration.py`

- [ ] **Step 1: Write failing tests for document understanding packets.**

Assert packets include summary slots, claim candidates, concept candidates,
entity candidates, high-value sections, low-confidence warnings, and candidate
graph edges.

- [ ] **Step 2: Verify red.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_document_intelligence.py -q
```

- [ ] **Step 3: Implement packet normalization.**

Keep synthesis provider-neutral: the connected agent supplies analysis, Engram
normalizes it into evidence, draft memories, and graph proposals.

- [ ] **Step 4: Verify.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_document_intelligence.py tests/test_memory_os_migration.py -q
```

- [ ] **Step 5: Commit.**

```powershell
git add core/document_intelligence.py core/graph_manager.py tests/test_document_intelligence.py tests/test_memory_os_migration.py
git commit -m "feat: add document understanding graph proposals"
```

## Task 8: Add Book Dismantling Gate

**Files:**
- Create: `tests/fixtures/document_books/README.md`
- Modify: `tests/test_document_disassembly.py`
- Modify: `core/reliability_harness.py`
- Modify: `docs/ENGRAM_1_0_RELEASE_CHECKLIST.md`

- [ ] **Step 1: Write fixture manifest tests.**

Add synthetic or local-only fixture manifests for clean text PDF, book-style
PDF, image-only PDF, table-heavy page, figure/caption page, rotated page, and
OCR-noise page. Do not commit copyrighted PDFs.

- [ ] **Step 2: Verify red.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_document_disassembly.py -q
```

- [ ] **Step 3: Implement gate runner.**

Add a deterministic test helper that validates page inventory, text coverage,
visual-needed flags, quality warnings, chunk provenance, and promotion drafts.

- [ ] **Step 4: Add optional local large-book smoke.**

Document an environment-variable gated smoke for local PDFs such as the 79 MB
book. The smoke must not require the file in CI and must not commit extracted
copyrighted text. The default local corpus directory for Cole's machine is
`C:\Users\colek\Downloads\Design Books`; test code must treat it as optional
and skip cleanly when `ENGRAM_DOCUMENT_FIXTURE_DIR` is unset or unavailable.

- [ ] **Step 5: Verify.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_document_disassembly.py -q
.\venv\Scripts\python.exe server.py --agent-eval
```

- [ ] **Step 6: Commit.**

```powershell
git add tests/fixtures/document_books/README.md tests/test_document_disassembly.py core/reliability_harness.py docs/ENGRAM_1_0_RELEASE_CHECKLIST.md
git commit -m "test: add book dismantling release gate"
```

## Task 9: Route Document Jobs Through Engramd

**Files:**
- Modify: `core/engramd_api.py`
- Modify: `core/engramd_client.py`
- Modify: `server.py`
- Test: `tests/test_engramd_api.py`
- Test: `tests/test_server_daemon_client.py`
- Test: `tests/test_server_daemon_status.py`

- [ ] **Step 1: Write failing daemon route tests.**

Add tests for document disassembly prepare/status/read-manifest routes in
daemon mode.

- [ ] **Step 2: Verify red.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_engramd_api.py tests/test_server_daemon_client.py tests/test_server_daemon_status.py -q
```

- [ ] **Step 3: Implement daemon routes.**

Route document jobs through `engramd` when `ENGRAM_DAEMON_URL` is set.

- [ ] **Step 4: Verify.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_engramd_api.py tests/test_server_daemon_client.py tests/test_server_daemon_status.py tests/test_document_disassembly.py -q
```

- [ ] **Step 5: Commit.**

```powershell
git add core/engramd_api.py core/engramd_client.py server.py tests/test_engramd_api.py tests/test_server_daemon_client.py tests/test_server_daemon_status.py
git commit -m "feat: route document jobs through engramd"
```

## Task 10: Final 1.0 Release Gate

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `plan.md`
- Modify: `docs/ENGRAM_1_0_RELEASE_CHECKLIST.md`
- Modify: `docs/ENGRAM_1_0_MIGRATION_NOTES.md`

- [ ] **Step 1: Update public docs.**

Document local-first daemon mode, document disassembly, codebase mapping,
migration, and no-collaboration boundary.

- [ ] **Step 2: Run final commands.**

Run:

```powershell
.\venv\Scripts\python.exe server.py --help
.\venv\Scripts\python.exe -c "from core.memory_manager import memory_manager; print('ok')"
.\venv\Scripts\python.exe server.py --self-test
.\venv\Scripts\python.exe server.py --agent-eval
.\venv\Scripts\python.exe -m pytest -q
git diff --check
codex mcp get engram
```

- [ ] **Step 3: Optional large-book local smoke.**

Run the environment-gated local smoke against the 250-page design book and the
79 MB book if both files are available. The expected output is quality reports
and manifests, not committed extracted text.

- [ ] **Step 4: Commit release docs.**

```powershell
git add README.md AGENTS.md plan.md docs/ENGRAM_1_0_RELEASE_CHECKLIST.md docs/ENGRAM_1_0_MIGRATION_NOTES.md
git commit -m "docs: prepare Engram 1.0 release"
```

## Plan Self-Review

- Spec coverage: all consolidated tracks from the design have a task or gate.
- Placeholder scan: the plan intentionally contains no unresolved placeholder
  tokens or fill-in requirements.
- Type consistency: the plan uses existing terms where possible:
  source, document, page, section, chunk, visual artifact, table artifact,
  quality report, draft, graph edge, promotion transaction, and receipt.
- Scope control: hosted collaboration remains outside Engram 1.0. Extractors
  are adapters; Engram owns evidence, provenance, quality, review, retrieval,
  and promotion.
