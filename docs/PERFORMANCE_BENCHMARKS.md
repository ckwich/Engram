# Engram Performance Benchmarks

Date: 2026-05-21

Engram's benchmark lane is intentionally separate from the normal pytest and
release-gate path. It gives operators a repeatable way to collect startup,
daemon, document, Docker, and ops timings without making every development run
slow or dependent on Docker.

## Quick Catalog

```bash
./venv/bin/python scripts/benchmark_engram.py --list --json
```

The catalog is machine-readable and currently covers:

- `startup_imports`: thin client, full server, and Memory OS runtime imports.
- `daemon_search`: live daemon search against a temporary benchmark memory.
- `daemon_retrieve_chunk`: live daemon chunk retrieval against a temporary
  benchmark memory.
- `daemon_direct_write`: live daemon direct memory write with cleanup.
- `daemon_metadata_update`: live daemon metadata update with cleanup.
- `document_ingestion`: isolated synthetic Document Intelligence ingestion.
- `docker_startup`: Compose config timing by default, optional isolated Compose
  startup with `--include-docker-live`.
- `ops_commands`: operator command timing. Slow release checks are included
  only with `--include-slow-ops`.

## Planning Without Running

```bash
./venv/bin/python scripts/benchmark_engram.py --plan --json
```

Use this in docs, CI setup, and release planning when you need to prove the
suite covers the startup-regression dimensions without touching a live daemon or
starting Docker.

## Safe Default Run

```bash
./venv/bin/python scripts/benchmark_engram.py --run --json
```

The default run uses isolated or static work:

- startup imports run under a temporary `ENGRAM_DATA_DIR`;
- startup imports set `ENGRAM_DAEMON_AUTOSTART=0`;
- document ingestion uses the existing isolated synthetic reliability harness;
- ops commands run static self-host validation and `server.py --help`.

## Live Daemon Run

```bash
./venv/bin/python scripts/benchmark_engram.py --run --include-live-daemon --json
```

Live daemon scenarios require `--include-live-daemon`, even when a scenario is
selected by id. Without that flag, the harness records a skipped result instead
of touching the daemon.

Live daemon scenarios create temporary `_engram_benchmark_*` memories and delete
them during cleanup. They measure the same daemon route path used by thin MCP
clients. They first require daemon health with Memory OS retrieval ready, so a
warming fallback path is not accidentally measured as normal performance. Pass
`--require-live-daemon` in automation when a skipped daemon benchmark should
fail the run.

## Docker Startup Run

```bash
./venv/bin/python scripts/benchmark_engram.py --run --scenario docker_startup --include-docker-live --json
```

Docker startup is opt-in. The harness uses a unique Compose project name and
runs `docker compose down -v` afterward. It also records a skip when
`127.0.0.1:8765` is already in use so the benchmark does not collide with a
developer's normal local daemon.

## Slow Ops Run

```bash
./venv/bin/python scripts/benchmark_engram.py --run --scenario ops_commands --include-slow-ops --json
```

This adds `engramd.py --doctor`, `engramd.py --smoke-test`, isolated
`server.py --self-test`, and isolated `server.py --agent-eval` timings to the
ops benchmark.

## Reading Results

Benchmark output is JSON by default in automation. Each result reports:

- `status`: `pass`, `fail`, or `skipped`;
- `metrics`: stable timing and count fields;
- `details`: command receipts or backend information;
- `error`: a compact failure or skip reason.

Treat benchmark values as local trend data, not universal product guarantees.
Track changes across the same machine, data root, and benchmark flags before
calling a performance regression.
