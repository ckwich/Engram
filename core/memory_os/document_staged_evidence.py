"""Read-only loading of staged document evidence artifacts for resume flows."""
from __future__ import annotations

import json
from typing import Any

from core.document_coverage import page_number_from_ref
from core.memory_os._records import list_records


DOCUMENT_STAGED_EVIDENCE_SCHEMA_VERSION = "2026-05-21.document-staged-evidence.v1"


def load_staged_document_evidence(
    ledger: Any,
    store: Any,
    document_id: str,
    *,
    artifact_id: str | None = None,
) -> dict[str, Any]:
    """Load staged document evidence and its original review packets without writing."""
    normalized_document_id = str(document_id or "").strip()
    artifacts = _find_document_artifacts(ledger, normalized_document_id, artifact_id)
    payloads: list[dict[str, Any]] = []
    review_packets: list[dict[str, Any]] = []
    blocking_issues: list[dict[str, Any]] = []
    for artifact in artifacts:
        artifact_record_id = str(artifact.get("artifact_id") or "")
        try:
            payload = _read_artifact_payload(store, artifact)
        except Exception as exc:
            blocking_issues.append(
                {
                    "code": "staged_artifact_unreadable",
                    "message": "The staged document artifact payload could not be read.",
                    "artifact_id": artifact_record_id,
                    "error_type": type(exc).__name__,
                }
            )
            continue
        if not isinstance(payload, dict):
            blocking_issues.append(
                {
                    "code": "staged_artifact_unreadable",
                    "message": "The staged document artifact payload could not be read.",
                    "artifact_id": artifact_record_id,
                }
            )
            continue
        payloads.append(payload)
        packet = payload.get("review_packet")
        if isinstance(packet, dict):
            review_packets.append(packet)
        else:
            blocking_issues.append(
                {
                    "code": "staged_review_packet_missing",
                    "message": "The staged document artifact does not include a review packet.",
                    "artifact_id": artifact_record_id,
                }
            )

    review_packets = sorted(review_packets, key=_review_packet_sort_key)
    complete = not blocking_issues and staged_review_packets_complete(review_packets)
    return {
        "schema_version": DOCUMENT_STAGED_EVIDENCE_SCHEMA_VERSION,
        "document_id": normalized_document_id,
        "artifact_id": artifact_id,
        "artifact_count": len(artifacts),
        "payload_count": len(payloads),
        "review_packet_count": len(review_packets),
        "artifacts": artifacts,
        "review_packets": review_packets,
        "complete": complete,
        "blocking_issues": blocking_issues,
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "error": None if not blocking_issues else blocking_issues[0],
    }


def staged_review_packets_complete(review_packets: list[dict[str, Any]]) -> bool:
    """Return whether staged review packets represent a complete document window set."""
    if not review_packets:
        return False
    sorted_packets = sorted(review_packets, key=_review_packet_sort_key)
    covered_pages: set[int] = set()
    page_count = 0
    saw_terminal_window = False
    for packet in sorted_packets:
        disassembly = packet.get("disassembly") if isinstance(packet.get("disassembly"), dict) else {}
        document = disassembly.get("document") if isinstance(disassembly.get("document"), dict) else {}
        try:
            page_count = max(page_count, int(document.get("page_count") or 0))
        except (TypeError, ValueError):
            pass
        for page in disassembly.get("pages") or []:
            page_number = page_number_from_ref(page) if isinstance(page, dict) else None
            if page_number is not None:
                covered_pages.add(page_number)
        resume = disassembly.get("resume") if isinstance(disassembly.get("resume"), dict) else {}
        if resume.get("has_more") is False:
            saw_terminal_window = True
    if not saw_terminal_window:
        return False
    if page_count <= 0:
        return True
    return set(range(1, page_count + 1)).issubset(covered_pages)


def _find_document_artifacts(ledger: Any, document_id: str, artifact_id: str | None) -> list[dict[str, Any]]:
    matches = [
        artifact
        for artifact in list_records(ledger, "knowledge_artifacts")
        if str(artifact.get("document_id") or "") == document_id
        and str(artifact.get("artifact_type") or "") == "document_evidence"
        and str(artifact.get("review_state") or "") == "ledgered_evidence"
    ]
    matches = sorted(matches, key=_artifact_sort_key)
    if artifact_id:
        normalized_artifact_id = str(artifact_id).strip()
        if not any(str(artifact.get("artifact_id") or "") == normalized_artifact_id for artifact in matches):
            return []
    return matches


def _read_artifact_payload(store: Any, artifact: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(artifact, dict):
        return None
    content_ref = str(artifact.get("content_ref") or "").strip()
    if not content_ref:
        return None
    decoded = json.loads(store.read_bytes(content_ref).decode("utf-8"))
    return decoded if isinstance(decoded, dict) else None


def _artifact_sort_key(artifact: dict[str, Any]) -> tuple[int, str, str]:
    pages = [
        page_number_from_ref(ref)
        for ref in artifact.get("page_refs") or []
        if isinstance(ref, dict)
    ]
    pages = [page for page in pages if page is not None]
    min_page = min(pages) if pages else 10**9
    return (
        min_page,
        str(artifact.get("created_at") or ""),
        str(artifact.get("artifact_id") or ""),
    )


def _review_packet_sort_key(packet: dict[str, Any]) -> tuple[int, str]:
    disassembly = packet.get("disassembly") if isinstance(packet.get("disassembly"), dict) else {}
    document = disassembly.get("document") if isinstance(disassembly.get("document"), dict) else {}
    page_range = document.get("page_range") if isinstance(document.get("page_range"), dict) else {}
    try:
        start = int(page_range.get("start") or 10**9)
    except (TypeError, ValueError):
        start = 10**9
    return (start, str(document.get("document_id") or ""))
