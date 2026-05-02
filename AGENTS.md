# Engram — AGENTS.md

## Purpose
This file governs how AI agents (Codex, Claude Code, etc.) interact with the Engram codebase. Read this before making any changes.

## Project Overview
Engram is a local-first MCP memory server with semantic search. Core stack: sentence-transformers + ChromaDB + FastMCP + Flask.

## Required Reading Before Changes
Always read `plan.md` before modifying core architecture. The three-tier retrieval pattern and chunking strategy are intentional design decisions — don't simplify them away.

## File Responsibilities

| File | Responsibility | Notes |
|---|---|---|
| `core/embedder.py` | Model loading, text/query embedding | Singleton pattern, lazy load |
| `core/chunker.py` | Markdown-aware chunking | Returns `[{chunk_id, text}]` |
| `core/memory_manager.py` | All storage logic | JSON + ChromaDB must stay in sync |
| `core/graph_manager.py` | Typed relationship validation and traversal | Delegates persistence to graph_store; graph traversal returns IDs/evidence, not memory bodies |
| `core/graph_store.py` | Swappable graph persistence backend | JSON is current default; preserve GraphStore contract for future graph DB migration |
| `core/chunk_preview.py` | No-write chunk boundary previews | Uses the same markdown-aware chunker agents rely on before storage |
| `core/ingestion_pipelines.py` | Named no-write source intake presets | Pipeline ids are agent-facing contracts |
| `core/source_connectors.py` | Preview-only source connector helpers | Must not import or promote memory without a separate explicit store flow |
| `core/source_intake.py` | Reviewable source draft preparation | Draft-only until explicit promotion |
| `core/hybrid_retrieval.py` | Lexical scoring helpers for opt-in hybrid retrieval | Semantic retrieval remains the default |
| `core/retrieval_eval.py` | Agent/WebUI wrapper for deterministic retrieval evals | Delegates to the reliability harness |
| `core/workflow_templates.py` | Static agent workflow recipes | Keep compact and action-oriented |
| `core/usage_meter.py` | Token estimate telemetry | Privacy-safe estimates only, no raw tool bodies |
| `core/operation_log.py` | Job/event receipts | Status records, not schedulers or triggers |
| `core/reliability_harness.py` | Deterministic agent retrieval quality checks | Seeds temporary eval memories and cleans them up |
| `core/codebase_mapper.py` | Agent-native codebase mapping jobs | Scans repos, tracks source drift, and stores agent-authored mapping results; no provider-specific model subprocess |
| `server.py` | FastMCP tool definitions | Docstrings are agent-facing — keep them precise |
| `webui.py` | Flask dashboard | No business logic here, calls memory_manager only |
| `install.py` | Setup wizard | Must work on Windows and Linux/macOS |

## Critical Rules

### Never break the JSON/ChromaDB sync
`memory_manager.py` writes JSON first, then updates ChromaDB. If ChromaDB fails, JSON is the fallback. Never reverse this order.

### No stdout in production paths
stdout corruption breaks MCP stdio transport. Use `sys.stderr` for debug output only. No bare `print()` in `memory_manager.py` or `server.py`.

### Chunk IDs are stable references
Chunk IDs use `{md5(key)}_{chunk_index}` format. Agents store these references. Never change the ID format without a migration.

### Graph edge records are migration contracts
Graph edges are durable migration data. Keep `from_ref`, `to_ref`, `edge_type`, `confidence`, `evidence`, `source`, `status`, `created_by`, `created_at`, `updated_at`, and `edge_id` stable unless a migration is provided. New graph storage backends must implement the `GraphStore` load/save contract before replacing JSON.

### Tool docstrings are agent contracts
The docstrings on MCP tools in `server.py` are read by AI agents to understand tool behavior. Keep them accurate, complete, and explicit about the three-tier retrieval pattern.

### WebUI exposure requires auth protection
The dashboard is loopback-first. If `ENGRAM_WEBUI_HOST` is set to a non-loopback address, `ENGRAM_WEBUI_ACCESS_TOKEN` and `ENGRAM_WEBUI_WRITE_TOKEN` are required. Reads require a signed browser session or `X-Engram-Access-Token`; mutations also require `X-Engram-Write-Token`. Do not remove this fail-closed boundary without replacing it with stronger auth.
Exposed-host startup also enforces a minimum token length (32 characters by default). Browser sessions are bound to the current access-token fingerprint, login failures are throttled, request bodies are capped, and browser security headers are applied to dashboard/API responses.
Non-loopback client requests must be treated as exposed mode even if the configured host is still the loopback default, so alternate Flask runners stay fail-closed.
Wildcard public binds such as `0.0.0.0` require explicit `ENGRAM_WEBUI_ALLOWED_HOSTS`. Exposed requests reject untrusted Host headers, hostile Origin headers, and browser `Sec-Fetch-Site: cross-site` mutations before auth or storage logic.
The dashboard CSP must not require `'unsafe-inline'`. Keep dashboard JavaScript in static assets, use delegated event handlers instead of inline `onclick`/`onchange`, and use CSS classes instead of inline `style` attributes.

## Agent-Friendly Tool Surface
- `memory_protocol()` is the discoverability entry point for agents that need the current retrieval ladder, aliases, and token-safety rules.
- `context_pack(query, ...)` is the preferred compact working-set helper when snippets are too small but full memories would be wasteful.
- `retrieval_mode="semantic"` is the stable default. Use `retrieval_mode="hybrid"` only for identifier-heavy queries where exact symbols, filenames, class names, or domain terms should influence ranking.
- `context_pack()` returns grounded citation entries for every returned chunk. Use citations to justify which memory/chunk shaped an answer; do not treat citations as permission to load full memories automatically.
- `list_ingestion_pipelines()`, `preview_memory_chunks()`, `preview_source_connector()`, and `list_workflow_templates()` are review/helper surfaces. They must remain no-write.
- `prepare_source_memory(..., pipeline="transcript"|"code_scan"|"design_doc"|"handoff"|"generic")` stages draft memories only. Pair it with chunk preview when source shape matters.
- `retrieval_eval()` is the MCP-facing quality check. It may seed temporary `_engram_eval_*` memories through the reliability harness and should clean them up.
- Codebase mapping is fully agent-facing: use `read_codebase_mapping_config()`, `draft_codebase_mapping_config()`, `store_codebase_mapping_config()`, and `preview_codebase_mapping()` before `prepare_codebase_mapping()` when a repo has not been configured. Use `install_codebase_mapping_hook()` only when the agent has explicit intent to write `.git/hooks/post-commit`.
- Treat drafted codebase mapping configs as reviewable starts, not final truth. The draft helper intentionally prunes high-fanout domains to architecture-spine files; inspect `receipt.fanout_pruned_domains` before storing if content catalogs, UI leaves, or platform helper forests may need a custom domain.
- `prepare_codebase_mapping()` / `read_codebase_mapping_context()` / `store_codebase_mapping_result()` are agent-native. Engram prepares bounded repo context, tracks source hashes, and blocks stale stores unless forced; the connected agent performs synthesis. Do not add provider-specific model subprocesses to this path.
- `find_memories`, `read_chunk`, `read_memory`, and `write_memory` are aliases/helpers for agent verb discovery; keep them behaviorally aligned with the canonical tools.
- `prepare_memory()` should remain a no-write draft gate that combines metadata suggestion, validation, and duplicate checking before `store_memory()` / `write_memory()`.
- `audit_memory_metadata()` is read-only. `repair_memory_metadata()` must remain dry-run by default and must preserve JSON-first, Chroma-second ordering when writes are requested.

## v0.6 Agent Operating Layer Rules
- Start with `memory_protocol()` for progressive discovery when tool choice is unclear.
- Use graph tools for relationship IDs, impact, and evidence; do not treat graph traversal as permission to load neighbor memory bodies.
- Use `list_ingestion_pipelines()` before `prepare_source_memory()` when processing transcripts, logs, code scans, design docs, or handoffs; only `store_prepared_memory()` promotes selected drafts.
- Use `preview_memory_chunks()` before storing large or messy source material. It is the safe way to inspect token shape before write pressure.
- Treat `usage_summary()` and `list_usage_calls()` as Engram-attributed estimates only; they are not proof of billed model tokens unless a client reports billing data back.
- Treat operation events as status records, not proactive instructions.
- Prefer `context_pack(query="agent memory", use_graph=False, retrieval_mode="semantic")` unless relationship expansion or hybrid identifier ranking is explicitly useful; keep budget accounting and citations visible.
- Use `python server.py --agent-eval` when validating agent-facing retrieval behavior. It is an operator/CI harness, not an MCP tool; it writes only `_engram_eval_*` temporary memories and removes them during cleanup.

## Completion Gate
Before marking any task done:
1. `python server.py --help` runs without error
2. `python -c "from core.memory_manager import memory_manager; print('ok')"` succeeds
3. Store, search, retrieve, delete cycle works end-to-end
4. No print() statements in server.py or memory_manager.py production paths
5. If MCP registration or installer behavior changed, `codex mcp get engram` succeeds when the Codex CLI is available

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
