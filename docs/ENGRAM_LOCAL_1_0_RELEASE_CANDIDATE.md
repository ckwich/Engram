# Engram Local 1.0 Release Candidate

Date: 2026-05-14
Branch: `codex/ekc-v0-contract`
Validation commit: `6a3e6710`

This is a local-first release-candidate checkpoint for Engram as an agent-facing
Memory OS. It is not a hosted/team product release. The validated path is a
loopback daemon owner with thin MCP clients as the normal multi-session agent
entrypoint.

## What Is Stable

- Thin daemon-client MCP path through `server_daemon_client.py`.
- Daemon-owned Memory OS runtime through `engramd`.
- EKC read-only `query_knowledge` contract for project, source, document,
  review, evidence, graph, and artifact-family orientation.
- Document intake review, disassembly, visual/OCR coverage requests, and
  ledgered document-evidence artifact flow.
- Explicit reviewed promotion flow for document evidence, with accept/reviewer
  requirements before memory or graph writes.
- Memory Inspector review queue, document artifact transaction, promotion
  transaction, graph evidence, EKC eval, and release-gate surfaces.
- Codebase mapping with current Memory OS domains, source hashes, drift checks,
  and central-file omission warnings.
- Backend truth reporting that keeps daemon-owned Memory OS as the product path
  while treating direct JSON/Chroma as compatibility and recovery input.

## What Remains Deferred

- Hosted auth, tenant isolation, billing, sync, marketplace, and team workflow
  features.
- Optional backend live switches. LanceDB/Kuzu candidate promotion remains
  blocked until corpus parity, rollback recovery, Windows restart reliability,
  daemon ownership, and operator docs pass.
- Autonomous document analysis inside Engram. Agents still supply synthesis and
  review decisions.
- Full removal of legacy JSON/Chroma compatibility.

## Validation

| Command | Result |
|---|---|
| `.\venv\Scripts\python.exe server.py --help` | Pass |
| `.\venv\Scripts\python.exe -c "from core.memory_manager import memory_manager; print('ok')"` | Pass |
| `.\venv\Scripts\python.exe engramd.py --doctor` | Pass: daemon healthy, one daemon plus one launcher, no warnings |
| `.\venv\Scripts\python.exe engramd.py --smoke-test` | Pass: health, duplicate check, store, metadata update/repair, search, chunk read, memory read, delete |
| isolated `.\venv\Scripts\python.exe server.py --self-test` | Pass |
| isolated `.\venv\Scripts\python.exe server.py --agent-eval` | Pass: 3 retrieval scenarios, 2 workflow checks, Book Dismantling Gate |
| `.\venv\Scripts\python.exe -m pytest -q` | Pass: 631 passed, 2 skipped, 26 warnings |
| `git diff --check` | Pass |

Warnings are the existing LanceDB `table_names()` deprecation warnings surfaced
by tests that exercise Memory OS document/evidence paths.

## How To Use Engram From Other Projects

1. Keep `engramd` running on loopback.
2. Use `server_daemon_client.py` as the Codex MCP entrypoint for ordinary
   multi-session agent work.
3. Start with `memory_protocol()` when tool choice is unclear.
4. Use `search_memories`, `read_chunk`, and `query_knowledge` before full
   memory reads.
5. Use document intake review tools for large source material; promote only
   after review.
6. Treat backend readiness reports as evidence, not switches.

## Operator Notes

- Use `docs/ENGRAM_CURRENT_STATUS.md` for the current stability-tier map.
- Use `docs/RELEASE_GATES.md` before future release or architecture work.
- Use `AGENTS.md` before modifying core architecture or agent-facing contracts.
- Do not promote optional backend defaults or hosted product scope without a new
  explicit implementation plan and release gate.
