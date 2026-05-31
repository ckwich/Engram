# Engram Self-Hosting

This package makes local and private self-hosted Engram reproducible.

Engram's self-hosted shape is still the local Memory OS shape:

```text
thin clients -> one engramd-core -> SQLite + objects + LanceDB + Kuzu
```

Do not publish the daemon port to the public internet. The default Compose file
binds `engramd-core` to loopback only. Use a private network boundary and the
documented access tokens for any non-loopback Web Inspector access.

Raw `engramd` and MCP SSE transports now fail closed on non-loopback binds
unless `ENGRAM_ALLOW_PUBLIC_BIND` is set to an explicit acknowledgement such as
`loopback-published`. Use that only when another boundary is enforcing access,
for example Docker Compose binding the host port to `127.0.0.1`. Do not use it
to put the raw daemon or SSE MCP
endpoint directly on the public internet.

## Services

- `engramd-core`: the only long-running writer. It owns `/var/lib/engram`.
- `web-inspector`: optional local inspector profile.
- `mcp-gateway`: optional thin MCP client profile for controlled environments.
- `ops`: one-shot validation profile for doctor, smoke, self-test, and
  agent-eval checks.

The one writer rule is strict: run exactly one `engramd-core` against a given
data volume.

Containers run as the non-root `engram` user (`10001:10001`). The Compose file
adds conservative memory and process limits, keeps published ports on loopback,
and keeps direct-mode ops checks on temporary data roots so validation cannot
write self-test records into the release data volume.

## Native Tools

The core image installs Poppler and Tesseract:

- Poppler: `pdfinfo`, `pdftotext`, `pdfimages`, and `pdftoppm`.
- Tesseract: OCR support for coverage passes that require it.

Document workflows can still report missing adapter coverage when a source
requires capabilities outside the local toolchain.

The core image installs the CPU Torch wheel before the rest of the Python
requirements. That keeps local/self-hosted images from accidentally resolving a
CUDA dependency stack on Linux.

## Build

```bash
docker build --target engramd-core -t engram:local .
docker build --target thin-client -t engram-thin-client:local .
```

## Run

```bash
docker compose up -d engramd-core
curl -fsS http://127.0.0.1:8765/health
```

Check the `serving` object in `/health`, not only the top-level `status`.
`serving.search_backend` reports the backend currently serving search
(`memory_os` or `legacy_json_chroma`), and `serving.fallback_active` plus
`serving.fallback_reason` tells you when Memory OS retrieval is still warming
and reads are being served by the slower legacy fallback.
When Memory OS is configured, `/health.stats.source` is `memory_os` and the
top-level memory/chunk counts describe the active Memory OS corpus. Legacy
JSON/Chroma compatibility counts are still exposed under `/health.legacy_stats`.

The core image itself defaults to loopback binding. Compose deliberately binds
to `0.0.0.0` inside the container only with
`ENGRAM_ALLOW_PUBLIC_BIND=loopback-published`, and then publishes the host port
as `127.0.0.1:8765:8765`.

Data and model files live in named volumes:

- `engram-data`: `/var/lib/engram`
- `model-cache`: `/var/lib/engram/model-cache`

The model-cache volume prevents repeated sentence-transformers downloads across
image rebuilds and restarts.

## Request Limits

Direct memory writes are capped at 15,000 characters. Larger material should
use source intake, document intake, or artifact storage so review coverage stays
explicit.

The daemon also rejects oversized HTTP request bodies before JSON dispatch.
Set `ENGRAM_DAEMON_MAX_CONTENT_LENGTH` to raise or lower that byte cap for a
private deployment. Keep it comfortably above expected source/document review
packet size; it is a transport safety limit, not the direct memory limit.

## Validate

Docker validation:

```bash
docker compose config
docker compose --profile inspector --profile mcp --profile ops config
docker compose up -d engramd-core
docker compose run --rm ops
docker compose down
```

Live smoke validation:

```bash
scripts/self_host_smoke.sh
```

The live smoke uses an isolated Compose project by default
(`engram-smoke-<timestamp>-<pid>`) so the `engram-data` and `model-cache`
volumes are not the normal development volumes. It builds the core, WebUI, MCP
thin-client, and ops images; verifies Poppler and Tesseract tools; starts
`engramd-core`; checks daemon health and Memory OS retrieval readiness; starts
the Web Inspector with temporary access/write tokens and checks `/health` through
the token-protected host port; proves the MCP thin client can reach the daemon;
runs the ops profile; then runs `docker compose down -v --remove-orphans` for
the isolated project.

Set `ENGRAM_SELF_HOST_SMOKE_PROJECT` only when a CI runner needs a deterministic
project name. The script publishes the smoke daemon on `127.0.0.1:18765` and
the smoke WebUI on `127.0.0.1:15000` by default so it can run while the normal
local daemon is still listening on `127.0.0.1:8765`. Override those ports with
`ENGRAM_SELF_HOST_SMOKE_DAEMON_PORT` and `ENGRAM_SELF_HOST_SMOKE_WEBUI_PORT`.
The script refuses to run when its chosen ports are already in use.

Native tool checks:

```bash
docker run --rm engram:local pdfinfo -v
docker run --rm engram:local pdftotext -v
docker run --rm engram:local pdfimages -v
docker run --rm engram:local pdftoppm -v
docker run --rm engram:local tesseract --version
```

## Web Inspector

The optional `web-inspector` profile is a local Memory OS review surface. Keep
it loopback-bound unless the
documented WebUI access and write token requirements are deliberately configured.
Because the container must listen on all container interfaces for Docker port
publishing, the Compose profile requires `ENGRAM_WEBUI_ACCESS_TOKEN` and
`ENGRAM_WEBUI_WRITE_TOKEN` when you run it outside the smoke script.

```bash
export ENGRAM_WEBUI_ACCESS_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export ENGRAM_WEBUI_WRITE_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
docker compose --profile inspector up -d web-inspector
```

## Backup And Portability

Treat `/var/lib/engram` as the durable self-hosted data root. It contains the
SQLite ledger, content-addressed objects, retrieval/graph indexes, receipts,
and model cache. Indexes must remain rebuildable from durable ledger/source
content, but backups should still include the full volume for fast restore.

Before moving or upgrading a self-hosted instance, run:

```bash
docker compose run --rm ops
```

For portable backup, stop writers first or run the ops check before copying the
volume. Keep backups private because they contain the durable memory ledger and
source artifacts.
