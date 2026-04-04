"""
webui.py — Flask web dashboard for Engram.

All business logic goes through memory_manager only.
No direct file or ChromaDB access here.
"""
from flask import Flask, render_template, request, jsonify

from core.memory_manager import memory_manager, DuplicateMemoryError, _now, _json_path

app = Flask(__name__)


# ── Pages ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    memories = memory_manager.list_memories()
    stats = memory_manager.get_stats()
    all_tags = sorted({t for m in memories for t in m.get("tags", [])})
    return render_template("index.html", memories=memories, stats=stats, all_tags=all_tags)


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
    data = request.get_json()
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
    data = request.get_json()
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


@app.route("/api/memory/<path:key>/reviewed", methods=["POST"])
def api_reviewed(key):
    """
    Mark a memory as reviewed without deleting it (STAL-04).
    - time-stale: resets last_accessed to now
    - code-stale: clears potentially_stale flag
    - both: applies both resets
    Reads stale_type from request JSON body: {"stale_type": "time"|"code"|"both"}
    """
    body = request.get_json(silent=True) or {}
    stale_type = body.get("stale_type", "both")

    data = memory_manager._load_json(key)
    if data is None:
        return jsonify({"error": "Memory not found"}), 404

    now = _now()
    if stale_type in ("time", "both"):
        data["last_accessed"] = now
    if stale_type in ("code", "both"):
        data["potentially_stale"] = False
        data["stale_reason"] = ""
        data["stale_flagged_at"] = None

    try:
        memory_manager._save_json(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 503

    return jsonify({"reviewed": True, "key": key})


@app.route("/health")
def health():
    from core.embedder import embedder
    stats = memory_manager.get_stats()
    return jsonify({
        "status": "ok",
        "model_loaded": embedder._model is not None,
        "total_memories": stats["total_memories"],
        "total_chunks": stats["total_chunks"],
    })


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from core.embedder import embedder
    embedder._load()
    app.run(host="0.0.0.0", port=5000, debug=False)