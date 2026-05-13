# Engram 1.0 Release Spec

Date: 2026-05-05
Updated: 2026-05-12
Status: Engram 1.0 local core release spec
Scope: Public Engram core release, contract freeze, Memory OS readiness, document intelligence, reliability gates, and collaboration substrate seams

## Purpose

Engram 1.0 is the stable public release of the local-first agent Memory OS core: JSON-backed durable memory, ChromaDB-backed semantic retrieval, FastMCP tools, source-intake drafts, document evidence, graph relationships, codebase mapping, migration checks, retrieval receipts, opt-in daemon routing, and local review surfaces.

This spec deliberately stops before team collaboration. The collaboration product is planned separately in `docs/COLLABORATION_PRODUCT_PRD.md` and should integrate with Engram through stable contracts instead of pulling team-workspace concerns into this repository.

## Shared Roadmap

The shared program has two products and one integration contract:

1. Engram 1.0: stabilize the public local-first memory substrate.
2. Collaboration product: build a separate team workspace and review experience on top of Engram.
3. Engram adapter contract: define how the app calls Engram, preserves receipts, enforces visibility, and promotes reviewable drafts.

Recommended sequence:

1. Finish and publish the current Engram planning branch. Local merge to `main` is complete as of 2026-05-06; remote publication remains a release-management step.
2. Bring Engram to 1.0 with contract, storage, source-intake, document evidence, graph, codebase mapping, daemon, migration, docs, and release gates.
3. Start the collaboration product in a separate repo/project with its own auth, workspace, and UI architecture.
4. Build the first collaboration vertical slice as a thin app over stable Engram calls: source intake -> cited draft -> human review -> explicit memory promotion.
5. Add richer pages, comments, assignments, mentions, and game-development knowledge spaces only after permission-aware retrieval and draft review are proven.

Coordination rule: Engram changes should be judged by whether they make the generic memory substrate stronger. Collaboration-app changes should be judged by whether they improve team workflow without corrupting Engram's storage or tool contracts.

## Product Thesis

Engram 1.0 is ready when a fresh agent can discover how to use memory safely, retrieve bounded context with evidence, stage messy source and document material for review, inspect relationship evidence without token blowups, and validate the local store with repeatable commands.

The release should feel boring in the best way: stable contracts, recoverable storage, explicit writes, clear docs, and a release checklist that future agents can run without folklore.

## Non-Goals

- No multi-user collaboration, permissions, comments, assignments, mentions, team presence, or workspace admin in Engram 1.0.
- No private/business project names in public repo docs.
- No automatic memory writes from agents.
- No direct replacement of JSON memories as the source of truth.
- No graph database migration before the JSON-backed graph edge contract is frozen.
- No provider-specific model subprocess for codebase mapping.
- No hosted tenant auth, billing, or live backend switch. Backend readiness reports and hosted checklists are preparation, not live 1.0 feature promises.
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

Status: locally complete on 2026-05-06. `main` was fast-forwarded to `codex/collaboration-product-handoff-spec`. The local branch is ahead of `origin/main`; push/PR publication is still an operator decision.

Required outcomes:

- Publish local `main` when ready; it now includes `4e6b6881 Harden source intake tool errors` plus tracked 1.0/collaboration planning docs.
- Keep `codex/collaboration-product-handoff-spec` as historical branch context or delete it after remote publication.
- Keep ignored `docs/superpowers/` planning artifacts out of public commits unless the repo intentionally changes that policy.
- Keep any release-planning docs in tracked `docs/`.
- Preserve existing unrelated worktrees and branches unless a cleanup request is explicit.

Acceptance gates:

- `git status --short --branch` is clean before each implementation branch starts.
- Each branch has one readable purpose.
- Release docs do not contain non-public project names.

### Track 1: Contract Freeze

Purpose: make the MCP and data contracts dependable for agents, clients, and the future collaboration adapter.

Product/protocol identity decision: the 1.0 local core release reports product version `1.0.0` and stability `stable`. The MCP protocol remains a separate agent contract with `version: 2` and `schema_version: "2026-04-27"` until an explicit protocol migration is required.

Required outcomes:

- Inventory every MCP tool, alias, return shape, schema version, and stability tier in `docs/ENGRAM_1_0_MCP_CONTRACT.md`.
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

Status: implemented in Track 2 branch on 2026-05-06. Release operator commands live in `docs/ENGRAM_1_0_RELEASE_CHECKLIST.md`.

Required outcomes:

- Audit JSON-first/Chroma-second storage paths and tests.
- Add or confirm backup-before-repair behavior for destructive or schema-affecting operations. Metadata repair now writes a pre-repair backup before normalized JSON is saved.
- Confirm import/export round trips preserve required memory metadata. Import now preserves full exported JSON records instead of rewriting through `store_memory()`.
- Confirm Chroma rebuild from JSON restores searchable chunks and clears stale vector rows.
- Confirm graph audits can detect malformed edges without loading full memory bodies; graph audit remains edge-record-only.
- Confirm metadata repair stays dry-run by default and preserves JSON-first ordering when applied.

Acceptance gates:

- Store/search/retrieve/delete self-test passes.
- Rebuild/import/export checks have documented commands.
- Repair operations have dry-run evidence before writes.
- Any schema-affecting change has migration notes.

### Track 3: Source Intake and Lifecycle Governance

Purpose: make messy source material reviewable and trustworthy without memory spam.

Status: implemented in Track 3 branch on 2026-05-07. Source intake now exposes explicit no-write/lifecycle policy, draft promotion guidance, and rejected-draft promotion protection.

Required outcomes:

- Keep `list_ingestion_pipelines()`, `preview_memory_chunks()`, and `preview_source_connector()` no-write. Pipeline catalog now reports `write_performed: false`.
- Keep `prepare_source_memory()` transport-safe for malformed agent input.
- Confirm source drafts are separated from active memory search until promoted; drafts report `active_memory_write_performed: false`.
- Harden lifecycle statuses and trust metadata enough for agents to prefer approved, current, validated memories.
- Ensure stale/scanner-derived/source-derived records are visibly marked through draft status, source-intake tags, and proposed-memory `source_intake` receipts.
- Define when a draft should become a memory, a graph edge, app-only collaboration state, or an external pointer through `promotion_guidance`.

Acceptance gates:

- Malformed source-intake inputs return structured errors.
- Large source material can be previewed before storage.
- Draft promotion remains explicit and test-covered.
- Retrieval surfaces can exclude stale records by default.

### Track 4: Codebase Mapping and Memory OS Migration Readiness

Purpose: keep repository understanding and migration checks agent-facing, provider-neutral, and safe against data loss.

Status: implemented during the 2026-05-12 Memory OS rebuild slices.

Required outcomes:

- Keep codebase mapping provider-neutral; Engram prepares bounded source context and source hashes, while the connected agent performs synthesis.
- Keep mapping config draft/store/preview/prepare/read/store-result tools agent-facing and drift-aware.
- Honor `ENGRAM_DATA_DIR` for mapping jobs.
- Add no-write migration dry runs and round-trip checks for legacy JSON memory records.
- Keep retrieval and graph backend status reports read-only until backend replacements pass real-corpus gates.

Acceptance gates:

- Mapping jobs include current Memory OS domains instead of the old pre-daemon shape.
- Stale mapping results are blocked unless forced after review.
- Migration dry runs and round-trip checks do not mutate active memories or ChromaDB.
- Chroma/JSON remain live until backend replacement gates pass.

### Track 5: Document Intelligence and Agent Reliability

Purpose: make book-scale source understanding and agent-facing quality measurable instead of vibes.

Status: implemented during the 2026-05-12 document disassembly slices.

Required outcomes:

- Keep `server.py --agent-eval` as the deterministic reliability gate.
- Add a no-write local PDF disassembly path that inventories pages, text coverage, image-bearing pages, extraction receipts, quality seeds, artifact manifests, visual candidates, and mandatory visual/OCR work requests.
- Add document quality reports that identify no-text pages, image-heavy pages, failed pages, and visual-review needs.
- Add understanding packets that normalize connected-agent synthesis into summaries, claim/concept/entity candidates, high-value sections, low-confidence warnings, draft memory proposals, and supplied plus auto-generated graph coverage proposals.
- Add golden reliability scenarios for source intake, workflow packets, document disassembly, mandatory visual evidence coverage, graph coverage proposals, and the Book Dismantling Gate.
- Keep context-pack budget receipts and citations visible in eval output.
- Treat usage telemetry as Engram-attributed estimates, not provider billing truth.
- Document expected warnings from the embedding model load so they do not become false failures.

Acceptance gates:

- Agent eval passes on a clean checkout.
- Evaluation failures identify the broken retrieval contract.
- All temporary eval memories are cleaned up after the run.
- Document intelligence paths report evidence and promotion plans without active memory writes.

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

## Post-1.0 Work

- Expand WebUI operator surfaces for document imports, graph proposals,
  migration receipts, evals, and daemon/job health while preserving local-only
  review boundaries.
- Run real-corpus backend decision gates before replacing live Chroma or JSON
  graph storage with LanceDB, Kuzu, or another backend. The 2026-05-13
  backend follow-up added dependency profiles, thin daemon-client registration,
  LanceDB reopen support, retrieval comparison gates, Kuzu graph parity gates,
  and cross-document graph edge vocabulary; live promotion still requires
  golden retrieval quality and daemon-owned backend switching.
- Move more long-running work behind durable daemon jobs only after a job store,
  resumability, and operator receipts exist.
- Add hosted tenant auth, object authorization, billing, support-bundle
  redaction, and hosted deletion/export semantics before any hosted Engram
  claim.

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
