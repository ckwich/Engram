"""
webui.py — Flask web dashboard for Engram.

All business logic goes through memory_manager only.
No direct file or ChromaDB access here.
"""
from flask import (
    Flask,
    has_request_context,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
import hashlib
import hmac
import ipaddress
import os
import secrets
import time
from urllib.parse import urlsplit

from core.chunk_preview import preview_memory_chunks
from core.memory_manager import memory_manager, DuplicateMemoryError
from core.retrieval_eval import run_retrieval_eval
from core.source_connectors import preview_source_connector
from core.usage_meter import usage_meter

DEFAULT_WEBUI_HOST = "127.0.0.1"
DEFAULT_WEBUI_PORT = 5000
DEFAULT_MAX_CONTENT_LENGTH = 1_048_576
DEFAULT_MIN_REMOTE_TOKEN_CHARS = 32
DEFAULT_LOGIN_MAX_ATTEMPTS = 5
DEFAULT_LOGIN_WINDOW_SECONDS = 300
# These are names only; token values come from the environment.
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


app = Flask(__name__)
app.secret_key = os.environ.get(SESSION_SECRET_ENV) or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=_env_flag(COOKIE_SECURE_ENV),
    MAX_CONTENT_LENGTH=_env_int(MAX_CONTENT_LENGTH_ENV, DEFAULT_MAX_CONTENT_LENGTH, minimum=1024),
)


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


def _validate_required_remote_token(env_name: str, token: str) -> None:
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
    _validate_required_remote_token(ACCESS_TOKEN_ENV, get_webui_access_token())
    _validate_required_remote_token(WRITE_TOKEN_ENV, get_webui_write_token())
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


def _login_limit_config() -> tuple[int, int]:
    return (
        _env_int(LOGIN_MAX_ATTEMPTS_ENV, DEFAULT_LOGIN_MAX_ATTEMPTS, minimum=1),
        _env_int(LOGIN_WINDOW_SECONDS_ENV, DEFAULT_LOGIN_WINDOW_SECONDS, minimum=1),
    )


def _login_attempt_key() -> str:
    return request.remote_addr or "unknown"


def _pruned_login_failures(key: str, now: float, window_seconds: int) -> list[float]:
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
    max_attempts, window_seconds = _login_limit_config()
    current_time = time.time() if now is None else now
    return len(_pruned_login_failures(key, current_time, window_seconds)) >= max_attempts


def record_failed_login(key: str, now: float | None = None) -> None:
    _, window_seconds = _login_limit_config()
    current_time = time.time() if now is None else now
    failures = _pruned_login_failures(key, current_time, window_seconds)
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


@app.before_request
def fail_closed_if_exposed_misconfigured():
    """Catch remote exposure even if Flask was started outside webui.py main."""
    if not webui_effectively_exposed():
        return None
    try:
        _validate_required_remote_token(ACCESS_TOKEN_ENV, get_webui_access_token())
        _validate_required_remote_token(WRITE_TOKEN_ENV, get_webui_write_token())
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503
    return validate_exposed_request_trust()


@app.after_request
def add_security_headers(response):
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


def require_json_object_body() -> tuple[dict, object | None]:
    """Require mutating JSON APIs to receive a parseable JSON object."""
    if not request.is_json:
        return {}, (jsonify({"error": "application/json required"}), 415)
    body = request.get_json(silent=True)
    if body is None:
        return {}, (jsonify({"error": "valid JSON body required"}), 400)
    if not isinstance(body, dict):
        return {}, (jsonify({"error": "JSON object required"}), 400)
    return body, None


@app.before_request
def require_write_token_for_mutations():
    """Protect browser/API writes before they reach memory storage."""
    if request.endpoint in AUTH_EXEMPT_ENDPOINTS:
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


@app.before_request
def require_access_for_reads():
    """Protect dashboard and read APIs when the WebUI is exposed off-loopback."""
    if request.endpoint in AUTH_EXEMPT_ENDPOINTS or not webui_read_auth_required():
        return None
    if is_access_authenticated():
        return None

    if request.path.startswith("/api/") or request.path == "/health":
        return jsonify({"error": "access token required for exposed WebUI"}), 401

    return redirect(url_for("login", next=request.full_path.rstrip("?")))


# ── Pages ────────────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if not webui_read_auth_required():
        return redirect(url_for("index"))

    error = ""
    if request.method == "POST":
        attempt_key = _login_attempt_key()
        if login_rate_limited(attempt_key):
            return render_template(
                "login.html",
                error="Too many failed attempts. Try again later.",
            ), 429

        expected = get_webui_access_token()
        provided = request.form.get("access_token", "").strip()
        if expected and hmac.compare_digest(provided, expected):
            clear_failed_logins(attempt_key)
            session[AUTH_SESSION_KEY] = True
            session[AUTH_TOKEN_FINGERPRINT_SESSION_KEY] = access_token_fingerprint(expected)
            return redirect(safe_next_url(request.args.get("next")))
        record_failed_login(attempt_key)
        error = "Invalid access token"

    return render_template("login.html", error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.pop(AUTH_SESSION_KEY, None)
    session.pop(AUTH_TOKEN_FINGERPRINT_SESSION_KEY, None)
    return redirect(url_for("login"))


@app.route("/")
def index():
    memories = memory_manager.list_memories()
    stats = memory_manager.get_stats()
    all_tags = sorted({t for m in memories for t in m.get("tags", [])})
    return render_template(
        "index.html",
        memories=memories,
        stats=stats,
        all_tags=all_tags,
        auth=webui_auth_status(),
    )


# ── API endpoints ────────────────────────────────────────────────────────────

@app.route("/api/search")
def api_search():
    query = request.args.get("q", "").strip()
    limit = min(max(request.args.get("limit", 10, type=int), 1), 50)
    if not query:
        return jsonify([])
    results = memory_manager.search_memories(query, limit=limit)
    return jsonify(results)


@app.route("/api/chunk/<path:key>/<int:chunk_id>")
def api_chunk(key, chunk_id):
    chunk = memory_manager.retrieve_chunk(key, chunk_id)
    if chunk is None:
        return jsonify({"error": "Chunk not found"}), 404
    return jsonify(chunk)


@app.route("/api/memory/<path:key>")
def api_memory(key):
    memory = memory_manager.retrieve_memory(key)
    if memory is None:
        return jsonify({"error": "Memory not found"}), 404
    return jsonify(memory)


@app.route("/api/memory", methods=["POST"])
def api_create():
    data, error_response = require_json_object_body()
    if error_response:
        return error_response
    if not data or not data.get("key") or not data.get("content"):
        return jsonify({"error": "key and content are required"}), 400
    tags = data.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    related_to = data.get("related_to", [])
    if isinstance(related_to, str):
        related_to = [k.strip() for k in related_to.split(",") if k.strip()]
    force = bool(data.get("force", False))
    try:
        result = memory_manager.store_memory(
            key=data["key"],
            content=data["content"],
            tags=tags,
            title=data.get("title"),
            related_to=related_to,
            force=force,
        )
    except DuplicateMemoryError as e:
        return jsonify({"status": "duplicate", **e.duplicate}), 409
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    return jsonify(result), 201


@app.route("/api/memory/<path:key>", methods=["PUT"])
def api_update(key):
    data, error_response = require_json_object_body()
    if error_response:
        return error_response
    if not data or not data.get("content"):
        return jsonify({"error": "content is required"}), 400
    tags = data.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    related_to = data.get("related_to", [])
    if isinstance(related_to, str):
        related_to = [k.strip() for k in related_to.split(",") if k.strip()]
    force = bool(data.get("force", False))
    try:
        result = memory_manager.store_memory(
            key=key,
            content=data["content"],
            tags=tags,
            title=data.get("title"),
            related_to=related_to,
            force=force,
        )
    except DuplicateMemoryError as e:
        return jsonify({"status": "duplicate", **e.duplicate}), 409
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    return jsonify(result)


@app.route("/api/memory/<path:key>", methods=["DELETE"])
def api_delete(key):
    try:
        deleted = memory_manager.delete_memory(key)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    if not deleted:
        return jsonify({"error": "Memory not found"}), 404
    return jsonify({"deleted": True})


@app.route("/api/stats")
def api_stats():
    return jsonify(memory_manager.get_stats())


@app.route("/api/related/<path:key>")
def api_related(key):
    """Return all memories related to the given key (bidirectional)."""
    result = memory_manager.get_related_memories(key)
    return jsonify(result)


@app.route("/api/stale")
def api_stale():
    """Return stale memories list. Optional query params: days (int), type (time|code|all)."""
    days = request.args.get("days", None, type=int)
    filter_type = request.args.get("type", "all")
    if filter_type not in ("time", "code", "all"):
        filter_type = "all"
    results = memory_manager.get_stale_memories(days=days, type=filter_type)
    return jsonify(results)


@app.route("/api/usage/summary")
def api_usage_summary():
    days = min(max(request.args.get("days", 7, type=int), 1), 90)
    return jsonify(usage_meter.get_summary(days=days))


@app.route("/api/usage/calls")
def api_usage_calls():
    tool = request.args.get("tool") or None
    limit = min(max(request.args.get("limit", 100, type=int), 1), 500)
    return jsonify(usage_meter.list_calls(tool=tool, limit=limit))


@app.route("/api/eval/retrieval")
def api_retrieval_eval():
    return jsonify(run_retrieval_eval(memory_manager))


@app.route("/api/chunk-preview", methods=["POST"])
def api_chunk_preview():
    body, error_response = require_json_object_body()
    if error_response:
        return error_response
    content = body.get("content", "")
    title = body.get("title", "")
    max_size = body.get("max_size", 800)
    max_chunks = body.get("max_chunks", 50)
    try:
        return jsonify(preview_memory_chunks(content, title=title, max_size=max_size, max_chunks=max_chunks))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/source-connectors/preview", methods=["POST"])
def api_source_connector_preview():
    body, error_response = require_json_object_body()
    if error_response:
        return error_response
    try:
        payload = preview_source_connector(
            connector_type=body.get("connector_type", ""),
            target=body.get("target", ""),
            include_globs=body.get("include_globs"),
            max_files=body.get("max_files", 20),
            max_file_size_kb=body.get("max_file_size_kb", 256),
            max_source_text_chars=body.get("max_source_text_chars", 12000),
        )
    except ValueError as e:
        return jsonify({"error": str(e), "write_performed": False}), 400
    return jsonify(payload)


@app.route("/api/memory/<path:key>/reviewed", methods=["POST"])
def api_reviewed(key):
    """
    Mark a memory as reviewed without deleting it (STAL-04).
    - time-stale: resets last_accessed to now
    - code-stale: clears potentially_stale flag
    - both: applies both resets
    Reads stale_type from request JSON body: {"stale_type": "time"|"code"|"both"}
    """
    body, error_response = require_json_object_body()
    if error_response:
        return error_response
    stale_type = body.get("stale_type", "both")

    try:
        result = memory_manager.mark_memory_reviewed(key, stale_type=stale_type)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 503
    if result is None:
        return jsonify({"error": "Memory not found"}), 404

    return jsonify(result)


@app.route("/health")
def health():
    from core.embedder import embedder
    stats = memory_manager.get_stats()
    return jsonify({
        "status": "ok",
        "model_loaded": embedder._model is not None,
        "total_memories": stats["total_memories"],
        "total_chunks": stats["total_chunks"],
        "storage_bytes": stats["storage_bytes"],
        "storage_size": stats["storage_size"],
    })


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from core.embedder import embedder
    host, port = resolve_webui_bind()
    validate_webui_security(host)
    embedder._load()
    app.run(host=host, port=port, debug=False)
