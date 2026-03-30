# Domain Pitfalls

**Domain:** MCP memory server — semantic dedup, codebase indexing, relationship tracking, session evaluation
**Researched:** 2026-03-29
**Confidence:** HIGH (codebase verified) / MEDIUM (ChromaDB, skills) / HIGH (stop hook docs)

---

## Critical Pitfalls

Mistakes that cause rewrites, silent data corruption, or unrecoverable states.

---

### Pitfall 1: ChromaDB Rejects Empty Arrays in Metadata

**What goes wrong:** When storing a memory with no related memories yet, setting `related_to: []` in ChromaDB metadata raises `ValueError: Expected metadata value to be a str, int, float or bool`. ChromaDB 1.x allows arrays of primitives but explicitly forbids empty arrays. Every `store_memory` call for a new memory (before any relationships are established) will crash the ChromaDB upsert step.

**Why it happens:** ChromaDB validates metadata at write time. The spec says arrays must have at least one element. This is not obvious from surface-level docs — only the issue tracker and `types.py` source confirm it.

**Consequences:** The `_prepare_store` path writes JSON first, then upserts to ChromaDB. If the ChromaDB upsert throws on an empty `related_to` array, the JSON is persisted but the chunk is not indexed — a JSON/Chroma drift that degrades search without any visible error beyond the existing WARNING log.

**Prevention:**
- Never store `related_to` as an empty array in ChromaDB metadata.
- Store `related_to` as a comma-separated string in ChromaDB (e.g. `""` for no relations, `"keyA,keyB"` for linked memories). The canonical list form lives in JSON only.
- The `get_related_memories` tool reads the JSON field, not the ChromaDB metadata field, so no functionality is lost.
- Alternative: omit the field entirely from ChromaDB metadata when empty; add it only when at least one relationship exists.

**Detection:** Unit test `store_memory` with no `related_to` value and verify the ChromaDB upsert does not raise.

**Phase:** Phase 2b (related_to field implementation).

---

### Pitfall 2: Deduplication False Positives on Short or Boilerplate Content

**What goes wrong:** The 0.92 cosine similarity gate incorrectly blocks storage of memories that are semantically distinct but textually similar. This most commonly hits: (1) short memories under ~100 words where sentence-transformer embeddings are noisy, (2) memories sharing a boilerplate structure (e.g. all architecture decisions start with "Decision: X. Rationale: Y. Outcome: Z."), and (3) memories about the same topic across different projects.

**Why it happens:** `all-MiniLM-L6-v2` was trained for semantic textual similarity on sentence pairs. At 0.92, even structurally similar but content-different documents can exceed the threshold. Short texts are particularly vulnerable because there are few tokens to differentiate meaning.

**Consequences:** The agent silently fails to store important session context. The user gets a "duplicate detected" message but the new memory — which may contain a different decision for a different project — is discarded. There is no "force store" escape hatch, so the information is lost entirely.

**Prevention:**
- Make the threshold configurable per-project AND per-call (a `force=True` parameter on `store_memory`).
- When dedup fires, surface the existing duplicate memory key and similarity score in the response so the user can decide: the tool should return `{"status": "duplicate", "existing_key": "...", "similarity": 0.94}` not just reject silently.
- Add a minimum content length check: skip dedup entirely for memories under 150 characters (too short for reliable embedding).
- Consider checking tags as a secondary gate: two memories with identical content but different project tags (e.g. `sylvara` vs `lumen`) should not deduplicate.

**Detection:** Test with two memories that share a header template but have different body content. Test with a memory about "authentication design" for project A vs project B.

**Warning signs:** Users reporting important memories "didn't save" — especially common when storing multiple session outcomes in quick succession.

**Phase:** Phase 1 (Engramize skill) and Phase 2a (deduplication gate).

---

### Pitfall 3: Audit Log Appended to Content Poisons Deduplication

**What goes wrong:** The existing `_prepare_store` appends a timestamp audit line (`--- 2026-03-29T12:00:00 | Updated via Engram`) to every stored content. This means each update changes the embedding of the memory. At 0.92 threshold, the previous version of a memory and its updated version may score below 0.92 — causing the deduplication gate to treat an update as a new memory rather than a duplicate. Alternatively, two distinct memories edited close together may hash similarly if the audit line dominates the embedding.

**Why it happens:** The audit suffix was implemented before dedup was planned. It's not removed during the dedup similarity check.

**Consequences:** Dedup becomes unreliable: it sometimes passes when it should block (audit line diverges embeddings between versions) and sometimes blocks when it should pass (short memories where the audit line is a large fraction of the text).

**Prevention:**
- Perform the cosine similarity check against content **without** the audit suffix — strip the `\n\n---\n**...** ` block before embedding for the dedup comparison.
- This is also the right fix for the pre-existing "audit log accumulates in content" concern noted in CONCERNS.md.
- Ideally, move the audit log to a separate `history` JSON field (as suggested in CONCERNS.md) before implementing dedup.

**Detection:** Store a memory, wait, update it with minor changes, and verify dedup does not block the update. If it does, the audit line is corrupting the comparison.

**Phase:** Phase 2a (deduplication gate) — must fix audit log accumulation first or during the same phase.

---

### Pitfall 4: API Cost Spiraling on Codebase Indexing

**What goes wrong:** The codebase indexer sends large file batches to Claude Sonnet with no per-run or per-month cost ceiling. A large repository (20K+ lines across 50 files) can consume $5–15 per full bootstrap run. Running `evolve` mode after every commit on an active codebase can accumulate $30–50/day without the developer noticing. Projects at `C:\Obsidian` (large knowledge vault) are especially risky.

**Why it happens:** Code files are verbose. A single file with docstrings and comments can be 3,000+ tokens. Sonnet input pricing ($3/MTok) makes 100 files × 3K tokens = $0.90 per run, and output tokens (synthesis responses) add more. No hard stop is enforced in the design.

**Consequences:** Unexpected API charges. Runaway automation (e.g. git post-commit hook triggering evolve on every commit during a refactor session) can drain the account.

**Prevention:**
- Implement a mandatory per-run token budget and a dry-run mode that estimates cost before any API call is made.
- Use Anthropic's `messages.countTokens` API to pre-estimate cost before sending; abort or warn if over threshold.
- In `evolve` mode, only send changed files to the API — not the full codebase. Use `git diff --name-only HEAD~1 HEAD` to scope the batch.
- Add a configurable `max_tokens_per_run` in `per_project_config` (default: 100K input tokens) and enforce it before dispatching API calls.
- Log every API call with model, input_tokens, output_tokens, and estimated cost to a local file.
- Set a hard daily cap in the git hook: if today's log shows > N tokens consumed, skip evolve and warn.

**Detection:** Add cost estimation output to every indexer run. Track cumulative spend in a `.planning/indexer-cost.log`.

**Warning signs:** Indexer runs taking longer than expected; git commits suddenly slow due to the post-commit hook.

**Phase:** Phase 3 (Codebase Indexer) — cost controls must be in the first implementation, not retrofitted.

---

### Pitfall 5: Git Post-Commit Hook Silently Fails on Windows

**What goes wrong:** Git hooks on Windows have well-documented reliability issues. The shebang line (`#!/usr/bin/env python`) does not resolve correctly in Git for Windows (MinGW/Git Bash environment). Hooks may run successfully when executed manually but silently fail when Git triggers them. Hooks that call external scripts via subprocess from a Python hook may fail because `PATH` inside the git hook environment on Windows differs from the user's shell `PATH`.

**Why it happens:** Git for Windows executes hooks through its bundled bash shell. The `PATH` in that shell does not include `C:\Dev\Engram\venv\Scripts\` by default. Python `venv` activation does not carry over from the user's session.

**Consequences:** The `evolve` mode never runs after commits even though the hook appears installed. The developer assumes indexing is happening; it is not. No error is visible in the git commit output for `post-commit` (errors are suppressed because post-commit hooks cannot abort a commit).

**Prevention:**
- Use explicit absolute paths for the Python interpreter in the hook: `C:/Dev/Engram/venv/Scripts/python.exe` — never rely on `python` resolving from PATH inside the hook.
- Write the hook body in Python (not bash) using the venv Python directly: `#!/c/Dev/Engram/venv/Scripts/python` as the shebang.
- Alternatively, write a minimal `.bat` wrapper that activates the venv explicitly, and use `core.hooksPath` to point git to a hooks directory containing the `.bat` files.
- Add a self-test command: `python engram.py --verify-git-hook` that manually runs the hook script and confirms it executes correctly.
- Log every hook invocation to a timestamped file so the developer can verify hooks are firing.

**Detection:** After hook installation, make a test commit and check the log file. If no log entry appears within 5 seconds, the hook is not firing.

**Warning signs:** The indexer memory count is not growing after active commits.

**Phase:** Phase 3 (git hook installation) — write the hook installer in Python using absolute venv paths from day one.

---

### Pitfall 6: Stop Hook Infinite Loop via `stop_hook_active` Blindness

**What goes wrong:** The session evaluator fires on every Claude Code session stop. If the hook script does not check the `stop_hook_active` flag in the JSON input and always returns `{"decision": "block", "reason": "..."}`, it creates an infinite loop: Claude stops → hook blocks → Claude continues and produces another response → Claude stops again → hook blocks again. The session never terminates.

**Why it happens:** This is the #1 documented pitfall in the Claude Code hooks reference. The `stop_hook_active: true` flag signals that Claude is already in a forced-continuation state from a previous block. Failing to respect it creates a deadlock.

**Consequences:** Session hangs indefinitely. The user must force-kill Claude Code. Any in-progress work is potentially lost.

**Prevention:**
- The very first line of the session evaluator hook must read and check `stop_hook_active`. If `true`, exit 0 immediately without blocking.
- Never set `decision: "block"` unconditionally. Always have a fallback path that allows Claude to stop.
- Test the infinite-loop prevention explicitly: simulate a hook invocation with `stop_hook_active: true` and confirm it returns exit 0.
- Keep the approval gate logic simple — if the hook cannot determine whether to block within 5 seconds, allow Claude to stop (fail open, not fail closed).

**Detection:** Run a test session and verify it terminates normally. Set `stop_hook_active: true` in a manual test invocation and confirm the hook exits 0.

**Warning signs:** Sessions that never end; increasing CPU usage from stuck hook processes.

**Phase:** Phase 5 (session evaluator hook).

---

### Pitfall 7: Skill File Format Breaks Automatic Triggering

**What goes wrong:** The Engramize skill file (`~/.claude/skills/engramize/SKILL.md`) does not trigger automatically because: (1) the description exceeds 250 characters and gets truncated in Claude's skill listing, cutting off the keywords that would match user requests; (2) the frontmatter `---` delimiters are missing or malformed, causing the entire file to be treated as plain markdown without metadata; (3) the skill directory name does not match the `name` field, creating a mismatch.

**Why it happens:** The skill description character limit (250 chars max before truncation in the skill listing) is not obvious. Skills descriptions are front-loaded in context, and truncation strips the use-case keywords that drive automatic activation. Official docs note that skill activation goes from 20% to 90% success rate with proper description optimization.

**Consequences:** The Engramize skill is technically installed but never activates automatically. Users must invoke it manually with `/engramize` every time, which defeats the "natural mid-session memory creation" goal.

**Prevention:**
- Front-load the key trigger phrases in the description: start with "Use when..." and put the most specific trigger keywords in the first 100 characters.
- Keep the description under 200 characters to ensure it is never truncated.
- Use `disable-model-invocation: false` explicitly (or omit, as false is default) to confirm the skill is auto-activatable.
- Test by asking Claude: "What skills are available?" to verify the skill appears with its description.
- Test automatic activation by saying "Store this as a memory" and verifying the skill loads without explicit `/engramize` invocation.

**Detection:** After installation, run `What skills are available?` in a Claude Code session and check that the engramize description is fully visible and not truncated.

**Warning signs:** Skill appears in the list but never fires unless explicitly invoked.

**Phase:** Phase 1 (Engramize skill).

---

## Moderate Pitfalls

---

### Pitfall 8: `last_accessed` Tracking Adds Per-Retrieval Write Overhead

**What goes wrong:** Every call to `search_memories`, `retrieve_chunk`, and `retrieve_memory` must now write an updated `last_accessed` timestamp to the JSON file. At current scale this is imperceptible, but the existing CONCERNS.md already flags `list_memories` as a scaling concern at 1000+ memories. Adding per-retrieval writes converts a previously read-heavy workload to read-write, and increases JSON/ChromaDB drift risk: if `last_accessed` is stored in ChromaDB metadata too, every retrieval requires a ChromaDB metadata upsert.

**Prevention:**
- Store `last_accessed` in JSON only — not in ChromaDB metadata. ChromaDB is the index; temporal tracking is data.
- Batch `last_accessed` updates: write on a 30-second flush timer rather than immediately on every retrieval, to avoid hammering disk during a burst of searches.
- Alternatively, maintain an in-memory `last_accessed` cache and flush to disk at process shutdown/startup.

**Phase:** Phase 2a.

---

### Pitfall 9: Staleness Detection Cries Wolf

**What goes wrong:** The `potentially_stale` flag is set when indexed files change after a memory was created. If the indexer is too sensitive (any file change in the codebase triggers staleness for all architecture memories), the WebUI staleness tab fills up with noise. Users start ignoring it — the tab loses its value.

**Prevention:**
- Scope staleness to file-level: only flag memories whose `source_files` metadata includes the changed file.
- Set a minimum change threshold: a 5-line diff in a non-structural file (e.g. a constant value change) should not trigger staleness for architecture memories.
- Consider a staleness "confidence" level: trivial changes = "possibly stale", file deletion or rename = "likely stale".

**Phase:** Phase 4 (staleness detection).

---

### Pitfall 10: Session Evaluator Captures Low-Value Sessions

**What goes wrong:** The always-on Stop hook fires for every session, including: one-line Q&A sessions, sessions where the user gave up mid-way, and sessions where no code was changed. Automatically creating memories for these sessions bloats the memory store with low-signal content and increases dedup noise.

**Prevention:**
- Add a minimum session length gate in the evaluator hook: skip sessions with fewer than 3 assistant turns, fewer than 100 words in the assistant's responses, or no tool calls.
- Read `last_assistant_message` (guaranteed available in hook input) to detect sessions that ended with "I can't help with that" or error messages.
- Make the minimum quality threshold configurable in `per_project_config`.

**Phase:** Phase 5 (session evaluator).

---

### Pitfall 11: Codebase Indexer Overwrites Human-Edited Memories Without Warning

**What goes wrong:** The `evolve` mode re-indexes changed files and upserts new memories. If a developer has manually edited an Engram memory to correct or extend the auto-generated content, `evolve` silently overwrites it with fresh API synthesis output, discarding the human refinement.

**Prevention:**
- Implement the "manual edits win" rule (already in PROJECT.md Key Decisions) as a concrete check: before overwriting a memory, compare `updated_at` against the indexer's last run timestamp. If `updated_at` is newer, skip the overwrite and log a warning.
- Add a `--force` flag to `evolve` and `full` modes that explicitly permits overwriting human-edited memories.
- Tag indexer-generated memories with `source:indexer` so the conflict check can be scoped.

**Phase:** Phase 3 (codebase indexer).

---

## Minor Pitfalls

---

### Pitfall 12: Backward Compatibility Breaks from New Required JSON Fields

**What goes wrong:** Adding `related_to`, `last_accessed`, `potentially_stale`, and `source_files` fields to the JSON schema without defensive reads causes `KeyError` in every code path that reads existing JSON files pre-migration. The `list_memories` function reads all JSON files on every call; one file with a missing field would raise and break the entire listing.

**Prevention:**
- Use `data.get("related_to", [])`, `data.get("last_accessed", None)`, etc. everywhere these fields are read.
- Never assume a new field exists; all new fields must have sensible defaults that allow old memories to function without migration.
- The `--rebuild-index` command is the migration path; add a migration step there that backfills missing fields with defaults rather than requiring all memories to be re-stored manually.

**Phase:** Phases 2b, 2a, 4, 3 respectively — apply this pattern as each field is introduced.

---

### Pitfall 13: Per-Project Config File Not Found Crashes the Indexer

**What goes wrong:** The indexer's per-project config (`domain_questions`, `source_files`, etc.) is loaded from a project-local config file. If that file is missing, malformed, or pointing to a nonexistent directory, the indexer raises an unhandled exception and exits without a useful error message.

**Prevention:**
- Always validate the per-project config on load. If missing, print a clear actionable message: "No indexer config found for this project. Run `python engram.py init-project /path/to/project` to generate one."
- Never let a missing config crash silently — fail loudly with context.
- Provide a template config generator as part of the indexer CLI.

**Phase:** Phase 3.

---

### Pitfall 14: Windows Path Separator Breaks Glob Patterns in Skill `paths` Field

**What goes wrong:** The skill `paths` frontmatter field accepts glob patterns. On Windows, if the pattern uses backslashes (`src\**\*.py`), Claude Code's glob matching (which uses forward-slash patterns internally) will never match and the skill silently never activates for matching files.

**Prevention:**
- Always use forward slashes in `paths` glob patterns, even on Windows: `src/**/*.py` not `src\**\*.py`.
- Document this in the skill file comment.
- This is consistent with the PROJECT.md constraint "All paths must use forward slashes or os.path.join."

**Phase:** Phase 1 (skill file creation) and Phase 3 (auto-generated skill files from indexer).

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| Phase 1: Engramize skill | Description truncation kills auto-trigger | Keep description under 200 chars; front-load trigger keywords |
| Phase 1: Engramize skill | Skill triggers on unrelated memory queries | Add `disable-model-invocation: true` if over-triggering; tune description |
| Phase 2a: Deduplication gate | Audit log suffix corrupts similarity check | Strip audit suffix before embedding comparison |
| Phase 2a: Deduplication gate | False positives block legitimate stores | Surface existing duplicate key + score; add `force=True` escape hatch |
| Phase 2a: `last_accessed` tracking | Per-retrieval write bottleneck | Write to JSON only; batch flushes |
| Phase 2b: `related_to` field | Empty array crashes ChromaDB upsert | Store as comma-string in Chroma; list in JSON only |
| Phase 3: Codebase indexer | API cost spiral on large repos | Token budget + dry-run mode before any production use |
| Phase 3: Codebase indexer | `evolve` overwrites human edits | Compare `updated_at` to indexer timestamp; skip if human-newer |
| Phase 3: Git hook | Silent failure on Windows PATH | Hardcode venv Python path; log every hook invocation |
| Phase 4: Staleness detection | Over-flagging creates noise | File-level scoping; minimum change threshold |
| Phase 5: Session evaluator | Infinite loop from missing `stop_hook_active` check | Check flag as first line of hook; always fail open |
| Phase 5: Session evaluator | Low-quality sessions create noise memories | Minimum turn count + word count gate |
| All phases | New JSON fields break old memory reads | `.get()` with defaults everywhere; migration in rebuild-index |

---

## Sources

- ChromaDB metadata array constraints: [ChromaDB Issue #1552](https://github.com/chroma-core/chroma/issues/1552), [ChromaDB FAQ Cookbook](https://cookbook.chromadb.dev/faq/), [Metadata Filtering Docs](https://docs.trychroma.com/docs/querying-collections/metadata-filtering)
- Deduplication threshold behavior: [Milvus — Tuning similarity thresholds](https://milvus.io/ai-quick-reference/how-do-you-tune-similarity-thresholds-to-reduce-false-positives), [FutureSearch — Semantic Deduplication](https://futuresearch.ai/semantic-deduplication/)
- Claude Code Stop hook pitfalls: [Claude Code Hooks Reference](https://code.claude.com/docs/en/hooks), [Stop hook error issue #34600](https://github.com/anthropics/claude-code/issues/34600)
- Skill file format and triggering: [Claude Code Skills Reference](https://code.claude.com/docs/en/skills), [Experts Exchange — Skills anatomy](https://www.experts-exchange.com/articles/40886/Setting-Up-Claude-Code-Properly-Part-3-Skills-anatomy-triggering-global-skills.html)
- Git hooks on Windows: [Medium — Git hooks on Windows pitfalls](https://medium.com/@rohitkvv/how-to-run-git-hooks-in-windows-using-c-avoiding-common-pitfalls-9166c441abef), [tygertec — Git hooks practical uses on Windows](https://www.tygertec.com/git-hooks-practical-uses-windows/)
- API cost control: [Claude Code — Manage costs](https://code.claude.com/docs/en/costs), [Anthropic token counting](https://towardsdatascience.com/introducing-the-new-anthropic-token-counting-api-5afd58bad5ff/)
- Codebase-specific constraints: `C:/Dev/Engram/.planning/PROJECT.md`, `C:/Dev/Engram/.planning/codebase/CONCERNS.md`
