# Engram 1.0 Release Spec

Date: 2026-05-05
Status: Draft for implementation planning
Scope: Public Engram core release readiness, contract freeze, reliability hardening, and collaboration substrate seams

## Purpose

Engram 1.0 should be the stable public release of the local-first agent memory substrate: JSON-backed durable memory, ChromaDB-backed semantic retrieval, FastMCP tools, source-intake drafts, graph relationships, codebase mapping, retrieval receipts, and local review surfaces.

This spec deliberately stops before team collaboration. The collaboration product is planned separately in `docs/COLLABORATION_PRODUCT_PRD.md` and should integrate with Engram through stable contracts instead of pulling team-workspace concerns into this repository.

## Shared Roadmap

The shared program has two products and one integration contract:

1. Engram 1.0: stabilize the public local-first memory substrate.
2. Collaboration product: build a separate team workspace and review experience on top of Engram.
3. Engram adapter contract: define how the app calls Engram, preserves receipts, enforces visibility, and promotes reviewable drafts.

Recommended sequence:

1. Finish and publish the current Engram planning branch.
2. Bring Engram to 1.0 with contract, storage, source-intake, graph, WebUI, docs, and release gates.
3. Start the collaboration product in a separate repo/project with its own auth, workspace, and UI architecture.
4. Build the first collaboration vertical slice as a thin app over stable Engram calls: source intake -> cited draft -> human review -> explicit memory promotion.
5. Add richer pages, comments, assignments, mentions, and game-development knowledge spaces only after permission-aware retrieval and draft review are proven.

Coordination rule: Engram changes should be judged by whether they make the generic memory substrate stronger. Collaboration-app changes should be judged by whether they improve team workflow without corrupting Engram's storage or tool contracts.

## Product Thesis

Engram 1.0 is ready when a fresh agent can discover how to use memory safely, retrieve bounded context with evidence, stage messy source material for review, inspect relationship evidence without token blowups, and validate the local store with repeatable commands.

The release should feel boring in the best way: stable contracts, recoverable storage, explicit writes, clear docs, and a release checklist that future agents can run without folklore.

## Non-Goals

- No multi-user collaboration, permissions, comments, assignments, mentions, team presence, or workspace admin in Engram 1.0.
- No private/business project names in public repo docs.
- No automatic memory writes from agents.
- No direct replacement of JSON memories as the source of truth.
- No graph database migration before the JSON-backed graph edge contract is frozen.
- No provider-specific model subprocess for codebase mapping.
- No WebUI business logic layer; WebUI stays a local review and management surface over core managers.

## Binding Invariants

- JSON memory files remain authoritative.
- ChromaDB remains a rebuildable semantic index.
- Store flow remains JSON-first, then Chroma indexing.
- Chunk IDs keep the current `{md5(key)}_{chunk_index}` reference format unless a migration exists.
- Graph edges remain compact durable migration records.
- Graph traversal returns IDs, reasons, scores, and evidence by default, not neighbor memory bodies.
- Source connector and chunk preview helpers remain no-write.
- Source intake remains draft-first and explicit-promotion only.
- MCP docstrings remain agent-facing contracts.
- No stdout in MCP production paths.
- `memory_protocol()` remains the progressive-discovery entry point.

## Release Tracks

### Track 0: Repo and Branch Hygiene

Purpose: start 1.0 work from a clean public baseline.

Required outcomes:

- Decide whether to push local `main` with `4e6b6881 Harden source intake tool errors`.
- Decide whether to merge or PR `codex/collaboration-product-handoff-spec`.
- Keep ignored `docs/superpowers/` planning artifacts out of public commits unless the repo intentionally changes that policy.
- Keep any release-planning docs in tracked `docs/`.
- Preserve existing unrelated worktrees and branches unless a cleanup request is explicit.

Acceptance gates:

- `git status --short --branch` is clean before each implementation branch starts.
- Each branch has one readable purpose.
- Release docs do not contain non-public project names.

### Track 1: Contract Freeze

Purpose: make the MCP and data contracts dependable for agents, clients, and the future collaboration adapter.

Required outcomes:

- Inventory every MCP tool, alias, return shape, schema version, and stability tier.
- Mark stable, beta, and experimental surfaces clearly in `memory_protocol()`.
- Ensure `server.py` tool docstrings match real behavior, especially retrieval ladder, no-write helpers, draft promotion, graph traversal, and token/receipt expectations.
- Freeze the context-pack receipt fields or write migration notes for any field that remains beta.
- Freeze graph edge required fields and migration expectations.
- Document which Python internals are not public contracts.

Acceptance gates:

- A fresh agent can call `memory_protocol()` and choose the right retrieval/write/source/graph path without reading the whole README.
- Compatibility aliases remain behaviorally aligned with canonical tools.
- Tool docstrings and README tool tables agree.

### Track 2: Storage, Rebuild, and Repair Readiness

Purpose: prove local data can survive index drift, import/export, repair, and release upgrades.

Required outcomes:

- Audit JSON-first/Chroma-second storage paths and tests.
- Add or confirm backup-before-repair behavior for destructive or schema-affecting operations.
- Confirm import/export round trips preserve required memory metadata.
- Confirm Chroma rebuild from JSON restores searchable chunks.
- Confirm graph audits can detect malformed edges without loading full memory bodies.
- Confirm metadata repair stays dry-run by default and preserves JSON-first ordering when applied.

Acceptance gates:

- Store/search/retrieve/delete self-test passes.
- Rebuild/import/export checks have documented commands.
- Repair operations have dry-run evidence before writes.
- Any schema-affecting change has migration notes.

### Track 3: Source Intake and Lifecycle Governance

Purpose: make messy source material reviewable and trustworthy without memory spam.

Required outcomes:

- Keep `list_ingestion_pipelines()`, `preview_memory_chunks()`, and `preview_source_connector()` no-write.
- Keep `prepare_source_memory()` transport-safe for malformed agent input.
- Confirm source drafts are separated from active memory search until promoted.
- Harden lifecycle statuses and trust metadata enough for agents to prefer approved, current, validated memories.
- Ensure stale/scanner-derived/source-derived records are visibly marked.
- Define when a draft should become a memory, a graph edge, app-only collaboration state, or an external pointer.

Acceptance gates:

- Malformed source-intake inputs return structured errors.
- Large source material can be previewed before storage.
- Draft promotion remains explicit and test-covered.
- Retrieval surfaces can exclude stale records by default.

### Track 4: WebUI 1.0 Readiness

Purpose: make the local dashboard a trustworthy review and operations surface without turning it into the collaboration app.

Required outcomes:

- Fix the existing dashboard JSON serialization bug in create/edit forms.
- Remove or align the hardcoded textarea character limit with server-side validation.
- Preserve exposed-host auth requirements, write-token mutation protection, host/origin checks, request body limits, throttling, security headers, and CSP without unsafe inline script/style.
- Surface source draft review, graph relationship browsing, retrieval receipt inspection, health/self-test status, stale warnings, and storage stats only as local Engram surfaces.
- Keep WebUI logic calling core managers rather than becoming the domain layer.

Acceptance gates:

- Browser form submissions safely handle backticks, angle brackets, dashes, quotes, and multiline markdown.
- Exposed-host startup remains fail-closed without required tokens.
- Security-sensitive WebUI tests remain green.

### Track 5: Agent Reliability and Evaluation

Purpose: make agent-facing quality measurable instead of vibes.

Required outcomes:

- Keep `server.py --agent-eval` as the deterministic reliability gate.
- Add golden retrieval scenarios for source intake, graph-aware context, stale exclusion, hybrid identifier lookup, and codebase mapping if coverage is thin.
- Keep context-pack budget receipts and citations visible in eval output.
- Treat usage telemetry as Engram-attributed estimates, not provider billing truth.
- Document expected warnings from the embedding model load so they do not become false failures.

Acceptance gates:

- Agent eval passes on a clean checkout.
- Evaluation failures identify the broken retrieval contract.
- All temporary eval memories are cleaned up after the run.

### Track 6: Release Documentation

Purpose: make 1.0 understandable to public users and future agents.

Required outcomes:

- Update `README.md` for 1.0 with clear generic framing.
- Update `AGENTS.md` with current completion gates, Codex MCP visibility notes, and 1.0 operating rules.
- Update `plan.md` to mark completed milestones and define 1.0 status.
- Add a release checklist and migration guide.
- Cross-link the collaboration boundary docs without implying the collaboration app ships in Engram 1.0.
- Keep private/customer/project names out of public docs.

Acceptance gates:

- A new user can install, register, run health checks, and understand the retrieval ladder.
- A new agent can follow AGENTS.md and finish a safe Engram change.
- Public docs do not overpromise collaboration features.

## 1.0 Validation Gate

Before declaring Engram 1.0 ready:

- `python server.py --help`
- `python -c "from core.memory_manager import memory_manager; print('ok')"`
- `python server.py --self-test`
- `python server.py --agent-eval`
- `pytest -q`
- Production stdout audit for `server.py` and `core/memory_manager.py`
- `git diff --check`
- `codex mcp get engram` when Codex CLI is available and MCP registration changed
- Fresh-session MCP tool availability check when Codex visibility changed

## Release Risks

- `server.py` and `core/memory_manager.py` are large enough that contract changes can have hidden blast radius.
- `docs/superpowers/` is ignored, so release docs placed there can disappear from public history unless force-added intentionally.
- Collaboration language can accidentally make Engram look like a team workspace product; keep public framing generic.
- WebUI security changes can regress exposed-host fail-closed behavior if tested only in loopback mode.
- Graph traversal can become token-expensive if relationship expansion starts returning bodies instead of IDs/evidence.
- Source intake can become memory spam if draft promotion is made automatic.

## Implementation Planning Notes

This spec should become one implementation plan with small commits by track. The first implementation slice should be Track 0 plus a release-readiness audit, not feature work. Each subsequent slice should name the contract it hardens, the files it touches, and the validation command that proves the gate.

Do not begin collaboration-app implementation inside this repo. Engram 1.0 should only add or stabilize the substrate seams the separate app needs.
