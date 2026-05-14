"""EKC v0 project-orientation eval helpers."""
from __future__ import annotations

from typing import Any

DEFAULT_QUESTIONS = (
    "What is Engram's current architecture direction?",
    "What are the active constraints around reviewed writes?",
    "What should I know before modifying the MCP interface?",
    "What decisions already exist about local-first memory?",
    "What are the open questions for project capsule implementation?",
)


def run_project_orientation_eval(
    runtime: Any,
    *,
    project: str,
    human_ratings: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    search_only = [
        _run_search_orientation_workflow(runtime, project, question)
        for question in DEFAULT_QUESTIONS
    ]
    ekc = [_run_ekc_question(runtime, project, question) for question in DEFAULT_QUESTIONS]
    search_summary = _summarize_search(search_only)
    ekc_summary = _summarize_ekc(ekc)
    reduction = _tool_call_reduction(
        search_summary["tool_calls"],
        ekc_summary["tool_calls"],
    )
    human_usefulness = _summarize_human_usefulness(DEFAULT_QUESTIONS, human_ratings)
    citation_preserved = (
        ekc_summary["citation_presence_rate"] >= search_summary["citation_presence_rate"]
    )
    return {
        "schema_version": "2026-05-13.ekc-v0.eval.v1",
        "project": project,
        "question_count": len(DEFAULT_QUESTIONS),
        "search_only": search_summary,
        "ekc": ekc_summary,
        "tool_call_reduction_rate": reduction,
        "citation_presence_preserved": citation_preserved,
        "human_usefulness": human_usefulness,
        "continuation_threshold": {
            "tool_call_reduction_target": 0.3,
            "requires_citation_presence_preserved": True,
            "requires_human_usefulness_preserved": True,
        },
        "passes": (
            reduction >= 0.3
            and citation_preserved
            and human_usefulness["preserved"] is True
        ),
    }


def _run_search_orientation_workflow(
    runtime: Any,
    project: str,
    question: str,
) -> dict[str, Any]:
    tool_calls = 0
    initial = runtime.search_memories(question, project=project, limit=3)
    tool_calls += 1
    results = list(initial.get("results") or [])[:3]
    chunks = []
    for result in results:
        chunks.append(runtime.retrieve_chunk(result.get("key"), result.get("chunk_id")))
        tool_calls += 1
    if results:
        # Project orientation normally needs a second pass for constraints,
        # decisions, or related context after the first result set is read.
        if hasattr(runtime, "context_pack"):
            runtime.context_pack(
                f"{question} constraints decisions citations",
                project=project,
                max_chunks=3,
            )
        else:
            runtime.search_memories(
                f"{question} constraints decisions citations",
                project=project,
                limit=3,
            )
        tool_calls += 1
    return {
        "question": question,
        "tool_calls": tool_calls,
        "result_count": int(initial.get("count") or 0),
        "has_citation": any(result.get("citation") for result in results)
        or any(chunk.get("citation") for chunk in chunks if isinstance(chunk, dict)),
    }


def _run_ekc_question(runtime: Any, project: str, question: str) -> dict[str, Any]:
    payload = runtime.query_knowledge(
        {
            "ask": {
                "goal": question,
                "task_type": "project_orientation",
                "project": project,
            }
        }
    )
    return {
        "question": question,
        "tool_calls": 1,
        "status": payload.get("status"),
        "has_citation": bool(payload.get("citations")),
        "schema_valid": payload.get("answer") is not None
        or payload.get("status")
        in {
            "no_answer",
            "partial",
            "schema_failed",
            "policy_denied",
            "budget_exceeded",
            "unavailable",
        },
    }


def _summarize_search(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "tool_calls": sum(int(row["tool_calls"]) for row in rows),
        "questions_with_results": sum(1 for row in rows if row["result_count"] > 0),
        "citation_presence_rate": _rate(rows, "has_citation"),
    }


def _summarize_ekc(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "tool_calls": sum(int(row["tool_calls"]) for row in rows),
        "ok_or_partial_count": sum(1 for row in rows if row["status"] in {"ok", "partial"}),
        "schema_valid_rate": _rate(rows, "schema_valid"),
        "citation_presence_rate": _rate(rows, "has_citation"),
    }


def _rate(rows: list[dict[str, Any]], field: str) -> float:
    if not rows:
        return 0.0
    return sum(1 for row in rows if row.get(field)) / len(rows)


def _tool_call_reduction(search_calls: int, ekc_calls: int) -> float:
    if search_calls <= 0:
        return 0.0
    return max((search_calls - ekc_calls) / search_calls, 0.0)


def _summarize_human_usefulness(
    questions: tuple[str, ...],
    ratings: dict[str, dict[str, float]] | None,
) -> dict[str, Any]:
    if not ratings:
        return {
            "status": "not_scored",
            "preserved": False,
            "reason": "Human ratings are required for the EKC v0 continuation gate.",
        }
    rows = [ratings.get(question, {}) for question in questions]
    search_avg = sum(float(row.get("search_only", 0.0)) for row in rows) / len(questions)
    ekc_avg = sum(float(row.get("ekc", 0.0)) for row in rows) / len(questions)
    return {
        "status": "scored",
        "search_only_average": search_avg,
        "ekc_average": ekc_avg,
        "preserved": ekc_avg >= search_avg,
    }
