# Remote WebUI Guide

Engram's WebUI is loopback-first. The safe default is still:

```powershell
python webui.py
```

That binds to `127.0.0.1:5000` and keeps local use frictionless. Only expose the dashboard deliberately, preferably through Tailscale, a VPN, or a trusted reverse proxy.

## Tailscale / LAN Checklist

1. Generate two strong tokens:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

2. Set the remote WebUI environment variables:

```powershell
set ENGRAM_WEBUI_HOST=0.0.0.0
set ENGRAM_WEBUI_PORT=5000
set ENGRAM_WEBUI_ALLOWED_HOSTS=your-device.tailnet-name.ts.net
set ENGRAM_WEBUI_ACCESS_TOKEN=paste-generated-read-token
set ENGRAM_WEBUI_WRITE_TOKEN=paste-generated-write-token
```

3. Start the dashboard:

```powershell
python webui.py
```

4. Check the backend:

```powershell
python server.py --health
```

## What Each Setting Does

| Variable | Required When | Purpose |
|---|---|---|
| `ENGRAM_WEBUI_HOST` | Exposing beyond loopback | Bind address. Use `0.0.0.0` only when a network control layer is present. |
| `ENGRAM_WEBUI_PORT` | Optional | Dashboard port. Defaults to `5000`. |
| `ENGRAM_WEBUI_ALLOWED_HOSTS` | Wildcard binds such as `0.0.0.0` or `::` | Comma-separated Host headers the dashboard will accept. |
| `ENGRAM_WEBUI_ACCESS_TOKEN` | Any non-loopback exposure | Unlocks dashboard/read API access through login or `X-Engram-Access-Token`. |
| `ENGRAM_WEBUI_WRITE_TOKEN` | Any non-loopback exposure | Required for create, update, delete, and review calls through `X-Engram-Write-Token`. |
| `ENGRAM_WEBUI_COOKIE_SECURE` | HTTPS | Set to `1` when serving through HTTPS. |
| `ENGRAM_WEBUI_TRUSTED_ORIGINS` | Separate trusted frontend origins only | Allows explicit cross-origin mutation requests. Leave unset for the built-in dashboard. |

## Safety Notes

- Tokens must be at least 32 characters by default.
- The dashboard never renders token values, only whether each token is configured.
- Non-loopback clients trigger exposed-mode checks even if the process was launched with the default loopback host.
- Public wildcard binds fail closed unless `ENGRAM_WEBUI_ALLOWED_HOSTS` is configured.
- Do not put Engram directly on the public internet without a hardened network/auth layer in front of it.
