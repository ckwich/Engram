# Engram Refactor Baseline

Branch: `codex/memory-os-architecture-hardening`
Date: `2026-05-13T15:40:11.9307450-07:00`
Commit: `d1c29936`
Python: `Python 3.12.10`
OS: `Microsoft Windows 10.0.26200`

## Purpose

This baseline records the repo state before the non-EKC architecture hardening
work. Do not treat these commands as a license to broaden scope; use them as the
comparison point for later phases.

## Commands Run

| Command | Exit | Result |
|---|---:|---|
| `git status --short --branch` | 0 | `main...origin/main [ahead 4]` before branch creation; no dirty files. |
| `git log --oneline -5` | 0 | Top commit before branch creation: `d1c29936 docs: harden non-EKC repo improvement plan`. |
| `git checkout -b codex/memory-os-architecture-hardening` | 0 | Created isolated implementation branch. |
| `.\venv\Scripts\python.exe server.py --help` | 0 | CLI help rendered for Engram 1.0.0. |
| `.\venv\Scripts\python.exe engramd.py --doctor` | 0 | Daemon health `ok`; 1 daemon and 1 daemon launcher detected; no warnings. |
| `.\venv\Scripts\python.exe engramd.py --smoke-test` | 0 | Store/search/retrieve/delete daemon smoke passed through Memory OS backend. |
| `$env:ENGRAM_DATA_DIR = Join-Path $env:TEMP ('engram-baseline-self-test-' + [guid]::NewGuid()); .\venv\Scripts\python.exe server.py --self-test` | 0 | Isolated self-test passed. |
| `$env:ENGRAM_DATA_DIR = Join-Path $env:TEMP ('engram-baseline-agent-eval-' + [guid]::NewGuid()); .\venv\Scripts\python.exe server.py --agent-eval` | 0 | Agent reliability eval passed: 3/3 scenarios and 2/2 workflow checks. |
| `.\venv\Scripts\python.exe -m pytest -q` | 0 | `482 passed, 2 skipped, 6 warnings in 35.10s`. |
| `git diff --check` | 0 | No whitespace errors. |

## Daemon Snapshot

- Daemon URL: `http://127.0.0.1:8765`
- Daemon status: `ok`
- Total memories: `986`
- Total chunks: `7333`
- Storage size: `83.0 MB`
- JSON path: `C:\Dev\Engram\data\memories`
- Chroma path: `C:\Dev\Engram\data\chroma`
- Process hygiene: one daemon launcher and one daemon process, no explicit stop
  candidates, no warnings.

## Known Failures

None observed in the baseline commands.

## Known Skips

- Full pytest reported 2 skipped tests. The baseline run did not expand skip
  reasons; later phases should preserve or explicitly justify this count.

## Known Warnings

- Full pytest reported 6 warnings.
- Warning class observed: LanceDB `table_names()` deprecation warning from
  `core/lancedb_vector_index.py`, also surfaced through `asyncio.events`.

## Baseline Rule

Do not treat future failures as pre-existing unless they match this document or
are recorded in a later phase baseline. If a refactor touches a subsystem with a
new failure, prove whether the failure existed before the change.
