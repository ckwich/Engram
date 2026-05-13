# Engram Non-EKC Repo Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the existing Engram 1.0 repo architecture so EKC can be built on top of stable daemon ownership, no-write review semantics, evidence records, backend gates, and release checks.

**Architecture:** This is a pre-EKC repo-health plan, not an EKC implementation plan. It first adds executable guardrails and baseline evidence, then refactors only where live source inspection proves a boundary is missing or duplicated. Existing Memory OS, document intelligence, backend-status, graph, and project-capsule modules are wrapped, tested, or normalized before any new parallel package is introduced.

**Tech Stack:** Python 3.10+, pytest, FastMCP, `engramd`, SQLite Memory OS ledger, LanceDB/Kuzu readiness surfaces, legacy JSON/Chroma compatibility, PowerShell validation gates on Windows.

---

Status: Proposed refactor / hardening plan
Scope: Non-EKC improvements only
Goal: Improve Engram's maintainability, daemon-owned architecture, document-evidence readiness, and release confidence without expanding product scope.

## Intent

This plan improves the current Engram repo aside from the Engram Knowledge Contract. EKC remains a separate product enhancement. Do not implement `query_knowledge`, local KnowQL, Pinecone/Nexus adapters, autonomous compilers, or new EKC artifact families as part of this plan.

The purpose of this plan is to make Engram easier for agents and maintainers to reason about by tightening architecture boundaries:

- daemon-owned Memory OS core
- thin MCP client as the normal agent entrypoint
- legacy storage behind explicit adapters
- document/source evidence as first-class Memory OS records
- no-write preview/review/promotion semantics made consistent
- graph treated as evidence navigation, not truth
- backend readiness gates made executable
- protocol/tool metadata generated from a registry
- release gates that prove Engram 1.0 behavior

## Hardening pass changes

This revision tightens the original refactor plan so it can be executed safely
before EKC work starts.

### Binding execution rules

- Start every phase with a live drift check using `rg --files` and focused
  source reads. If a proposed file already has an equivalent current module,
  wrap or test the existing module first instead of creating a parallel path.
- Add guardrails before refactors. A phase that moves code must first have a
  failing boundary/parity test proving the intended behavior.
- Keep commits small and revertible. Each commit must be one guardrail, one
  adapter, one tool group move, or one documentation gate.
- Do not mix prerequisite hardening with broad architecture cleanup in one
  session. If a phase uncovers larger design work, record it and stop at the
  guardrail.
- Preserve direct-mode compatibility unless a later explicit migration removes
  it. The recommended path can be thin daemon client without deleting `server.py`
  direct mode.
- Treat `server.py` splitting, repository extraction, and response-envelope
  migration as incremental cleanup, not prerequisites for EKC unless a failing
  pre-EKC gate proves otherwise.
- Never add a second semantic implementation when an existing module already
  owns the concept. This applies especially to project capsules, document
  evidence, backend status/eval, graph traversal, and no-write policy metadata.
- All no-write, preview, draft, review, and promotion tools must keep returning
  explicit write metadata. Any missing write metadata is a test failure before it
  is a refactor target.

### Current repo facts this plan must honor

Live source inspection shows existing seams that this plan must use:

- `server_daemon_client.py` already exposes the thin daemon-client entrypoint.
- `server.py` already has `memory_protocol()`, `retrieval_backend_status`,
  `graph_backend_status`, no-write helpers, and `prepare_project_capsule`.
- `core.project_capsule` already owns no-write project capsule draft semantics.
- `core.document_intelligence`, `core.document_extractors`,
  `core.document_artifacts`, `core.document_quality`, and
  `core.memory_os.document_pipeline` already cover major document-evidence
  behavior.
- `core.retrieval_backend_status`, `core.graph_backend_status`,
  `core.retrieval_backend_eval`, and `core.graph_backend_eval` already provide
  backend readiness/eval surfaces.
- `core.memory_os` already has runtime, ledger, retrieval, graph, jobs,
  snapshots, transactions, entities, firewall, content-store, and bundle
  modules.

Any task below that says "Create" must first run the drift check in that phase.
If an equivalent module already exists, the implementation step changes to
"add tests around existing behavior" or "add a thin adapter around existing
behavior."

### Pre-EKC readiness subset

The repo is "ready enough to build EKC on it" when these are complete:

1. Phase 0 baseline is recorded.
2. Phase 1 import-boundary tests prevent thin-client and Memory OS drift.
3. Phase 5 thin-daemon-client recommendation and import smoke are green.
4. Phase 10 no-write policy contract tests cover existing preview/draft tools.
5. Phase 12 backend readiness checks wrap existing backend status/eval surfaces
   without switching live backends.
6. Phase 17 release gate docs exist and are tested.

Phase 2/3 tool registry, Phase 4 server split, Phase 7 repositories, Phase 8
document model expansion, Phase 11 graph package reshaping, Phase 13 response
envelopes, Phase 14 retention, Phase 15 mapping modernization, and Phase 16
WebUI cleanup are valuable but not blockers for starting EKC unless the readiness
subset exposes a concrete failure in that area.

## Grounding

Engram 1.0 is a local-first Memory OS for agents. The current README says the rebuilt runtime uses `engramd`, a SQLite ledger, content-addressed source artifacts, LanceDB retrieval, and Kuzu graph storage, while legacy JSON memories and ChromaDB remain compatibility/migration inputs until callers move through the rebuilt runtime.

The binding 1.0 design says the immediate forcing function is book-scale document intelligence: Engram must process large documents without flattening away pages, figures, tables, captions, OCR evidence, or provenance. The output should be reviewable evidence first, then explicit memory and graph promotion.

## Non-goals

Do not:

- rewrite the whole repo
- build EKC as part of this plan
- add a local KnowQL clone
- add Pinecone/Nexus integration
- make Kuzu the default before graph parity is proven
- make LanceDB the only path before retrieval parity is proven
- delete legacy JSON/Chroma compatibility prematurely
- add hosted/team/collaboration concepts
- build perfect OCR/table extraction
- add a provider-specific model subprocess for document understanding
- expand WebUI into a collaboration product
- add more MCP tools without a registry entry
- weaken local-first or reviewed-write defaults

## Success definition

This plan succeeds when:

- `server.py` is no longer a god file.
- `server_daemon_client.py` is the recommended MCP entrypoint for agents.
- new Memory OS work does not import `core.memory_manager` directly.
- document evidence records are modeled under Memory OS.
- no-write, preview, draft, and promotion behaviors are standardized.
- graph traversal cannot silently load bodies or raise confidence from uncited edges.
- LanceDB and Kuzu readiness are controlled by executable decision gates.
- `memory_protocol()` and docs are generated or checked from a tool registry.
- architecture import-boundary tests prevent future drift.
- Book Dismantling Gate fixtures are executable without committing copyrighted source material.
- release gates can be run by a fresh agent from README/AGENTS instructions.

---

# Phase 0: Baseline inventory and guardrails

## Goal

Create a safe baseline before refactoring.

## Hardening notes

- This phase is mandatory before any code movement.
- Do not create a branch if the current session is already on a user-selected
  branch with local work. In that case, record the current branch and ask before
  switching.
- Capture both command results and environment assumptions. A baseline with
  failing tests is acceptable if failures are documented and not silently folded
  into later refactors.
- Do not run destructive cleanup commands to make the baseline green.

## Tasks

- [ ] Inspect branch and dirty state:

```powershell
git status --short --branch
git log --oneline -5
```

Expected: record the current branch, ahead/behind state, and any dirty files.
If dirty files are unrelated user work, do not touch them.

- [ ] Create a new branch only when safe:

```powershell
git checkout -b refactor/memory-os-architecture-hardening
```

Expected: a new branch is created from the current checked-out commit. If the
branch already exists, use a new `codex/`-prefixed branch or stop and ask.

- [ ] Run and record the current validation baseline:

```powershell
.\venv\Scripts\python.exe server.py --help
.\venv\Scripts\python.exe engramd.py --doctor
.\venv\Scripts\python.exe engramd.py --smoke-test
.\venv\Scripts\python.exe server.py --self-test
.\venv\Scripts\python.exe server.py --agent-eval
.\venv\Scripts\python.exe -m pytest -q
git diff --check
```

- [ ] Create `docs/architecture/ENGRAM_REFACTOR_BASELINE.md`.

Include:

```markdown
# Engram Refactor Baseline

Branch:
Date:
Commit:
Python:
OS:

Commands run:
- ...

Known failures:
- ...

Known skips:
- ...

Do not treat existing failures as new refactor failures unless this plan touches the relevant subsystem.
```

## Gate

No refactor starts until baseline failures/skips are documented with exact
commands, exit codes, and whether each failure is pre-existing.

## Commit

```powershell
git add docs/architecture/ENGRAM_REFACTOR_BASELINE.md
git commit -m "docs: record architecture refactor baseline"
```

---

# Phase 1: Add architecture import-boundary tests

## Goal

Prevent the repo from drifting further while refactors happen.

## Rationale

The current architecture wants a daemon-owned Memory OS and a thin MCP client. Boundary violations should fail tests, especially imports from thin client code into storage-heavy or legacy modules.

## Hardening notes

- Phase 1 should not refactor production code. It only adds tests and an
  explicit allowlist for current known exceptions.
- The first test run may fail because the repo already has boundary violations.
  If so, commit only the test after documenting each current violation in the
  baseline, then fix violations one small commit at a time.
- Keep the scanner AST-based. Do not rely on plain substring grep for import
  assertions.
- Ignore `__pycache__`, generated files, fixtures, and archived docs.

## Files

Create:

```text
tests/architecture/test_import_boundaries.py
```

## Rules to enforce

- `server_daemon_client.py` must not import:
  - `core.memory_manager`
  - `core.embedder`
  - `chromadb`
  - `lancedb`
  - `kuzu`
  - document/PDF libraries
  - `server.py`

- `core/memory_os/**` must not import:
  - `server.py`
  - `server_daemon_client.py`
  - FastMCP
  - WebUI modules

- new Memory OS services must not import `core.memory_manager`.

- document extraction/adapters must not write active memory.

- graph traversal services must not import MCP server modules.

- architecture tests must include a narrow allowlist:
  - migration/compatibility modules may touch legacy JSON/Chroma paths
  - `server.py` may keep direct-mode compatibility imports until a later
    explicit server split removes them
  - tests may import implementation modules directly

## Implementation sketch

Use AST-based import scanning.

```python
# tests/architecture/test_import_boundaries.py

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_thin_daemon_client_stays_thin():
    imports = _imports(ROOT / "server_daemon_client.py")
    banned = {
        "core.memory_manager",
        "core.embedder",
        "chromadb",
        "lancedb",
        "kuzu",
        "server",
    }
    assert not (imports & banned)


def test_memory_os_does_not_import_mcp_or_server_modules():
    banned_prefixes = ("server", "server_daemon_client", "mcp", "fastmcp")
    for path in (ROOT / "core" / "memory_os").rglob("*.py"):
        imports = _imports(path)
        bad = [name for name in imports if name.startswith(banned_prefixes)]
        assert bad == [], f"{path} imports banned modules: {bad}"
```

## Gate

```powershell
.\venv\Scripts\python.exe -m pytest tests\architecture\test_import_boundaries.py -q
```

## Commit

```powershell
git add tests/architecture/test_import_boundaries.py
git commit -m "test: add architecture import boundary checks"
```

---

# Phase 2: Create MCP tool registry scaffolding

## Goal

Move protocol/tool metadata into code instead of hard-coding it across `server.py`, `server_daemon_client.py`, README, and tests.

## Rationale

Engram exposes a broad MCP tool surface. The README currently documents many structured tools and states that new integrations should prefer structured tools over text wrappers. Tool metadata should be centralized so docs/protocol/test expectations do not drift.

## Hardening notes

- Build the registry in shadow mode first. The initial registry must not change
  `memory_protocol()` output or MCP registration behavior.
- Register only tools proven by current `memory_protocol()` and tests. Do not
  invent future/EKC tools in this registry.
- Add a parity test that compares registry output to the current protocol
  manifest, but start it as a focused subset to avoid a giant one-shot metadata
  migration.
- Treat aliases as first-class entries only when the current tool surface already
  exposes them.
- This phase is not a blocker for EKC unless protocol drift is already causing
  implementation errors.

## Files

Create:

```text
core/mcp/tool_spec.py
core/mcp/tool_registry.py
tests/mcp/test_tool_registry.py
```

## ToolSpec model

Keep it dependency-light. Use dataclasses, not Pydantic, unless the repo already standardizes on Pydantic.

```python
# core/mcp/tool_spec.py

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ToolStability = Literal["stable", "beta", "experimental", "legacy"]
ToolMode = Literal[
    "read_only",
    "preview_only",
    "draft_only",
    "promotion_required",
    "writes_memory",
    "destructive",
]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    group: str
    description: str
    stability: ToolStability
    mode: ToolMode
    cost_class: str = "low"
    daemon_preferred: bool = True
    daemon_required: bool = False
    writes_active_memory: bool = False
    canonical: bool = True
    aliases: tuple[str, ...] = field(default_factory=tuple)
```

## Initial registry entries

Do not register every tool on the first pass. Start with the canonical groups
and the most important existing tools from the live `memory_protocol()` output:

```text
memory_protocol
search_memories
context_pack
prepare_context
make_handoff
prepare_project_capsule
retrieve_chunk
retrieve_chunks
retrieve_memory
prepare_memory
store_memory
prepare_source_memory
prepare_document_disassembly
preview_document_extraction
prepare_document_understanding_packet
prepare_document_promotion_transaction
list_graph_edges
conflict_scan
retrieval_backend_status
graph_backend_status
retrieval_eval
```

Before writing code, run:

```powershell
rg -n "def memory_protocol|tool_groups|canonical_tools" server.py server_daemon_client.py core/tool_payloads.py
.\venv\Scripts\python.exe -m pytest tests\test_agent_protocol_tools.py tests\test_server_daemon_client_entrypoint.py -q
```

Expected: identify current protocol fields and existing tests that must remain
green after the shadow registry lands.

## Registry behavior

`core/mcp/tool_registry.py` should provide:

```python
def register_tool(spec: ToolSpec) -> None: ...
def get_tool_spec(name: str) -> ToolSpec | None: ...
def list_tool_specs() -> list[ToolSpec]: ...
def build_tool_groups_manifest() -> dict[str, dict[str, object]]: ...
def build_canonical_tools_manifest() -> dict[str, str]: ...
```

Do not call these builders from `server.py` in Phase 2. That happens only after
Phase 3 parity tests are green.

## Tests

- every registered tool has non-empty name/group/description
- aliases do not collide
- destructive tools cannot be marked `read_only`
- write tools must set `writes_active_memory=True`
- no-write preview tools must set `writes_active_memory=False`

## Gate

```powershell
.\venv\Scripts\python.exe -m pytest tests\mcp\test_tool_registry.py -q
```

## Commit

```powershell
git add core/mcp/tool_spec.py core/mcp/tool_registry.py tests/mcp/test_tool_registry.py
git commit -m "feat: add MCP tool registry"
```

---

# Phase 3: Make `memory_protocol()` consume the registry

## Goal

Make protocol discovery less brittle by deriving tool groups and canonical tool descriptions from the registry.

## Hardening notes

- Do not replace the whole protocol payload in one edit.
- First add a parity assertion that registry-generated `tool_groups` and
  `canonical_tools` match a selected stable subset of the current payload.
- Preserve hand-authored narrative fields: product identity, protocol version,
  daemon warnings, retrieval ladder, recommended gates, and progressive
  discovery prose.
- If registry output would change a tool description, group name, stability, or
  cost class, stop and decide whether the registry or the existing protocol is
  canonical. Do not silently change agent-facing tool contracts.
- Keep `server_daemon_client.py` thin. It may import metadata helpers only if
  they do not import storage, indexes, document extractors, or `server.py`.

## Files

Modify:

```text
server.py
server_daemon_client.py
tests/test_agent_protocol_tools.py
tests/test_server_daemon_client_entrypoint.py
```

## Implementation steps

- [ ] Add a helper in `core/mcp/tool_registry.py`:

```python
def build_memory_protocol_sections() -> dict[str, object]:
    return {
        "tool_groups": build_tool_groups_manifest(),
        "canonical_tools": build_canonical_tools_manifest(),
    }
```

- [ ] In `server.py`, replace manually maintained `tool_groups` and `canonical_tools` sections with registry-generated sections where possible.

- [ ] In `server_daemon_client.py`, do the same for the thin client manifest.

- [ ] Keep manually authored narrative fields such as product version, protocol version, and retrieval ladder description.

- [ ] Add tests that fail if a registered canonical tool is missing from `memory_protocol()`.

- [ ] Snapshot the selected protocol subset before the registry switch:

```powershell
.\venv\Scripts\python.exe - <<'PY'
import asyncio, json
import server
payload = asyncio.run(server.memory_protocol())
subset = {
    "tool_groups": payload["tool_groups"],
    "canonical_tools": payload["canonical_tools"],
}
print(json.dumps(subset, indent=2, sort_keys=True))
PY
```

Expected: keep this output in the phase notes, not necessarily in a committed
fixture unless the snapshot is stable and intentionally curated.

## Gate

```powershell
.\venv\Scripts\python.exe -m pytest tests\test_agent_protocol_tools.py tests\test_server_daemon_client_entrypoint.py -q
```

## Commit

```powershell
git add server.py server_daemon_client.py core/mcp/tool_registry.py tests/test_agent_protocol_tools.py tests/test_server_daemon_client_entrypoint.py
git commit -m "refactor: generate protocol tool metadata from registry"
```

---

# Phase 4: Split `server.py` without changing behavior

## Goal

Reduce `server.py` into bootstrapping and compatibility glue while moving tool handlers into focused modules.

## Rationale

The current repo has a large MCP surface: retrieval, writes, metadata, source workflows, document intelligence, graph, evaluation, codebase mapping, operations, and text wrappers. Keeping all handlers in one central file makes it harder for agents to patch safely.

## Hardening notes

- Phase 4 is intentionally deferred until after Phases 1, 2, 3, and 10 have
  guardrails. A server split without import-boundary, registry, and no-write
  tests is too risky.
- Split only when a tool group has a clear dependency boundary. If a handler
  relies heavily on shared `server.py` globals, first introduce an explicit
  dependency object in a separate commit.
- Moving code is not allowed to change payload shape, docstring behavior, MCP
  tool names, usage accounting, or daemon/direct-mode fallback behavior.
- Each moved group needs a before/after focused test run plus `server.py
  --self-test`.
- Do not move `query_knowledge` here; EKC has its own implementation plan.

## Target structure

Create:

```text
core/mcp/tools/__init__.py
core/mcp/tools/retrieval_tools.py
core/mcp/tools/write_tools.py
core/mcp/tools/source_tools.py
core/mcp/tools/document_tools.py
core/mcp/tools/graph_tools.py
core/mcp/tools/eval_tools.py
core/mcp/tools/codebase_tools.py
core/mcp/tools/ops_tools.py
core/mcp/tools/compat_text_tools.py
```

## Migration strategy

Do not rewrite logic. Move functions in batches.

Batch order:

1. operations and usage tools
2. retrieval tools
3. source tools
4. document tools
5. graph tools
6. codebase mapping tools
7. compatibility text wrappers
8. write/destructive tools last

For each batch:

- move only related handlers
- keep function names stable
- keep MCP registration stable
- re-export if tests import from `server.py`
- do not change payload shapes
- run focused tests

## Suggested pattern

```python
# core/mcp/tools/retrieval_tools.py


def register_retrieval_tools(mcp, deps) -> None:
    @mcp.tool()
    async def search_memories(...):
        ...
```

`server.py` becomes:

```python
mcp = FastMCP("Engram")


def register_all_tools() -> None:
    register_retrieval_tools(mcp, deps)
    register_write_tools(mcp, deps)
    ...
```

## Gate

After each batch:

```powershell
.\venv\Scripts\python.exe -m pytest tests\test_agent_protocol_tools.py tests\test_server_structured_tools.py -q
.\venv\Scripts\python.exe server.py --self-test
git diff --check
```

## Final success metric

`server.py` should mainly contain:

- app creation
- dependency construction
- protocol/version metadata
- tool-module registration
- CLI entrypoints
- direct-mode compatibility glue

## Commit pattern

Use one commit per batch:

```powershell
git commit -m "refactor: move retrieval MCP tools into focused module"
git commit -m "refactor: move document MCP tools into focused module"
...
```

---

# Phase 5: Make `server_daemon_client.py` the recommended agent entrypoint

## Goal

Protect daemon-owned storage by making the thin daemon client the default recommendation for multi-agent use.

## Rationale

The README says `engramd` owns the rebuilt Memory OS runtime and that the thin MCP client avoids local storage/index imports. This should be reflected in docs, tests, and installation guidance.

## Hardening notes

- This phase is part of the pre-EKC readiness subset.
- Prefer wording that says "recommended for multi-session agents" rather than
  "only supported path." `server.py` direct mode remains debug/compatibility.
- The import smoke test must prove absence of heavy imports, not merely that the
  module imports. Pair it with Phase 1 import-boundary assertions.
- If installer behavior changes, run `codex mcp get engram` when available and
  record whether it points at `server_daemon_client.py` or `server.py`.

## Tasks

- [ ] Update README quickstart to say:

```markdown
Recommended MCP entrypoint for multi-session agents:

python server_daemon_client.py

Use `server.py` direct mode only for local debug, compatibility, or single-process development.
```

- [ ] Update `AGENTS.md` with the same guidance.

- [ ] Add a thin-client startup smoke test:

```text
tests/test_thin_client_startup_imports.py
```

- [ ] Test that importing `server_daemon_client.py` does not initialize storage-heavy dependencies.

## Implementation sketch

```python
def test_server_daemon_client_imports_without_storage_backends(monkeypatch):
    import importlib
    import sys

    module = importlib.import_module("server_daemon_client")
    assert module is not None
    forbidden = {"chromadb", "lancedb", "kuzu", "sentence_transformers"}
    assert forbidden.isdisjoint(sys.modules)
```

Pair this with Phase 1 import-boundary tests.

## Gate

```powershell
.\venv\Scripts\python.exe -m pytest tests\test_server_daemon_client_entrypoint.py tests\architecture\test_import_boundaries.py -q
```

## Commit

```powershell
git add README.md AGENTS.md tests/test_thin_client_startup_imports.py
git commit -m "docs: recommend thin daemon client for agents"
```

---

# Phase 6: Freeze legacy `memory_manager` behind adapter boundary

## Goal

Stop new Memory OS work from importing or extending legacy JSON/Chroma behavior directly.

## Rationale

The README says legacy JSON memories and ChromaDB remain compatibility/migration inputs until every caller moves through the rebuilt runtime. Treat them as legacy adapters, not the future core.

## Hardening notes

- Do not move or rename `core/memory_manager.py` in this phase.
- First create tests that identify current direct imports and classify them as
  allowed compatibility, migration, or drift.
- Add the adapter as a seam for new work; do not force all existing direct-mode
  callers through it in one patch.
- JSON-first/Chroma-second behavior is a compatibility contract. Adapter work
  must preserve it and must not make Chroma failures fatal across the MCP
  transport.
- Direct imports in `server.py` may remain until Phase 4 splits server modules
  or an explicit compatibility migration removes them.

## Files

Create:

```text
core/legacy/__init__.py
core/legacy/memory_manager_adapter.py
tests/legacy/test_memory_manager_adapter.py
```

## Adapter API

```python
class LegacyMemoryAdapter:
    def search_memories(...): ...
    def retrieve_memory(...): ...
    def list_memories(...): ...
    def migrate_to_memory_os(...): ...
```

## Tasks

- [ ] Move direct imports of `core.memory_manager` into `core/legacy/memory_manager_adapter.py` where possible.
- [ ] Replace new service imports with adapter imports.
- [ ] Add architecture test:

```text
New code outside core/legacy, migration modules, and server direct-mode compatibility must not import core.memory_manager.
```

Suggested allowlist:

```python
ALLOWED_MEMORY_MANAGER_IMPORTERS = {
    "server.py",
    "webui.py",
    "core/legacy/memory_manager_adapter.py",
    "core/memory_os_migration.py",
    "core/memory_os/_migration_bridge.py",
}
```

- [ ] Mark `core/memory_manager.py` with a docstring:

```python
"""Legacy JSON/Chroma memory manager.

Do not add new Memory OS functionality here.
Use daemon-owned Memory OS runtime or core.legacy adapters.
"""
```

## Gate

```powershell
rg -n "core\.memory_manager|from core import memory_manager|import memory_manager" .
.\venv\Scripts\python.exe -m pytest tests\legacy tests\architecture -q
```

## Commit

```powershell
git add core/legacy core/memory_manager.py tests/legacy tests/architecture
git commit -m "refactor: isolate legacy memory manager behind adapter"
```

---

# Phase 7: Add Memory OS repository layer

## Goal

Move low-level SQLite record manipulation out of orchestration services.

## Rationale

The Memory OS runtime owns ledger, content store, retrieval, graph, jobs, transactions, snapshots, and firewall. As document evidence expands, direct record manipulation in orchestration code will become brittle.

## Hardening notes

- This phase is not a pre-EKC blocker unless Phase 1 finds Memory OS write/read
  logic too tangled to guard safely.
- Start with read-side repository helpers if possible. Moving write paths first
  is higher risk because store/search/delete smoke tests are release gates.
- Do not create repository files for every future concept in one commit. Create
  only the repository that a failing test requires.
- Keep `MemoryOSRuntime` as the orchestration boundary. Repositories own table
  access, not policy decisions, embedding, retrieval, graph updates, or
  transactions.
- Before creating any repository file, inspect `core/memory_os/ledger.py`,
  `core/memory_os/runtime.py`, and existing tests so the new seam matches the
  current ledger API.

## Files

Create:

```text
core/memory_os/repositories/__init__.py
core/memory_os/repositories/memory_repository.py
core/memory_os/repositories/source_repository.py
core/memory_os/repositories/document_repository.py
core/memory_os/repositories/artifact_repository.py
core/memory_os/repositories/graph_edge_repository.py
core/memory_os/repositories/transaction_repository.py
tests/memory_os/repositories/
```

## First slice

Start with `MemoryRepository` only.

```python
class MemoryRepository:
    def __init__(self, ledger: MemoryOSLedger): ...

    def get(self, key: str) -> dict[str, Any] | None: ...
    def upsert(self, record: dict[str, Any]) -> dict[str, Any]: ...
    def list(self, *, filters: dict[str, Any] | None = None, limit: int = 50) -> list[dict[str, Any]]: ...
    def delete(self, key: str) -> bool: ...
```

Then refactor `MemoryOSRuntime.store_memory`, `retrieve_memory`, `list_memories`, update/delete paths to use it.

## Rules

- no ORM
- no behavior changes in first pass
- repositories return plain dicts unless repo already uses typed models
- repository functions own table names
- runtime owns orchestration and cross-service behavior

## Gate

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_runtime.py tests\memory_os\repositories -q
```

## Commit

```powershell
git add core/memory_os/repositories tests/memory_os/repositories core/memory_os/runtime.py
git commit -m "refactor: add Memory OS memory repository"
```

## Follow-up slices

Add repositories in this order:

1. source/artifact repository
2. document/page/chunk repository
3. graph edge repository
4. transaction/snapshot repository

Do not add all at once.

---

# Phase 8: Model document/source evidence under Memory OS

## Goal

Make document disassembly evidence records first-class Memory OS records instead of ad hoc preview payloads.

## Rationale

The binding 1.0 design requires source, document, page, section, chunk, visual artifact, table artifact, extraction receipt, and quality report records. It says large documents are sources with many evidence records, not single memories.

## Hardening notes

- Do not create a parallel document-intelligence stack. The repo already has
  `core.document_intelligence`, `core.document_extractors`,
  `core.document_artifacts`, `core.document_quality`, and
  `core.memory_os.document_pipeline`.
- First add model/contract tests around existing payloads: source refs, document
  refs, page refs, artifact refs, coordinates, quality warnings,
  `write_performed=false`, and `active_memory_write_performed=false`.
- Add Memory OS document records only where existing preview payloads cannot be
  reconstructed or resumed from current receipts/manifests.
- Treat OCR/vision/table extraction as adapter output. Engram owns provenance,
  coverage, quality, draft, and promotion records; it does not need perfect
  extraction in this phase.
- This phase should not store copyrighted source text, rendered page images, OCR
  output, or table exports in the repo.

## Target package

Create only after the drift check proves the current modules cannot carry the
needed boundary:

```text
core/memory_os/document/
  __init__.py
  models.py
  repositories.py
  manifest.py
  quality.py
  retention.py
  adapters/
    __init__.py
    pdf_local.py
    text_html_markdown.py
```

## Models

Use simple dataclasses or typed dicts.

Required record types:

```text
SourceRecord
DocumentRecord
PageRecord
SectionRecord
ChunkRecord
VisualArtifactRecord
TableArtifactRecord
ExtractionReceiptRecord
QualityReportRecord
ImportManifestRecord
```

## First implementation slice

Do not rewrite all document extraction. Add the model/repository layer and adapt one existing preview path to produce/store or return records in this shape.

Suggested first target:

```text
prepare_document_disassembly
```

It already promises no-write local PDF page/text/image inventory with quality warnings, portable artifact refs, visual candidates, and OCR/vision follow-up request.

## Rules

- no active memory writes
- evidence records only
- every record gets source/document identifiers
- every chunk has source/page/section/span provenance where available
- every extraction has an extraction receipt
- quality warnings are first-class, not just prose strings
- copyrighted source text must not appear in public docs or fixture outputs

## Gate

Add tests:

```text
tests/memory_os/document/test_document_models.py
tests/memory_os/document/test_document_disassembly_records.py
```

Validate:

- clean text PDF fixture creates source/document/page/chunk/receipt/quality records
- image-only fixture creates OCR/vision work requests
- no active memory write occurs
- each chunk has citation/provenance refs
- quality report includes low/no-text pages

## Commit

```powershell
git add core/memory_os/document tests/memory_os/document
git commit -m "feat: model document evidence records in Memory OS"
```

---

# Phase 9: Implement Book Dismantling Gate fixtures

## Goal

Turn the document intelligence promise into an executable release gate.

## Hardening notes

- Prefer synthetic fixtures generated from small scripts or checked-in minimal
  PDFs. Never commit downloaded design books or derived page images/text.
- Keep fixture expectations as manifests, hashes, counts, redacted snippets, and
  structural assertions.
- If local PDF tooling is unavailable in CI, the gate should skip with a clear
  missing-tool reason, not silently pass.
- The gate should exercise existing document disassembly APIs before adding new
  document model code.

## Rationale

The binding 1.0 design says Engram cannot claim rich document intelligence until the Book Dismantling Gate passes. The gate covers clean text, book-style PDFs, image-heavy PDFs, scanned pages, multi-column pages, irregular tables, figure/caption pages, rotated pages, OCR noise, and mixed text/image pages.

## Files

Create:

```text
tests/fixtures/documents/
  clean_text_pdf/
  scanned_one_page/
  rotated_page/
  multicolumn_page/
  table_irregular/
  figure_caption/
  mixed_text_image/
  manifests/

tests/document_gate/test_book_dismantling_gate.py
```

## Fixture rules

Do not commit:

```text
copyrighted PDFs
extracted book text
rendered page images
OCR output from copyrighted sources
table exports from copyrighted sources
```

Commit only:

```text
synthetic PDFs
fixture manifests
hashes
counts
receipts
quality summaries
redacted snippets
```

## Gate behavior

The Book Dismantling Gate passes when Engram can:

- inventory pages without loading full documents into memory
- extract available text and identify low/no-text pages
- detect image/table/figure/caption candidates
- create targeted OCR/vision work requests only where needed
- preserve page and coordinate provenance
- produce chunk manifests with source/page/section refs
- produce quality reports with failed pages and low-confidence regions
- propose memories and graph edges without auto-promoting
- resume interrupted jobs without duplicating artifacts
- retrieve chunks with citations back to page/artifact ids

## Implementation sketch

```python
def test_clean_text_pdf_disassembly_gate(tmp_path):
    payload = prepare_document_disassembly(...)
    assert payload["write_performed"] is False
    assert payload["quality_report"]["page_count"] > 0
    assert payload["chunk_manifest"]
    assert all("page_ref" in chunk for chunk in payload["chunk_manifest"]["chunks"])


def test_scanned_pdf_creates_visual_work_request(tmp_path):
    payload = prepare_document_disassembly(...)
    assert payload["quality_report"]["ocr_needed_pages"]
    assert payload["visual_extraction_request"]["required_artifacts"]
```

## Gate

```powershell
.\venv\Scripts\python.exe -m pytest tests\document_gate -q
```

## Commit

```powershell
git add tests/fixtures/documents tests/document_gate
git commit -m "test: add book dismantling gate fixtures"
```

---

# Phase 10: Standardize no-write, preview, draft, and promotion policies

## Goal

Prevent accidental active-memory writes from preview/document/source workflows.

## Rationale

Engram has many no-write tools: source previews, document disassembly, document extraction previews, understanding packets, draft preparation, promotion transaction preparation, context packets, handoffs, and project capsules. Their write semantics should be consistent and testable.

## Hardening notes

- This phase is part of the pre-EKC readiness subset.
- The repo already returns `write_performed` and
  `active_memory_write_performed` from many tools. First add audit tests over
  current responses; only then introduce shared helpers.
- Do not mass-edit every tool to a new enum in one patch. Add `WritePolicy` as
  a validator/normalizer and migrate touched tools gradually.
- Treat missing write metadata as a contract failure for preview/draft tools.
  Treat contradictory metadata, such as `write_policy="preview_only"` with
  `active_memory_write_performed=true`, as a hard failure.
- Keep destructive tools explicit and out of preview/draft groups in the future
  tool registry.

## Files

Create:

```text
core/policy/write_policy.py
tests/policy/test_write_policy.py
tests/mcp/test_no_write_tool_contracts.py
```

## WritePolicy

```python
from enum import Enum


class WritePolicy(str, Enum):
    READ_ONLY = "read_only"
    PREVIEW_ONLY = "preview_only"
    DRAFT_ONLY = "draft_only"
    PROMOTION_REQUIRED = "promotion_required"
    ALLOW_DURABLE_WRITE = "allow_durable_write"
    DESTRUCTIVE = "destructive"
```

## Shared fields

All preview/draft/review tools should include:

```json
{
  "write_policy": "preview_only",
  "write_performed": false,
  "active_memory_write_performed": false,
  "promotion_required": true
}
```

For tools that actually write:

```json
{
  "write_policy": "allow_durable_write",
  "write_performed": true,
  "active_memory_write_performed": true
}
```

For destructive tools:

```json
{
  "write_policy": "destructive",
  "write_performed": true
}
```

## Tests

Use the tool registry from Phase 2.

- all tools with mode `preview_only` return `write_performed=False`
- all tools with mode `draft_only` return `active_memory_write_performed=False`
- tools named `prepare_*` must not write active memory unless explicitly listed as exceptions
- document review/promotion preparation tools never auto-promote

## Gate

```powershell
.\venv\Scripts\python.exe -m pytest tests\policy tests\mcp\test_no_write_tool_contracts.py -q
```

## Commit

```powershell
git add core/policy tests/policy tests/mcp/test_no_write_tool_contracts.py
git commit -m "feat: standardize write policy metadata"
```

---

# Phase 11: Harden graph as evidence navigation

## Goal

Ensure graph traversal explains relationships without becoming an uncited truth source.

## Rationale

The binding 1.0 design requires document drafts to propose typed edges and requires graph evidence inspection without surprise memory body loads. Graph storage should surface support, contradiction, supersession, and dependency relationships, but uncited/proposed edges should not raise answer confidence.

## Hardening notes

- Start with tests around existing graph modules (`core/graph_manager.py`,
  `core/graph_store.py`, `core/kuzu_graph_store.py`, and
  `core/memory_os/graph.py`) before creating a new `core/graph/` package.
- A new graph package is allowed only if it wraps existing graph contracts
  without changing durable edge records.
- Preserve existing graph edge migration fields and typed edge vocabulary.
- Traversal tests must assert returned refs/evidence, not full memory bodies.
- Contradiction/supersession surfacing should remain bounded and cited; it must
  not become an uncited confidence boost for answers.

## Files

Create or refactor toward only after existing graph contracts are covered by
tests:

```text
core/graph/edge_schema.py
core/graph/edge_policy.py
core/graph/traversal_service.py
core/graph/contradiction_service.py
tests/graph/test_edge_policy.py
tests/graph/test_traversal_no_surprise_loads.py
```

## Edge schema

Every edge should have:

```json
{
  "edge_id": "...",
  "from_ref": "...",
  "to_ref": "...",
  "edge_type": "supports|contradicts|depends_on|supersedes|...",
  "source_refs": [],
  "citation_refs": [],
  "review_state": "proposed|reviewed|rejected",
  "confidence": 0.0,
  "created_at": "...",
  "metadata": {}
}
```

## Rules

- proposed edges are never treated as reviewed
- uncited edges cannot raise confidence
- traversal should not load full memory bodies by default
- contradiction/supersession edges are surfaced separately from generic relatedness
- graph backend choice remains behind readiness gates

## Tests

- `conflict_scan` returns contradiction/supersession refs without full body loads
- `impact_scan` respects hop/path limits
- uncited edges are marked low-trust
- graph edge creation requires source/citation refs or `review_state=proposed`
- no test switches live graph backend implicitly

## Gate

```powershell
.\venv\Scripts\python.exe -m pytest tests\graph -q
```

## Commit

```powershell
git add core/graph tests/graph
git commit -m "refactor: treat graph traversal as cited evidence navigation"
```

---

# Phase 12: Make backend readiness gates executable

## Goal

Prevent premature backend switching for LanceDB and Kuzu.

## Rationale

The binding 1.0 design says Chroma remains live until LanceDB proves real-corpus persistence, filtering, rebuild, hybrid lookup, and Windows reliability. JSON graph storage remains live until Kuzu proves import parity, traversal behavior, persistence, and Windows reliability.

## Hardening notes

- This phase is part of the pre-EKC readiness subset, but it should wrap
  existing backend status/eval modules rather than create a parallel decision
  system.
- Existing modules include `core.retrieval_backend_status`,
  `core.graph_backend_status`, `core.retrieval_backend_eval`, and
  `core.graph_backend_eval`. Use them as the source of truth unless a test
  proves a missing decision field.
- Backend gates must remain no-write and must never switch live backends.
- A `ready_for_default` decision must require both parity and Windows path
  reliability evidence. A configured backend alone is not readiness.
- Forced overrides must be explicit, logged, and excluded from default agent
  guidance.

## Files

Create only if a wrapper is needed around existing status/eval modules:

```text
core/backend_gates/__init__.py
core/backend_gates/retrieval_gate.py
core/backend_gates/graph_gate.py
core/backend_gates/parity_report.py
tests/backend_gates/test_retrieval_gate.py
tests/backend_gates/test_graph_gate.py
```

## Gate response schema

```json
{
  "schema_version": "2026-05-13.backend-gate.v1",
  "backend": "lancedb|kuzu|chroma|json_graph",
  "decision": "not_ready|ready_for_shadow|ready_for_default",
  "blocking_failures": [],
  "parity": {},
  "windows_status": {},
  "rebuild_status": {},
  "filtering_status": {},
  "recommendation": ""
}
```

## Retrieval gate checks

- migrated corpus present
- index rebuild succeeds
- metadata filtering works
- hybrid lookup works
- identifier lookup works
- stale exclusion works
- Windows path handling works
- parity against legacy search meets threshold

## Graph gate checks

- edge import parity
- traversal parity
- contradiction scan parity
- persistence across restart
- Windows path handling
- no surprise body loads

## Policy

Backend switch is allowed only if:

```text
decision == "ready_for_default"
```

or if a force override is explicit and logged.

## Gate

```powershell
.\venv\Scripts\python.exe -m pytest tests\backend_gates -q
.\venv\Scripts\python.exe server.py --agent-eval
```

## Commit

```powershell
git add core/backend_gates tests/backend_gates
git commit -m "feat: add executable backend readiness gates"
```

---

# Phase 13: Add shared response envelope helpers

## Goal

Make agent-facing tool responses easier to inspect consistently.

## Rationale

Different tools currently return different payload shapes. That is workable, but every agent should be able to inspect status, errors, warnings, write behavior, citations, receipts, and budget without bespoke parsing.

## Hardening notes

- This is a compatibility-sensitive phase. Do not force every tool into one
  envelope before EKC.
- Start with a helper plus tests for new or newly touched tools. Existing tool
  payloads should be audited before they are migrated.
- Do not change public response fields without a test that proves callers still
  receive the legacy fields.
- Keep EKC's response envelope separate in its EKC plan. This shared helper is
  for general MCP ergonomics and must not pre-decide EKC status/error semantics.
- Migration target for existing tools is additive: add common fields while
  preserving existing fields where agents already rely on them.

## Files

Create:

```text
core/contracts/response_envelope.py
tests/contracts/test_response_envelope.py
tests/mcp/test_tool_response_envelopes.py
```

## Envelope helper

```python
def build_response(
    *,
    operation: str,
    status: str,
    data: dict[str, Any] | None = None,
    citations: list[dict[str, Any]] | None = None,
    receipts: list[dict[str, Any]] | None = None,
    budget_used: dict[str, Any] | None = None,
    write_policy: str = "read_only",
    write_performed: bool = False,
    active_memory_write_performed: bool = False,
    warnings: list[dict[str, Any]] | None = None,
    error: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ...
```

## Canonical top-level fields

```json
{
  "schema_version": "...",
  "operation": "...",
  "status": "ok|partial|failed",
  "data": {},
  "citations": [],
  "receipts": [],
  "budget_used": {},
  "write_policy": "read_only",
  "write_performed": false,
  "active_memory_write_performed": false,
  "warnings": [],
  "error": null
}
```

## Migration strategy

Do not change every tool at once.

Start with:

```text
retrieval_backend_status
graph_backend_status
prepare_document_disassembly
prepare_document_promotion_transaction
retrieval_eval
```

Then migrate more tools as touched.

## Gate

```powershell
.\venv\Scripts\python.exe -m pytest tests\contracts tests\mcp\test_tool_response_envelopes.py -q
```

## Commit

```powershell
git add core/contracts tests/contracts tests/mcp/test_tool_response_envelopes.py
git commit -m "feat: add shared response envelope helpers"
```

---

# Phase 14: Add storage budget and retention policy primitives

## Goal

Control local storage growth from document/page/image/table/chunk evidence.

## Rationale

The binding 1.0 design explicitly warns that storing a full book's pages, images, tables, and chunks can bloat local storage. Mitigation requires content-addressed artifacts, deduplication, page-level manifests, and retention policies.

## Hardening notes

- This phase should build on `core.memory_os.content_store` and document
  artifact manifests instead of inventing a second object store.
- Retention defaults must be conservative: preserve source hashes/manifests,
  avoid committing or exporting copyrighted derivatives by default, and make
  full support bundles explicit.
- Budget enforcement should record skipped work and resume state rather than
  silently dropping pages/artifacts.
- Do not delete existing artifacts as part of the first retention-policy slice.
  Start with reporting and dry-run cleanup plans.

## Files

Create:

```text
core/memory_os/storage_budget.py
core/memory_os/retention.py
tests/memory_os/test_storage_budget.py
tests/memory_os/test_retention_policy.py
```

## Retention policy

```json
{
  "keep_source_artifact": "always",
  "keep_rendered_pages": "failed_pages|all|never",
  "keep_ocr_outputs": "reviewed_only|all|manual",
  "keep_table_exports": "reviewed_only|all|manual",
  "support_bundle_mode": "hashes_only|redacted|full_explicit"
}
```

## Import budget

```json
{
  "max_pages_processed": 250,
  "max_rendered_page_dpi": 150,
  "max_image_artifacts": 500,
  "max_ocr_queue_size": 100,
  "max_source_text_chars": 1000000,
  "record_skipped_work": true
}
```

## Rules

- skipped work must be recorded
- interrupted jobs must resume from import manifests
- support bundles default to hashes/counts/redacted snippets
- no copyrighted source text in public docs or default support bundles

## Gate

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_storage_budget.py tests\memory_os\test_retention_policy.py -q
```

## Commit

```powershell
git add core/memory_os/storage_budget.py core/memory_os/retention.py tests/memory_os/test_storage_budget.py tests/memory_os/test_retention_policy.py
git commit -m "feat: add storage budget and retention policies"
```

---

# Phase 15: Modernize codebase mapping for Memory OS 1.0

## Goal

Ensure codebase mapping remains useful as agent self-knowledge and does not miss major files.

## Hardening notes

- Codebase mapping must remain agent-authored and provider-neutral.
- Do not add a model subprocess, hidden network dependency, or background
  autonomous summarizer.
- Start by testing current mapping domain coverage and warnings. Only then
  adjust default domains.
- Large-file exclusion warnings must identify the omitted file, configured size
  limit, observed file size, and suggested override.
- Mapping jobs must honor `ENGRAM_DATA_DIR` and source drift receipts.

## Rationale

The binding 1.0 design requires mapping configs to include daemon, migration, document intelligence, backend-status, graph, source, WebUI, and reliability domains. It also says large central files such as `server.py` and `memory_manager.py` must not be silently excluded by a too-low `max_file_size_kb`.

## Tasks

- [ ] Update default mapping domains to include:

```text
daemon
memory_os
migration
document_intelligence
backend_status
graph
source
webui
reliability
mcp_tools
legacy_adapters
```

- [ ] Add warnings when large central files are excluded.

- [ ] Add source drift checks to mapping result storage.

- [ ] Ensure mapping jobs honor `ENGRAM_DATA_DIR`.

- [ ] Ensure mapping synthesis remains agent-authored; do not add a provider-specific model subprocess.

## Tests

Create:

```text
tests/codebase_mapping/test_memory_os_domains.py
tests/codebase_mapping/test_large_file_exclusion_warning.py
tests/codebase_mapping/test_engram_data_dir.py
```

## Gate

```powershell
.\venv\Scripts\python.exe -m pytest tests\codebase_mapping -q
```

## Commit

```powershell
git add core/codebase_mapping* tests/codebase_mapping
git commit -m "feat: modernize codebase mapping for Memory OS domains"
```

---

# Phase 16: WebUI reads daemon-owned operation state only

## Goal

Keep the WebUI as an operator surface, not a parallel state manager.

## Rationale

The 1.0 design says the dashboard should review health, imports, drafts, graph proposals, migration receipts, and evals without becoming a collaboration product.

## Hardening notes

- Preserve current WebUI fail-closed auth behavior for non-loopback exposure.
- Do not add comments, assignments, mentions, roles, collaboration pages, or
  team workflow UI in this repo-hardening plan.
- First inventory current WebUI state sources and classify each as
  daemon/ledger-backed, legacy compatibility, or parallel state.
- Any mutation path must remain explicit and token-protected. The Memory
  Inspector side of the UI remains read-only for Memory OS state.
- WebUI work is not a pre-EKC blocker unless release gates or document evidence
  review are failing because of parallel state.

## Tasks

- [ ] Identify all WebUI state that is not daemon/ledger-backed.
- [ ] Move job/event/receipt state into Memory OS jobs/operation records.
- [ ] Update WebUI to read daemon-owned state.
- [ ] Add tests that WebUI does not create parallel job/import/review state.
- [ ] Preserve fail-closed token protection when exposed beyond loopback.

## Files

Likely modify:

```text
webui.py
core/memory_os/jobs.py
core/memory_os/operation_events.py
core/memory_os/receipts.py
tests/webui/
```

## Gate

```powershell
.\venv\Scripts\python.exe -m pytest tests\webui -q
```

## Commit

```powershell
git add webui.py core/memory_os tests/webui
git commit -m "refactor: make WebUI read daemon-owned operation state"
```

---

# Phase 17: Release gate consolidation

## Goal

Give a fresh agent one documented command sequence that proves Engram 1.0 readiness.

## Hardening notes

- This phase is part of the pre-EKC readiness subset.
- Release docs must distinguish full release gates from quick pre-EKC
  readiness gates so agents do not run an expensive full suite for every small
  plan edit.
- If a gate is optional because local dependencies are missing, the docs must
  say exactly what dependency is missing and what evidence the skip still
  provides.
- `AGENTS.md`, README, and release docs must agree on thin daemon client,
  direct-mode compatibility, no-write previews, and review-first promotion.

## Files

Create or update:

```text
docs/RELEASE_GATES.md
AGENTS.md
README.md
tests/release/test_release_gate_docs.py
```

## Required gates

```powershell
.\venv\Scripts\python.exe server.py --help
.\venv\Scripts\python.exe engramd.py --doctor
.\venv\Scripts\python.exe engramd.py --smoke-test
.\venv\Scripts\python.exe server.py --self-test
.\venv\Scripts\python.exe server.py --agent-eval
.\venv\Scripts\python.exe -m pytest -q
git diff --check
```

Add document-specific gate:

```powershell
.\venv\Scripts\python.exe -m pytest tests\document_gate -q
```

Add architecture gate:

```powershell
.\venv\Scripts\python.exe -m pytest tests\architecture -q
```

Add backend gate:

```powershell
.\venv\Scripts\python.exe -m pytest tests\backend_gates -q
```

## Docs test

Ensure README/AGENTS mention:

- recommended thin daemon client
- direct mode as debug/compatibility
- no-write document preview flow
- review-first promotion
- release gate command sequence

## Commit

```powershell
git add docs/RELEASE_GATES.md README.md AGENTS.md tests/release/test_release_gate_docs.py
git commit -m "docs: consolidate Engram release gates"
```

---

# Recommended execution order

Do not run all phases as one giant patch. Execute in two lanes.

## Lane A: pre-EKC readiness

Run these first, then stop for review:

1. Phase 0: baseline
2. Phase 1: import-boundary tests
3. Phase 5: thin daemon client as recommended entrypoint
4. Phase 10: no-write policy standardization, audit-only first slice
5. Phase 12: backend readiness gates as wrappers around existing status/eval
6. Phase 17: release gate consolidation

This lane is enough to make EKC implementation safer because it proves daemon
ownership, thin-client boundaries, no-write discipline, backend decision
discipline, and repeatable validation.

## Lane B: deeper cleanup after readiness review

Run only after Lane A is reviewed:

1. Phase 2: MCP tool registry in shadow mode
2. Phase 3: memory_protocol generated metadata after parity tests
3. Phase 6: legacy adapter boundary
4. Phase 7: Memory OS repository first slice
5. Phase 8: document evidence model gaps, wrapping existing modules first
6. Phase 9: Book Dismantling Gate fixtures
7. Phase 11: graph evidence hardening around existing graph contracts
8. Phase 13: response envelope helpers, additive only
9. Phase 14: storage budget/retention dry-run policies
10. Phase 15: codebase mapping modernization
11. Phase 16: WebUI state cleanup

Phase 4, splitting `server.py`, is a rolling cleanup phase. It should happen
only after the relevant tool group has registry parity, import-boundary tests,
and no-write/write-policy coverage. Do not attempt to split the entire server in
one commit.

---

# High-risk areas

## Risk: accidental behavior changes while splitting `server.py`

Mitigation:

- move one tool group at a time
- preserve function names and payloads
- run focused tests after each group
- keep re-export shims when tests or callers import from `server.py`

## Risk: breaking legacy users

Mitigation:

- do not delete legacy text wrappers
- keep `server.py` direct mode available for debug/compatibility
- isolate legacy `memory_manager` behind adapter instead of deleting it
- update docs to distinguish recommended path from compatibility path

## Risk: overbuilding document extraction

Mitigation:

- Engram owns evidence records, provenance, chunking, quality reports, drafts, graph proposals, retrieval, and promotion transactions
- extractors remain adapters
- perfect OCR/table reconstruction is not required
- quality reporting and reviewable evidence are required

## Risk: graph becoming fake truth

Mitigation:

- require citation/source refs or mark edges proposed
- do not let uncited edges raise answer confidence
- keep traversal bounded
- avoid surprise full-memory loads

## Risk: backend switching too early

Mitigation:

- Chroma/JSON graph remain live until gates pass
- LanceDB/Kuzu become default only when executable gates say ready
- forced overrides must be explicit and logged

## Risk: storage bloat

Mitigation:

- content-addressed artifacts
- deduplication
- page-level manifests
- retention policy
- import budget
- support bundles default to hashes/counts/redacted snippets

---

# Closeout requirements

At the end of each phase, report:

```text
Phase:
Commit:
Files changed:
Tests run:
Pass/fail:
Behavior changed? yes/no
Residual risks:
Next recommended phase:
```

At the end of the entire plan, create:

```text
docs/architecture/ENGRAM_REFACTOR_CLOSEOUT.md
```

Include:

```markdown
# Engram Architecture Refactor Closeout

Branch:
Final commit:
Phases completed:
Phases deferred:
Validation commands:
Known issues:
Next recommended work:
```

If Engram MCP tools are available, write a closeout memory with key:

```text
engram_architecture_hardening_closeout_2026_05_13
```

If the memory write fails, append an import-ready fallback entry to:

```text
docs/ENGRAM_MEMORY_FALLBACK_2026_05_13.md
```

---

# Plan self-review

- Scope coverage: The hardened plan preserves the original non-EKC direction:
  daemon-owned core, thin agent entrypoint, legacy adapter boundary,
  evidence-first documents, no-write review discipline, bounded graph evidence,
  backend gates, and release checks.
- EKC boundary: The plan explicitly excludes `query_knowledge`, local KnowQL,
  Pinecone/Nexus adapters, autonomous compilers, and new EKC artifact families.
- Current-repo alignment: The plan now requires live drift checks and names
  existing modules that must be wrapped/tested before any parallel path is
  created.
- Pre-EKC readiness: The plan separates the minimum readiness lane from deeper
  cleanup so EKC is not blocked on broad server splitting or repository
  extraction unless a guardrail proves it is necessary.
- Risk reduction: The plan adds baseline capture, import-boundary tests,
  no-write policy audits, backend readiness wrappers, and release docs before
  high-risk refactors.
- Placeholder scan: No phase may execute with "create a new package" as the
  default if current code already owns the concept. Each such phase now starts
  with drift checks and existing-module tests.

---

# Final instruction to Codex

Proceed test-first. Prefer small, reviewable commits. Do not implement EKC in this plan. Do not expand product scope. The purpose is to make the existing Engram 1.0 architecture enforceable: daemon-owned core, thin agent entrypoint, legacy adapter boundary, evidence-first document records, no-write review discipline, bounded graph evidence, executable backend gates, and reliable release checks.

Recommended first action: execute Lane A Phase 0 and Phase 1 only, then stop
for review. Those phases are low-risk and immediately useful because they
capture the current baseline and add guardrails before touching architecture.
