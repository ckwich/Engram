"""Client-side Personal Hub Mode configuration helpers."""
from __future__ import annotations

import os
import ipaddress
from typing import Any
from urllib.parse import urlparse, urlunparse

from core.hub_auth import HUB_ACCESS_TOKEN_ENV, load_hub_access_token, token_fingerprint


HUB_URL_ENV = "ENGRAM_HUB_URL"
HUB_URL_ALLOWED_SCHEMES = frozenset({"http", "https"})
HUB_INSECURE_HTTP_OK_ENV = "ENGRAM_HUB_INSECURE_HTTP_OK"


def normalize_hub_url(value: str | None) -> str:
    """Return a safe hub base URL or raise ValueError with a policy code."""
    parsed = _parse_hub_url(value)
    error = parsed.get("error")
    if error:
        raise ValueError(str(error.get("code") or "hub_url_invalid"))
    return str(parsed.get("hub_url") or "")


def read_hub_client_config(env: dict[str, str] | None = None) -> dict[str, Any]:
    """Read hub client settings from the environment."""
    source = env if env is not None else os.environ
    hub_url_result = _parse_hub_url(source.get(HUB_URL_ENV), env=source)
    token = str(source.get(HUB_ACCESS_TOKEN_ENV) or "").strip()
    return {
        "hub_url": hub_url_result.get("hub_url"),
        "hub_configured": bool(hub_url_result.get("configured")),
        "hub_url_error": hub_url_result.get("error"),
        "access_token": token,
        "token_fingerprint": token_fingerprint(token) if token else None,
    }


def validate_hub_client_config(config: dict[str, Any]) -> dict[str, Any]:
    """Validate hub client settings without returning raw secrets."""
    if not bool(config.get("hub_configured")):
        return {"status": "not_configured", "mode": "loopback", "error": None}
    if config.get("hub_url_error"):
        return {
            "status": "policy_denied",
            "mode": "hub",
            "hub_url": None,
            "token_fingerprint": config.get("token_fingerprint"),
            "error": config.get("hub_url_error"),
        }
    token_result = load_hub_access_token({HUB_ACCESS_TOKEN_ENV: str(config.get("access_token") or "")})
    if token_result.get("status") != "ready":
        return {
            "status": token_result.get("status"),
            "mode": "hub",
            "hub_url": config.get("hub_url"),
            "token_fingerprint": config.get("token_fingerprint"),
            "required_min_length": token_result.get("required_min_length"),
            "error": token_result.get("error"),
        }
    return {
        "status": "ready",
        "mode": "hub",
        "hub_url": config.get("hub_url"),
        "token_fingerprint": token_result.get("token_fingerprint"),
        "error": None,
    }


def build_hub_headers(config: dict[str, Any]) -> dict[str, str]:
    """Build outbound hub headers. This is the only helper that returns the token."""
    token = str(config.get("access_token") or "").strip()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def describe_hub_mode(config: dict[str, Any]) -> dict[str, Any]:
    """Return non-secret client-mode diagnostics."""
    if bool(config.get("hub_configured")):
        return {
            "mode": "hub",
            "hub_url": config.get("hub_url") if not config.get("hub_url_error") else None,
            "token_fingerprint": config.get("token_fingerprint"),
            "single_owner_rule": "Remote clients use the authenticated hub and never open local Engram storage.",
        }
    return {
        "mode": "loopback",
        "hub_url": None,
        "token_fingerprint": None,
        "single_owner_rule": "Local thin clients use the loopback daemon owner.",
    }


def _parse_hub_url(value: str | None, *, env: dict[str, str] | None = None) -> dict[str, Any]:
    raw = str(value or "").strip()
    if not raw:
        return {"configured": False, "hub_url": None, "error": None}
    parsed = urlparse(raw)
    if parsed.scheme.lower() not in HUB_URL_ALLOWED_SCHEMES or not parsed.netloc:
        return {
            "configured": True,
            "hub_url": None,
            "error": {"code": "hub_url_invalid"},
        }
    if parsed.username or parsed.password or "@" in parsed.netloc:
        return {
            "configured": True,
            "hub_url": None,
            "error": {"code": "hub_url_must_not_include_credentials"},
        }
    if parsed.params or parsed.query or parsed.fragment:
        return {
            "configured": True,
            "hub_url": None,
            "error": {"code": "hub_url_must_not_include_query_or_fragment"},
        }
    if parsed.path not in {"", "/"}:
        return {
            "configured": True,
            "hub_url": None,
            "error": {"code": "hub_url_must_not_include_path"},
        }
    cleartext_error = _cleartext_http_policy_error(parsed, env=env)
    if cleartext_error is not None:
        return {
            "configured": True,
            "hub_url": None,
            "error": cleartext_error,
        }
    normalized = urlunparse((parsed.scheme.lower(), parsed.netloc, "", "", "", ""))
    return {"configured": True, "hub_url": normalized.rstrip("/"), "error": None}


def _cleartext_http_policy_error(parsed: Any, *, env: dict[str, str] | None) -> dict[str, str] | None:
    if parsed.scheme.lower() != "http":
        return None
    source = env if env is not None else os.environ
    if _env_truthy(source.get(HUB_INSECURE_HTTP_OK_ENV)):
        return None
    host = str(parsed.hostname or "").strip().lower()
    if _is_loopback_host(host) or host.endswith(".localhost") or host.endswith(".ts.net") or _is_tailscale_ip(host):
        return None
    return {"code": "hub_url_insecure_http_requires_opt_in"}


def _is_loopback_host(host: str) -> bool:
    if host in {"localhost", "::1"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_tailscale_ip(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address in ipaddress.ip_network("100.64.0.0/10")


def _env_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
