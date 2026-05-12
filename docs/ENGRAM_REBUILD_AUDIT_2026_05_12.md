# Engram Rebuild Audit - 2026-05-12

Status: Final audit for the 2026-05-12 Memory OS rebuild session
Scope: `C:\Dev\Engram`, public Engram core, local Memory OS migration store,
agent-facing MCP/tool contracts, storage/retrieval/graph/document-intelligence
readiness, and hosted/sellable readiness.

## Bottom Line

The repo is in a strong local-core state: tests pass, Chroma has been rebuilt
from JSON, the Memory OS migration ledger imports the current corpus, old
Engram progress memory was migrated, the queued rebuild progress memory was
stored in the rebuilt ledger, and the new readiness/status surfaces are
documented and tested.

Engram is not yet a finished daemon-backed Memory OS or hosted sellable service.
The remaining blockers are architectural, not mystery bugs: `engramd`, real
LanceDB/Kuzu corpus spikes, live backend switching, hosted tenant isolation,
and hosted export/delete/backup guarantees.

## Evidence Run

- `git status --short --branch` before final audit: `## main...origin/main [ahead 62]`
- `python -m pytest -q`: `341 passed`
- `python server.py --help`: passed
- `python -c "from core.memory_manager import memory_manager; print('ok')"`: `ok`
- `python server.py --health`: `Status: OK`, `882` memories, `5878` chunks
- `python server.py --self-test`: `Self-test PASSED`
- `python server.py --agent-eval`: summary `status: pass`, `3` scenarios passed
- `git diff --check`: passed
- AST print audit: no stdout `print()` calls in `server.py` or `core/memory_manager.py`
- `python -m compileall -q core server.py webui.py install.py engram_index.py`: passed
- `python -m pip check`: no broken requirements
- `python -m pip_audit -r requirements.txt`: no known vulnerabilities found
- `python -m bandit -r core server.py webui.py install.py -q`: no findings
- `codex mcp get engram`: enabled stdio registration

## Migration and Memory Evidence

Fresh ignored Memory OS store:

`C:\Dev\Engram\.engram\memory-os-current-20260512-010044\store`

Imported legacy corpus:

- `source_count`: `882`
- `valid_count`: `882`
- `invalid_count`: `0`
- `unsupported_fields`: `{}`
- `chunk_count_total`: `5878`
- `derived_chunk_count_total`: `5878`
- `related_to_count`: `674`

Queued rebuild memory:

- Added key: `engram_memory_os_rebuild_progress_2026_05_12`
- Old progress key migrated: `engram_memory_os_phase5_phase6_rebuild_progress_2026_05_11`
- Final migrated key count: `883`
- Final deterministic vector rebuild probe: `5882` vector source records, `5882`
  documents, `23` batches, `status: pass`
- Final migrated graph edge count: `675` after the queued progress memory's
  `related_to` edge

## What Changed This Session

- Migration ledger now preserves stale metadata from legacy memories.
- MCP exposes `migration_dry_run()` and `memory_os_round_trip_check()`.
- MCP exposes `retrieval_backend_status()` for no-write Chroma/LanceDB/store
  readiness checks.
- MCP exposes `graph_backend_status()` for no-write JSON/Kuzu/store readiness
  checks.
- Document visual extraction requests now include `image_recognition_required`,
  `visual_evidence_contract`, and `framework_strategy`.
- Hosted/sellable readiness checklist added at
  `docs/ENGRAM_HOSTED_SELLABLE_CHECKLIST.md`.
- Chroma was rebuilt from JSON after audit found drift between live health
  chunk count and migration-derived chunk count.

## Findings

### P0: None

No data-loss bug, failing release gate, unstructured MCP exception, known
dependency vulnerability, or immediate security regression was found after the
final fixes and rebuild.

### P1: Memory OS Is Not Yet The Live Runtime

The rebuild has a solid migration ledger and readiness gates, but the live
runtime is still legacy JSON plus Chroma plus JSON graph storage. LanceDB and
Kuzu are not installed in this environment and are correctly reported as
optional candidates, not production defaults.

Required before calling the rebuild finished:

- build `engramd` as the single owner of SQLite, content store, vector index,
  graph backend, embeddings, imports, repairs, and rebuild jobs
- convert stdio MCP servers into daemon clients
- run real LanceDB and Kuzu corpus spikes on Windows against the migrated corpus
- switch live retrieval/graph storage only after the spike gates pass
- add rollback and compatibility notes for any backend switch

### P1: Hosted/Sellable Is Planned, Not Ready

The hosted checklist is now explicit, but hosted Engram cannot be sold as a
shared service until tenant access control applies before retrieval ranking.
That includes vector, lexical, graph, hybrid, receipts, source metadata, visual
artifacts, and usage telemetry.

Required before hosted release:

- threat model for local, self-hosted, and hosted modes
- authentication and tenant isolation
- object-level authorization before retrieval
- hosted backup, restore, export, delete, and audit behavior
- privacy leak tests across chunks, graph edges, receipts, sources, and telemetry

### P1: Current Codex Thread Still Has A Closed Engram MCP Transport

Tool discovery can lazy-load the `mcp__engram__` namespace, and CLI registration
is valid, but this thread's `memory_protocol()` call still returned
`Transport closed`. Direct server health, self-test, agent-eval, and
`codex mcp get engram` are healthy, so this is a current-session MCP transport
mount issue rather than proof of broken repo code.

Operational guidance:

- use fresh Codex sessions after MCP surface changes
- do not treat configured registration as current-thread callability
- the daemon work should remove most direct Chroma ownership pressure from
  stdio sessions

### P2: Chroma Drift Was Found And Repaired

Initial final health reported `5521` chunks while the migration ledger derived
`5878` chunks from authoritative JSON. Running `server.py --rebuild-index`
rebuilt `882` memories and health now reports `5878` chunks.

Recommendation:

- keep `server.py --health` and migration dry-run chunk counts in release gates
- consider adding a lightweight parity check that compares Chroma chunk count
  with derived JSON chunks without requiring a full rebuild

### P2: Rebuild Store Is Ignored And Not Yet Productized

The current rebuilt store lives under `.engram/`, which is correct for this
session but not a user-facing default. It proves import/rebuild readiness, not a
supported runtime storage location.

Recommendation:

- define official Memory OS local storage paths
- document backup/export/restore behavior for the ledger and content-addressed
  store
- decide how local users select legacy mode versus Memory OS mode during the
  transition

### P2: Docs Are Clear, But Roadmaps Now Span Two Eras

The repo intentionally contains the old Engram 1.0 release docs and the newer
Memory OS rebuild spec. This is useful history, but it can confuse future
agents unless they start from `plan.md` and the rebuild spec.

Recommendation:

- keep `plan.md` as the current routing document
- when daemon work begins, add a new implementation plan specifically for the
  Memory OS runtime instead of extending old Track 4-6 wording

## Hosted/Sellable Checklist

The dedicated checklist is now tracked in
`docs/ENGRAM_HOSTED_SELLABLE_CHECKLIST.md`.

Highest gates before selling hosted Engram:

- `engramd` owns all mutable indexes and jobs
- tenant authorization runs before any retrieval/ranking
- local-first mode remains fully useful offline
- migration from JSON is a first-class onboarding path
- export/delete/backup/restore are product promises
- support bundles redact memory bodies by default
- hosted collaboration features stay outside Engram core

## Repo Health Summary

Strong:

- 341 passing tests across storage, MCP contracts, source intake, document
  intelligence, graph, vector, WebUI auth, usage, and reliability harnesses
- no known vulnerable dependencies from `pip-audit`
- no `bandit` findings in the scanned app code
- no TODO/FIXME/HACK markers in tracked source/docs
- public docs avoid private project names
- WebUI exposed-host security remains heavily tested
- migration and backend readiness are explicit, no-write MCP surfaces

Residual risk:

- no daemon yet
- LanceDB/Kuzu not proven with real installed dependencies
- hosted service security is not implemented
- current-thread MCP transport can still be stale/closed after lazy-load
- Memory OS ledger is a migration/readiness store, not live retrieval yet

## Recommendation

Treat the current repo as a stable, well-tested local Engram core plus a proven
Memory OS migration foundation. The next build milestone should not be more
surface polish. It should be the daemon/runtime slice that makes the rebuilt
ledger and backend seams the actual operating path.
