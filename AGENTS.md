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

### Tool docstrings are agent contracts
The docstrings on MCP tools in `server.py` are read by AI agents to understand tool behavior. Keep them accurate, complete, and explicit about the three-tier retrieval pattern.

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

Step 3 (if needed): retrieve_memory(key)
   → Returns full memory. Use sparingly.
```

Never call `retrieve_memory` without first checking if a chunk is sufficient.
