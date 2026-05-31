"""Authentication helpers for Engram Personal Hub Mode."""
from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any


HUB_ACCESS_TOKEN_ENV = "ENGRAM_HUB_ACCESS_TOKEN"
MIN_HUB_TOKEN_LENGTH = 32


def token_fingerprint(token: str) -> str:
    """Return a stable non-secret fingerprint for hub access-token diagnostics."""
    return "sha256:" + hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def load_hub_access_token(env: dict[str, str] | None = None) -> dict[str, Any]:
    """Load and policy-check the hub bearer token without logging it."""
    source = env if env is not None else os.environ
    token = str(source.get(HUB_ACCESS_TOKEN_ENV) or "").strip()
    if len(token) < MIN_HUB_TOKEN_LENGTH:
        return {
            "status": "policy_denied",
            "error": {"code": "hub_access_token_too_short"},
            "required_min_length": MIN_HUB_TOKEN_LENGTH,
        }
    return {
        "status": "ready",
        "token": token,
        "token_fingerprint": token_fingerprint(token),
    }


def authorize_hub_request(headers: dict[str, str], *, expected_token: str) -> dict[str, Any]:
    """Authorize one hub request using a boring bearer token comparison."""
    raw = headers.get("Authorization") or headers.get("authorization") or ""
    prefix = "Bearer "
    if not raw.startswith(prefix):
        return {"authorized": False, "error": {"code": "hub_authorization_required"}}
    supplied = raw[len(prefix) :].strip()
    expected = str(expected_token or "")
    authorized = hmac.compare_digest(supplied, expected)
    result: dict[str, Any] = {
        "authorized": authorized,
        "token_fingerprint": token_fingerprint(expected),
    }
    if not authorized:
        result["error"] = {"code": "hub_authorization_failed"}
    return result
