"""Evidence-gated higher-level EKC artifact family packets."""
from __future__ import annotations

import json
import re
from typing import Any

from core.memory_os._records import list_records
from core.memory_os.knowledge_audit import build_evidence_audit
from core.memory_os.knowledge_citations import normalize_knowledge_citations
from core.memory_os.ledger import MemoryOSLedger


SUPPORTED_ARTIFACT_FAMILIES = {
    "entity_profile",
    "decision_packet",
    "implementation_context",
    "evidence_bundle",
}


def build_artifact_family_packet(
    ledger: MemoryOSLedger,
    *,
    artifact_family: str,
    project: str,
    focus: list[str] | None = None,
    max_records: int = 12,
) -> dict[str, Any]:
    """Build a higher-level artifact packet only from cited evidence."""
    family = str(artifact_family or "").strip()
    if family not in SUPPORTED_ARTIFACT_FAMILIES:
        return _no_answer("unsupported_artifact_family", f"Unsupported artifact family: {family}")

    if family == "entity_profile":
        items, citations = _entity_profile_items(ledger, project=project, focus=focus, max_records=max_records)
    elif family == "decision_packet":
        items, citations = _decision_packet_items(ledger, project=project, focus=focus, max_records=max_records)
    elif family == "implementation_context":
        items, citations = _implementation_context_items(ledger, project=project, focus=focus, max_records=max_records)
    else:
        items, citations = _evidence_bundle_items(ledger, project=project, focus=focus, max_records=max_records)

    if not items or not citations:
        return _no_answer("missing_cited_evidence", f"{family} requires cited evidence before it can be built.")

    audit = build_evidence_audit(
        ledger,
        project=project,
        focus=None,
        max_records=max_records,
    )
    audit_status = str(audit.get("status") or "unknown")
    audit_optional_unavailable = family == "implementation_context" and audit_status == "no_answer"
    status = "ok" if audit_status == "ok" or audit_optional_unavailable else "partial"
    answer = {
        "artifact_family": family,
        "project": project,
        "items": items,
        "evidence_audit": {
            "status": audit_status,
            "required": not audit_optional_unavailable,
            "finding_count": len(((audit.get("answer") or {}).get("findings") or []))
            if isinstance(audit.get("answer"), dict)
            else 0,
        },
        "write_performed": False,
        "active_memory_write_performed": False,
    }
    if family == "implementation_context":
        answer["brief"] = _implementation_context_brief(items)
        for item in items:
            item.pop("_brief_text", None)
    omissions = []
    errors = []
    if audit_optional_unavailable:
        omissions.append(
            {
                "code": "evidence_audit_unavailable",
                "message": "No artifact, coverage, or draft audit records matched this implementation_context request.",
            }
        )
    elif status == "partial":
        errors.append(
            {
                "code": "evidence_audit_not_clear",
                "message": f"{family} has cited evidence, but the evidence audit status is {audit_status}.",
            }
        )
    return {
        "status": status,
        "answer": answer,
        "citations": normalize_knowledge_citations(citations, default_source="memory_os"),
        "omissions": omissions,
        "errors": errors,
        "source_reads": len(items),
        "write_performed": False,
        "active_memory_write_performed": False,
    }


def _no_answer(code: str, message: str) -> dict[str, Any]:
    return {
        "status": "no_answer",
        "answer": None,
        "citations": [],
        "omissions": [{"code": code, "message": message}],
        "errors": [{"code": code, "message": message}],
        "source_reads": 0,
        "write_performed": False,
        "active_memory_write_performed": False,
    }


def _entity_profile_items(
    ledger: MemoryOSLedger,
    *,
    project: str,
    focus: list[str] | None,
    max_records: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    entities = _matching_records(list_records(ledger, "entities"), project=project, focus=focus)
    items: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    for entity in entities[: max(int(max_records), 1)]:
        refs = _source_refs(entity)
        if not refs:
            continue
        items.append(
            {
                "entity_id": entity.get("entity_id"),
                "canonical_name": entity.get("canonical_name") or entity.get("label"),
                "entity_type": entity.get("entity_type") or entity.get("type"),
                "source_ref_count": len(refs),
            }
        )
        citations.extend(_citations_from_refs(refs))
    return items, citations


def _decision_packet_items(
    ledger: MemoryOSLedger,
    *,
    project: str,
    focus: list[str] | None,
    max_records: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    chunks = [
        chunk
        for chunk in _matching_records(list_records(ledger, "chunks"), project=project, focus=focus)
        if _has_decision_signal(chunk)
    ]
    items = [
        {
            "key": chunk.get("memory_key") or chunk.get("key") or chunk.get("parent_key"),
            "chunk_id": int(chunk.get("chunk_id") or 0),
            "text_preview": str(chunk.get("text") or "")[:240],
        }
        for chunk in chunks[: max(int(max_records), 1)]
    ]
    citations = [
        {
            "level": "chunk",
            "key": item["key"],
            "chunk_id": item["chunk_id"],
        }
        for item in items
        if item.get("key") is not None
    ]
    return items, citations


def _implementation_context_items(
    ledger: MemoryOSLedger,
    *,
    project: str,
    focus: list[str] | None,
    max_records: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    chunks = _matching_records(list_records(ledger, "chunks"), project=project, focus=focus)
    items = []
    for chunk in chunks[: max(int(max_records), 1)]:
        text = str(chunk.get("text") or "")
        items.append(
            {
                "key": chunk.get("memory_key") or chunk.get("key") or chunk.get("parent_key"),
                "chunk_id": int(chunk.get("chunk_id") or 0),
                "domain": chunk.get("domain"),
                "text_preview": text[:240],
                "updated_at": chunk.get("updated_at"),
                "_brief_text": text,
            }
        )
    citations = [
        {
            "level": "chunk",
            "key": item["key"],
            "chunk_id": item["chunk_id"],
        }
        for item in items
        if item.get("key") is not None
    ]
    return items, citations


def _evidence_bundle_items(
    ledger: MemoryOSLedger,
    *,
    project: str,
    focus: list[str] | None,
    max_records: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    documents = _matching_records(list_records(ledger, "documents"), project=project, focus=focus)
    receipts = list_records(ledger, "retrieval_receipts")
    receipt_by_doc = {str(receipt.get("document_id") or ""): receipt for receipt in receipts}
    items: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    for document in documents[: max(int(max_records), 1)]:
        document_id = str(document.get("document_id") or "")
        receipt = receipt_by_doc.get(document_id, {})
        items.append(
            {
                "document_id": document_id,
                "title": document.get("title") or (document.get("document") or {}).get("title"),
                "coverage_map_id": receipt.get("coverage_map_id"),
                "claim_count": int(receipt.get("claim_count") or 0),
            }
        )
        citations.append(_document_citation(document))
    return items, citations


def _source_refs(record: dict[str, Any]) -> list[dict[str, Any]]:
    refs = record.get("source_refs")
    return [ref for ref in refs or [] if isinstance(ref, dict)]


def _citations_from_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for ref in refs:
        if ref.get("document_id") or ref.get("source_ref"):
            citations.append(
                {
                    "level": "document",
                    "document_id": ref.get("document_id"),
                    "source_ref": ref.get("source_ref"),
                }
            )
        elif ref.get("key") is not None:
            citations.append(
                {
                    "level": "chunk",
                    "key": ref.get("key"),
                    "chunk_id": int(ref.get("chunk_id") or 0),
                }
            )
    return citations


def _document_citation(document: dict[str, Any]) -> dict[str, Any]:
    source_ref = document.get("source_ref") if isinstance(document.get("source_ref"), dict) else {}
    return {
        "level": "document",
        "document_id": document.get("document_id"),
        "source_ref": source_ref.get("source_uri"),
    }


def _matching_records(
    records: list[dict[str, Any]],
    *,
    project: str,
    focus: list[str] | None,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for record in records:
        record_project = str(record.get("project") or "").strip()
        if record_project and record_project != project:
            continue
        if _matches_focus(record, focus):
            matches.append(record)
    matches.sort(
        key=lambda record: (
            _focus_score(record, focus),
            str(record.get("updated_at") or record.get("created_at") or ""),
        ),
        reverse=True,
    )
    return matches


def _matches_focus(record: dict[str, Any], focus: list[str] | None) -> bool:
    terms = [str(term).strip().lower() for term in focus or [] if str(term).strip()]
    if not terms:
        return True
    haystack = json.dumps(record, ensure_ascii=False, sort_keys=True).lower()
    return any(term in haystack for term in terms)


def _focus_score(record: dict[str, Any], focus: list[str] | None) -> int:
    terms = [str(term).strip().lower() for term in focus or [] if str(term).strip()]
    if not terms:
        return 0
    haystack = json.dumps(record, ensure_ascii=False, sort_keys=True).lower()
    return sum(1 for term in terms if term in haystack)


def _has_decision_signal(chunk: dict[str, Any]) -> bool:
    haystack = json.dumps(chunk, ensure_ascii=False, sort_keys=True).lower()
    return "decision" in haystack


def _implementation_context_brief(items: list[dict[str, Any]]) -> dict[str, Any]:
    previews = [
        str(item.get("_brief_text") or item.get("text_preview") or "").strip()
        for item in items
    ]
    previews = [preview for preview in previews if preview]
    return {
        "summary": _first_sentence(previews[0]) if previews else "",
        "next_actions": _extract_next_actions(previews),
        "relevant_files": _extract_file_refs(previews),
    }


def _first_sentence(text: str) -> str:
    normalized = " ".join(str(text).split())
    for delimiter in (". ", "? ", "! "):
        if delimiter in normalized:
            return normalized.split(delimiter, 1)[0] + delimiter.strip()
    return normalized


def _extract_next_actions(texts: list[str]) -> list[str]:
    patterns = (
        "next recommended step:",
        "next recommended polish:",
        "next recommended target:",
        "next recommended slice:",
        "next step:",
        "todo:",
        "action:",
    )
    for text in texts:
        actions: list[str] = []
        lower = text.lower()
        for pattern in patterns:
            start = lower.find(pattern)
            if start < 0:
                continue
            action = text[start + len(pattern) :].strip()
            action = _clean_next_action(action)
            if action and action not in actions:
                actions.append(action)
        for match in re.finditer(
            r"\b(?:main\s+)?next\s+polish\s+target\s+is\s+",
            text,
            flags=re.IGNORECASE,
        ):
            action = _clean_next_action(text[match.end() :].strip(), first_sentence=True)
            if action and action not in actions:
                actions.append(action)
        if actions:
            return actions
    return []


def _clean_next_action(text: str, *, first_sentence: bool = False) -> str:
    action = re.split(
        r"\s+(?:files changed|validation performed|validation|repo|branch|commit):",
        str(text or ""),
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    action = " ".join(action.split()).strip(" -")
    if first_sentence:
        action = _first_sentence(action)
    return action.strip()


def _extract_file_refs(texts: list[str]) -> list[str]:
    files: list[str] = []
    for text in texts:
        for match in re.findall(r"\b(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\b", text):
            cleaned = match.rstrip(".,;:")
            if not re.search(r"\.[A-Za-z0-9]{1,8}$", cleaned):
                continue
            if any("." in part and not part.startswith(".") for part in cleaned.split("/")[:-1]):
                continue
            if cleaned and cleaned not in files:
                files.append(cleaned)
    return files
