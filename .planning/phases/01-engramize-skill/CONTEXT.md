# Phase 1 Context — Engramize Skill

## Decisions Made

### Skill File Naming
- **SKILL.md** (uppercase) — matches official Claude Code skill convention
- Install path: `C:\Users\colek\.claude\skills\engramize\SKILL.md`

### Ambiguity Handling
- **Infer, then confirm** — when user says bare "engramize this", the skill instructs Claude to draft the memory from recent conversation context, then show it to the user for approval before calling store_memory

### Deduplication
- **No dedup in Phase 1** — skill calls store_memory directly. Dedup gate is Phase 2's responsibility at the server level

### Content Strategy
- Structured markdown with headers (## Context, ## Decision/Pattern/Finding, ## Watch Out For)
- Mirrors "Model B" architecture from Phase 3 for consistency
- 3000-char soft limit enforced by skill instructions (server has 15K hard limit)

### Tag Inference
- Project name inferred from cwd directory name
- Domain inferred from conversation context
- Type from fixed vocabulary: decision, pattern, constraint, gotcha, architecture
- All inferences shown to user during confirmation step

### MCP Tool Access
- Uses existing mcp__engram__store_memory — no new server code needed
- Phase 1 is purely a skill file creation task

## Research Flags
- Skill frontmatter: name, description (under 250 chars, front-loaded with trigger), disable-model-invocation: true
- allowed-tools syntax for MCP tools needs verification (mcp__engram__store_memory format)
- Windows skill loading from ~/.claude/skills/ confirmed to work (resolves to C:\Users\colek\.claude\skills\)
