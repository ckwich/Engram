"""Signed peer request helpers for LAN/Tailscale Memory OS sync transport."""
from __future__ import annotations

import secrets
import base64
import ipaddress
import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib import error, request
from urllib.parse import urlparse

from core.memory_os._records import hash_payload, now_iso, read_record, stable_id, upsert_record
from core.memory_os.sync_crypto import load_local_sync_keys, sign_payload, verify_payload
from core.memory_os.sync_identity import LOCAL_DEVICE_RECORD_ID, export_local_sync_identity
from core.memory_os.sync_transport import register_sync_transport_receipt
from core.memory_os.transactions import MemoryTransactionService


SYNC_PEER_TRANSPORT_SCHEMA_VERSION = "2026-05-26.sync-peer-transport.v1"
MAX_SIGNATURE_SKEW_SECONDS = 300
SYNC_PEER_URL_ACK_ENV = "ENGRAM_SYNC_PRIVATE_NETWORK_ACK"
PUBLIC_BIND_ALLOW_ENV = "ENGRAM_ALLOW_PUBLIC_BIND"
MAX_SYNC_PEER_RESPONSE_BYTES = 1024 * 1024


class _NoSyncPeerRedirectHandler(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise error.HTTPError(req.full_url, code, "sync_peer_redirect_not_allowed", headers, fp)


def build_sync_challenge(
    *,
    method: str,
    route: str,
    nonce: str,
    timestamp: str,
    body_hash: str,
    source_device_id: str,
    target_device_id: str,
) -> dict[str, Any]:
    """Build the canonical request envelope covered by a peer signature."""
    return {
        "schema_version": SYNC_PEER_TRANSPORT_SCHEMA_VERSION,
        "method": str(method or "").upper(),
        "route": str(route or "").split("?", 1)[0],
        "nonce": str(nonce or ""),
        "timestamp": str(timestamp or ""),
        "body_hash": str(body_hash or ""),
        "source_device_id": str(source_device_id or ""),
        "target_device_id": str(target_device_id or ""),
    }


def build_signed_sync_request(
    runtime: Any,
    *,
    target_device_id: str,
    method: str,
    route: str,
    body_payload: dict[str, Any],
) -> dict[str, Any]:
    """Build signed metadata for one sync-only peer request."""
    local = export_local_sync_identity(runtime.ledger)
    nonce = secrets.token_urlsafe(24)
    timestamp = now_iso()
    body_hash = hash_payload(body_payload if isinstance(body_payload, dict) else {})
    challenge = build_sync_challenge(
        method=method,
        route=route,
        nonce=nonce,
        timestamp=timestamp,
        body_hash=body_hash,
        source_device_id=str(local["device_id"]),
        target_device_id=str(target_device_id or ""),
    )
    keys = load_local_sync_keys(runtime.root / "keys")
    return {
        "peer_id": local["device_id"],
        "target_device_id": str(target_device_id or ""),
        "nonce": nonce,
        "timestamp": timestamp,
        "body_hash": body_hash,
        "signature": sign_payload(_canonical_json_bytes(challenge), keys.signing_private_key),
    }


def verify_sync_request_signature(
    runtime: Any,
    *,
    peer_id: str,
    nonce: str,
    timestamp: str,
    body_hash: str,
    signature: str,
    method: str,
    route: str,
    target_device_id: str,
    record_nonce: bool = True,
) -> dict[str, Any]:
    """Verify one signed peer request and record nonce use for replay defense."""
    normalized_peer_id = _text(peer_id)
    if not normalized_peer_id:
        return _policy_denied("sync_peer_signature_required")
    peer = _active_peer_record(runtime, normalized_peer_id)
    if peer is None:
        return _policy_denied("sync_peer_not_registered")
    if not all(_text(value) for value in (nonce, timestamp, body_hash, signature, target_device_id)):
        return _policy_denied("sync_peer_signature_required")
    local = read_record(runtime.ledger, "sync_devices", LOCAL_DEVICE_RECORD_ID)
    if not isinstance(local, dict) or str(local.get("device_id") or "") != str(target_device_id):
        return _policy_denied("sync_target_mismatch")
    if not _timestamp_is_fresh(str(timestamp)):
        return _policy_denied("sync_timestamp_out_of_range")
    nonce_id = stable_id(
        "sync_nonce",
        {"peer_id": normalized_peer_id, "nonce": str(nonce), "route": str(route or "")},
    )
    if read_record(runtime.ledger, "sync_transport_receipts", nonce_id) is not None:
        return _policy_denied("sync_nonce_replay")
    challenge = build_sync_challenge(
        method=method,
        route=route,
        nonce=str(nonce),
        timestamp=str(timestamp),
        body_hash=str(body_hash),
        source_device_id=normalized_peer_id,
        target_device_id=str(target_device_id),
    )
    if not verify_payload(_canonical_json_bytes(challenge), str(signature), str(peer["signing_public_key"])):
        return _policy_denied("sync_signature_invalid")
    if not record_nonce:
        return {
            "schema_version": SYNC_PEER_TRANSPORT_SCHEMA_VERSION,
            "status": "ok",
            "write_performed": False,
            "receipt_id": nonce_id,
            "peer_id": normalized_peer_id,
            "error": None,
        }
    recorded = record_sync_request_nonce(
        runtime,
        peer_id=normalized_peer_id,
        nonce=str(nonce),
        route=str(route or ""),
        body_hash=str(body_hash),
    )
    if recorded.get("status") != "ok":
        return recorded
    return recorded


def record_sync_request_nonce(
    runtime: Any,
    *,
    peer_id: str,
    nonce: str,
    route: str,
    body_hash: str,
) -> dict[str, Any]:
    """Record one verified sync request nonce after all request checks pass."""
    nonce_id = stable_id(
        "sync_nonce",
        {"peer_id": str(peer_id), "nonce": str(nonce), "route": str(route or "")},
    )
    if read_record(runtime.ledger, "sync_transport_receipts", nonce_id) is not None:
        return _policy_denied("sync_nonce_replay")
    now = now_iso()
    record = {
        "schema_version": SYNC_PEER_TRANSPORT_SCHEMA_VERSION,
        "record_type": "sync_nonce",
        "receipt_id": nonce_id,
        "peer_id": str(peer_id),
        "nonce": str(nonce),
        "route": str(route or "").split("?", 1)[0],
        "body_hash": str(body_hash),
        "status": "verified",
        "apply_performed": False,
        "created_at": now,
        "updated_at": now,
        "sync_policy": "local_only",
    }
    upsert_record(runtime.ledger, "sync_transport_receipts", nonce_id, record)
    return {
        "schema_version": SYNC_PEER_TRANSPORT_SCHEMA_VERSION,
        "status": "ok",
        "write_performed": True,
        "receipt_id": nonce_id,
        "peer_id": str(peer_id),
        "error": None,
    }


def configure_sync_peer_transport(
    runtime: Any,
    *,
    peer_id: str,
    url: str,
    mode: str = "manual",
    allow_pull: bool = False,
    accept: bool,
    approved_by: str | None,
) -> dict[str, Any]:
    """Attach reviewed transport coordinates to a registered sync peer."""
    reviewer = _text(approved_by)
    normalized_peer_id = _text(peer_id)
    normalized_url = _text(url)
    normalized_mode = _text(mode) or "manual"
    if normalized_mode not in {"manual", "push", "pull", "bidirectional"}:
        return _policy_denied("invalid_sync_transport_mode")
    if not accept or not reviewer:
        return _policy_denied("acceptance_required")
    if not normalized_peer_id or not normalized_url:
        return _policy_denied("peer_transport_required")
    if not _valid_peer_url(normalized_url):
        return _policy_denied("invalid_sync_peer_url")
    trust = _peer_url_trust(normalized_url)
    if trust.get("status") != "ready":
        return _policy_denied(str((trust.get("error") or {}).get("code") or "sync_peer_url_not_private"))
    peer = _active_peer_record(runtime, normalized_peer_id)
    if peer is None:
        return _policy_denied("sync_peer_not_registered")
    now = now_iso()
    updated = {
        **peer,
        "transport": {
            "url": normalized_url,
            "mode": normalized_mode,
            "allow_pull": bool(allow_pull),
            "url_trust": trust,
            "updated_at": now,
            "approved_by": reviewer,
        },
        "updated_at": now,
    }
    record_id = f"sync_device:peer:{normalized_peer_id}"
    upsert_record(runtime.ledger, "sync_devices", record_id, updated)
    transaction = MemoryTransactionService(runtime.ledger).promote(
        operation_kind="sync_peer_transport_configure",
        proposed_writes=[{"table": "sync_devices", "id": record_id}],
        idempotency_key=f"sync_peer_transport_configure:{normalized_peer_id}:{hash_payload(updated['transport'])}",
        affected_refs=[{"table": "sync_devices", "id": record_id}],
    )
    return {
        "schema_version": SYNC_PEER_TRANSPORT_SCHEMA_VERSION,
        "status": "configured",
        "write_performed": True,
        "peer": _public_peer(updated),
        "transaction": transaction,
        "error": None,
    }


def inspect_sync_peer(runtime: Any, *, peer_id: str) -> dict[str, Any]:
    """Inspect one registered sync peer and its transport coordinates."""
    normalized_peer_id = _text(peer_id)
    peer = _active_peer_record(runtime, normalized_peer_id)
    if peer is None:
        return _policy_denied("sync_peer_not_registered")
    return {
        "schema_version": SYNC_PEER_TRANSPORT_SCHEMA_VERSION,
        "status": "ok",
        "write_performed": False,
        "peer": _public_peer(peer),
        "error": None,
    }


def push_sync_bundle(
    runtime: Any,
    peer: dict[str, Any],
    bundle_bytes: bytes,
    *,
    approved_by: str | None,
    artifact_id: str | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Push encrypted bundle bytes to a peer's sync-only listener."""
    if not _text(approved_by):
        return _policy_denied("acceptance_required")
    if not isinstance(peer, dict) or not isinstance(bundle_bytes, bytes):
        return _policy_denied("invalid_push_request")
    transport = peer.get("transport") if isinstance(peer.get("transport"), dict) else {}
    peer_url = _text(transport.get("url"))
    if not peer_url:
        return _policy_denied("sync_peer_transport_not_configured")
    if not _valid_peer_url(peer_url):
        return _policy_denied("invalid_sync_peer_url")
    trust = _peer_url_trust(peer_url)
    if trust.get("status") != "ready":
        return _policy_denied(str((trust.get("error") or {}).get("code") or "sync_peer_url_not_private"))
    bundle_b64 = base64.urlsafe_b64encode(bundle_bytes).decode("ascii")
    route = "/v1/sync/inbox"
    signed = build_signed_sync_request(
        runtime,
        target_device_id=str(peer.get("device_id") or ""),
        method="POST",
        route=route,
        body_payload={"bundle": bundle_b64},
    )
    payload = {**signed, "bundle": bundle_b64}
    target = peer_url.rstrip("/") + route
    try:
        opener = request.build_opener(_NoSyncPeerRedirectHandler)
        with opener.open(  # nosec B310
            request.Request(
                target,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                method="POST",
            ),
            timeout=timeout,
        ) as response:
            raw = _read_limited_response(response).decode("utf-8")
            body = json.loads(raw)
            http_status = int(response.status)
    except error.HTTPError as exc:
        http_status = int(exc.code)
        if 300 <= http_status < 400:
            body = {
                "error": {
                    "code": "sync_peer_redirect_not_allowed",
                    "message": "Sync peer redirects are not followed.",
                }
            }
        else:
            raw = _read_limited_response(exc).decode("utf-8", errors="replace")
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = {"error": {"code": "sync_peer_http_error", "message": raw}}
    except Exception as exc:
        return {
            "schema_version": SYNC_PEER_TRANSPORT_SCHEMA_VERSION,
            "status": "unavailable",
            "write_performed": False,
            "peer_id": peer.get("device_id"),
            "bundle_size_bytes": len(bundle_bytes),
            "error": {"code": "sync_peer_push_failed", "message": str(exc)},
        }
    status = "pushed" if 200 <= http_status < 300 else "peer_rejected"
    receipt = register_sync_transport_receipt(
        runtime,
        {
            "transport_type": "sync_peer",
            "peer_id": peer.get("device_id"),
            "artifact_id": artifact_id,
            "direction": "outbound",
            "status": status,
            "metadata": {
                "url": peer_url,
                "http_status": http_status,
                "route": route,
            },
        },
    )
    return {
        "schema_version": SYNC_PEER_TRANSPORT_SCHEMA_VERSION,
        "status": status,
        "write_performed": bool(receipt.get("write_performed")),
        "peer_id": peer.get("device_id"),
        "bundle_size_bytes": len(bundle_bytes),
        "http_status": http_status,
        "transport_receipt": receipt,
        "peer_response": body,
        "error": None if 200 <= http_status < 300 else body.get("error"),
    }


def push_sync_changeset(
    runtime: Any,
    *,
    peer_id: str,
    accept: bool,
    approved_by: str | None,
) -> dict[str, Any]:
    """Prepare, export, and push a reviewed encrypted changeset to a configured peer."""
    reviewer = _text(approved_by)
    normalized_peer_id = _text(peer_id)
    if not accept or not reviewer:
        return _policy_denied("acceptance_required")
    if not normalized_peer_id:
        return _policy_denied("peer_id_required")
    peer_result = inspect_sync_peer(runtime, peer_id=normalized_peer_id)
    if peer_result.get("status") != "ok":
        return peer_result
    plan = runtime.prepare_sync_changeset(peer_id=normalized_peer_id)
    if plan.get("status") != "ready":
        return {
            "schema_version": SYNC_PEER_TRANSPORT_SCHEMA_VERSION,
            "status": "not_ready",
            "write_performed": False,
            "plan": plan,
            "error": plan.get("error") or {"code": "sync_changeset_not_ready"},
        }
    exported = runtime.export_sync_changeset(
        plan=plan,
        accept=True,
        approved_by=reviewer,
    )
    if exported.get("status") != "exported":
        return {
            "schema_version": SYNC_PEER_TRANSPORT_SCHEMA_VERSION,
            "status": "not_ready",
            "write_performed": bool(exported.get("write_performed")),
            "export": exported,
            "error": exported.get("error") or {"code": "sync_export_failed"},
        }
    bundle_bytes = runtime.content_store.read_bytes(str(exported["artifact_id"]))
    pushed = push_sync_bundle(
        runtime,
        peer_result["peer"],
        bundle_bytes,
        approved_by=reviewer,
        artifact_id=str(exported["artifact_id"]),
    )
    return {
        "schema_version": SYNC_PEER_TRANSPORT_SCHEMA_VERSION,
        "status": pushed.get("status"),
        "write_performed": bool(exported.get("write_performed")),
        "peer_id": normalized_peer_id,
        "plan": plan,
        "export": exported,
        "transport": pushed,
        "error": pushed.get("error"),
    }


def pull_sync_bundle(peer: dict[str, Any], cursor: dict[str, Any] | None, *, approved_by: str | None) -> dict[str, Any]:
    """Placeholder packet for pull transport, disabled unless a peer opts in."""
    if not _text(approved_by):
        return _policy_denied("acceptance_required")
    transport = peer.get("transport") if isinstance(peer, dict) else {}
    if not isinstance(transport, dict) or transport.get("allow_pull") is not True:
        return _policy_denied("sync_pull_not_allowed")
    return {
        "schema_version": SYNC_PEER_TRANSPORT_SCHEMA_VERSION,
        "status": "not_implemented",
        "write_performed": False,
        "cursor": cursor or {},
        "error": {"code": "transport_client_not_configured"},
    }


def _active_peer_record(runtime: Any, peer_id: str | None) -> dict[str, Any] | None:
    if not peer_id:
        return None
    record = read_record(runtime.ledger, "sync_devices", f"sync_device:peer:{peer_id}")
    if not record or record.get("status") != "active" or record.get("sync_allowed") is not True:
        return None
    return record


def _public_peer(peer: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in peer.items()
        if "private" not in str(key).lower()
    }


def _timestamp_is_fresh(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    delta = abs((datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())
    return delta <= MAX_SIGNATURE_SKEW_SECONDS


def _valid_peer_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    if parsed.username or parsed.password or "@" in parsed.netloc:
        return False
    if parsed.params or parsed.query or parsed.fragment:
        return False
    return parsed.path in {"", "/"}


def _read_limited_response(handle: Any, *, limit: int = MAX_SYNC_PEER_RESPONSE_BYTES) -> bytes:
    raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("sync_peer_response_too_large")
    return raw


def _peer_url_trust(value: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    source = env if env is not None else os.environ
    parsed = urlparse(value)
    host = str(parsed.hostname or "").strip().lower().rstrip(".")
    if _host_is_private_or_tailscale(host):
        return {
            "status": "ready",
            "classification": "private_network",
            "host": host,
            "ack_required": False,
        }
    if _public_peer_acknowledged(source):
        return {
            "status": "ready",
            "classification": "public_or_proxy_acknowledged",
            "host": host,
            "ack_required": True,
        }
    return {
        "status": "policy_denied",
        "classification": "public",
        "host": host,
        "ack_required": True,
        "error": {"code": "sync_peer_url_private_ack_required"},
    }


def _host_is_private_or_tailscale(host: str) -> bool:
    if host in {"localhost"} or host.endswith(".localhost") or host.endswith(".ts.net"):
        return True
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    tailscale_cgnat = ipaddress.ip_network("100.64.0.0/10")
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address in tailscale_cgnat
    )


def _public_peer_acknowledged(source: dict[str, str]) -> bool:
    if str(source.get(PUBLIC_BIND_ALLOW_ENV) or "").strip().lower() in {"trusted-proxy", "trusted_proxy"}:
        return True
    return str(source.get(SYNC_PEER_URL_ACK_ENV) or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _canonical_json_bytes(payload: Any) -> bytes:
    import json

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _policy_denied(code: str) -> dict[str, Any]:
    return {
        "schema_version": SYNC_PEER_TRANSPORT_SCHEMA_VERSION,
        "status": "policy_denied",
        "write_performed": False,
        "error": {"code": code},
    }


def _text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
