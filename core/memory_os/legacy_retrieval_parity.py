"""No-write retrieval parity checks for migrated legacy memories."""
from __future__ import annotations

from typing import Any


SCHEMA_VERSION = "2026-05-15.legacy_retrieval_parity.v1"
VALID_EXPECTATIONS = {"present", "absent"}


def run_legacy_retrieval_parity_check(
    runtime: Any,
    *,
    probes: list[dict[str, Any]],
    source_label: str = "memory_os",
) -> dict[str, Any]:
    """Run fixture or live-corpus retrieval checks without writing memory."""
    checks = [_run_probe(runtime, probe, index) for index, probe in enumerate(probes)]
    failed = [check for check in checks if not check["passed"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "operation": "legacy_retrieval_parity_check",
        "source_label": str(source_label or "memory_os"),
        "status": "fail" if failed else "pass",
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "checked_count": len(checks),
        "passed_count": len(checks) - len(failed),
        "failed_count": len(failed),
        "checks": checks,
        "error": (
            {
                "code": "retrieval_parity_failed",
                "message": f"{len(failed)} retrieval parity check(s) failed.",
            }
            if failed
            else None
        ),
    }


def _run_probe(runtime: Any, probe: dict[str, Any], index: int) -> dict[str, Any]:
    name = _optional_text(probe.get("name")) or f"probe_{index + 1}"
    try:
        return _run_validated_probe(runtime, probe, name=name)
    except Exception as exc:
        return {
            "name": name,
            "passed": False,
            "matched": False,
            "error": {"code": "probe_error", "message": str(exc)},
        }


def _run_validated_probe(runtime: Any, probe: dict[str, Any], *, name: str) -> dict[str, Any]:
    query = _required_text(probe.get("query"), "query")
    expected_key = _required_text(probe.get("expected_key"), "expected_key")
    expectation = str(probe.get("expect") or "present").strip().lower()
    if expectation not in VALID_EXPECTATIONS:
        raise ValueError(f"expect must be one of {sorted(VALID_EXPECTATIONS)}")

    retrieval_mode = str(probe.get("retrieval_mode") or "semantic").strip() or "semantic"
    limit = max(int(probe.get("limit") or 5), 1)
    search = runtime.search_memories(
        query,
        limit=limit,
        project=_optional_text(probe.get("project")),
        exact_project_match=bool(probe.get("exact_project_match", False)),
        domain=_optional_text(probe.get("domain")),
        tags=_string_list(probe.get("tags")),
        include_stale=bool(probe.get("include_stale", True)),
        canonical_only=bool(probe.get("canonical_only", False)),
        retrieval_mode=retrieval_mode,
    )
    results = list(search.get("results") or [])
    matched_result = _find_result(results, expected_key)
    matched = matched_result is not None
    passed = matched if expectation == "present" else not matched
    check: dict[str, Any] = {
        "name": name,
        "query": query,
        "expected_key": expected_key,
        "expect": expectation,
        "retrieval_mode": search.get("retrieval_mode", retrieval_mode),
        "include_stale": bool(probe.get("include_stale", True)),
        "project": _optional_text(probe.get("project")),
        "limit": limit,
        "matched": matched,
        "passed": passed and search.get("error") is None,
        "top_key": str(results[0].get("key")) if results else None,
        "result_keys": [str(result.get("key")) for result in results],
        "search_error": search.get("error"),
    }
    if expectation == "present" and matched and bool(probe.get("check_ladder", False)):
        ladder = _check_agent_ladder(runtime, matched_result, probe)
        check["ladder"] = ladder
        check["passed"] = bool(check["passed"] and ladder["passed"])
    elif bool(probe.get("check_ladder", False)):
        check["ladder"] = {
            "checked": False,
            "passed": expectation == "absent",
            "reason": "expected key was not present in search results",
        }
    return check


def _check_agent_ladder(
    runtime: Any,
    matched_result: dict[str, Any],
    probe: dict[str, Any],
) -> dict[str, Any]:
    key = str(matched_result.get("key"))
    chunk_id = int(matched_result.get("chunk_id", 0))
    chunk = runtime.retrieve_chunk(key, chunk_id)
    memory = runtime.retrieve_memory(key)
    expected_text = _optional_text(probe.get("expected_text_contains"))
    chunk_text = str((chunk.get("chunk") or {}).get("text") or "")
    memory_text = str((memory.get("memory") or {}).get("content") or "")
    text_contains_expected = (
        True if expected_text is None else expected_text in chunk_text or expected_text in memory_text
    )
    return {
        "checked": True,
        "key": key,
        "chunk_id": chunk_id,
        "chunk_found": bool(chunk.get("found")),
        "memory_found": bool(memory.get("found")),
        "text_contains_expected": text_contains_expected,
        "passed": bool(chunk.get("found") and memory.get("found") and text_contains_expected),
        "chunk_error": chunk.get("error"),
        "memory_error": memory.get("error"),
    }


def _find_result(results: list[dict[str, Any]], expected_key: str) -> dict[str, Any] | None:
    for result in results:
        if str(result.get("key")) == expected_key:
            return result
    return None


def _required_text(value: Any, field: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"{field} is required")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]
