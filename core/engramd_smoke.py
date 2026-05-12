"""End-to-end smoke checks for a running local Engram daemon."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any


SMOKE_MARKER = "engramd smoke marker"


@dataclass
class _SmokeFailure(Exception):
    step: str
    code: str
    message: str
    details: Any = None


def run_daemon_smoke(client: Any, *, key: str | None = None) -> dict[str, Any]:
    """Exercise health, write, search, read, and delete against a running daemon."""
    smoke_key = key or f"_engramd_smoke_{uuid.uuid4().hex}"
    content = (
        "# Engramd Smoke Test\n\n"
        f"{SMOKE_MARKER}: {smoke_key}\n\n"
        "This temporary memory proves daemon-owned storage, retrieval, and cleanup."
    )
    steps: list[dict[str, Any]] = []
    stored = False
    status = "ok"
    error: dict[str, Any] | None = None

    def record(name: str, step_status: str, details: Any = None) -> None:
        entry: dict[str, Any] = {"name": name, "status": step_status}
        if details is not None:
            entry["details"] = details
        steps.append(entry)

    try:
        health = client.health()
        _raise_for_daemon_error("health", health)
        if health.get("status") != "ok":
            raise _SmokeFailure(
                "health",
                "daemon_unhealthy",
                "Daemon health did not report status ok.",
                health,
            )
        record("health", "ok", {"status": health.get("status")})

        duplicate_response = client.check_duplicate(
            {
                "key": smoke_key,
                "content": content,
            }
        )
        _raise_for_daemon_error("check_duplicate", duplicate_response)
        if duplicate_response.get("duplicate") is True:
            raise _SmokeFailure(
                "check_duplicate",
                "unexpected_duplicate",
                "Daemon reported the smoke memory as a duplicate before storage.",
                duplicate_response,
            )
        record("check_duplicate", "ok", {"key": smoke_key})

        store_payload = {
            "key": smoke_key,
            "content": content,
            "title": "Engramd Smoke Test",
            "tags": ["engramd", "smoke-test"],
            "force": True,
            "project": "Engram",
            "domain": "daemon",
            "status": "active",
            "canonical": False,
        }
        store_response = client.store_memory(store_payload)
        _raise_for_daemon_error("store_memory", store_response)
        if store_response.get("stored") is not True:
            raise _SmokeFailure(
                "store_memory",
                "store_failed",
                "Daemon did not store the smoke memory.",
                store_response,
            )
        stored = True
        record("store_memory", "ok", {"key": smoke_key})

        update_response = client.update_memory_metadata(
            {
                "key": smoke_key,
                "title": "Updated Engramd Smoke Test",
                "tags": ["engramd", "smoke-test", "updated"],
                "project": "Engram",
                "domain": "daemon",
                "status": "active",
                "canonical": False,
            }
        )
        _raise_for_daemon_error("update_memory_metadata", update_response)
        if update_response.get("updated") is not True:
            raise _SmokeFailure(
                "update_memory_metadata",
                "metadata_update_failed",
                "Daemon did not update the smoke memory metadata.",
                update_response,
            )
        record("update_memory_metadata", "ok", {"key": smoke_key})

        search_response = client.search_memories(
            {
                "query": SMOKE_MARKER,
                "limit": 5,
                "project": "Engram",
                "domain": "daemon",
                "tags": ["engramd", "smoke-test"],
                "include_stale": True,
                "canonical_only": False,
                "retrieval_mode": "semantic",
            }
        )
        _raise_for_daemon_error("search_memories", search_response)
        match = _find_search_result(search_response, smoke_key)
        if match is None:
            raise _SmokeFailure(
                "search_memories",
                "search_miss",
                "Daemon search did not return the smoke memory.",
                search_response,
            )
        record(
            "search_memories",
            "ok",
            {"key": smoke_key, "chunk_id": match.get("chunk_id")},
        )

        chunk_response = client.retrieve_chunk(
            {"key": smoke_key, "chunk_id": int(match.get("chunk_id", 0))}
        )
        _raise_for_daemon_error("retrieve_chunk", chunk_response)
        chunk = chunk_response.get("chunk") if isinstance(chunk_response, dict) else None
        chunk_text = chunk.get("text", "") if isinstance(chunk, dict) else ""
        if chunk_response.get("found") is not True or SMOKE_MARKER not in chunk_text:
            raise _SmokeFailure(
                "retrieve_chunk",
                "chunk_miss",
                "Daemon chunk retrieval did not return the smoke marker.",
                chunk_response,
            )
        record("retrieve_chunk", "ok", {"key": smoke_key})

        memory_response = client.retrieve_memory({"key": smoke_key})
        _raise_for_daemon_error("retrieve_memory", memory_response)
        memory = memory_response.get("memory") if isinstance(memory_response, dict) else None
        memory_content = memory.get("content", "") if isinstance(memory, dict) else ""
        if memory_response.get("found") is not True or SMOKE_MARKER not in memory_content:
            raise _SmokeFailure(
                "retrieve_memory",
                "memory_miss",
                "Daemon full-memory retrieval did not return the smoke marker.",
                memory_response,
            )
        record("retrieve_memory", "ok", {"key": smoke_key})
    except _SmokeFailure as exc:
        status = "failed"
        error = {"code": exc.code, "message": exc.message, "step": exc.step}
        record(exc.step, "failed", exc.details)
    except Exception as exc:  # noqa: BLE001 - smoke output should preserve runtime failures
        status = "failed"
        error = {"code": "runtime_error", "message": str(exc), "step": "runtime"}
        record("runtime", "failed", {"exception": type(exc).__name__})
    finally:
        if stored:
            try:
                delete_response = client.delete_memory({"key": smoke_key})
                _raise_for_daemon_error("delete_memory", delete_response)
                if delete_response.get("deleted") is not True:
                    raise _SmokeFailure(
                        "delete_memory",
                        "delete_failed",
                        "Daemon did not delete the smoke memory.",
                        delete_response,
                    )
                record("delete_memory", "ok", {"key": smoke_key})
            except _SmokeFailure as exc:
                status = "failed"
                error = {"code": exc.code, "message": exc.message, "step": exc.step}
                record(exc.step, "failed", exc.details)
            except Exception as exc:  # noqa: BLE001 - cleanup diagnostics are useful
                status = "failed"
                error = {
                    "code": "cleanup_failed",
                    "message": str(exc),
                    "step": "delete_memory",
                }
                record("delete_memory", "failed", {"exception": type(exc).__name__})

    return {
        "status": status,
        "key": smoke_key,
        "steps": steps,
        "error": error,
    }


def _raise_for_daemon_error(step: str, payload: Any) -> None:
    if not isinstance(payload, dict):
        raise _SmokeFailure(
            step,
            "invalid_response",
            "Daemon returned a non-object response.",
            payload,
        )
    error = payload.get("error")
    if error is None:
        return
    if isinstance(error, dict):
        code = str(error.get("code") or "daemon_error")
        message = str(error.get("message") or error)
    else:
        code = "daemon_error"
        message = str(error)
    raise _SmokeFailure(step, code, message, payload)


def _find_search_result(payload: dict[str, Any], key: str) -> dict[str, Any] | None:
    results = payload.get("results")
    if not isinstance(results, list):
        return None
    for result in results:
        if isinstance(result, dict) and result.get("key") == key:
            return result
    return None
