# Engram Hosted and Sellable Checklist

Date: 2026-05-12
Status: Planning checklist
Scope: Optional hosted/self-hosted Engram edition readiness, not local core requirements

## Boundary

Engram core remains a public, generic, local-first agent memory system. Hosting
Engram should be an optional deployment path, not a reason to weaken local
privacy, explicit writes, evidence records, or rebuildable storage.

This checklist does not move team collaboration into this repository. A
collaboration app may use Engram as a memory substrate, but workspaces, shared
pages, comments, assignments, mentions, team authorization, product workflow UI,
and billing experience belong to that separate product unless a future Engram
service explicitly takes ownership of those concerns with a new threat model.

## Current Rebuild Proofs

- Legacy JSON memories import into the Memory OS migration ledger without lossy
  field conversion.
- Import/export/restore round-trip checks prove the current memory corpus can
  migrate through a disposable store.
- Retrieval backend status reports Chroma as the legacy live index and LanceDB
  as an optional candidate, with no live backend switch; LanceDB table reopen
  is fixed and golden retrieval comparison remains the promotion gate.
- Graph backend status reports JSON graph storage as the legacy live graph
  backend and Kuzu as an optional candidate, with no live backend switch; Kuzu
  parity passes in daemon-style fresh-process reopen tests but remains
  daemon-only because Windows concurrent opens lock.
- Thin daemon-client registration exists for ordinary multi-session agents, so
  Codex sessions can avoid importing local storage/index modules while using one
  shared `engramd`.
- Document intelligence supports review-first text, document, OCR, and vision
  evidence contracts without trusted memory promotion.

## Hostable Core Gates

- Single-owner daemon exists for SQLite, content store, vector index, graph
  backend, embeddings, import jobs, repair jobs, and rebuild jobs.
- Stdio MCP servers become thin clients of the daemon rather than direct owners
  of embedded vector or graph backends.
- SQLite ledger migrations are versioned, repeatable, reversible where
  practical, and tested against legacy JSON imports.
- Content-addressed raw and normalized source storage has export, restore,
  integrity checks, and delete semantics.
- Vector and graph indexes rebuild fully from durable ledger/source content.
- Retrieval receipts include filters, rankings, stale/conflict warnings,
  citation refs, omitted counts, and budget estimates.
- Memory promotion requires explicit review for source, document, OCR, vision,
  and agent-drafted content.
- Local-first mode remains fully useful without hosted sync, hosted billing, or
  cloud-only dependencies.

## Security Gates

- Threat model covers local desktop, self-hosted server, and hosted service
  modes separately.
- Hosted mode has real authentication, session management, tenant isolation,
  object-level authorization, and audit logs before any shared retrieval.
- Tenant access control applies before vector, lexical, graph, or hybrid
  ranking.
- Secrets, API keys, model credentials, billing credentials, and signing keys
  never enter memory content, receipts, logs, or export bundles.
- All source imports have size limits, MIME/type validation, path traversal
  protection, SSRF protections for URL connectors, and malware scanning policy
  if files are accepted.
- Web/dashboard exposure remains fail-closed with host/origin checks, CSRF
  posture, rate limiting, security headers, body limits, and CSP.
- Deletion is defined for memories, sources, documents, visual artifacts,
  chunks, embeddings, graph edges, receipts, backups, and hosted replicas.
- Privacy leak tests prove one tenant cannot retrieve another tenant's chunks,
  graph edges, receipts, source metadata, or usage telemetry.

## Operations Gates

- Health checks distinguish daemon health, MCP availability, semantic retrieval
  health, graph backend health, migration state, and queue/job health.
- Backup and restore cover SQLite ledger, content store, vector index rebuild,
  graph index rebuild, configuration, and audit logs.
- Rebuild jobs are idempotent and resumable; failed jobs leave receipts with
  clear retry or rollback guidance.
- Operator CLI supports dry-run migration, dry-run rebuild, integrity audit,
  metadata repair dry-run, export bundle, restore bundle, and health report.
- Observability records status and aggregate metrics without storing raw memory
  bodies in logs.
- Upgrade path includes migration notes, compatibility windows, and rollback
  instructions.
- Support bundle redaction removes private memory bodies by default while
  preserving schema, counts, errors, and environment details.

## Sellable Product Gates

- First-run experience explains Engram as an agent memory OS, not merely a
  vector database wrapper.
- Fresh agents can discover the safe retrieval/write/source/document/graph
  ladder from `memory_protocol()` without reading the full README.
- Migration from existing local Engram JSON is a first-class onboarding path
  with parity proof.
- Demo data shows trust-aware memory: evidence, citations, stale warnings,
  conflicts, graph impact, document evidence, OCR/vision evidence, and explicit
  promotion.
- Hosted/self-hosted value is clear: reliable agent memory across tools,
  durable evidence, controlled retrieval, document intelligence, graph-aware
  context, eval receipts, and operational safety.
- Pricing and packaging are separated from local open-source core semantics.
- Export and portability are visible product promises, not hidden admin tasks.
- Public docs include limits and non-goals: no surprise writes, no cloud lock-in,
  no team collaboration features in Engram core, no retrieval without access
  filtering in hosted mode.

## Release Decision Checklist

Use this before presenting Engram as hosted-ready or sellable:

- Can a new user install/run local Engram and pass the local health gate?
- Can a new agent call `memory_protocol()` and use memory safely?
- Can legacy JSON import, round-trip, and restore without data loss?
- Can source/document/OCR/vision evidence be reviewed before promotion?
- Can vector and graph indexes be rebuilt from durable state?
- Can a hosted tenant only retrieve authorized context?
- Can an operator explain where raw source bytes, normalized text, embeddings,
  graph records, receipts, backups, and logs live?
- Can the product be backed up, restored, exported, deleted, and upgraded?
- Can support diagnose failures without reading private memory bodies?
- Can public docs explain what Engram is, what it is not, and why an agent should
  trust it?

## Do Not Ship Hosted Until

- The daemon architecture replaces direct multi-process ownership of embedded
  retrieval/graph backends.
- Tenant isolation and object authorization are enforced before retrieval.
- Hosted deletion/export/backup behavior is tested, documented, and audited.
- LanceDB, Kuzu, or any replacement backend has passed real corpus tests before
  becoming the live default.
- The collaboration product boundary remains intact.
