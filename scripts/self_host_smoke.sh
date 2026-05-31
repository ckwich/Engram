#!/usr/bin/env bash
set -euo pipefail

project_name="${ENGRAM_SELF_HOST_SMOKE_PROJECT:-engram-smoke-$(date +%s)-$$}"
export ENGRAM_DAEMON_HOST_PORT="${ENGRAM_SELF_HOST_SMOKE_DAEMON_PORT:-18765}"
export ENGRAM_WEBUI_HOST_PORT="${ENGRAM_SELF_HOST_SMOKE_WEBUI_PORT:-15000}"
daemon_url="http://127.0.0.1:${ENGRAM_DAEMON_HOST_PORT}/health"
webui_url="http://127.0.0.1:${ENGRAM_WEBUI_HOST_PORT}/health"

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "$command_name is required for the self-host smoke check" >&2
    exit 1
  fi
}

docker_compose() {
  docker compose -p "$project_name" "$@"
}

port_open() {
  local host="$1"
  local port="$2"
  python - "$host" "$port" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.settimeout(0.2)
    sys.exit(0 if sock.connect_ex((host, port)) == 0 else 1)
PY
}

require_port_free() {
  local host="$1"
  local port="$2"
  if port_open "$host" "$port"; then
    echo "$host:$port is already in use; stop the local service before live Docker smoke" >&2
    exit 2
  fi
}

webui_access_token() {
  python - <<'PY'
import secrets

print(secrets.token_urlsafe(32))
PY
}

fetch_health() {
  local url="$1"
  if [[ "$url" == "$webui_url" ]]; then
    curl -fsS -H "X-Engram-Access-Token: ${ENGRAM_WEBUI_ACCESS_TOKEN}" "$url"
  else
    curl -fsS "$url"
  fi
}

wait_for_host_url() {
  local url="$1"
  local label="$2"
  for _ in $(seq 1 90); do
    if fetch_health "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "timed out waiting for $label at $url" >&2
  return 1
}

assert_daemon_health() {
  local payload
  payload="$(curl -fsS "$daemon_url")"
  python - "$payload" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
serving = payload.get("serving") if isinstance(payload.get("serving"), dict) else {}
if payload.get("status") != "ok":
    raise SystemExit(f"daemon status was not ok: {payload}")
if serving.get("memory_os_retrieval_ready") is not True:
    raise SystemExit(f"memory os retrieval was not ready: {serving}")
print("Daemon health is ok and Memory OS retrieval is ready")
PY
}

assert_webui_health() {
  local payload
  payload="$(fetch_health "$webui_url")"
  python - "$payload" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
if payload.get("status") != "ok":
    raise SystemExit(f"web inspector status was not ok: {payload}")
print("WebUI health is ok")
PY
}

cleanup() {
  docker compose -p "$project_name" \
    --profile inspector \
    --profile mcp \
    --profile ops \
    down -v --remove-orphans >/dev/null 2>&1 || true
}

on_signal() {
  cleanup
  exit 130
}

require_command docker
require_command python
require_command curl

if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose is required for the self-host smoke check" >&2
  exit 1
fi

require_port_free 127.0.0.1 "$ENGRAM_DAEMON_HOST_PORT"
require_port_free 127.0.0.1 "$ENGRAM_WEBUI_HOST_PORT"

export ENGRAM_WEBUI_ACCESS_TOKEN="${ENGRAM_WEBUI_ACCESS_TOKEN:-$(webui_access_token)}"
export ENGRAM_WEBUI_WRITE_TOKEN="${ENGRAM_WEBUI_WRITE_TOKEN:-$(webui_access_token)}"
export ENGRAM_WEBUI_ALLOWED_HOSTS="${ENGRAM_WEBUI_ALLOWED_HOSTS:-127.0.0.1,localhost}"
export ENGRAM_WEBUI_TRUSTED_ORIGINS="${ENGRAM_WEBUI_TRUSTED_ORIGINS:-http://127.0.0.1:${ENGRAM_WEBUI_HOST_PORT},http://localhost:${ENGRAM_WEBUI_HOST_PORT}}"

trap cleanup EXIT
trap on_signal INT TERM

docker_compose --profile inspector --profile mcp --profile ops config >/dev/null
docker_compose --profile inspector --profile mcp --profile ops build \
  engramd-core web-inspector mcp-gateway ops

docker run --rm engram:local pdfinfo -v >/dev/null
docker run --rm engram:local pdftotext -v >/dev/null
docker run --rm engram:local pdfimages -v >/dev/null
docker run --rm engram:local pdftoppm -v >/dev/null
docker run --rm engram:local tesseract --version >/dev/null

docker_compose up -d engramd-core
docker volume inspect "${project_name}_engram-data" >/dev/null
docker volume inspect "${project_name}_model-cache" >/dev/null
docker_compose exec -T engramd-core python - <<'PY'
import os
from pathlib import Path

root = os.environ.get("ENGRAM_DATA_DIR")
if root != "/var/lib/engram":
    raise SystemExit(f"unexpected ENGRAM_DATA_DIR: {root}")
if not Path(root).is_dir():
    raise SystemExit(f"data root does not exist: {root}")
print("Isolated container data root is mounted at /var/lib/engram")
PY

wait_for_host_url "$daemon_url" "engramd-core"
assert_daemon_health

docker_compose --profile inspector up -d web-inspector
wait_for_host_url "$webui_url" "web-inspector"
assert_webui_health

docker_compose --profile mcp run --rm mcp-gateway python scripts/smoke_mcp_thin_client.py

docker_compose --profile ops run --rm ops
echo "Self-host live smoke passed for Compose project: $project_name"
