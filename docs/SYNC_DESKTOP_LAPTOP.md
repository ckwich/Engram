# Engram Desktop/Laptop Sync

Personal Hub Mode is the default online path. One always-on hub owns the live
Memory OS data root, and every other device uses authenticated thin clients.

Never sync active SQLite, WAL, LanceDB, Kuzu, Chroma, or lock files.

This document covers local-first desktop/laptop operation over loopback,
Tailscale, LAN, or file-bundle transport. It does not make the raw daemon API a
hosted multi-tenant surface. For hub exposure details, keep this runbook aligned
with `docs/HUB_MODE_TAILSCALE.md`.

## Personal Hub Mode

Use Personal Hub Mode whenever both machines can reach the same always-on Engram
owner. The hub is the single writer for the live Memory OS runtime, so normal
agent work does not require database merge logic.

Hub machine:

1. Store `ENGRAM_DATA_DIR` on a non-synced local disk or managed server volume.
2. Generate a 32+ character `ENGRAM_HUB_ACCESS_TOKEN`.
3. Start the loopback daemon owner with `python engramd.py --host 127.0.0.1 --port 8765`.
4. Start the authenticated hub gateway on Tailscale/LAN with `--hub-listen`.
5. Run `python engramd.py --doctor` and a hub status check.

Client machine:

1. Set `ENGRAM_HUB_URL` to the authenticated hub gateway URL.
2. Set the matching `ENGRAM_HUB_ACCESS_TOKEN`.
3. Register Codex MCP against `server_daemon_client.py`.
4. Prove hub mode with `memory_protocol()` or hub status.

If the hub is unreachable, clients fail closed. Standalone Local Mode requires
explicit operator intent because any accepted work on both machines creates an
offline divergence that must later be reconciled.

## Offline Divergence Reconciliation

Use reviewed sync changesets only after two standalone ledgers both accepted
work:

1. On both machines: `ensure_sync_device_identity(device_name="laptop")`.
2. On both machines: `export_local_sync_identity()`.
3. On both machines: `register_sync_peer(peer_identity_packet=packet_from_other_machine, accept=True, approved_by="operator")`.
4. Laptop to desktop: `inspect_sync_state`, `prepare_sync_changeset(peer_id="device:desktop")`, then `export_sync_changeset(plan=reviewed_plan, accept=True, approved_by="operator")`.
5. Move or push the signed-and-encrypted laptop bundle. For LAN/Tailscale
   listener transport, the bundle lands in the target sync inbox.
6. Desktop: prefer the staged-inbox operator path. Start with the cheap
   metadata view (`list_sync_inbox`) when large bundles are pending, then run
   `python engramd.py --prepare-sync-inbox-apply --sync-inbox-limit 0`,
   then `python engramd.py --apply-sync-inbox --sync-inbox-limit 0 --accept --approved-by operator`.
   This reads already-staged signed bundles from the local content store,
   prepares each apply plan with runtime-local caching, reports preparation
   timing, creates restore-grade snapshots during apply, and marks applied
   inbox bundles so reruns are idempotent. After a bundle is applied, Engram
   prunes the encrypted `.engram-sync` artifact bytes and keeps the compact
   ledger receipts, cursors, and imported-row audit trail. If older applied
   bundle artifacts are still present, run
   `python engramd.py --prune-applied-sync-inbox-artifacts --sync-inbox-limit 0`
   to preview them, then add `--accept --approved-by operator` to prune. For manual file-bundle
   transport, `prepare_sync_apply(bundle=received_bundle)` and
   `apply_sync_changeset(plan=verified_plan, accept=True, approved_by="operator")`
   remain available.
7. Desktop to laptop: repeat `inspect_sync_state`, `prepare_sync_changeset(peer_id="device:laptop")`, and `export_sync_changeset(plan=reviewed_plan, accept=True, approved_by="operator")`.
8. Move or push the signed-and-encrypted desktop bundle.
9. Laptop: `prepare_sync_apply(bundle=received_bundle)`, ensure a restore-grade runtime snapshot exists, then `apply_sync_changeset(plan=verified_plan, accept=True, approved_by="operator")`.
10. On both machines: `inspect_sync_convergence(peer_id="device:other-machine")`.
11. On both machines: run `python engramd.py --preflight`, `python engramd.py --doctor`, and `python engramd.py --smoke-test`.

Indexes are rebuilt or refreshed from the ledger after apply. Conflicts are
reviewed through sync conflict records and Knowledge PRs. Distinct rows from
both machines are imported. Same-key divergent rows are not overwritten; they
become conflicts. Private sync keys never leave the local Engram data root.

## Transport Options

- Personal hub: authenticated `ENGRAM_HUB_URL` over Tailscale/LAN for normal
  online work.
- File bundle: `export_bundle_to_file` and `import_bundle_from_file`.
- Tailscale/LAN peer changesets: start the target sync listener with
  `--sync-listen`, configure the peer URL, run `inspect_sync_peer`, then
  `push_sync_changeset`. On the target, use `list_sync_inbox`,
  `prepare_sync_inbox_apply`, and `apply_sync_inbox`, or the equivalent
  `engramd.py --apply-sync-inbox` CLI, instead of moving helper scripts
  between machines.
- Do not bind the broad raw daemon API to LAN/Tailscale. Use the authenticated
  hub gateway for ordinary clients and the sync-only listener for changesets.
  The Personal Hub gateway may expose the narrow staged-inbox apply route
  because it accepts no arbitrary bundle bytes; it only reviews and applies
  bundles already received by the signed sync listener.

## Inspector Checks

The Memory Inspector sync panel is read-only. It reports the active mode, hub
readiness, hub URL fingerprint, local device id, peer summaries, last export,
last apply, pending conflicts, last snapshot id, rebuild requirement, and a safe
next command. It must not approve sync exports, imports, conflict resolution, or
Knowledge PR merges.

Use it as a quick orientation surface, then run the underlying gates before
trusting a device sync:

```bash
python engramd.py --preflight
python engramd.py --doctor
python engramd.py --smoke-test
```
