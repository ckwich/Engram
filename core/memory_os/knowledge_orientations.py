"""Read-only EKC source and document orientation builders."""
from __future__ import annotations

import json
from typing import Any

from core.memory_os._records import list_records
from core.memory_os.document_catalog import enrich_document_record
from core.memory_os.knowledge_citations import normalize_knowledge_citations
from core.memory_os.knowledge_pr_read_model import (
    build_knowledge_pr_review_state,
    knowledge_pr_citations,
)
from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.project_identity import resolve_project_filter_values


ORIENTATION_INCOMPLETE_ERROR = {
    "code": "orientation_incomplete",
    "message": "Document orientation is missing required evidence or usable ingestion state.",
}


def build_source_orientation(
    ledger: MemoryOSLedger,
    *,
    project: str,
    focus: list[str] | None = None,
    max_records: int = 12,
) -> dict[str, Any]:
    """Build a source-first orientation from ledgered source and document records."""
    project_values = _project_values(ledger, project)
    sources = _matching_records(list_records(ledger, "sources"), project_values=project_values, focus=focus)
    documents = _matching_documents(
        list_records(ledger, "documents"),
        project_values=project_values,
        focus=focus,
        source_uris={_source_uri(source) for source in sources},
    )
    if not sources and not documents:
        return _no_answer("No source or document records matched the requested orientation.")
    chunks = list_records(ledger, "chunks")
    receipts = list_records(ledger, "retrieval_receipts")
    limited_documents = documents[: max(int(max_records), 1)]
    summaries, omissions = _document_summaries(
        limited_documents,
        chunks=chunks,
        receipts=receipts,
        require_usable=False,
    )
    source_items = _source_items(sources, summaries)
    knowledge_pr_state = build_knowledge_pr_review_state(
        ledger,
        project_values=project_values,
        document_ids={str(document.get("document_id") or "") for document in limited_documents},
        source_uris={_source_uri(source) for source in sources}
        | {str(document.get("source_uri") or "") for document in summaries}
        | {_source_uri(document) for document in limited_documents},
        limit=max_records,
    )
    answer = {
        "orientation_type": "source_orientation",
        "project": project,
        "source_count": len(source_items),
        "document_count": len(summaries),
        "chunk_count": sum(int(document["chunk_count"]) for document in summaries),
        "knowledge_pr_state": knowledge_pr_state,
        "sources": source_items,
        "documents": summaries,
    }
    citations = (_document_citations(summaries) or _source_citations(source_items)) + knowledge_pr_citations(knowledge_pr_state)
    return _orientation_result(
        answer=answer,
        citations=citations,
        omissions=omissions,
        source_reads=(
            len(sources)
            + len(limited_documents)
            + _related_read_count(summaries)
            + knowledge_pr_state["knowledge_pr_count"]
            + knowledge_pr_state["memory_ci_run_count"]
        ),
    )


def build_document_orientation(
    ledger: MemoryOSLedger,
    *,
    project: str,
    focus: list[str] | None = None,
    max_records: int = 12,
) -> dict[str, Any]:
    """Build a document-first orientation from ledgered document evidence."""
    project_values = _project_values(ledger, project)
    documents = _matching_documents(
        list_records(ledger, "documents"),
        project_values=project_values,
        focus=focus,
        source_uris=set(),
    )
    if not documents:
        return _no_answer("No document records matched the requested orientation.")
    chunks = list_records(ledger, "chunks")
    receipts = list_records(ledger, "retrieval_receipts")
    artifacts = _matching_document_artifacts(
        list_records(ledger, "knowledge_artifacts"),
        document_ids={str(document.get("document_id") or "") for document in documents},
        artifact_types={"document_evidence"},
    )
    completion_artifacts = _matching_document_artifacts(
        list_records(ledger, "knowledge_artifacts"),
        document_ids={str(document.get("document_id") or "") for document in documents},
        artifact_types={"document_completion"},
    )
    limited_documents = documents[: max(int(max_records), 1)]
    summaries, omissions = _document_summaries(
        limited_documents,
        chunks=chunks,
        receipts=receipts,
        artifacts=artifacts,
        completion_artifacts=completion_artifacts,
        require_usable=True,
    )
    knowledge_pr_state = build_knowledge_pr_review_state(
        ledger,
        project_values=project_values,
        document_ids={str(document.get("document_id") or "") for document in limited_documents},
        source_uris={_source_uri(document) for document in limited_documents},
        limit=max_records,
    )
    answer = {
        "orientation_type": "document_orientation",
        "project": project,
        "document_count": len(summaries),
        "document_evidence_artifact_count": len(artifacts),
        "document_completion_artifact_count": len(completion_artifacts),
        "chunk_count": sum(int(document["chunk_count"]) for document in summaries),
        "knowledge_pr_state": knowledge_pr_state,
        "documents": summaries,
    }
    return _orientation_result(
        answer=answer,
        citations=_document_citations(summaries) + knowledge_pr_citations(knowledge_pr_state),
        omissions=omissions,
        source_reads=(
            len(limited_documents)
            + _related_read_count(summaries)
            + knowledge_pr_state["knowledge_pr_count"]
            + knowledge_pr_state["memory_ci_run_count"]
        ),
        artifacts_read=len(artifacts) + len(completion_artifacts),
    )


def _orientation_result(
    *,
    answer: dict[str, Any],
    citations: list[dict[str, Any]],
    omissions: list[dict[str, str]],
    source_reads: int,
    artifacts_read: int = 0,
) -> dict[str, Any]:
    status = "partial" if omissions else "ok"
    return {
        "status": status,
        "answer": answer,
        "citations": normalize_knowledge_citations(citations, default_source="memory_os"),
        "omissions": omissions,
        "errors": [dict(ORIENTATION_INCOMPLETE_ERROR)] if omissions else [],
        "source_reads": source_reads,
        "artifacts_read": artifacts_read,
    }


def _no_answer(message: str) -> dict[str, Any]:
    return {
        "status": "no_answer",
        "answer": None,
        "citations": [],
        "omissions": [{"code": "no_orientation_evidence", "message": message}],
        "errors": [{"code": "no_orientation_evidence", "message": message}],
        "source_reads": 0,
    }


def _document_summaries(
    documents: list[dict[str, Any]],
    *,
    chunks: list[dict[str, Any]],
    receipts: list[dict[str, Any]],
    artifacts: list[dict[str, Any]] | None = None,
    completion_artifacts: list[dict[str, Any]] | None = None,
    require_usable: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    summaries: list[dict[str, Any]] = []
    omissions: list[dict[str, str]] = []
    for document in documents:
        document = enrich_document_record(document)
        document_id = str(document.get("document_id") or "")
        doc_chunks = [chunk for chunk in chunks if str(chunk.get("document_id") or "") == document_id]
        doc_artifacts = [
            artifact
            for artifact in artifacts or []
            if str(artifact.get("document_id") or "") == document_id
        ]
        doc_completion_artifacts = [
            artifact
            for artifact in completion_artifacts or []
            if str(artifact.get("document_id") or "") == document_id
        ]
        coverage = _select_document_coverage(
            document,
            [
                receipt
                for receipt in receipts
                if str(receipt.get("document_id") or "") == document_id
            ],
            doc_completion_artifacts,
        )
        if not doc_chunks:
            omissions.append(
                {
                    "code": "missing_chunks",
                    "message": f"{document_id} has no chunk evidence.",
                }
            )
        if coverage is None:
            omissions.append(
                {
                    "code": "missing_coverage",
                    "message": f"{document_id} has no coverage map.",
                }
            )
        usability = _usability_summary(document, doc_artifacts, doc_completion_artifacts)
        if require_usable and doc_artifacts and usability["status"] != "usable":
            omissions.append(
                {
                    "code": "document_not_usable",
                    "message": f"{document_id} has staged evidence but has not completed document ingestion.",
                }
            )
        source_ref = _source_ref(document)
        summaries.append(
            {
                "document_id": document_id,
                "title": document.get("title") or (document.get("document") or {}).get("title"),
                "source_uri": source_ref.get("source_uri"),
                "source_type": source_ref.get("source_type"),
                "document_catalog": document.get("document_catalog"),
                "page_count": _page_count(document, coverage),
                "chunk_count": len(doc_chunks),
                "document_evidence_artifact_count": len(doc_artifacts),
                "document_completion_artifact_count": len(doc_completion_artifacts),
                "coverage": _coverage_summary(coverage),
                "usability": usability,
            }
        )
    return summaries, omissions


def _select_document_coverage(
    document: dict[str, Any],
    receipts: list[dict[str, Any]],
    completion_artifacts: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not receipts:
        return None
    preferred_ids = []
    completion_receipt = document.get("completion_receipt")
    if isinstance(completion_receipt, dict) and completion_receipt.get("coverage_map_id"):
        preferred_ids.append(str(completion_receipt["coverage_map_id"]))
    for artifact in reversed(completion_artifacts):
        coverage_id = str(artifact.get("coverage_map_id") or "").strip()
        if coverage_id:
            preferred_ids.append(coverage_id)
        artifact_receipt = artifact.get("completion_receipt")
        if isinstance(artifact_receipt, dict) and artifact_receipt.get("coverage_map_id"):
            preferred_ids.append(str(artifact_receipt["coverage_map_id"]))
    for coverage_id in preferred_ids:
        for receipt in reversed(receipts):
            if str(receipt.get("coverage_map_id") or "") == coverage_id:
                return receipt
    complete = [receipt for receipt in receipts if receipt.get("coverage_complete") is True]
    if complete:
        return complete[-1]
    return receipts[-1]


def _source_items(
    sources: list[dict[str, Any]],
    document_summaries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_uri: dict[str, dict[str, Any]] = {}
    for source in sources:
        uri = _source_uri(source)
        if not uri:
            continue
        by_uri[uri] = {
            "source_uri": uri,
            "source_type": source.get("source_type"),
            "document_ids": [],
        }
    for document in document_summaries:
        uri = str(document.get("source_uri") or "")
        if not uri:
            continue
        by_uri.setdefault(
            uri,
            {
                "source_uri": uri,
                "source_type": document.get("source_type"),
                "document_ids": [],
            },
        )
        by_uri[uri]["document_ids"].append(document["document_id"])
    return list(by_uri.values())


def _document_citations(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for document in documents:
        citations.append(
            {
                "level": "document",
                "document_id": document.get("document_id"),
                "source_ref": document.get("source_uri"),
            }
        )
    return citations


def _source_citations(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"level": "document", "source_ref": source.get("source_uri")}
        for source in sources
        if source.get("source_uri")
    ]


def _matching_records(
    records: list[dict[str, Any]],
    *,
    project_values: set[str],
    focus: list[str] | None,
) -> list[dict[str, Any]]:
    return [
        record
        for record in records
        if _matches_project(record, project_values) and _matches_focus(record, focus)
    ]


def _matching_documents(
    records: list[dict[str, Any]],
    *,
    project_values: set[str],
    focus: list[str] | None,
    source_uris: set[str],
) -> list[dict[str, Any]]:
    matches = []
    for record in records:
        if not _matches_project(record, project_values):
            continue
        if _matches_focus(record, focus) or _source_uri(record) in source_uris:
            matches.append(record)
    return matches


def _matching_document_artifacts(
    artifacts: list[dict[str, Any]],
    *,
    document_ids: set[str],
    artifact_types: set[str],
) -> list[dict[str, Any]]:
    return [
        artifact
        for artifact in artifacts
        if str(artifact.get("document_id") or "") in document_ids
        and str(artifact.get("artifact_type") or "") in artifact_types
    ]


def _usability_summary(
    document: dict[str, Any],
    artifacts: list[dict[str, Any]],
    completion_artifacts: list[dict[str, Any]],
) -> dict[str, Any]:
    completion_artifact_id = (
        document.get("completion_artifact_id")
        or (completion_artifacts[-1].get("artifact_id") if completion_artifacts else None)
    )
    if document.get("usable") is True or document.get("ingestion_status") == "usable" or completion_artifact_id:
        return {
            "status": "usable",
            "usable": True,
            "completion_artifact_id": completion_artifact_id,
            "source_evidence_artifact_ids": [artifact.get("artifact_id") for artifact in artifacts],
        }
    if artifacts:
        return {
            "status": "staged",
            "usable": False,
            "completion_artifact_id": None,
            "source_evidence_artifact_ids": [artifact.get("artifact_id") for artifact in artifacts],
        }
    return {
        "status": "unknown",
        "usable": False,
        "completion_artifact_id": None,
        "source_evidence_artifact_ids": [],
    }


def _project_values(ledger: MemoryOSLedger, project: str) -> set[str]:
    return set(resolve_project_filter_values(ledger, project)) or {project}


def _matches_project(record: dict[str, Any], project_values: set[str]) -> bool:
    record_project = str(record.get("project") or "").strip()
    return not record_project or record_project in project_values


def _matches_focus(record: dict[str, Any], focus: list[str] | None) -> bool:
    terms = [str(term).strip().lower() for term in focus or [] if str(term).strip()]
    if not terms:
        return True
    haystack = json.dumps(record, ensure_ascii=False, sort_keys=True).lower()
    return any(term in haystack for term in terms)


def _source_ref(document: dict[str, Any]) -> dict[str, Any]:
    source_ref = document.get("source_ref")
    return source_ref if isinstance(source_ref, dict) else {}


def _source_uri(record: dict[str, Any]) -> str:
    if record.get("source_uri"):
        return str(record["source_uri"])
    source_ref = _source_ref(record)
    return str(source_ref.get("source_uri") or "")


def _page_count(document: dict[str, Any], coverage: dict[str, Any] | None) -> int | None:
    if coverage and coverage.get("page_count") is not None:
        return int(coverage["page_count"])
    inner = document.get("document") if isinstance(document.get("document"), dict) else {}
    if inner.get("page_count") is not None:
        return int(inner["page_count"])
    return None


def _coverage_summary(coverage: dict[str, Any] | None) -> dict[str, Any]:
    if not coverage:
        return {}
    return {
        key: coverage[key]
        for key in (
            "coverage_map_id",
            "page_count",
            "chunk_count",
            "claim_count",
            "visual_needed_pages",
            "interpreted_visual_count",
            "low_confidence_region_count",
            "skipped_region_count",
        )
        if key in coverage
    }


def _related_read_count(documents: list[dict[str, Any]]) -> int:
    return sum(int(document["chunk_count"]) for document in documents) + sum(
        1 for document in documents if document.get("coverage")
    )
