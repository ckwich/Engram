# Engram

### Local-first semantic memory for AI agents

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP Compliant](https://img.shields.io/badge/MCP-compliant-green.svg)](https://modelcontextprotocol.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Platform: Windows | macOS | Linux](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()

Engram 1.0 is a local Model Context Protocol (MCP) server that gives AI agents a durable, searchable memory across sessions.

The rebuilt 1.0 runtime uses a daemon-owned SQLite ledger, content-addressed source artifacts, LanceDB retrieval, and Kuzu graph storage. Legacy JSON memories and ChromaDB remain as compatibility and migration inputs until every caller is moved through the rebuilt runtime.

Engram is built around one simple idea: agents should retrieve the smallest useful context first, then expand only when needed.

---

## Why Engram?

Most agent memory systems fail in one of two ways: they forget too much between sessions, or they load too much context into every session.

Engram aims for a middle path:

- Keep memories on your machine.
- Search semantically instead of relying on exact keywords.
- Retrieve snippets before chunks, and chunks before full documents.
- Give agents receipts for what they loaded and why.
- Dismantle messy source material into reviewable evidence before it becomes memory.
- Keep durable memory readable, editable, and recoverable.

The result is a practical intersession memory layer for coding agents, research agents, local assistants, and MCP clients that need continuity without dumping an entire knowledge base into every prompt.

---

## What Engram Provides

### Memory Server

- **Daemon-owned Memory OS runtime** through `engramd`, with a thin MCP client entrypoint that avoids local storage/index imports.
- **SQLite ledger** for metadata, jobs, transactions, snapshots, aliases, entities, concepts, receipts, and migration state.
- **Content-addressed source store** for raw, normalized, and extracted evidence artifacts.
- **LanceDB retrieval and Kuzu graph storage** inside the rebuilt local runtime.
- **Legacy JSON/Chroma compatibility** kept readable and recoverable during migration.
- **Markdown-aware chunking** that preserves headings and paragraph boundaries where possible.
- **Deduplication checks** before writes, with explicit `force=True` override.
- **Metadata filters** for project, domain, tags, lifecycle status, and canonical memories.
- **Relationship links** between memories, including bidirectional traversal.
- **Staleness surfacing** for old or potentially code-stale memories.

### Agent-Facing Retrieval

- **Three-tier retrieval**: search snippets, retrieve chunks, then read full memories only when necessary.
- **Context packs** that search, dedupe, and retrieve a bounded working set in one call.
- **Context profiles, packets, and handoffs** that compile task-focused, cited working context without writing memory.
- **Protocol discovery** so an agent can ask Engram how to use the memory ladder.
- **Session pins** that temporarily promote known memories without changing stored metadata.
- **Token-use estimates** for Engram-attributed calls.
- **Retrieval eval harness** for checking that the memory ladder still behaves as expected.

### Source and Codebase Workflows

- **Source intake drafts** for transcripts, logs, handoffs, design notes, and other reviewable inputs.
- **No-write previews** for chunking and local source connector intake.
- **Named ingestion pipelines** for common source types.
- **Codebase mapping jobs** that gather bounded repository context while the connected agent performs synthesis.
- **Source drift detection** so stale mapping results are blocked unless explicitly forced.

### Document Intelligence

- **Local PDF disassembly** that inventories pages, text coverage, image-bearing pages, and extraction receipts without writing active memories.
- **Quality reports** that flag no-text pages, image-heavy pages, failed pages, and visual-review needs.
- **Portable artifact manifests** with page-level resume states and content-addressed source references.
- **Mandatory OCR/vision work requests** for image-bearing pages or regions, including per-artifact coverage requirements and expected provenance contracts.
- **Understanding packets** that normalize agent-supplied summaries, claims, concepts, entities, high-value sections, draft memory proposals, and supplied plus auto-generated graph coverage proposals.
- **Review-first promotion plans** so document evidence becomes durable memory or graph edges only after explicit review.

### Web Dashboard

- Browse, search, create, update, and delete memories.
- Review stale memories and related memories.
- Inspect usage estimates and retrieval eval status.
- Inspect Memory OS runtime state, jobs, transactions, coverage maps, firewall events, graph edges, entities, concepts, snapshots, and skill packs.
- Monitor disk usage and memory-store growth.
- Run locally by default, with fail-closed token protection when exposed beyond loopback.

---

## Retrieval Model

Engram's core workflow is the retrieval ladder.

```text
1. search_memories("release checklist", limit=5)
   -> scored snippets with keys and chunk IDs

2. retrieve_chunk("project_release_notes", chunk_id=2)
   -> one focused chunk

3. retrieve_memory("project_release_notes")
   -> full memory, used only when the chunk is not enough
```

Most agent work should stop at step 1 or 2.

For a compact one-call working set, use `context_pack`:

```text
context_pack(
  query="release checklist",
  project="example-project",
  max_chunks=5,
  budget_chars=6000
)
```

`context_pack` returns selected chunks, citations, omitted-result counts, and budget receipts so agents can see what context they spent.

For repeated project, source, document orientation, review preparation,
evidence audit, bounded graph evidence, or higher-level artifact family packets
such as entity profiles, decision packets, implementation context, and evidence
bundles, start with `query_knowledge` when available. It returns typed EKC 1.0
responses on the compatibility `engram.knowledge.*.v0` envelope. Use
`search_memories` and `retrieve_chunk` when you need lower-level evidence
beyond the orientation, review, audit, graph, or artifact-family packet.

---

## MCP Tool Surface

Engram exposes structured MCP tools first. Text wrappers remain available for older clients, but new integrations should prefer the structured tools.

Product release identity and protocol identity are intentionally separate:
`memory_protocol()` reports product version `1.0.0`, protocol `version: 2`,
and protocol `schema_version: "2026-04-27"`.

### Discovery and Retrieval

| Tool | Purpose |
|---|---|
| `memory_protocol` | Describes the retrieval ladder and current tool contract. |
| `search_memories` | Semantic or hybrid memory search with filters and scored snippets. |
| `find_memories` | Alias for agents looking for a find verb. |
| `context_pack` | Search, dedupe, and retrieve a bounded chunk working set. |
| `list_context_profiles` | List no-write retrieval profiles for task-focused context compilation. |
| `prepare_context` | Compile a no-write, cited context packet for an agent task. |
| `make_handoff` | Generate a no-write handoff packet with context refs, citations, next steps, and validation notes. |
| `prepare_project_capsule` | Prepare a no-write project capsule draft from context refs and quality signals. |
| `query_knowledge` | Return an EKC 1.0 project, source, document orientation, review-preparation, evidence-audit, bounded graph-evidence, or evidence-gated artifact-family response with citations, policy, budget, planner, and typed errors. The envelope remains `engram.knowledge.*.v0` for compatibility. |
| `retrieve_chunk` | Retrieve one chunk by memory key and chunk ID. |
| `retrieve_chunks` | Retrieve several known chunks in one call. |
| `retrieve_memory` | Retrieve a full memory intentionally. |
| `read_chunk` | Alias for `retrieve_chunk`. |
| `read_memory` | Tier-aware helper: metadata by default, chunk with `chunk_id`, full only with `full=True`. |

### Writing and Metadata

| Tool | Purpose |
|---|---|
| `prepare_memory` | Draft key/metadata, validate, and check duplicates without writing. |
| `store_memory` | Create or update a memory. |
| `write_memory` | Alias for agents looking for a write verb. |
| `check_duplicate` | Preview semantic duplicate risk. |
| `suggest_memory_metadata` | Suggest key, title, tags, and metadata from content. |
| `validate_memory` | Validate a proposed payload. |
| `update_memory_metadata` | Update metadata without rewriting content. |
| `delete_memory` | Permanently delete a memory. |

### Organization and Quality

| Tool | Purpose |
|---|---|
| `list_memories` | Paginated memory directory with filters. |
| `audit_memory_quality` | Read-only metadata quality audit for scope, lifecycle, chunking, and retrieval-risk signals. |
| `get_related_memories` | Traverse forward and reverse memory links. |
| `get_stale_memories` | Surface stale or potentially stale memories. |
| `pin_memory` | Pin a memory for the current session. |
| `unpin_memory` | Remove a pinned memory. |
| `list_pins` | List session pins. |
| `clear_pins` | Clear session pins. |
| `audit_memory_metadata` | Read-only metadata hygiene audit. |
| `repair_memory_metadata` | Dry-run-first metadata repair. |
| `daemon_status` | Report direct mode versus opt-in `ENGRAM_DAEMON_URL` daemon-client mode. |

### Source, Graph, and Evaluation

| Tool | Purpose |
|---|---|
| `prepare_source_memory` | Create reviewable source-memory drafts. |
| `list_source_drafts` | Browse prepared source drafts. |
| `store_prepared_memory` | Promote selected drafts to stored memories. |
| `discard_source_draft` | Delete a draft. |
| `preview_memory_chunks` | Preview chunking without writing. |
| `preview_source_connector` | Preview local source intake without writing. |
| `list_document_extractors` | List bundled and external document extraction capabilities. |
| `preview_document_source_connector` | Preview local Markdown/text/HTML and URL/external parser request arguments without writing. |
| `prepare_document_disassembly` | Prepare a no-write local PDF page/text/image inventory with quality warnings, portable artifact refs, visual candidates, and an OCR/vision follow-up request. |
| `prepare_document_intake_review` | Prepare a no-write end-to-end document review packet with disassembly, text preview, quality, artifact, and missing OCR/visual/table coverage receipts. |
| `prepare_document_extraction_request` | Prepare a no-write external parser request for PDF/DOCX/image-bearing sources. |
| `prepare_document_extraction_result` | Normalize external parser output into no-write preview arguments. |
| `preview_document_extraction` | Preview document evidence and chunks without writing. |
| `prepare_document_understanding_packet` | Normalize agent-supplied summaries, claims, concepts, entities, sections, warnings, and supplied plus auto-generated graph coverage proposals without writing. |
| `prepare_document_draft` | Prepare no-write document memory/graph proposals. |
| `prepare_document_promotion_transaction` | Prepare no-write document promotion operations. |
| `prepare_document_artifact_store` | Prepare an explicit reviewed document evidence artifact-store transaction without active memory or graph promotion. |
| `store_document_artifact` | Store ledgered document evidence only when `accept=True` and the matching reviewed packet is supplied again; active memories and graph edges remain untouched. |
| `prepare_visual_extraction_request` | Prepare a no-write OCR/vision work request with mandatory per-image-ref coverage. |
| `preview_visual_extraction` | Preview OCR/vision observations without writing; pass the originating visual request to enforce coverage. |
| `list_ingestion_pipelines` | List available source-intake pipelines. |
| `migration_dry_run` | Validate legacy JSON memories against the Memory OS ledger schema without writing. |
| `memory_os_round_trip_check` | Run Memory OS import/export/restore parity checks in a migration work directory. |
| `retrieval_backend_status` | Report legacy Chroma, daemon Memory OS LanceDB readiness, backend config intent, migrated-store, rebuild-probe, and golden-comparison status without mutating data. |
| `add_graph_edge` | Store a typed relationship between refs, including document structure and visual evidence refs. |
| `list_graph_edges` | List graph edges around refs. |
| `impact_scan` | Traverse graph relationships for impact analysis. |
| `conflict_scan` | List contradiction, invalidation, and supersession graph edges without loading memory bodies. |
| `audit_graph` | Inspect graph hygiene. |
| `graph_backend_status` | Report JSON graph, optional Kuzu, backend config intent, migrated graph-edge, graph-parity, and daemon-readiness gates without switching live graph storage. |
| `usage_summary` | Summarize Engram-attributed token estimates. |
| `list_usage_calls` | Inspect recent estimated usage calls. |
| `retrieval_eval` | Run deterministic retrieval and no-write workflow-quality checks. |
| `list_workflow_templates` | List built-in agent workflow recipes. |

### Codebase Mapping

| Tool | Purpose |
|---|---|
| `read_codebase_mapping_config` | Read a repo mapping config when one exists. |
| `draft_codebase_mapping_config` | Draft a safe `.engram/config.json` without writing it. |
| `store_codebase_mapping_config` | Validate and write `.engram/config.json` with overwrite protection. |
| `preview_codebase_mapping` | Dry-run configured mapping domains without storing a job. |
| `prepare_codebase_mapping` | Prepare source-hashed, bounded repo context for agent synthesis. |
| `read_codebase_mapping_context` | Read one prepared mapping job context part. |
| `store_codebase_mapping_result` | Store an agent-authored mapping result with source-drift checks. |
| `install_codebase_mapping_hook` | Install the optional post-commit mapping hook after explicit intent. |

### Operations

| Tool | Purpose |
|---|---|
| `list_operation_jobs` | List recent local operation/job receipts. |
| `list_operation_events` | List recent local operation event records. |

### Compatibility Text Wrappers

| Tool | Purpose |
|---|---|
| `search_memories_text` | Legacy text wrapper for memory search. |
| `retrieve_chunk_text` | Legacy text wrapper for one chunk. |
| `retrieve_memory_text` | Legacy text wrapper for full-memory retrieval. |
| `list_all_memories` | Legacy text wrapper for listing memory metadata. |
| `get_related_memories_text` | Legacy text wrapper for related-memory links. |
| `get_stale_memories_text` | Legacy text wrapper for stale-memory review. |

Compatibility wrappers remain for older clients. New integrations should prefer the structured tools above.

---

## Installation

### Requirements

- Python 3.10+
- Git
- An MCP-capable client, such as Codex, Claude Code, Claude Desktop, or another MCP host

### Quick Start

```bash
git clone https://github.com/ckwich/Engram.git
cd Engram
python install.py
```

The installer creates a virtual environment, installs dependencies, downloads the local embedding model, generates configuration, and registers Engram with Codex when the `codex` CLI is available.

The first model download is roughly 80 MB.

Install profiles are split so ordinary agent sessions can stay thin:

| Profile | File | Purpose |
|---|---|---|
| Thin daemon client | `requirements-daemon-client.txt` | FastMCP adapter that talks to `engramd` without importing ChromaDB or sentence-transformers. |
| Full local core | `requirements-core.txt` | Full local daemon/direct runtime with sentence-transformers, ChromaDB compatibility, LanceDB, and Kuzu. |
| Dashboard | `requirements-dashboard.txt` | Flask dashboard dependency. |
| Backend spike | `requirements-backend-spike.txt` | Compatibility profile that currently references the full core dependency set. |
| Dev | `requirements-dev.txt` | Test and audit tooling. |

---

## MCP Client Setup

### Codex

The Codex CLI stores MCP registrations in `~/.codex/config.toml`.

Recommended multi-session setup: run one local `engramd` daemon and register
the thin daemon-client MCP entrypoint. This keeps Codex sessions from importing
or owning ChromaDB, LanceDB, Kuzu, sentence-transformers, or document extraction
state.

Windows:

```powershell
python install.py --daemon-url http://127.0.0.1:8765 --thin-daemon-client

# Manual fallback:
codex mcp add engram `
  --env ENGRAM_DATA_DIR=C:\path\to\Engram\data `
  --env ENGRAM_DAEMON_URL=http://127.0.0.1:8765 `
  -- C:\path\to\Engram\venv\Scripts\python.exe `
  C:\path\to\Engram\server_daemon_client.py
```

macOS / Linux:

```bash
python install.py --daemon-url http://127.0.0.1:8765 --thin-daemon-client

# Manual fallback:
codex mcp add engram \
  --env ENGRAM_DATA_DIR=/path/to/Engram/data \
  --env ENGRAM_DAEMON_URL=http://127.0.0.1:8765 \
  -- /path/to/Engram/venv/bin/python \
  /path/to/Engram/server_daemon_client.py
```

Direct `server.py` registration remains supported for local debug,
compatibility, and single-process development. Prefer it only when you
intentionally need the broader direct-mode surface:

```bash
codex mcp add engram -- \
  /path/to/Engram/venv/bin/python \
  /path/to/Engram/server.py
```

Open a fresh Codex thread, or restart Codex, after changing MCP registration. Existing threads may not hot-load newly added MCP servers.

Stdio clients may start one Engram process per conversation. Engram keeps JSON writes available in every process, but only one live process owns the ChromaDB vector index at a time; secondary processes skip vector indexing/search instead of closing the MCP transport. If many stale Engram processes accumulate after client crashes or app updates, close old threads or restart the MCP host before diagnosing storage failures.

### Claude Code

```bash
claude mcp add engram --scope user \
  /path/to/Engram/venv/bin/python \
  /path/to/Engram/server.py
```

Windows:

```powershell
claude mcp add engram --scope user `
  "C:\path\to\Engram\venv\Scripts\python.exe" `
  "C:\path\to\Engram\server.py"
```

### Claude Desktop

Add Engram to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "engram": {
      "command": "/path/to/Engram/venv/bin/python",
      "args": ["/path/to/Engram/server.py"]
    }
  }
}
```

### SSE Mode

Engram defaults to stdio transport for MCP clients.

For SSE transport:

```bash
python server.py --transport sse --host 127.0.0.1 --port 5100
```

Only bind to a non-loopback host when you have appropriate network controls in place.

### Local Daemon Mode

`engramd.py` starts an opt-in loopback daemon that owns the live Engram memory
store and vector index. This lets MCP stdio sessions act as clients instead of
each agent process trying to own embedded ChromaDB directly.

Terminal 1:

```bash
python engramd.py --host 127.0.0.1 --port 8765
```

By default, Engram stores local data under this repo's `data/` directory. For
isolated daemon smoke tests or alternate local stores, set `ENGRAM_DATA_DIR`
before starting `engramd` or `server.py`; memory JSON, ChromaDB, Chroma lock
files, and source intake drafts will live under that directory.

Terminal 2, before starting the MCP server process:

```bash
export ENGRAM_DAEMON_URL=http://127.0.0.1:8765
python server.py
```

PowerShell:

```powershell
$env:ENGRAM_DAEMON_URL = "http://127.0.0.1:8765"
python server.py
```

When `ENGRAM_DAEMON_URL` points at a loopback URL and the daemon is not already
reachable, `server.py` will try to start `engramd.py` before accepting MCP
traffic. This keeps daemon-client MCP adapters from becoming direct ChromaDB
owners. Set `ENGRAM_DAEMON_AUTOSTART=0` to require a manually started daemon.
Autostart writes daemon logs under `ENGRAM_DATA_DIR\operations\`.

Health check:

```bash
python engramd.py --health --host 127.0.0.1 --port 8765
```

Smoke test a running daemon:

```bash
python engramd.py --smoke-test --host 127.0.0.1 --port 8765
```

The smoke test checks duplicate risk, writes, updates metadata, dry-runs
metadata repair, searches, reads, and deletes a temporary `_engramd_smoke_*`
memory through the daemon.

Process hygiene doctor:

```bash
python engramd.py --doctor --host 127.0.0.1 --port 8765
```

The doctor reports daemon health plus this checkout's `engramd.py` and
`server.py` processes. To stop stale MCP adapter processes, pass explicit PIDs
from the doctor report:

```bash
python engramd.py --stop-server-pid 12345 12346
```

The stop command refuses to terminate `engramd.py`, one-shot CLI checks,
processes from other Engram checkouts, and the current process.

Generate MCP client config for daemon-client mode:

```bash
python server.py --generate-config --daemon-url http://127.0.0.1:8765
```

This emits `ENGRAM_DATA_DIR` and `ENGRAM_DAEMON_URL` in the generated MCP
server environment. `ENGRAM_DATA_DIR` keeps Engram pointed at this repo's
memory store even when Codex launches the MCP server while you are working in a
different project. The daemon URL is normalized by trimming trailing slashes.

For Codex sessions that span many repositories, prefer registering the MCP
server in daemon-client mode and running one local daemon. Use
`server_daemon_client.py` for the thinnest stable memory surface, or
`server.py` with `ENGRAM_DAEMON_URL` when you need the broader beta tool
surface:

```powershell
codex mcp remove engram
codex mcp add engram `
  --env ENGRAM_DATA_DIR=C:\Dev\Engram\data `
  --env ENGRAM_DAEMON_URL=http://127.0.0.1:8765 `
  -- C:\Dev\Engram\venv\Scripts\python.exe C:\Dev\Engram\server_daemon_client.py
```

Existing Codex sessions may still need a fresh tool discovery step or restart
before they see the Engram tool namespace. The important stability guarantee is
that every discovered Engram MCP adapter routes stable memory operations to the
same daemon instead of competing for embedded Chroma ownership.

Daemon mode currently routes stable memory search, duplicate checks, chunk/full
reads, writes, source draft prepare/list/discard/promotion, no-write document
disassembly preparation, metadata updates, metadata repair, and deletes through
`engramd`. The rebuilt Memory OS runtime also initializes SQLite, the
content-addressed source store, LanceDB, Kuzu, jobs, transactions, snapshots,
firewall state, and the local Memory OS inspector under the daemon owner.
Direct in-process MCP mode remains supported unless `ENGRAM_DAEMON_URL` is set.
Hosted tenant authorization is not part of local 1.0.

---

## Web Dashboard

Start the dashboard:

```bash
python webui.py
```

Then open:

```text
http://127.0.0.1:5000
```

The dashboard is loopback-first. Local use is intentionally low-friction.

If you expose the dashboard beyond loopback, Engram requires:

- `ENGRAM_WEBUI_ACCESS_TOKEN` for read access.
- `ENGRAM_WEBUI_WRITE_TOKEN` for mutating requests.
- Strong tokens, with a 32-character minimum by default.
- Host, origin, request-size, session, and browser-security checks.

See `docs/REMOTE_WEBUI.md` for remote-access setup notes.

---

## Codebase Mapping

Engram can prepare codebase mapping jobs for agents.

It does not secretly spawn a provider-specific model to write architecture summaries. Instead, it collects bounded repository context, tracks source hashes, and asks the connected agent to synthesize and store the result.

Mapping jobs are data-root aware: when `ENGRAM_DATA_DIR` is set, prepared job
records are written under `ENGRAM_DATA_DIR/codebase_mapping_jobs` instead of the
default repo `data/` folder. Engram's own draft mapping config uses Memory OS
domains for daemon runtime, document intelligence, migration, backend status,
graph, source intake, codebase mapping, reliability, WebUI, server tools, and
storage so agents can map the current 1.0 architecture instead of the older
pre-daemon shape.

Typical MCP flow:

1. `read_codebase_mapping_config(project_root)`
2. `draft_codebase_mapping_config(project_root)`
3. `store_codebase_mapping_config(project_root, config)`
4. `preview_codebase_mapping(project_root, mode="bootstrap")`
5. `prepare_codebase_mapping(project_root, mode="bootstrap")`
6. `read_codebase_mapping_context(job_id, domain, part_index)`
7. `store_codebase_mapping_result(job_id, domain, content)`

Terminal flow:

```bash
# Create .engram/config.json interactively
python engram_index.py --project /path/to/project --init

# Preview planned mapping work
python engram_index.py --project /path/to/project --mode bootstrap --dry-run

# Prepare all configured domains
python engram_index.py --project /path/to/project --mode bootstrap

# Prepare only changed domains
python engram_index.py --project /path/to/project --mode evolve

# Prepare every configured domain
python engram_index.py --project /path/to/project --mode full
```

Example `.engram/config.json`:

```json
{
  "project_name": "example_app",
  "domains": {
    "auth": {
      "file_globs": ["src/auth/**", "src/middleware/auth*"],
      "questions": [
        "How does authentication work?",
        "What trust boundaries matter?"
      ]
    },
    "billing": {
      "file_globs": ["src/billing/**", "src/payments/**"],
      "questions": [
        "How does the billing pipeline work?",
        "What external integration points exist?"
      ]
    }
  },
  "planning_paths": ["docs/"],
  "max_file_size_kb": 512
}
```

Engram skips generated directories, dependency folders, caches, obvious secret files, and symlinks that resolve outside the project root.

---

## Source Intake

Use source intake for large or noisy inputs that should be reviewed before storage:

- Meeting transcripts
- Debug logs
- Agent handoffs
- Design notes
- Research excerpts
- Code review summaries

The review flow is:

```text
prepare_source_memory -> inspect draft -> store_prepared_memory
```

Use `preview_memory_chunks`, `preview_source_connector`, `list_document_extractors`, `preview_document_source_connector`, `prepare_document_disassembly`, `prepare_document_intake_review`, `prepare_document_extraction_request`, `prepare_document_extraction_result`, `preview_document_extraction`, `prepare_document_understanding_packet`, `prepare_document_draft`, `prepare_document_promotion_transaction`, `prepare_visual_extraction_request`, or `preview_visual_extraction` when you want to inspect what Engram would ingest before any active-memory write happens. Document disassembly, extraction requests/results, understanding packets, draft proposals, promotion operation plans, and image/OCR requests or observations are evidence records, not trusted active memory, until a later explicit review path promotes them. Visual extraction requests include a `visual_evidence_contract`, per-image-ref coverage requirements, and `framework_strategy` so an agent can use native vision when available, or hand work to an external OCR/vision framework and return observations through `preview_visual_extraction`. Pass the originating visual request back into `preview_visual_extraction` when coverage matters; incomplete visual observations return `status: "partial"` with coverage warnings instead of letting a draft claim full coverage. `prepare_document_artifact_store` and `store_document_artifact` are the explicit ledgered document-evidence path; `prepare_document_artifact_store` persists only a compact review intent and digest, while `store_document_artifact(..., accept=True, review_packet=packet)` verifies the reviewed packet and source bytes before storing artifact/document/chunk/coverage records. Neither tool promotes active memories or graph edges. Visual/table evidence records preserve page number, source artifact id, coordinates/bounding boxes when available, confidence, and extractor id. Understanding packets keep synthesis provider-neutral: the connected agent supplies analysis, and Engram normalizes it into summary slots, claim/concept/entity candidates, high-value sections, low-confidence warnings, draft memory proposals, and supplied plus auto-generated graph proposals.

Source intake never auto-promotes active memories. Drafts are review records with
`status: "draft"`, `active_memory_write_performed: false`, and promotion guidance
for the four valid outcomes:

- Store selected durable content as Engram memory with `store_prepared_memory`.
- Store relationship facts as graph edges with `add_graph_edge`.
- Keep collaboration-only workflow state in the separate app.
- Keep raw source material outside Engram and reference it by `source_uri`.

Rejected drafts cannot be promoted.

---

## CLI Utilities

```bash
# MCP server, stdio transport
python server.py

# Local daemon, then opt-in MCP daemon-client mode
python engramd.py --host 127.0.0.1 --port 8765
ENGRAM_DAEMON_URL=http://127.0.0.1:8765 python server.py
python engramd.py --smoke-test --host 127.0.0.1 --port 8765

# SSE transport
python server.py --transport sse --port 5100

# Rebuild ChromaDB from JSON
python server.py --rebuild-index

# Export/import memories
python server.py --export
python server.py --import-file engram_export_YYYY-MM-DD.json

# Health and integration checks
python server.py --health
python server.py --self-test

# Agent-facing retrieval reliability harness
python server.py --agent-eval

# Generate MCP client config
python server.py --generate-config
python server.py --generate-config --daemon-url http://127.0.0.1:8765

# Memory OS migration utilities
python -m core.memory_os_migration import-legacy --legacy-dir data/memories --store-root .engram-migration/store
python -m core.memory_os_migration import-graph-edges --store-root .engram-migration/store --graph-path data/graph/edges.json
python -m core.memory_os_migration list-document-records --store-root .engram-migration/store --record-type document_draft
python -m core.memory_os_migration export-bundle --store-root .engram-migration/store --bundle .engram-migration/bundle.json
python -m core.memory_os_migration restore-bundle --store-root .engram-migration/restored --bundle .engram-migration/bundle.json
python -m core.memory_os_migration round-trip --legacy-dir data/memories --work-root .engram-migration/round-trip

# Agent-facing migration checks are also available over MCP:
# migration_dry_run, memory_os_round_trip_check, and retrieval_backend_status
# verify the legacy import and rebuilt Memory OS stores.
```

---

## Architecture

```text
Engram
|-- server.py              # FastMCP server and MCP tools
|-- server_daemon_client.py # Thin MCP client that delegates to engramd only
|-- engramd.py             # Optional loopback daemon for shared local ownership
|-- webui.py               # Flask dashboard and REST API
|-- engram_index.py        # Codebase mapping CLI
|-- install.py             # Setup wizard
|-- core/
|   |-- memory_os/         # SQLite ledger, content store, LanceDB/Kuzu services
|   |-- memory_manager.py  # legacy JSON + Chroma storage, search, metadata
|   |-- embedder.py        # Local embedding model wrapper
|   |-- chunker.py         # Markdown-aware chunking
|   |-- source_intake.py   # Reviewable source drafts
|   |-- codebase_mapper.py # Agent-native codebase mapping jobs
|   |-- document_extractors.py # Local no-write document disassembly
|   |-- document_quality.py # Document quality warnings and next-tool guidance
|   |-- document_artifacts.py # Portable artifact manifests
|   |-- graph_manager.py   # Graph policy and traversal
|   |-- graph_store.py     # Swappable graph persistence seam
|   |-- graph_backend_status.py # No-write graph backend readiness report
|   |-- graph_backend_eval.py # No-write graph parity/cross-document readiness
|   |-- retrieval_backend_status.py # No-write backend readiness report
|   |-- retrieval_backend_eval.py # No-write vector backend comparison gates
|   |-- usage_meter.py     # Privacy-safe token estimates
|   |-- operation_log.py   # Job and event receipts
|   `-- reliability_harness.py
|-- data/
|   |-- memory_os/         # rebuilt ledger, objects, LanceDB, and Kuzu stores
|   |-- memories/          # legacy plain JSON memories
|   `-- chroma/            # legacy rebuildable vector index
|-- templates/             # Dashboard templates
|-- static/                # Dashboard assets
|-- tests/                 # Pytest suite
`-- docs/                  # Additional setup and operating notes
```

### Runtime Dependencies

| Package | Purpose |
|---|---|
| `fastmcp` | MCP server layer. |
| `sentence-transformers` | Local semantic embeddings. |
| `chromadb` | Persistent vector index. |
| `flask` | Web dashboard. |
| `lancedb` | Local Memory OS retrieval index. |
| `kuzu` | Local Memory OS graph store. |

See `requirements.txt` and the split profile files for exact version ranges and security floors. The thin daemon-client profile remains small for ordinary MCP adapter processes.

---

## Storage Layout

The rebuilt Memory OS stores operational state under `data/memory_os/`:

- `ledger.sqlite3` for durable metadata, receipts, jobs, transactions, entities, concepts, aliases, graph-edge mirrors, snapshots, and eval/skill-pack records.
- `objects/` for content-addressed source artifacts.
- `lance/` for rebuildable retrieval indexes.
- `kuzu/` for rebuildable graph storage.

Legacy compatible memories are still stored as plain JSON files under `data/memories/`.

Example:

```json
{
  "key": "example_architecture",
  "title": "Example App Architecture Notes",
  "content": "## Overview\n...",
  "tags": ["example", "architecture", "decisions"],
  "project": "example_app",
  "domain": "architecture",
  "status": "active",
  "canonical": true,
  "created_at": "2026-03-16T14:23:00-07:00",
  "updated_at": "2026-03-16T14:23:00-07:00",
  "last_accessed": "2026-04-01T09:15:00-07:00",
  "related_to": ["example_api_contract"],
  "potentially_stale": false,
  "chunk_count": 7,
  "chars": 3200,
  "lines": 81
}
```

If the ChromaDB index is damaged or deleted, run:

```bash
python server.py --rebuild-index
```

---

## Design Principles

- **Local first.** Memory content stays on your machine unless you expose or export it.
- **Memory OS first.** Rebuild 1.0 uses a SQLite ledger, content-addressed source store, LanceDB retrieval, Kuzu graph storage, and daemon-owned runtime.
- **Evidence before memory.** Raw and extracted sources become evidence and drafts before reviewed durable memory.
- **Token proportional.** Agents should load the smallest useful context first.
- **Human review for noisy intake.** Large source inputs become drafts before promotion.
- **Provider neutral.** The MCP server and codebase mapper do not require a specific model provider.
- **Portable by default.** Indexes and graphs must rebuild from the durable ledger and content-addressed artifacts.

---

## Roadmap

Engram 1.0 is the public, generic, local-first Memory OS rebuild: SQLite ledger, content-addressed source storage, LanceDB retrieval, Kuzu graph reasoning, daemon-owned operations, source/document evidence, visual/OCR coverage, retrieval receipts, graph relationships, transactions, snapshots, project capsules, skill-pack export, portable memory passport, and local Memory Inspector.

Post-1.0 work is hosted/commercial packaging: hosted sync, tenant auth, billing, hosted MCP/API gateway, hosted collaboration bridge, marketplace, and support operations. Local 1.0 should not be watered down into readiness gates around the legacy JSON/Chroma runtime.

Planning docs:

- `docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md`
- `docs/superpowers/plans/2026-05-13-engram-memory-os-rebuild-1-0-plan.md`
- `docs/RELEASE_GATES.md`
- `docs/ENGRAM_MEMORY_OS_1_0_RELEASE_CHECKLIST.md`
- `docs/ENGRAM_MEMORY_OS_1_0_MIGRATION_GUIDE.md`
- `docs/archive/legacy-local-core-1-0/README.md`
- `docs/ENGRAM_HOSTED_SELLABLE_CHECKLIST.md`

---

## Development

Install dev dependencies:

```bash
pip install -r requirements-dev.txt
```

Run tests:

```bash
python -m pytest -q
```

Run the main health gates:

```bash
python server.py --help
python -c "from core.memory_manager import memory_manager; print('ok')"
python engramd.py --doctor
python engramd.py --smoke-test
python server.py --health
python server.py --self-test
python server.py --agent-eval
python -m pytest tests/architecture tests/test_server_daemon_client_entrypoint.py tests/policy tests/mcp/test_no_write_tool_contracts.py tests/backend_gates -q
```

See `docs/RELEASE_GATES.md` for the pre-EKC readiness gate and the full 1.0
release gate. The pre-EKC gate verifies the thin daemon-client boundary,
no-write review surfaces, explicit write-policy metadata, and backend readiness
wrappers before new agent contracts are layered on top.

---

## Contributing

Issues and pull requests are welcome.

For code changes, please keep the JSON-first storage contract intact and run the test suite before opening a PR.

---

## License

MIT - see [LICENSE](LICENSE) for details.

---

Built by [CKWich](https://github.com/ckwich).
