# Phase 1: Engramize Skill — Research

**Researched:** 2026-03-29
**Domain:** Claude Code Skills (SKILL.md format, MCP tool invocation, Windows path resolution)
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **Skill file naming:** SKILL.md (uppercase) — matches official Claude Code skill convention
- **Install path:** `C:\Users\colek\.claude\skills\engramize\SKILL.md`
- **Ambiguity handling:** Infer, then confirm — when user says bare "engramize this", the skill instructs Claude to draft the memory from recent conversation context, then show it to the user for approval before calling store_memory
- **Deduplication:** No dedup in Phase 1 — skill calls store_memory directly. Dedup gate is Phase 2's responsibility at the server level
- **Content strategy:** Structured markdown with headers (## Context, ## Decision/Pattern/Finding, ## Watch Out For); mirrors "Model B" architecture from Phase 3; 3000-char soft limit enforced by skill instructions (server has 15K hard limit)
- **Tag inference:** Project name inferred from cwd directory name; domain inferred from conversation context; type from fixed vocabulary: decision, pattern, constraint, gotcha, architecture; all inferences shown to user during confirmation step
- **MCP tool access:** Uses existing mcp__engram__store_memory — no new server code needed; Phase 1 is purely a skill file creation task

### Claude's Discretion

None listed explicitly — all design decisions are locked for Phase 1.

### Deferred Ideas (OUT OF SCOPE)

- Deduplication gate (Phase 2's responsibility)
- Any new Python server code
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SKIL-01 | User can say "engramize [description]" mid-session and Code creates a properly formatted memory automatically | Trigger via `/engramize` slash command + `$ARGUMENTS` substitution; `disable-model-invocation: true` prevents Claude auto-firing it |
| SKIL-02 | Skill enforces naming conventions (underscore keys, lowercase, descriptive) | Enforced through skill instructions — Claude follows constraints in SKILL.md body when generating the key |
| SKIL-03 | Skill enforces tagging standards (project name, domain, type: decision/pattern/constraint/gotcha/architecture) | Enforced through skill instructions — Claude infers from cwd + context, shows to user before calling store_memory |
| SKIL-04 | Skill enforces content limit (under 3000 characters) | Enforced through skill instructions — Claude checks char count before calling store_memory |
| SKIL-05 | Skill produces human-readable titles ("Sylvara — Billing Webhook Pattern") | Enforced through skill instructions — title format specified in SKILL.md body |
| SKIL-06 | Skill file installed globally at ~/.claude/skills/engramize/skill.md | Path `~/.claude/skills/engramize/SKILL.md` confirmed as personal skill location; resolves to `C:\Users\colek\.claude\skills\engramize\SKILL.md` on Windows |
</phase_requirements>

---

## Summary

Phase 1 requires creating a single SKILL.md file at `~/.claude/skills/engramize/SKILL.md`. This file creates the `/engramize` slash command globally across all Claude Code sessions. The skill is entirely prompt-based: no Python code, no new dependencies, and no server changes. All enforcement (naming conventions, tagging, content limits, title format) is implemented through natural-language instructions in the SKILL.md body, which Claude follows when the skill is invoked.

The official Claude Code skill documentation (fetched from code.claude.com/docs/en/skills, HIGH confidence) confirms all key design assumptions from CONTEXT.md: the `disable-model-invocation: true` frontmatter field exists and works as expected, the `~/.claude/skills/` path is the correct personal skill location, and descriptions over 250 characters are truncated. The `allowed-tools` field syntax for MCP tools is confirmed by the permissions docs as `mcp__<server-name>__<tool-name>`.

The FastMCP server name is `"engram"` (confirmed from `server.py` line 1: `mcp = FastMCP("engram")`), making the full MCP tool reference `mcp__engram__store_memory`. The `store_memory` tool accepts `key`, `content`, `title`, and `tags` parameters.

**Primary recommendation:** Create `~/.claude/skills/engramize/SKILL.md` with `disable-model-invocation: true`, `allowed-tools: mcp__engram__store_memory`, and a body that implements the infer-then-confirm workflow with all convention enforcement baked into the instructions.

---

## Standard Stack

### Core

| Item | Value | Purpose | Why Standard |
|------|-------|---------|--------------|
| SKILL.md location | `~/.claude/skills/engramize/SKILL.md` | Personal global skill | Official docs: personal skills at `~/.claude/skills/<name>/SKILL.md` apply across all projects |
| Frontmatter field: `name` | `engramize` | Becomes the `/engramize` slash command | Official docs: name field creates the `/slash-command` |
| Frontmatter field: `description` | Front-loaded trigger phrase ≤250 chars | Appears in skill listing; front-loaded for keyword matching | Official docs: entries capped at 250 chars in skill listing |
| Frontmatter field: `disable-model-invocation` | `true` | Prevents Claude from auto-triggering the skill | Official docs: use for workflows with side effects; hides skill from Claude's context entirely |
| Frontmatter field: `allowed-tools` | `mcp__engram__store_memory` | Grants permission without per-use approval prompt during skill execution | Official docs + permissions docs: MCP tool format is `mcp__<server>__<tool>` |
| MCP tool: store_memory | `mcp__engram__store_memory` | Writes memory to Engram | Server name `"engram"` confirmed in server.py |

### Supporting

| Item | Value | Purpose | When to Use |
|------|-------|---------|-------------|
| `$ARGUMENTS` substitution | Built-in skill variable | Passes user's description to the skill body | Always — enables `/engramize fix the webhook race condition` |
| `argument-hint` | `[description]` | Shows in autocomplete as hint | Optional UX improvement |

### No Installation Required

```
# No npm install, pip install, or any other package installation needed.
# This phase is a single file creation.
mkdir -p ~/.claude/skills/engramize
# Then write SKILL.md to that directory
```

---

## Architecture Patterns

### Recommended Skill Structure

```
~/.claude/skills/engramize/
└── SKILL.md    # Only file needed; all logic is in the body
```

No supporting files are needed. The skill is short enough to be self-contained in a single SKILL.md.

### Pattern 1: Infer-Then-Confirm Workflow

**What:** When invoked, Claude drafts the full memory (key, title, tags, content) from the conversation context, shows the complete draft to the user in a structured preview, waits for approval or edits, then calls `mcp__engram__store_memory` once confirmed.

**When to use:** Any skill with irreversible side effects (writing data). Prevents unwanted stores and gives the user a chance to correct inferences.

**Example SKILL.md body structure:**
```markdown
When `/engramize` is invoked:

1. **Infer** the memory content from $ARGUMENTS and recent conversation context.
2. **Draft** the following fields:
   - key: snake_case, lowercase, descriptive (e.g. `sylvara_webhook_race_fix`)
   - title: "Project — Topic Pattern" format (e.g. "Sylvara — Webhook Race Fix")
   - tags: project_name, domain, type (one of: decision/pattern/constraint/gotcha/architecture)
   - content: structured markdown under 3000 characters

3. **Show** the complete draft to the user:
   ```
   Key:     sylvara_webhook_race_fix
   Title:   Sylvara — Webhook Race Fix
   Tags:    sylvara, backend, gotcha
   Content: (preview below)
   ---
   [content here]
   ---
   ```

4. **Ask**: "Store this memory? (yes / edit / cancel)"

5. **Only if confirmed**, call mcp__engram__store_memory with the finalized fields.
```

### Pattern 2: Convention Enforcement via Instructions

**What:** All naming, tagging, content, and title conventions are specified as concrete rules in the SKILL.md body. Claude treats these as hard constraints when generating the memory draft.

**When to use:** Any skill that must produce structured, convention-compliant output.

**Rules to include:**
```markdown
## Key naming rules
- snake_case only (no hyphens, no spaces, no uppercase)
- Format: {project}_{domain}_{topic} or {project}_{topic}
- Be specific: `sylvara_billing_webhook_pattern` not `billing_pattern`

## Title format
- Pattern: "Project — Topic" or "Project — Topic Pattern"
- Em dash (—) separator, not hyphen
- Title case: "Sylvara — Billing Webhook Pattern"

## Tag requirements
- Always include: project name (from cwd directory name)
- Always include: domain (inferred from context: backend, frontend, db, infra, etc.)
- Always include: type tag — exactly one of: decision, pattern, constraint, gotcha, architecture

## Content rules
- Use structured markdown headers: ## Context, ## Decision/Pattern/Finding, ## Watch Out For
- Under 3000 characters total
- Captures WHY, not just what — explain the reasoning, not just the outcome
```

### Anti-Patterns to Avoid

- **Auto-storing without confirmation:** Never call `mcp__engram__store_memory` without showing a preview. Side effects require explicit user approval.
- **Using `user-invocable: false`:** This hides the skill from the `/` menu. The opposite of what we want — users need to invoke `/engramize` explicitly.
- **Omitting `disable-model-invocation: true`:** Without this, Claude might auto-invoke `/engramize` when it thinks something is worth saving. This must be user-controlled.
- **Over-long description:** Descriptions over 250 chars are truncated in the skill listing. Front-load the trigger phrase.
- **Empty `allowed-tools`:** Without `allowed-tools: mcp__engram__store_memory`, Claude will prompt for permission every time it calls the tool, breaking the seamless UX.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Slash command creation | Custom command infrastructure | SKILL.md frontmatter `name` field | Official Claude Code skill system creates `/engramize` automatically from the `name` field |
| Permission grant for MCP tools | Custom permission hooks | `allowed-tools: mcp__engram__store_memory` | Frontmatter field grants skill-scoped permission without modifying global settings |
| Argument passing | Custom parsing in skill body | `$ARGUMENTS` substitution | Built-in skill variable; Claude Code substitutes it automatically before skill body reaches the model |

**Key insight:** Every "infrastructure" concern (command creation, permission management, argument passing) is already handled by the skill frontmatter. The entire implementation effort is writing clear natural-language instructions in the SKILL.md body.

---

## Common Pitfalls

### Pitfall 1: `disable-model-invocation: true` Also Removes Description from Context

**What goes wrong:** With `disable-model-invocation: true`, the skill description is NOT loaded into Claude's context at all (unlike default skills where the description is always present). Claude will not automatically suggest using `/engramize` even when it would be relevant.

**Why it happens:** Per official docs table: with `disable-model-invocation: true`, "Description not in context, full skill loads when you invoke." This is intentional — it fully hides the skill from Claude's awareness.

**How to avoid:** This is the correct behavior for a side-effect skill. Users explicitly type `/engramize`. The description still appears in the `/` autocomplete menu.

**Warning signs:** Not a pitfall to fix — expected behavior. Document for user-facing notes.

---

### Pitfall 2: MCP Tool Name Must Match Server Registration

**What goes wrong:** If `allowed-tools` uses the wrong server name (e.g. `mcp__Engram__store_memory` with capital E), the permission grant silently fails and Claude gets prompted on every `store_memory` call.

**Why it happens:** The `mcp__<server>__<tool>` format is case-sensitive. The server name comes from the `name` argument in `FastMCP("engram")` — lowercase `engram`.

**How to avoid:** Use exactly `mcp__engram__store_memory`. Verified: `server.py` line 1 is `mcp = FastMCP("engram")`.

**Warning signs:** Claude prompts "Allow mcp__engram__store_memory?" during skill execution even though `allowed-tools` is set.

---

### Pitfall 3: Description Truncation Hides Trigger Keywords

**What goes wrong:** A 300-char description gets truncated to 250 chars in the skill listing. If trigger keywords appear after the 250-char mark, Claude won't see them when deciding whether to load the skill (though this matters less with `disable-model-invocation: true`).

**Why it happens:** Official docs: "descriptions longer than 250 characters are truncated in the skill listing to reduce context usage."

**How to avoid:** Front-load the key trigger phrase. Start with "Use when you want to save" or "Captures important decisions" — not with meta-description text. Since `disable-model-invocation: true` is set, this pitfall is low-severity for this skill (description is not loaded into context anyway), but good practice.

**Warning signs:** `/engramize` description is cut off mid-sentence in the autocomplete menu.

---

### Pitfall 4: `~/.claude/skills/` Directory Does Not Exist Yet

**What goes wrong:** Installing the skill fails silently or writes to the wrong path because `~/.claude/skills/` doesn't exist.

**Why it happens:** The `skills` subdirectory is not created by default. `~/.claude/` exists (confirmed by checking `C:\Users\colek\.claude\`), but `skills/` must be created manually.

**How to avoid:** The plan must include a mkdir step before writing SKILL.md:
```bash
mkdir -p ~/.claude/skills/engramize
```
On Windows this resolves to `C:\Users\colek\.claude\skills\engramize\`. The `~` tilde is resolved by bash/Git Bash.

**Warning signs:** SKILL.md write fails with "directory not found" or similar error.

---

### Pitfall 5: Store Without Confirming Character Count

**What goes wrong:** Claude drafts content over 3000 chars and stores it. The server accepts it (15K hard limit), but violates the Phase 1 soft-limit convention.

**Why it happens:** Without explicit instruction to count characters, Claude may not self-check content length.

**How to avoid:** Skill instructions must explicitly state: "Before calling store_memory, verify the content section is under 3000 characters. If over, ask the user which sections to trim."

**Warning signs:** Stored memory is truncated or oversized when retrieved.

---

## Code Examples

Verified patterns from official sources:

### Minimum Valid SKILL.md (Official Docs Pattern)
```yaml
---
name: engramize
description: Save an important decision, pattern, or finding as an Engram memory. Use when you want to capture architectural insights, implementation decisions, or lessons learned mid-session.
disable-model-invocation: true
allowed-tools: mcp__engram__store_memory
---

[skill body here]
```
Source: https://code.claude.com/docs/en/skills (frontmatter reference table)

### MCP Tool Permission Format (Official Permissions Docs)
```
# In allowed-tools frontmatter field:
mcp__engram__store_memory

# Pattern: mcp__<server-name>__<tool-name>
# server-name = FastMCP("engram") registration name
# tool-name   = Python async function name decorated with @mcp.tool()
```
Source: https://code.claude.com/docs/en/permissions (MCP section)

### store_memory Call Signature (from server.py)
```python
async def store_memory(
    key: str,       # e.g. "sylvara_webhook_race_fix"
    content: str,   # markdown, max 15000 chars (3000 soft limit for this skill)
    title: str = "",  # e.g. "Sylvara — Webhook Race Fix"
    tags: str = "",   # comma-separated: "sylvara,backend,gotcha"
) -> str:
```
Source: `C:/Dev/Engram/server.py` lines 143-148

### $ARGUMENTS Substitution (Official Docs)
```yaml
---
name: engramize
description: ...
---

The user wants to capture: $ARGUMENTS

[rest of instructions...]
```
When user runs `/engramize fix the webhook race condition`, Claude receives:
"The user wants to capture: fix the webhook race condition"
Source: https://code.claude.com/docs/en/skills (Pass arguments to skills)

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `.claude/commands/deploy.md` flat files | `~/.claude/skills/<name>/SKILL.md` in subdirectory | Current (docs note both still work) | Skills add frontmatter control, supporting files directory; commands still work but skills recommended |

**Deprecated/outdated:**
- `.claude/commands/` format: Still supported but superseded by skills. "Custom commands have been merged into skills." Both create the same `/command` and work identically. Skills are preferred for new work.

---

## Open Questions

1. **Does `allowed-tools` suppress the MCP approval prompt during skill execution?**
   - What we know: Official docs say `allowed-tools` "Tools Claude can use without asking permission when this skill is active." Permissions docs confirm `mcp__server__tool` is valid syntax.
   - What's unclear: Whether "when this skill is active" means only while the skill body is executing, or for the entire session after invocation. Given the skill body calls `store_memory` directly, execution-scope is sufficient.
   - Recommendation: Include `allowed-tools: mcp__engram__store_memory` as specified. If it doesn't suppress the prompt in practice, the skill still works — it just requires one extra approval click. LOW risk.
   - Confidence: MEDIUM (syntax confirmed, runtime behavior not tested on this machine)

2. **Does `/engramize` appear in the autocomplete menu before `~/.claude/skills/` is created?**
   - What we know: Skills are loaded at startup. The directory doesn't exist yet.
   - What's unclear: Nothing — creating the directory and SKILL.md is the implementation task.
   - Recommendation: Plan must mkdir first, then write SKILL.md. Skills are not hot-reloaded mid-session by default unless in `--add-dir` mode.
   - Confidence: HIGH

---

## Environment Availability

Step 2.6: SKIPPED (no external dependencies identified — Phase 1 is a single file creation with no CLIs, runtimes, or services beyond the already-running Engram MCP server).

---

## Validation Architecture

`nyquist_validation: true` in `.planning/config.json`.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | Manual verification (no automated test framework applicable) |
| Config file | None — skill validation is behavioral |
| Quick run command | `/engramize test memory` in a Claude Code session |
| Full suite command | See Phase Requirements test map below |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SKIL-01 | `/engramize [description]` creates a memory | Manual smoke | Run `/engramize test decision` in any session; verify store_memory called | N/A |
| SKIL-02 | Key uses snake_case, lowercase | Manual inspection | Check key in Engram WebUI after SKIL-01 test | N/A |
| SKIL-03 | Tags include project, domain, type | Manual inspection | Check tags in Engram WebUI after SKIL-01 test | N/A |
| SKIL-04 | Content under 3000 chars | Manual inspection | Confirm skill truncates or rejects over-3000-char draft | N/A |
| SKIL-05 | Title format "Project — Topic" | Manual inspection | Check title in Engram WebUI after SKIL-01 test | N/A |
| SKIL-06 | Skill available in all sessions | Manual verification | Open new session in different directory; verify `/engramize` appears in `/` menu | N/A |

### Sampling Rate

- **Per task commit:** Not applicable (single file creation phase)
- **Phase gate:** All 6 manual checks pass before marking phase complete

### Wave 0 Gaps

None — this phase creates no code files. No test infrastructure needed. Validation is entirely manual (behavioral testing of the skill in a live Claude Code session).

---

## Sources

### Primary (HIGH confidence)
- https://code.claude.com/docs/en/skills — Complete SKILL.md frontmatter schema, invocation control table, allowed-tools field, description truncation at 250 chars, personal skill path, $ARGUMENTS substitution
- https://code.claude.com/docs/en/permissions — MCP tool permission syntax: `mcp__<server>__<tool>` format confirmed
- `C:/Dev/Engram/server.py` line 1 — FastMCP server name: `mcp = FastMCP("engram")` → confirms `mcp__engram__` prefix

### Secondary (MEDIUM confidence)
- `C:/Dev/Engram/.planning/research/STACK.md` — Pre-existing research notes; all claims cross-verified against official docs above

### Tertiary (LOW confidence)
- None

---

## Metadata

**Confidence breakdown:**
- Frontmatter schema: HIGH — fetched directly from official docs at code.claude.com/docs/en/skills
- `disable-model-invocation` behavior: HIGH — documented in official invocation control table with exact semantics
- `allowed-tools` MCP syntax: HIGH — confirmed in permissions docs with explicit `mcp__puppeteer__puppeteer_navigate` example pattern
- Windows `~/.claude/skills/` path resolution: HIGH — `~/.claude/` confirmed to exist at `C:\Users\colek\.claude\`; `skills/` subdirectory does not exist yet (must be created)
- `store_memory` tool signature: HIGH — read directly from server.py
- Architecture patterns (infer-then-confirm): HIGH — standard UX pattern for side-effect skills; no conflicting guidance found

**Research date:** 2026-03-29
**Valid until:** 2026-06-29 (stable API; skill format unlikely to change within 90 days)
