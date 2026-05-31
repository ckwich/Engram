# Security Sweep - 2026-05-30

This note records the public-repository security sweep performed before the
clean public snapshot.

## Scope

- Current source tree and public documentation.
- Declared dependency inputs: `requirements.txt` and `requirements-dev.txt`.
- Runtime entrypoints: `engramd.py`, `server.py`, `server_daemon_client.py`,
  `install.py`, sync transport, hub transport, source intake, document intake,
  and Memory OS storage helpers.
- Repository hygiene checks for personal paths, private project names, local
  memories, launch material, and forward-looking planning material.

Ignored local runtime stores, private planning folders, and old local database
backups were moved out of the repository folder before the public snapshot.

## Tooling

- `pip-audit -r requirements.txt`: no known vulnerabilities.
- `pip-audit -r requirements-dev.txt`: no known vulnerabilities.
- `bandit -r core server.py server_daemon_client.py engramd.py install.py engram_index.py scripts -x core\__pycache__ -ll`:
  no medium or high issues.
- Focused sync peer transport regression tests: 6 passing tests.
- Full test suite: 1126 passing tests, 4 environment-gated skips.
- Daemon and direct-mode validation gates:
  `server.py --help`, `memory_manager` import, `engramd.py --preflight`,
  `engramd.py --doctor`, `engramd.py --smoke-test`, isolated
  `server.py --self-test`, and isolated `server.py --agent-eval`.

## Fixes Applied

- Raw daemon and sync listeners now reject negative `Content-Length` values.
- Raw daemon POST requests reject unsupported content types, hostile browser
  headers, and unsafe exposed-host requests before dispatch.
- Docker Compose publishes the raw daemon port on loopback only by default.
- Remote hub and raw daemon client URLs reject embedded credentials and unsafe
  public cleartext HTTP defaults unless the operator explicitly opts in.
- Daemon and peer client response reads are bounded.
- Sync peer URLs reject credentials, query strings, fragments, and path suffixes.
- Sync peer bundle pushes do not follow peer-supplied redirects.
- Sync key files reject symlink writes/loads and tighten file permissions where
  the platform allows it.
- Source and document connector globs reject absolute and parent-directory
  escapes, skip symlinks, and keep resolved files under the declared root.
- Content-addressed storage verifies existing artifacts match the expected
  digest and refuses symlink or non-regular artifact paths.
- Legacy recovery backups skip symlinked files, reject non-regular sources, and
  keep archived files under the approved source root.
- Sync apply table access is allowlisted before any ledger import/readback.
- SQLite dynamic table identifiers are schema-owned and annotated so static
  analysis remains useful for new issues.

## Remaining Operator Notes

- Rebuild developer virtual environments from the checked-in requirements before
  auditing the installed environment itself. Ignored local virtualenv contents
  are not part of the public repository artifact.
- Keep runtime data, sync inboxes, vector indexes, graph stores, Chroma data,
  document artifacts, exported bundles, and model caches outside git.
