# Engram Current Status

Date: 2026-05-14

This page is the short operational truth for the current Engram repo. For the
full architecture, see `docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md`; for executable
release gates, see `docs/RELEASE_GATES.md`.

## Stable

- Thin daemon-client MCP entrypoint: `server_daemon_client.py`.
- Local daemon owner: `engramd` on loopback.
- Core retrieval and explicit memory writes through daemon-owned runtime.
- EKC `query_knowledge` read-only serving contract on the compatibility
  `engram.knowledge.*.v0` envelope.
- Agent-facing retrieval ladder: search, chunk read, and full memory read only
  when chunk context is insufficient.

## Beta

- `document intake` and intelligence review flow.
- Ledgered document evidence artifacts.
- Review-preparation, evidence-audit, graph-evidence, and artifact-family EKC
  packets.
- Agent workflow helpers, usage estimates, operation receipts, codebase
  mapping, backend readiness reports, and inspector surfaces.

## Legacy Compatibility

- Direct `server.py` mode.
- `core.memory_manager`.
- `legacy JSON/Chroma` memories and index.
- Legacy JSON graph storage where still needed for compatibility and migration
  evidence.

## Deferred

- Hosted auth, tenant isolation, billing, sync, marketplace, comments,
  assignments, and rich team workflow UI.
- Any hosted scope beyond local-first daemon operation.
- Live backend switching unless recovery, parity, and operator documentation
  gates pass.
- Autonomous document analysis inside Engram.

## Operating Rule

Use the thin daemon-client path for ordinary Codex work. Use direct `server.py`
only for deliberate compatibility debugging, local self-tests, or migration
work.
