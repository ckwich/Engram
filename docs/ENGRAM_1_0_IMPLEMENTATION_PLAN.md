# Engram 1.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish Engram 1.0 as a stable public, generic, local-first agent memory substrate.

**Architecture:** Keep JSON memories authoritative, ChromaDB rebuildable, graph/source/codebase mapping seams explicit, and MCP tools discoverable through `memory_protocol()`. The collaboration product remains separate and consumes Engram through adapters instead of adding team-workspace features here.

**Tech Stack:** Python 3.10+, FastMCP, ChromaDB, sentence-transformers, Flask, pytest, local JSON files.

---

## File Responsibilities

- `server.py`: MCP tool definitions, docstrings, protocol contract, CLI/operator gates.
- `core/memory_manager.py`: JSON-first memory writes, Chroma indexing, retrieval, import/export, metadata repair.
- `core/graph_manager.py` and `core/graph_store.py`: graph edge validation, traversal evidence, backend seam.
- `core/source_intake.py`, `core/source_connectors.py`, `core/ingestion_pipelines.py`, `core/chunk_preview.py`: no-write previews, source drafts, explicit promotion.
- `core/reliability_harness.py`, `core/retrieval_eval.py`: deterministic retrieval and agent-quality gates.
- `webui.py`, `templates/index.html`, `static/app.js`: local review/operations dashboard; no business collaboration layer.
- `README.md`, `AGENTS.md`, `plan.md`, `docs/*.md`: public docs, release instructions, agent contracts, and product-boundary records.

## Task 1: Contract Freeze and Version Identity

**Files:**
- Modify: `server.py`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/ENGRAM_1_0_RELEASE_SPEC.md`
- Create: `docs/ENGRAM_1_0_MCP_CONTRACT.md`
- Test: `tests/test_agent_protocol_tools.py`, `tests/test_cli_config.py`, `tests/test_server_structured_tools.py`

- [x] Inventory every MCP tool and alias from `memory_protocol()` and `server.py`.
- [x] Decide the product version string for the 1.0 release and keep it separate from protocol schema version.
- [x] Replace stale user-facing legacy version strings with the chosen release identity.
- [x] Verify tool docstrings match real behavior for retrieval, writing, source intake, graph, codebase mapping, usage, operations, and eval tools.
- [x] Add or update focused tests for alias behavior where gaps are found.
- [x] Run:

```powershell
.\venv\Scripts\python.exe server.py --help
.\venv\Scripts\python.exe -m pytest tests/test_server_structured_tools.py -q
.\venv\Scripts\python.exe server.py --agent-eval
```

- [x] Commit with a message like `docs: freeze 1.0 MCP contract`.

## Task 2: Storage, Rebuild, and Repair Proof

**Files:**
- Modify: `core/memory_manager.py`
- Modify: `tests/test_storage_invariants.py`, `tests/conftest.py`
- Modify: `docs/ENGRAM_1_0_RELEASE_SPEC.md`
- Create or modify: `docs/ENGRAM_1_0_RELEASE_CHECKLIST.md`

- [x] Trace every write path and confirm JSON is written before Chroma indexing.
- [x] Confirm Chroma rebuild from JSON restores searchable chunks.
- [x] Confirm import/export preserves required metadata and chunk references.
- [x] Confirm metadata repair is dry-run by default and backup-safe before writes.
- [x] Confirm graph audit detects malformed edges without loading neighbor memory bodies.
- [x] Document exact operator commands in the release checklist.
- [x] Run:

```powershell
.\venv\Scripts\python.exe server.py --self-test
.\venv\Scripts\python.exe -m pytest -q
git diff --check
```

- [x] Commit with a message like `test: prove 1.0 storage repair gates`.

## Task 3: Source Intake and Lifecycle Governance

**Files:**
- Modify: `core/source_intake.py`
- Modify: `core/ingestion_pipelines.py`
- Modify: `core/source_connectors.py`
- Modify: `tests/test_source_intake.py`
- Modify: `tests/test_server_structured_tools.py`
- Modify: `docs/ENGRAM_1_0_RELEASE_SPEC.md`

- [x] Confirm list/preview connector tools remain no-write.
- [x] Confirm malformed `prepare_source_memory` inputs return structured errors and never escape across MCP transport.
- [x] Confirm source drafts remain separated from active memory search until explicit promotion.
- [x] Define when a draft should become a memory, graph edge, app-only collaboration record, or external pointer.
- [x] Tighten lifecycle status docs so agents can prefer current, validated records and exclude stale ones by default.
- [x] Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_source_intake.py tests/test_server_structured_tools.py -q
.\venv\Scripts\python.exe server.py --self-test
```

- [x] Commit with a message like `fix: harden source intake lifecycle`.

## Task 4: WebUI 1.0 Review Surface

**Files:**
- Modify: `webui.py`
- Modify: `templates/index.html`
- Modify: `static/app.js`
- Test: `tests/test_webui_auth.py`
- Test: `tests/test_webui_memory.py`
- Test: `tests/test_security_defaults.py`
- Modify: `docs/ENGRAM_1_0_RELEASE_SPEC.md`

- [ ] Preserve JSON-safe create/edit form behavior for backticks, angle brackets, dashes, quotes, and multiline markdown.
- [ ] Keep exposed-host auth, write-token mutation protection, host/origin checks, body caps, throttling, security headers, and CSP fail-closed.
- [ ] Add local review surfaces only where they support Engram core: source drafts, graph relationships, retrieval receipts, health/self-test status, stale warnings, and storage stats.
- [ ] Do not add team workspaces, comments, assignments, mentions, or app-owned business workflow here.
- [ ] Run:

```powershell
.\venv\Scripts\python.exe -m pytest -q
git diff --check
```

- [ ] Commit with a message like `feat: finish 1.0 webui review surface`.

## Task 5: Agent Reliability Coverage

**Files:**
- Modify: `core/reliability_harness.py`
- Modify: `core/retrieval_eval.py`
- Modify: `tests/` reliability/eval coverage
- Modify: `docs/ENGRAM_1_0_RELEASE_SPEC.md`

- [ ] Add golden scenarios for source intake, graph-aware context, stale exclusion, hybrid identifier lookup, and codebase mapping.
- [ ] Keep context-pack receipts, citations, budget accounting, and token estimates visible in eval output.
- [ ] Document expected embedding-model load warnings so they do not become false failures.
- [ ] Confirm temporary eval memories clean up after every scenario.
- [ ] Run:

```powershell
.\venv\Scripts\python.exe server.py --agent-eval
.\venv\Scripts\python.exe -m pytest -q
```

- [ ] Commit with a message like `test: expand agent reliability gate`.

## Task 6: Release Docs and Final Gate

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `plan.md`
- Modify: `docs/ENGRAM_1_0_RELEASE_SPEC.md`
- Create or modify: `docs/ENGRAM_1_0_RELEASE_CHECKLIST.md`
- Create or modify: `docs/ENGRAM_1_0_MIGRATION_NOTES.md`

- [ ] Update README with 1.0 framing while keeping Engram public, generic, and local-first.
- [ ] Update AGENTS.md with current completion gates, Codex MCP visibility notes, and 1.0 operating rules.
- [ ] Update plan.md track checkboxes based on the completed work.
- [ ] Add release checklist and migration notes for public users and future agents.
- [ ] Cross-link the collaboration PRD without implying the collaboration product ships in Engram 1.0.
- [ ] Run the final gate:

```powershell
.\venv\Scripts\python.exe server.py --help
.\venv\Scripts\python.exe -c "from core.memory_manager import memory_manager; print('ok')"
.\venv\Scripts\python.exe server.py --self-test
.\venv\Scripts\python.exe server.py --agent-eval
.\venv\Scripts\python.exe -m pytest -q
git diff --check
codex mcp get engram
```

- [ ] Commit with a message like `docs: prepare Engram 1.0 release`.

## Collaboration Product Handoff

Do not implement collaboration features in this repo. After Engram 1.0 contracts are stable, start a separate project using `docs/COLLABORATION_PRODUCT_PRD.md` and `docs/POST_1_COLLABORATION_PRODUCT_HANDOFF.md`.

The first collaboration slice should prove:

- App-owned auth and workspace/project visibility.
- App-owned raw source storage and draft review records.
- Engram adapter calls through `memory_protocol()`, `context_pack()`, `prepare_memory()`, and explicit `store_memory()` promotion.
- Receipts and citations preserved on app draft records.
- No comments, assignments, page edits, or chat messages auto-promote Engram memories.
