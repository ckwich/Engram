# Engram Architecture Hardening Closeout

Date: 2026-05-13
Branch: `codex/memory-os-architecture-hardening`
Implementation head before this closeout: `b6aec5e9`

## Scope Completed

This branch executed the pre-EKC hardening lane from
`docs/superpowers/plans/2026-05-13-engram-non-ekc-repo-hardening-plan.md`.
It did not implement EKC. The goal was to make the existing Engram 1.0
architecture safer to build on.

Completed slices:

- Recorded a clean architecture/refactor baseline.
- Added executable import-boundary tests for the thin daemon client, Memory OS,
  document preview modules, graph services, and legacy memory-manager imports.
- Re-centered docs and tests on `server_daemon_client.py` as the recommended
  multi-session agent entrypoint.
- Standardized explicit no-write policy metadata across representative preview,
  draft, context, document, and project capsule surfaces.
- Added backend readiness wrappers for retrieval and graph promotion reports.
  These wrappers report decisions and blockers without switching live backends.
- Added `docs/RELEASE_GATES.md` and release-gate doc tests that distinguish the
  pre-EKC readiness gate from the full 1.0 release gate.

## Commits

- `64266b41` - `docs: record architecture refactor baseline`
- `e2d7e5e2` - `test: add architecture import boundary checks`
- `65963305` - `docs: recommend thin daemon client for agents`
- `e6eaa2a7` - `feat: standardize no-write policy metadata`
- `8ef644cb` - `feat: add executable backend readiness gates`
- `b6aec5e9` - `docs: consolidate Engram release gates`

## Validation

Final verification passed:

```text
python -m pytest -q
502 passed, 2 skipped, 6 warnings in 34.41s
```

Additional gates passed:

- `python server.py --help`
- `python -c "from core.memory_manager import memory_manager; print('ok')"`
- `python engramd.py --doctor`
- `python engramd.py --smoke-test`
- isolated `python server.py --self-test`
- isolated `python server.py --agent-eval`
- `python -m pytest tests\release\test_release_gate_docs.py tests\architecture tests\test_server_daemon_client_entrypoint.py tests\policy tests\mcp\test_no_write_tool_contracts.py tests\backend_gates -q`
- `git diff --check`

Daemon state during final doctor:

- daemon status: `ok`
- total memories: `986`
- total chunks: `7333`
- process hygiene warnings: none

`server.py --agent-eval` passed all 3 retrieval scenarios and both workflow
checks, including the Book Dismantling Gate.

## EKC Launch Point

The repo is now in better shape to start EKC v0:

- Use `docs/RELEASE_GATES.md` as the pre-EKC readiness gate.
- Use `server_daemon_client.py` as the normal multi-session MCP entrypoint.
- Keep EKC v0 read-only and policy-enforced.
- Reuse existing project capsule behavior instead of adding a parallel capsule
  semantics path.
- Treat skipped parity, unproven Windows behavior, and unproven backend live
  switches as blockers, not soft warnings.

The next implementation session can begin with
`docs/superpowers/plans/2026-05-13-engram-knowledge-contract-v0-plan.md`.

