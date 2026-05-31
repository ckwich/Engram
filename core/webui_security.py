"""Auth, exposure, and browser-security helpers for the Engram WebUI."""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import time
from urllib.parse import urlsplit

from flask import has_request_context, jsonify, redirect, request, session, url_for


DEFAULT_WEBUI_HOST = "127.0.0.1"
DEFAULT_WEBUI_PORT = 5000
DEFAULT_MAX_CONTENT_LENGTH = 1_048_576
DEFAULT_MIN_REMOTE_TOKEN_CHARS = 32
DEFAULT_LOGIN_MAX_ATTEMPTS = 5
DEFAULT_LOGIN_WINDOW_SECONDS = 300
SESSION_SECRET_ENV = "ENGRAM_WEBUI_SESSION_SECRET"  # nosec B105
ACCESS_TOKEN_ENV = "ENGRAM_WEBUI_ACCESS_TOKEN"  # nosec B105
ACCESS_TOKEN_HEADER = "X-Engram-Access-Token"  # nosec B105
WRITE_TOKEN_ENV = "ENGRAM_WEBUI_WRITE_TOKEN"  # nosec B105
WRITE_TOKEN_HEADER = "X-Engram-Write-Token"  # nosec B105
COOKIE_SECURE_ENV = "ENGRAM_WEBUI_COOKIE_SECURE"
MAX_CONTENT_LENGTH_ENV = "ENGRAM_WEBUI_MAX_CONTENT_LENGTH"
MIN_REMOTE_TOKEN_CHARS_ENV = "ENGRAM_WEBUI_MIN_TOKEN_CHARS"  # nosec B105
LOGIN_MAX_ATTEMPTS_ENV = "ENGRAM_WEBUI_LOGIN_MAX_ATTEMPTS"
LOGIN_WINDOW_SECONDS_ENV = "ENGRAM_WEBUI_LOGIN_WINDOW_SECONDS"
ALLOWED_HOSTS_ENV = "ENGRAM_WEBUI_ALLOWED_HOSTS"
TRUSTED_ORIGINS_ENV = "ENGRAM_WEBUI_TRUSTED_ORIGINS"
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
AUTH_SESSION_KEY = "engram_webui_authenticated"
AUTH_TOKEN_FINGERPRINT_SESSION_KEY = "engram_webui_access_token_fingerprint"  # nosec B105
AUTH_EXEMPT_ENDPOINTS = {"login", "logout", "static"}
LOOPBACK_HOST_ALIASES = {"localhost", "localhost.localdomain", "127.0.0.1", "::1"}
_LOGIN_FAILURES: dict[str, list[float]] = {}


def _env_int(name: str, default: int, minimum: int | None = None) -> int:
    raw_value = os.environ.get(name, "").strip()
    try:
        value = int(raw_value) if raw_value else default
    except ValueError:
        value = default
    if minimum is not None:
        return max(value, minimum)
    return value


def _env_flag(name: str, default: bool = False) -> bool:
    raw_value = os.environ.get(name, "").strip().lower()
    if not raw_value:
        return default
    return raw_value in {"1", "true", "yes", "y", "on"}


def _env_list(name: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


def resolve_webui_bind() -> tuple[str, int]:
    """Resolve the dashboard bind address. Public exposure must be explicit."""
    host = os.environ.get("ENGRAM_WEBUI_HOST", DEFAULT_WEBUI_HOST).strip() or DEFAULT_WEBUI_HOST
    raw_port = os.environ.get("ENGRAM_WEBUI_PORT", str(DEFAULT_WEBUI_PORT)).strip()
    try:
        port = int(raw_port)
    except ValueError:
        port = DEFAULT_WEBUI_PORT
    return host, port


def is_loopback_host(host: str) -> bool:
    """Return whether the configured bind host is local-only."""
    normalized = (host or "").strip().lower().strip("[]")
    if normalized in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def normalize_host_value(value: str | None) -> str:
    """Normalize a Host-like value to a lowercase hostname without a port."""
    raw_value = (value or "").strip().lower()
    if not raw_value:
        return ""
    if "://" in raw_value:
        parsed = urlsplit(raw_value)
        raw_value = parsed.netloc or parsed.path
    raw_value = raw_value.rsplit("@", 1)[-1]
    if raw_value.startswith("["):
        end = raw_value.find("]")
        if end != -1:
            return raw_value[1:end].rstrip(".")
    if raw_value.count(":") == 1:
        host, port = raw_value.rsplit(":", 1)
        if port.isdigit():
            raw_value = host
    return raw_value.strip("[]").rstrip(".")


def normalize_origin_value(value: str | None) -> str:
    """Normalize an Origin value to scheme://host[:port], or empty if invalid."""
    raw_value = (value or "").strip()
    if not raw_value:
        return ""
    parsed = urlsplit(raw_value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    try:
        port = parsed.port
    except ValueError:
        return ""
    host = normalize_host_value(parsed.hostname)
    if not host:
        return ""
    default_port = (parsed.scheme == "http" and port == 80) or (
        parsed.scheme == "https" and port == 443
    )
    port_suffix = f":{port}" if port and not default_port else ""
    return f"{parsed.scheme}://{host}{port_suffix}"


def is_wildcard_host(host: str) -> bool:
    """Return whether a bind host accepts all interfaces and needs explicit host names."""
    try:
        return ipaddress.ip_address(normalize_host_value(host)).is_unspecified
    except ValueError:
        return False


def is_loopback_remote_addr(remote_addr: str | None) -> bool:
    """Return whether an inbound request appears to come from the local machine."""
    normalized = (remote_addr or "").strip().lower().strip("[]")
    if not normalized:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def configured_allowed_hosts(host: str | None = None) -> set[str]:
    """Return normalized Host header names accepted for exposed dashboard requests."""
    hosts = {
        normalized
        for normalized in (normalize_host_value(item) for item in _env_list(ALLOWED_HOSTS_ENV))
        if normalized
    }
    bind_host = normalize_host_value(host if host is not None else resolve_webui_bind()[0])
    if bind_host and not is_wildcard_host(bind_host):
        hosts.add(bind_host)
        if is_loopback_host(bind_host):
            hosts.update(LOOPBACK_HOST_ALIASES)
    return hosts


def configured_trusted_origins() -> set[str]:
    """Return normalized extra origins allowed for exposed unsafe requests."""
    return {
        normalized
        for normalized in (normalize_origin_value(item) for item in _env_list(TRUSTED_ORIGINS_ENV))
        if normalized
    }


def webui_effectively_exposed(host: str | None = None) -> bool:
    """Treat configured public binds or non-loopback clients as exposed mode."""
    bind_host = host if host is not None else resolve_webui_bind()[0]
    if not is_loopback_host(bind_host):
        return True
    if has_request_context() and not is_loopback_remote_addr(request.remote_addr):
        return True
    return False


def get_webui_write_token() -> str:
    """Read the optional write token without exposing it to templates."""
    return os.environ.get(WRITE_TOKEN_ENV, "").strip()


def get_webui_access_token() -> str:
    """Read the optional read-access token without exposing it to templates."""
    return os.environ.get(ACCESS_TOKEN_ENV, "").strip()


def minimum_remote_token_chars() -> int:
    """Minimum token entropy proxy for exposed-host startup validation."""
    return _env_int(
        MIN_REMOTE_TOKEN_CHARS_ENV,
        DEFAULT_MIN_REMOTE_TOKEN_CHARS,
        minimum=16,
    )


def validate_required_remote_token(env_name: str, token: str) -> None:
    """Require sufficiently long tokens before serving exposed WebUI requests."""
    if not token:
        raise RuntimeError(f"{env_name} is required when ENGRAM_WEBUI_HOST is not loopback")
    minimum_chars = minimum_remote_token_chars()
    if len(token) < minimum_chars:
        raise RuntimeError(
            f"{env_name} must be at least {minimum_chars} characters when "
            "ENGRAM_WEBUI_HOST is not loopback"
        )


def webui_read_auth_required(host: str | None = None) -> bool:
    """Require read auth when explicitly configured or when exposed off-loopback."""
    return bool(get_webui_access_token()) or webui_effectively_exposed(host)


def webui_write_auth_required(host: str | None = None) -> bool:
    """Require write auth when explicitly configured or when exposed off-loopback."""
    return bool(get_webui_write_token()) or webui_effectively_exposed(host)


def webui_auth_status() -> dict[str, bool | int | str]:
    host, port = resolve_webui_bind()
    env_allowed_hosts = _env_list(ALLOWED_HOSTS_ENV)
    trusted_origins = configured_trusted_origins()
    return {
        "bind_host": host,
        "bind_port": port,
        "exposed_mode": webui_effectively_exposed(host),
        "public_bind": not is_loopback_host(host),
        "wildcard_bind": is_wildcard_host(host),
        "read_auth_required": webui_read_auth_required(host),
        "access_token_configured": bool(get_webui_access_token()),
        "access_token_env": ACCESS_TOKEN_ENV,
        "access_token_header": ACCESS_TOKEN_HEADER,
        "write_auth_required": webui_write_auth_required(host),
        "write_token_configured": bool(get_webui_write_token()),
        "write_token_env": WRITE_TOKEN_ENV,
        "write_token_header": WRITE_TOKEN_HEADER,
        "allowed_hosts_configured": bool(env_allowed_hosts),
        "allowed_hosts_env": ALLOWED_HOSTS_ENV,
        "allowed_host_count": len(configured_allowed_hosts(host)),
        "trusted_origins_configured": bool(trusted_origins),
        "trusted_origins_env": TRUSTED_ORIGINS_ENV,
        "trusted_origin_count": len(trusted_origins),
        "minimum_token_chars": minimum_remote_token_chars(),
    }


def validate_webui_security(host: str | None = None) -> None:
    """Fail closed before binding the dashboard to a non-loopback interface."""
    bind_host = host if host is not None else resolve_webui_bind()[0]
    if is_loopback_host(bind_host):
        return
    validate_required_remote_token(ACCESS_TOKEN_ENV, get_webui_access_token())
    validate_required_remote_token(WRITE_TOKEN_ENV, get_webui_write_token())
    if is_wildcard_host(bind_host) and not configured_allowed_hosts(bind_host):
        raise RuntimeError(
            f"{ALLOWED_HOSTS_ENV} is required when ENGRAM_WEBUI_HOST is a wildcard address"
        )


def safe_next_url(value: str | None) -> str:
    """Keep login redirects local to the dashboard."""
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return url_for("index")


def access_token_fingerprint(token: str | None = None) -> str:
    """Bind browser sessions to the current configured access token."""
    value = get_webui_access_token() if token is None else token
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def is_access_authenticated() -> bool:
    expected = get_webui_access_token()
    if not expected:
        return False

    provided = request.headers.get(ACCESS_TOKEN_HEADER, "")
    if provided and hmac.compare_digest(provided, expected):
        return True

    expected_fingerprint = access_token_fingerprint(expected)
    session_fingerprint = session.get(AUTH_TOKEN_FINGERPRINT_SESSION_KEY, "")
    return (
        session.get(AUTH_SESSION_KEY) is True
        and isinstance(session_fingerprint, str)
        and hmac.compare_digest(session_fingerprint, expected_fingerprint)
    )


def login_limit_config() -> tuple[int, int]:
    return (
        _env_int(LOGIN_MAX_ATTEMPTS_ENV, DEFAULT_LOGIN_MAX_ATTEMPTS, minimum=1),
        _env_int(LOGIN_WINDOW_SECONDS_ENV, DEFAULT_LOGIN_WINDOW_SECONDS, minimum=1),
    )


def login_attempt_key() -> str:
    return request.remote_addr or "unknown"


def pruned_login_failures(key: str, now: float, window_seconds: int) -> list[float]:
    failures = [
        timestamp
        for timestamp in _LOGIN_FAILURES.get(key, [])
        if now - timestamp < window_seconds
    ]
    if failures:
        _LOGIN_FAILURES[key] = failures
    else:
        _LOGIN_FAILURES.pop(key, None)
    return failures


def login_rate_limited(key: str, now: float | None = None) -> bool:
    max_attempts, window_seconds = login_limit_config()
    current_time = time.time() if now is None else now
    return len(pruned_login_failures(key, current_time, window_seconds)) >= max_attempts


def record_failed_login(key: str, now: float | None = None) -> None:
    _, window_seconds = login_limit_config()
    current_time = time.time() if now is None else now
    failures = pruned_login_failures(key, current_time, window_seconds)
    failures.append(current_time)
    _LOGIN_FAILURES[key] = failures


def clear_failed_logins(key: str) -> None:
    _LOGIN_FAILURES.pop(key, None)


def request_host_allowed() -> bool:
    """Return whether the inbound Host header is acceptable for exposed mode."""
    request_host = normalize_host_value(request.host)
    if not request_host:
        return False
    if is_loopback_remote_addr(request.remote_addr) and is_loopback_host(request_host):
        return True
    return request_host in configured_allowed_hosts()


def request_origin_allowed() -> bool:
    """Return whether an unsafe request's Origin is allowed for this dashboard."""
    origin = request.headers.get("Origin", "")
    if not origin:
        return True
    normalized_origin = normalize_origin_value(origin)
    if not normalized_origin:
        return False
    current_origin = normalize_origin_value(f"{request.scheme}://{request.host}")
    if normalized_origin == current_origin and request_host_allowed():
        return True
    return normalized_origin in configured_trusted_origins()


def validate_exposed_request_trust():
    """Block untrusted Host/Origin browser boundaries before auth or storage logic."""
    if not request_host_allowed():
        return jsonify({"error": "host not allowed for exposed WebUI"}), 400
    if request.method in MUTATING_METHODS:
        if request.headers.get("Sec-Fetch-Site", "").strip().lower() == "cross-site":
            return jsonify({"error": "cross-site request forbidden"}), 403
        if not request_origin_allowed():
            return jsonify({"error": "origin not allowed for exposed WebUI"}), 403
    return None


def enforce_exposed_request_security():
    """Catch remote exposure even if Flask was started outside webui.py main."""
    if not webui_effectively_exposed():
        return None
    try:
        validate_required_remote_token(ACCESS_TOKEN_ENV, get_webui_access_token())
        validate_required_remote_token(WRITE_TOKEN_ENV, get_webui_write_token())
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503
    return validate_exposed_request_trust()


def apply_security_headers(response):
    """Apply browser hardening headers to dashboard and API responses."""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), geolocation=(), microphone=()")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "base-uri 'none'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "object-src 'none'; "
        "script-src 'self'; "
        "style-src 'self'",
    )
    return response


def enforce_write_token_for_mutations(auth_exempt_endpoints: set[str] | None = None):
    """Protect browser/API writes before they reach storage."""
    exempt = auth_exempt_endpoints or AUTH_EXEMPT_ENDPOINTS
    if request.endpoint in exempt:
        return None
    if request.method not in MUTATING_METHODS or not webui_write_auth_required():
        return None

    expected = get_webui_write_token()
    if not expected:
        return jsonify({"error": "write token required for exposed WebUI"}), 403

    provided = request.headers.get(WRITE_TOKEN_HEADER, "")
    if not hmac.compare_digest(provided, expected):
        return jsonify({"error": "invalid write token"}), 401

    return None


def enforce_access_for_reads(auth_exempt_endpoints: set[str] | None = None):
    """Protect dashboard and read APIs when the WebUI is exposed off-loopback."""
    exempt = auth_exempt_endpoints or AUTH_EXEMPT_ENDPOINTS
    if request.endpoint in exempt or not webui_read_auth_required():
        return None
    if is_access_authenticated():
        return None

    if request.path.startswith("/api/") or request.path == "/health":
        return jsonify({"error": "access token required for exposed WebUI"}), 401

    return redirect(url_for("login", next=request.full_path.rstrip("?")))
