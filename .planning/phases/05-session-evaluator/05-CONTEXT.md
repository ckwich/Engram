# Phase 5: Session Evaluator - Context

**Gathered:** 2026-04-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Claude Code Stop hook that evaluates every session after it ends, drafts memories for worthy sessions, and presents them for approval. Non-blocking (detached subprocess), loop-safe (stop_hook_active check), dedup-protected (Phase 2 gate), always-on.

</domain>

<decisions>
## Implementation Decisions

### Hook Architecture
- **D-01:** Hook script lives at `C:/Dev/Engram/hooks/engram_stop.py`. Claude Code settings.json points to it with absolute venv Python path.
- **D-02:** Hook reads stdin JSON, checks `stop_hook_active` as absolute first action (exit immediately if true), then spawns evaluator as detached subprocess with `CREATE_NO_WINDOW` flag.
- **D-03:** Evaluator uses `claude.cmd -p` for evaluation (same pattern as Phase 3 indexer). Uses Max plan, zero cost.
- **D-04:** Hook must exit in under 10 seconds. All heavy work happens in the detached subprocess.

### Evaluation Logic
- **D-05:** Primary context = `last_assistant_message` from hook payload. Fastest, cheapest, usually contains session outcome.
- **D-06:** Single `claude -p` call with session context + configured criteria. Claude returns structured JSON: `{worth_capturing: bool, confidence: float, draft_key: str, draft_title: str, draft_content: str, draft_tags: list, reasoning: str}`.
- **D-07:** Evaluation prompt includes the configured logic_win_triggers and milestone_triggers from project config.

### Approval Flow
- **D-08:** Pending file pattern. Evaluator writes draft to `.engram/pending_memories/{date}_{key}.json`. At next session start, a skill checks for pending drafts and presents them for approval.
- **D-09:** Need a `pending-memories` skill at `~/.claude/skills/engram-pending/SKILL.md` that auto-loads on session start and checks for pending drafts.
- **D-10:** Dedup gate (Phase 2) runs before writing the pending file. If near-duplicate exists, include the similar memory info in the pending file so the approval prompt shows it.
- **D-11:** auto_approve_threshold is confidence-based. If Claude's confidence >= threshold, store immediately without writing a pending file. Default 0.0 = always ask.
- **D-12:** Pending drafts persist indefinitely until approved or manually deleted. Surface in next session via the pending-memories skill.

### Per-Project Config
- **D-13:** Config lives in per-project `.engram/config.json` `session_evaluator` section. Falls back to Engram global defaults if no project config exists.
- **D-14:** Default criteria: logic_win_triggers = ["bug resolved", "new capability added", "architectural decision made"]; milestone_triggers = ["phase completed", "feature shipped", "significant refactor done"]; auto_approve_threshold = 0.0.

### Claude's Discretion
- Exact evaluation prompt wording and system message
- How to format the pending draft approval presentation in the skill
- Whether to log evaluation results to a file for debugging
- How to handle Claude CLI failures during evaluation (retry once? skip?)
- Pending file naming convention details

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Hook Infrastructure
- `.planning/research/STACK.md` — Stop hook payload format (session_id, transcript_path, cwd, stop_hook_active, last_assistant_message)
- `.planning/research/PITFALLS.md` — stop_hook_active infinite loop prevention

### Subprocess Patterns
- `engram_index.py` — Claude CLI subprocess pattern (claude.cmd, --output-format json, --no-session-persistence)
- Phase 3 CONTEXT.md — D-01 CLI pivot decision, D-17 absolute venv path

### Dedup Integration
- `core/memory_manager.py` — DuplicateMemoryError, _check_dedup, store_memory with force param

### Skill Format
- `C:/Users/colek/.claude/skills/engramize/SKILL.md` — Reference for skill file format
- Phase 1 CONTEXT.md — Skill conventions (SKILL.md uppercase, frontmatter fields)

### Config Pattern
- `config.json` — Engram runtime config (add session_evaluator defaults)
- Phase 3 `.engram/config.json` — Per-project config pattern

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `claude.cmd -p` subprocess pattern from `engram_index.py` `synthesize_domain()` — reuse for evaluation
- `CREATE_NO_WINDOW` + `subprocess.Popen` from `engram_index.py` git hook — reuse for detached evaluator
- `memory_manager.store_memory()` sync API — for storing approved memories
- `memory_manager._check_dedup()` — for pre-approval dedup check
- `_load_config()` in memory_manager.py — for loading evaluation criteria

### Established Patterns
- JSON stdin parsing (standard Python json.load(sys.stdin))
- Absolute venv Python paths for Windows compatibility
- SKILL.md with frontmatter for auto-loading skills

### Integration Points
- `hooks/engram_stop.py` — NEW file, hook entry point
- `hooks/engram_evaluator.py` — NEW file, detached evaluator subprocess
- `~/.claude/skills/engram-pending/SKILL.md` — NEW skill for surfacing pending drafts
- Claude Code `settings.json` — needs hook registration (manual step)
- `.engram/pending_memories/` — NEW directory per project for draft files

</code_context>

<specifics>
## Specific Ideas

- The pending file JSON format was previewed in discussion — includes draft_key, draft_title, draft_content, draft_tags, confidence, reasoning, session_id, evaluated_at.
- The settings.json hook configuration was previewed — uses absolute venv Python path.
- The pending-memories skill should NOT use disable-model-invocation (should auto-load and check on session start).

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 05-session-evaluator*
*Context gathered: 2026-04-04*
