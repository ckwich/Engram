# Collaboration Product PRD

Date: 2026-05-05
Status: Draft PRD for separate product planning
Scope: A team collaboration application built on top of Engram as a memory substrate

## Purpose

The collaboration product is a separate app that helps teams turn work artifacts into reviewable, cited, durable operating memory. It should use Engram for memory, retrieval, source drafts, graph evidence, receipts, and token telemetry, while owning users, workspaces, pages, comments, assignments, mentions, permissions, and product workflow UI.

This PRD starts from the boundary decision in `docs/POST_1_COLLABORATION_PRODUCT_HANDOFF.md`: Engram stays public, generic, and local-first. The collaboration app may connect to Engram, but it should not be implemented inside the Engram repo.

## Shared Roadmap

The shared program has two products and one integration contract:

1. Engram 1.0: stabilize the public local-first memory substrate.
2. Collaboration product: build a separate team workspace and review experience on top of Engram.
3. Engram adapter contract: define how the app calls Engram, preserves receipts, enforces visibility, and promotes reviewable drafts.

Recommended sequence:

1. Finish and publish the current Engram planning branch.
2. Bring Engram to 1.0 with contract, storage, source-intake, graph, WebUI, docs, and release gates.
3. Start the collaboration product in a separate repo/project with its own auth, workspace, and UI architecture.
4. Build the first collaboration vertical slice as a thin app over stable Engram calls: source intake -> cited draft -> human review -> explicit memory promotion.
5. Add richer pages, comments, assignments, mentions, and game-development knowledge spaces only after permission-aware retrieval and draft review are proven.

Coordination rule: Engram changes should be judged by whether they make the generic memory substrate stronger. Collaboration-app changes should be judged by whether they improve team workflow without corrupting Engram's storage or tool contracts.

## Product Thesis

Teams do not need another place where AI sprays text. They need a reviewable workspace where AI drafts are grounded in known context, every durable memory write is explicit, and future agents can understand why a decision exists.

The collaboration product should make the Engram loop visible:

```text
source material
-> draft extraction
-> cited proposal
-> team review
-> approved page/decision/task
-> explicit Engram memory promotion when durable
-> future retrieval with receipts
```

## Target Users

Primary users:

- Small software, game, or product teams that work with AI agents.
- Leads who need continuity across planning, implementation, QA, handoffs, and reviews.
- Contributors who need to understand current decisions without reading every chat, transcript, or repo scan.

Secondary users:

- Solo builders who want a structured workspace over a local Engram memory store.
- Consultants or agencies that need project handoff, client-safe summaries, and reviewable AI output.

## MVP Problem

The first problem is not rich page editing. The first problem is trustworthy conversion from messy source material into reviewed project knowledge.

MVP should answer:

- What source did this draft come from?
- Which Engram memories or chunks informed it?
- Who is allowed to see it?
- Who approved it?
- What became durable memory, and what remained app-only collaboration state?
- Can a future agent retrieve the approved result with citations?

## MVP Scope

### Included

- Workspace and project shell with app-owned identity and authorization.
- Engram connection settings for a local or service-backed Engram adapter.
- Source intake flow for pasted/imported transcripts, notes, bug reports, design docs, and repo scan summaries.
- Draft review queue showing proposed summaries, decisions, actions, risks, glossary terms, and possible memory records.
- Cited AI draft detail view with Engram context-pack receipts and source references.
- Explicit approve/reject/edit controls before any Engram memory promotion.
- Project capsule view backed by approved Engram memories and app-owned workspace metadata.
- Basic comments and assignments on draft review items, stored in the app rather than Engram.
- Audit trail for draft creation, approval, rejection, promotion, and visibility decisions.

### Deferred

- Full Notion-like block editor.
- Realtime multiplayer editing.
- Complex databases and formulas.
- Billing and organization administration.
- Mobile app.
- Public marketplace/connectors.
- Advanced creative critique workflows.
- Automated proactive agent triggers.

## Core Concepts

Workspace:
The app-owned tenant boundary for members, permissions, projects, pages, comments, assignments, sources, and audit records.

Project:
A workspace-scoped work area that maps to Engram `project` filters and app-owned project metadata.

Source item:
Imported or pasted raw material. The app owns the raw source, visibility, retention, and connector metadata.

Draft:
A reviewable AI or system-generated proposal derived from a source item or Engram context. Drafts are not durable Engram memories.

Decision:
A reviewed and approved conclusion that may become a page section, task, or Engram memory.

Memory promotion:
The explicit act of writing an approved distilled record to Engram through `prepare_memory()` and `store_memory()` or source-intake promotion tools.

Receipt:
Engram context-pack, operation, or usage metadata that explains what context was loaded and why.

## Engram Integration Contract

The app should use an adapter layer, not direct filesystem access.

Required adapter capabilities:

- Discover Engram protocol via `memory_protocol()`.
- Request bounded context via `context_pack()`.
- Search selectable memory snippets via `search_memories()`.
- Retrieve one chunk via `retrieve_chunk()` for inspect flows.
- Prepare candidate memory writes via `prepare_memory()`.
- Promote approved memory writes via `store_memory()` or `write_memory()`.
- Prepare messy source through `prepare_source_memory()` where available.
- Preserve context-pack receipts and citations on app draft records.
- Surface Engram operation failures as reviewable app errors, not silent drops.

Forbidden adapter behavior:

- Direct writes to `data/memories`.
- Direct reads from ChromaDB as a source of truth.
- Automatic memory promotion from comments, page edits, chat messages, or assignment churn.
- Trusting Engram metadata tags as the only authorization boundary.
- Loading full memories by default when chunks or context packs are sufficient.

## Security and Visibility

The app owns all multi-user security.

Required model:

- Authenticate users before source upload, retrieval, draft generation, or memory promotion.
- Resolve workspace/project visibility before calling Engram.
- Pass only allowed project/domain/tag/source scopes to Engram.
- Recheck output visibility before displaying any AI draft or retrieved context.
- Store raw source and app collaboration state under app-owned access control.
- Record audit events for source ingestion, draft generation, approval, rejection, edits, and Engram promotion.
- Keep connector secrets in the app, never in Engram memories.

Early prototype rule:

```text
App auth and visibility first
-> Engram retrieval second
-> app-side output visibility check third
-> human approval before durable memory write
```

## UX Principles

- Show the work: sources, citations, receipts, and approval state should be visible.
- Separate draft from truth: generated drafts should never look approved until reviewed.
- Keep dense operational screens quiet and scannable.
- Make the primary workflow source review, not a marketing-style landing page.
- Prefer explicit controls for approve, reject, edit, assign, comment, and promote.
- Keep memory promotion rare and deliberate.

## First Vertical Slice

Goal: prove the app can turn one messy source into a reviewed, cited, durable memory without violating the Engram boundary.

Flow:

1. User creates a workspace and project.
2. User connects a local Engram instance.
3. User imports or pastes a source item.
4. App calls Engram source-intake or context tools through the adapter.
5. App creates a draft review item with source references, proposed memory records, citations, and receipts.
6. User edits and approves one proposed record.
7. App calls Engram prepare/store flow for the approved memory only.
8. App records the promotion audit event.
9. Project capsule updates from app metadata plus Engram retrieval.

Success criteria:

- No raw source material is automatically promoted to memory.
- The approved memory can be found through Engram search.
- The draft retains citations and receipt metadata.
- A user without access to the project cannot see the draft, source, or retrieved context.
- App comments and assignments do not create Engram memories unless explicitly distilled and approved.

## Roadmap After MVP

### Phase 1: Reviewable Knowledge Workspace

- Source inbox.
- Draft review queue.
- Project capsule.
- Decision log.
- Basic comments and assignments.
- Engram receipts and citations in draft detail.

### Phase 2: Team Workflow Layer

- Mentions and notifications.
- Status workflows for drafts, decisions, actions, and source items.
- Role-aware views.
- Issue/task tracker integration.
- Git/repo scan import integration.

### Phase 3: Rich Knowledge Spaces

- Rich pages and backlinks.
- Game-development knowledge spaces for lore, mechanics, assets, playtests, builds, and production checklists.
- Review rooms for design, QA, release, source intake, and agent handoffs.
- Reusable workspace templates.

### Phase 4: Advanced AI Collaboration

- Critique workflows grounded in approved craft memory.
- Multi-source synthesis with visible conflict handling.
- Agent briefing and debrief rooms.
- Workspace analytics for stale decisions, unresolved drafts, and retrieval gaps.

## Open Questions

- Is the first app local desktop, hosted web, or hybrid local-first?
- Does each workspace connect to one Engram store, many project stores, or per-user local stores?
- Which auth provider and permission model should be used for the first pilot?
- Which source type should be first: transcript, design doc, bug report, repo scan, or meeting notes?
- Should raw source live only in the app, or should some source drafts also be represented in Engram draft storage?
- What is the first game-development knowledge space worth proving: playtests, lore/design, assets, builds, or production tasks?

## Risks

- Starting with a rich page editor could bury the core reviewed-memory workflow.
- Weak auth modeling could make permission-aware retrieval impossible to retrofit.
- Too many automatic writes could make Engram noisy and less trustworthy.
- Direct filesystem integration with Engram would bypass the public contract and make future service deployment harder.
- Product-specific terminology could leak into the public Engram repo if planning boundaries are not respected.

## Implementation Planning Notes

Start this product in a new repository or project root. The first implementation plan should build the adapter, workspace/project shell, source item model, draft review model, and one Engram-backed promotion flow. Do not implement rich pages, comments beyond draft discussion, or assignments beyond draft ownership until the source-to-reviewed-memory loop works end to end.
