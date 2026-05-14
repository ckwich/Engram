# Engram — AGENTS.md

## Purpose
This file governs how AI agents (Codex, Claude Code, etc.) interact with the Engram codebase. Read this before making any changes.

## Project Overview
Engram 1.0 is now the full local-first, agent-facing Memory OS rebuild exposed through MCP. The target stack is `engramd` owning a SQLite ledger, content-addressed source store, LanceDB retrieval, Kuzu graph storage, embeddings, jobs, transactions, snapshots, and repairs, with thin MCP clients as the normal multi-session agent entrypoint. The current JSON/Chroma runtime is legacy compatibility and migration input; keep it recoverable while daemon-owned Memory OS services become the normal stable path.

## Required Reading Before Changes
Always read `plan.md` and `docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md` before modifying core architecture. The active implementation plan is `docs/superpowers/plans/2026-05-13-engram-memory-os-rebuild-1-0-plan.md`. Archived local-core 1.0 docs under `docs/archive/legacy-local-core-1-0/` are historical only and must not be treated as the current roadmap.

## File Responsibilities

| File | Responsibility | Notes |
|---|---|---|
| `core/embedder.py` | Model loading, text/query embedding | Singleton pattern, lazy load |
| `core/chunker.py` | Markdown-aware chunking | Returns `[{chunk_id, text}]` |
| `core/memory_manager.py` | All storage logic | JSON + ChromaDB must stay in sync |
| `core/graph_manager.py` | Typed relationship validation and traversal | Delegates persistence to graph_store; graph traversal returns IDs/evidence, not memory bodies |
| `core/graph_store.py` | Swappable graph persistence backend | Preserve GraphStore contract for legacy JSON and Memory OS Kuzu paths |
| `core/kuzu_graph_store.py` | Kuzu-backed graph persistence adapter | Must preserve the GraphStore document contract; used by `core/memory_os/graph.py` under daemon-owned Memory OS runtime |
| `core/memory_os/` | Rebuilt Memory OS runtime services | SQLite ledger, content store, LanceDB retrieval, Kuzu graph, jobs, transactions, snapshots, firewall, inspector, imports, bundles, and skill packs |
| `core/memory_os/knowledge_artifacts.py` | Ledgered EKC artifact records | Explicit materialization only; `query_knowledge` may read artifacts but must not write them implicitly |
| `core/memory_os/knowledge_audit.py` | EKC evidence audit reports | Deterministic metadata audit over artifacts, citations, coverage receipts, and graph proposals |
| `core/memory_os/knowledge_artifact_families.py` | EKC higher-level artifact family packets | Entity profiles, decision packets, implementation context, and evidence bundles must be evidence-gated, cited, and read-only |
| `core/memory_os/knowledge_citations.py` | EKC citation envelope normalization and validation | Keep artifact, chunk, document, and graph citation refs explicit |
| `core/memory_os/knowledge_graph.py` | EKC bounded graph evidence packets | Surface edge IDs, evidence, and contradictions without loading neighbor memory bodies |
| `core/memory_os/knowledge_orientations.py` | EKC project-adjacent orientation packets | Source and document orientation must be read-only and report partial/no-answer when evidence is missing |
| `core/memory_os/knowledge_planner.py` | EKC accountable planner receipts | Planner receipts must expose strategy, methods, omissions, budget, failure receipts, and response status |
| `core/memory_os/knowledge_review.py` | EKC review-preparation packets | Review packets read drafts and quality warnings but must never promote memory |
| `core/backend_config.py` | Backend selection policy | Records operator intent only; defaults keep Chroma/JSON live and never promote candidates by itself |
| `core/retrieval_backend_eval.py` | No-write retrieval backend comparison gates | Compares baseline and candidate VectorIndex adapters without touching live Chroma or memories |
| `core/graph_backend_eval.py` | No-write graph parity and cross-document readiness gates | Reports edge contract health, cross-document concept links, and daemon-only Kuzu promotion requirements |
| `core/chunk_preview.py` | No-write chunk boundary previews | Uses the same markdown-aware chunker agents rely on before storage |
| `core/ingestion_pipelines.py` | Named no-write source intake presets | Pipeline ids are agent-facing contracts |
| `core/source_connectors.py` | Preview-only source connector helpers | Must not import or promote memory without a separate explicit store flow |
| `core/source_intake.py` | Reviewable source draft preparation | Draft-only until explicit promotion |
| `core/document_intelligence.py` | Provider-neutral document evidence and draft records | Document extraction, visual/OCR evidence, understanding packets, drafts, and promotion plans stay no-write until explicit promotion |
| `core/document_artifacts.py` | Portable document artifact manifests | Content-addressed refs and resume states must stay relative and safe under the Engram data root |
| `core/document_extractors.py` | Local no-write document disassembly adapters | PDF page/text/image inventory uses local tools when available and returns evidence, receipts, quality seeds, artifact manifests, visual candidates, and visual extraction requests only |
| `core/document_quality.py` | No-write document quality reports | Converts disassembly evidence into deterministic warnings and next-tool guidance; must not write repairs |
| `core/hybrid_retrieval.py` | Lexical scoring helpers for opt-in hybrid retrieval | Semantic retrieval remains the default |
| `core/memory_quality.py` | Metadata-only quality audit signals | Read-only scope/lifecycle/chunking risk report; must not load memory bodies or write repairs |
| `core/retrieval_eval.py` | Agent/WebUI wrapper for deterministic retrieval evals | Delegates to the reliability harness |
| `core/workflow_templates.py` | Static agent workflow recipes | Keep compact and action-oriented |
| `core/usage_meter.py` | Token estimate telemetry | Privacy-safe estimates only, no raw tool bodies |
| `core/operation_log.py` | Job/event receipts | Status records, not schedulers or triggers |
| `core/project_capsule.py` | No-write project capsule drafts | Reviewable read-this-first packets from context refs and quality summaries; must not store durable memory |
| `core/reliability_harness.py` | Deterministic agent retrieval quality checks | Seeds temporary eval memories and cleans them up |
| `core/codebase_mapper.py` | Agent-native codebase mapping jobs | Scans repos, tracks source drift, and stores agent-authored mapping results; no provider-specific model subprocess |
| `core/context_compiler.py` | No-write agent context packets | Static retrieval profiles plus packet assembly on top of context_pack; must not write or promote memory |
| `server.py` | FastMCP tool definitions | Docstrings are agent-facing — keep them precise |
| `server_daemon_client.py` | Thin daemon-client FastMCP entrypoint | Must not import `memory_manager`, ChromaDB, sentence-transformers, LanceDB, Kuzu, or document extractor modules |
| `webui.py` | Flask dashboard / local Memory Inspector | Keep mutation paths explicit and token-protected; Memory OS inspector routes are read-only and must not approve promotions |
| `install.py` | Setup wizard | Must work on Windows and Linux/macOS |

## Critical Rules

### Never break the JSON/ChromaDB sync
`memory_manager.py` writes JSON first, then updates ChromaDB. If ChromaDB fails, JSON is the fallback. Never reverse this order.
Concurrent stdio MCP sessions may leave multiple Engram server processes alive. Only one process may own ChromaDB; secondary processes must preserve JSON-first write behavior and fail/skip vector work without closing MCP transport.

### No stdout in production paths
stdout corruption breaks MCP stdio transport. Use `sys.stderr` for debug output only. No bare `print()` in `memory_manager.py` or `server.py`.

### Chunk IDs are stable references
Chunk IDs use `{md5(key)}_{chunk_index}` format. Agents store these references. Never change the ID format without a migration.

### Graph edge records are migration contracts
Graph edges are durable migration data. Keep `from_ref`, `to_ref`, `edge_type`, `confidence`, `evidence`, `source`, `status`, `created_by`, `created_at`, `updated_at`, and `edge_id` stable unless a migration is provided. New graph storage backends must implement the `GraphStore` load/save contract before replacing JSON. Cross-document/book concept links are first-class graph data; use typed edges such as `related_to`, `same_as`, `similar_to`, `extends`, `refines`, `applies_to`, `synthesizes`, `supports`, `contradicts`, `example_of`, `illustrates`, and `cites` with source/document refs and evidence.

### Tool docstrings are agent contracts
The docstrings on MCP tools in `server.py` are read by AI agents to understand tool behavior. Keep them accurate, complete, and explicit about the three-tier retrieval pattern.

### WebUI exposure requires auth protection
The dashboard is loopback-first. If `ENGRAM_WEBUI_HOST` is set to a non-loopback address, `ENGRAM_WEBUI_ACCESS_TOKEN` and `ENGRAM_WEBUI_WRITE_TOKEN` are required. Reads require a signed browser session or `X-Engram-Access-Token`; mutations also require `X-Engram-Write-Token`. Do not remove this fail-closed boundary without replacing it with stronger auth.
Exposed-host startup also enforces a minimum token length (32 characters by default). Browser sessions are bound to the current access-token fingerprint, login failures are throttled, request bodies are capped, and browser security headers are applied to dashboard/API responses.
Non-loopback client requests must be treated as exposed mode even if the configured host is still the loopback default, so alternate Flask runners stay fail-closed.
Wildcard public binds such as `0.0.0.0` require explicit `ENGRAM_WEBUI_ALLOWED_HOSTS`. Exposed requests reject untrusted Host headers, hostile Origin headers, and browser `Sec-Fetch-Site: cross-site` mutations before auth or storage logic.
The dashboard CSP must not require `'unsafe-inline'`. Keep dashboard JavaScript in static assets, use delegated event handlers instead of inline `onclick`/`onchange`, and use CSS classes instead of inline `style` attributes.

## Agent-Friendly Tool Surface
- Product version and MCP protocol version are separate contracts. Keep the product identity in `server.py`, `memory_protocol()`, README, and release docs aligned, while preserving protocol `version` / `schema_version` compatibility unless an explicit migration is planned.
- `memory_protocol()` is the discoverability entry point for agents that need the current retrieval ladder, aliases, and token-safety rules.
- For ordinary multi-session agent work, use `server_daemon_client.py` with a running loopback `engramd` daemon. Use `server.py` direct mode only for local debug, compatibility checks, or deliberate single-process development.
- `context_pack(query, ...)` is the preferred compact working-set helper when snippets are too small but full memories would be wasteful.
- `list_context_profiles()`, `prepare_context(task, ...)`, `make_handoff(task, ...)`, and `prepare_project_capsule(project, ...)` are no-write agent workflow helpers for task-focused context packets, resume handoffs, and reviewable project capsules. They wrap context-pack retrieval with profile defaults, receipts, warnings, next actions, and citation refs; they must not promote memory or hide citations.
- Use `query_knowledge` for project, source, document orientation, review preparation, evidence audit, bounded graph evidence, and cited higher-level artifact families such as entity profiles, decision packets, implementation context, and evidence bundles when the thin daemon client advertises EKC 1.0. The request/response envelope remains `engram.knowledge.*.v0` for compatibility, but the evaluated workflow set is stable. It is a read-only serving contract. It may read ledgered EKC artifacts, orientation records, drafts, quality receipts, graph proposals, entities, documents, and chunks when present, but it must not be treated as permission to write, promote memory, or load neighbor memory bodies.
- `retrieval_mode="semantic"` is the stable default. Use `retrieval_mode="hybrid"` only for identifier-heavy queries where exact symbols, filenames, class names, or domain terms should influence ranking.
- `context_pack()` returns grounded citation entries for every returned chunk. Use citations to justify which memory/chunk shaped an answer; do not treat citations as permission to load full memories automatically.
- `list_ingestion_pipelines()`, `preview_memory_chunks()`, `preview_source_connector()`, and `list_workflow_templates()` are review/helper surfaces. They must remain no-write.
- `list_document_extractors()`, `preview_document_source_connector()`, `prepare_document_disassembly()`, `prepare_document_extraction_request()`, `prepare_document_extraction_result()`, `preview_document_extraction()`, `prepare_document_understanding_packet()`, `prepare_document_draft()`, `prepare_document_promotion_transaction()`, `prepare_visual_extraction_request()`, and `preview_visual_extraction()` are review/helper surfaces. They must remain no-write and must report evidence/provenance rather than promoting active memories. Visual/table/page-crop evidence must retain page number, source artifact id, coordinates/bounding boxes when available, confidence, and extractor id. `prepare_visual_extraction_request()` marks visual interpretation and per-image-ref coverage as required; pass that request back to `preview_visual_extraction()` when coverage must be enforced. Understanding packets normalize agent-supplied synthesis into candidates and supplied plus auto-generated graph coverage proposals; Engram must not invent the document analysis itself or promote graph edges without review.
- `prepare_source_memory(..., pipeline="transcript"|"code_scan"|"design_doc"|"handoff"|"generic")` stages draft memories only. Pair it with chunk preview when source shape matters.
- `retrieval_eval()` is the MCP-facing quality check. It may seed temporary `_engram_eval_*` memories through the reliability harness and should clean them up.
- Codebase mapping is fully agent-facing: use `read_codebase_mapping_config()`, `draft_codebase_mapping_config()`, `store_codebase_mapping_config()`, and `preview_codebase_mapping()` before `prepare_codebase_mapping()` when a repo has not been configured. Use `install_codebase_mapping_hook()` only when the agent has explicit intent to write `.git/hooks/post-commit`.
- Treat drafted codebase mapping configs as reviewable starts, not final truth. The draft helper intentionally prunes high-fanout domains to architecture-spine files; inspect `receipt.fanout_pruned_domains` before storing if content catalogs, UI leaves, or platform helper forests may need a custom domain.
- `prepare_codebase_mapping()` / `read_codebase_mapping_context()` / `store_codebase_mapping_result()` are agent-native. Engram prepares bounded repo context, tracks source hashes, and blocks stale stores unless forced; the connected agent performs synthesis. Do not add provider-specific model subprocesses to this path.
- `find_memories`, `read_chunk`, `read_memory`, and `write_memory` are aliases/helpers for agent verb discovery; keep them behaviorally aligned with the canonical tools.
- `prepare_memory()` should remain a no-write draft gate that combines metadata suggestion, validation, and duplicate checking before `store_memory()` / `write_memory()`.
- `audit_memory_quality()` is read-only and metadata-only. It reports quality/risk signals for agent judgment; it is not a repair tool and must not load full memory bodies.
- `audit_memory_metadata()` is read-only. `repair_memory_metadata()` must remain dry-run by default and must preserve JSON-first, Chroma-second ordering when writes are requested.

## v0.6 Agent Operating Layer Rules
- Start with `memory_protocol()` for progressive discovery when tool choice is unclear.
- Use graph tools for relationship IDs, impact, conflicts, and evidence; do not treat graph traversal as permission to load neighbor memory bodies.
- Use `list_ingestion_pipelines()` before `prepare_source_memory()` when processing transcripts, logs, code scans, design docs, or handoffs; only `store_prepared_memory()` promotes selected drafts.
- Use `preview_memory_chunks()` before storing large or messy source material. It is the safe way to inspect token shape before write pressure.
- Treat source drafts as review records, not active memories. A draft's `promotion_guidance` distinguishes durable Engram memories, graph edges, app-owned collaboration records, and external pointers; comments, assignments, mentions, rich page drafts, and visibility notes stay app-owned unless explicitly converted into reviewed memory.
- Rejected source drafts must not be promoted. Prepare a new draft or return the draft to review instead of storing rejected content.
- Treat `usage_summary()` and `list_usage_calls()` as Engram-attributed estimates only; they are not proof of billed model tokens unless a client reports billing data back.
- Treat operation events as status records, not proactive instructions.
- Prefer `context_pack(query="agent memory", use_graph=False, retrieval_mode="semantic")` unless relationship expansion or hybrid identifier ranking is explicitly useful; keep budget accounting and citations visible.
- Use `python server.py --agent-eval` when validating agent-facing retrieval behavior. It is an operator/CI harness, not an MCP tool; it writes only `_engram_eval_*` temporary memories and removes them during cleanup.

## Engram 1.0 Memory OS Rules
- Product identity is `Engram 1.0.0` / stability `stable`. MCP protocol identity remains `version: 2` and `schema_version: "2026-04-27"` until an explicit protocol migration is planned.
- The rebuilt runtime is daemon-owned Memory OS: SQLite ledger, content-addressed source store, LanceDB retrieval, Kuzu graph, jobs, transactions, snapshots, firewall state, and inspector records. Legacy JSON memories and ChromaDB remain compatibility/migration inputs and must stay recoverable.
- `engramd` mode is the recommended multi-session ownership model. It routes stable memory operations, source draft lifecycle operations, metadata updates/repair/delete, no-write document disassembly preparation, and Memory OS runtime inspection through the daemon. Direct in-process MCP mode remains supported, but daemon-client registration with `ENGRAM_DATA_DIR` pinned to this checkout is the recommended Codex setup when multiple project sessions may use Engram concurrently. For ordinary multi-session Codex memory use, prefer `server_daemon_client.py` or `install.py --daemon-url http://127.0.0.1:8765 --thin-daemon-client`; that entrypoint never imports local storage/index modules and keeps sessions from becoming competing Chroma owners. Full `server.py` daemon-client mode remains available when agents need the broader beta tool surface.
- Legacy backend config remains intent/reporting for old direct paths. Do not silently switch legacy `memory_manager` search or legacy JSON graph traversal based only on `ENGRAM_RETRIEVAL_BACKEND` or `ENGRAM_GRAPH_BACKEND`; Memory OS LanceDB/Kuzu ownership belongs behind `engramd` and its explicit runtime services.
- Use `python engramd.py --doctor` for process hygiene before assuming ChromaDB is broken. Stop stale MCP adapter processes only by explicit PID with `python engramd.py --stop-server-pid <pid...>`; do not delete lock files or kill fuzzy process matches.
- Codebase mapping is agent-facing and provider-neutral. Engram prepares source-hashed context and drift receipts; the connected agent writes the synthesis. Do not add hardcoded model subprocesses to mapping.
- Document intelligence is evidence-first. Local PDF disassembly, artifact manifests, quality reports, mandatory visual/OCR coverage requests, understanding packets, draft proposals, graph proposals, and promotion transactions are no-write review surfaces until explicit memory or graph promotion.
- The local Memory Inspector is read-only for Memory OS state. It may surface jobs, transactions, graph edges, entities, concepts, firewall events, coverage maps, snapshots, and skill packs; it must not silently approve drafts, firewall events, graph proposals, or promotion transactions.
- The Book Dismantling Gate in `server.py --agent-eval` is the minimum release proof for rich document-intelligence claims. Optional local PDF smoke tests may use `C:\Users\colek\Downloads\Design Books`, but never commit copyrighted PDFs, extracted book text, rendered page images, OCR output, or table exports.
- Hosted auth, tenant isolation, billing, team collaboration, rich pages, comments, assignments, mentions, role-aware visibility, and team workflow UI remain outside Engram core unless a future spec changes the product boundary.

## Completion Gate
Before marking any task done:
1. `python server.py --help` runs without error
2. `python -c "from core.memory_manager import memory_manager; print('ok')"` succeeds
3. Daemon process health and store/search/read/delete smoke gates pass through `python engramd.py --doctor` and `python engramd.py --smoke-test`
4. Direct store, search, retrieve, delete cycle works end-to-end through `python server.py --self-test` in an isolated `ENGRAM_DATA_DIR` when a live daemon owns the default store
5. Agent-facing retrieval/source/document workflow gates pass through `python server.py --agent-eval` in an isolated `ENGRAM_DATA_DIR` when a live daemon owns the default store
6. The pre-EKC readiness lane in `docs/RELEASE_GATES.md` passes for architecture boundaries, thin daemon-client imports, no-write policy metadata, and backend readiness wrappers when those areas were touched
7. No new bare `print()` statements are introduced in `server.py` or `core/memory_manager.py` production paths
8. If MCP registration or installer behavior changed, `codex mcp get engram` succeeds when the Codex CLI is available

## Development Environment
- Python 3.10+
- Virtual environment at `./venv`
- Dependencies: `pip install -r requirements.txt`
- First run downloads `all-MiniLM-L6-v2` (~80MB) — this is expected

## Three-Tier Retrieval — The Core Pattern
Agents MUST follow this pattern for token efficiency:

```
Step 1: search_memories(query, limit=5)
   → Returns scored snippets. Identify relevant key + chunk_id.

Step 2 (if needed): retrieve_chunk(key, chunk_id)
   → Returns one chunk. Usually sufficient.

Optional shortcut: context_pack(query, max_chunks=5)
   → Search + dedupe + retrieve bounded chunks in one call.

Step 3 (if needed): retrieve_memory(key)
   → Returns full memory. Use sparingly.
```

Never call `retrieve_memory` without first checking if a chunk is sufficient.
