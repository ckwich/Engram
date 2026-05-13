# Engram Memory OS Rebuild 1.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild Engram 1.0 as a local-first, daemon-owned, agent-facing Memory OS with SQLite ledger, content-addressed source store, LanceDB retrieval, Kuzu graph storage, evidence-first document intelligence, cross-document graph reasoning, and portable export/restore.

**Architecture:** Keep the current JSON/Chroma runtime as the legacy import and rollback source while building the rebuilt runtime behind `engramd`. SQLite becomes the durable operational ledger, large evidence lives in a content-addressed store, LanceDB and Kuzu become daemon-owned live indexes, and MCP stdio servers become thin clients over reviewed, transactional workflows.

**Tech Stack:** Python 3.10+, FastMCP, SQLite stdlib, LanceDB, Kuzu, sentence-transformers, local content-addressed files, pytest, Flask inspector, Poppler-compatible PDF tools, optional provider-neutral OCR/vision adapters.

---

## Current Truth

- The active spec is `docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md`.
- Legacy local-core 1.0 docs are archived under `docs/archive/legacy-local-core-1-0/`.
- Task 0 canonical scope cleanup was completed in commit `f73a040f` (`docs: make Memory OS rebuild canonical`).
- The direct legacy compatibility path still uses JSON memories and Chroma for memory CRUD/search, and must remain recoverable during migration.
- The rebuilt runtime now exists under `core/memory_os/` and `engramd` owns SQLite, the content-addressed source store, LanceDB, Kuzu, jobs, transactions, snapshots, firewall state, stable memory operations, and read-only inspector records.
- `server_daemon_client.py` is the safe multi-session MCP entrypoint for stable memory operations; Memory OS runtime status/inspector surfaces are daemon-backed.
- This session's lazy-loaded Engram MCP surface exposed tools but `memory_protocol()` returned `Transport closed`; closeout memory must use the daemon API if healthy, or a markdown fallback if not.
- All durable writes must remain explicit and review-first.

## Overnight Hardening Addendum

This plan is being executed after a live repo scan on 2026-05-13. The repo
already contains rebuild-adjacent foundations that must be promoted or wrapped
rather than duplicated:

- `core/memory_os_migration.py` already implements the proven migration kernel,
  legacy JSON import/export/restore, graph-edge import, document-evidence
  round trips, and CLI parity reports.
- `core/vector_index.py` and `core/lancedb_vector_index.py` already define the
  vector adapter contract and LanceDB adapter.
- `core/graph_store.py` and `core/kuzu_graph_store.py` already define the JSON
  graph contract and Kuzu adapter.
- `core/engramd_api.py`, `core/engramd_client.py`, `engramd.py`, and
  `server_daemon_client.py` provide the daemon/thin-client path for the rebuilt
  runtime and the legacy compatibility runtime.
- `core/document_intelligence.py`, `core/document_extractors.py`,
  `core/document_artifacts.py`, and `core/document_quality.py` already provide
  no-write document intelligence and visual-evidence review surfaces.

Execution rules for the overnight pass:

- Treat each task below as a target capability, not a command to create a
  duplicate module if an existing module already owns part of the behavior.
- Add `core/memory_os/` package modules as the stable rebuilt-runtime boundary,
  but delegate to existing proven modules where that preserves behavior and
  reduces migration risk.
- Every production-code slice starts with a failing test, then minimal
  implementation, then focused verification, then a commit.
- For docs-only hardening, run `git diff --check` and a focused grep/doc sanity
  check before committing.
- If MCP Engram remains unavailable at closeout, append import-ready memories to
  `docs/ENGRAM_MEMORY_FALLBACK_2026_05_13.md`; do not claim Engram persistence
  unless the daemon API or MCP write succeeds.

## Execution Ledger

- `4bf2af17` hardened this plan before implementation.
- `70cb7173` through `1f66b858` implemented the Memory OS schema, ledger,
  content store, import/passport wrappers, transactions, jobs, snapshots,
  firewall, LanceDB retrieval, Kuzu graph, daemon runtime, document pipeline,
  retrieval planner/eval packs, and design skill compiler.
- `39fd6266` added read-only Memory OS inspector surfaces in core, daemon,
  client, and WebUI layers.
- `2a77efa8` routed daemon stable memory operations through Memory OS runtime,
  added backend-proving daemon smoke output, and made metadata updates create
  distinct transaction receipts.

## File Map

- Create `core/memory_os/schema.py`: canonical schema constants, table names, lifecycle enums, truth types, and reference helpers.
- Create `core/memory_os/ledger.py`: SQLite connection, migrations, repository functions, and transaction boundaries. Align with the existing migration ledger tables before widening.
- Create `core/memory_os/content_store.py`: content-addressed artifact storage and safe path handling. Reuse the artifact/hash semantics already proven in `core/memory_os_migration.py`.
- Create `core/memory_os/legacy_import.py`: stable rebuilt-runtime wrapper around current JSON memory and graph imports. Prefer delegating to `MemoryOSMigrationKernel` until the new ledger fully subsumes it.
- Create `core/memory_os/bundles.py`: export/restore bundles and portable memory passport manifests. Preserve compatibility with `MemoryOSMigrationKernel.export_bundle()` / `restore_bundle()`.
- Create `core/memory_os/entities.py`: entity, concept, alias, merge, and split workflows.
- Create `core/memory_os/transactions.py`: dry-run, promote, rollback, receipts, idempotency, and partial failure records.
- Create `core/memory_os/jobs.py`: daemon-owned durable job queue and progress events.
- Create `core/memory_os/firewall.py`: prompt-injection and untrusted-source classification.
- Create `core/memory_os/snapshots.py`: snapshot manifests, diffs, and answer replay support.
- Create `core/memory_os/retrieval.py`: LanceDB-backed vector/full-text/hybrid retrieval over ledger chunks.
- Create `core/memory_os/graph.py`: Kuzu-backed graph store over entities, concepts, documents, memories, claims, and visual artifacts.
- Create `core/memory_os/planner.py`: inspectable retrieval planner for vector/full-text/graph/capsule/document strategies.
- Create `core/memory_os/document_pipeline.py`: materialized document jobs, coverage maps, licensing metadata, and promotion transactions.
- Create `core/memory_os/design_compiler.py`: design knowledge compiler and skill-pack export from reviewed concepts.
- Modify `engramd.py`: route rebuilt operations through the Memory OS services.
- Modify `core/engramd_api.py` and `core/engramd_client.py`: expose rebuilt daemon endpoints.
- Modify `server_daemon_client.py`: expose stable thin-client MCP workflows.
- Modify `webui.py`, `templates/index.html`, `static/app.js`: local Memory Inspector surfaces.
- Modify `requirements-core.txt` and `requirements-backend-spike.txt`: promote LanceDB/Kuzu into the rebuilt core dependency profile when the gates pass.
- Add tests under `tests/memory_os/` for every new module.

## Task 0: Canonical Scope Cleanup

Status: completed in commit `f73a040f`.

**Files:**
- Modify: `plan.md`
- Modify: `docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md`
- Create: `docs/archive/legacy-local-core-1-0/README.md`
- Move: legacy `docs/ENGRAM_1_0_*.md` files into `docs/archive/legacy-local-core-1-0/`

- [x] **Step 1: Verify legacy docs are archived.**

Run:

```powershell
Get-ChildItem docs\archive\legacy-local-core-1-0 -File | Select-Object -ExpandProperty Name
```

Expected: the archive contains the legacy local-core release spec, implementation plan, MCP contract, release checklist, migration notes, and track audit.

- [x] **Step 2: Verify active docs point at the rebuild spec.**

Run:

```powershell
rg -n "ENGRAM_MEMORY_OS_REBUILD_SPEC|legacy-local-core-1-0|SQLite ledger|LanceDB|Kuzu" plan.md docs\archive\legacy-local-core-1-0\README.md docs\ENGRAM_MEMORY_OS_REBUILD_SPEC.md
```

Expected: `plan.md` names the rebuild spec as active and the archive README names it as the replacement.

- [x] **Step 3: Commit the cleanup.**

Run:

```powershell
git add plan.md docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md docs/archive/legacy-local-core-1-0
git commit -m "docs: make Memory OS rebuild spec canonical"
```

## Task 1: Schema Contract and Test Harness

**Files:**
- Create: `core/memory_os/__init__.py`
- Create: `core/memory_os/schema.py`
- Create: `tests/memory_os/test_schema_contract.py`

- [ ] **Step 1: Write failing schema contract tests.**

Add `tests/memory_os/test_schema_contract.py`:

```python
from core.memory_os import schema


def test_schema_declares_required_core_tables():
    assert {
        "sources",
        "documents",
        "sections",
        "chunks",
        "drafts",
        "memories",
        "entities",
        "concepts",
        "graph_edges",
        "transactions",
        "retrieval_receipts",
        "jobs",
        "snapshots",
        "firewall_events",
    }.issubset(set(schema.TABLES))


def test_truth_types_match_rebuild_spec():
    assert schema.TRUTH_TYPES == (
        "observation",
        "user_preference",
        "decision",
        "claim",
        "summary",
        "inference",
        "procedure",
        "artifact",
    )


def test_cross_document_edge_types_are_available():
    assert {
        "same_as",
        "similar_to",
        "extends",
        "refines",
        "supports",
        "contradicts",
        "applies_to",
        "example_of",
        "anti_pattern_of",
        "synthesizes",
        "cites",
        "illustrates",
    }.issubset(set(schema.GRAPH_EDGE_TYPES))
```

- [ ] **Step 2: Run the failing test.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_schema_contract.py -q
```

Expected: fail because `core.memory_os.schema` does not exist.

- [ ] **Step 3: Add minimal schema constants.**

Create `core/memory_os/__init__.py`:

```python
"""Engram Memory OS runtime package."""
```

Create `core/memory_os/schema.py`:

```python
"""Canonical Memory OS schema constants."""
from __future__ import annotations

SCHEMA_VERSION = "2026-05-13.memory-os.v1"

TABLES = (
    "sources",
    "documents",
    "sections",
    "chunks",
    "drafts",
    "memories",
    "entities",
    "concepts",
    "aliases",
    "graph_edges",
    "transactions",
    "retrieval_receipts",
    "jobs",
    "job_events",
    "snapshots",
    "firewall_events",
    "eval_packs",
    "skill_packs",
)

TRUTH_TYPES = (
    "observation",
    "user_preference",
    "decision",
    "claim",
    "summary",
    "inference",
    "procedure",
    "artifact",
)

GRAPH_EDGE_TYPES = (
    "related_to",
    "same_as",
    "similar_to",
    "extends",
    "refines",
    "supports",
    "contradicts",
    "applies_to",
    "example_of",
    "anti_pattern_of",
    "synthesizes",
    "cites",
    "illustrates",
    "supersedes",
    "derived_from",
    "mentions",
)
```

- [ ] **Step 4: Run the test.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_schema_contract.py -q
```

Expected: pass.

- [ ] **Step 5: Commit.**

Run:

```powershell
git add core/memory_os tests/memory_os/test_schema_contract.py
git commit -m "feat: define Memory OS schema contract"
```

## Task 2: SQLite Ledger Kernel

**Files:**
- Create: `core/memory_os/ledger.py`
- Create: `tests/memory_os/test_ledger.py`

- [ ] **Step 1: Write failing ledger migration tests.**

Add `tests/memory_os/test_ledger.py`:

```python
import sqlite3

from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.schema import TABLES


def test_ledger_initializes_required_tables(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "engram.sqlite")
    ledger.initialize()

    with sqlite3.connect(ledger.path) as db:
        tables = {
            row[0]
            for row in db.execute(
                "select name from sqlite_master where type = 'table'"
            ).fetchall()
        }

    assert set(TABLES).issubset(tables)


def test_ledger_records_schema_version(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "engram.sqlite")
    ledger.initialize()

    with sqlite3.connect(ledger.path) as db:
        version = db.execute(
            "select value from meta where key = 'schema_version'"
        ).fetchone()[0]

    assert version == "2026-05-13.memory-os.v1"
```

- [ ] **Step 2: Run the failing tests.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_ledger.py -q
```

Expected: fail because `MemoryOSLedger` does not exist.

- [ ] **Step 3: Implement ledger initialization.**

Add `MemoryOSLedger` with:

- `path: Path`
- `connect() -> sqlite3.Connection`
- `initialize() -> None`
- explicit `create table if not exists` statements for every table in `schema.TABLES`
- `meta(key text primary key, value text not null)`
- foreign keys enabled on each connection

- [ ] **Step 4: Run ledger tests.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_ledger.py tests\memory_os\test_schema_contract.py -q
```

Expected: pass.

- [ ] **Step 5: Commit.**

Run:

```powershell
git add core/memory_os/ledger.py tests/memory_os/test_ledger.py
git commit -m "feat: add SQLite Memory OS ledger"
```

## Task 3: Content-Addressed Source Store

**Files:**
- Create: `core/memory_os/content_store.py`
- Create: `tests/memory_os/test_content_store.py`

- [ ] **Step 1: Write failing content store tests.**

Add tests that assert:

- storing bytes returns a SHA-256 artifact id
- duplicate bytes return the same id
- artifact paths remain under the configured data root
- reading by artifact id returns exact bytes

- [ ] **Step 2: Run the failing tests.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_content_store.py -q
```

Expected: fail because the content store does not exist.

- [ ] **Step 3: Implement `ContentAddressedStore`.**

Required public methods:

```python
class ContentAddressedStore:
    def __init__(self, root: Path): ...
    def put_bytes(self, data: bytes, *, suffix: str = "") -> str: ...
    def read_bytes(self, artifact_id: str) -> bytes: ...
    def path_for(self, artifact_id: str) -> Path: ...
```

Use SHA-256 ids and sharded paths such as `sha256/ab/cd/<hash><suffix>`.

- [ ] **Step 4: Verify.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_content_store.py -q
```

Expected: pass.

- [ ] **Step 5: Commit.**

Run:

```powershell
git add core/memory_os/content_store.py tests/memory_os/test_content_store.py
git commit -m "feat: add content-addressed source store"
```

## Task 4: Legacy JSON Import and Portable Bundle

**Files:**
- Create: `core/memory_os/legacy_import.py`
- Create: `core/memory_os/bundles.py`
- Create: `tests/memory_os/test_legacy_import.py`
- Create: `tests/memory_os/test_bundles.py`

- [ ] **Step 1: Write failing legacy import tests.**

Use small fixture JSON records with fields matching current memories: `key`,
`title`, `content`, `tags`, `project`, `domain`, `status`, `canonical`,
`related_to`, timestamps, `chars`, `lines`, and `chunk_count`.

Assert:

- imported key set matches fixture keys
- metadata survives
- `related_to` creates graph/import relation records
- original JSON is stored as an immutable content artifact
- chunk counts are preserved or recorded with an explanation

- [ ] **Step 2: Write failing bundle tests.**

Assert:

- export writes a manifest with ledger schema version and artifact ids
- restore into a clean directory preserves keys and metadata
- restore does not require the old Chroma directory

- [ ] **Step 3: Run failing tests.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_legacy_import.py tests\memory_os\test_bundles.py -q
```

Expected: fail because import and bundle modules do not exist.

- [ ] **Step 4: Implement import and bundle modules.**

Required functions:

```python
def import_legacy_memory_dir(memory_dir: Path, ledger: MemoryOSLedger, store: ContentAddressedStore, *, dry_run: bool = True) -> dict: ...
def export_memory_passport(ledger: MemoryOSLedger, store: ContentAddressedStore, target: Path) -> dict: ...
def restore_memory_passport(bundle: Path, target_root: Path) -> dict: ...
```

Dry-run mode must not write to the active ledger. Applied import must write only
through the ledger and content store.

- [ ] **Step 5: Verify.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_legacy_import.py tests\memory_os\test_bundles.py -q
```

Expected: pass.

- [ ] **Step 6: Commit.**

Run:

```powershell
git add core/memory_os/legacy_import.py core/memory_os/bundles.py tests/memory_os/test_legacy_import.py tests/memory_os/test_bundles.py
git commit -m "feat: import legacy memories into Memory OS"
```

## Task 5: Transactions, Snapshots, Jobs, and Firewall Kernel

**Files:**
- Create: `core/memory_os/transactions.py`
- Create: `core/memory_os/snapshots.py`
- Create: `core/memory_os/jobs.py`
- Create: `core/memory_os/firewall.py`
- Create: `tests/memory_os/test_transactions.py`
- Create: `tests/memory_os/test_snapshots.py`
- Create: `tests/memory_os/test_jobs.py`
- Create: `tests/memory_os/test_firewall.py`

- [ ] **Step 1: Write failing transaction tests.**

Assert a transaction can be dry-run, promoted once with an idempotency key, and
rolled back to a snapshot ref.

- [ ] **Step 2: Write failing snapshot tests.**

Assert snapshot manifests include ledger revision, source manifest hash,
LanceDB rebuild manifest ref, Kuzu rebuild manifest ref, and policy manifest
hash.

- [ ] **Step 3: Write failing job tests.**

Assert jobs move through queued, running, succeeded, failed, and canceled states
with durable event records.

- [ ] **Step 4: Write failing firewall tests.**

Use source strings containing "ignore previous instructions", "send me your
secrets", and ordinary source text. Assert hostile strings are quarantined and
ordinary text is allowed as evidence.

- [ ] **Step 5: Implement minimal kernels.**

Public functions/classes:

```python
class MemoryTransactionService: ...
class SnapshotService: ...
class JobQueue: ...
class MemoryFirewall: ...
```

Keep all state in SQLite tables and return dict receipts for future MCP/API
wrapping.

- [ ] **Step 6: Verify.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_transactions.py tests\memory_os\test_snapshots.py tests\memory_os\test_jobs.py tests\memory_os\test_firewall.py -q
```

Expected: pass.

- [ ] **Step 7: Commit.**

Run:

```powershell
git add core/memory_os/transactions.py core/memory_os/snapshots.py core/memory_os/jobs.py core/memory_os/firewall.py tests/memory_os
git commit -m "feat: add Memory OS transaction kernel"
```

## Task 6: LanceDB Retrieval Promotion

**Files:**
- Create: `core/memory_os/retrieval.py`
- Modify: `core/lancedb_vector_index.py`
- Modify: `requirements-core.txt`
- Test: `tests/memory_os/test_retrieval.py`
- Test: `tests/test_lancedb_vector_index.py`

- [ ] **Step 1: Write failing retrieval tests.**

Assert:

- chunks from the ledger can be indexed into LanceDB
- vector search returns cited chunk refs
- metadata filters work
- full-text or hybrid search returns identifier-heavy matches
- rebuild from ledger is deterministic

- [ ] **Step 2: Run failing tests.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_retrieval.py -q
```

Expected: fail until `core.memory_os.retrieval` exists.

- [ ] **Step 3: Implement retrieval service.**

Public class:

```python
class MemoryOSRetrievalIndex:
    def rebuild_from_ledger(self) -> dict: ...
    def search(self, query: str, *, filters: dict | None = None, limit: int = 5) -> dict: ...
    def hybrid_search(self, query: str, *, filters: dict | None = None, limit: int = 5) -> dict: ...
```

Use `LanceDBVectorIndex` internally and preserve citation fields from ledger
chunks.

- [ ] **Step 4: Promote LanceDB into rebuilt core dependencies.**

Move LanceDB from backend-spike-only to the rebuilt core dependency profile only
after tests pass in the local venv.

- [ ] **Step 5: Verify.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_retrieval.py tests\test_lancedb_vector_index.py -q
```

Expected: pass.

- [ ] **Step 6: Commit.**

Run:

```powershell
git add core/memory_os/retrieval.py core/lancedb_vector_index.py requirements-core.txt tests/memory_os/test_retrieval.py tests/test_lancedb_vector_index.py
git commit -m "feat: promote LanceDB retrieval for Memory OS"
```

## Task 7: Kuzu Graph Promotion and Entity Registry

**Files:**
- Create: `core/memory_os/entities.py`
- Create: `core/memory_os/graph.py`
- Modify: `core/kuzu_graph_store.py`
- Modify: `requirements-core.txt`
- Test: `tests/memory_os/test_entities.py`
- Test: `tests/memory_os/test_graph.py`
- Test: `tests/test_kuzu_graph_store.py`

- [ ] **Step 1: Write failing entity registry tests.**

Assert:

- aliases resolve to canonical entities
- low-confidence aliases are flagged
- entity merge preserves original labels
- entity split records history

- [ ] **Step 2: Write failing Kuzu graph tests.**

Assert:

- graph import preserves edge ids and evidence
- cross-book concept edges return path evidence
- traversal returns refs/evidence, not memory bodies
- contradiction and supersession paths are queryable

- [ ] **Step 3: Run failing tests.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_entities.py tests\memory_os\test_graph.py -q
```

Expected: fail until modules exist.

- [ ] **Step 4: Implement registry and graph service.**

Public classes:

```python
class EntityRegistry: ...
class MemoryOSGraph: ...
```

Persist entity metadata in SQLite and graph topology in Kuzu. Mirror required
edge metadata in SQLite for export/restore.

- [ ] **Step 5: Verify.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_entities.py tests\memory_os\test_graph.py tests\test_kuzu_graph_store.py -q
```

Expected: pass.

- [ ] **Step 6: Commit.**

Run:

```powershell
git add core/memory_os/entities.py core/memory_os/graph.py core/kuzu_graph_store.py requirements-core.txt tests/memory_os/test_entities.py tests/memory_os/test_graph.py tests/test_kuzu_graph_store.py
git commit -m "feat: promote Kuzu graph for Memory OS"
```

## Task 8: Daemon-Owned Runtime Switch

**Files:**
- Modify: `engramd.py`
- Modify: `core/engramd_api.py`
- Modify: `core/engramd_client.py`
- Modify: `server_daemon_client.py`
- Test: `tests/memory_os/test_daemon_runtime.py`
- Test: `tests/test_engramd_api.py`
- Test: `tests/test_server_daemon_client.py`

- [ ] **Step 1: Write failing daemon runtime tests.**

Assert:

- `engramd` initializes SQLite, content store, LanceDB, and Kuzu
- thin MCP client never imports storage/index backends
- memory search goes through the rebuilt retrieval service
- graph path calls go through Kuzu service
- source imports create jobs instead of blocking MCP stdio

- [ ] **Step 2: Run failing tests.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_daemon_runtime.py tests\test_server_daemon_client.py -q
```

Expected: fail until daemon runtime wiring exists.

- [ ] **Step 3: Wire daemon services.**

Create one daemon-owned service container that holds ledger, content store,
retrieval, graph, jobs, transactions, firewall, and snapshots. API routes must
call the service container and return structured errors.

- [ ] **Step 4: Verify.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_daemon_runtime.py tests\test_engramd_api.py tests\test_server_daemon_client.py -q
```

Expected: pass.

- [ ] **Step 5: Commit.**

Run:

```powershell
git add engramd.py core/engramd_api.py core/engramd_client.py server_daemon_client.py tests/memory_os/test_daemon_runtime.py tests/test_engramd_api.py tests/test_server_daemon_client.py
git commit -m "feat: route Memory OS through engramd"
```

## Task 9: Document Intelligence Jobs and Coverage Maps

**Files:**
- Create: `core/memory_os/document_pipeline.py`
- Modify: `core/document_intelligence.py`
- Modify: `core/document_extractors.py`
- Test: `tests/memory_os/test_document_pipeline.py`
- Test: `tests/test_document_disassembly.py`
- Test: `tests/test_document_intelligence.py`

- [ ] **Step 1: Write failing coverage-map tests.**

Assert a fixture PDF-like manifest reports pages, text coverage, visual-needed
pages, interpreted visuals, tables, figures, chunks, claims, concepts, graph
proposals, low-confidence regions, and skipped regions.

- [ ] **Step 2: Write failing licensing metadata tests.**

Assert document imports preserve quote policy, citation format, and whether
skill export may include direct excerpts.

- [ ] **Step 3: Run failing tests.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_document_pipeline.py -q
```

Expected: fail until the document pipeline exists.

- [ ] **Step 4: Implement materialized document jobs.**

Document jobs must write source/document/section/chunk metadata to SQLite,
artifacts to the content store, and coverage maps as job receipts. They must not
promote active memories automatically.

- [ ] **Step 5: Verify.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_document_pipeline.py tests\test_document_disassembly.py tests\test_document_intelligence.py -q
```

Expected: pass.

- [ ] **Step 6: Commit.**

Run:

```powershell
git add core/memory_os/document_pipeline.py core/document_intelligence.py core/document_extractors.py tests/memory_os/test_document_pipeline.py tests/test_document_disassembly.py tests/test_document_intelligence.py
git commit -m "feat: add Memory OS document pipeline"
```

## Task 10: Retrieval Planner and Golden Eval Packs

**Files:**
- Create: `core/memory_os/planner.py`
- Modify: `core/reliability_harness.py`
- Modify: `core/retrieval_eval.py`
- Test: `tests/memory_os/test_planner.py`
- Test: `tests/test_retrieval_eval.py`

- [ ] **Step 1: Write failing planner tests.**

Assert planner chooses:

- LanceDB vector search for semantic questions
- full-text/hybrid search for identifiers
- Kuzu graph paths for relationship questions
- project capsule first for repo resume
- contradiction scan for claims and decisions

- [ ] **Step 2: Write failing eval-pack tests.**

Create a tiny design-book fixture with two documents and expected cross-document
evidence. Assert missing expected source refs fail the eval.

- [ ] **Step 3: Implement planner and eval packs.**

Public functions:

```python
def plan_retrieval(task: str, *, filters: dict, budget_chars: int) -> dict: ...
def run_eval_pack(pack_id: str, *, ledger: MemoryOSLedger) -> dict: ...
```

- [ ] **Step 4: Verify.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os/test_planner.py tests/test_retrieval_eval.py -q
```

Expected: pass.

- [ ] **Step 5: Commit.**

Run:

```powershell
git add core/memory_os/planner.py core/reliability_harness.py core/retrieval_eval.py tests/memory_os/test_planner.py tests/test_retrieval_eval.py
git commit -m "feat: add retrieval planner and eval packs"
```

## Task 11: Design Knowledge Compiler and Skill Export

**Files:**
- Create: `core/memory_os/design_compiler.py`
- Test: `tests/memory_os/test_design_compiler.py`

- [ ] **Step 1: Write failing design compiler tests.**

Use reviewed concept fixtures for visual hierarchy and attention. Assert the
compiler produces:

- design principle
- critique rubric
- checklist item
- anti-pattern
- citation refs
- quote-safety metadata
- eval pack refs

- [ ] **Step 2: Run failing tests.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_design_compiler.py -q
```

Expected: fail until the compiler exists.

- [ ] **Step 3: Implement compiler and skill manifest export.**

Public functions:

```python
def compile_design_knowledge(scope: dict, *, ledger: MemoryOSLedger) -> dict: ...
def export_skill_pack(compilation_id: str, target: Path, *, ledger: MemoryOSLedger) -> dict: ...
```

Do not export raw book text except short quote-safe excerpts with citation
metadata.

- [ ] **Step 4: Verify.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_design_compiler.py -q
```

Expected: pass.

- [ ] **Step 5: Commit.**

Run:

```powershell
git add core/memory_os/design_compiler.py tests/memory_os/test_design_compiler.py
git commit -m "feat: compile design knowledge into skill packs"
```

## Task 12: Local Memory Inspector

**Files:**
- Modify: `webui.py`
- Modify: `templates/index.html`
- Modify: `static/app.js`
- Test: `tests/test_webui_inspector.py`
- Test: `tests/test_webui_auth.py`
- Test: `tests/test_security_defaults.py`

- [ ] **Step 1: Write failing inspector route tests.**

Assert loopback-authenticated inspector routes expose:

- migration/import coverage
- jobs
- transactions
- graph paths
- entity/concept registry
- firewall queue
- coverage maps
- snapshots
- skill-pack previews

- [ ] **Step 2: Verify exposed-host security still fails closed.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\test_webui_auth.py tests\test_security_defaults.py -q
```

Expected: current tests pass before UI changes.

- [ ] **Step 3: Implement read-only inspector APIs and UI panels.**

Keep mutation flows explicit and token-protected. The inspector can show queue
items and transaction previews, but it must not silently approve promotions.

- [ ] **Step 4: Verify.**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\test_webui_inspector.py tests\test_webui_auth.py tests\test_security_defaults.py -q
```

Expected: pass.

- [ ] **Step 5: Commit.**

Run:

```powershell
git add webui.py templates/index.html static/app.js tests/test_webui_inspector.py tests/test_webui_auth.py tests/test_security_defaults.py
git commit -m "feat: add Memory OS inspector surfaces"
```

## Task 13: Final Rebuild 1.0 Gate

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `plan.md`
- Modify: `docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md`
- Create: `docs/ENGRAM_MEMORY_OS_1_0_RELEASE_CHECKLIST.md`
- Create: `docs/ENGRAM_MEMORY_OS_1_0_MIGRATION_GUIDE.md`

- [ ] **Step 1: Write release checklist.**

The checklist must include:

```powershell
.\venv\Scripts\python.exe server.py --help
.\venv\Scripts\python.exe -c "from core.memory_manager import memory_manager; print('ok')"
.\venv\Scripts\python.exe engramd.py --doctor
.\venv\Scripts\python.exe engramd.py --smoke-test
.\venv\Scripts\python.exe server.py --agent-eval
.\venv\Scripts\python.exe -m pytest -q
git diff --check
codex mcp get engram
```

Add Memory OS-specific checks for:

- legacy JSON import parity
- SQLite export/restore
- LanceDB rebuild/search parity
- Kuzu graph import/path parity
- document Book Dismantling Gate
- firewall quarantine fixture
- transaction rollback fixture
- memory passport restore

- [ ] **Step 2: Update public docs.**

README and AGENTS must say the rebuilt 1.0 target is SQLite + content store +
LanceDB + Kuzu + daemon ownership. Archived legacy docs must not be presented as
active 1.0.

- [ ] **Step 3: Run final validation.**

Run:

```powershell
.\venv\Scripts\python.exe server.py --help
.\venv\Scripts\python.exe -c "from core.memory_manager import memory_manager; print('ok')"
.\venv\Scripts\python.exe engramd.py --doctor
.\venv\Scripts\python.exe engramd.py --smoke-test
$env:ENGRAM_LIVE_DAEMON_SMOKE = "1"
.\venv\Scripts\python.exe -m pytest tests\test_engramd_smoke.py::test_live_engramd_subprocess_smoke -q
Remove-Item Env:\ENGRAM_LIVE_DAEMON_SMOKE
.\venv\Scripts\python.exe server.py --agent-eval
.\venv\Scripts\python.exe -m pytest -q
git diff --check
codex mcp get engram
```

Expected: all commands pass or documented operator-only checks are explicitly
called out with evidence.

- [ ] **Step 4: Write closeout memory.**

Use Engram MCP if callable. If this thread's MCP surface is still stale, use the
daemon API to store a concise closeout memory with branch, commits, files,
validation, and next step.

- [ ] **Step 5: Commit final release docs.**

Run:

```powershell
git add README.md AGENTS.md plan.md docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md docs/ENGRAM_MEMORY_OS_1_0_RELEASE_CHECKLIST.md docs/ENGRAM_MEMORY_OS_1_0_MIGRATION_GUIDE.md
git commit -m "docs: prepare Memory OS rebuild 1.0 gate"
```

## Implementation Rules

- Verify every task before committing.
- Keep legacy JSON/Chroma readable until import/export parity is proven.
- Do not promote LanceDB or Kuzu to live runtime outside `engramd`.
- Do not make hosted sync, tenant auth, billing, or collaboration workflows part
  of local rebuild 1.0.
- Do not auto-promote document evidence or agent-written drafts.
- Do not store copyrighted book text in tests, fixtures, skill packs, or docs.
- Use deterministic fixtures in committed tests; use local books only for
  ignored/manual smoke runs.
- Preserve MCP docstring accuracy whenever tool behavior changes.

## Plan Self-Review

- Spec coverage: this plan covers SQLite ledger, content-addressed store,
  LanceDB, Kuzu, daemon ownership, document intelligence, visual evidence,
  graph reasoning, entity registry, firewall, transactions, jobs, snapshots,
  eval packs, skill export, inspector, and portable memory passport.
- Scope: hosted sync, hosted tenant auth, billing, hosted marketplace, and
  hosted collaboration bridge remain post-1.0.
- Completion scan: no incomplete implementation tasks remain; each task has
  explicit files, tests, commands, and commit boundaries.
- Risk: the plan is broad enough to require multiple execution sessions.
  Execute it phase-by-phase with commits after every task.
