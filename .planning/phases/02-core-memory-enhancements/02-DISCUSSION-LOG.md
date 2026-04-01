# Phase 2: Core Memory Enhancements - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-01
**Phase:** 02-core-memory-enhancements
**Areas discussed:** Dedup behavior, Relationship model, last_accessed scope, WebUI integration

---

## Dedup Behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Warn and block | Return similar memory key/title/score and refuse to store. force=True overrides. | ✓ |
| Warn but store anyway | Return warning alongside stored result. No force needed. | |
| Interactive prompt | Return similar memory info and ask caller to confirm/cancel | |

**User's choice:** Warn and block
**Notes:** Caller must explicitly pass force=True to override.

| Option | Description | Selected |
|--------|-------------|----------|
| Content embedding only | Embed new content, query ChromaDB, compare cosine. Ignore key/title. | ✓ |
| Content + key similarity | Also check edit distance on keys | |
| Content + title | Also embed title and factor into score | |

**User's choice:** Content embedding only

| Option | Description | Selected |
|--------|-------------|----------|
| Strip before comparing | Strip audit trail before embedding for comparison | ✓ |
| Move audit to metadata | Stop appending audit log to content entirely | |
| Embed raw content only | Compare against pre-audit content from caller | |

**User's choice:** Strip before comparing

| Option | Description | Selected |
|--------|-------------|----------|
| Engram config file | config.json at C:/Dev/Engram/config.json | ✓ |
| Environment variable | ENGRAM_DEDUP_THRESHOLD env var | |
| Server CLI flag | --dedup-threshold flag | |

**User's choice:** Engram config file

---

## Relationship Model

| Option | Description | Selected |
|--------|-------------|----------|
| Query-time resolution | Only source JSON stores link. get_related_memories scans all. | ✓ |
| Write-time duplication | Update both A and B JSON on link creation | |
| Index-based | Separate index file for relationship pairs | |

**User's choice:** Query-time resolution

| Option | Description | Selected |
|--------|-------------|----------|
| Silently skip | Filter out deleted keys from results | ✓ |
| Warn on retrieval | Return dangling key with 'deleted' flag | |
| Cascade cleanup | delete_memory removes refs from all other memories | |

**User's choice:** Silently skip

| Option | Description | Selected |
|--------|-------------|----------|
| Cap at 10 | Max 10 related_to links per memory | ✓ |
| No limit | Unlimited links | |
| Cap at 5 | Tighter limit | |

**User's choice:** Cap at 10

---

## last_accessed Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, all results | Every search result gets last_accessed bumped | ✓ |
| Only explicit retrieves | Only retrieve_memory/retrieve_chunk update | |
| Only top result | Highest-scoring result only | |

**User's choice:** Yes, all results

| Option | Description | Selected |
|--------|-------------|----------|
| No | list_all_memories is directory listing, not access | ✓ |
| Yes | Any appearance counts as access | |

**User's choice:** No

| Option | Description | Selected |
|--------|-------------|----------|
| Fire-and-forget | Background update, don't block response | ✓ |
| Blocking | Write before returning | |
| Batch periodic | Queue and flush periodically | |

**User's choice:** Fire-and-forget

---

## WebUI Integration

| Option | Description | Selected |
|--------|-------------|----------|
| Inline links section | "Related Memories" section below content with clickable links | ✓ |
| Sidebar panel | Collapsible side panel | |
| Chips/tags style | Small clickable chips below title | |

**User's choice:** Inline links section

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, show warning | Display dedup warning with similar memory title/score | ✓ |
| No, server-only | Dedup for MCP only | |
| Preview before save | Similarity check on blur | |

**User's choice:** Yes, show warning

| Option | Description | Selected |
|--------|-------------|----------|
| In memory detail only | Show alongside created_at and updated_at | ✓ |
| In list view too | Show as sortable column | |
| Hidden | Programmatic use only | |

**User's choice:** In memory detail only

---

## Claude's Discretion

- Config file schema and loading mechanism
- search_memories exclude_self parameter for dedup queries
- Fire-and-forget implementation (asyncio.create_task vs background executor)
- WebUI JavaScript for related memories section

## Deferred Ideas

None — discussion stayed within phase scope.
