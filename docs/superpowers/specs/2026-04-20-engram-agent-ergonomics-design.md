# Engram Agent Ergonomics Upgrade Design

Date: 2026-04-20
Status: Draft for review
Scope: Design and overnight execution strategy for 8 agent-centered Engram improvements

## Context

Engram is already a live dependency for multiple projects. The goal of this work is not to reinvent the product from a human UX perspective, but to make the MCP server materially easier and safer for AI agents to use well.

The current tool surface is readable but human-formatted. Search and retrieval rely on string-shaped responses, chunk metadata is minimal, and agent workflows often require multiple round-trips and judgment calls that could be encoded in the tool surface itself.

This session will target eight agent-centered improvements:

1. Structured tool outputs
2. Scoped search filters
3. Richer chunk metadata
4. Batch retrieval
5. Safer write helpers
6. Lifecycle semantics (`canonical`, `superseded`, etc.)
7. Search explanations / confidence signals
8. Session working set / pinning

## Goals

- Make Engram faster and more reliable for agent retrieval and writing workflows.
- Reduce ambiguity in MCP responses so agents do not need to parse prose to recover machine-usable fields.
- Preserve existing flat-file memories as the source of truth.
- Preserve ChromaDB as a rebuildable index, not the authority.
- Deliver the work in one overnight session using additive-first changes and repeated health checks.

## Non-Goals

- Replacing `all-MiniLM-L6-v2` tonight
- Rewriting the storage model
- Removing current MCP tools during the overnight session
- Performing a destructive migration of all existing memories
- Introducing behavior that requires all dependent projects to update immediately

## Critical Invariants

These rules are non-negotiable during execution:

- Store flow remains JSON-first, then Chroma indexing.
- Delete flow remains Chroma-first, then JSON deletion, to prevent ghost search results.
- Existing memories without new metadata must remain readable and searchable.
- Any new fields added to JSON or Chroma metadata must be additive and optional.
- If Chroma drift occurs, `rebuild_index()` must remain sufficient to recover from JSON.
- Existing MCP tools must still work at the end of the overnight session.

## Approaches Considered

### Approach A — Replace current MCP tools in place

Change the existing tools to return structured payloads and new semantics immediately.

Pros:
- Cleanest final API
- No duplicated tool surface

Cons:
- Highest compatibility risk
- Existing dependent agents may fail or behave unexpectedly
- Harder to isolate regressions during an overnight unattended run

Recommendation: Reject for tonight.

### Approach B — Additive v2 tool surface plus internal upgrades

Keep current tools stable while adding agent-optimized structured tools, richer metadata, scoped search, and helper APIs in parallel.

Pros:
- Safest overnight path
- Easy rollback at the tool-contract level
- Lets us verify new behavior without breaking current consumers
- Supports gradual migration later

Cons:
- Temporary duplication in the tool surface
- Some internal logic will need to support both formatted and structured responses

Recommendation: Preferred.

### Approach C — Separate agent-only sidecar service

Create a distinct agent-oriented interface while leaving the original server untouched.

Pros:
- Maximum isolation

Cons:
- More architecture than needed
- Splits maintenance effort
- Not realistic for one overnight session

Recommendation: Reject.

## Recommended Design

Use Approach B. Build an additive, agent-first layer over the current Engram core, then deepen the storage/index metadata to support better filtering, better ranking interpretation, and safer write flows.

The design is intentionally staged:

1. Expand verification first
2. Add structured tool contracts beside the current ones
3. Introduce additive metadata and scoped retrieval
4. Add write helpers and lifecycle semantics
5. Add session pinning only after retrieval/storage safety is proven

## Tool Surface Design

### Existing Tools

The current tools remain in place and continue returning human-formatted strings:

- `search_memories`
- `list_all_memories`
- `retrieve_chunk`
- `retrieve_memory`
- `store_memory`
- `get_related_memories`
- `get_stale_memories`
- `delete_memory`

### New Structured Tools

Add a parallel structured tool family:

- `search_memories_v2`
- `list_memories_v2`
- `retrieve_chunk_v2`
- `retrieve_chunks_v2`
- `retrieve_memory_v2`
- `get_related_memories_v2`
- `get_stale_memories_v2`

Each returns structured data rather than formatted prose. Core fields should be stable and explicit.

#### `search_memories_v2`

Inputs:
- `query`
- `limit`
- optional `project`
- optional `domain`
- optional `tags`
- optional `updated_after`
- optional `include_stale`
- optional `canonical_only`
- optional `pinned_first`

Output shape:

```json
{
  "query": "scheduler conflict",
  "count": 3,
  "results": [
    {
      "key": "sylvara_scheduler_architecture",
      "chunk_id": 2,
      "title": "Sylvara Scheduler Architecture",
      "score": 0.91,
      "snippet": "...",
      "tags": ["sylvara", "scheduler", "architecture"],
      "project": "sylvara",
      "domain": "scheduler",
      "section_title": "Conflict resolution",
      "heading_path": ["Architecture", "Conflict resolution"],
      "source_kind": "manual",
      "stale_type": "none",
      "canonical": true,
      "status": "active",
      "explanation": {
        "same_project": true,
        "matched_tags": ["scheduler"],
        "is_pinned": false,
        "excluded_by_filters": []
      }
    }
  ]
}
```

#### `retrieve_chunks_v2`

Accepts an array of `{key, chunk_id}` inputs and returns a structured list. This removes repetitive round-trips after search.

#### `retrieve_memory_v2`

Returns:
- metadata
- lifecycle fields
- related keys
- chunk count
- content

without formatted decoration.

## Safer Write Tool Design

Do not overload `store_memory` with planning or validation responsibilities. Add helpers:

- `check_duplicate`
- `suggest_memory_metadata`
- `validate_memory`
- `update_memory_metadata`

### `check_duplicate`

Purpose:
- Inspect whether proposed content is near an existing memory before a write attempt

Returns:
- duplicate candidate list
- score
- whether self-update exemption would apply

### `suggest_memory_metadata`

Purpose:
- Suggest `key`, `title`, `tags`, optional `project`, optional `domain`

This reduces agent guesswork and naming inconsistency.

### `validate_memory`

Purpose:
- Validate size, relationship count, lifecycle fields, metadata completeness, and expected write shape without mutating JSON or Chroma.

### `update_memory_metadata`

Purpose:
- Adjust lifecycle or metadata fields without requiring a full content rewrite when the memory body is unchanged.

## Metadata Design

### JSON Memory Additions

Existing memory JSON stays valid. Add optional fields only:

- `project`
- `domain`
- `memory_type`
- `source_kind`
- `status`
- `canonical`
- `confidence`
- `supersedes`
- `superseded_by`
- `heading_index`

Default behavior for older memories:

- `status = "active"`
- `canonical = false`
- absent fields are treated as unknown, not invalid

### Chroma Metadata Additions

Each chunk may include:

- `project`
- `domain`
- `memory_type`
- `source_kind`
- `section_title`
- `heading_path`
- `status`
- `canonical`
- `stale_type`

This metadata must remain optional so old indexes can still be read. A rebuild can enrich the index progressively from JSON.

## Chunking Enhancements

Current chunking returns only `chunk_id` and `text`. Extend the chunking pipeline internally to also derive:

- `section_title`
- `heading_path`
- `chunk_kind`

The chunk text itself should remain unchanged unless required by correctness. The overnight session should avoid a broad chunking strategy rewrite.

## Lifecycle Semantics

Introduce explicit memory lifecycle states:

- `active`
- `draft`
- `historical`
- `superseded`
- `archived`

And orthogonal flags:

- `canonical: true|false`
- `confidence: low|medium|high` or numeric equivalent

Rules:

- `canonical=true` means preferred retrieval candidate when multiple memories overlap.
- `superseded_by` must point to a valid key if present.
- A superseded memory remains retrievable but is clearly marked.
- Search filters may include or exclude superseded memories.

## Search Explanations

Agent trust improves when results explain why they ranked. Explanations should be lightweight and additive:

- score
- filter matches
- lifecycle flags
- stale flags
- whether the result came from a pinned working set

This is not a full reranker tonight. It is an explanation layer over current retrieval and filters.

## Session Working Set / Pinning

Pinning should not mutate permanent memory JSON by default.

Recommended implementation:

- store session working-set state outside the core memory files
- provide tools such as:
  - `pin_memory`
  - `unpin_memory`
  - `list_pins`
  - `clear_pins`

Pins are a retrieval aid, not a content mutation.

Open design choice:
- If MCP session identity is not reliably available, use a lightweight local session store scoped to the current process/thread context.

Preferred overnight behavior:
- safe local/session persistence
- zero effect on permanent memory integrity

## Error Handling

- Any validation helper failure returns structured error objects, not plain text strings.
- Storage helpers never write partial JSON.
- Metadata-only updates preserve existing content and audit expectations.
- Missing optional metadata never crashes search or retrieval.
- Search filters on absent metadata degrade gracefully by excluding only when explicitly requested.

## Verification Strategy

Because current pytest coverage is thin, the overnight session must start by strengthening tests before changing tool contracts.

### Baseline Checks

- `python server.py --help`
- `python server.py --health`
- `python server.py --self-test`
- `python -c "from core.memory_manager import memory_manager; print('ok')"`
- `pytest`
- export all memories
- record memory count and chunk count

### New Tests Required

- structured tool output schema tests
- backward compatibility tests for old MCP tools
- JSON-first write invariant tests
- Chroma-first delete invariant tests
- scoped search filter tests
- richer chunk metadata fallback tests
- batch retrieval tests
- lifecycle metadata tests
- pinning isolation tests
- export/import compatibility tests

### Health Passes

Run a health pass after every wave:

1. test suite
2. `server.py --self-test`
3. `server.py --health`
4. memory count and chunk count comparison
5. sample retrieval checks against real memories

If a wave fails, stop and repair before continuing.

## Overnight Execution Phases

### Phase 0 — Safety setup

- export memories
- snapshot `data/memories/`
- snapshot `data/chroma/`
- capture baseline health

### Phase 1 — Verification harness

- add tests and fixtures
- extend self-test or add adjacent integration coverage

### Phase 2 — Structured tool family

- add v2 tools without removing current ones

### Phase 3 — Scoped search and metadata enrichment

- add additive filters and metadata
- rebuild index only if needed, with JSON backup already in place

### Phase 4 — Batch retrieval and explanations

- add multi-chunk retrieval and explanation fields

### Phase 5 — Safer write helpers

- add duplicate check, metadata suggestion, validation, metadata update paths

### Phase 6 — Lifecycle semantics

- add memory lifecycle fields and retrieval filters

### Phase 7 — Session pins

- add local working-set pinning that does not touch memory JSON

### Phase 8 — Final verification and docs

- rerun all health passes
- update README and tool docstrings
- leave current tools intact

## Risks and Mitigations

### Risk: breaking live consumers

Mitigation:
- additive v2 tools
- old tools preserved overnight

### Risk: JSON / Chroma drift

Mitigation:
- preserve existing write/delete ordering
- export plus snapshots before changes
- rebuild path remains available

### Risk: weak test coverage hides regressions

Mitigation:
- expand verification first, before behavior changes

### Risk: metadata migration becomes too large

Mitigation:
- additive optional fields only
- no forced rewrite of all memories tonight

### Risk: pinning leaks into permanent storage

Mitigation:
- separate session-state storage from memory JSON

## Success Criteria

By the end of the overnight session:

- all eight improvements exist in usable form
- existing MCP tools still work
- new structured tools are available for agent-first use
- flat-file memories remain authoritative and intact
- Chroma index remains rebuildable from JSON
- baseline health checks and expanded tests pass
- real sampled retrievals behave at least as well as baseline

## Recommendation

Proceed with the additive-first overnight plan. It is the only option that realistically delivers all eight agent-centered improvements in one session while protecting live project dependencies and preserving the JSON/Chroma safety model.
