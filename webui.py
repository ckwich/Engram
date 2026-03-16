"""
webui.py — Flask web dashboard for Engram.

All business logic goes through memory_manager only.
No direct file or ChromaDB access here.
"""
from flask import Flask, render_template, request, jsonify

from core.memory_manager import memory_manager

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
    limit = request.args.get("limit", 10, type=int)
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
    result = memory_manager.store_memory(
        key=data["key"],
        content=data["content"],
        tags=tags,
        title=data.get("title"),
    )
    return jsonify(result), 201


@app.route("/api/memory/<path:key>", methods=["PUT"])
def api_update(key):
    data = request.get_json()
    if not data or not data.get("content"):
        return jsonify({"error": "content is required"}), 400
    tags = data.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    result = memory_manager.store_memory(
        key=key,
        content=data["content"],
        tags=tags,
        title=data.get("title"),
    )
    return jsonify(result)


@app.route("/api/memory/<path:key>", methods=["DELETE"])
def api_delete(key):
    deleted = memory_manager.delete_memory(key)
    if not deleted:
        return jsonify({"error": "Memory not found"}), 404
    return jsonify({"deleted": True})


@app.route("/api/stats")
def api_stats():
    return jsonify(memory_manager.get_stats())


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
