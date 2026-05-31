# Engram

Engram is a local-first Memory OS for AI agents. It exposes durable memory,
cited retrieval, reviewed source intake, document evidence workflows, graph
evidence, and local runtime inspection through MCP.

Engram is built around a small retrieval ladder:

1. Search for relevant snippets.
2. Retrieve the cited chunk when a snippet is useful.
3. Read the full memory only when a chunk is not enough.

That keeps agent context smaller, easier to cite, and easier to review.

## What Works Now

- `engramd` daemon runtime with one writer owning the local data root.
- Thin MCP client entrypoint through `server_daemon_client.py`.
- SQLite ledger for metadata, jobs, transactions, snapshots, receipts, aliases,
  entities, concepts, and migration state.
- Content-addressed source store for raw, normalized, and extracted evidence.
- LanceDB retrieval and Kuzu graph storage inside the daemon-owned runtime.
- Legacy JSON compatibility, with Chroma recovery support only when an operator
  installs ChromaDB separately.
- Semantic memory search with metadata filters for project, domain, tags,
  lifecycle status, and canonical memories.
- Chunk and full-memory retrieval with stable citations.
- Reviewed source intake and prepared-memory promotion.
- Document disassembly, artifact storage, coverage receipts, and reviewed
  document-ingestion completion.
- Read-only Knowledge Contract queries for orientation, review preparation,
  evidence audit, graph evidence, entity profiles, decision packets,
  implementation context, and evidence bundles.
- Local Web Inspector for Memory OS state.
- Personal Hub Mode for one always-on local hub with clients using an access
  token.
- Docker Compose self-hosting for private/local deployments.

## Privacy Model

Engram is local-first. Runtime data belongs in a local application-data folder
or a private self-hosted volume, not in the git checkout.

Do not commit runtime memory stores, SQLite ledgers, WAL files, vector indexes,
graph indexes, sync inboxes, document artifacts, exported bundles, model caches,
or local credentials. The repository is intended to contain source code, tests,
fixtures, and public documentation only.

## Requirements

- Python 3.10 or newer
- Windows, macOS, or Linux
- Optional local document tools: Poppler and Tesseract
- Optional Docker and Docker Compose for private self-hosting

## Install

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

On macOS or Linux:

```bash
python3 -m venv venv
./venv/bin/python -m pip install --upgrade pip
./venv/bin/python -m pip install -r requirements.txt
```

## Start The Daemon

```powershell
.\venv\Scripts\python.exe engramd.py --host 127.0.0.1 --port 8765
```

Check daemon health:

```powershell
.\venv\Scripts\python.exe engramd.py --doctor
```

## Register MCP

Use the thin daemon client for normal multi-session agent work:

```powershell
.\venv\Scripts\python.exe install.py --daemon-url http://127.0.0.1:8765 --thin-daemon-client
```

The thin client does not open local storage directly. It talks to the running
daemon and keeps SQLite, LanceDB, Kuzu, Chroma, and document extraction state
owned by one process.

## Core MCP Flow

```text
memory_protocol()
search_memories(query, limit=5)
retrieve_chunk(key, chunk_id)
retrieve_memory(key)
query_knowledge(...)
```

Use `retrieve_memory` only when chunk-level context is insufficient.

For writes, use the review surfaces first when available:

```text
prepare_source_memory(...)
store_prepared_memory(...)
```

Direct memory writes should stay small. Larger source material should go through
source intake, document intake, or artifact storage so review coverage remains
explicit.

## Document Workflow

The document workflow is review-first:

```text
list_document_extractors
prepare_document_disassembly
prepare_document_intake_review
prepare_document_artifact_store
store_document_artifact
prepare_document_ingestion_completion
complete_document_ingestion
```

Engram can prepare evidence, coverage receipts, extraction requests, and
reviewed completion records. It does not silently promote document text or graph
edges into active memory.

See `docs/DOCUMENT_INGESTION_WORKFLOW.md` for details.

## Local Web Inspector

The Web Inspector is a local review surface:

```powershell
.\venv\Scripts\python.exe webui.py
```

Loopback use is the default. If you bind the Web Inspector to a non-loopback
address, configure access and write tokens first.

See `docs/REMOTE_WEBUI.md` for token and host-header behavior.

## Personal Hub Mode

Personal Hub Mode lets one machine own the live daemon while other local clients
connect with `ENGRAM_HUB_URL` and `ENGRAM_HUB_ACCESS_TOKEN`.

See `docs/HUB_MODE_TAILSCALE.md` and `docs/SYNC_DESKTOP_LAPTOP.md`.

## Private Self-Hosting

Docker Compose can run a private local deployment:

```bash
docker compose up -d engramd-core
curl -fsS http://127.0.0.1:8765/health
```

See `docs/SELF_HOSTING.md`.

## Validation

Basic local checks:

```powershell
.\venv\Scripts\python.exe server.py --help
.\venv\Scripts\python.exe -c "from core.memory_manager import memory_manager; print('ok')"
.\venv\Scripts\python.exe engramd.py --preflight
.\venv\Scripts\python.exe engramd.py --doctor
.\venv\Scripts\python.exe engramd.py --smoke-test
```

Isolated direct-mode checks:

```powershell
$env:ENGRAM_DATA_DIR = Join-Path $env:TEMP "engram-self-test"
.\venv\Scripts\python.exe server.py --self-test
.\venv\Scripts\python.exe server.py --agent-eval
Remove-Item Env:\ENGRAM_DATA_DIR
```

## Public Docs

- `docs/DOCUMENT_INGESTION_WORKFLOW.md`
- `docs/HUB_MODE_TAILSCALE.md`
- `docs/LOCAL_HOOKS.md`
- `docs/OPERATOR_RECOVERY.md`
- `docs/PERFORMANCE_BENCHMARKS.md`
- `docs/REMOTE_WEBUI.md`
- `docs/SECURITY_SWEEP_2026_05_30.md`
- `docs/SELF_HOSTING.md`
- `docs/SYNC_DESKTOP_LAPTOP.md`

## License

MIT. See `LICENSE`.
