"""Shared guards for raw local service bind addresses."""
from __future__ import annotations

import os

from core.hub_auth import load_hub_access_token

PUBLIC_BIND_ALLOW_ENV = "ENGRAM_ALLOW_PUBLIC_BIND"
HUB_LISTEN_ENV = "ENGRAM_HUB_LISTEN"
HUB_PRIVATE_NETWORK_ACK_ENV = "ENGRAM_HUB_PRIVATE_NETWORK_ACK"
HUB_ALLOWED_HOSTS_ENV = "ENGRAM_HUB_ALLOWED_HOSTS"
SYNC_LISTEN_ENV = "ENGRAM_SYNC_LISTEN"
SYNC_PRIVATE_NETWORK_ACK_ENV = "ENGRAM_SYNC_PRIVATE_NETWORK_ACK"
SYNC_ALLOWED_HOSTS_ENV = "ENGRAM_SYNC_ALLOWED_HOSTS"
PUBLIC_BIND_ALLOW_VALUES = {
    "loopback-published",
    "loopback_publish",
    "trusted-proxy",
    "trusted_proxy",
}


class PublicBindDenied(ValueError):
    """Raised when a raw Engram surface is about to bind publicly without acknowledgement."""


def is_loopback_host(host: str | None) -> bool:
    normalized = str(host or "").strip().lower().strip("[]")
    return normalized in {"localhost", "127.0.0.1", "::1"}


def is_wildcard_host(host: str | None) -> bool:
    normalized = str(host or "").strip().lower().strip("[]")
    return normalized in {"", "0.0.0.0", "::"}  # nosec B104


def public_bind_allowed() -> bool:
    value = os.environ.get(PUBLIC_BIND_ALLOW_ENV, "").strip().lower()
    return value in PUBLIC_BIND_ALLOW_VALUES


def _trusted_proxy_allowed_from(source: dict[str, str]) -> bool:
    value = str(source.get(PUBLIC_BIND_ALLOW_ENV) or "").strip().lower()
    return value in {"trusted-proxy", "trusted_proxy"}


def validate_raw_service_bind(host: str | None, *, surface: str) -> None:
    """Fail closed before binding unauthenticated raw service surfaces publicly."""
    if is_loopback_host(host) or public_bind_allowed():
        return
    normalized = str(host or "").strip() or "<all interfaces>"
    raise PublicBindDenied(
        f"{surface} refuses to bind to non-loopback host {normalized!r}. "
        f"Set {PUBLIC_BIND_ALLOW_ENV}=loopback-published only when an authenticated "
        "private gateway or loopback-only port publish is enforcing the public boundary."
    )


def validate_hub_gateway_bind(
    host: str | None,
    *,
    env: dict[str, str] | None = None,
) -> dict[str, object]:
    """Validate an authenticated Personal Hub bind before starting its listener."""
    source = env if env is not None else os.environ
    normalized = str(host or "").strip() or "127.0.0.1"
    token_result = load_hub_access_token(source)
    if token_result.get("status") != "ready":
        return {
            "status": "policy_denied",
            "error": token_result.get("error"),
            "host": normalized,
            "safe_to_bind": False,
        }
    if is_loopback_host(normalized):
        return {
            "status": "ready",
            "host": normalized,
            "safe_to_bind": True,
            "token_fingerprint": token_result.get("token_fingerprint"),
        }
    if str(source.get(HUB_LISTEN_ENV) or "").strip().lower() not in {"1", "true", "yes", "on"}:
        return {
            "status": "policy_denied",
            "host": normalized,
            "safe_to_bind": False,
            "error": {"code": "hub_listen_not_acknowledged"},
        }
    if str(source.get(HUB_PRIVATE_NETWORK_ACK_ENV) or "").strip().lower() not in {"1", "true", "yes", "on"}:
        return {
            "status": "policy_denied",
            "host": normalized,
            "safe_to_bind": False,
            "error": {"code": "hub_private_network_ack_required"},
        }
    if is_wildcard_host(normalized) and not str(source.get(HUB_ALLOWED_HOSTS_ENV) or "").strip():
        return {
            "status": "policy_denied",
            "host": normalized,
            "safe_to_bind": False,
            "error": {"code": "hub_allowed_hosts_required"},
        }
    return {
        "status": "ready",
        "host": normalized,
        "safe_to_bind": True,
        "token_fingerprint": token_result.get("token_fingerprint"),
    }


def validate_sync_listener_bind(
    host: str | None,
    *,
    env: dict[str, str] | None = None,
) -> dict[str, object]:
    """Validate a signed-peer sync listener bind before starting its sidecar."""
    source = env if env is not None else os.environ
    normalized = str(host or "").strip() or "127.0.0.1"
    if is_loopback_host(normalized):
        return {
            "status": "ready",
            "host": normalized,
            "safe_to_bind": True,
        }
    if _trusted_proxy_allowed_from(source):
        if is_wildcard_host(normalized) and not str(source.get(SYNC_ALLOWED_HOSTS_ENV) or "").strip():
            return {
                "status": "policy_denied",
                "host": normalized,
                "safe_to_bind": False,
                "error": {"code": "sync_allowed_hosts_required"},
            }
        return {
            "status": "ready",
            "host": normalized,
            "safe_to_bind": True,
        }
    if str(source.get(SYNC_LISTEN_ENV) or "").strip().lower() not in {"1", "true", "yes", "on"}:
        return {
            "status": "policy_denied",
            "host": normalized,
            "safe_to_bind": False,
            "error": {"code": "sync_listen_not_acknowledged"},
        }
    if str(source.get(SYNC_PRIVATE_NETWORK_ACK_ENV) or "").strip().lower() not in {"1", "true", "yes", "on"}:
        return {
            "status": "policy_denied",
            "host": normalized,
            "safe_to_bind": False,
            "error": {"code": "sync_private_network_ack_required"},
        }
    if is_wildcard_host(normalized) and not str(source.get(SYNC_ALLOWED_HOSTS_ENV) or "").strip():
        return {
            "status": "policy_denied",
            "host": normalized,
            "safe_to_bind": False,
            "error": {"code": "sync_allowed_hosts_required"},
        }
    return {
        "status": "ready",
        "host": normalized,
        "safe_to_bind": True,
    }
