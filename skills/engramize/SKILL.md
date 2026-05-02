---
name: engramize
description: Save an important decision, pattern, or finding as an Engram memory. Captures architectural insights, implementation decisions, gotchas, and lessons learned mid-session.
disable-model-invocation: true
allowed-tools: mcp__engram__store_memory
argument-hint: "[description of what to capture]"
---

When the user invokes /engramize, they want to save something important from the current session
to Engram. The user has described what to capture as: $ARGUMENTS

Follow these steps exactly. Do not skip or reorder them.


**Step 1 — Infer the memory fields**

Using $ARGUMENTS and the recent conversation context, infer the following:

key (required)
- Format: snake_case, all lowercase, no hyphens, no spaces
- Pattern: {project}_{domain}_{topic} or {project}_{topic}
- Derive project from the basename of the current working directory
  (e.g. cwd C:/Projects/ExampleApp -> project is "example_app"; cwd /home/user/engram -> project is "engram")
- Be specific and descriptive: "example_app_billing_webhook_race_fix" not "billing_fix"
- Examples: engram_store_memory_dedup_pattern, mytool_auth_jwt_refresh_decision

title (required)
- Format: "Project — Topic" or "Project — Topic Pattern"
- Use an em dash (—) as the separator, not a hyphen (-)
- Title case on both sides of the em dash
- Examples: "Engram — Store Memory Dedup Pattern", "ExampleApp - JWT Refresh Token Decision"

tags (required — exactly three tags as a comma-separated string)
  1. Project tag: lowercase basename of cwd (e.g. "engram", "example_app", "mytool")
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
