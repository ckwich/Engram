"""EKC project-orientation and 1.0 contract eval helpers."""
from __future__ import annotations

from typing import Any

from core.memory_os._records import upsert_record
from core.memory_os.knowledge_contract import (
    REQUEST_SCHEMA_VERSION,
    RESPONSE_SCHEMA_VERSION,
    validate_knowledge_response,
)

DEFAULT_QUESTIONS = (
    "What is Engram's current architecture direction?",
    "What are the active constraints around reviewed writes?",
    "What should I know before modifying the MCP interface?",
    "What decisions already exist about local-first memory?",
    "What are the open questions for project capsule implementation?",
)
DEFAULT_WORKFLOW_SCENARIOS = (
    {
        "scenario_id": "project_orientation",
        "task_type": "project_orientation",
        "goal": "Orient me to this project.",
        "focus": ["architecture"],
    },
    {
        "scenario_id": "source_orientation",
        "task_type": "source_orientation",
        "goal": "Orient me to available source evidence.",
        "focus": ["source"],
    },
    {
        "scenario_id": "document_orientation",
        "task_type": "document_orientation",
        "goal": "Orient me to available document evidence.",
        "focus": ["document"],
    },
    {
        "scenario_id": "review_preparation",
        "task_type": "review_preparation",
        "goal": "Prepare review evidence for promotion decisions.",
        "focus": ["review"],
    },
    {
        "scenario_id": "evidence_audit",
        "task_type": "evidence_audit",
        "goal": "Audit evidence coverage and citation health.",
        "focus": ["evidence"],
    },
    {
        "scenario_id": "graph_evidence",
        "task_type": "graph_evidence",
        "goal": "Show bounded graph evidence and contradictions.",
        "focus": ["claim"],
    },
    {
        "scenario_id": "entity_profile",
        "task_type": "entity_profile",
        "goal": "Build a cited entity profile.",
        "focus": ["entity"],
    },
    {
        "scenario_id": "decision_packet",
        "task_type": "decision_packet",
        "goal": "Build a cited decision packet.",
        "focus": ["decision"],
    },
    {
        "scenario_id": "implementation_context",
        "task_type": "implementation_context",
        "goal": "Build cited implementation context.",
        "focus": ["implementation"],
    },
    {
        "scenario_id": "evidence_bundle",
        "task_type": "evidence_bundle",
        "goal": "Build a cited evidence bundle.",
        "focus": ["evidence"],
    },
)
STABLE_EKC_TASK_TYPES = tuple(scenario["task_type"] for scenario in DEFAULT_WORKFLOW_SCENARIOS)


def seed_knowledge_contract_eval_fixtures(runtime: Any, *, project: str) -> dict[str, Any]:
    """Seed the smallest real Memory OS records needed for every EKC workflow."""
    seeded: list[dict[str, str]] = []
    runtime.store_memory(
        key="ekc_eval_architecture_direction",
        content=(
            "# Architecture Direction\n\n"
            "Engram architecture direction is daemon-owned Memory OS runtime. "
            "Decision: keep query_knowledge stable task types tied to eval scenarios. "
            "Reviewed writes stay explicit and local-first memory remains the product boundary."
        ),
        title="EKC Eval Architecture Direction",
        tags=["ekc", "eval", "architecture", "decision", "reviewed"],
        project=project,
        domain="architecture",
        status="accepted",
        canonical=True,
        force=True,
    )
    seeded.append({"table": "memories", "id": "ekc_eval_architecture_direction"})
    runtime.store_memory(
        key="ekc_eval_implementation_context",
        content=(
            "# Implementation Context\n\n"
            "Implementation context for query_knowledge eval coverage. "
            "Next step: keep protocol task_types synchronized with the EKC eval pack."
        ),
        title="EKC Eval Implementation Context",
        tags=["ekc", "eval", "implementation"],
        project=project,
        domain="implementation",
        status="accepted",
        canonical=True,
        force=True,
    )
    seeded.append({"table": "memories", "id": "ekc_eval_implementation_context"})

    source_uri = "file:///eval/source_document_evidence.md"
    document_id = "doc_eval_source_document_evidence"
    upsert_record(
        runtime.ledger,
        "sources",
        "source:ekc_eval",
        {
            "source_uri": source_uri,
            "source_type": "markdown",
            "title": "Source Document Evidence Review",
            "project": project,
        },
    )
    upsert_record(
        runtime.ledger,
        "documents",
        document_id,
        {
            "document_id": document_id,
            "title": "Source Document Evidence Review",
            "project": project,
            "source_ref": {"source_uri": source_uri, "source_type": "markdown"},
            "document": {"page_count": 1},
        },
    )
    upsert_record(
        runtime.ledger,
        "chunks",
        f"{document_id}:chunk:0",
        {
            "chunk_record_id": f"{document_id}:chunk:0",
            "document_id": document_id,
            "memory_key": "ekc_eval_document_evidence",
            "chunk_id": 0,
            "project": project,
            "domain": "document",
            "status": "accepted",
            "text": "Source document evidence supports review, entity, and claim coverage.",
        },
    )
    upsert_record(
        runtime.ledger,
        "retrieval_receipts",
        f"coverage:{document_id}",
        {
            "coverage_map_id": f"coverage:{document_id}",
            "document_id": document_id,
            "page_count": 1,
            "chunk_count": 1,
            "claim_count": 1,
            "visual_needed_pages": [],
            "interpreted_visual_count": 0,
            "low_confidence_region_count": 0,
            "skipped_region_count": 0,
        },
    )
    upsert_record(
        runtime.ledger,
        "drafts",
        "draft:ekc_eval_review",
        {
            "draft_id": "draft:ekc_eval_review",
            "record_type": "document_draft",
            "document_id": document_id,
            "project": project,
            "review_status": "candidate",
            "promotion_required": True,
            "proposed_memories": [{"key": "ekc_eval_review_memory"}],
            "candidate_graph_edges": [
                {
                    "proposal_id": "proposal:ekc_eval_review_claim",
                    "from_ref": {"kind": "document", "key": document_id},
                    "to_ref": {"kind": "claim", "key": "ekc_eval_claim"},
                    "edge_type": "supports",
                    "confidence": 0.91,
                    "evidence": "Review draft supports the EKC eval claim.",
                    "source": "knowledge_eval.seed",
                    "status": "draft",
                }
            ],
        },
    )
    upsert_record(
        runtime.ledger,
        "graph_edges",
        "edge:ekc_eval_claim",
        {
            "edge_id": "edge:ekc_eval_claim",
            "from_ref": {"kind": "claim", "key": "ekc_eval_claim"},
            "to_ref": {"kind": "claim", "key": "query_knowledge_eval"},
            "edge_type": "supports",
            "confidence": 0.93,
            "evidence": "Claim graph evidence supports stable query_knowledge eval coverage.",
            "source": "knowledge_eval.seed",
            "status": "active",
            "created_by": "eval",
            "created_at": "2026-05-14T00:00:00+00:00",
            "updated_at": "2026-05-14T00:00:00+00:00",
            "project": project,
        },
    )
    upsert_record(
        runtime.ledger,
        "entities",
        "entity:ekc_eval_entity",
        {
            "entity_id": "entity:ekc_eval_entity",
            "canonical_name": "Entity Evaluation Concept",
            "entity_type": "concept",
            "project": project,
            "source_refs": [{"document_id": document_id, "source_ref": source_uri}],
        },
    )
    seeded.extend(
        [
            {"table": "sources", "id": "source:ekc_eval"},
            {"table": "documents", "id": document_id},
            {"table": "chunks", "id": f"{document_id}:chunk:0"},
            {"table": "retrieval_receipts", "id": f"coverage:{document_id}"},
            {"table": "drafts", "id": "draft:ekc_eval_review"},
            {"table": "graph_edges", "id": "edge:ekc_eval_claim"},
            {"table": "entities", "id": "entity:ekc_eval_entity"},
        ]
    )
    return {
        "schema_version": "2026-05-14.ekc-eval-fixtures.v1",
        "project": project,
        "records": seeded,
    }


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


def run_knowledge_contract_eval(
    runtime: Any,
    *,
    project: str,
    human_ratings: dict[str, dict[str, float]] | None = None,
    workflow_scenarios: tuple[dict[str, Any], ...] | None = None,
) -> dict[str, Any]:
    """Run the EKC 1.0 continuation gate across every proven workflow."""
    project_orientation = run_project_orientation_eval(
        runtime,
        project=project,
        human_ratings=human_ratings,
    )
    scenarios = tuple(workflow_scenarios or DEFAULT_WORKFLOW_SCENARIOS)
    workflow_rows = [
        _run_ekc_workflow_scenario(runtime, project, scenario)
        for scenario in scenarios
    ]
    workflow_coverage = _summarize_workflows(workflow_rows)
    passes = project_orientation["passes"] is True and workflow_coverage["passes"] is True
    return {
        "schema_version": "2026-05-14.ekc-1.0.eval.v1",
        "contract_release": "1.0",
        "compatibility_contract_versions": {
            "request": REQUEST_SCHEMA_VERSION,
            "response": RESPONSE_SCHEMA_VERSION,
        },
        "project": project,
        "stability": "stable" if passes else "beta",
        "project_orientation": project_orientation,
        "workflow_coverage": workflow_coverage,
        "release_threshold": {
            "requires_project_orientation_pass": True,
            "requires_all_workflows_ok_or_partial": True,
            "requires_schema_valid_rate": 1.0,
            "requires_citation_presence_rate": 1.0,
        },
        "passes": passes,
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
    validation = validate_knowledge_response(payload)
    return {
        "question": question,
        "tool_calls": 1,
        "status": payload.get("status"),
        "has_citation": bool(payload.get("citations")),
        "schema_valid": validation["valid"],
        "schema_errors": validation.get("errors", []),
    }


def _run_ekc_workflow_scenario(
    runtime: Any,
    project: str,
    scenario: dict[str, Any],
) -> dict[str, Any]:
    task_type = str(scenario["task_type"])
    payload = runtime.query_knowledge(
        {
            "request_id": f"eval-{scenario['scenario_id']}",
            "ask": {
                "goal": scenario["goal"],
                "task_type": task_type,
                "project": project,
                "focus": list(scenario.get("focus") or []),
            },
        }
    )
    validation = validate_knowledge_response(payload)
    planner = payload.get("planner") if isinstance(payload.get("planner"), dict) else {}
    planner_strategy = str(planner.get("strategy") or "")
    active_memory_write_performed = bool(payload.get("active_memory_write_performed", False))
    write_performed = bool(payload.get("write_performed", False))
    return {
        "scenario_id": scenario["scenario_id"],
        "task_type": task_type,
        "tool_calls": 1,
        "status": payload.get("status"),
        "has_citation": bool(payload.get("citations")),
        "schema_valid": validation["valid"],
        "schema_errors": validation.get("errors", []),
        "planner_strategy": planner_strategy,
        "planner_strategy_matches_task": planner_strategy == task_type,
        "write_performed": write_performed,
        "active_memory_write_performed": active_memory_write_performed,
        "read_only": not active_memory_write_performed,
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


def _summarize_workflows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok_or_partial_count = sum(1 for row in rows if row["status"] in {"ok", "partial"})
    schema_valid_rate = _rate(rows, "schema_valid")
    citation_required_rows = [row for row in rows if row["status"] in {"ok", "partial"}]
    citation_presence_rate = _rate(citation_required_rows, "has_citation")
    planner_strategy_match_rate = _rate(rows, "planner_strategy_matches_task")
    active_memory_write_free_rate = _rate(rows, "read_only")
    passes = (
        ok_or_partial_count == len(rows)
        and schema_valid_rate == 1.0
        and citation_presence_rate == 1.0
        and planner_strategy_match_rate == 1.0
        and active_memory_write_free_rate == 1.0
    )
    return {
        "scenario_count": len(rows),
        "tool_calls": sum(int(row["tool_calls"]) for row in rows),
        "ok_or_partial_count": ok_or_partial_count,
        "schema_valid_rate": schema_valid_rate,
        "citation_presence_rate": citation_presence_rate,
        "planner_strategy_match_rate": planner_strategy_match_rate,
        "active_memory_write_free_rate": active_memory_write_free_rate,
        "scenarios": rows,
        "passes": passes,
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
