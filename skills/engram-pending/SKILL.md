---
name: engram-pending
description: Check for pending Engram memory drafts awaiting approval. Reviews drafts written by the session evaluator from previous sessions.
allowed-tools: Bash, mcp__engram__store_memory
---

At the start of every session, check for pending Engram memory drafts that need human approval.
These drafts were created by the session evaluator after previous sessions ended.

Follow these steps exactly. Do not skip or reorder them.


**Step 1 — Check for pending drafts**

Use the Bash tool to list JSON files in the pending_memories directory relative to the current working directory:

    ls .engram/pending_memories/*.json 2>/dev/null

If no files are found (command returns nothing or fails): print "No pending Engram memory drafts." and stop. Do not proceed further.

If files exist: count them and proceed to Step 2.


**Step 2 — Present each draft**

For each pending JSON file, read it with the Bash tool:

    cat .engram/pending_memories/{filename}

Parse the JSON content. Each file contains these fields:
- draft_key, draft_title, draft_content, draft_tags, confidence, reasoning
- session_id, evaluated_at, cwd, dedup_warning

Present the draft in this exact format:

    Pending Engram Memory Draft ({N} of {total}):

      Key:        {draft_key}
      Title:      {draft_title}
      Tags:       {draft_tags joined with ", "}
      Confidence: {confidence} ({reasoning})
      Evaluated:  {evaluated_at}

      Content preview:
      {draft_content — first 400 characters, add "..." if truncated}

      [Dedup warning: similar memory "{existing_key}" exists (score={score})]
      (only show the dedup warning line if dedup_warning is not null)

    Store this memory? (approve / skip / edit / delete)

Wait for the user's response before proceeding.


**Step 3 — Handle user response**

Based on the user's answer:

- **"approve"** (or "yes", "store", "y", or similar affirmative):
  Call mcp__engram__store_memory with:
    - key: draft_key
    - content: draft_content
    - title: draft_title
    - tags: draft_tags joined as comma-separated string (e.g. "engram,tooling,pattern")
    - force: true (bypass dedup gate — the evaluator already checked for duplicates)

  After successful store, delete the pending file:

      rm .engram/pending_memories/{filename}

  Report: "Stored: {draft_title}"

  If store_memory returns an error, report the error and ask: "Retry or skip?"

- **"skip"** (or "later", "next", or similar deferral):
  Leave the file in place. Report: "Skipped — draft will appear again next session."

- **"edit"** (or user provides corrections):
  Update the relevant fields based on the user's feedback. Re-show the updated draft in the same format as Step 2. Ask again: "Store this memory? (approve / skip / edit / delete)". Do NOT store until the user explicitly approves.

- **"delete"** (or "discard", "remove", or similar rejection):
  Delete the pending file without storing:

      rm .engram/pending_memories/{filename}

  Report: "Discarded: {draft_key}."


**Step 4 — Continue to next draft**

After handling one draft, present the next pending file. Repeat Steps 2-3 for each remaining draft.

If the user says "stop" or "done" at any point, stop presenting drafts. Report how many remain: "{N} pending drafts remaining — they will appear next session."


**Conventions — always enforced**

- Never call store_memory without explicit user approval. This is a hard rule.
- Always pass force=true when calling store_memory (dedup was already checked by the evaluator).
- Tags must be passed as a comma-separated string (e.g. "engram,tooling,pattern"), not as an array.
- If dedup_warning is present in the pending file, always show it so the user can make an informed decision.
- The pending_memories path is always relative to the current working directory: .engram/pending_memories/
- This skill works in any project directory, not just Engram — the evaluator writes pending files per-project.
