# Engram 🧠
### Semantic Long-Term Memory for AI Agents

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MCP Compliant](https://img.shields.io/badge/MCP-compliant-green.svg)](https://modelcontextprotocol.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Platform: Windows | macOS | Linux](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()

Engram is a local-first MCP memory server that gives AI agents genuinely useful long-term memory. Unlike naive memory servers that rely on substring matching, Engram uses real semantic embeddings — so searching *"dispatch calendar"* surfaces content about *"scheduling and daily operations"* even with zero keyword overlap.

Built as a direct response to the limitations of existing MCP memory tools.

---

## Why Engram?

Most MCP memory servers are glorified key-value stores with a `query in content.lower()` search. That's not memory — that's `grep`.

Engram is different:

| Feature | Typical MCP Memory Server | Engram |
|---|---|---|
| Search | Substring match | Cosine similarity (real semantic search) |
| Retrieval | All-or-nothing | Three-tier: snippet → chunk → full content |
| Token cost | High (dumps full memories) | Proportional to what's actually needed |
| Storage | SQLite or flat JSON | JSON (source of truth) + ChromaDB (search index) |
| Chunking | None | Markdown-aware, header-respecting |
| Dashboard | Minimal or none | Full web UI with CRUD, tag filtering, search |

---

## How It Works

### Three-Tier Retrieval

The core insight: agents should pay token costs proportional to what they actually need.

```
Tier 1 — search_memories("dispatch calendar")
         → 5 scored snippets, ~50 tokens each
         → identify the right key + chunk_id

Tier 2 — retrieve_chunk("sylvara_scheduler", chunk_id=3)
         → one relevant section, ~200 tokens
         → usually sufficient

Tier 3 — retrieve_memory("sylvara_scheduler")
         → full content, intentional and explicit
```

A typical agent session uses Tier 1 and Tier 2 only. Tier 3 is there when you need it.

### Semantic Search That Actually Works

Engram uses `sentence-transformers/all-MiniLM-L6-v2` for local embeddings and ChromaDB for vector storage. No API calls, no privacy exposure, no ongoing cost. The model runs fully on CPU and downloads once (~80MB) on first use.

```python
# These will match even with zero keyword overlap:
search_memories("CRM overlap with competitor")
# → surfaces memory about "Arbostar integration decision"

search_memories("audio transcription pipeline")
# → surfaces memory about "VoIP-first WebRTC architecture"
```

### Markdown-Aware Chunking

Content is split on markdown headers first, then paragraph boundaries, then hard size limits. This means a 5,000-character architectural decision doc doesn't get dumped into a single chunk — it becomes 6-8 semantically coherent pieces, each independently retrievable.

---

## MCP Tools

Engram exposes 6 tools to any MCP-compatible agent (Claude Code, Claude Desktop, Cursor, etc.):

| Tool | Signature | Purpose | Token Cost |
|---|---|---|---|
| `search_memories` | `(query, limit=5)` | Semantic search, returns scored snippets | Low |
| `list_all_memories` | `()` | Full directory: keys, titles, tags, timestamps | Very low |
| `retrieve_chunk` | `(key, chunk_id)` | Single chunk by key + chunk_id | Medium |
| `retrieve_memory` | `(key)` | Full memory content | High (intentional) |
| `store_memory` | `(key, content, tags, title)` | Create or update a memory | — |
| `delete_memory` | `(key)` | Permanently delete a memory | — |

### Recommended Agent Directive

Add this to your `AGENTS.md` or `CLAUDE.md`:

```markdown
## Memory Protocol
Before starting any task, search Engram for relevant context:
1. search_memories(query) — identify relevant keys and chunk_ids
2. retrieve_chunk(key, chunk_id) — fetch the relevant section
3. retrieve_memory(key) — only if the full content is needed

Never call retrieve_memory() without checking if a chunk is sufficient first.
```

---

## Installation

### Prerequisites
- Python 3.10+
- Git

### Quick Start

```bash
git clone https://github.com/ckwich/Engram.git
cd Engram
python install.py
```

The installer creates a virtual environment, installs dependencies, pre-downloads the embedding model, and generates your MCP config.

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

Then configure your client to connect via `http://your-server:5100/sse`.

---

## Web Dashboard

Engram ships with a full-featured web UI at `http://localhost:5000`.

```bash
python webui.py
```

Features:
- **Grid and List views** — metadata-only cards with chunk count, char count, tags, date
- **Semantic search** — real-time results with relevance scores, snippets, and chunk IDs
- **Three-tier expansion** — click a result to load the chunk; escalate to full memory on demand
- **Full CRUD** — create, edit, delete from the browser
- **Memory templates** — Project, Decision, Reference, Snippet scaffolds
- **Tag filtering** — sidebar tag browser across all memories
- **Stats header** — live memory count and total chunk count

---

## CLI Utilities

```bash
# Rebuild the ChromaDB index from JSON files (recovery tool)
python server.py --rebuild-index

# Export all memories to a portable JSON bundle
python server.py --export
# → engram_export_2026-03-16.json

# Import from a JSON bundle
python server.py --import-file engram_export_2026-03-16.json

# Fix chunk_count on legacy memories
python server.py --migrate

# Generate MCP client config
python server.py --generate-config
```

---

## Architecture

```
engram/
├── core/
│   ├── embedder.py        # sentence-transformers wrapper (lazy load, batched)
│   ├── chunker.py         # markdown-aware content chunker
│   └── memory_manager.py  # storage engine (JSON + ChromaDB, JSON-first)
├── data/
│   ├── memories/          # JSON flat files — source of truth
│   └── chroma/            # ChromaDB vector index — rebuilt from JSON if lost
├── server.py              # FastMCP server (stdio + SSE transport)
├── webui.py               # Flask web dashboard
└── install.py             # setup wizard
```

### Design Decisions

**JSON as source of truth, ChromaDB as index.** If the vector index is ever lost or corrupted, `--rebuild-index` reconstructs it entirely from the JSON files. Your memories are never solely in a binary database.

**Local embeddings only.** No external API calls for embedding. The model runs on CPU, works offline, and has zero ongoing cost. Your memory contents never leave your machine.

**Batched embedding.** `embed_batch()` processes in groups of 8 to prevent CPU timeouts on large memories.

**Non-blocking encoding.** The MCP server uses async embedding (`embed_batch_async`) that runs in a thread pool executor, so encoding never blocks the event loop. This prevents MCP client timeouts when storing large memories with many chunks.

**15,000 character limit per memory.** `store_memory` rejects content over 15,000 characters with a helpful error. For large documents, split into multiple memories with specific keys that follow a naming pattern:

```
lumen_adr_018          # ADR section 1
lumen_adr_019          # ADR section 2
sylvara_arch_overview  # Architecture overview
sylvara_arch_api       # Architecture — API layer
```

This produces better chunking, more precise search results, and avoids embedding timeouts.

**Agents must explicitly store.** Engram never writes memories automatically. Every `store_memory` call is an intentional act by the agent or user. No surprise writes.

---

## Storage Layout

Memories are stored as plain JSON files:

```json
{
  "key": "sylvara_architecture",
  "title": "Sylvara — Architecture and Technical Decisions",
  "content": "## Stack\n...",
  "tags": ["sylvara", "architecture", "decisions"],
  "created_at": "2026-03-16T14:23:00-07:00",
  "updated_at": "2026-03-16T14:23:00-07:00",
  "chunk_count": 19,
  "chars": 7099
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
