# Operator Recovery

This document describes current local operator checks for Engram.

## Runtime Checks

Use these commands to verify the local daemon and runtime state:

```powershell
.\venv\Scripts\python.exe engramd.py --preflight
.\venv\Scripts\python.exe engramd.py --doctor
.\venv\Scripts\python.exe engramd.py --smoke-test
```

`--preflight` checks the selected data root before daemon startup.
`--doctor` checks process hygiene, runtime preflight, ledger state, and graph
reconciliation. `--smoke-test` performs a store, search, retrieve, benchmark,
and delete cycle through the daemon.

## Recovery Boundaries

The daemon-owned Memory OS ledger and content store are durable runtime state.
Vector indexes, graph indexes, Chroma data, temporary document artifacts, and
sync inbox files are rebuildable or reviewable runtime artifacts. Do not commit
them to git.

Before restoring or replacing a runtime data root:

1. Stop active daemon processes cleanly.
2. Preserve the existing runtime directory as an operator backup.
3. Run `engramd.py --preflight` against the target data root.
4. Start the daemon on loopback.
5. Run `engramd.py --doctor` and `engramd.py --smoke-test`.

## Backend Readiness

Backend readiness is conservative. Engram should report blocked readiness when
candidate retrieval or graph backends have not proven corpus parity, recovery,
restart behavior, and operator documentation.

Skipped parity is a blocker for default backend promotion. A skipped parity
result means the comparison was not executed, not that the candidate backend is
safe to promote.

## Sync Recovery

Sync changesets and sync inbox payloads are review surfaces. If an apply fails,
inspect conflicts with the sync conflict tools, resolve reviewed conflicts, and
rerun the convergence check before deleting local inbox artifacts.
