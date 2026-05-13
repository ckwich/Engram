# Post-1.0 Collaboration Product Handoff

Date: 2026-05-05
Updated: 2026-05-06
Status: Draft handoff for future product planning
Scope: Product boundary between public Engram core and a separate collaboration application built on top of Engram

## Purpose

Engram now has most of the seams a richer collaboration product would need: MCP memory, bounded retrieval, source intake, graph relationships, codebase mapping, workflow templates, retrieval receipts, operation receipts, and token telemetry.

The gap is that those seams are still described inside the Engram 1.0 operating-layer roadmap. There is no dedicated handoff that says what belongs in Engram, what belongs in a separate collaboration app, and which security and multi-user concerns must not be pulled into the public memory server by accident.

This document fills that gap. It is not an implementation plan. It is the boundary spec future work should start from.

Follow-on planning docs:

- `docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md`
- `docs/COLLABORATION_PRODUCT_PRD.md`

The older local-core Engram 1.0 docs have been archived under
`docs/archive/legacy-local-core-1-0/` and should not be used as the active
Engram roadmap.

## Product Boundary Decision

Engram remains a public, generic, local-first agent memory system.

The Notion-like collaboration layer should be a separate product that connects to Engram instead of being swallowed by this repository. "Engram Studio" can remain a working label in planning docs, but the important decision is architectural: Engram is the memory substrate; the collaboration app is the team workspace and product experience.

This keeps Engram useful for any MCP client, local assistant, coding agent, research agent, or single-user workflow without forcing the public repo to absorb team workspaces, rich page editing, comments, assignments, mentions, role-aware visibility, notifications, billing, or organization administration.

## Current Evidence

- `plan.md` marks v0.6 and v0.7 complete and keeps the key decisions local-first, JSON-first/vector-second, token-proportional retrieval, review-first source intake, provider neutrality, and graph backend migration readiness.
- `docs/superpowers/specs/2026-04-27-engram-1-agent-operating-layer-design.md` says the 1.0 scope should focus on the memory kernel, graph control, source intake, lifecycle governance, and workflow/craft primitives.
- That same design explicitly pushes team collaboration, rich page editing, comments, assignments, role-aware visibility, and advanced creative workflows post-1.0.
- `README.md` is public-facing and generic. It frames Engram as local-first semantic memory for agents, not as a private business workspace product.

## Engram Core Responsibilities

Engram owns durable memory and agent-facing retrieval.

Core responsibilities:

- MCP discovery through `memory_protocol()`.
- Three-tier retrieval: search snippets, retrieve chunks, then retrieve full memories only when needed.
- Bounded context packs with citations, receipts, budget accounting, and stale-result policy.
- JSON memory files as the source of truth, with ChromaDB as a rebuildable semantic index.
- Review-first source intake for transcripts, logs, handoffs, documents, code scans, and other source material.
- Draft memory preparation and explicit promotion into stored memories.
- Typed graph relationships as a retrieval and reasoning control plane.
- Project capsules, workflow templates, craft memory, verification recipes, and codebase mapping summaries.
- Usage and operation telemetry as local status records, not billing truth or proactive automation.
- WebUI surfaces for local memory review, health checks, source review, graph browsing, and receipt inspection.
- Import, export, audit, repair, backup, and rebuild readiness for local memory stores.

Core non-responsibilities:

- Multi-user workspace membership.
- Organization-level identity, roles, or permissions.
- Comments, assignments, mentions, notifications, or team presence.
- Rich collaborative page editing.
- Product workflow ownership for studios, agencies, companies, or teams.
- Private business-specific terminology, project names, or workflow assumptions in public docs.
- Treating ChromaDB, graph indexes, or WebUI state as authority.
- Automatic memory writes from agents or external apps.

## Collaboration App Responsibilities

The collaboration app owns the human team experience.

App responsibilities:

- Team workspaces, projects, channels, folders, pages, databases, and dashboards.
- Rich pages with blocks, embeds, backlinks, comments, review threads, and version history.
- Assignments, mentions, due dates, statuses, notifications, and activity feeds.
- Role-aware visibility, workspace membership, invite flows, teams, groups, and admin settings.
- Reviewable AI drafts for pages, decisions, issue summaries, source-ingestion proposals, and handoff notes.
- Business or team workflow UI such as planning boards, review queues, release rooms, playtest rooms, or client/customer spaces.
- Game-development knowledge spaces when relevant: lore, mechanics, assets, playtest findings, build notes, design decisions, and production checklists.
- Connectors to systems of record such as Git, issue trackers, chat, documents, calendar tools, design tools, and file stores.
- Tenant-aware audit trails, moderation, retention controls, export policy, and compliance posture.
- Product analytics and billing if the collaboration app becomes commercial.

The app may use Engram to remember distilled facts, decisions, relationships, retrieval evidence, workflow/craft guidance, and reviewable source drafts. It should not ask Engram to become the canonical store for every page block, comment, assignment, notification, or permission rule.

## Boundary Architecture

The clean boundary is:

```text
Collaboration app
  owns users, workspaces, pages, comments, assignments, permissions, notifications, and product workflows
  calls Engram through MCP/API/library adapters for memory, source drafts, retrieval, graph evidence, receipts, and telemetry

Engram core
  owns local durable memory, retrieval, graph relationships, source-intake drafts, workflow/craft memory, codebase mapping context, and audit/repair gates
  never directly owns team collaboration state
```

The collaboration app should use public Engram contracts instead of reaching into `data/memories`, ChromaDB, graph JSON, or internal manager files directly.

Acceptable integration paths:

- Local single-user app calls a local Engram MCP server or local HTTP/API bridge.
- Desktop app embeds or launches Engram as a local memory service.
- Team app talks to a future Engram service adapter that preserves the same memory contracts.
- Server-side workflow calls `prepare_source_memory()` and shows drafts for review before promotion.
- App-side search asks for `context_pack()` or `search_memories()` with explicit project/domain/tag/status filters.
- App-side source review promotes selected memory drafts only after a human or trusted workflow action.

Unacceptable integration paths:

- Writing directly to Engram JSON files from the collaboration app.
- Treating ChromaDB results as durable truth without JSON-backed memory records.
- Letting page edits, comments, notifications, or assignment churn become raw memory spam.
- Hiding permission checks inside ad hoc memory tags and calling that security.
- Adding private customer or project names to public Engram repo docs.

## API and MCP Contract

The collaboration app should treat Engram as a bounded memory service with explicit calls.

Discovery:

- Start with `memory_protocol()` to learn stable tools, beta tools, retrieval ladder, aliases, cost classes, and warnings.

Read path:

- Use `context_pack(query, project, domain, tags, retrieval_mode, budget_chars, use_graph)` for compact working context.
- Use `search_memories()` when the app needs ranked snippets and user-selectable results.
- Use `retrieve_chunk()` after a result identifies a specific key and chunk.
- Use full-memory retrieval only for deliberate inspect/edit flows.

Write path:

- Use `prepare_memory()` before durable memory writes when metadata, validation, or duplicate checks matter.
- Use `store_memory()` or `write_memory()` only for explicit promotions.
- Use source-intake draft flows for large or messy material instead of storing raw transcripts, chats, meeting notes, or scan dumps.

Graph path:

- Use graph tools for IDs, relationship evidence, impact scans, and contradiction/support chains.
- Do not use graph traversal as permission to load neighbor memory bodies automatically.
- Let final content selection flow through context budgets and citations.

Receipts and telemetry:

- Preserve context-pack receipts, operation receipts, and usage estimates in the app UI when they explain why an AI draft relied on specific memory.
- Treat Engram usage telemetry as local estimates unless the collaboration app separately records provider billing data.

Compatibility rule:

- The collaboration app should depend on stable Engram MCP/API contracts, not Python internals.

## Security, Auth, and Multi-User Implications

Engram's current security model is local-first and loopback-first. The WebUI has exposed-host protections, access tokens, write tokens, host checks, origin checks, request-size limits, throttled login failures, session binding, and browser security headers. Those protections are not a complete team collaboration auth system.

The collaboration app must own:

- Identity providers, login sessions, workspace membership, teams, groups, and invite flows.
- Role-based access control and object-level authorization for pages, comments, assignments, source drafts, and AI outputs.
- Tenant isolation, audit logs, retention policy, exports, admin controls, and incident response posture.
- Secret handling for connectors and model providers.
- Permission-aware search and retrieval before any AI answer or page suggestion is shown to a user.

Engram can support visibility by storing and filtering metadata such as `project`, `domain`, `tags`, `status`, `source_kind`, `source_uri`, `trust`, `created_by`, `approved_by`, and validation timestamps. It should not be treated as the sole authorization engine for a multi-user app unless a future Engram service explicitly adds tenant isolation and ACL semantics with tests, migrations, and threat modeling.

For early collaboration prototypes, the safe pattern is:

```text
App authenticates user
-> app determines visible workspace/project/source scopes
-> app sends only allowed filters and source material to Engram
-> Engram returns bounded memory/context with citations
-> app rechecks output visibility before display or draft promotion
```

## Before 1.0

Engram 1.0 should not implement the collaboration app.

Before 1.0, Engram should focus on being a strong substrate:

- Keep JSON-first, Chroma-second storage behavior stable and tested.
- Keep chunk IDs and MCP tool contracts stable.
- Keep source intake review-first and explicit-promotion only.
- Harden graph edge schema, graph audits, and graph traversal receipts.
- Harden lifecycle, provenance, freshness, stale memory handling, and trust metadata.
- Keep context packs budgeted, cited, and receipt-backed.
- Keep codebase mapping provider-neutral: Engram prepares context, the connected agent synthesizes.
- Keep WebUI local memory review focused on memory, source drafts, graph relationships, health, and receipts.
- Keep public README and repo docs generic.
- Add or maintain migration notes for schema-affecting changes.
- Validate core gates: `server.py --help`, memory-manager import, self-test store/search/retrieve/delete cycle, production stdout audit, and agent retrieval eval when agent-facing behavior changes.

## Post-1.0

The separate collaboration product can begin once Engram has a stable 1.0 memory contract.

Recommended first product slices:

1. Read-only memory panel: show context-pack results, citations, freshness, and why a draft is grounded.
2. Reviewable source intake: import a transcript, meeting note, bug report, design doc, or repo scan into draft memory proposals, then let a human approve selected records.
3. Workspace-aware project capsule: show a team-facing project summary backed by Engram memories and app-owned workspace metadata.
4. AI draft review queue: generate page, decision, handoff, issue, or playtest-summary drafts with citations and explicit promotion controls.
5. Comments and assignments around drafts: keep collaboration state in the app while storing only approved decisions, summaries, and memory-worthy outcomes in Engram.
6. Game-development knowledge space: model design decisions, lore, mechanics, assets, playtests, build notes, and production checklists as app-owned pages with Engram-backed memory and graph evidence.
7. Team security foundation: identity, RBAC, workspace membership, audit log, export policy, and connector secret handling.

The collaboration product should earn each Engram write. Most team activity is not durable memory. Durable memory should be distilled, reviewed, cited, and useful to future agents or teammates.

## Handoff for Future Planning

When starting the collaboration product, begin outside this repository.

Recommended starting packet:

- Create a new project/repo for the collaboration app.
- Copy this boundary document into that project's planning docs or link back to this public spec.
- Use `docs/COLLABORATION_PRODUCT_PRD.md` as the starting PRD and update it in the new product repo.
- Wait for Engram Track 1 contract freeze before treating the Engram adapter surface as stable.
- Define the first user workflow as a thin vertical slice over Engram's existing contracts.
- Choose the auth and tenant model before building comments, assignments, or shared pages.
- Treat the first Engram integration as an adapter with tests, not as direct filesystem access.
- Keep private/customer/project-specific terms in the collaboration app's private planning space, not in the public Engram repo.

## Open Product Questions

These questions belong to the future collaboration product, not Engram 1.0:

- Is the first target a local desktop team tool, a hosted web app, or a hybrid local-first app?
- Will each workspace have its own Engram store, a shared service-backed store, or per-user local stores with sync?
- Which collaboration object is first-class: page, project, decision, source draft, issue, playtest, or review queue item?
- Which identity provider and permission model are required before any team pilot?
- Which AI draft workflows are valuable enough to justify durable memory writes?
- Which external systems of record must stay authoritative instead of being mirrored into Engram?

## Success Criteria

This boundary is successful when future work can answer these questions without reopening Engram 1.0 scope:

- Does this feature belong in public Engram core or the separate collaboration app?
- Which stable Engram MCP/API contract does the app call?
- Is this data durable memory, source-draft material, graph evidence, app collaboration state, or external system-of-record data?
- Who authorizes the user to see this result?
- Which writes are explicit, reviewable, and worth preserving for future agents?
- Can Engram remain useful as a generic local-first memory system if the collaboration app never ships?
