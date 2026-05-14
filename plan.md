# Engram — Persistent Semantic Memory for AI Agents

## Vision
A local-first, agent-facing Memory OS that gives AI agents durable, searchable, source-grounded memory across sessions. Engram keeps context token-proportional, preserves evidence and graph relationships, and remains complementary to structured project documents such as `plan.md`, `AGENTS.md`, and specs.

## Core Philosophy
- **Retrieve what's relevant, not everything.** Three-tier retrieval keeps token costs proportional to need.
- **Semantic search that actually works.** Local embeddings via sentence-transformers, not substring matching.
- **Durable operational ledger.** Rebuilt 1.0 uses SQLite for metadata, receipts, transactions, jobs, entities, concepts, aliases, and migration state.
- **Portable evidence store.** Raw, normalized, and extracted sources live in a content-addressed store so indexes and graphs can be rebuilt.
- **Complementary to structured docs.** Engram is fast operational memory; AGENTS.md/plan.md are canonical governance.

## Architecture

### Stack
- `engramd` — daemon-owned local runtime for shared process ownership.
- `SQLite` — Memory OS ledger.
- Content-addressed object store — source artifacts and normalized evidence.
- `sentence-transformers` — local embeddings (`all-MiniLM-L6-v2`, ~80MB, CPU-capable).
- `LanceDB` — rebuilt local retrieval index.
- `Kuzu` — rebuilt local graph store.
- `FastMCP` — MCP server layer (stdio + SSE transport).
- `Flask` — local Memory Inspector dashboard.
- Legacy JSON + ChromaDB — migration/compatibility store that remains protected until all callers move to the rebuilt runtime.

### Storage Layout
```
engram/
├── data/
│   ├── memory_os/
│   │   ├── ledger.sqlite3
│   │   ├── objects/
│   │   ├── lance/
│   │   └── kuzu/
│   ├── memories/       # legacy JSON memories for compatibility/migration
│   └── chroma/         # legacy ChromaDB vector index
├── core/
│   ├── embedder.py     # sentence-transformers wrapper
│   ├── chunker.py      # smart markdown-aware chunking
│   └── memory_manager.py
├── server.py           # FastMCP MCP server
├── webui.py            # Flask dashboard
├── install.py          # setup wizard
├── requirements.txt
├── AGENTS.md
└── plan.md
```

### Three-Tier Retrieval Pattern
```
search_memories(query)       → scored snippets only       [~50 tokens/result]
retrieve_chunk(key, chunk_id) → one relevant section      [~200 tokens]
retrieve_memory(key)         → full content               [full cost, intentional]
```

Agents should always start at tier 1 and escalate only when needed.

## MCP Tool Surface

| Tool | Signature | Returns | Token Cost |
|---|---|---|---|
| `memory_protocol` | `()` | Current retrieval ladder, aliases, and warnings | Very low |
| `search_memories` | `(query, limit=5, project=None, domain=None, tags=None, retrieval_mode='semantic', ...)` | Scored snippet per chunk match | Low |
| `context_pack` | `(query, max_chunks=5, budget_chars=6000, retrieval_mode='semantic', ...)` | Bounded retrieved chunks, citations, and receipt after search/dedupe | Medium |
| `list_context_profiles` | `()` | No-write context profile catalog for task-focused retrieval | Very low |
| `prepare_context` | `(task, profile='repo_resume', project=None, ...)` | No-write cited context packet with profile receipt, warnings, and next actions | Medium |
| `make_handoff` | `(task, project=None, next_steps=None, validation=None, ...)` | No-write handoff packet with context refs, citations, resume prompt, and validation notes | Medium |
| `prepare_project_capsule` | `(project, task='prepare project capsule', ...)` | No-write project capsule draft from context refs and quality signals | Medium |
| `list_memories` | `(limit=50, offset=0, project=None, domain=None, tags=None)` | Paginated metadata directory | Very low |
| `audit_memory_quality` | `(limit=100, offset=0, project=None, domain=None, tags=None)` | Metadata-only quality/risk signals without memory bodies | Very low |
| `retrieve_chunk` | `(key, chunk_id)` | Full text of one chunk | Medium |
| `retrieve_memory` | `(key)` | Full memory and metadata | High (intentional) |
| `store_memory` / `write_memory` | `(key, content, tags, title, project=None, domain=None, status=None, canonical=None)` | Confirmation | — |
| `prepare_memory` | `(content, key='', title='', tags='', ...)` | Draft metadata, validation, duplicate check | — |
| `list_ingestion_pipelines` | `()` | Agent-safe source intake presets | Very low |
| `preview_memory_chunks` | `(content, title='', max_size=800)` | Reviewable chunk boundaries; no writes | Low |
| `preview_source_connector` | `(connector_type='local_path', target, include_globs=None, ...)` | Local source items and draft args; no writes | Low-medium |
| `prepare_source_memory` | `(source_text, source_type, pipeline='generic', ...)` | Reviewable source draft; no active memory | Medium |
| `retrieval_eval` | `()` | Deterministic retrieval quality report | Medium |
| `list_workflow_templates` | `()` | Static agent workflow recipes | Very low |
| `read_codebase_mapping_config` | `(project_root)` | Existing config, manifest, and hook status | Very low |
| `draft_codebase_mapping_config` | `(project_root, project_name=None)` | Reviewable config draft; no writes | Low |
| `store_codebase_mapping_config` | `(project_root, config, overwrite=False)` | Validate and write `.engram/config.json` | Write |
| `preview_codebase_mapping` | `(project_root, mode='bootstrap', domain=None, budget_chars=6000)` | Dry-run selected mapping domains without creating a job | Low |
| `prepare_codebase_mapping` | `(project_root, mode='bootstrap', domain=None, budget_chars=6000)` | Agent-native codebase mapping job | Medium |
| `read_codebase_mapping_context` | `(job_id, domain, part_index=0)` | Bounded repo context part plus source-drift receipt for active agent synthesis | Medium |
| `store_codebase_mapping_result` | `(job_id, domain, content, force=False)` | Store agent-authored architecture memory; blocks stale source by default | Write |
| `install_codebase_mapping_hook` | `(project_root, overwrite=False)` | Install non-blocking post-commit evolve hook | Write |
| `audit_memory_metadata` | `(limit=100, offset=0, project=None)` | Metadata drift report | Very low |
| `repair_memory_metadata` | `(keys, dry_run=True)` | Dry-run or selected repair results | — |
| `delete_memory` | `(key)` | Confirmation | — |

## Chunking Strategy
- Split on markdown headers (`#`, `##`, `###`) first
- Fall back to double-newline paragraph splits
- Max chunk size: 800 chars (tunable)
- Memory OS chunks are stored in the SQLite ledger and indexed in LanceDB with: `parent_key`, `chunk_id`, `chunk_index`, `title`, `tags`, project/domain/status metadata, and citation fields. Legacy direct mode still mirrors chunks into ChromaDB for compatibility.
- Chunk IDs: `{md5(key)}_{chunk_index}` for stable referencing

## Milestones

### v0.1 — Core (complete)
- [x] Project structure and plan
- [x] `core/embedder.py` — model loading, embed text/query
- [x] `core/chunker.py` — markdown-aware chunking
- [x] `core/memory_manager.py` — store/retrieve/search/delete
- [x] `server.py` — FastMCP with all 6 tools
- [x] `install.py` — venv setup, dependency install, config generation
- [x] `requirements.txt`

### v0.2 — Web Dashboard (complete)
- [x] Flask web UI
- [x] Grid/List views with chunk count, tag chips
- [x] Search UI backed by real semantic search
- [x] Full CRUD from browser

### v0.3 — Quality of Life (complete)
- [x] Memory templates (project, decision, reference, snippet)
- [x] Tag-based filtering in search
- [x] Export/import (JSON bundle)
- [x] Stats endpoint (total memories, total chunks, index size)

## v0.4 — Polish and Reliability (complete)

### Webui Fixes
- [x] Fix JSON serialization bug in dashboard edit/create form — special
      characters (backticks, dashes, angle brackets) in content field break
      JSON.parse on submit. Properly escape content before POST.
- [x] Remove hardcoded character limit on content textarea in the dashboard
      form — the 15K limit is enforced server-side, the UI shouldn't
      silently truncate or error before submission.

### Engram Protocol
- [ ] Add v0.4 section to AGENTS.md template with forward-slash key warning
      and 15K char guidance baked in as defaults

### Reliability
- [x] Add integration test: store → search → retrieve_chunk → delete cycle
      run against a live server instance (python server.py --self-test)
- [x] Add health check endpoint: GET /health returns server status, model
      load state, memory count, chunk count (webui.py + server.py --health)

## v0.5 — Agent-Native Tool Surface

- [x] Add `memory_protocol` discovery tool for the retrieval ladder, aliases, and warnings.
- [x] Add filtered `search_memories`, paginated `list_memories`, and `context_pack` for compact working sets.
- [x] Add verb-friendly aliases: `find_memories`, `read_chunk`, `read_memory`, and `write_memory`.
- [x] Add `prepare_memory` no-write draft gate before storing.
- [x] Add `audit_memory_metadata` and dry-run-first `repair_memory_metadata` for JSON metadata hygiene.
- [x] Preserve compatibility text wrappers while keeping structured tools canonical.

## v0.6 — Agent Operating Layer

- [x] Add progressive-discovery protocol groups for stable retrieval and beta expansion surfaces.
- [x] Add typed graph edge storage with evidence-first relationship traversal.
- [x] Add GraphStore persistence boundary so JSON graph data can migrate to a future graph DB backend.
- [x] Add graph MCP tools for edge listing, impact scans, and read-only audits.
- [x] Add source intake draft storage for transcripts, logs, scans, and handoffs.
- [x] Add source intake MCP tools for prepare/list/read/discard/promote flows.
- [x] Add context pack receipts so agents can see chunk selection and budget accounting.
- [x] Add token usage telemetry and a Token Lens dashboard for Engram-attributed estimates.
- [x] Add operation job/event seams for long-running import, scan, and maintenance workflows.
- [x] Add deterministic agent reliability harness for retrieval, budget, and token-estimate regression checks.
- [x] Add provider-neutral codebase mapping tools where the connected agent, not a hardcoded subprocess, performs synthesis.

## v0.7 — Retrieval Quality and Source Reviewability

- [x] Add named no-write ingestion pipelines for transcripts, code scans, design docs, handoffs, and generic sources.
- [x] Add chunk preview helpers and WebUI/API surfaces so agents can inspect chunk boundaries before storing.
- [x] Add preview-only local path source connector helpers that produce draft arguments without importing memory.
- [x] Add opt-in `retrieval_mode="hybrid"` for identifier-heavy queries while preserving semantic retrieval as default.
- [x] Add grounded citations to `context_pack` chunk output and receipts.
- [x] Add MCP/WebUI retrieval eval surfaces backed by the deterministic reliability harness.
- [x] Add static workflow templates for common agent flows such as repo resume, source decision extraction, brownfield mapping, and retrieval quality review.

## Engram 1.0 — Memory OS Rebuild

Engram 1.0 is now the full local Memory OS rebuild described in
`docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md`. Older local-core 1.0 release docs have
been archived under `docs/archive/legacy-local-core-1-0/` so future work does
not confuse "readiness gates around Chroma/JSON" with the new product target.

The active 1.0 rebuild includes:

- SQLite ledger for durable metadata, migrations, jobs, receipts, aliases,
  transactions, snapshots, entities, and concepts.
- Content-addressed source store for raw, normalized, and extracted evidence.
- LanceDB as the live local retrieval index.
- Kuzu as the live local graph store.
- `engramd` as the single owner of SQLite, source store writes, LanceDB, Kuzu,
  embedding jobs, migrations, repairs, transactions, and background jobs.
- Thin MCP clients as the normal agent-facing entrypoint.
- Evidence-first document intelligence with mandatory visual/OCR coverage when
  visual material may carry meaning.
- Cross-document and cross-book concept graphing for design books and other
  source corpora.
- Retrieval planner, context compiler, project capsules, contradiction queue,
  local prompt-injection firewall, memory transactions, snapshots, golden eval
  packs, skill-pack export, portable memory passport, and local Memory
  Inspector.

Active tracked docs:

- `docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md` — canonical rebuild spec.
- `docs/superpowers/plans/2026-05-13-engram-memory-os-rebuild-1-0-plan.md` —
  active implementation plan.
- `docs/ENGRAM_BACKEND_EVAL_2026_05_13.md` — prior backend evidence used by the
  rebuild, not the final target.
- `docs/ENGRAM_HOSTED_SELLABLE_CHECKLIST.md` — post-1.0 hosted/commercial
  checklist.

Rebuild 1.0 phases:

- [x] Phase 0: baseline, archive legacy docs, freeze rebuild scope.
- [x] Phase 1: SQLite ledger, content-addressed source store, legacy JSON
      migration, snapshots, transactions, entities, concepts, local firewall
      tables, export/restore.
- [x] Phase 2: LanceDB retrieval, Chroma legacy adapter, full-text/hybrid
      search, retrieval planner, golden eval packs.
- [x] Phase 3: Kuzu graph store, entity/concept graph, cross-book relationships,
      contradiction/supersession, graph path and impact tools.
- [x] Phase 4: document intelligence, OCR/vision adapters, coverage maps,
      licensing metadata, draft analysis, promotion transactions.
- [x] Phase 5: agent workflows, context compiler, project capsules, design
      knowledge compiler, skill-pack export, answer replay.
- [x] Phase 6: local Memory Inspector for migration, imports, drafts, graph,
      receipts, quality, jobs, firewall, snapshots, coverage, and skill packs.

Release gate docs:

- `docs/ENGRAM_MEMORY_OS_1_0_RELEASE_CHECKLIST.md`
- `docs/ENGRAM_MEMORY_OS_1_0_MIGRATION_GUIDE.md`

Post-1.0 is hosted work only: hosted sync, hosted tenant auth, billing, hosted
MCP/API gateway, hosted collaboration bridge, hosted eval platform, marketplace,
and commercial packaging.

## Engram Knowledge Contract v0 - Local Agent Contract Hardening

EKC v0 is a planned local product enhancement, not a hosted feature and not a
Pinecone/Nexus dependency. It adds one MCP-facing `query_knowledge` contract,
one deterministic `project_capsule` artifact, and one project-orientation eval.

Tracked docs:

- `docs/superpowers/specs/2026-05-13-engram-knowledge-contract-v0-design.md`
- `docs/superpowers/plans/2026-05-13-engram-knowledge-contract-v0-plan.md`

Key constraints:

- no local KnowQL clone
- no Pinecone dependency
- no autonomous compiler in v0
- no automatic durable memory writes
- unsupported inference defaults to forbidden
- artifact-level or chunk-level citations are acceptable for v0; locator-level
  citations remain future work.

## Key Decisions
- **SQLite ledger for rebuilt 1.0:** SQLite becomes the durable operational ledger for metadata, jobs, receipts, entities, concepts, transactions, snapshots, aliases, and import/export manifests.
- **Content-addressed source store:** Raw and normalized evidence lives outside the ledger in portable content-addressed artifacts.
- **LanceDB for rebuilt retrieval:** LanceDB is the target live retrieval index for rebuilt 1.0, with Chroma retained only as a legacy migration/rollback adapter.
- **Kuzu for rebuilt graph:** Kuzu is the target live graph store for rebuilt 1.0, with JSON graph records imported as migration evidence.
- **Daemon ownership:** `engramd` owns SQLite, source store writes, LanceDB, Kuzu, embeddings, jobs, repairs, migrations, and transactions; MCP stdio servers are thin clients.
- **Local embeddings only:** No API cost, no privacy exposure, works offline
- **No automatic memory writes from agents:** Agents must explicitly call `store_memory`. No surprise writes.
- **Review helpers stay no-write:** Chunk preview, source connector preview, workflow templates, and pipeline listing must never promote active memories.
- **Retrieval planner over manual mode-picking:** Agents should get an inspectable retrieval plan that chooses vector, full-text, graph, capsule, document evidence, and contradiction checks within budget.
- **Token-proportional retrieval:** Agents should prefer search snippets, chunks, and context packs before full memory reads.
- **Provider-neutral synthesis:** Codebase mapping prepares bounded context and source receipts; the connected agent performs synthesis.
- **Review-first document intelligence:** Document imports, including OCR/vision extraction for image-bearing sources, create evidence and drafts before any active memory promotion.
- **Prompt-injection firewall:** Imported source instructions are evidence, not guidance, unless reviewed and promoted through trusted workflows.
- **Cross-document graph reasoning:** Books, documents, figures, tables, concepts, claims, and memories must connect through evidence-bearing graph edges.
- **Post-1.0 equals hosted:** Hosted sync, tenant auth, billing, hosted collaboration bridge, and hosted MCP/API gateway do not define local rebuild 1.0.
