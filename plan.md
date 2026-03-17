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
| `search_memories` | `(query, limit=5)` | Scored snippet per chunk match | Low |
| `list_all_memories` | `()` | Keys, titles, tags, timestamps | Very low |
| `retrieve_chunk` | `(key, chunk_id)` | Full text of one chunk | Medium |
| `retrieve_memory` | `(key, full=False)` | Full memory or metadata | High (intentional) |
| `store_memory` | `(key, content, tags, title)` | Confirmation | — |
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

## v0.4 — Polish and Reliability

### Webui Fixes
- [ ] Fix JSON serialization bug in dashboard edit/create form — special
      characters (backticks, dashes, angle brackets) in content field break
      JSON.parse on submit. Properly escape content before POST.
- [ ] Remove hardcoded character limit on content textarea in the dashboard
      form — the 15K limit is enforced server-side, the UI shouldn't
      silently truncate or error before submission.

### Engram Protocol
- [ ] Add v0.4 section to AGENTS.md template with forward-slash key warning
      and 15K char guidance baked in as defaults

### Reliability
- [ ] Add integration test: store → search → retrieve_chunk → delete cycle
      run against a live server instance
- [ ] Add health check endpoint: GET /health returns server status, model
      load state, memory count, chunk count

## Key Decisions
- **ChromaDB over SQLite FTS:** Real cosine similarity, not substring matching
- **JSON backing store:** Survives ChromaDB corruption, human-readable, portable
- **Local embeddings only:** No API cost, no privacy exposure, works offline
- **No automatic memory writes from agents:** Agents must explicitly call `store_memory`. No surprise writes.
