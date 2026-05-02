# Engram

### Local-first semantic memory for AI agents

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP Compliant](https://img.shields.io/badge/MCP-compliant-green.svg)](https://modelcontextprotocol.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Platform: Windows | macOS | Linux](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()

Engram is a local Model Context Protocol (MCP) server that gives AI agents a durable, searchable memory across sessions.

It stores memories as plain JSON, indexes them with local embeddings, and exposes agent-friendly tools for search, bounded context retrieval, source intake, codebase mapping, relationship tracking, and retrieval-quality checks.

Engram is built around one simple idea: agents should retrieve the smallest useful context first, then expand only when needed.

---

## Why Engram?

Most agent memory systems fail in one of two ways: they forget too much between sessions, or they load too much context into every session.

Engram aims for a middle path:

- Keep memories on your machine.
- Search semantically instead of relying on exact keywords.
- Retrieve snippets before chunks, and chunks before full documents.
- Give agents receipts for what they loaded and why.
- Keep durable memory readable, editable, and recoverable.

The result is a practical intersession memory layer for coding agents, research agents, local assistants, and MCP clients that need continuity without dumping an entire knowledge base into every prompt.

---

## What Engram Provides

### Memory Server

- **Local semantic search** using `sentence-transformers` and ChromaDB.
- **Plain JSON source of truth** for memories, with ChromaDB as a rebuildable vector index.
- **Markdown-aware chunking** that preserves headings and paragraph boundaries where possible.
- **Deduplication checks** before writes, with explicit `force=True` override.
- **Metadata filters** for project, domain, tags, lifecycle status, and canonical memories.
- **Relationship links** between memories, including bidirectional traversal.
- **Staleness surfacing** for old or potentially code-stale memories.

### Agent-Facing Retrieval

- **Three-tier retrieval**: search snippets, retrieve chunks, then read full memories only when necessary.
- **Context packs** that search, dedupe, and retrieve a bounded working set in one call.
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

### Web Dashboard

- Browse, search, create, update, and delete memories.
- Review stale memories and related memories.
- Inspect usage estimates and retrieval eval status.
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

---

## MCP Tool Surface

Engram exposes structured MCP tools first. Text wrappers remain available for older clients, but new integrations should prefer the structured tools.

### Discovery and Retrieval

| Tool | Purpose |
|---|---|
| `memory_protocol` | Describes the retrieval ladder and current tool contract. |
| `search_memories` | Semantic or hybrid memory search with filters and scored snippets. |
| `find_memories` | Alias for agents looking for a find verb. |
| `context_pack` | Search, dedupe, and retrieve a bounded chunk working set. |
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
| `get_related_memories` | Traverse forward and reverse memory links. |
| `get_stale_memories` | Surface stale or potentially stale memories. |
| `pin_memory` | Pin a memory for the current session. |
| `unpin_memory` | Remove a pinned memory. |
| `list_pins` | List session pins. |
| `clear_pins` | Clear session pins. |
| `audit_memory_metadata` | Read-only metadata hygiene audit. |
| `repair_memory_metadata` | Dry-run-first metadata repair. |

### Source, Graph, and Evaluation

| Tool | Purpose |
|---|---|
| `prepare_source_memory` | Create reviewable source-memory drafts. |
| `list_source_drafts` | Browse prepared source drafts. |
| `store_prepared_memory` | Promote selected drafts to stored memories. |
| `discard_source_draft` | Delete a draft. |
| `preview_memory_chunks` | Preview chunking without writing. |
| `preview_source_connector` | Preview local source intake without writing. |
| `list_ingestion_pipelines` | List available source-intake pipelines. |
| `add_graph_edge` | Store a typed relationship between refs. |
| `list_graph_edges` | List graph edges around refs. |
| `impact_scan` | Traverse graph relationships for impact analysis. |
| `audit_graph` | Inspect graph hygiene. |
| `usage_summary` | Summarize Engram-attributed token estimates. |
| `list_usage_calls` | Inspect recent estimated usage calls. |
| `retrieval_eval` | Run deterministic retrieval-quality checks. |
| `list_workflow_templates` | List built-in agent workflow recipes. |

Compatibility wrappers include `search_memories_text`, `retrieve_chunk_text`, `retrieve_memory_text`, `list_all_memories`, `get_related_memories_text`, and `get_stale_memories_text`.

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

---

## MCP Client Setup

### Codex

The Codex CLI stores MCP registrations in `~/.codex/config.toml`.

Windows:

```powershell
codex mcp add engram -- `
  "C:\path\to\Engram\venv\Scripts\python.exe" `
  "C:\path\to\Engram\server.py"
```

macOS / Linux:

```bash
codex mcp add engram -- \
  /path/to/Engram/venv/bin/python \
  /path/to/Engram/server.py
```

Open a fresh Codex thread, or restart Codex, after changing MCP registration. Existing threads may not hot-load newly added MCP servers.

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
  "max_file_size_kb": 100
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

Use `preview_memory_chunks` or `preview_source_connector` when you want to inspect what Engram would ingest before any write happens.

---

## CLI Utilities

```bash
# MCP server, stdio transport
python server.py

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
```

---

## Architecture

```text
Engram
|-- server.py              # FastMCP server and MCP tools
|-- webui.py               # Flask dashboard and REST API
|-- engram_index.py        # Codebase mapping CLI
|-- install.py             # Setup wizard
|-- core/
|   |-- memory_manager.py  # JSON + Chroma storage, search, metadata
|   |-- embedder.py        # Local embedding model wrapper
|   |-- chunker.py         # Markdown-aware chunking
|   |-- source_intake.py   # Reviewable source drafts
|   |-- codebase_mapper.py # Agent-native codebase mapping jobs
|   |-- graph_manager.py   # Graph policy and traversal
|   |-- graph_store.py     # Swappable graph persistence seam
|   |-- usage_meter.py     # Privacy-safe token estimates
|   |-- operation_log.py   # Job and event receipts
|   `-- reliability_harness.py
|-- data/
|   |-- memories/          # Plain JSON memories
|   `-- chroma/            # Rebuildable vector index
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

See `requirements.txt` for exact version ranges and security floors.

---

## Storage Layout

Memories are stored as plain JSON files under `data/memories/`.

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
- **JSON first, vector second.** JSON is the durable source of truth; ChromaDB is rebuildable.
- **Token proportional.** Agents should load the smallest useful context first.
- **Human review for noisy intake.** Large source inputs become drafts before promotion.
- **Provider neutral.** The MCP server and codebase mapper do not require a specific model provider.
- **Migration ready.** Graph persistence is behind a narrow store interface for future backends.

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
python server.py --health
python server.py --self-test
python server.py --agent-eval
```

---

## Contributing

Issues and pull requests are welcome.

For code changes, please keep the JSON-first storage contract intact and run the test suite before opening a PR.

---

## License

MIT - see [LICENSE](LICENSE) for details.

---

Built by [CKWich](https://github.com/ckwich).
