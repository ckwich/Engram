from __future__ import annotations

import server


def test_build_health_payload_reports_degraded_for_chroma_owner(monkeypatch):
    monkeypatch.setattr(server.embedder, "_load", lambda: None)
    monkeypatch.setattr(server.embedder, "_model", object())

    def raise_chroma_owner():
        raise RuntimeError(
            "ChromaDB is owned by another Engram process; using JSON-first fallback in this process."
        )

    monkeypatch.setattr(server.memory_manager, "_ensure_initialized", raise_chroma_owner)
    monkeypatch.setattr(
        server.memory_manager,
        "get_json_fallback_stats",
        lambda *, chroma_error=None: {
            "total_memories": 3,
            "total_chars": 1200,
            "total_chunks": None,
            "storage_bytes": 42,
            "storage_size": "42 B",
            "json_bytes": 40,
            "json_size": "40 B",
            "chroma_bytes": 2,
            "chroma_size": "2 B",
            "json_path": "C:/Dev/Engram/data/memories",
            "chroma_path": "C:/Dev/Engram/data/chroma",
            "vector_index": {
                "available": False,
                "error": chroma_error,
            },
        },
    )

    payload = server._build_health_payload()

    assert payload["status"] == "degraded"
    assert payload["model"] == "loaded"
    assert payload["stats"]["total_memories"] == 3
    assert payload["stats"]["total_chunks"] is None
    assert payload["stats"]["vector_index"]["available"] is False
    assert payload["error"]["code"] == "runtime_error"
    assert "ChromaDB is owned by another Engram process" in payload["error"]["message"]


def test_build_health_payload_uses_daemon_when_configured(monkeypatch):
    class FakeDaemonClient:
        def health(self):
            return {
                "daemon": "engramd",
                "status": "ok",
                "stats": {
                    "total_memories": 7,
                    "total_chunks": 21,
                    "storage_size": "1 MB",
                    "json_size": "200 KB",
                    "chroma_size": "800 KB",
                    "json_path": "C:/Dev/Engram/data/memories",
                    "chroma_path": "C:/Dev/Engram/data/chroma",
                },
                "error": None,
            }

    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765/")
    monkeypatch.setattr(server, "_daemon_client", lambda: FakeDaemonClient())

    def fail_local_init():
        raise AssertionError("daemon-client health must not initialize local Chroma")

    monkeypatch.setattr(server.memory_manager, "_ensure_initialized", fail_local_init)

    payload = server._build_health_payload()

    assert payload["status"] == "ok"
    assert payload["mode"] == "daemon_client"
    assert payload["daemon_url"] == "http://127.0.0.1:8765"
    assert payload["daemon_reachable"] is True
    assert payload["stats"]["total_chunks"] == 21
    assert payload["error"] is None


def test_mcp_env_includes_data_dir_and_optional_daemon_url():
    direct = server._mcp_env()
    daemon = server._mcp_env("http://127.0.0.1:8765/")

    assert direct["ENGRAM_DATA_DIR"].endswith("Engram\\data") or direct["ENGRAM_DATA_DIR"].endswith("Engram/data")
    assert "ENGRAM_DAEMON_URL" not in direct
    assert daemon["ENGRAM_DAEMON_URL"] == "http://127.0.0.1:8765"
    assert daemon["ENGRAM_DATA_DIR"] == direct["ENGRAM_DATA_DIR"]
