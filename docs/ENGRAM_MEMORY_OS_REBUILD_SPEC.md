# Engram Memory OS Rebuild Spec

Status: Draft rebuild spec
Date: 2026-05-11
Scope: Public, generic, local-first, agent-facing persistent memory system

## Executive Summary

Engram's 1.0 track should pause. The stronger product direction is a rebuild
around a true agent-facing memory OS: a local daemon that preserves evidence,
models trust, compiles task-specific context, tracks graph relationships, and
migrates the current JSON memory store without loss.

The current Engram implementation has proven the important product shape:
agent-facing MCP tools, token-proportional retrieval, JSON-first durability,
source-intake drafts, graph evidence, codebase mapping, and retrieval receipts.
The rebuild should keep those principles while replacing the storage and
runtime center of gravity.

The rebuild is successful when an agent can ask:

- What do we know?
- Why do we believe it?
- Is it current?
- What conflicts with it?
- What evidence supports it?
- What context should I load next?

Engram should never merely remember text. It should preserve evidence, model
trust, compile context, and help agents avoid confidently using the wrong
memory.

## Product Principles

- Agent-facing first. MCP is the primary product surface, not an afterthought.
- Local-first by default. Hosted capabilities must be optional and explicit.
- Evidence before memory. Raw and extracted sources are evidence; reviewed
  memories are durable knowledge derived from evidence.
- Explicit writes only. No automatic durable memory promotion without review.
- Token-proportional retrieval. Search snippets before chunks, chunks before
  full documents, context packs before broad loads.
- Rebuildable indexes. Vector, full-text, and graph indexes must be rebuildable
  from the durable ledger and content store.
- Migration is a product feature. The current JSON memory store must import
  cleanly before new architecture is considered viable.
- Public generic repo. Do not encode private business or customer project names
  into public Engram artifacts.

## Why Rebuild

The current architecture grew from a simple local semantic memory server into a
larger agent operating layer. That growth created useful seams, but also
concentrated too much responsibility in the flat JSON plus Chroma path.

Current pain points:

- Multiple stdio MCP sessions can contend over embedded vector storage.
- Chroma-specific behavior leaks into architecture, docs, and health checks.
- Flat JSON files are portable, but not ideal as the live operational ledger
  for documents, drafts, receipts, graph edges, jobs, aliases, and migrations.
- Source intake exists, but documents are not first-class evidence objects.
- Graph relationships exist, but graph reasoning is not yet backed by a true
  graph database.
- Retrieval, graph, source, and lifecycle semantics are spread across many
  manager modules rather than one coherent memory OS model.

The rebuild should preserve the proven user-facing behavior and make the
internal architecture boring, durable, and extensible.

## Current Store Migration Baseline

Live local evidence checked on 2026-05-11:

- Existing memory JSON files: 816.
- Stored chunk count total from JSON metadata: 5644.
- Records with `related_to`: 338.
- Current memory JSON fields include `key`, `title`, `content`, `tags`,
  `project`, `domain`, `status`, `canonical`, `related_to`, timestamps,
  stale metadata, `chars`, `lines`, and `chunk_count`.
- Existing active memories do not rely on a populated `source_intake` field.

The rebuild must import those records without lossy conversion. The first
rebuild milestone is not LanceDB, Kuzu, document ingestion, or a new UI. It is
a verified migration dry run for the current memory corpus.

## Core Data Model

The rebuild should model the memory lifecycle explicitly:

```text
Source -> Document -> Section -> Chunk -> Draft -> Memory -> Graph Edge -> Retrieval Receipt
```

### Source

A raw input origin. Examples: local file, folder, URL, transcript, exported
chat, repository, issue export, email export, PDF, DOCX, markdown file, or
manual user note.

Required source properties:

- stable source id
- source type
- original URI or path
- content hash
- observed timestamp
- connector id and version
- privacy classification
- import job id
- extraction status

### Document

A normalized representation extracted from a source. One source may produce one
or more documents.

Required document properties:

- document id
- source id
- normalized markdown/text path
- extraction tool and version
- extraction hash
- title
- language if known
- created and updated timestamps
- page/section map when available

### Section

A structural region inside a document: heading, page, slide, transcript turn,
code file, issue comment, or semantic section.

Required section properties:

- section id
- document id
- heading path or locator
- source span
- normalized text span
- page number or line range when available

### Chunk

A retrieval unit derived from a document section or memory body. Chunks are
indexed for vector, full-text, and hybrid retrieval.

Required chunk properties:

- chunk id
- parent kind: source document, memory, or draft
- parent id
- source locator
- text
- embedding model id
- chunker id and version
- chunk hash
- token/character estimates
- citation fields

### Draft

A reviewable proposed conversion from evidence to durable memory or graph
relationship.

Required draft properties:

- draft id
- source ids and document ids used
- proposed memories
- proposed graph edges
- proposed aliases/entities
- confidence
- review status
- created by agent/user/system
- promotion guidance
- rejection reason if rejected

### Memory

A durable knowledge item intended for future agent use.

Required memory properties:

- stable memory key
- memory type
- title
- content
- lifecycle status
- trust state
- confidence
- review state
- project/domain/tags
- canonical entity references
- provenance links
- supersession links
- created and updated timestamps

### Graph Edge

A typed relationship between compact refs. Graph traversal must return
relationship ids, refs, types, confidence, and evidence, not surprise full
memory bodies.

Required edge properties:

- edge id
- from ref
- to ref
- edge type
- confidence
- evidence
- source
- status
- created by
- created at
- updated at

### Retrieval Receipt

A record of how context was assembled for an agent.

Required receipt properties:

- receipt id
- query/task
- retrieval profile
- filters
- chunk refs returned
- graph refs returned
- omitted counts
- budget estimate
- ranking explanation
- stale/conflict warnings
- timestamp

## Truth Model

Every stored memory-like item should have a truth type. Agents must not treat
all memory as equivalent.

Recommended truth types:

- `observation`: direct evidence observed in a source or runtime output.
- `user_preference`: a stable preference explicitly expressed by the user.
- `decision`: a chosen direction or constraint.
- `claim`: a statement that may need supporting evidence.
- `summary`: a compression of source material.
- `inference`: agent-derived conclusion from evidence.
- `procedure`: repeatable workflow or command sequence.
- `artifact`: a pointer to a file, commit, branch, document, or external object.

Trust dimensions should be separate fields, not collapsed into one status:

- confidence
- review state
- source-backed state
- freshness
- contradiction state
- supersession state
- privacy classification
- last successful use

## Recommended Backend Stack

### SQLite Ledger

SQLite should become the durable local ledger for metadata, relationships
between durable objects, migration state, jobs, receipts, aliases, and repair
state. It should not replace the content store for raw large source files.

SQLite responsibilities:

- schema migrations
- sources
- documents
- chunks metadata
- memories
- drafts
- graph edge metadata mirror
- retrieval receipts
- jobs and operation logs
- usage estimates
- project capsules
- aliases and canonical entity mappings
- import/export manifests

### Content-Addressed Source Store

Raw and normalized document content should live in a content-addressed file
store. This keeps large material auditable, portable, and rebuildable without
stuffing everything into one database file.

Content store responsibilities:

- raw imported source bytes
- normalized markdown/text
- extraction artifacts
- source maps
- bundle export payloads

### LanceDB Retrieval Index

LanceDB is the recommended default retrieval index candidate. It should replace
Chroma only after a spike proves Windows support, persistence, metadata
filtering, full-text search, hybrid search, rebuild behavior, and multi-session
daemon behavior against Engram's real corpus.

LanceDB responsibilities:

- chunk vectors
- full-text indexes
- hybrid search
- metadata filters
- citation fields in result rows
- index optimization/cleanup

Chroma should remain as a legacy adapter during migration. Qdrant can be a
future adapter for users who want a separate vector service. SQLite vector
extensions should remain experimental until their stability story is stronger.

Implementation status, 2026-05-12: Engram now has a no-write
`retrieval_backend_status` MCP gate that reports legacy Chroma as the live
index, LanceDB as an optional candidate, migrated-store vector source counts,
and deterministic rebuild-probe results. This is not a backend switch. LanceDB
must still pass a real optional-dependency spike against the migrated corpus
before it can replace Chroma in live retrieval.

### Kuzu Graph Store

Kuzu is the recommended default graph database candidate. It is embedded,
local-first, Python-friendly, supports a property graph model, supports Cypher,
persists on disk, and has ACID transaction support.

Kuzu responsibilities:

- entities
- decisions
- claims
- constraints
- source relationships
- memory relationships
- contradiction paths
- supersession chains
- impact analysis
- multi-hop graph queries

Neo4j should be an optional power-user adapter for advanced GraphRAG, graph
data science, visualization-heavy workflows, or shared deployments. Memgraph is
interesting for real-time streaming graph workloads, but it should not be the
default for a personal local-first memory OS.

Implementation status, 2026-05-12: Engram now has a no-write
`graph_backend_status` MCP gate that reports the JSON graph store as the live
graph backend, Kuzu as an optional candidate, live JSON edge counts, and
migrated ledger graph-edge counts. This is not a backend switch. Kuzu must
still pass a real optional-dependency corpus spike before it can replace JSON
graph storage in live traversal.

### Engram Daemon

The rebuilt runtime should introduce `engramd`, a single local daemon that owns
SQLite, source store writes, LanceDB, Kuzu, embedding jobs, migrations, and
repair operations.

MCP stdio servers should become thin clients that talk to `engramd`. This
prevents every agent thread from owning the vector or graph backend directly.

First implementation slice, 2026-05-12:

- `engramd.py` now provides an opt-in loopback daemon over a small JSON HTTP
  API.
- The daemon owns the current live `memory_manager` path, including JSON memory
  writes and legacy Chroma indexing.
- MCP stdio sessions can set `ENGRAM_DAEMON_URL` to route stable memory search,
  duplicate checks, chunk/full reads, writes, source draft
  prepare/list/discard/promotion, metadata updates, metadata repair, and
  deletes through the daemon.
- Direct in-process MCP mode remains the default while daemon mode is proven in
  real sessions.
- `engramd.py --smoke-test` verifies a running daemon by checking duplicate
  risk, writing, updating metadata, dry-running metadata repair, searching,
  reading, and deleting a temporary `_engramd_smoke_*` memory. Pair it with
  `ENGRAM_DATA_DIR` for disposable daemon smoke runs.
- This slice does not switch live retrieval to LanceDB, switch graph storage to
  Kuzu, add tenant authorization, or complete the full SQLite/content-addressed
  Memory OS runtime.

## Agent-Facing MCP Surface

The MCP surface should be workflow-oriented, not merely CRUD-oriented.

Core discovery:

- `memory_protocol`
- `memory_schema`
- `list_capabilities`
- `health_report`

Context:

- `prepare_context`
- `context_pack`
- `what_should_i_read_first`
- `find_current_truth_about`
- `show_conflicts_about`
- `why_do_we_believe`
- `what_changed_since`

Memory write workflow:

- `prepare_memory`
- `validate_memory`
- `check_memory_conflicts`
- `store_memory_transaction`
- `update_memory_with_diff`
- `supersede_memory`

Document workflow:

- `preview_source`
- `extract_document`
- `preview_document_chunks`
- `prepare_document_analysis`
- `store_document_draft`
- `promote_document_draft`

Graph workflow:

- `list_graph_edges`
- `explain_graph_path`
- `impact_scan`
- `add_graph_edge`
- `prepare_graph_suggestions`
- `promote_graph_suggestions`

Project workflow:

- `read_project_capsule`
- `prepare_project_capsule`
- `refresh_project_capsule`
- `make_handoff`
- `resume_project`

Operations:

- `migration_dry_run`
- `import_legacy_memories`
- `export_bundle`
- `restore_bundle`
- `audit_memory_quality`
- `repair_memory_store`
- `run_retrieval_eval`

## Context Compiler

The context compiler is a core feature. Agents should be able to ask for a
bounded, task-specific packet rather than manually running many searches.

Example:

```text
prepare_context(task="resume repo work", project="example")
```

The returned packet should include:

- current project capsule
- relevant current memories
- source-backed citations
- known hazards
- stale or contradicted memories
- current branch/commit if known
- next recommended files
- validation commands
- omitted evidence counts
- token budget estimate
- graph paths used

Retrieval profiles should tune the compiler:

- `resume_project`
- `debug_bug`
- `audit_repo`
- `write_spec`
- `import_document`
- `review_pr`
- `answer_user_history`
- `architecture_decision`
- `generate_handoff`
- `compare_sources`

## Project Capsules

Project capsules are first-class memory packs. They are the "load this first"
state for a project.

Capsules should include:

- project identity and aliases
- current goal
- repo paths
- important docs
- current architecture summary
- branch/worktree status when captured
- known hazards
- active decisions
- stale warnings
- validation commands
- recent commits
- next recommended step
- memories that must be read first

Capsules must be source-backed where possible and refreshable through explicit
agent review.

## Memory Quality and Anti-Drift

Each memory should have quality signals:

- source-backed
- reviewed
- current
- confidence score
- contradiction count
- duplicate risk
- project relevance
- stale risk
- last successful retrieval
- last successful use in an answer or task
- unsupported inference warning

Engram should support anti-drift evals that prove agents prefer:

- current over stale
- user preference over agent inference
- source evidence over unsupported summary
- reviewed memory over draft
- specific project capsule over generic memory
- explicit contradiction warning over silent retrieval

## Contradiction and Supersession

Contradiction detection should run before durable promotion when a proposed
memory overlaps a known topic, project, entity, or decision.

Expected outcomes:

- store both and mark conflict
- supersede older memory
- ask user for adjudication
- reject new draft
- mark as uncertain

Supersession chains should preserve history:

```text
draft -> active -> superseded -> historical
```

Agents should default to the current active memory while keeping access to the
historical chain.

## Document Intelligence Intake

Document intelligence is a core rebuild feature, not a hosted-only feature.

MVP formats:

- markdown
- plain text
- HTML
- URL/web page
- PDF
- DOCX
- repository folders
- transcript exports
- image-bearing documents and folders when visual extraction is needed

Pipeline:

```text
connector -> extractor -> normalizer -> sectioner -> chunker -> draft analysis -> explicit promotion
```

Visual extraction is part of document intelligence when the agent's native
visual capability is not enough to create durable, reviewable memory. It should
be a pluggable lane, not an always-on opaque processor:

```text
image or page render -> OCR/vision extractor -> visual artifact records -> section/chunk references -> draft analysis
```

Visual extraction should support:

- OCR text from scans, screenshots, image-only PDFs, and photographed notes
- figure, chart, table, and diagram descriptions
- screenshot UI state and error-message capture
- captions, alt text, page coordinates, bounding boxes, and confidence scores
- links from visual artifacts back to source document ids, page ids, section ids,
  and content-addressed raw files

The output of image recognition should be evidence, not trusted memory. Agents
must review visual extraction records before promotion, and every promoted claim
from an image should retain provenance to the rendered page or image artifact.
Engram should allow provider-neutral local or external OCR/vision adapters, but
the storage contract must not depend on one model vendor.

Implementation status, 2026-05-12: visual extraction requests now always mark
image recognition and per-image-ref coverage as required, including OCR-only
and agent-native vision flows. Each request includes a
`visual_evidence_contract` and `framework_strategy` so agents know whether
native vision is enough, when an external OCR/vision framework is required,
and that observations must return through `preview_visual_extraction` as
reviewable visual artifacts. When the originating visual request is passed
back to `preview_visual_extraction`, every requested image ref must have a
matching reviewed observation before the preview can claim complete coverage.
Visual artifact records now preserve source artifact id, page number,
coordinates and bounding boxes when available, confidence, and extractor id
for figure, table, caption, OCR block, page crop, and diagram evidence.

Document analysis should identify:

- summary
- decisions
- claims
- entities
- constraints
- tasks
- risks
- dates
- open questions
- candidate graph edges
- external pointers

No document import should automatically become durable memory. Imports create
evidence and drafts first.

Implementation status, 2026-05-12: `prepare_document_understanding_packet`
normalizes connected-agent synthesis into no-write summary slots, claim
candidates, concept candidates, entity candidates, high-value sections,
low-confidence warnings, draft memory proposals, and graph edge proposals.
Engram validates supplied graph proposal refs and edge types, then adds
reviewable automatic coverage proposals for document, page, section, chunk,
concept, claim, and visual-artifact relationships. Engram still does not
perform the analysis itself and does not promote the packet into active
memory or graph storage.

### Book Dismantling Gate

Engram 1.0 must pass the Book Dismantling Gate before claiming rich document
intelligence. The current binding design is
`docs/superpowers/specs/2026-05-12-engram-1-0-memory-os-document-disassembly-design.md`.

The gate requires book-scale imports to produce page inventory, extracted text,
visual/OCR work requests, table and figure artifact candidates, quality
warnings, chunk manifests, draft memory proposals, graph edge proposals, and
explicit promotion transactions without automatic durable memory writes.

Large documents must be processed as resumable jobs with content-addressed
artifacts and page-level receipts. A 79 MB image-heavy book must not require a
single all-or-nothing in-memory parse. Failed or skipped pages must be recorded
as evidence with recommended next actions.

Implementation status, 2026-05-12: `prepare_document_disassembly` now provides
a no-write local PDF page/text/image inventory through Poppler-compatible
`pdfinfo`, `pdftotext`, and `pdfimages` tools when available. It returns source
hashes, page text status, image-bearing pages, extraction receipts, quality seed
signals, deterministic document quality warnings, portable artifact refs, and
page-level resume states without promoting memory. It also returns page-crop
visual candidates and a prepared OCR/vision request for low-text, no-text, or
image-bearing pages, keeping visual/table analysis review-first instead of
automatic. It is not yet the final materialized artifact writer.

## Watchers

Watchers should be review-first.

Useful watcher targets:

- repo docs
- local folders
- URLs
- exported chats
- issue exports
- Obsidian vault folders
- email exports
- release notes

Watcher changes should produce review drafts and source-drift warnings, not
automatic active memories.

## Agent Session Recorder

Engram should optionally ingest agent sessions into reviewable drafts.

The session recorder should capture:

- user goals
- decisions
- commands run
- test results
- failures
- fixes
- commits
- changed files
- closeout summaries
- next recommended step

It must not blindly store the entire transcript as active memory. The output is
a draft handoff with evidence links.

## Memory Transactions

Multi-step writes should be transactional at the Engram domain level.

Examples:

- import document plus draft memories plus graph suggestions
- session closeout memory plus project capsule refresh plus graph edges
- migration import plus rebuilt retrieval index plus receipt

Transactions should support:

- dry run
- preview
- promote
- rollback
- receipt
- partial failure report

## Identity Resolution

The current memory corpus already shows project/domain naming drift. The
rebuild should treat identity resolution as a core feature.

Identity resolution should normalize:

- project names
- repo paths
- branch names
- tools
- people
- documents
- aliases
- product names
- module names

Original labels must be preserved. Canonical entities should not erase source
language.

## Local Inspector

The WebUI should become a local Memory Inspector, not a collaboration app.

Inspector surfaces:

- migration dry runs
- source imports
- document extraction results
- draft review queue
- conflict queue
- graph path browser
- project capsules
- retrieval receipts
- memory quality dashboard
- stale memory review
- backend health
- export/restore status

No team workspaces, comments, assignments, mentions, or role-aware visibility
belong in local Engram core.

## Hosted Edition Dream Features

Hosted Engram should be a separate optional deployment path. It should sell
trustworthy agent memory, not generic notes.

### Hosted Value Proposition

Hosted Engram is memory infrastructure for agents that need continuity,
evidence, graph reasoning, and context portability across tools and sessions.

The hosted product should compete on:

- agent-native MCP/API workflows
- evidence-backed memory
- local-first sync rather than cloud lock-in
- migration/export guarantees
- graph plus retrieval context compilation
- strong privacy and tenant isolation
- memory quality observability
- developer-friendly evals

### Hosted Features

Multi-device sync:

- encrypted sync for local-first users
- conflict-aware offline edits
- per-project sync controls
- portable export at all times
- personal memory passport: one signed export bundle that can move between
  local, hosted, and self-hosted deployments

Team/workspace layer:

- workspaces
- project spaces
- shared project capsules
- shared source libraries
- shared graph entities
- reviewed team memories
- memory ownership

Permission-aware memory:

- tenant isolation
- workspace roles
- project visibility
- source-level access control
- retrieval that respects visibility before ranking
- audit logs for memory access and promotion
- memory firewall policies that can reject, quarantine, redact, or require
  approval before sensitive or instruction-like content becomes retrievable
- prompt-injection quarantine for imported documents and web pages

Hosted agent gateway:

- hosted MCP endpoint
- API keys
- scoped tokens
- per-agent identities
- per-agent memory sandboxes
- tool-call audit logs
- rate limits and usage budgets
- per-agent write policies
- scoped retrieval profiles
- service accounts for CI and automations

Memory observability:

- retrieval traces
- context pack diffs
- memory usage heatmaps
- stale memory alerts
- contradiction dashboards
- unsupported inference reports
- "why did the agent use this?" inspection
- context drift timeline
- memory lineage view from source to answer
- agent behavior change reports after memory updates

Eval and regression platform:

- memory retrieval benchmarks
- project-specific golden questions
- drift regression reports
- context compiler evaluations
- contradiction handling tests
- privacy leak tests
- migration parity tests
- prompt-injection resilience tests
- memory CI gates for agent apps before deployment
- replayable agent sessions against old and new memory states

Managed connectors:

- GitHub
- Google Drive
- Microsoft 365
- Slack/Teams exports
- Notion exports
- Obsidian sync folders
- browser bookmarks/history exports
- issue trackers
- support/customer exports

Memory marketplace:

- connector packs
- retrieval profiles
- project capsule templates
- memory schema templates
- eval packs
- workflow recipes
- memory quality graders
- hosted demo datasets
- domain schema packs

Trust center:

- tenant-level encryption posture
- export and delete guarantees
- audit trail
- data residency options
- no-training policy
- local-first sync explanation
- admin review of connectors and agents
- bring-your-own-key option
- self-hosted enterprise package
- air-gapped deployment path
- data processing region controls
- connector permission diff before approval

Developer experience:

- SDKs for Python and TypeScript
- MCP-first quickstart
- local dev daemon compatible with hosted sync
- migration CLI
- test fixtures
- hosted sandbox workspaces
- visual graph/debug console
- memory playground for retrieval profile tuning
- generated eval fixtures from real project capsules
- one-command local-to-hosted migration dry run
- clean downgrade/export path back to local-only

Hosted sellable workflows:

- memory branching, diffing, and merge review for risky project changes
- point-in-time rollback for memory, graph, retrieval indexes, and policies
- answer provenance badges that can be attached to agent outputs
- shareable audit packets for "why the agent answered this way"
- agent handoff packets that move a working context between Codex, Claude,
  local scripts, CI agents, and hosted agents
- onboarding capture flows that turn a repo, docs folder, and prior chats into a
  reviewed project capsule
- token-savings and retrieval-quality ROI reports
- policy simulator for visibility, redaction, and prompt-injection rules before
  they affect live retrieval
- model/provider portability reports showing which memories and context packs
  survive a provider switch
- memory steward review queues for teams that want explicit approval before
  agent-written memories become active
- incident mode that freezes writes, preserves receipts, and lets operators
  inspect what memory state existed during a bad answer
- verified export bundles with checksums, schema manifests, and source lineage
  for migrations, audits, and account recovery

Collaboration product bridge:

- hosted Engram can power a separate collaboration app, but should not become
  that app.
- rich pages, comments, assignments, mentions, and team workflows live in the
  collaboration layer.
- Engram owns evidence, memory, graph reasoning, receipts, and context
  compilation.

### Hosted Differentiators

Hosted memory tools often emphasize simple add/search APIs, managed vector
stores, graph memory, or agent state visibility. Engram should differentiate by
combining:

- local-first default
- full migration/export story
- graph evidence rather than opaque graph magic
- review-first promotion
- context compiler outputs with receipts
- memory quality scoring
- contradiction and supersession handling
- project capsules for coding and long-running work
- MCP as a first-class interface
- memory firewall and prompt-injection quarantine
- offline-first local daemon with optional hosted sync
- transparent rollback and replay after memory changes
- agent memory CI for production apps

The hosted edition should make teams feel they can trust agent memory in
production because every important answer can be traced back to source,
review state, graph path, and retrieval receipt.

## Competitive Reference Points

These are not products to clone. They are useful landscape signals.

- Mem0 documents a managed memory layer with vector store, graph services,
  rerankers, graph memory, async clients, metadata filters, MCP support, and
  integrations: https://docs.mem0.ai/platform/overview
- Zep emphasizes graph-backed agent memory, high-level memory APIs, graph APIs,
  fact ratings, group graphs, and custom context strings:
  https://help.getzep.com/v2/memory
- Letta emphasizes stateful agents, memory hierarchy, memory blocks, context
  management, agent development visibility, evals, permissions, hooks, and
  agent tooling: https://docs.letta.com/
- Chaos Cypher describes document ingestion, hybrid search, GraphRAG search,
  entity/relationship extraction, MCP server modes, and self-hosted knowledge
  graph workflows: https://chaoscypher.com/docs/getting-started/overview

Engram should borrow the best ideas while staying focused on evidence,
migration, local-first operation, and agent-facing control.

## Rebuild Phases

### Phase 0: Rebuild Spec and Baseline

- Commit this rebuild spec.
- Freeze old 1.0 feature work unless it directly supports migration.
- Capture current memory corpus stats.
- Define acceptance tests for legacy import.
- Define backend decision matrix.

### Phase 1: Migration Kernel

- Add SQLite ledger schema.
- Add content-addressed source store.
- Implement legacy JSON import dry run.
- Import current JSON memories into the new ledger.
- Preserve original JSON records as immutable imported artifacts.
- Export a portable bundle from the new store.
- Restore that bundle into a clean store.

Acceptance gates:

- imported memory key set matches legacy key set.
- metadata survives.
- `related_to` survives.
- chunk counts are preserved or differences are explained.
- old JSON can be restored from imported artifacts.

### Phase 2: Retrieval Index

- Add `VectorIndex` adapter contract.
- Implement LanceDB adapter.
- Keep Chroma legacy adapter.
- Rebuild LanceDB from the SQLite/content store.
- Compare search quality against current Chroma on golden queries.
- Add full-text and hybrid search tests.

Acceptance gates:

- search returns cited chunks.
- metadata filters work.
- hybrid search works.
- rebuild from durable store works.
- daemon-owned backend avoids multi-stdio ownership failure.

### Phase 3: Graph Store

- Add `GraphStore` adapter contract for the new model.
- Implement Kuzu adapter.
- Import existing graph edges and `related_to` links.
- Add entity, claim, decision, source, memory, and document nodes.
- Add graph path and impact-scan tools.

Acceptance gates:

- graph import preserves edge ids and evidence.
- graph traversal does not load surprise memory bodies.
- impact scans return refs and evidence.
- contradiction and supersession edge types are test-covered.

### Phase 4: Document Intelligence

- Add source connectors and extractors.
- Add provider-neutral OCR/vision extraction adapters for image-bearing
  documents when native agent visual analysis is not enough.
- Add normalized document store.
- Add visual artifact records for scans, figures, diagrams, screenshots, tables,
  captions, coordinates, and confidence scores.
- Add section and chunk provenance.
- Add draft analysis packets.
- Add explicit promotion transactions.

Acceptance gates:

- markdown, text, HTML, URL, PDF, and DOCX fixtures import as evidence.
- image-only PDF, screenshot, figure, and diagram fixtures produce reviewable
  visual extraction evidence with source/page/coordinate provenance.
- source citations survive chunk retrieval.
- promoted claims from visual extraction retain links to the originating image
  artifact and extractor receipt.
- drafts do not become active memories automatically.

### Phase 5: Agent Workflows

- Add context compiler.
- Add project capsules.
- Add handoff generator.
- Add contradiction checks.
- Add memory quality audit.
- Add retrieval profiles.

Acceptance gates:

- `prepare_context` returns bounded cited packets.
- `make_handoff` produces actionable resume packets.
- stale/conflicting memories are warned about.
- evals prove current/reviewed/source-backed memories are preferred.

Implementation checkpoint, 2026-05-11:

- Current-stack Phase 5 primitives are implemented as no-write agent workflow
  helpers: `prepare_context`, `make_handoff`, `prepare_project_capsule`,
  `audit_memory_quality`, `conflict_scan`, and expanded workflow templates.
- Graph-enabled context packets now run compact conflict scans over selected
  memory refs and warn with counts/types only.
- `retrieval_eval` now includes workflow-packet checks, workflow-template
  checks, stale-distractor exclusion, and reviewed/source-backed metadata
  targeting scenarios.

### Phase 6: Local Inspector

- Rebuild WebUI as Memory Inspector.
- Add migration, source, draft, graph, receipt, and quality review surfaces.
- Preserve loopback-first security.

Acceptance gates:

- inspector never bypasses review-first promotion.
- exposed-host security remains fail-closed.
- no hosted collaboration features leak into local core.

Implementation checkpoint, 2026-05-11:

- Initial local inspector APIs expose memory quality, graph audit/edges, source
  drafts, and operation jobs/events as read-only WebUI routes.
- The dashboard has an Inspector tab for quality, graph, and operation receipt
  summaries, plus draft queue visibility.
- Remaining inspector work includes draft promotion/rejection ergonomics,
  migration receipts, graph relationship browsing, health/self-test display,
  and any visual polish needed after browser screenshot review.

### Phase 7: Hosted Readiness

- Define hosted architecture separately.
- Add tenant isolation design.
- Add sync protocol design.
- Add hosted MCP/API gateway design.
- Add privacy, export, delete, and audit guarantees.

Acceptance gates:

- hosted features are optional.
- local-first export remains complete.
- tenant access control applies before retrieval ranking.

## Non-Goals

- Do not continue the old 1.0 feature checklist as the main roadmap.
- Do not make hosted sync required for local Engram.
- Do not turn local Engram into a team collaboration app.
- Do not auto-promote noisy source imports into active memory.
- Do not replace evidence with agent summaries.
- Do not let vector or graph indexes become the only source of truth.
- Do not require Neo4j, Docker, or cloud services for the default local path.

## First Implementation Slice

The first implementation slice should be migration-only:

1. Create the SQLite schema draft.
2. Create the content store layout.
3. Import current JSON memories in dry-run mode.
4. Report exact counts, field mappings, unsupported fields, and chunk parity.
5. Export a bundle from the new store.
6. Restore it into a clean temp store.
7. Commit only after the current memory corpus can make the round trip.

This protects the user's existing memory before any backend excitement begins.
