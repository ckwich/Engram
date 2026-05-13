# Engram — Persistent Semantic Memory for AI Agents

## Vision
A local-first MCP memory server that gives AI agents (Claude Code, Claude chat) genuinely useful long-term memory through semantic search, chunked retrieval, and token-efficient access patterns. Built to complement structured project documents (plan.md, AGENTS.md) — not replace them.

## Core Philosophy
- **Retrieve what's relevant, not everything.** Three-tier retrieval keeps token costs proportional to need.
- **Semantic search that actually works.** Local embeddings via sentence-transformers, not substring matching.
- **Human-readable backing store.** JSON files remain the source of truth; ChromaDB is the search index.
- **Complementary to structured docs.** Engram is fast operational memory; AGENTS.md/plan.md are canonical governance.

## Architecture

### Stack
- `sentence-transformers` — local embeddings (`all-MiniLM-L6-v2`, ~80MB, CPU-capable)
- `ChromaDB` — persistent vector store, no server required
- `FastMCP` — MCP server layer (stdio + SSE transport)
- `Flask` — web dashboard
- JSON flat files — human-readable memory backing store

### Storage Layout
```
engram/
├── data/
│   ├── memories/       # JSON flat files (one per memory, full content)
│   └── chroma/         # ChromaDB persistent vector index
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
- Each chunk stored in ChromaDB with: `parent_key`, `chunk_id`, `chunk_index`, `title`, `tags`
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

## Engram 1.0 — Finish Line

Engram 1.0 is the public, generic, local-first memory substrate release. The separate collaboration product should build on Engram through stable adapters, not inside this repository.

Status update, 2026-05-12: Engram 1.0 is the local agent-facing Memory OS core release. The release preserves the current JSON-first / Chroma-second runtime while adding migration dry runs, backend readiness reports, codebase mapping modernization, opt-in daemon routing, document disassembly, mandatory visual/OCR coverage contracts, document understanding packets with auto graph coverage proposals, and reliability gates. Hosted operation, tenant auth, live backend switching, and the collaboration product remain post-1.0 work.

Status update, 2026-05-13: Daemon-client startup is now daemon-first. When `ENGRAM_DAEMON_URL` points at loopback, MCP startup probes the daemon, autostarts `engramd.py` if needed, and skips local embedding/Chroma initialization in the adapter process. `engramd.py --doctor` and `engramd.py --stop-server-pid <pid...>` provide process hygiene without fuzzy kill-all behavior or Chroma lock-file deletion.

Status update, 2026-05-13 backend eval: Track 7's first real-corpus checkpoint says to keep Chroma and JSON graph storage live. The migrated store has 5,882 vector source records and 675 migrated graph edges; deterministic rebuild passed. A real ignored-venv LanceDB spike rebuilt/search/upsert/delete-tested the corpus but failed fresh-adapter persistence because the adapter does not reload existing tables. A real Kuzu spike persisted and reopened 675 graph edges, but concurrent opens on Windows hit the expected database lock, so Kuzu only makes sense behind the daemon if graph volume later justifies it. Stack lightening should proceed through install profiles and a daemon-client thin entrypoint, not by removing Chroma/sentence-transformers from the full local runtime.

Tracked planning docs:

- `docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md` — new rebuild spec for an agent-facing local memory OS with SQLite ledger, content-addressed sources, LanceDB retrieval, Kuzu graph reasoning, migration guarantees, document intelligence including mandatory OCR/vision coverage for visual artifacts, and optional hosted-edition direction.
- `docs/ENGRAM_BACKEND_EVAL_2026_05_13.md` — backend decision checkpoint: live Chroma/JSON remain, LanceDB/Kuzu stay optional, and safe stack lightening moves through dependency profiles plus a daemon-client thin entrypoint.
- `docs/superpowers/specs/2026-05-12-engram-1-0-memory-os-document-disassembly-design.md` — binding 1.0 Memory OS and book-scale document disassembly design, including the Book Dismantling Gate, steelman review, and post-steelman addendums.
- `docs/superpowers/plans/2026-05-12-engram-1-0-memory-os-document-disassembly-plan.md` — current executable implementation plan for getting Engram to 1.0 under the Memory OS/document-disassembly direction.
- `docs/ENGRAM_1_0_RELEASE_SPEC.md` — binding Engram 1.0 scope, invariants, release tracks, and validation gate.
- `docs/ENGRAM_1_0_IMPLEMENTATION_PLAN.md` — legacy finish-line history superseded by the Memory OS/document-disassembly implementation plan above.
- `docs/ENGRAM_1_0_TRACK_0_AUDIT.md` — repo/branch hygiene audit and evidence.
- `docs/ENGRAM_HOSTED_SELLABLE_CHECKLIST.md` — optional hosted/self-hosted readiness and commercial packaging checklist for Engram without weakening local-first core boundaries.
- `docs/POST_1_COLLABORATION_PRODUCT_HANDOFF.md` — boundary handoff for the separate collaboration product.
- `docs/COLLABORATION_PRODUCT_PRD.md` — draft PRD for that separate product.

1.0 release tracks:

- [x] Track 0: repo and branch hygiene audit; local `main` has been fast-forwarded to the planning/audit branch.
- [x] Track 1: freeze MCP/tool/data contracts, version identity, docstrings, README tables, and alias behavior.
- [x] Track 2: prove storage rebuild, import/export, backup/repair, JSON-first/Chroma-second ordering, migration round trip, and graph audit readiness.
- [x] Track 3: harden source intake, lifecycle metadata, stale exclusion, explicit draft promotion, and daemon-routed source draft lifecycle.
- [x] Track 4: modernize codebase mapping for the Memory OS runtime, including current daemon/document/migration/backend domains and data-root-aware mapping jobs.
- [x] Track 5: implement book-scale document disassembly for the local core: PDF page/text/image inventory, quality reports, mandatory visual/OCR coverage requests, artifact manifests, chunk provenance, no-write understanding packets, auto document graph coverage proposals, and review-first promotion plans.
- [x] Track 6: add opt-in daemon ownership for stable memory operations, source draft lifecycle operations, metadata updates/repair/delete, and no-write document disassembly preparation. Direct in-process mode remains supported; mapping jobs, import/export, rebuild, and live backend switching stay direct or operator-gated until a future durable job store.
- [x] Track 8: expand release reliability coverage for source intake, workflow packets, retrieval receipts, document disassembly, mandatory visual evidence coverage, graph coverage proposals, and the Book Dismantling Gate.
- [x] Track 10: publish release docs, checklist, migration notes, AGENTS.md updates, public README 1.0 framing, and the Book Dismantling Gate results.

Post-1.0 tracks:

- [ ] Track 7: run real-corpus backend decision gates for retrieval and graph storage. First checkpoint complete: keep Chroma/JSON live, keep LanceDB/Kuzu optional, and pursue stack lightening through dependency profiles plus a daemon-client thin entrypoint before any backend promotion.
- [ ] Track 9: expand WebUI operator surfaces for health, drafts, document imports, graph proposals, migration receipts, and evals without turning the dashboard into the collaboration app.
- [ ] Hosted readiness: add tenant auth, object-level authorization, queue/job health, backup/restore, support-bundle redaction, and hosted deletion/export semantics before selling hosted Engram.

1.0 does not include multi-user workspaces, permissions, comments, assignments, mentions, or rich collaboration pages. Those belong to the separate collaboration product.

## Key Decisions
- **ChromaDB over SQLite FTS:** Real cosine similarity, not substring matching
- **JSON-first / Chroma-second storage:** JSON files are authoritative and portable; ChromaDB is a rebuildable semantic index.
- **Graph backend seam before graph DB:** Keep JSON graph edges local-first now, but isolate persistence behind GraphStore so a future graph database can import the same edge contract.
- **Local embeddings only:** No API cost, no privacy exposure, works offline
- **No automatic memory writes from agents:** Agents must explicitly call `store_memory`. No surprise writes.
- **Review helpers stay no-write:** Chunk preview, source connector preview, workflow templates, and pipeline listing must never promote active memories.
- **Hybrid retrieval is opt-in:** Exact lexical/identifier scoring is useful for code and game-dev symbols, but semantic mode remains the default to avoid unnecessary ranking drift.
- **Token-proportional retrieval:** Agents should prefer search snippets, chunks, and context packs before full memory reads.
- **Provider-neutral synthesis:** Codebase mapping prepares bounded context and source receipts; the connected agent performs synthesis.
- **Review-first document intelligence:** Document imports, including OCR/vision extraction for image-bearing sources, create evidence and drafts before any active memory promotion.
