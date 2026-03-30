# Technology Stack

**Project:** Engram Enhancement Suite
**Researched:** 2026-03-29
**Mode:** Subsequent milestone — adding features to existing Python MCP server

---

## Current Stack (Verified)

From `requirements.txt` and `server.py`:

| Package | Pinned Version | Role |
|---------|---------------|------|
| fastmcp | ~3.1.1 | MCP server framework |
| sentence-transformers | ~5.3.0 | Local embedding model |
| chromadb | ~1.5.5 | Vector index |
| flask | ~3.1.3 | WebUI server |

Python 3.12 on Windows 10/11. `python` (not `python3`) invocation.

---

## Recommended Additions by Feature Area

### Phase 1 — Engramize Skill (Claude Code skill file)

**No new Python dependencies.** This is purely a SKILL.md file creation task.

| Item | Recommendation | Confidence | Rationale |
|------|---------------|------------|-----------|
| Skill location | `~/.claude/skills/engramize/SKILL.md` | HIGH | Official docs confirm `~/.claude/skills/<name>/SKILL.md` is the personal skill path (applies across all projects) |
| Frontmatter: `name` | `engramize` | HIGH | Becomes the `/engramize` slash command |
| Frontmatter: `description` | Front-loaded trigger phrase + conditions | HIGH | Official docs: descriptions >250 chars truncated in context; front-load the key use case |
| Frontmatter: `disable-model-invocation` | `true` | HIGH | This skill has side effects (stores data to Engram); must be user-triggered, not auto-invoked |
| Frontmatter: `allowed-tools` | `mcp__engram__store_memory` | MEDIUM | Grants store permission without approval prompt during skill execution |
| Supporting files | Single `SKILL.md` only | HIGH | Skill content is instructions + prompting, no scripts needed |

**SKILL.md format confirmed from official docs** (fetched from code.claude.com/docs/en/skills):

```yaml
---
name: engramize
description: Capture an important decision, pattern, or finding as an Engram memory. Use when you want to save architectural insights, implementation decisions, or lessons learned.
disable-model-invocation: true
---

[skill instructions here]
```

The `user-invocable: false` field (model-only invocation) is NOT appropriate here — we want `/engramize` as an explicit user command with `disable-model-invocation: true` to prevent Claude from auto-firing it.

---

### Phase 2a — Deduplication Gate on `store_memory`

**No new Python dependencies required.** Use existing sentence-transformers and numpy (already a transitive dependency of sentence-transformers).

| Item | Recommendation | Confidence | Rationale |
|------|---------------|------------|-----------|
| Cosine similarity computation | `numpy.dot` on normalized embeddings | HIGH | `sentence-transformers` already normalizes embeddings when `normalize_embeddings=True`; dot product of normalized vectors equals cosine similarity — no additional library needed |
| Duplicate threshold | 0.92 (configurable via env or config file) | HIGH | Specified in PROJECT.md; high enough to catch near-duplicates, low enough to allow related memories |
| Where to compute | In `memory_manager.py` `store_memory` path, before write | HIGH | Consistent with existing architecture pattern; sync and async paths both need the check |
| Embedding reuse | Reuse the new memory's embedding computed during the store path | MEDIUM | ChromaDB query returns distance scores; fetch top-N existing memories by embedding similarity to new content before writing |
| ChromaDB distance to cosine | `cosine_similarity = 1 - chroma_distance` | HIGH | ChromaDB with cosine space returns cosine distance (not similarity); this conversion is well-documented |

**Do NOT add:** `scikit-learn`, `scipy`, or `faiss` for cosine similarity. The existing `sentence_transformers.util.cos_sim()` (already available) or plain numpy dot product is sufficient.

---

### Phase 2b — `last_accessed` Tracking

**No new dependencies.** Pure JSON field addition + timestamp logic using stdlib `datetime`.

| Item | Recommendation | Confidence | Rationale |
|------|---------------|------------|-----------|
| Storage | Add `last_accessed` ISO timestamp field to existing JSON schema | HIGH | Consistent with `updated_at` pattern already in memory_manager.py |
| Update path | Write on every `retrieve_memory` and `retrieve_chunk` call | HIGH | Both are read paths; update JSON file on each retrieval |
| ChromaDB metadata sync | Store `last_accessed` in ChromaDB metadata as well | MEDIUM | Enables future date-range filtering at query time without JSON read |

---

### Phase 2c — `related_to` Relationships + `get_related_memories` Tool

**No new dependencies.** JSON field addition and new MCP tool registration.

| Item | Recommendation | Confidence | Rationale |
|------|---------------|------------|-----------|
| Storage | `related_to: list[str]` field in JSON schema | HIGH | Simple list of memory keys; avoids graph DB complexity (explicitly out of scope) |
| New MCP tool | `get_related_memories(key)` added to `server.py` | HIGH | Follows existing tool pattern in server.py: `@mcp.tool()` async function |
| FastMCP tool registration | `@mcp.tool()` decorator unchanged from v3.1 | HIGH | Verified from fastmcp docs; v3 keeps `@mcp.tool()` as primary registration pattern |

---

### Phase 3 — Codebase Indexer (Claude API Synthesis)

**New dependency: anthropic SDK.**

| Item | Recommendation | Version | Confidence | Rationale |
|------|---------------|---------|------------|-----------|
| anthropic SDK | `anthropic` | `>=0.86.0,<1.0` | HIGH | Latest release is 0.86.0 (March 18, 2026); requires Python >=3.9; already described as "available in venv" in PROJECT.md — verify installed version with `pip show anthropic` |
| Synthesis model | `claude-sonnet-4-5` (or current Sonnet) | HIGH | PROJECT.md specifies Sonnet for cost/quality ratio; use the model ID returned by `claude-sonnet-*` alias at call time |
| API call pattern | `AsyncAnthropic().messages.create()` with `await` | HIGH | MCP server is async throughout; verified from official SDK docs |
| File hashing for change detection | `hashlib.md5` (already used in memory_manager.py) or `hashlib.sha256` | HIGH | No new dependency; stdlib hashlib sufficient for file change fingerprinting; xxhash/blake3 are unnecessary additions for this use case |
| File traversal | `pathlib.Path.rglob()` | HIGH | Already used in codebase; stdlib; cross-platform on Windows |
| Gitignore parsing | `pathspec` | `>=0.12.1` | MEDIUM | Pure-Python gitignore pattern matching; maintained library used by Black, mypy, and others; avoids writing a gitignore parser from scratch. Alternative: subprocess `git ls-files` — simpler but requires git in PATH |
| Progress output | `print(..., file=sys.stderr)` | HIGH | Consistent with existing CLI pattern in server.py; no rich/tqdm needed for a CLI tool |

**Indexer CLI modes** (bootstrap/evolve/full) should be a separate script (e.g., `indexer.py`) following the existing `server.py` argparse pattern, NOT added as MCP tools. Rationale: indexing is a slow, multi-file operation unsuitable for MCP tool call semantics.

**Do NOT add:** `langchain`, `llamaindex`, or any orchestration framework. Direct Anthropic SDK calls with a structured prompt are sufficient and keep the dependency surface minimal.

**Rate limiting:** The anthropic SDK has built-in retry with exponential backoff. For large codebases, add `asyncio.sleep(0.5)` between API calls in evolve mode to stay within rate limits without an additional library.

---

### Phase 4 — Git Post-Commit Hook

**New dependency: none.** Git hooks are shell/Python scripts installed to `.git/hooks/post-commit`.

| Item | Recommendation | Confidence | Rationale |
|------|---------------|------------|-----------|
| Hook mechanism | Raw Python script at `.git/hooks/post-commit` installed by `install.py` | HIGH | Git hook is a plain executable; no additional framework needed |
| Windows compatibility | Script file with Python shebang + `.bat` wrapper approach | MEDIUM | Windows git (Git for Windows / MSYS2) executes shebang-bearing scripts via bash layer; works in Git Bash. If bare cmd.exe hooks are needed, use a `.bat` that calls `python hook_script.py`. Recommend testing both approaches |
| Changed files detection | `subprocess.run(["git", "diff", "--name-only", "HEAD~1", "HEAD"])` | HIGH | Stdlib subprocess; gets exactly the files changed in last commit; no GitPython needed |
| Hook invocation of indexer | `subprocess.Popen(["python", "indexer.py", "--evolve", ...])` non-blocking | HIGH | Post-commit hook must return quickly; spawn indexer as background process |
| Hook installation | Add to existing `install.py` with explicit user confirmation | HIGH | Consistent with project's existing install tooling |

**Do NOT add:** `gitpython`, `pre-commit` framework, or `husky`. These are over-engineered for a single post-commit hook on one repo.

---

### Phase 5 — Staleness Detection

**No new dependencies.**

| Item | Recommendation | Confidence | Rationale |
|------|---------------|------------|-----------|
| Staleness signal | `potentially_stale: bool` field added to JSON schema | HIGH | Simple flag set by indexer when tracked file changes; cleared on re-index |
| New MCP tool | `get_stale_memories(limit)` added to server.py | HIGH | Returns memories with `potentially_stale: true`; follows existing tool pattern |
| WebUI tab | New Flask route + Jinja template using existing Flask patterns | HIGH | No new Flask plugins needed; existing webui.py pattern covers it |
| Date-based staleness | Optional: flag memories not accessed in N days | MEDIUM | `last_accessed` field from Phase 2b enables this; add as configurable threshold |

---

### Phase 6 — Session Evaluator (Claude Code Stop Hook)

**No new Python dependencies.** Stop hook is a standalone script called by Claude Code.

| Item | Recommendation | Confidence | Rationale |
|------|---------------|------------|-----------|
| Hook type | `Stop` hook in `~/.claude/settings.json` | HIGH | Verified from official docs: Stop hook fires when main Claude Code agent finishes responding |
| Hook script | `evaluator.py` standalone script at `C:/Dev/Engram/evaluator.py` | HIGH | Receives JSON on stdin, writes JSON to stdout; exits 0 to allow stop |
| Stop hook payload | stdin JSON with `session_id`, `transcript_path`, `cwd`, `stop_hook_active`, `last_assistant_message` | HIGH | Verified from code.claude.com/docs/en/hooks |
| Infinite loop prevention | Check `stop_hook_active` field; if true, skip evaluation | HIGH | Official docs flag this as the critical safety check |
| Session transcript reading | Read `transcript_path` JSONL with stdlib `json` | HIGH | Path provided in payload; no special library needed |
| Claude API call | `anthropic.Anthropic().messages.create()` synchronous (not async) | HIGH | Stop hook script runs outside asyncio context; sync SDK is appropriate here |
| Output to approve/deny stop | Exit 0 with no `decision: block` JSON to allow stop; or `{"decision": "block", "reason": "..."}` to continue | HIGH | Verified from official docs |
| Settings.json location | `~/.claude/settings.json` (user-level) | HIGH | Makes the evaluator always-on across all projects, matching PROJECT.md requirement |

**Configuration in `~/.claude/settings.json`:**

```json
{
  "hooks": {
    "Stop": [
      {
        "type": "command",
        "command": "python C:/Dev/Engram/evaluator.py",
        "timeout": 60
      }
    ]
  }
}
```

**Do NOT use:** `prompt`-type or `agent`-type Stop hooks (these spawn subagents). A `command`-type hook calling our own Python script gives full control over the evaluation logic, Claude API calls, and approval gate.

---

## Full Dependency Summary

### No Changes to `requirements.txt` Needed for Phases 1, 2, 4, 5, 6

These phases use only existing dependencies + Python stdlib.

### Phase 3 Addition

```
anthropic>=0.86.0,<1.0
```

Already described as "available in venv" in PROJECT.md — confirm with:
```bash
python -m pip show anthropic
```

If not installed:
```bash
python -m pip install "anthropic>=0.86.0,<1.0"
```

### Optional Phase 3 Addition (Recommended)

```
pathspec>=0.12.1
```

For gitignore-aware file filtering in the codebase indexer. Install:
```bash
python -m pip install "pathspec>=0.12.1"
```

Alternative if `pathspec` is rejected: use `subprocess.run(["git", "ls-files"])` to enumerate tracked files — simpler but limits indexer to files already committed.

---

## Alternatives Considered and Rejected

| Category | Recommended | Rejected | Why Rejected |
|----------|-------------|---------|--------------|
| Cosine similarity | numpy dot product (stdlib transitive dep) | scikit-learn, scipy | No new dependency needed; sentence-transformers already in venv; sklearn adds 100MB+ |
| File hashing | hashlib.md5 (stdlib) | xxhash, blake3 | Performance difference irrelevant at file-level granularity; no new deps |
| Git integration | subprocess git commands | gitpython | GitPython is 3x the complexity for reading changed file lists; subprocess.run is sufficient |
| Stop hook type | command (Python script) | prompt-type, agent-type | Command type gives full control over API calls, approval gate, and error handling |
| Indexer entry point | Separate indexer.py CLI | New MCP tools | Indexing is slow/batch; MCP tools expect fast responses; CLI pattern already established |
| Hook framework | Raw .git/hooks/post-commit | pre-commit, husky | One hook, one repo; full framework is unnecessary overhead |
| LLM orchestration | Direct anthropic SDK calls | langchain, llamaindex | Minimal dependency surface; one synthesis call per file group does not need a framework |
| Skill invocation control | `disable-model-invocation: true` | No frontmatter | Without this, Claude may auto-invoke `/engramize` mid-task; must be user-controlled |

---

## Version Verification Checklist

Before starting each phase, run:

```bash
python -m pip show fastmcp sentence-transformers chromadb flask anthropic
```

Expected versions (from requirements.txt and research):
- fastmcp: 3.1.x
- sentence-transformers: 5.3.x
- chromadb: 1.5.x
- flask: 3.1.x
- anthropic: 0.86.x (Phase 3+)

---

## Sources

- FastMCP 3.x tool patterns: [gofastmcp.com/servers/tools](https://gofastmcp.com/servers/tools), [FastMCP 3.0 release blog](https://www.jlowin.dev/blog/fastmcp-3)
- Anthropic SDK version 0.86.0: [pypi.org/project/anthropic](https://pypi.org/project/anthropic/), [github.com/anthropics/anthropic-sdk-python](https://github.com/anthropics/anthropic-sdk-python)
- Claude Code skills format: [code.claude.com/docs/en/skills](https://code.claude.com/docs/en/skills) (fetched directly, HIGH confidence)
- Claude Code Stop hook format: [code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks) (fetched directly, HIGH confidence)
- sentence-transformers cosine similarity: [sbert.net/docs/sentence_transformer/usage/semantic_textual_similarity.html](https://sbert.net/docs/sentence_transformer/usage/semantic_textual_similarity.html)
- ChromaDB cosine distance conversion: [docs.trychroma.com/guides](https://docs.trychroma.com/guides)
- pathspec library: [pypi.org/project/pathspec](https://pypi.org/project/pathspec/)
