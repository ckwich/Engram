"""Focused EKC query and knowledge-artifact service for Memory OS."""
from __future__ import annotations

from typing import Any, Callable

from core.memory_os._records import read_record
from core.memory_os.knowledge_artifact_families import (
    SUPPORTED_ARTIFACT_FAMILIES,
    build_artifact_family_packet,
)
from core.memory_os.knowledge_audit import build_evidence_audit
from core.memory_os.knowledge_citations import normalize_knowledge_citations
from core.memory_os.knowledge_contract import (
    RESPONSE_SCHEMA_VERSION,
    no_answer_response,
    normalize_knowledge_request,
    ok_response,
)
from core.memory_os.knowledge_graph import build_graph_evidence
from core.memory_os.knowledge_orientations import (
    build_document_orientation,
    build_source_orientation,
)
from core.memory_os.knowledge_planner import build_planner_receipt
from core.memory_os.knowledge_review import build_review_preparation
from core.memory_os.project_capsule_artifact import build_project_capsule_artifact


class KnowledgeQueryService:
    """Serve read-only EKC packets and explicit project-capsule materialization."""

    def __init__(
        self,
        *,
        ledger: Any,
        transactions: Any,
        knowledge_artifacts: Any,
        search_memories: Callable[..., dict[str, Any]],
    ) -> None:
        self.ledger = ledger
        self.transactions = transactions
        self.knowledge_artifacts = knowledge_artifacts
        self.search_memories = search_memories

    def query_knowledge(self, request: dict[str, Any]) -> dict[str, Any]:
        """Return an EKC v0 typed project capsule response without writing memory."""
        normalized = normalize_knowledge_request(request)
        if normalized.get("contract_version") == RESPONSE_SCHEMA_VERSION:
            return normalized

        ask = normalized["ask"]
        if ask["task_type"] == "source_orientation":
            return _orientation_response(
                normalized,
                build_source_orientation(
                    self.ledger,
                    project=ask["project"],
                    focus=ask["focus"],
                    max_records=int(normalized["budget"].get("max_source_reads", 12)),
                ),
                strategy="source_orientation",
            )
        if ask["task_type"] == "document_orientation":
            return _orientation_response(
                normalized,
                build_document_orientation(
                    self.ledger,
                    project=ask["project"],
                    focus=ask["focus"],
                    max_records=int(normalized["budget"].get("max_source_reads", 12)),
                ),
                strategy="document_orientation",
            )
        if ask["task_type"] == "review_preparation":
            return _orientation_response(
                normalized,
                build_review_preparation(
                    self.ledger,
                    project=ask["project"],
                    focus=ask["focus"],
                    max_records=int(normalized["budget"].get("max_source_reads", 12)),
                ),
                strategy="review_preparation",
            )
        if ask["task_type"] == "evidence_audit":
            return _orientation_response(
                normalized,
                build_evidence_audit(
                    self.ledger,
                    project=ask["project"],
                    focus=ask["focus"],
                    max_records=int(normalized["budget"].get("max_source_reads", 12)),
                ),
                strategy="evidence_audit",
            )
        if ask["task_type"] == "graph_evidence":
            return _orientation_response(
                normalized,
                build_graph_evidence(
                    self.ledger,
                    project=ask["project"],
                    focus=ask["focus"],
                    max_records=int(normalized["budget"].get("max_source_reads", 12)),
                ),
                strategy="graph_evidence",
            )
        if ask["task_type"] in SUPPORTED_ARTIFACT_FAMILIES:
            return _orientation_response(
                normalized,
                build_artifact_family_packet(
                    self.ledger,
                    artifact_family=ask["task_type"],
                    project=ask["project"],
                    focus=ask["focus"],
                    max_records=int(normalized["budget"].get("max_source_reads", 12)),
                ),
                strategy=ask["task_type"],
            )
        persisted = self.knowledge_artifacts.read_latest_artifact(
            project=ask["project"],
            artifact_type="project_capsule",
            artifact_version="v0",
            require_fresh=True,
        )
        if persisted is not None:
            return _project_capsule_response(
                normalized,
                artifact_record=persisted,
                planner=build_planner_receipt(
                    strategy="project_orientation",
                    methods_used=["persisted_artifact"],
                    request_budget=normalized["budget"],
                ),
                artifacts_built=0,
                artifacts_read=1,
                source_reads=0,
            )

        built = self._build_project_capsule_artifact(normalized)
        if built.get("response") is not None:
            return built["response"]

        return _project_capsule_response(
            normalized,
            artifact_record={"artifact": built["artifact"]},
            planner=built["planner"],
            artifacts_built=1,
            artifacts_read=0,
            source_reads=len(built["results"]),
        )

    def materialize_project_capsule_artifact(self, request: dict[str, Any]) -> dict[str, Any]:
        """Explicitly persist a project capsule artifact for later read-only EKC serving."""
        normalized = normalize_knowledge_request(request)
        if normalized.get("contract_version") == RESPONSE_SCHEMA_VERSION:
            return {**normalized, "write_performed": False}

        built = self._build_project_capsule_artifact(normalized)
        if built.get("response") is not None:
            return {**built["response"], "write_performed": False}

        artifact_record = self.knowledge_artifacts.store_artifact(
            built["artifact"],
            request_id=normalized["request_id"],
        )
        receipt = self.transactions.promote(
            operation_kind="materialize_knowledge_artifact",
            proposed_writes=[
                {"table": "knowledge_artifacts", "id": artifact_record["artifact_id"]},
            ],
            idempotency_key=f"materialize_knowledge_artifact:{artifact_record['artifact_id']}",
            affected_refs=[
                {
                    "kind": "knowledge_artifact",
                    "artifact_id": artifact_record["artifact_id"],
                    "project": artifact_record["project"],
                },
            ],
        )
        return {
            "status": "ok",
            "write_performed": True,
            "artifact_record": artifact_record,
            "transaction_id": receipt["transaction_id"],
            "error": None,
        }

    def _build_project_capsule_artifact(self, normalized: dict[str, Any]) -> dict[str, Any]:
        budget = normalized["budget"]
        ask = normalized["ask"]
        query = _knowledge_search_query(ask)
        max_source_reads = max(int(budget.get("max_source_reads", 12)), 1)
        search = self.search_memories(
            query,
            limit=max_source_reads * 2,
            project=ask["project"],
            include_stale=False,
            retrieval_mode="hybrid",
        )
        results = _prepare_knowledge_results(
            self.ledger,
            list(search.get("results") or []),
            ask=ask,
            limit=max_source_reads,
        )
        planner = build_planner_receipt(
            strategy="project_orientation",
            methods_used=[
                "project_capsule_artifact",
                "hybrid_search",
                "chunk_hydration",
                "focus_rerank",
            ],
            request_budget=budget,
        )
        if not results:
            return {
                "response": no_answer_response(
                    request_id=normalized["request_id"],
                    code="no_project_sources",
                    message=f"No eligible project sources found for {ask['project']}.",
                    planner=planner,
                )
            }

        context_packet = {
            "profile": {"id": "project_capsule"},
            "context": {
                "chunks": results,
                "citations": [
                    result.get("citation")
                    for result in results
                    if result.get("citation")
                ],
            },
            "warnings": [],
        }
        artifact = build_project_capsule_artifact(
            project=ask["project"],
            goal=ask["goal"],
            focus=ask["focus"],
            context_packet=context_packet,
            quality_payload={"summary": {}, "issue_count": 0},
            source_snapshot_id="memory_os:latest",
        )
        return {"artifact": artifact, "results": results, "planner": planner, "response": None}


def _knowledge_search_query(ask: dict[str, Any]) -> str:
    parts = [ask.get("goal") or "project orientation", ask.get("project") or ""]
    parts.extend(ask.get("focus") or [])
    return " ".join(str(part).strip() for part in parts if str(part).strip())


def _prepare_knowledge_results(
    ledger: Any,
    results: list[dict[str, Any]],
    *,
    ask: dict[str, Any],
    limit: int,
) -> list[dict[str, Any]]:
    focus_terms = _knowledge_focus_terms(ask)
    hydrated: list[dict[str, Any]] = []
    for result in results:
        item = dict(result)
        key = str(item.get("key") or "")
        chunk_id = int(item.get("chunk_id") or 0)
        chunk_record = read_record(ledger, "chunks", f"{key}:chunk:{chunk_id}") if key else None
        if chunk_record:
            text = str(chunk_record.get("text") or item.get("snippet") or "")
            item["text"] = text
            item["snippet"] = text[:300]
            item["title"] = chunk_record.get("title") or item.get("title") or key
            item["tags"] = chunk_record.get("tags") or item.get("tags") or []
            item["project"] = chunk_record.get("project") or item.get("project")
            item["domain"] = chunk_record.get("domain") or item.get("domain")
            item["_ekc_updated_at"] = str(chunk_record.get("updated_at") or "")
            item["_ekc_focus_score"] = _knowledge_focus_score(chunk_record, focus_terms)
        else:
            item["text"] = str(item.get("text") or item.get("snippet") or "")
            item["_ekc_updated_at"] = ""
            item["_ekc_focus_score"] = _knowledge_focus_score(item, focus_terms)
        hydrated.append(item)

    hydrated.sort(
        key=lambda item: (
            int(item.get("_ekc_focus_score") or 0),
            str(item.get("_ekc_updated_at") or ""),
            float(item.get("score") or 0.0),
        ),
        reverse=True,
    )
    return [
        {key: value for key, value in item.items() if not str(key).startswith("_ekc_")}
        for item in hydrated[: max(int(limit), 1)]
    ]


def _knowledge_focus_terms(ask: dict[str, Any]) -> list[str]:
    return [str(term).strip().lower() for term in ask.get("focus") or [] if str(term).strip()]


def _knowledge_focus_score(record: dict[str, Any], focus_terms: list[str]) -> int:
    if not focus_terms:
        return 0
    haystack = str(record).lower()
    return sum(1 for term in focus_terms if term in haystack)


def _project_capsule_response(
    normalized: dict[str, Any],
    *,
    artifact_record: dict[str, Any],
    planner: dict[str, Any],
    artifacts_built: int,
    artifacts_read: int,
    source_reads: int,
) -> dict[str, Any]:
    artifact = dict(artifact_record.get("artifact") or {})
    answer = {
        "project": artifact.get("project"),
        "summary": artifact.get("summary") or "",
        "current_goals": list(artifact.get("current_goals") or []),
        "active_decisions": list(artifact.get("active_decisions") or []),
        "constraints": list(artifact.get("constraints") or []),
        "open_questions": list(artifact.get("open_questions") or []),
        "important_entities": list(artifact.get("important_entities") or []),
        "recent_changes": list(artifact.get("recent_changes") or []),
    }
    citations = _artifact_response_citations(artifact_record)
    staleness = dict(artifact.get("staleness") or {})
    partial = staleness.get("state") != "fresh" or not answer["summary"]
    freshness = {
        "state": staleness.get("state") or "unknown",
        "artifact_generated_at": artifact.get("generated_at"),
        "source_snapshot_id": artifact.get("source_snapshot_id"),
    }
    if artifact_record.get("artifact_id"):
        freshness["artifact_id"] = artifact_record["artifact_id"]
        freshness["artifact_persisted_at"] = artifact_record.get("created_at")
    return ok_response(
        request_id=normalized["request_id"],
        answer=answer,
        citations=citations,
        freshness=freshness,
        budget_used={
            "artifacts_built": artifacts_built,
            "artifacts_read": artifacts_read,
            "source_reads": source_reads,
            "tokens_out_estimate": len(str(answer)) // 4,
        },
        planner=planner,
        partial=partial,
        errors=[]
        if not partial
        else [
            {
                "code": "partial_capsule",
                "message": "Capsule is missing one or more optional orientation fields.",
            }
        ],
    )


def _artifact_response_citations(artifact_record: dict[str, Any]) -> list[dict[str, Any]]:
    artifact = dict(artifact_record.get("artifact") or {})
    citations = []
    artifact_id = artifact_record.get("artifact_id")
    if artifact_id:
        citations.append(
            {
                "citation_id": "artifact_001",
                "level": "artifact",
                "artifact_id": artifact_id,
                "artifact_type": artifact_record.get("artifact_type"),
                "artifact_version": artifact_record.get("artifact_version"),
                "project": artifact_record.get("project"),
                "source": "memory_os",
            }
        )
    citations.extend(
        citation
        for citation in list(artifact.get("citations") or [])
        if isinstance(citation, dict)
    )
    return normalize_knowledge_citations(citations, default_source="memory_os")


def _orientation_response(
    normalized: dict[str, Any],
    orientation: dict[str, Any],
    *,
    strategy: str,
) -> dict[str, Any]:
    planner = build_planner_receipt(
        strategy=strategy,
        methods_used=["ledger_records"],
        request_budget=normalized["budget"],
        omissions=list(orientation.get("omissions") or []),
    )
    if orientation.get("status") == "no_answer":
        error = (orientation.get("errors") or [{}])[0]
        return no_answer_response(
            request_id=normalized["request_id"],
            code=str(error.get("code") or "no_orientation_evidence"),
            message=str(error.get("message") or "No orientation evidence was available."),
            planner=planner,
        )
    answer = dict(orientation.get("answer") or {})
    return ok_response(
        request_id=normalized["request_id"],
        answer=answer,
        citations=list(orientation.get("citations") or []),
        freshness={"state": "fresh", "source_snapshot_id": "memory_os:latest"},
        budget_used={
            "artifacts_built": 0,
            "artifacts_read": int(orientation.get("artifacts_read") or 0),
            "source_reads": int(orientation.get("source_reads") or 0),
            "tokens_out_estimate": len(str(answer)) // 4,
        },
        planner=planner,
        partial=orientation.get("status") == "partial",
        errors=list(orientation.get("errors") or []),
    )
