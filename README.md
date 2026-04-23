# Engram
### Intelligent Semantic Memory for AI Agents

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP Compliant](https://img.shields.io/badge/MCP-compliant-green.svg)](https://modelcontextprotocol.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Platform: Windows | macOS | Linux](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()

Engram is a local-first MCP memory server that gives AI agents genuinely useful long-term memory. It uses real semantic embeddings for search, provides three-tier retrieval to keep token costs proportional to need, and includes an intelligent layer that prevents duplicates, tracks access patterns, surfaces stale memories, indexes codebases automatically, and captures session outcomes for human approval.

Codex and GPT-5.5 use Engram through the same structured MCP tools as every other agent. There is no model-specific server mode; the important contract is the retrieval ladder: search first, retrieve chunks second, and read full memories only when the smaller context is not enough.

---

## Features

### Core Memory Server
- **Semantic search** via sentence-transformers (all-MiniLM-L6-v2) — local, offline, zero cost
- **Three-tier retrieval** — snippets, chunks, or full content based on what's actually needed
- **Agent-first structured MCP tools** — canonical structured payloads for search, listing, retrieval, relationships, and staleness
- **Protocol discovery + context packs** — agents can call `memory_protocol` to learn the contract or `context_pack` to fetch a bounded working set
- **Compatibility wrappers** — legacy text-returning tools still work for existing MCP clients
- **Session pins** — promote a temporary working set in search without mutating stored memory metadata
- **Markdown-aware chunking** — splits on headers first, then paragraphs, max 800 chars per chunk
- **Dual storage** — JSON flat files (source of truth) + ChromaDB vector index (search)
- **Web dashboard** at localhost:5000 — full CRUD, search, tag filtering, memory templates

### Memory Quality Layer
- **Deduplication gate** — blocks near-duplicate stores (cosine similarity >= 0.92, configurable) with `force=True` override
- **Access tracking** — `last_accessed` timestamp on every retrieval (fire-and-forget, non-blocking)
- **Relationship links** — `related_to` field with bidirectional `get_related_memories` queries
- **Staleness detection** — surfaces time-stale (not accessed in N days) and code-stale memories via WebUI tab and MCP tool
- **Metadata hygiene tools** — `prepare_memory`, `audit_memory_metadata`, and dry-run-first `repair_memory_metadata`

### Codebase Indexer
- **Architectural synthesis** — `engram_index.py` uses the Claude Code CLI to synthesize "Model B" understanding (why, decisions, patterns, watch-outs) from any codebase
- **Three modes** — bootstrap (full synthesis), evolve (incremental hash-diff), full (re-index everything)
- **Per-project config** — `.engram/config.json` with custom domains, file globs, and synthesis questions
- **Auto-generated skills** — thin skill files that trigger Engram retrieval when editing domain files
- **Git hook** — post-commit hook runs evolve mode automatically in the background

### Session Evaluator
- **Stop hook** — evaluates Claude Code sessions after they end against configurable criteria
- **Approval gate** — worthy sessions produce a memory draft saved to `.engram/pending_memories/`
- **Next-session surfacing** — `engram-pending` skill auto-loads and presents drafts for approval
- **Dedup-protected** — deduplication gate runs automatically before any draft is stored

---

## How It Works

### Three-Tier Retrieval

Agents should pay token costs proportional to what they actually need. New integrations
should use the structured unsuffixed tools as the canonical path.

```
Tier 1 — search_memories("dispatch calendar")
         -> 5 scored snippets, ~50 tokens each
         -> identify the right key + chunk_id

Tier 2 — retrieve_chunk("sylvara_scheduler", chunk_id=3)
         -> one relevant section, ~200 tokens
         -> usually sufficient

Tier 2b — retrieve_chunks([{key, chunk_id}, ...])
          -> fetch several known chunks in one round-trip

Shortcut — context_pack("dispatch calendar", project="sylvara")
           -> search + dedupe + retrieve bounded chunks in one call

Tier 3 — retrieve_memory("sylvara_scheduler")
         -> full content, intentional and explicit
```

The legacy wrappers `search_memories_text`, `list_all_memories`, `retrieve_chunk_text`,
and `retrieve_memory_text` remain available for compatibility. They render from the same
structured payloads, so old clients stay aligned with the canonical logic path.

### Semantic Search

Engram uses `all-MiniLM-L6-v2` for local embeddings and ChromaDB for vector storage. No API calls, no privacy exposure, no ongoing cost. The model runs on CPU and downloads once (~80MB).

```python
# These match with zero keyword overlap:
search_memories("CRM overlap with competitor")
# -> "Arbostar integration decision"

search_memories("audio transcription pipeline")
# -> "VoIP-first WebRTC architecture"
```

### Deduplication Gate

When storing a memory, Engram automatically checks for near-duplicates:

```python
store_memory("billing_fix", content="...")
# -> "WARNING: Similar memory exists: billing_webhook_pattern (score: 0.94)"
# -> Memory NOT stored. Use force=True to override.

store_memory("billing_fix", content="...", force=True)
# -> Stored (dedup overridden)
```

The threshold (default 0.92) is configurable in `config.json`.

---

## MCP Tools

Engram exposes a structured-first MCP surface. The unsuffixed tools are the
canonical agent-first interface, and the rendered text tools remain available
under explicit compatibility names.

### Canonical Structured Tools

| Tool | Signature | Purpose |
|---|---|---|
| `memory_protocol` | `()` | Describe the retrieval ladder, canonical tools, aliases, and token-safety warnings |
| `search_memories` | `(query, limit=5, session_id=None, pinned_first=False, project=None, domain=None, tags=None, include_stale=True, canonical_only=False)` | Semantic search with structured snippets, session pins, and metadata filters |
| `context_pack` | `(query, project=None, domain=None, tags=None, max_chunks=5, budget_chars=6000, include_stale=False, canonical_only=False)` | Search, dedupe, and retrieve a bounded chunk working set |
| `find_memories` | same as `search_memories` | Alias for agents that look for a find verb |
| `list_memories` | `(limit=50, offset=0, project=None, domain=None, tags=None, recent_first=True)` | Paginated structured memory directory metadata |
| `retrieve_chunk` | `(key, chunk_id)` | Structured single-chunk retrieval |
| `retrieve_chunks` | `(requests)` | Structured batch chunk retrieval |
| `retrieve_memory` | `(key)` | Structured full-memory retrieval |
| `read_chunk` | `(key, chunk_id)` | Alias for `retrieve_chunk` |
| `read_memory` | `(key, chunk_id=None, full=False)` | Tier-aware helper: chunk if chunk_id is provided, metadata by default, full only with `full=True` |
| `pin_memory` | `(session_id, key)` | Pin a memory key into a temporary session working set |
| `unpin_memory` | `(session_id, key)` | Remove one key from a session working set |
| `list_pins` | `(session_id)` | List pinned keys for a session |
| `clear_pins` | `(session_id)` | Clear all pinned keys for a session |
| `store_memory` | `(key, content, title='', tags='', related_to='', force=False, project=None, domain=None, status=None, canonical=None)` | Create or update a memory |
| `write_memory` | same as `store_memory` | Alias for agents that look for a write verb |
| `prepare_memory` | `(content, key='', title='', tags='', related_to='', project=None, domain=None, status=None, canonical=None)` | Draft key/metadata, validate, and check duplicates without writing |
| `check_duplicate` | `(key, content)` | Preview deduplication matches before storing |
| `suggest_memory_metadata` | `(content)` | Suggest normalized metadata from draft content |
| `validate_memory` | `(content, title=None, tags=None, related_to=None, status=None, project=None, domain=None, canonical=None)` | Validate a memory payload before storing |
| `update_memory_metadata` | `(key, title=None, tags=None, related_to=None, project=None, domain=None, status=None, canonical=None)` | Update metadata fields without rewriting content |
| `audit_memory_metadata` | `(limit=100, offset=0, project=None)` | Read-only metadata drift audit |
| `repair_memory_metadata` | `(keys, dry_run=True)` | Repair selected metadata drift; writes JSON first, then reindexes when `dry_run=False` |
| `get_related_memories` | `(key)` | Structured forward and reverse relationship traversal |
| `get_stale_memories` | `(days=90, type='all')` | Structured stale-memory surfacing |
| `delete_memory` | `(key)` | Permanently delete a memory |

### Compatibility Wrappers

| Tool | Returns | Notes |
|---|---|---|
| `search_memories_text` | Rendered text | Compatibility wrapper over `search_memories` |
| `list_all_memories` | Rendered text | Compatibility wrapper over `list_memories` |
| `retrieve_chunk_text` | Rendered text | Compatibility wrapper over `retrieve_chunk` |
| `retrieve_memory_text` | Rendered text | Compatibility wrapper over `retrieve_memory` |
| `get_related_memories_text` | Rendered text | Legacy text view of relationships |
| `get_stale_memories_text` | Rendered text | Legacy text view of stale-memory results |

### Session Pins and Migration

- Session pins are working-state only. They do not mutate memory JSON, tags, or long-term metadata.
- Use `pin_memory` and `search_memories(..., session_id=..., pinned_first=True)` when you want pinned memories to sort ahead of unpinned results.
- Use `prepare_memory` before writes when key/metadata quality or duplicate risk is uncertain.
- Use `audit_memory_metadata` first, then `repair_memory_metadata(..., dry_run=False)` only for selected keys after reviewing the dry-run output.
- Structured reads now live on the unsuffixed tool names. The compatibility text wrappers moved to explicit `*_text` names, with `list_all_memories` retained for legacy browsing.
- Compatibility wrappers render from the canonical structured payloads so the old and new surfaces stay behaviorally aligned.

---

## Installation

### Prerequisites
- Python 3.10+
- Git
- Codex CLI (recommended for automatic Codex MCP registration)
- Claude Code CLI (optional; used by the codebase indexer and session evaluator)

### Quick Start

```bash
git clone https://github.com/ckwich/Engram.git
cd Engram
python install.py
```

The installer creates a virtual environment, installs dependencies, pre-downloads the embedding model, generates your MCP config, and registers Engram with Codex automatically when the `codex` CLI is available.

### Connect to Codex

The Codex CLI stores MCP server registrations in `~/.codex/config.toml`.

```powershell
codex mcp add engram -- `
  "C:\path\to\engram\venv\Scripts\python.exe" `
  "C:\path\to\engram\server.py"
```

**macOS / Linux:**
```bash
codex mcp add engram -- \
  /path/to/engram/venv/bin/python \
  /path/to/engram/server.py
```

Open a fresh Codex thread, or restart Codex, after changing MCP registration. Existing threads do not always hot-load newly added MCP servers.

### Connect to Claude Code

```bash
claude mcp add engram --scope user \
  /path/to/engram/venv/bin/python \
  /path/to/engram/server.py
```

**Windows:**
```powershell
claude mcp add engram --scope user `
  "C:\path\to\engram\venv\Scripts\python.exe" `
  "C:\path\to\engram\server.py"
```

### Connect to Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "engram": {
      "command": "/path/to/engram/venv/bin/python",
      "args": ["/path/to/engram/server.py"]
    }
  }
}
```

### SSE Mode (Remote / Homelab)

```bash
python server.py --transport sse --port 5100
```

---

## Skills

Engram ships optional Claude Code skills at `~/.claude/skills/`. Codex uses the MCP registration directly.

### /engramize

Create memories naturally mid-session:

```
/engramize the billing webhook race condition fix we just figured out
```

The skill looks back at the session context, drafts a properly formatted memory (key, title, tags, content), shows it for approval, then stores. It enforces naming conventions (snake_case keys, em-dash titles, three-tag standard).

### engram-pending

Auto-loads at session start. Checks for pending memory drafts from the session evaluator and presents them for approval, editing, or deletion.

---

## Codebase Indexer

Synthesize architectural understanding from any codebase into Engram memories.

```bash
# Interactive setup — auto-detects domains, you confirm
python engram_index.py --project /path/to/project --init

# Full synthesis from planning docs + source code
python engram_index.py --project /path/to/project --mode bootstrap

# Incremental — only changed domains since last run
python engram_index.py --project /path/to/project --mode evolve

# Complete re-index
python engram_index.py --project /path/to/project --mode full

# Preview without synthesizing
python engram_index.py --project /path/to/project --dry-run

# Re-index a specific domain
python engram_index.py --project /path/to/project --domain billing

# Install git post-commit hook for automatic evolve
python engram_index.py --project /path/to/project --install-hook
```

### Per-Project Config

Create `.engram/config.json` in your project root (or use `--init`):

```json
{
  "project_name": "sylvara",
  "domains": {
    "billing": {
      "file_globs": ["src/billing/**", "src/stripe/**"],
      "questions": [
        "How does the billing pipeline work?",
        "What are the key integration points?"
      ]
    },
    "auth": {
      "file_globs": ["src/auth/**", "src/middleware/auth*"],
      "questions": [
        "How does authentication flow work?",
        "What session management decisions were made?"
      ]
    }
  },
  "planning_paths": [".planning/", "docs/"],
  "model": "sonnet",
  "max_file_size_kb": 100
}
```

### How It Works

1. **Bootstrap** reads planning artifacts + source files per domain
2. **Sends context** to the Claude Code CLI (`claude -p`) for synthesis — uses your Max plan, zero extra cost
3. **Stores memories** in the `codebase_{project}_{domain}_architecture` namespace
4. **Generates thin skill files** at `~/.claude/skills/{project}-{domain}-context/` that trigger Engram retrieval when editing matching files
5. **Tracks file hashes** in `.engram/index.json` for incremental re-indexing

Manual edits to Engram memories always win over re-indexing (unless `--force` is passed).

---

## Session Evaluator

Automatically captures significant session outcomes as memories.

### Setup

Register the Stop hook in Claude Code settings (one-time):

```json
// In ~/.claude/settings.json, add to hooks.Stop array:
{
  "type": "command",
  "command": "C:/Dev/Engram/venv/Scripts/python.exe C:/Dev/Engram/hooks/engram_stop.py"
}
```

### How It Works

1. **After every session**, the Stop hook fires and spawns a detached evaluator subprocess (never blocks)
2. **Evaluator reads** `last_assistant_message` from the session and calls the Claude CLI with configured criteria
3. **If criteria are met** (bug resolved, new capability, architectural decision, milestone), a memory draft is written to `.engram/pending_memories/`
4. **Dedup gate runs** before writing — if a near-duplicate exists, it's noted in the draft
5. **Next session**, the `engram-pending` skill surfaces drafts for approval

### Safety

- `stop_hook_active` check is the absolute first action — prevents infinite evaluation loops
- Evaluator runs as a detached subprocess — hook exits in under 10 seconds
- `auto_approve_threshold: 0.0` means always ask (configurable per project)
- No memory is ever stored without explicit human approval (unless threshold is raised)

### Configuration

Add to your project's `.engram/config.json`:

```json
{
  "session_evaluator": {
    "logic_win_triggers": [
      "bug resolved",
      "new system capability added",
      "architectural decision made"
    ],
    "milestone_triggers": [
      "phase completed",
      "feature shipped",
      "significant refactor done"
    ],
    "auto_approve_threshold": 0.0
  }
}
```

---

## Web Dashboard

Full-featured web UI at `http://localhost:5000`:

```bash
python webui.py
```

The dashboard binds to `127.0.0.1` by default. To expose it intentionally, set
`ENGRAM_WEBUI_HOST` and optionally `ENGRAM_WEBUI_PORT` before starting it.

- **Grid and List views** with metadata cards
- **Semantic search** with relevance scores and three-tier expansion
- **Full CRUD** from the browser with dedup warnings
- **Related memories** displayed as clickable links on detail view
- **Stale Memories tab** showing time-stale and code-stale memories with Mark Reviewed action
- **Memory templates** for common types (Project, Decision, Reference, Snippet)
- **Tag filtering** sidebar

### Web API

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/search?q=...&limit=10` | Semantic search |
| `GET` | `/api/chunk/<key>/<chunk_id>` | Retrieve a single chunk |
| `GET` | `/api/memory/<key>` | Retrieve full memory |
| `POST` | `/api/memory` | Create a memory |
| `PUT` | `/api/memory/<key>` | Update a memory |
| `DELETE` | `/api/memory/<key>` | Delete a memory |
| `GET` | `/api/related/<key>` | Get related memories |
| `GET` | `/api/stale` | List stale memories |
| `POST` | `/api/memory/<key>/reviewed` | Mark memory as reviewed |
| `GET` | `/api/stats` | Memory count, chunk count |
| `GET` | `/health` | Health check |

---

## CLI Utilities

```bash
# MCP server (stdio transport, default)
python server.py

# SSE transport for remote access
python server.py --transport sse --port 5100

# Rebuild ChromaDB index from JSON (recovery)
python server.py --rebuild-index

# Export/import all memories
python server.py --export
python server.py --import-file engram_export_2026-03-16.json

# Health check and self-test
python server.py --health
python server.py --self-test

# Generate MCP client config using the active Python interpreter
python server.py --generate-config
```

---

## Architecture

```
engram/
├── core/
│   ├── embedder.py          # sentence-transformers wrapper
│   ├── chunker.py           # markdown-aware content chunker
│   └── memory_manager.py    # storage engine (JSON + ChromaDB, dedup, relationships, staleness)
├── hooks/
│   ├── engram_stop.py       # Claude Code Stop hook entry point
│   ├── engram_evaluator.py  # detached session evaluator
│   └── test_engram_evaluator.py
├── data/
│   ├── memories/            # JSON flat files — source of truth
│   └── chroma/              # ChromaDB vector index
├── templates/
│   └── index.html           # web dashboard
├── static/
│   └── style.css            # dashboard styles
├── server.py                # FastMCP server (structured + compatibility MCP tools)
├── webui.py                 # Flask web dashboard + REST API
├── engram_index.py          # codebase indexer CLI
├── config.json              # runtime config (dedup threshold, stale days, evaluator criteria)
├── install.py               # setup wizard
└── requirements.txt         # pinned dependencies
```

### Dependencies

| Package | Version | Purpose |
|---|---|---|
| `fastmcp` | ~3.1.1 | MCP server layer (stdio + SSE) |
| `sentence-transformers` | ~5.3.0 | Local semantic embeddings |
| `chromadb` | ~1.5.5 | Persistent vector store |
| `flask` | ~3.1.3 | Web dashboard |

The core MCP server has no Codex- or Claude-specific runtime dependency. The optional codebase indexer and session evaluator use the Claude Code CLI (`claude -p`), which runs under your existing subscription.

### Design Decisions

**JSON as source of truth.** If the vector index is corrupted, `--rebuild-index` reconstructs it from JSON. Your memories are never solely in a binary database.

**Local embeddings only.** No external API calls. The model runs on CPU, works offline, zero ongoing cost. Memory contents never leave your machine.

**Dedup before store.** Every `store_memory` call checks for semantic near-duplicates. The threshold (0.92 cosine) is configurable. Self-updates (same key) are always allowed through.

**Fire-and-forget access tracking.** `last_accessed` updates run in background tasks — retrieval is never slowed down by tracking writes.

**CLI-based synthesis.** The optional codebase indexer and session evaluator use `claude -p` subprocess calls instead of the Anthropic API. This uses your existing Claude Code subscription with zero marginal cost.

**Non-blocking hooks.** The Stop hook spawns the evaluator as a detached subprocess and exits immediately. Sessions are never blocked by evaluation.

**Human approval for automated captures.** The session evaluator never stores memories directly — it writes drafts to pending files. A human must approve, edit, or delete each draft.

---

## Storage Layout

Memories are stored as plain JSON:

```json
{
  "key": "sylvara_architecture",
  "title": "Sylvara — Architecture and Technical Decisions",
  "content": "## Stack\n...",
  "tags": ["sylvara", "architecture", "decisions"],
  "created_at": "2026-03-16T14:23:00-07:00",
  "updated_at": "2026-03-16T14:23:00-07:00",
  "last_accessed": "2026-04-01T09:15:00-07:00",
  "related_to": ["sylvara_ops", "sylvara_billing"],
  "potentially_stale": false,
  "chunk_count": 19,
  "chars": 7099,
  "lines": 142
}
```

Human-readable, portable, and editable with any text editor.

---

## Contributing

Issues and PRs welcome. If you find a bug or have a feature idea, open an issue.

---

## License

MIT — see [LICENSE](LICENSE) for details.

---

*Built by [Cole Wichman](https://github.com/ckwich)*
