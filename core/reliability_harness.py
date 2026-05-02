from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from core.context_builder import build_context_receipt, make_filters
from core.usage_meter import ESTIMATE_METHOD, estimate_tokens


SCHEMA_VERSION = "2026-04-28.agent-reliability.v1"
DEFAULT_PROJECT = "C:/Dev/Engram"
DEFAULT_DOMAIN = "agent-reliability"
EVAL_KEY_PREFIX = "_engram_eval_"
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentReliabilityScenario:
    scenario_id: str
    description: str
    key: str
    content: str
    query: str
    expected_key: str
    title: str
    tags: list[str]
    project: str = DEFAULT_PROJECT
    domain: str = DEFAULT_DOMAIN
    max_chunks: int = 3
    budget_chars: int = 1200
    include_stale: bool = False
    canonical_only: bool = False


def default_agent_reliability_scenarios() -> list[AgentReliabilityScenario]:
    return [
        AgentReliabilityScenario(
            scenario_id="retrieval_ladder_context_budget",
            description=(
                "Seed one calibration memory and verify search, chunk retrieval, "
                "budget accounting, and token estimates stay aligned."
            ),
            key=f"{EVAL_KEY_PREFIX}retrieval_ladder_context_budget",
            expected_key=f"{EVAL_KEY_PREFIX}retrieval_ladder_context_budget",
            title="Agent Reliability Retrieval Ladder",
            content=(
                "## Retrieval Ladder Calibration\n\n"
                "Engram should let agents search first, retrieve only bounded "
                "chunks, and see budget accounting before escalating to full "
                "memory reads."
            ),
            query="Engram retrieval ladder bounded context budget accounting",
            tags=["agent-eval", "reliability", "context-pack"],
            max_chunks=2,
            budget_chars=1000,
        )
    ]


def run_agent_reliability_harness(
    memory_manager: Any,
    *,
    scenarios: Iterable[AgentReliabilityScenario] | None = None,
    cleanup: bool = True,
) -> dict[str, Any]:
    scenario_list = list(scenarios or default_agent_reliability_scenarios())
    reports: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []

    for scenario in scenario_list:
        reports.append(_run_scenario(memory_manager, scenario, cleanup=cleanup))

    passed = sum(1 for report in reports if report["status"] == "pass")
    failed = len(reports) - passed
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "status": "pass" if failed == 0 else "fail",
            "scenario_count": len(reports),
            "passed": passed,
            "failed": failed,
        },
        "scenarios": reports,
        "warnings": warnings,
    }


def _run_scenario(
    memory_manager: Any,
    scenario: AgentReliabilityScenario,
    *,
    cleanup: bool,
) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    search_payload: dict[str, Any] = {"query": scenario.query, "count": 0, "results": []}
    chunks: list[dict[str, Any]] = []

    try:
        memory_manager.store_memory(
            scenario.key,
            scenario.content,
            scenario.tags,
            scenario.title,
            force=True,
            project=scenario.project,
            domain=scenario.domain,
            canonical=True,
        )
        search_payload = memory_manager.search_memories_structured(
            scenario.query,
            limit=max(scenario.max_chunks, 1),
            project=scenario.project,
            domain=scenario.domain,
            tags=scenario.tags,
            include_stale=scenario.include_stale,
            canonical_only=scenario.canonical_only,
        )
        expected_rank = _expected_key_rank(search_payload.get("results", []), scenario.expected_key)
        chunk_requests = _chunk_requests(search_payload.get("results", []), scenario.max_chunks)
        retrieved_chunks = memory_manager.retrieve_chunks(chunk_requests)
        chunks = _select_budgeted_chunks(retrieved_chunks, scenario.budget_chars)

        if expected_rank is None:
            findings.append(
                {
                    "code": "expected_key_not_found",
                    "message": f"Expected memory {scenario.expected_key} was not returned by search.",
                }
            )
        if not chunks:
            findings.append(
                {
                    "code": "no_chunks_selected",
                    "message": "Search returned no retrievable chunks within the scenario budget.",
                }
            )

        used_chars = sum(len(chunk.get("text") or "") for chunk in chunks)
        omitted_count = max(len(retrieved_chunks) - len(chunks), 0)
        status = "pass" if not findings else "fail"
        return {
            "id": scenario.scenario_id,
            "description": scenario.description,
            "status": status,
            "expected_key": scenario.expected_key,
            "expected_key_found": expected_rank is not None,
            "expected_key_rank": expected_rank,
            "search": {
                "count": search_payload.get("count", 0),
                "top_keys": [result.get("key") for result in search_payload.get("results", [])],
            },
            "context_pack": {
                "selected_chunk_count": len(chunks),
                "used_chars": used_chars,
                "budget_chars": scenario.budget_chars,
                "omitted_count": omitted_count,
                "receipt": build_context_receipt(
                    query=scenario.query,
                    filters=make_filters(
                        project=scenario.project,
                        domain=scenario.domain,
                        tags=scenario.tags,
                        include_stale=scenario.include_stale,
                        canonical_only=scenario.canonical_only,
                    ),
                    semantic_candidate_count=search_payload.get("count", 0),
                    graph_candidate_count=0,
                    selected_chunk_count=len(chunks),
                    omitted_count=omitted_count,
                    budget_chars=scenario.budget_chars,
                    used_chars=used_chars,
                    include_stale=scenario.include_stale,
                    graph_enabled=False,
                    max_hops=0,
                ),
            },
            "token_estimates": {
                "search_response_tokens": estimate_tokens(search_payload),
                "context_response_tokens": estimate_tokens(chunks),
                "estimate_method": ESTIMATE_METHOD,
            },
            "findings": findings,
        }
    except Exception as exc:
        return {
            "id": scenario.scenario_id,
            "description": scenario.description,
            "status": "fail",
            "expected_key": scenario.expected_key,
            "expected_key_found": False,
            "expected_key_rank": None,
            "search": {
                "count": search_payload.get("count", 0),
                "top_keys": [result.get("key") for result in search_payload.get("results", [])],
            },
            "context_pack": {
                "selected_chunk_count": len(chunks),
                "used_chars": sum(len(chunk.get("text") or "") for chunk in chunks),
                "budget_chars": scenario.budget_chars,
                "omitted_count": 0,
                "receipt": {},
            },
            "token_estimates": {
                "search_response_tokens": estimate_tokens(search_payload),
                "context_response_tokens": estimate_tokens(chunks),
                "estimate_method": ESTIMATE_METHOD,
            },
            "findings": [
                {
                    "code": "scenario_runtime_error",
                    "message": str(exc),
                }
            ],
        }
    finally:
        if cleanup:
            try:
                memory_manager.delete_memory(scenario.key)
            except Exception as cleanup_exc:
                LOGGER.warning(
                    "Failed to clean up agent reliability eval memory %s: %s",
                    scenario.key,
                    cleanup_exc,
                )


def _expected_key_rank(results: list[dict[str, Any]], expected_key: str) -> int | None:
    for index, result in enumerate(results, start=1):
        if result.get("key") == expected_key:
            return index
    return None


def _chunk_requests(results: list[dict[str, Any]], max_chunks: int) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for result in results:
        key = result.get("key")
        chunk_id = result.get("chunk_id")
        if key is None or chunk_id is None:
            continue
        ref = (str(key), int(chunk_id))
        if ref in seen:
            continue
        seen.add(ref)
        requests.append({"key": ref[0], "chunk_id": ref[1]})
        if len(requests) >= max(max_chunks, 1):
            break
    return requests


def _select_budgeted_chunks(chunks: list[dict[str, Any]], budget_chars: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    used_chars = 0
    budget = max(int(budget_chars), 1)
    for chunk in chunks:
        if not chunk.get("found"):
            continue
        text = chunk.get("text") or ""
        if used_chars + len(text) > budget:
            continue
        selected.append(chunk)
        used_chars += len(text)
    return selected
