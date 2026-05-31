# Engram Personal Hub Mode Over Tailscale/LAN

Personal Hub Mode is the default online desktop/laptop topology. One always-on machine owns the Engram data root; every other device uses authenticated thin clients over Tailscale or a trusted LAN.

Do not sync active SQLite, WAL, LanceDB, Kuzu, Chroma, graph JSON, memory JSON, lock files, or document extraction state through Dropbox, iCloud, OneDrive, Git, Syncthing, or any other file sync tool. Those files are owned by the running hub daemon.

Do not expose the raw daemon to the LAN or tailnet. Keep `engramd` loopback-first and expose only the authenticated Personal Hub gateway.

## Hub Machine

1. Store `ENGRAM_DATA_DIR` on a non-synced local disk or managed server volume.
2. Generate a 32+ character `ENGRAM_HUB_ACCESS_TOKEN`.
3. Start `engramd` on loopback for the live Memory OS data root.
4. Start the authenticated hub gateway with `--hub-listen` on the Tailscale/LAN interface.
5. For non-loopback hub binds, set `ENGRAM_HUB_LISTEN=1` and `ENGRAM_HUB_PRIVATE_NETWORK_ACK=1`.
6. For wildcard binds such as `0.0.0.0`, also set `ENGRAM_HUB_ALLOWED_HOSTS` to the accepted hub hostnames.
7. Run `python engramd.py --doctor` and a hub client status check before relying on the hub.

Example:

```bash
export ENGRAM_DATA_DIR=/Volumes/LocalData/engram
export ENGRAM_HUB_ACCESS_TOKEN='replace-with-a-32-plus-character-secret'
export ENGRAM_HUB_LISTEN=1
export ENGRAM_HUB_PRIVATE_NETWORK_ACK=1
python engramd.py --hub-listen --hub-host 100.64.0.10 --hub-port 8767
```

## Client Machine

1. Set `ENGRAM_HUB_URL` to the gateway URL.
2. Set `ENGRAM_HUB_ACCESS_TOKEN` to the same hub token.
3. Register Codex MCP against `server_daemon_client.py`.
4. Run `memory_protocol()` or `daemon_status()` to prove remote hub mode.

Example:

```bash
export ENGRAM_HUB_URL=http://engram-hub.tailnet-name.ts.net:8767
export ENGRAM_HUB_ACCESS_TOKEN='replace-with-the-hub-secret'
python install.py --hub-url "$ENGRAM_HUB_URL"
```

The installer does not persist `ENGRAM_HUB_ACCESS_TOKEN` by default. Use `--persist-hub-token` only when you explicitly want the current token written into generated MCP client config.

## Failure Behavior

If the hub is unreachable or the client token is missing, thin clients fail closed. They do not silently start a local direct-storage server and they do not open SQLite, LanceDB, Kuzu, Chroma, memory JSON, graph JSON, or document extraction state.

Use Standalone Local Mode only when intentionally choosing offline work:

```bash
python install.py --standalone-local
```

If two standalone devices both accept independent writes, use reviewed bidirectional changeset reconciliation after sync foundations are installed. Personal Hub Mode does not need conflict reconciliation while all writes go to the hub.

## Windows Hub Watchdog

On a Windows hub, install the scheduled watchdog task after the repo and venv are ready:

```powershell
.\scripts\install_engram_watchdog_task.ps1
```

The task launches through `scripts\run_engram_watchdog_hidden.vbs`, which runs
`scripts\watch_engram_hub.ps1` without opening a visible console window, about
once per minute while the Windows user session is active. It is intentionally
local-only: it checks loopback daemon health and local listening sockets for the
hub/sync ports. It does not ping peer devices, call the Mac, or probe public
URLs, so it should not add periodic network chatter while another VPN is active.
If the daemon or listeners are unhealthy, it restarts `engramd.py` with the hub
gateway, sync listener, and `ENGRAM_DAEMON_MAX_CONTENT_LENGTH=104857600`.

The watchdog writes state and logs under `%LOCALAPPDATA%\Engram\watchdog` and
`%LOCALAPPDATA%\Engram\logs`. To pause it temporarily, create:

```powershell
New-Item -ItemType File "$env:LOCALAPPDATA\Engram\watchdog\watchdog.pause" -Force
```

Delete that file to resume.
