---
phase: 01-engramize-skill
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - C:/Users/colek/.claude/skills/engramize/SKILL.md
autonomous: false
requirements:
  - SKIL-01
  - SKIL-02
  - SKIL-03
  - SKIL-04
  - SKIL-05
  - SKIL-06
must_haves:
  truths:
    - "User types /engramize [description] in any session and Claude shows a memory draft before storing"
    - "Draft shows key (snake_case, lowercase), title (Project — Topic format), tags, and content"
    - "Skill enforces type tag from fixed vocabulary: decision, pattern, constraint, gotcha, architecture"
    - "Skill warns and asks to trim if content draft exceeds 3000 characters"
    - "store_memory is only called after user confirms — never silently"
    - "Skill file exists at ~/.claude/skills/engramize/SKILL.md and /engramize appears in the slash-command menu in all sessions"
  artifacts:
    - path: "C:/Users/colek/.claude/skills/engramize/SKILL.md"
      provides: "Global /engramize slash command with infer-then-confirm memory creation workflow"
      contains: "disable-model-invocation: true"
  key_links:
    - from: "SKILL.md allowed-tools"
      to: "mcp__engram__store_memory"
      via: "FastMCP server name 'engram' in server.py"
      pattern: "mcp__engram__store_memory"
    - from: "SKILL.md body"
      to: "user confirmation gate"
      via: "Show draft, ask yes/edit/cancel before any tool call"
      pattern: "confirmation"
---

<objective>
Create the global /engramize Claude Code skill that enables natural mid-session memory creation.

Purpose: Users working in any project can type "/engramize [description]" and Claude will draft a properly formatted Engram memory (key, title, tags, content), show it for approval, then store it without leaving their workflow.

Output: A single SKILL.md file at ~/.claude/skills/engramize/SKILL.md. No Python code, no server changes, no dependencies.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@C:/Dev/Engram/.planning/ROADMAP.md
@C:/Dev/Engram/.planning/REQUIREMENTS.md
@C:/Dev/Engram/.planning/phases/01-engramize-skill/CONTEXT.md
@C:/Dev/Engram/.planning/phases/01-engramize-skill/01-RESEARCH.md

<interfaces>
<!-- store_memory tool signature — extracted from C:/Dev/Engram/server.py lines 143-148 -->
<!-- Executor MUST use these exact parameter names when writing the skill body. -->

store_memory(
    key: str,        # snake_case, e.g. "sylvara_webhook_race_fix"
    content: str,    # markdown, server hard limit 15000 chars; skill enforces 3000 soft limit
    title: str = "", # e.g. "Sylvara — Webhook Race Fix"
    tags: str = "",  # comma-separated: "sylvara,backend,gotcha"
) -> str

MCP tool reference (case-sensitive): mcp__engram__store_memory
Server name confirmed: mcp = FastMCP("engram") at server.py line 1
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Create skill directory and write SKILL.md</name>
  <files>C:/Users/colek/.claude/skills/engramize/SKILL.md</files>
  <action>
Create the directory C:/Users/colek/.claude/skills/engramize/ then write SKILL.md.

The ~/.claude/skills/ directory does not exist yet and must be created. Use mkdir -p or the Write tool (which creates intermediate directories automatically).

CONSTRAINTS (all locked in CONTEXT.md — do not deviate):
- disable-model-invocation: true in frontmatter (prevents Claude auto-firing a side-effect skill)
- allowed-tools: mcp__engram__store_memory (lowercase 'engram' — matches FastMCP("engram") in server.py)
- Description under 250 chars, front-loaded with trigger phrase
- Infer-then-confirm workflow: NEVER call store_memory without showing a draft and receiving approval
- Key format: snake_case, lowercase only, no hyphens (SKIL-02)
- Title format: "Project — Topic" with em dash not hyphen (SKIL-05)
- Tags: exactly three — project (cwd basename), domain (inferred), type (fixed vocabulary) (SKIL-03)
- Type vocabulary: decision, pattern, constraint, gotcha, architecture — no other values
- Content limit: 3000 characters enforced by skill (SKIL-04)
- Structured content headers: Context, Decision/Pattern/Finding, Watch Out For

Write the following content to C:/Users/colek/.claude/skills/engramize/SKILL.md.
The file uses YAML frontmatter (between the triple-dash delimiters) followed by natural language instructions.
The step separators inside the body use blank lines and bold headings — NOT triple dashes.

SKILL.md content to write:

[FRONTMATTER START]
name: engramize
description: Save an important decision, pattern, or finding as an Engram memory. Captures architectural insights, implementation decisions, gotchas, and lessons learned mid-session.
disable-model-invocation: true
allowed-tools: mcp__engram__store_memory
argument-hint: "[description of what to capture]"
[FRONTMATTER END]

When the user invokes /engramize, they want to save something important from the current session
to Engram. The user has described what to capture as: $ARGUMENTS

Follow these steps exactly. Do not skip or reorder them.


**Step 1 — Infer the memory fields**

Using $ARGUMENTS and the recent conversation context, infer the following:

key (required)
- Format: snake_case, all lowercase, no hyphens, no spaces
- Pattern: {project}_{domain}_{topic} or {project}_{topic}
- Derive project from the basename of the current working directory
  (e.g. cwd C:/Dev/Sylvara -> project is "sylvara"; cwd /home/user/engram -> project is "engram")
- Be specific and descriptive: "sylvara_billing_webhook_race_fix" not "billing_fix"
- Examples: engram_store_memory_dedup_pattern, mytool_auth_jwt_refresh_decision

title (required)
- Format: "Project — Topic" or "Project — Topic Pattern"
- Use an em dash (—) as the separator, not a hyphen (-)
- Title case on both sides of the em dash
- Examples: "Engram — Store Memory Dedup Pattern", "Sylvara — JWT Refresh Token Decision"

tags (required — exactly three tags as a comma-separated string)
  1. Project tag: lowercase basename of cwd (e.g. "engram", "sylvara", "mytool")
  2. Domain tag: inferred from context — choose one of:
     backend, frontend, db, infra, api, auth, testing, tooling, devops, cli
  3. Type tag: choose exactly one from this fixed vocabulary:
     - decision — an architectural or implementation choice made
     - pattern — a reusable approach or technique discovered
     - constraint — a limitation, rule, or boundary to respect
     - gotcha — a trap, bug, or non-obvious behavior to avoid
     - architecture — a structural or systemic design insight

content (required)
- Write structured markdown using these section headers (include the headers that apply; omit the rest):

    ## Context
    Why this came up — what problem or situation prompted this

    ## Decision / Pattern / Finding
    The actual insight, decision, or pattern — the "what" and "why"

    ## Watch Out For
    Edge cases, failure modes, or traps to avoid

- Capture WHY, not just what. Explain the reasoning, not just the outcome.
- Write for a future engineer reading this cold, with no session context.
- Do NOT include dates, session metadata, or "as of today" phrases.
- Target 200-800 characters for focused memories. Maximum: 3000 characters total.


**Step 2 — Check content length**

Count the total characters in the content field (all text across all sections).

If the content exceeds 3000 characters:
- Tell the user: "The content draft is [N] characters, which exceeds the 3000-character limit."
- Ask: "Which section should I trim, or should I split this into two memories?"
- Wait for their answer before proceeding. Do not store an over-limit memory.


**Step 3 — Show the full draft to the user**

Present the draft in this format:

    Key:     {key}
    Title:   {title}
    Tags:    {tags}
    Chars:   {character count of content}

    Content preview:
    {full content}

Then ask: Store this memory? (yes / edit / cancel)

- "yes" or similar confirmation: proceed to Step 4.
- "edit" or corrections provided: update the relevant fields and re-show the draft. Ask again.
- "cancel" or declined: confirm cancellation and stop. Do not call store_memory.


**Step 4 — Store the memory**

Only after explicit user confirmation, call mcp__engram__store_memory with:
- key: the confirmed key value
- content: the confirmed content value
- title: the confirmed title value
- tags: the confirmed tags as a comma-separated string (e.g. "engram,backend,pattern")

After the tool returns, report the result to the user.


**Conventions — hard rules**

These apply at all times. If you find yourself about to violate one, stop and correct it before proceeding.

- Key must be snake_case and all lowercase. Hyphens and capital letters are not allowed.
- Title must use an em dash (—) not a hyphen (-). "Project — Topic" not "Project - Topic".
- Tags must be exactly three: project, domain, type. No more, no fewer.
- Type tag must be one of: decision, pattern, constraint, gotcha, architecture. No other values.
- Content must be under 3000 characters total. Refuse to store if over the limit.
- Never call store_memory without first showing the draft and receiving explicit approval.

[END OF SKILL.md CONTENT]

When writing the actual file, replace [FRONTMATTER START] with "---" and [FRONTMATTER END] with "---"
(these markers were used above only to avoid confusing this plan's own frontmatter parser).
  </action>
  <verify>
    <automated>ls "C:/Users/colek/.claude/skills/engramize/SKILL.md" && grep -c "disable-model-invocation: true" "C:/Users/colek/.claude/skills/engramize/SKILL.md"</automated>
  </verify>
  <done>
File exists at C:/Users/colek/.claude/skills/engramize/SKILL.md. Running the automated verify command returns "1" (the grep count). File contains all required elements: disable-model-invocation: true, allowed-tools: mcp__engram__store_memory, snake_case key rule, em dash title rule, three-tag requirement, type vocabulary list, 3000-character limit, and the no-silent-store rule.
  </done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 2: Verify /engramize skill works end-to-end</name>
  <action>N/A — this is a human verification checkpoint. The automated work is complete. Human confirms behavior in a live Claude Code session.</action>
  <files>C:/Users/colek/.claude/skills/engramize/SKILL.md</files>
  <verify>
    <automated>MISSING — skill behavior can only be verified interactively in a Claude Code session</automated>
  </verify>
  <done>Human has confirmed all six SKIL requirements pass in a live session test.</done>
  <what-built>
The /engramize skill file at ~/.claude/skills/engramize/SKILL.md. This creates the global /engramize slash command in all Claude Code sessions.
  </what-built>
  <how-to-verify>
1. Start a new Claude Code session (skills load at session startup, not hot-reloaded mid-session).
2. Type "/" in the chat input and verify "/engramize" appears in the autocomplete menu with its description.
3. Run this test invocation: /engramize decision to use PostgreSQL advisory locks for distributed task queue deduplication instead of Redis
4. Verify Claude shows a draft with ALL of the following correct:
   - key: snake_case, all lowercase, no hyphens (e.g. engram_task_queue_pg_advisory_lock_decision)
   - title: uses em dash "Engram — ..." not hyphen "Engram - ..."
   - tags: exactly three — project (engram), domain (e.g. backend or db), type (must be one of: decision/pattern/constraint/gotcha/architecture)
   - content: structured markdown with ## Context and at least one other header, under 3000 chars
5. Verify Claude asks for confirmation ("Store this memory? (yes / edit / cancel)") BEFORE calling any tool.
6. Reply "yes" and confirm that mcp__engram__store_memory is called with key, title, tags, and content.
7. Check the memory appears in the Engram WebUI at http://localhost:5001.
8. Open a second session from a different working directory (e.g. cd C:/Dev) and verify /engramize still appears in the "/" menu (confirms SKIL-06 global availability).
  </how-to-verify>
  <resume-signal>Type "approved" if all checks pass, or describe any issues (wrong key format, missing em dash, wrong tag count, auto-stored without confirmation, not showing in menu, etc.)</resume-signal>
</task>

</tasks>

<verification>
The phase is complete when:
- SKILL.md exists at C:/Users/colek/.claude/skills/engramize/SKILL.md
- /engramize appears in the slash-command menu in a fresh Claude Code session
- Invoking /engramize produces a draft with correct key, title, tags, and content format
- Claude does not call store_memory before user confirms
- Content over 3000 chars triggers a trim prompt, not a silent store
- A test memory stored via the skill appears correctly in the Engram WebUI
</verification>

<success_criteria>
1. (SKIL-01) "/engramize [description]" mid-session creates a properly formatted memory — confirmed by live test in Task 2 checkpoint.
2. (SKIL-02) Key uses snake_case, all lowercase, no hyphens — enforced by skill instructions, verified in checkpoint step 4.
3. (SKIL-03) Tags always include project (from cwd), domain, and exactly one type from the fixed vocabulary — enforced by skill, verified in checkpoint step 4.
4. (SKIL-04) Content draft over 3000 characters triggers a trim prompt before store — enforced by Step 2 in skill body.
5. (SKIL-05) Title uses "Project — Topic" format with em dash — enforced by skill, verified in checkpoint step 4.
6. (SKIL-06) Skill file exists at ~/.claude/skills/engramize/SKILL.md and /engramize is available in all sessions regardless of working directory — verified in checkpoint step 8.
</success_criteria>

<output>
After completion, create .planning/phases/01-engramize-skill/01-engramize-skill-01-SUMMARY.md with:
- What was built (SKILL.md path, frontmatter fields used)
- Key decisions honored (disable-model-invocation, infer-then-confirm workflow, 3000-char limit, tag vocabulary)
- Verification result from the human checkpoint
- Any issues encountered and how they were resolved
- Requirements satisfied: SKIL-01, SKIL-02, SKIL-03, SKIL-04, SKIL-05, SKIL-06
</output>
