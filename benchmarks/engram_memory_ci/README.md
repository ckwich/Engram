# Engram Memory CI Benchmarks

This directory documents reproducible benchmark suites that can be used as
product evidence for Engram Memory CI claims. The initial `smoke` suite is
self-contained and does not require copyrighted documents or external network
services.

Run from the repo root:

```bash
./venv/bin/python -m pytest tests/memory_os/test_memory_benchmarks.py -q
./venv/bin/python -m core.memory_os.memory_benchmarks run --suite smoke --seed 42
```

The smoke suite verifies:

- retrieval finds an expected daemon-owned Memory OS decision at rank 1
- memory guardrails block secret-like content
- benchmark-scoped graph evidence can be written and read back in an isolated
  fixture runtime
- sync dry-run logic excludes local-only process tables

When persisted, a benchmark run writes a `benchmark_runs` receipt plus a
content-addressed JSON artifact. It must not promote active memory bodies or
live graph evidence in the supplied runtime.
