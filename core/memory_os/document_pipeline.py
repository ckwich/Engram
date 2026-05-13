"""Materialized document-intelligence jobs for the Memory OS ledger."""
from __future__ import annotations

import json
from typing import Any

from core.chunker import chunk_content_with_metadata
from core.memory_os._records import hash_payload, upsert_record
from core.memory_os.content_store import ContentAddressedStore
from core.memory_os.jobs import JobQueue
from core.memory_os.ledger import MemoryOSLedger


class DocumentPipeline:
    """Persist document evidence and coverage maps without promoting memory."""

    def __init__(self, ledger: MemoryOSLedger, store: ContentAddressedStore) -> None:
        self.ledger = ledger
        self.store = store
        self.jobs = JobQueue(ledger)

    def materialize_document_job(
        self,
        disassembly: dict[str, Any],
        *,
        visual_artifacts: list[dict[str, Any]] | None = None,
        understanding_packet: dict[str, Any] | None = None,
        licensing: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(disassembly, dict):
            raise ValueError("disassembly must be an object")
        if disassembly.get("active_memory_write_performed") is True:
            raise ValueError("document pipeline cannot materialize active memory writes")
        document = dict(disassembly.get("document") or {})
        source = dict(disassembly.get("source") or {})
        document_id = str(document.get("document_id") or "")
        if not document_id:
            raise ValueError("disassembly.document.document_id is required")

        job = self.jobs.enqueue(
            "document_materialization",
            {"document_id": document_id, "source_uri": source.get("source_uri")},
        )
        raw_artifact_id = self.store.put_bytes(
            _json_bytes(disassembly),
            suffix=".json",
        )
        text = dict(disassembly.get("text") or {})
        text_content = str(text.get("content") or "")
        text_artifact_id = (
            self.store.put_bytes(text_content.encode("utf-8"), suffix=".txt")
            if text_content
            else None
        )
        normalized_licensing = dict(licensing or {})
        document_record = {
            "document_id": document_id,
            "title": document.get("title"),
            "source_ref": source,
            "document": document,
            "raw_disassembly_artifact_id": raw_artifact_id,
            "text_artifact_id": text_artifact_id,
            "licensing": normalized_licensing,
            "active_memory_write_performed": False,
        }
        upsert_record(self.ledger, "sources", _record_id("source", source), source)
        upsert_record(self.ledger, "documents", document_id, document_record)
        chunks = self._store_chunks(document_id, text_content)
        for page in disassembly.get("pages") or []:
            if isinstance(page, dict):
                page_id = f"{document_id}:page:{int(page.get('page_number', 0)):05d}"
                upsert_record(self.ledger, "sections", page_id, {"document_id": document_id, **page})
        for artifact in visual_artifacts or []:
            if isinstance(artifact, dict):
                artifact_id = str(artifact.get("artifact_id") or _record_id("visual", artifact))
                upsert_record(self.ledger, "drafts", artifact_id, artifact)
        if isinstance(understanding_packet, dict):
            packet_id = str(understanding_packet.get("packet_id") or _record_id("packet", understanding_packet))
            upsert_record(self.ledger, "drafts", packet_id, understanding_packet)

        coverage_map = self._coverage_map(
            disassembly,
            chunks=chunks,
            visual_artifacts=visual_artifacts or [],
            understanding_packet=understanding_packet or {},
            licensing=normalized_licensing,
        )
        upsert_record(self.ledger, "retrieval_receipts", coverage_map["coverage_map_id"], coverage_map)
        job = self.jobs.succeed(job["job_id"], result={"coverage_map_id": coverage_map["coverage_map_id"]})
        return {
            **job,
            "document": document_record,
            "coverage_map": coverage_map,
            "active_memory_write_performed": False,
        }

    def _store_chunks(self, document_id: str, text_content: str) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        if not text_content.strip():
            return chunks
        for chunk in chunk_content_with_metadata(text_content):
            chunk_id = int(chunk["chunk_id"])
            record = {
                "chunk_record_id": f"{document_id}:chunk:{chunk_id}",
                "document_id": document_id,
                "chunk_id": chunk_id,
                "text": str(chunk["text"]),
                "heading_path": list(chunk.get("heading_path") or []),
                "chunk_kind": str(chunk.get("chunk_kind") or "section"),
            }
            upsert_record(self.ledger, "chunks", record["chunk_record_id"], record)
            chunks.append(record)
        return chunks

    @staticmethod
    def _coverage_map(
        disassembly: dict[str, Any],
        *,
        chunks: list[dict[str, Any]],
        visual_artifacts: list[dict[str, Any]],
        understanding_packet: dict[str, Any],
        licensing: dict[str, Any],
    ) -> dict[str, Any]:
        document = dict(disassembly.get("document") or {})
        pages = [page for page in disassembly.get("pages") or [] if isinstance(page, dict)]
        quality = dict(disassembly.get("quality_seed") or {})
        graph_edges = understanding_packet.get("candidate_graph_edges") or []
        low_confidence_warnings = understanding_packet.get("low_confidence_warnings") or []
        low_confidence_visuals = [
            artifact
            for artifact in visual_artifacts
            if isinstance(artifact.get("confidence"), (int, float)) and artifact["confidence"] < 0.5
        ]
        skipped = [
            page
            for page in pages
            if page.get("visual_review_needed") and not _page_has_visual_artifact(page, visual_artifacts)
        ]
        coverage = {
            "coverage_map_id": _record_id(
                "coverage",
                {
                    "document_id": document.get("document_id"),
                    "chunks": len(chunks),
                    "visuals": [artifact.get("artifact_id") for artifact in visual_artifacts],
                },
            ),
            "document_id": document.get("document_id"),
            "page_count": int(document.get("page_count") or len(pages)),
            "pages_reported": len(pages),
            "text_page_count": len(quality.get("text_pages") or []),
            "visual_needed_pages": list(quality.get("visual_review_needed_pages") or []),
            "interpreted_visual_count": len(visual_artifacts),
            "table_count": sum(1 for artifact in visual_artifacts if artifact.get("artifact_type") == "table"),
            "figure_count": sum(1 for artifact in visual_artifacts if artifact.get("artifact_type") == "figure"),
            "chunk_count": len(chunks),
            "claim_count": len(understanding_packet.get("claim_candidates") or []),
            "concept_count": len(understanding_packet.get("concept_candidates") or []),
            "graph_proposal_count": len(graph_edges),
            "low_confidence_region_count": len(low_confidence_warnings) + len(low_confidence_visuals),
            "skipped_region_count": len(skipped),
            "licensing": licensing,
            "active_memory_write_performed": False,
        }
        return coverage


def _page_has_visual_artifact(page: dict[str, Any], visual_artifacts: list[dict[str, Any]]) -> bool:
    page_number = page.get("page_number")
    for artifact in visual_artifacts:
        provenance = artifact.get("provenance") if isinstance(artifact.get("provenance"), dict) else {}
        if artifact.get("page_number") == page_number or provenance.get("page_number") == page_number:
            return True
    return False


def _record_id(prefix: str, payload: Any) -> str:
    return f"{prefix}:{hash_payload(payload).removeprefix('sha256:')}"


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
