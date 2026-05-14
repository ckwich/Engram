# Engram Backend Evaluation — 2026-05-13

Status: historical backend evidence for the Memory OS rebuild. This document
explains why Chroma/JSON stayed live during the earlier transition branch. It
does not define the active Engram 1.0 target. The active rebuild target is
`docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md`, where SQLite ledger, LanceDB, Kuzu,
content-addressed source storage, and daemon ownership are part of local 1.0.

Scope: decide whether Engram can safely lighten its backend/dependency stack
after the daemon-first and process-hygiene slices.

This is an evaluation, not a backend switch.

Current final-state policy: for local 1.0, the daemon-owned Memory OS path is
the product path. Direct JSON/Chroma remains compatibility and recovery input.
No optional backend becomes default until corpus parity, rollback recovery,
Windows restart reliability, daemon ownership, and operator documentation all
pass.

## Follow-Up Checkpoint — 2026-05-13

The implementation follow-up completed the safe stack-lightening pieces without
promoting optional backends:

- Added `server_daemon_client.py`, a thin MCP entrypoint that delegates to
  `engramd` and does not import `memory_manager`, ChromaDB,
  sentence-transformers, LanceDB, Kuzu, or document extractor modules.
- Added install/runtime profiles:
  - `requirements-daemon-client.txt`
  - `requirements-core.txt`
  - `requirements-dashboard.txt`
  - `requirements-backend-spike.txt`
- Added intent-only backend config through `ENGRAM_RETRIEVAL_BACKEND` and
  `ENGRAM_GRAPH_BACKEND`; these variables are reported by readiness tools but
  do not switch live storage.
- Fixed `LanceDBVectorIndex` table reopening. The rerun real LanceDB spike
  rebuilt 5,882 vector documents, searched, upserted a synthetic row, deleted
  that row, and reopened the persisted table with search results intact.
- Added `core/retrieval_backend_eval.py` for no-write golden retrieval
  comparison between a baseline index and a candidate index.
- Added `core/graph_backend_eval.py` for no-write graph parity, cross-document
  relationship readiness, and daemon-only Kuzu promotion reporting.
- Reran Kuzu parity in the ignored eval venv: 675 migrated graph edges saved,
  loaded, and reopened from a fresh process with parity passing. Same-process
  concurrent Kuzu opens on Windows still hit the expected database lock, so
  Kuzu remains daemon-only.

Decision after follow-up: keep Chroma and JSON live. LanceDB is no longer
blocked by the previous reopen bug, but live promotion still requires golden
Chroma-vs-Lance query quality, daemon-owned backend switching, recovery tests,
and operator docs. Kuzu remains optional until graph volume/query shape justifies
running it behind `engramd`.

## Verdict

Do not remove ChromaDB from the live stack yet, and do not add LanceDB or Kuzu
to the base install.

Engram can lighten safely by splitting install/runtime profiles:

- full local runtime: MCP + local embeddings + Chroma-backed live retrieval
- daemon-client thin adapter: future MCP adapter profile that talks only to
  `engramd` and does not import storage/index modules
- dashboard: Flask-only optional profile
- backend-spike: LanceDB/Kuzu optional evaluation profile
- dev: pytest/security tooling

The best stack-lightening target is not LanceDB/Kuzu promotion. It is splitting
the MCP daemon-client adapter so ordinary Codex sessions do not need to import
ChromaDB or sentence-transformers at all. The daemon remains the single heavy
local owner.

## Live Evidence

Repository state:

- Branch: `main`
- Latest commits:
  - `432d06d5 feat: add daemon process hygiene doctor`
  - `3bad2bd6 feat: autostart daemon client runtime`
- Working tree at eval start: clean, ahead of origin

Current required runtime dependencies in `requirements.txt`:

- `fastmcp`
- `sentence-transformers`
- `chromadb`
- `flask`
- security floors for transitive runtime packages:
  `authlib`, `cryptography`, `python-multipart`, `requests`

Current optional backend candidates:

- LanceDB is not in base requirements.
- Kuzu is not in base requirements.
- Both are adapter spikes, not live backends.

Current backend readiness probes against
`.engram/memory-os-current-20260512-010044/store`:

- Retrieval backend status:
  - live backend: Chroma
  - migrated vector source records: 5,882
  - deterministic rebuild probe: pass, 5,882 documents
  - LanceDB dependency: blocked in the main venv
  - real LanceDB corpus spike: blocked until proven
  - live backend switch: blocked
- Graph backend status:
  - live backend: JSON graph store
  - live JSON graph edges: 161
  - migrated ledger graph edges: 675
  - Kuzu dependency: blocked in the main venv
  - real Kuzu corpus spike: blocked until proven
  - live backend switch: blocked

Daemon health during eval:

- daemon status: OK
- live memory count: 983
- live chunk count: 7,319
- JSON storage: 3.6 MB
- Chroma storage: 79.4 MB
- process doctor reported multiple live `server.py` MCP adapter processes, so
  daemon-first/process-hygiene work remains relevant.

## Real Optional Backend Spike

The optional dependencies were installed only into an ignored eval venv under
`.engram/backend-eval-venv`; the main project venv was not changed.

Installed versions:

- LanceDB: 0.30.2
- Kuzu: 0.11.3

### LanceDB

Real LanceDB adapter spike over the migrated corpus:

- rebuilt 5,882 vector documents
- filtered search returned results
- upsert increased document count to 5,883
- delete by parent key removed the extra document
- post-delete document count returned to 5,882
- reopening a fresh `LanceDBVectorIndex` instance returned 0 search results

Interpretation:

The adapter can write and query a real LanceDB table in-process, but it does
not load an existing persisted table when reopened. That fails the persistence
gate for backend promotion. It is fixable, but until fixed and re-tested,
LanceDB is not a safe Chroma replacement.

Weight note:

- `lancedb` package directory: about 142 MB
- `pyarrow`: about 85 MB
- `numpy` in the eval venv: about 50 MB

LanceDB would not lighten the base install today. It would add a substantial
optional payload unless it replaces another heavy component after a proven
switch.

### Kuzu

Real Kuzu adapter spike over migrated graph edges:

- saved 675 migrated graph edges
- loaded 675 edges in the same process
- reopened from a new process and loaded 675 edges
- concurrent open of the same Kuzu database on Windows failed with a database
  lock error

Interpretation:

Kuzu can persist and reload the migrated graph through the current adapter, but
it should only be considered behind the single daemon owner. It is not a direct
multi-process graph store. Since the live graph has only 161 edges and the JSON
graph store is already stable, Kuzu is not worth adding to the base stack now.

Weight note:

- `kuzu` package directory: about 13 MB

Kuzu is not heavy, but it also is not needed for the current graph scale.

## Stack Weight Findings

Largest installed package directories in the current main venv:

- `torch`: about 443 MB
- `scipy`: about 111 MB
- `transformers`: about 88 MB
- `chromadb_rust_bindings`: about 57 MB
- `sklearn`: about 39 MB
- `onnxruntime`: about 39 MB
- `kubernetes`: about 32 MB
- `numpy` plus `numpy.libs`: about 50 MB combined

This means replacing Chroma alone is not the biggest lightening lever.
`sentence-transformers` pulls the largest local footprint through Torch,
Transformers, SciPy, and scikit-learn. Chroma adds real weight, but the largest
stack-lightening opportunity is an embedding-provider split or a daemon-client
thin adapter that avoids importing embedding/index code in client processes.

## Import Boundary Finding

Daemon-client startup now skips local embedding and Chroma initialization, but
the current `server.py` import graph still imports `memory_manager.py`, and
`memory_manager.py` imports `chromadb` at module load.

Evidence:

- Blocking `chromadb` import causes `import server` to fail.

So a daemon-client thin install is attractive but not current truth. It needs a
deliberate import-boundary refactor or a separate daemon-client MCP entrypoint.

## Security Finding

`pip check` passed.

`pip-audit` found two vulnerabilities in the current venv:

- `urllib3 2.6.3`, `CVE-2026-44431`, fixed in `2.7.0`
- `urllib3 2.6.3`, `CVE-2026-44432`, fixed in `2.7.0`

This is not a backend-promotion issue, but it is stack health. Add a
`urllib3>=2.7.0` security floor or refresh transitive dependencies in a
separate small maintenance slice.

## Recommendation

Immediate:

- Keep Chroma as the live retrieval backend.
- Keep JSON graph storage as the live graph backend.
- Keep LanceDB and Kuzu out of base requirements.
- Do not make Chroma optional until daemon-owned backend switching and recovery
  tests exist.
- Do not remove sentence-transformers from the full local runtime.
- Make Flask optional when packaging profiles are introduced.

Next implementation slice for stack lightening:

1. Use `server_daemon_client.py` plus `install.py --daemon-url
   http://127.0.0.1:8765 --thin-daemon-client` for ordinary multi-session
   Codex memory use.
2. Keep `server.py` available for the broader beta MCP surface when needed.
3. Run golden Chroma-vs-Lance query comparison before any retrieval promotion.
4. Keep Kuzu behind daemon-only planning until graph scale needs it.

Future backend work:

- Add real LanceDB query-quality comparison against current Chroma on golden
  semantic and hybrid queries.
- Keep Kuzu as optional until graph volume or query shape justifies it.
- Consider an embedding-provider seam only after daemon-client thin mode is
  done; that is where the largest local install weight lives.

## Decision

Safe to lighten the stack through profiles and daemon-client import splitting.

Not safe to lighten by removing ChromaDB or sentence-transformers from the live
full local runtime yet.

Not safe to promote LanceDB or Kuzu to required dependencies.
