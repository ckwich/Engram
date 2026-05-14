# Engram Final Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring Engram to a boring, trustworthy local-first final state so it can support work across other projects without recurring architectural cleanup.

**Architecture:** Stabilize the daemon-owned Memory OS path as the normal operating mode, keep direct JSON/Chroma paths recoverable as legacy compatibility, make review and promotion flows explicit, and collapse drift between docs, protocol metadata, tests, and runtime behavior. Do not chase hosted/SaaS scope, speculative backend swaps, or broad UI redesign before the local cross-project memory foundation is dependable.

**Tech Stack:** Python 3.12, FastMCP, `engramd`, thin `server_daemon_client.py`, `MemoryOSRuntime`, SQLite ledger, content-addressed source store, LanceDB/Kuzu behind daemon-owned Memory OS services, legacy JSON/Chroma compatibility paths, pytest, PowerShell validation gates.

---

## Final-State Definition

Engram is "solid enough to go back to other projects" when all of these are true:

- The current feature branch is pushed or merged according to the active branch strategy.
- The normal MCP path for Codex is `server_daemon_client.py` backed by one healthy `engramd`.
- `memory_protocol()` and docs describe the same current tool surface, stability tiers, and daemon/client split.
- EKC `query_knowledge` has an eval pack that covers project, source, document, review, audit, graph, and artifact-family workflows.
- Document intake can go from local source to review packet to ledgered evidence to explicit reviewed promotion without hidden writes or reviewer-blinding truncation.
- Review/promotion queues are inspectable from MCP and the WebUI without parallel state stores.
- New Memory OS work does not import or extend legacy `core.memory_manager` directly.
- Codebase mapping includes daemon, Memory OS, document, graph, backend, source, WebUI, reliability, MCP, and legacy-adapter domains, with source-drift checks.
- Backend status is truthful: either Memory OS LanceDB/Kuzu are the daemon-owned live path with recovery gates, or legacy direct-mode Chroma/JSON is clearly labeled compatibility only.
- The Full 1.0 Release Gate in `docs/RELEASE_GATES.md` passes from a clean worktree.
- A final Engram memory records the final commit, validation commands, known deferrals, and the next safe cross-project workflow.

## Explicit Non-Goals

- No hosted tenant isolation, billing, sync, marketplace, team collaboration, comments, assignments, rich pages, or shared hosted MCP gateway.
- No live backend switch just because an optional dependency imports.
- No broad rewrite of `server.py` in one commit.
- No new autonomous document analysis engine inside Engram. Connected agents and external OCR/vision tools provide synthesis; Engram validates, records, cites, audits, and promotes reviewed evidence.
- No removal of legacy JSON/Chroma until a migration, recovery, and rollback path is proven.

## File Responsibilities

- `docs/RELEASE_GATES.md`: Executable local readiness gates and final release criteria.
- `docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md`: Binding architecture truth for daemon-owned Memory OS.
- `docs/ENGRAM_CURRENT_STATUS.md`: New short status page that says what is stable, beta, legacy, and deferred.
- `plan.md`: Human-facing roadmap cleanup; remove or close stale checkboxes.
- `server.py`: Direct/full MCP compatibility entrypoint; should shrink only behind tests.
- `server_daemon_client.py`: Thin default MCP entrypoint for Codex and other multi-session agents.
- `core/mcp/tool_registry.py`: Single source of truth for tool groups, canonical tool descriptions, stability, and cost classes.
- `core/legacy/memory_manager_adapter.py`: Explicit boundary for legacy JSON/Chroma calls needed by direct mode and migration.
- `core/memory_os/runtime.py`: Daemon-owned Memory OS operations, EKC routing, promotion execution, and artifact/materialization entrypoints.
- `core/document_intelligence.py`: Provider-neutral document evidence, drafts, and promotion transaction preparation.
- `core/document_intake_workflow.py`: End-to-end no-write document intake review packet assembly.
- `core/memory_os/document_artifacts.py`: Explicit ledgered document evidence artifact preparation and storage.
- `core/memory_os/document_promotion.py`: New reviewed document promotion executor for accepted memory and graph operations.
- `core/memory_os/knowledge_eval.py`: EKC eval scenarios and pass/fail summary.
- `core/codebase_mapper.py`: Agent-facing mapping config/context/result flow.
- `webui.py`: Local inspector and review UI, still fail-closed for exposed hosts.
- `tests/architecture/`: Import-boundary and server-split guardrails.
- `tests/mcp/`: No-write and protocol contract checks.
- `tests/memory_os/`: Runtime, EKC, document artifact, promotion, mapping, and inspector tests.
- `tests/webui/`: Inspector/review UI route and auth tests.

## Execution Rules

- Execute one slice at a time.
- Start each slice with focused failing tests.
- Commit every slice after focused tests and the relevant release gate pass.
- After every committed slice, write an Engram memory with slice id, commit hash, files changed, validation commands, and next step.
- If Engram write is unavailable, append the memory entry to `docs/ENGRAM_MEMORY_FALLBACK_2026_05_14.md` and retry Engram at the start of the next slice.
- Run `engramd.py --doctor` and `engramd.py --smoke-test` sequentially, not in parallel.

---

## Slice 0: Publish Current Hardening Commit And Capture Baseline

**Goal:** Start from a shared, recoverable branch state before more stabilization work.

**Files:**
- Create: `docs/architecture/ENGRAM_FINAL_STABILIZATION_BASELINE.md`

- [ ] **Step 1: Confirm branch state**

Run:

```powershell
git status --short --branch
git log -5 --oneline
```

Expected:

```text
## codex/ekc-v0-contract...origin/codex/ekc-v0-contract [ahead 1]
e7d1196c fix: harden document intake artifacts
```

If the branch shape differs, record the actual branch state in the baseline and stop before pushing or merging.

- [ ] **Step 2: Push the current branch**

Run:

```powershell
git push origin codex/ekc-v0-contract
```

Expected: branch pushes without rejected refs. If rejected, run `git fetch origin`, inspect divergence with `git log --oneline --decorate --graph --left-right origin/codex/ekc-v0-contract...HEAD`, and resolve explicitly.

- [ ] **Step 3: Run baseline release gates**

Run:

```powershell
.\venv\Scripts\python.exe server.py --help
.\venv\Scripts\python.exe -c "from core.memory_manager import memory_manager; print('ok')"
.\venv\Scripts\python.exe engramd.py --doctor
.\venv\Scripts\python.exe engramd.py --smoke-test
.\venv\Scripts\python.exe -m pytest tests\architecture tests\test_server_daemon_client_entrypoint.py tests\policy tests\mcp\test_no_write_tool_contracts.py tests\backend_gates -q
.\venv\Scripts\python.exe -m pytest -q
git diff --check
```

Expected: all commands exit 0. Record exact pass counts.

- [ ] **Step 4: Write the baseline document**

Create `docs/architecture/ENGRAM_FINAL_STABILIZATION_BASELINE.md`:

```markdown
# Engram Final Stabilization Baseline

Date: 2026-05-14
Branch:
Commit:
Remote status:

## Validation

| Command | Result |
|---|---|
| `.\venv\Scripts\python.exe server.py --help` |  |
| `.\venv\Scripts\python.exe -c "from core.memory_manager import memory_manager; print('ok')"` |  |
| `.\venv\Scripts\python.exe engramd.py --doctor` |  |
| `.\venv\Scripts\python.exe engramd.py --smoke-test` |  |
| `.\venv\Scripts\python.exe -m pytest tests\architecture tests\test_server_daemon_client_entrypoint.py tests\policy tests\mcp\test_no_write_tool_contracts.py tests\backend_gates -q` |  |
| `.\venv\Scripts\python.exe -m pytest -q` |  |
| `git diff --check` |  |

## Known Stabilization Targets

- Review and promotion ergonomics.
- Protocol metadata registry.
- Legacy adapter boundary.
- Codebase mapping drift hardening.
- WebUI inspector/review ergonomics.
- Backend truth and release docs alignment.
```

Fill in actual branch, commit, remote status, and command results from Steps 1-3.

- [ ] **Step 5: Commit and store progress**

Run:

```powershell
git add docs/architecture/ENGRAM_FINAL_STABILIZATION_BASELINE.md
git commit -m "docs: record final stabilization baseline"
```

Write Engram memory key: `engram_final_stabilization_slice_0_baseline_2026_05_14`.

---

## Slice 1: Runtime Truth And Documentation Drift Cleanup

**Goal:** Make docs, plan, protocol, and current runtime state tell one story.

**Files:**
- Create: `docs/ENGRAM_CURRENT_STATUS.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `plan.md`
- Modify: `docs/RELEASE_GATES.md`
- Modify: `docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md`
- Modify: `tests/release/test_release_gate_docs.py`
- Create: `tests/release/test_current_status_docs.py`

- [ ] **Step 1: Add failing status-doc tests**

Create `tests/release/test_current_status_docs.py` with checks that:

- `docs/ENGRAM_CURRENT_STATUS.md` exists.
- It contains sections named `Stable`, `Beta`, `Legacy Compatibility`, `Deferred`.
- It mentions `server_daemon_client.py`, `engramd`, `query_knowledge`, `document intake`, `legacy JSON/Chroma`, and `hosted scope`.
- It does not contain placeholder markers or unresolved future-work language.

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\release\test_current_status_docs.py -q
```

Expected: fails because the new status doc does not exist.

- [ ] **Step 2: Create the current status document**

Create `docs/ENGRAM_CURRENT_STATUS.md` with:

```markdown
# Engram Current Status

Date: 2026-05-14

## Stable

- Thin daemon-client MCP entrypoint: `server_daemon_client.py`.
- Local daemon owner: `engramd` on loopback.
- Core retrieval and explicit memory writes through daemon-owned runtime.
- EKC `query_knowledge` read-only serving contract on the compatibility `engram.knowledge.*.v0` envelope.

## Beta

- Document intake and intelligence review flow.
- Ledgered document evidence artifacts.
- Review-preparation, evidence-audit, graph-evidence, and artifact-family EKC packets.
- Agent workflow helpers, usage estimates, operation receipts, codebase mapping, backend readiness reports.

## Legacy Compatibility

- Direct `server.py` mode.
- `core.memory_manager`.
- Legacy JSON memories and Chroma index.
- Legacy JSON graph storage where still needed for compatibility and migration evidence.

## Deferred

- Hosted auth, tenant isolation, billing, sync, marketplace, comments, assignments, and rich team workflow UI.
- Live backend switching unless recovery, parity, and operator documentation gates pass.
- Autonomous document analysis inside Engram.

## Operating Rule

Use the thin daemon-client path for ordinary Codex work. Use direct `server.py`
only for deliberate compatibility debugging, local self-tests, or migration work.
```

- [ ] **Step 3: Close stale roadmap checkboxes or move them to status**

In `plan.md`, close the dangling v0.4 AGENTS-template checkbox only if AGENTS and README already contain the forward-slash key and size guidance. If the guidance is missing, add it to AGENTS and README in this slice, then mark the checkbox complete with a short note.

- [ ] **Step 4: Mark historical backend/audit docs as historical**

Ensure historical docs that mention old live runtime status contain a top note pointing to `docs/ENGRAM_CURRENT_STATUS.md` and `docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md` as current truth.

- [ ] **Step 5: Verify**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\release\test_current_status_docs.py tests\release\test_release_gate_docs.py -q
rg -n "Engram Current Status|Stable|Beta|Legacy Compatibility|Deferred" docs\ENGRAM_CURRENT_STATUS.md
git diff --check
```

Expected: tests pass, `rg` finds the current status sections, whitespace check exits 0.

- [ ] **Step 6: Commit and store progress**

Run:

```powershell
git add docs/ENGRAM_CURRENT_STATUS.md README.md AGENTS.md plan.md docs/RELEASE_GATES.md docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md tests/release/test_current_status_docs.py tests/release/test_release_gate_docs.py
git commit -m "docs: align Engram current status"
```

Write Engram memory key: `engram_final_stabilization_slice_1_status_2026_05_14`.

---

## Slice 2: EKC Final Eval Pack And Protocol Truth

**Goal:** Make EKC stability evidence executable instead of implied by unit coverage.

**Files:**
- Modify: `core/memory_os/knowledge_eval.py`
- Modify: `core/memory_os/runtime.py`
- Modify: `server.py`
- Modify: `server_daemon_client.py`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `tests/memory_os/test_knowledge_eval.py`
- Modify: `tests/test_agent_protocol_tools.py`

- [ ] **Step 1: Add failing eval coverage tests**

Extend `tests/memory_os/test_knowledge_eval.py` to assert the eval scenario ids include:

```python
{
    "project_orientation",
    "source_orientation",
    "document_orientation",
    "review_preparation",
    "evidence_audit",
    "graph_evidence",
    "entity_profile",
    "decision_packet",
    "implementation_context",
    "evidence_bundle",
}
```

Also assert each scenario returns:

- a valid EKC envelope,
- at least one citation when status is `ok` or `partial`,
- planner strategy matching the task type,
- no active memory writes.

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_knowledge_eval.py -q
```

Expected: fails if any workflow is not represented or lacks validation.

- [ ] **Step 2: Wire missing eval fixtures**

Update `core/memory_os/knowledge_eval.py` so every listed workflow seeds the smallest possible ledger fixture and runs through `MemoryOSRuntime.query_knowledge()`.

- [ ] **Step 3: Make protocol stability conditional on eval proof**

Update protocol docs/tests so `knowledge_contract` stays `stable` only when the eval pack covers all advertised task types. The test should fail if `server.py` or `server_daemon_client.py` advertises a task type missing from `knowledge_eval.py`.

- [ ] **Step 4: Verify**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_knowledge_eval.py tests\memory_os\test_runtime.py tests\test_agent_protocol_tools.py -q
$env:ENGRAM_DATA_DIR = Join-Path $env:TEMP ("engram-slice2-agent-eval-" + [guid]::NewGuid().ToString("N"))
.\venv\Scripts\python.exe server.py --agent-eval
$exitCode = $LASTEXITCODE
Remove-Item Env:\ENGRAM_DATA_DIR
if ($exitCode -ne 0) { exit $exitCode }
git diff --check
```

Expected: focused tests pass; isolated `server.py --agent-eval` reports all
retrieval and workflow checks passing. Use an isolated `ENGRAM_DATA_DIR` when a
live daemon owns the default Chroma store.

- [ ] **Step 5: Commit and store progress**

Run:

```powershell
git add core/memory_os/knowledge_eval.py core/memory_os/runtime.py server.py server_daemon_client.py README.md AGENTS.md docs/superpowers/plans/2026-05-14-engram-final-stabilization-plan.md tests/memory_os/test_knowledge_eval.py tests/memory_os/test_runtime.py tests/test_agent_protocol_tools.py
git commit -m "test: complete EKC final eval coverage"
```

Write Engram memory key: `engram_final_stabilization_slice_2_ekc_eval_2026_05_14`.

---

## Slice 3: Reviewed Promotion Execution

**Goal:** Close the gap between prepared document promotion operations and explicit accepted memory/graph writes.

**Files:**
- Create: `core/memory_os/document_promotion.py`
- Modify: `core/memory_os/runtime.py`
- Modify: `core/engramd_api.py`
- Modify: `core/engramd_client.py`
- Modify: `server.py`
- Modify: `server_daemon_client.py`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Create: `tests/memory_os/test_document_promotion.py`
- Modify: `tests/test_engramd_api.py`
- Modify: `tests/test_server_daemon_client.py`
- Modify: `tests/mcp/test_no_write_tool_contracts.py`

- [ ] **Step 1: Add failing promotion executor tests**

Create `tests/memory_os/test_document_promotion.py` with tests for:

- `apply_document_promotion_transaction(..., accept=False)` returns `policy_denied`.
- `apply_document_promotion_transaction(..., accept=True, approved_by="agent-review")` writes only selected operations.
- Memory writes use the existing Memory OS memory write path.
- Graph writes use the existing Memory OS graph edge path.
- Reapplying an already applied transaction returns `idempotent_replay=True` and does not duplicate records.
- Unsafe or missing operations return `schema_failed` with stable error codes.

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_document_promotion.py -q
```

Expected: fails because `core.memory_os.document_promotion` does not exist.

- [ ] **Step 2: Implement promotion executor**

Create `core/memory_os/document_promotion.py` with:

- `apply_document_promotion_transaction(ledger, runtime, document_promotion_transaction, accept, approved_by, selected_operation_indexes=None)`.
- validation that transaction `record_type == "document_promotion_transaction"`.
- validation that `approved_by` is non-empty when `accept=True`.
- validation that each operation kind is `memory` or `graph_edge`.
- idempotency keyed by transaction id and operation indexes.
- result receipts with `memories_written`, `graph_edges_written`, `write_performed`, `active_memory_write_performed`, and `graph_write_performed`.

- [ ] **Step 3: Route through daemon and MCP tools**

Expose `apply_document_promotion_transaction` through:

- `MemoryOSRuntime.apply_document_promotion_transaction`.
- `core/engramd_api.py` route `/v1/apply_document_promotion_transaction`.
- `core/engramd_client.py` client method.
- `server_daemon_client.py` FastMCP tool.
- `server.py` daemon-routed compatibility wrapper.

Tool docstrings must say this is a write tool and requires explicit acceptance.

- [ ] **Step 4: Update no-write contract tests**

Update `tests/mcp/test_no_write_tool_contracts.py` so `apply_document_promotion_transaction` is not grouped with no-write preview tools. Add an assertion that it advertises explicit write behavior and acceptance requirements.

- [ ] **Step 5: Verify**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_document_promotion.py tests/test_engramd_api.py tests/test_server_daemon_client.py tests/mcp/test_no_write_tool_contracts.py -q
.\venv\Scripts\python.exe engramd.py --smoke-test
git diff --check
```

Expected: tests pass, daemon smoke passes, whitespace check exits 0.

- [ ] **Step 6: Commit and store progress**

Run:

```powershell
git add core/memory_os/document_promotion.py core/memory_os/runtime.py core/engramd_api.py core/engramd_client.py server.py server_daemon_client.py README.md AGENTS.md tests/memory_os/test_document_promotion.py tests/test_engramd_api.py tests/test_server_daemon_client.py tests/mcp/test_no_write_tool_contracts.py
git commit -m "feat: apply reviewed document promotions"
```

Write Engram memory key: `engram_final_stabilization_slice_3_promotion_2026_05_14`.

---

## Slice 4: MCP Tool Registry And Protocol Generation

**Goal:** Stop hand-maintaining protocol metadata in multiple places.

**Files:**
- Create: `core/mcp/tool_registry.py`
- Modify: `server.py`
- Modify: `server_daemon_client.py`
- Modify: `tests/test_agent_protocol_tools.py`
- Modify: `tests/test_server_daemon_client.py`

- [ ] **Step 1: Add failing registry parity tests**

Update `tests/test_agent_protocol_tools.py` to assert:

- every canonical tool in `core.mcp.tool_registry` appears in `memory_protocol()`,
- every tool group in the registry appears in protocol output,
- direct server and thin daemon client agree on stable tool names,
- `apply_document_promotion_transaction` is marked as write/explicit acceptance if Slice 3 is complete.

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_agent_protocol_tools.py tests/test_server_daemon_client.py -q
```

Expected: fails because `core.mcp.tool_registry` does not exist or is unused.

- [ ] **Step 2: Implement registry module**

Create `core/mcp/tool_registry.py` with:

- `ToolMetadata` dataclass.
- `TOOL_GROUPS` mapping.
- `CANONICAL_TOOLS` mapping.
- `build_memory_protocol_sections(include_beta=True, thin_client=False)`.
- `validate_protocol_sections(protocol_payload)`.

- [ ] **Step 3: Replace duplicated protocol construction**

Update `server.py` and `server_daemon_client.py` to use the registry for tool groups and canonical tool descriptions while preserving product/version/retrieval-ladder narrative fields.

- [ ] **Step 4: Verify**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_agent_protocol_tools.py tests/test_server_daemon_client.py tests/test_server_daemon_client_entrypoint.py -q
.\venv\Scripts\python.exe server.py --help
git diff --check
```

Expected: tests pass; help still works; whitespace check exits 0.

- [ ] **Step 5: Commit and store progress**

Run:

```powershell
git add core/mcp/tool_registry.py server.py server_daemon_client.py tests/test_agent_protocol_tools.py tests/test_server_daemon_client.py
git commit -m "refactor: generate MCP protocol metadata"
```

Write Engram memory key: `engram_final_stabilization_slice_4_tool_registry_2026_05_14`.

---

## Slice 5: Legacy Adapter Boundary

**Goal:** Prevent new Memory OS work from leaning on `core.memory_manager` while preserving direct-mode compatibility.

**Files:**
- Create: `core/legacy/__init__.py`
- Create: `core/legacy/memory_manager_adapter.py`
- Modify: `core/memory_manager.py`
- Modify: `server.py`
- Modify: `webui.py`
- Modify: `tests/architecture/test_import_boundaries.py`
- Create: `tests/legacy/test_memory_manager_adapter.py`

- [ ] **Step 1: Add failing adapter tests**

Create `tests/legacy/test_memory_manager_adapter.py` verifying:

- adapter imports `core.memory_manager` lazily,
- adapter exposes only direct-mode compatibility functions used by `server.py` and `webui.py`,
- importing Memory OS modules does not import `core.memory_manager`.

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/legacy/test_memory_manager_adapter.py tests/architecture/test_import_boundaries.py -q
```

Expected: fails until adapter exists and import allowlist is tightened.

- [ ] **Step 2: Implement adapter**

Create `core/legacy/memory_manager_adapter.py` with lazy wrappers for:

- `get_memory_manager()`
- `search_memories_legacy(...)`
- `retrieve_memory_legacy(...)`
- `retrieve_chunk_legacy(...)`
- `store_memory_legacy(...)`
- `delete_memory_legacy(...)`

Each wrapper imports `core.memory_manager` inside the function body.

- [ ] **Step 3: Mark legacy manager clearly**

Add this module docstring at the top of `core/memory_manager.py`:

```python
"""Legacy JSON/Chroma memory manager.

Do not add new Memory OS functionality here. New daemon-owned behavior belongs
in core.memory_os services, and direct-mode compatibility should enter through
core.legacy.memory_manager_adapter.
"""
```

- [ ] **Step 4: Move safe imports to adapter**

Update `server.py` and `webui.py` where possible to import from `core.legacy.memory_manager_adapter` instead of `core.memory_manager`. Keep any direct import that is required for `server.py --self-test` compatibility on the architecture-test allowlist with a reason comment.

- [ ] **Step 5: Verify**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/legacy/test_memory_manager_adapter.py tests/architecture/test_import_boundaries.py tests/test_server_structured_tools.py tests/test_webui_security.py -q
.\venv\Scripts\python.exe server.py --self-test
git diff --check
```

Expected: tests pass, self-test passes, whitespace check exits 0.

- [ ] **Step 6: Commit and store progress**

Run:

```powershell
git add core/legacy/__init__.py core/legacy/memory_manager_adapter.py core/memory_manager.py server.py webui.py tests/architecture/test_import_boundaries.py tests/legacy/test_memory_manager_adapter.py
git commit -m "refactor: isolate legacy memory manager access"
```

Write Engram memory key: `engram_final_stabilization_slice_5_legacy_adapter_2026_05_14`.

---

## Slice 6: Focused Server Handler Split

**Goal:** Reduce `server.py` risk without changing payload shape or tool names.

**Files:**
- Create: `core/mcp/document_tools.py`
- Create: `core/mcp/knowledge_tools.py`
- Create: `core/mcp/backend_tools.py`
- Modify: `server.py`
- Modify: `tests/architecture/test_import_boundaries.py`
- Modify: `tests/test_server_structured_tools.py`
- Modify: `tests/test_agent_protocol_tools.py`

- [ ] **Step 1: Add handler parity tests**

Add tests that call representative direct `server.py` tools before and after extraction:

- `prepare_document_intake_review`
- `prepare_document_artifact_store`
- `query_knowledge`
- `retrieval_backend_status`
- `graph_backend_status`

Use existing fake/runtime test patterns and assert response shapes are unchanged.

- [ ] **Step 2: Extract document tool implementation**

Move document helper bodies from `server.py` into `core/mcp/document_tools.py` as plain functions that accept explicit dependencies. Keep FastMCP decorators in `server.py`.

- [ ] **Step 3: Extract EKC and backend tool implementation**

Move query-knowledge runtime error helpers and backend status wrappers into `core/mcp/knowledge_tools.py` and `core/mcp/backend_tools.py`. Keep public tool names and docstrings stable.

- [ ] **Step 4: Verify**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_server_structured_tools.py tests/test_agent_protocol_tools.py tests/architecture/test_import_boundaries.py -q
.\venv\Scripts\python.exe server.py --help
git diff --check
```

Expected: tests pass, help works, whitespace check exits 0.

- [ ] **Step 5: Commit and store progress**

Run:

```powershell
git add core/mcp/document_tools.py core/mcp/knowledge_tools.py core/mcp/backend_tools.py server.py tests/architecture/test_import_boundaries.py tests/test_server_structured_tools.py tests/test_agent_protocol_tools.py
git commit -m "refactor: split focused MCP tool handlers"
```

Write Engram memory key: `engram_final_stabilization_slice_6_server_split_2026_05_14`.

---

## Slice 7: Codebase Mapping Drift Hardening

**Goal:** Make codebase mapping reliable enough for cross-project use.

**Files:**
- Modify: `core/codebase_mapper.py`
- Modify: `server.py`
- Modify: `server_daemon_client.py` if codebase mapping is advertised there.
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `tests/test_codebase_mapper.py`
- Modify: `tests/test_agent_protocol_tools.py`

- [ ] **Step 1: Add failing mapping-domain tests**

Update `tests/test_codebase_mapper.py` to assert default mapping domains include:

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

Also assert large central files such as `server.py` and `core/memory_manager.py` produce warnings when excluded by size filters.

- [ ] **Step 2: Add source drift storage tests**

Add tests that:

- prepare mapping context,
- mutate a mapped file,
- attempt to store the old mapping result,
- receive a stale-source rejection unless `force=True`.

- [ ] **Step 3: Implement mapping updates**

Update `core/codebase_mapper.py` to:

- include the required domains,
- warn on excluded central files,
- persist source hashes in mapping context,
- reject stale `store_codebase_mapping_result` calls unless forced,
- honor `ENGRAM_DATA_DIR` for config/result storage.

- [ ] **Step 4: Verify**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_codebase_mapper.py tests/test_agent_protocol_tools.py -q
git diff --check
```

Expected: tests pass and whitespace check exits 0.

- [ ] **Step 5: Commit and store progress**

Run:

```powershell
git add core/codebase_mapper.py server.py server_daemon_client.py README.md AGENTS.md tests/test_codebase_mapper.py tests/test_agent_protocol_tools.py
git commit -m "feat: harden codebase mapping drift checks"
```

Write Engram memory key: `engram_final_stabilization_slice_7_mapping_2026_05_14`.

---

## Slice 8: WebUI Inspector And Review Ergonomics

**Goal:** Make local inspection and review useful without creating a parallel state system.

**Files:**
- Modify: `webui.py`
- Modify: `static/` dashboard assets if present.
- Modify: `core/memory_os/inspector.py`
- Modify: `tests/test_webui_inspector.py`
- Modify: `tests/test_webui_security.py`
- Modify: `README.md`

- [ ] **Step 1: Add failing inspector tests**

Add tests asserting WebUI inspector routes expose:

- daemon status,
- Memory OS jobs,
- document artifact transactions,
- review-preparation queue,
- promotion transactions,
- graph evidence counts,
- EKC eval summary,
- release-gate command list.

Also assert exposed-host auth protections still fail closed.

- [ ] **Step 2: Add read-only review queue endpoint**

Update `core/memory_os/inspector.py` and `webui.py` so inspector reads review queue and promotion transaction state from the Memory OS ledger. Do not create WebUI-owned review state.

- [ ] **Step 3: Add explicit promotion action route**

If Slice 3 is complete, add a write-token-protected route that calls daemon `apply_document_promotion_transaction`. It must require:

- `ENGRAM_WEBUI_WRITE_TOKEN`,
- `accept=true`,
- transaction id,
- approved-by text.

If Slice 3 is not complete, expose only the read-only prepared transaction details and a disabled action state.

- [ ] **Step 4: Verify**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_webui_inspector.py tests/test_webui_security.py -q
.\venv\Scripts\python.exe -m pytest tests/mcp/test_no_write_tool_contracts.py -q
git diff --check
```

Expected: tests pass; no-write contract still passes; whitespace check exits 0.

- [ ] **Step 5: Commit and store progress**

Run:

```powershell
git add webui.py core/memory_os/inspector.py README.md tests/test_webui_inspector.py tests/test_webui_security.py
git commit -m "feat: surface review queues in inspector"
```

Write Engram memory key: `engram_final_stabilization_slice_8_webui_review_2026_05_14`.

---

## Slice 9: Backend Truth, Recovery Gates, And Deferral Decision

**Goal:** End backend ambiguity without forcing a risky live backend swap.

**Files:**
- Modify: `core/retrieval_backend_status.py`
- Modify: `core/graph_backend_status.py`
- Modify: `core/backend_gates/`
- Modify: `docs/ENGRAM_BACKEND_EVAL_2026_05_13.md`
- Modify: `docs/ENGRAM_CURRENT_STATUS.md`
- Modify: `docs/RELEASE_GATES.md`
- Modify: `tests/backend_gates/test_retrieval_gate.py`
- Modify: `tests/backend_gates/test_graph_gate.py`
- Modify: `tests/test_retrieval_backend_status.py`
- Modify: `tests/test_graph_backend_status.py`

- [ ] **Step 1: Add backend truth tests**

Add tests that assert backend status reports distinguish:

- direct legacy live backend,
- daemon-owned Memory OS backend,
- optional candidate backend,
- blocked live-switch gate,
- missing recovery documentation,
- skipped parity as blocker.

- [ ] **Step 2: Implement clearer status payloads**

Update backend status helpers to include:

- `runtime_mode`,
- `daemon_owned`,
- `direct_mode_legacy`,
- `candidate_dependency_available`,
- `corpus_parity_status`,
- `recovery_gate_status`,
- `operator_docs_status`,
- `live_switch_decision`.

- [ ] **Step 3: Decide and document backend final state**

Set current final-state policy in docs:

```text
For local 1.0, the daemon-owned Memory OS path is the product path.
Direct JSON/Chroma remains compatibility and recovery input.
No optional backend becomes default until parity, recovery, restart, and operator docs pass.
```

- [ ] **Step 4: Verify**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/backend_gates tests/test_retrieval_backend_status.py tests/test_graph_backend_status.py -q
.\venv\Scripts\python.exe engramd.py --doctor
.\venv\Scripts\python.exe engramd.py --smoke-test
git diff --check
```

Expected: tests pass; daemon gates pass; whitespace check exits 0.

- [ ] **Step 5: Commit and store progress**

Run:

```powershell
git add core/retrieval_backend_status.py core/graph_backend_status.py core/backend_gates docs/ENGRAM_BACKEND_EVAL_2026_05_13.md docs/ENGRAM_CURRENT_STATUS.md docs/RELEASE_GATES.md tests/backend_gates tests/test_retrieval_backend_status.py tests/test_graph_backend_status.py
git commit -m "docs: clarify backend final-state gates"
```

Write Engram memory key: `engram_final_stabilization_slice_9_backend_truth_2026_05_14`.

---

## Slice 10: Final Release Candidate Gate

**Goal:** Produce a clean local release-candidate checkpoint and durable handoff.

**Files:**
- Create: `docs/ENGRAM_LOCAL_1_0_RELEASE_CANDIDATE.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/RELEASE_GATES.md`
- Modify: `docs/ENGRAM_CURRENT_STATUS.md`

- [ ] **Step 1: Run full release gates**

Run sequentially:

```powershell
.\venv\Scripts\python.exe server.py --help
.\venv\Scripts\python.exe -c "from core.memory_manager import memory_manager; print('ok')"
.\venv\Scripts\python.exe engramd.py --doctor
.\venv\Scripts\python.exe engramd.py --smoke-test
$previous = $env:ENGRAM_DATA_DIR
$env:ENGRAM_DATA_DIR = Join-Path $env:TEMP ("engram-self-test-" + [guid]::NewGuid().ToString("N"))
.\venv\Scripts\python.exe server.py --self-test
if ($null -eq $previous) { Remove-Item Env:\ENGRAM_DATA_DIR -ErrorAction SilentlyContinue } else { $env:ENGRAM_DATA_DIR = $previous }
$previous = $env:ENGRAM_DATA_DIR
$env:ENGRAM_DATA_DIR = Join-Path $env:TEMP ("engram-agent-eval-" + [guid]::NewGuid().ToString("N"))
.\venv\Scripts\python.exe server.py --agent-eval
if ($null -eq $previous) { Remove-Item Env:\ENGRAM_DATA_DIR -ErrorAction SilentlyContinue } else { $env:ENGRAM_DATA_DIR = $previous }
.\venv\Scripts\python.exe -m pytest -q
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 2: Write release candidate document**

Create `docs/ENGRAM_LOCAL_1_0_RELEASE_CANDIDATE.md`:

```markdown
# Engram Local 1.0 Release Candidate

Date:
Branch:
Commit:

## What Is Stable

- Thin daemon-client MCP path.
- Daemon-owned Memory OS runtime.
- EKC read-only contract.
- Document intake review and ledgered evidence flow.
- Explicit reviewed promotion flow.
- Inspector review queue.
- Codebase mapping with source drift checks.

## What Remains Deferred

- Hosted product features.
- Optional backend live switch.
- Autonomous document analysis.
- Full removal of legacy JSON/Chroma compatibility.

## Validation

| Command | Result |
|---|---|
| `server.py --help` |  |
| `memory_manager import` |  |
| `engramd.py --doctor` |  |
| `engramd.py --smoke-test` |  |
| isolated `server.py --self-test` |  |
| isolated `server.py --agent-eval` |  |
| `pytest -q` |  |
| `git diff --check` |  |

## How To Use Engram From Other Projects

1. Keep `engramd` running on loopback.
2. Use `server_daemon_client.py` as the Codex MCP entrypoint.
3. Start with `memory_protocol()`.
4. Use `search_memories`, `read_chunk`, and `query_knowledge` before full memory reads.
5. Use document intake review tools for large source material; promote only after review.
```

- [ ] **Step 3: Update top-level docs**

Update README and AGENTS to point to the release-candidate doc and current status doc.

- [ ] **Step 4: Verify docs**

Run:

```powershell
rg -n "ENGRAM_LOCAL_1_0_RELEASE_CANDIDATE|ENGRAM_CURRENT_STATUS|server_daemon_client.py" README.md AGENTS.md docs\ENGRAM_LOCAL_1_0_RELEASE_CANDIDATE.md docs\ENGRAM_CURRENT_STATUS.md
.\venv\Scripts\python.exe -m pytest tests\release -q
git diff --check
```

Expected: docs are linked, release tests pass, whitespace check exits 0.

- [ ] **Step 5: Commit, push, and store final memory**

Run:

```powershell
git add docs/ENGRAM_LOCAL_1_0_RELEASE_CANDIDATE.md README.md AGENTS.md docs/RELEASE_GATES.md docs/ENGRAM_CURRENT_STATUS.md
git commit -m "docs: mark Engram local release candidate"
git push origin codex/ekc-v0-contract
```

Write Engram memory key: `engram_local_1_0_release_candidate_2026_05_14`.

---

## Recommended Execution Order

Run slices in this order:

1. Slice 0: publish and baseline.
2. Slice 1: current truth docs.
3. Slice 2: EKC final eval pack.
4. Slice 3: reviewed promotion execution.
5. Slice 4: tool registry.
6. Slice 5: legacy adapter boundary.
7. Slice 6: focused server split.
8. Slice 7: codebase mapping hardening.
9. Slice 8: WebUI review ergonomics.
10. Slice 9: backend truth and deferral decision.
11. Slice 10: release candidate gate.

The shortest credible path is Slices 0-5, 9, and 10. Slices 6-8 are still important, but Slices 0-5 plus 9-10 produce the biggest reliability gain for returning to other projects.

## Stop Conditions

Stop and ask for user intervention if:

- pushing the branch is rejected due to remote divergence,
- daemon doctor reports more than one real daemon owner after an isolated rerun,
- full pytest fails outside the touched slice,
- a promotion executor requires changing existing memory/graph storage semantics beyond explicit reviewed writes,
- backend status proves live runtime behavior contradicts `AGENTS.md` or `docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md`,
- WebUI review actions would require weakening exposed-host auth.

## Final Validation Bundle

Before saying Engram is ready to be depended on across projects, run:

```powershell
git status --short --branch
.\venv\Scripts\python.exe server.py --help
.\venv\Scripts\python.exe -c "from core.memory_manager import memory_manager; print('ok')"
.\venv\Scripts\python.exe engramd.py --doctor
.\venv\Scripts\python.exe engramd.py --smoke-test
.\venv\Scripts\python.exe server.py --agent-eval
.\venv\Scripts\python.exe -m pytest tests\architecture tests\mcp tests\policy tests\backend_gates tests\release -q
.\venv\Scripts\python.exe -m pytest -q
git diff --check
```

Expected:

- clean or intentionally documented git status,
- one daemon plus one launcher on Windows,
- no process hygiene warnings,
- daemon smoke store/search/read/delete passes,
- agent eval passes retrieval, workflow, EKC, and book/document gates,
- full pytest passes,
- current status and release-candidate docs are accurate.

## Self-Review

- Spec coverage: The plan covers branch publication, truth/docs drift, EKC evals, document promotion, MCP protocol metadata, legacy boundary, server split, codebase mapping, WebUI review, backend final-state truth, and release-candidate validation.
- Placeholder scan: The plan avoids unresolved future-work markers. Deferred scope is explicitly named in Non-Goals and release-candidate docs.
- Type consistency: Tool names are consistent: `query_knowledge`, `prepare_document_intake_review`, `prepare_document_artifact_store`, `store_document_artifact`, `prepare_document_promotion_transaction`, and proposed `apply_document_promotion_transaction`.
- Risk check: The plan does not remove legacy storage, switch backends, or weaken WebUI auth. It adds acceptance gates before write paths and keeps no-write review tools separate from promotion tools.
