# Engram Knowledge Contract v1 Roadmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move EKC from the completed v0 project-orientation serving contract toward a stable 1.0 knowledge contract through proven, evidence-first vertical slices.

**Architecture:** Keep `query_knowledge` read-only and daemon-owned. Add explicit artifact materialization, stronger citation/planner receipts, then source/document orientation, review preparation, evidence audit, bounded graph evidence, and only then higher-level artifact families. Every slice has focused tests, validation, a commit, and an Engram progress memory.

**Tech Stack:** Python 3.12, FastMCP, daemon-owned `MemoryOSRuntime`, SQLite JSON-record ledger, content-addressed store, LanceDB-backed retrieval, Kuzu/GraphStore-backed graph records, pytest.

---

## File Responsibilities

- `core/memory_os/knowledge_artifacts.py`: Persist and read ledgered EKC artifact records with content-addressed JSON payloads.
- `core/memory_os/knowledge_citations.py`: Normalize artifact, chunk, document, and graph citations into one EKC citation contract.
- `core/memory_os/knowledge_planner.py`: Build accountable planner receipts, omissions, budget receipts, and failure receipts.
- `core/memory_os/knowledge_orientations.py`: Build project, source, and document orientation packets without inventing unsupported facts.
- `core/memory_os/knowledge_review.py`: Build review-preparation packets over drafts, quality warnings, and candidate promotions.
- `core/memory_os/knowledge_audit.py`: Report grounding gaps, stale refs, weak claims, and evidence coverage status.
- `core/memory_os/knowledge_graph.py`: Return bounded graph evidence paths and contradiction summaries with citations.
- `core/memory_os/runtime.py`: Route EKC runtime methods and keep `query_knowledge` read-only.
- `core/engramd_api.py`, `core/engramd_client.py`, `server_daemon_client.py`, `server.py`: Expose only proven daemon-owned EKC surfaces.
- `tests/memory_os/test_knowledge_*.py`: Focused red-green tests per EKC slice.
- `docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md`, `README.md`, `AGENTS.md`, `plan.md`: Keep agent-facing docs aligned with implemented behavior.
- `docs/ENGRAM_MEMORY_FALLBACK_2026_05_14.md`: Append progress memories only if Engram MCP writes are unavailable.

## Progress Memory Rule

After every committed slice, write an Engram memory with:

- slice id and final commit
- files changed
- validation commands and pass/fail outcome
- current production readiness
- next recommended slice

If Engram MCP writes fail, append the same entry to `docs/ENGRAM_MEMORY_FALLBACK_2026_05_14.md`, commit that fallback doc with the slice only if it becomes the durable record, and retry Engram at the start of the next slice.

## Slice 0: Executable Roadmap Plan

**Files:**
- Create: `docs/superpowers/plans/2026-05-14-engram-knowledge-contract-v1-roadmap-plan.md`

- [ ] **Step 1: Save this executable roadmap**

Create this document with the slice sequence and validation rules.

- [ ] **Step 2: Verify plan discoverability**

Run:

```powershell
rg -n "Slice 1|Slice 8|query_knowledge|evidence audit|bounded graph" docs\superpowers\plans\2026-05-14-engram-knowledge-contract-v1-roadmap-plan.md
git diff --check
```

Expected: roadmap terms are discoverable and `git diff --check` exits 0.

- [ ] **Step 3: Commit**

Run:

```powershell
git add docs/superpowers/plans/2026-05-14-engram-knowledge-contract-v1-roadmap-plan.md
git commit -m "docs: add EKC v1 roadmap execution plan"
```

## Slice 1: v0.2 Persisted Project Capsule Artifacts

**Goal:** Add explicit ledgered project capsule artifacts while keeping `query_knowledge` read-only.

**Files:**
- Modify: `core/memory_os/schema.py`
- Create: `core/memory_os/knowledge_artifacts.py`
- Modify: `core/memory_os/runtime.py`
- Modify: `tests/memory_os/test_runtime.py`
- Create: `tests/memory_os/test_knowledge_artifacts.py`

- [ ] **Step 1: Write failing artifact-store tests**

Add tests that persist a `project_capsule` artifact, read it back by id, read the latest by project/type, and prove the JSON payload is stored in the content-addressed store.

- [ ] **Step 2: Verify red**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_knowledge_artifacts.py -q
```

Expected: fails because `core.memory_os.knowledge_artifacts` does not exist.

- [ ] **Step 3: Implement `KnowledgeArtifactStore`**

Add a `knowledge_artifacts` ledger table, content-addressed JSON writes, `store_artifact()`, `read_artifact()`, and `read_latest_artifact()` helpers. Artifact records must include `artifact_id`, `artifact_type`, `artifact_version`, `project`, `content_artifact_id`, `source_refs`, `created_at`, `updated_at`, and `staleness`.

- [ ] **Step 4: Add explicit runtime materialization**

Add `MemoryOSRuntime.materialize_project_capsule_artifact(request)` that normalizes the EKC request, builds the existing project capsule artifact, stores it through `KnowledgeArtifactStore`, and records a transaction with `operation_kind="materialize_knowledge_artifact"`.

- [ ] **Step 5: Make `query_knowledge` read persisted artifacts**

Update `MemoryOSRuntime.query_knowledge()` so it reads the latest fresh persisted `project_capsule` for the project before building an ephemeral capsule. Persisted responses must report `artifacts_read=1`, `artifacts_built=0`, and include artifact-level plus chunk citations. Ephemeral responses must keep `artifacts_built=1`, `artifacts_read=0`.

- [ ] **Step 6: Verify**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_knowledge_artifacts.py tests\memory_os\test_runtime.py tests\memory_os\test_knowledge_contract.py -q
git diff --check
```

Expected: all tests pass and whitespace check exits 0.

- [ ] **Step 7: Commit and store progress memory**

Run:

```powershell
git add core/memory_os/schema.py core/memory_os/knowledge_artifacts.py core/memory_os/runtime.py tests/memory_os/test_knowledge_artifacts.py tests/memory_os/test_runtime.py
git commit -m "feat: persist knowledge project capsules"
```

Then write the slice memory to Engram or fallback doc.

## Slice 2: v0.3 Citation Contract Hardening

**Goal:** Make EKC citations explicit, validated, and usable across artifact and chunk evidence.

**Files:**
- Create: `core/memory_os/knowledge_citations.py`
- Modify: `core/memory_os/project_capsule_artifact.py`
- Modify: `core/memory_os/knowledge_contract.py`
- Modify: `tests/memory_os/test_project_capsule_artifact.py`
- Modify: `tests/memory_os/test_knowledge_contract.py`

- [ ] **Step 1: Add tests for artifact and chunk citation normalization**
- [ ] **Step 2: Implement citation normalization with required `citation_id`, `level`, `source`, and ref fields**
- [ ] **Step 3: Enforce citation envelope validation in `validate_knowledge_response()`**
- [ ] **Step 4: Verify focused citation and contract tests**
- [ ] **Step 5: Commit and store progress memory**

## Slice 3: v0.4 Accountable Planner Receipts

**Goal:** Replace ad hoc planner payloads with explicit strategy, omissions, budget, and failure receipts.

**Files:**
- Create: `core/memory_os/knowledge_planner.py`
- Modify: `core/memory_os/runtime.py`
- Modify: `core/memory_os/knowledge_contract.py`
- Create: `tests/memory_os/test_knowledge_planner.py`
- Modify: `tests/memory_os/test_runtime.py`

- [ ] **Step 1: Add tests for ok, partial, no_answer, unavailable planner receipts**
- [ ] **Step 2: Implement planner receipt helpers**
- [ ] **Step 3: Route `query_knowledge` through the planner helper**
- [ ] **Step 4: Verify planner/runtime tests**
- [ ] **Step 5: Commit and store progress memory**

## Slice 4: v0.5 Source and Document Orientation

**Goal:** Add source/document orientation before generic artifact families.

**Files:**
- Create: `core/memory_os/knowledge_orientations.py`
- Modify: `core/memory_os/knowledge_contract.py`
- Modify: `core/memory_os/runtime.py`
- Create: `tests/memory_os/test_knowledge_orientations.py`

- [ ] **Step 1: Add tests for `source_orientation` and `document_orientation` requests**
- [ ] **Step 2: Implement source/document orientation over existing ledger source, document, chunk, and retrieval receipt records**
- [ ] **Step 3: Ensure missing evidence returns `partial` or `no_answer`, never invented facts**
- [ ] **Step 4: Verify focused orientation tests**
- [ ] **Step 5: Commit and store progress memory**

## Slice 5: v0.6 Review-Preparation Packets

**Goal:** Prepare review packets for candidate promotions and quality warnings without promoting memory.

**Files:**
- Create: `core/memory_os/knowledge_review.py`
- Modify: `core/memory_os/knowledge_contract.py`
- Modify: `core/memory_os/runtime.py`
- Create: `tests/memory_os/test_knowledge_review.py`

- [ ] **Step 1: Add tests for review-preparation packets over drafts and document quality warnings**
- [ ] **Step 2: Implement read-only packet assembly from `drafts`, `retrieval_receipts`, and document records**
- [ ] **Step 3: Verify no active memory writes occur**
- [ ] **Step 4: Commit and store progress memory**

## Slice 6: v0.7 Evidence Audit

**Goal:** Report grounding gaps, stale refs, weak claims, and coverage risk.

**Files:**
- Create: `core/memory_os/knowledge_audit.py`
- Modify: `core/memory_os/runtime.py`
- Create: `tests/memory_os/test_knowledge_audit.py`

- [ ] **Step 1: Add tests for stale refs, missing citations, weak claims, and low coverage**
- [ ] **Step 2: Implement deterministic audit signals over artifacts, citations, retrieval receipts, and graph proposals**
- [ ] **Step 3: Ensure audit responses are read-only and cite inspected records**
- [ ] **Step 4: Commit and store progress memory**

## Slice 7: v0.8 Bounded Graph Evidence and Contradictions

**Goal:** Surface bounded graph evidence paths and contradiction edges with citations.

**Files:**
- Create: `core/memory_os/knowledge_graph.py`
- Modify: `core/memory_os/runtime.py`
- Create: `tests/memory_os/test_knowledge_graph.py`

- [ ] **Step 1: Add tests for bounded path limits, contradiction edges, and cited graph evidence**
- [ ] **Step 2: Implement graph evidence summarization without loading neighbor memory bodies by default**
- [ ] **Step 3: Ensure contradictions are surfaced as warnings or partial status when relevant**
- [ ] **Step 4: Commit and store progress memory**

## Slice 8: v0.9 Higher-Level Artifact Families

**Goal:** Add entity profiles, decision packets, implementation-context artifacts, and richer evidence bundles only after slices 4-7 are green.

**Files:**
- Extend: `core/memory_os/knowledge_artifacts.py`
- Extend: `core/memory_os/knowledge_orientations.py`
- Extend: `tests/memory_os/test_knowledge_artifacts.py`

- [ ] **Step 1: Add tests proving artifact families are gated behind available evidence**
- [ ] **Step 2: Implement `entity_profile`, `decision_packet`, `implementation_context`, and `evidence_bundle` records**
- [ ] **Step 3: Ensure every family carries citations and evidence audit status**
- [ ] **Step 4: Commit and store progress memory**

## Slice 9: v1.0 Stable Contract and Eval Pack

**Goal:** Mark EKC stable only after project, source/document, review-prep, evidence audit, and bounded graph evals pass.

**Files:**
- Extend: `core/memory_os/knowledge_eval.py`
- Modify: `server.py`
- Modify: `server_daemon_client.py`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md`

- [ ] **Step 1: Add eval scenarios for all proven EKC workflows**
- [ ] **Step 2: Keep protocol stability beta until all evals pass**
- [ ] **Step 3: Promote docs to EKC 1.0 only when full eval pack passes**
- [ ] **Step 4: Run completion gates and full pytest**
- [ ] **Step 5: Commit and store final closeout memory**

## Validation Cadence

Every slice must run its focused tests, `git diff --check`, commit, and write progress memory. Before final closeout run:

```powershell
.\venv\Scripts\python.exe server.py --help
.\venv\Scripts\python.exe -c "from core.memory_manager import memory_manager; print('ok')"
.\venv\Scripts\python.exe engramd.py --doctor
.\venv\Scripts\python.exe engramd.py --smoke-test
$env:ENGRAM_DATA_DIR = Join-Path $env:TEMP ("engram-ekc-v1-self-test-" + [guid]::NewGuid())
Remove-Item Env:\ENGRAM_DAEMON_URL -ErrorAction SilentlyContinue
.\venv\Scripts\python.exe server.py --self-test
$env:ENGRAM_DATA_DIR = Join-Path $env:TEMP ("engram-ekc-v1-agent-eval-" + [guid]::NewGuid())
Remove-Item Env:\ENGRAM_DAEMON_URL -ErrorAction SilentlyContinue
.\venv\Scripts\python.exe server.py --agent-eval
.\venv\Scripts\python.exe -m pytest -q
git diff --check
```

## Self-Review

- Spec coverage: Slices 1-3 finish the v0-v0.4 foundation. Slices 4-7 implement the required evidence-first ladder before generic artifact families. Slice 8 introduces higher-level artifacts only after that ladder. Slice 9 covers stable eval and docs.
- Placeholder scan: This plan contains no `TBD`, `TODO`, or unspecified file paths.
- Type consistency: The plan consistently uses `query_knowledge`, EKC artifact records, project/source/document orientation, review-preparation, evidence audit, bounded graph evidence, and citation-bearing responses.
