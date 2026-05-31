"""
webui.py — Flask web dashboard for Engram.

Legacy memory business logic goes through the lazy memory manager adapter.
No direct file or ChromaDB access here.
"""
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
import hmac
import mimetypes
import os
import secrets

from core.chunk_preview import preview_memory_chunks
from core.engramd_client import EngramDaemonClientError
from core.graph_manager import graph_manager
from core.legacy.memory_manager_adapter import (
    is_duplicate_memory_error,
    memory_manager,
)
from core.memory_quality import audit_memory_quality as build_memory_quality_audit
from core.operation_log import operation_log
from core.retrieval_eval import run_retrieval_eval
from core.source_connectors import preview_source_connector
from core.source_intake import source_intake_manager
from core.usage_meter import usage_meter
from core.webui_gateway import WebUIDataGateway
from core.webui_security import (
    ACCESS_TOKEN_ENV,
    ACCESS_TOKEN_HEADER,
    ALLOWED_HOSTS_ENV,
    AUTH_EXEMPT_ENDPOINTS,
    AUTH_SESSION_KEY,
    AUTH_TOKEN_FINGERPRINT_SESSION_KEY,
    COOKIE_SECURE_ENV,
    DEFAULT_WEBUI_HOST,
    DEFAULT_WEBUI_PORT,
    DEFAULT_MAX_CONTENT_LENGTH,
    LOGIN_MAX_ATTEMPTS_ENV,
    LOGIN_WINDOW_SECONDS_ENV,
    MAX_CONTENT_LENGTH_ENV,
    MIN_REMOTE_TOKEN_CHARS_ENV,
    SESSION_SECRET_ENV,
    TRUSTED_ORIGINS_ENV,
    WRITE_TOKEN_ENV,
    WRITE_TOKEN_HEADER,
    _LOGIN_FAILURES,
    _env_flag,
    _env_int,
    access_token_fingerprint,
    apply_security_headers,
    clear_failed_logins,
    configured_allowed_hosts,
    configured_trusted_origins,
    enforce_access_for_reads,
    enforce_exposed_request_security,
    enforce_write_token_for_mutations,
    get_webui_access_token,
    get_webui_write_token,
    is_loopback_host,
    is_loopback_remote_addr,
    is_wildcard_host,
    login_attempt_key,
    login_rate_limited,
    minimum_remote_token_chars,
    normalize_host_value,
    normalize_origin_value,
    record_failed_login,
    request_host_allowed,
    request_origin_allowed,
    resolve_webui_bind,
    safe_next_url,
    validate_exposed_request_trust,
    validate_required_remote_token,
    validate_webui_security,
    webui_auth_status,
    webui_effectively_exposed,
    webui_read_auth_required,
    webui_write_auth_required,
)

mimetypes.add_type("application/javascript", ".js", strict=True)


app = Flask(__name__)
app.secret_key = os.environ.get(SESSION_SECRET_ENV) or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=_env_flag(COOKIE_SECURE_ENV),
    MAX_CONTENT_LENGTH=_env_int(MAX_CONTENT_LENGTH_ENV, DEFAULT_MAX_CONTENT_LENGTH, minimum=1024),
)


@app.before_request
def fail_closed_if_exposed_misconfigured():
    return enforce_exposed_request_security()


@app.after_request
def add_security_headers(response):
    return apply_security_headers(response)


@app.before_request
def require_write_token_for_mutations():
    return enforce_write_token_for_mutations(AUTH_EXEMPT_ENDPOINTS)


@app.before_request
def require_access_for_reads():
    return enforce_access_for_reads(AUTH_EXEMPT_ENDPOINTS)


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


def _bounded_query_int(name: str, default: int, minimum: int, maximum: int) -> int:
    value = request.args.get(name, default, type=int)
    return min(max(value, minimum), maximum)


def _query_tags() -> list[str]:
    raw_tags = request.args.get("tags", "")
    return [tag.strip() for tag in raw_tags.split(",") if tag.strip()]


def _filter_memory_metadata(
    memories: list[dict],
    *,
    project: str | None,
    domain: str | None,
    tags: list[str],
) -> list[dict]:
    filtered = memories
    if project:
        filtered = [memory for memory in filtered if memory.get("project") == project]
    if domain:
        filtered = [memory for memory in filtered if memory.get("domain") == domain]
    if tags:
        filtered = [
            memory
            for memory in filtered
            if all(tag in set(memory.get("tags") or []) for tag in tags)
        ]
    return filtered


def get_webui_gateway() -> WebUIDataGateway:
    return WebUIDataGateway(
        memory_manager=memory_manager,
        retrieval_eval_runner=run_retrieval_eval,
    )


def get_memory_os_inspector_payload(*, limit: int = 20) -> dict:
    """Return read-only Memory OS inspector data without performing promotions."""
    return get_webui_gateway().memory_os_inspector(limit=limit)


def apply_document_promotion_from_webui(payload: dict) -> dict:
    """Apply a reviewed document promotion through the configured Memory OS owner."""
    return get_webui_gateway().apply_document_promotion(payload)


# ── Pages ────────────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if not webui_read_auth_required():
        return redirect(url_for("index"))

    error = ""
    if request.method == "POST":
        attempt_key = login_attempt_key()
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
    try:
        result = get_webui_gateway().create_memory(data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        if is_duplicate_memory_error(e):
            return jsonify({"status": "duplicate", **e.duplicate}), 409
        raise
    return jsonify(result), 201


@app.route("/api/memory/<path:key>", methods=["PUT"])
def api_update(key):
    data, error_response = require_json_object_body()
    if error_response:
        return error_response
    if not data or not data.get("content"):
        return jsonify({"error": "content is required"}), 400
    try:
        result = get_webui_gateway().update_memory(key, data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        if is_duplicate_memory_error(e):
            return jsonify({"status": "duplicate", **e.duplicate}), 409
        raise
    return jsonify(result)


@app.route("/api/memory/<path:key>", methods=["DELETE"])
def api_delete(key):
    try:
        deleted = get_webui_gateway().delete_memory(key)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    if not deleted:
        return jsonify({"error": "Memory not found"}), 404
    return jsonify({"deleted": True})


@app.route("/api/stats")
def api_stats():
    return jsonify(memory_manager.get_stats())


@app.route("/api/inspector/memory-quality")
def api_inspector_memory_quality():
    limit = _bounded_query_int("limit", 100, 0, 500)
    offset = _bounded_query_int("offset", 0, 0, 100000)
    project = request.args.get("project") or None
    domain = request.args.get("domain") or None
    tags = _query_tags()
    try:
        memories = _filter_memory_metadata(
            memory_manager.list_memories(),
            project=project,
            domain=domain,
            tags=tags,
        )
        return jsonify(build_memory_quality_audit(memories, limit=limit, offset=offset))
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503


@app.route("/api/inspector/graph/edges")
def api_inspector_graph_edges():
    ref_kind = request.args.get("ref_kind") or None
    ref_key = request.args.get("ref_key") or None
    if bool(ref_kind) != bool(ref_key):
        return jsonify({"error": "ref_kind and ref_key must be provided together"}), 400
    ref = {"kind": ref_kind, "key": ref_key} if ref_kind and ref_key else None
    edge_type = request.args.get("edge_type") or None
    status_arg = request.args.get("status", "active")
    status = None if status_arg == "all" else status_arg
    try:
        return jsonify(graph_manager.list_edges(ref=ref, edge_type=edge_type, status=status))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503


@app.route("/api/inspector/graph/audit")
def api_inspector_graph_audit():
    try:
        return jsonify(graph_manager.audit_graph())
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503


@app.route("/api/inspector/source-drafts")
def api_inspector_source_drafts():
    project = request.args.get("project") or None
    status = request.args.get("status") or None
    limit = _bounded_query_int("limit", 50, 1, 500)
    offset = _bounded_query_int("offset", 0, 0, 100000)
    try:
        return jsonify(
            source_intake_manager.list_source_drafts(
                project=project,
                status=status,
                limit=limit,
                offset=offset,
            )
        )
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503


@app.route("/api/inspector/operations/jobs")
def api_inspector_operation_jobs():
    operation_type = request.args.get("operation_type") or None
    status = request.args.get("status") or None
    limit = _bounded_query_int("limit", 50, 1, 500)
    return jsonify(operation_log.list_jobs(operation_type=operation_type, status=status, limit=limit))


@app.route("/api/inspector/operations/events")
def api_inspector_operation_events():
    event_type = request.args.get("event_type") or None
    limit = _bounded_query_int("limit", 50, 1, 500)
    return jsonify(operation_log.list_events(event_type=event_type, limit=limit))


@app.route("/api/inspector/memory-os")
def api_inspector_memory_os():
    limit = _bounded_query_int("limit", 20, 1, 100)
    try:
        return jsonify(get_memory_os_inspector_payload(limit=limit))
    except EngramDaemonClientError as e:
        return jsonify({"error": {"code": "runtime_error", "message": str(e)}}), 503
    except RuntimeError as e:
        return jsonify({"error": {"code": "runtime_error", "message": str(e)}}), 503


@app.route("/api/inspector/sync")
def api_inspector_sync():
    limit = _bounded_query_int("limit", 20, 1, 100)
    try:
        payload = get_memory_os_inspector_payload(limit=limit)
    except EngramDaemonClientError as e:
        return jsonify({"error": {"code": "runtime_error", "message": str(e)}}), 503
    except RuntimeError as e:
        return jsonify({"error": {"code": "runtime_error", "message": str(e)}}), 503
    return jsonify(
        {
            "schema_version": payload.get("schema_version"),
            "write_performed": False,
            "limit": payload.get("limit", limit),
            "sync": payload.get("sync", {}),
        }
    )


@app.route("/api/inspector/review-queue")
def api_inspector_review_queue():
    limit = _bounded_query_int("limit", 20, 1, 100)
    try:
        payload = get_memory_os_inspector_payload(limit=limit)
    except EngramDaemonClientError as e:
        return jsonify({"error": {"code": "runtime_error", "message": str(e)}}), 503
    except RuntimeError as e:
        return jsonify({"error": {"code": "runtime_error", "message": str(e)}}), 503
    return jsonify(
        {
            "schema_version": payload.get("schema_version"),
            "write_performed": False,
            "limit": payload.get("limit", limit),
            "review_preparation_queue": payload.get("review_preparation_queue", {}),
            "document_artifact_transactions": payload.get("document_artifact_transactions", {}),
            "promotion_transactions": payload.get("promotion_transactions", {}),
            "knowledge_pr_review_state": payload.get("knowledge_pr_review_state", {}),
        }
    )


@app.route("/api/inspector/release-gates")
def api_inspector_release_gates():
    try:
        payload = get_memory_os_inspector_payload(limit=20)
    except EngramDaemonClientError as e:
        return jsonify({"error": {"code": "runtime_error", "message": str(e)}}), 503
    except RuntimeError as e:
        return jsonify({"error": {"code": "runtime_error", "message": str(e)}}), 503
    return jsonify(
        {
            "schema_version": payload.get("schema_version"),
            "write_performed": False,
            "release_gate_commands": payload.get("release_gate_commands", {}),
            "ekc_eval_summary": payload.get("ekc_eval_summary", {}),
        }
    )


@app.route("/api/inspector/document-promotions/apply", methods=["POST"])
def api_inspector_apply_document_promotion():
    body, error_response = require_json_object_body()
    if error_response:
        return error_response

    if body.get("accept") is not True:
        return jsonify(
            {
                "error": {
                    "code": "accept_required",
                    "message": "document promotion apply requires accept=true",
                }
            }
        ), 400

    approved_by = body.get("approved_by")
    if not isinstance(approved_by, str) or not approved_by.strip():
        return jsonify(
            {
                "error": {
                    "code": "approved_by_required",
                    "message": "document promotion apply requires non-empty approved_by",
                }
            }
        ), 400

    transaction = body.get("document_promotion_transaction")
    if not isinstance(transaction, dict):
        return jsonify(
            {
                "error": {
                    "code": "transaction_required",
                    "message": "document_promotion_transaction must be an object",
                }
            }
        ), 400
    if not str(transaction.get("transaction_id") or "").strip():
        return jsonify(
            {
                "error": {
                    "code": "transaction_id_required",
                    "message": "document_promotion_transaction.transaction_id is required",
                }
            }
        ), 400

    selected_indexes = body.get("selected_operation_indexes")
    if selected_indexes is not None and (
        not isinstance(selected_indexes, list)
        or any(not isinstance(index, int) for index in selected_indexes)
    ):
        return jsonify(
            {
                "error": {
                    "code": "selected_operation_indexes_invalid",
                    "message": "selected_operation_indexes must be a list of integers",
                }
            }
        ), 400

    payload = {
        "document_promotion_transaction": transaction,
        "accept": True,
        "approved_by": approved_by.strip(),
    }
    if selected_indexes is not None:
        payload["selected_operation_indexes"] = selected_indexes

    try:
        result = apply_document_promotion_from_webui(payload)
    except EngramDaemonClientError as e:
        return jsonify({"error": {"code": "runtime_error", "message": str(e)}}), 503
    except RuntimeError as e:
        return jsonify({"error": {"code": "runtime_error", "message": str(e)}}), 503

    status_code = 400 if isinstance(result.get("error"), dict) else 200
    return jsonify(result), status_code


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


@app.route("/api/eval/retrieval", methods=["POST"])
def api_retrieval_eval():
    return jsonify(get_webui_gateway().run_retrieval_eval())


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
        result = get_webui_gateway().mark_memory_reviewed(key, stale_type=stale_type)
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
