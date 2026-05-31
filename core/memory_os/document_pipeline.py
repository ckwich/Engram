"""Materialized document-intelligence jobs for the Memory OS ledger."""
from __future__ import annotations

import json
from typing import Any

from core.chunker import chunk_content_with_metadata
from core.document_coverage import artifact_covers_capability, page_number_from_ref
from core.memory_os._records import hash_payload, list_records, read_record, upsert_record
from core.memory_os.content_store import ContentAddressedStore
from core.memory_os.document_catalog import (
    enrich_document_chunk_metadata,
    enrich_document_identity_metadata,
)
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
        ingestion_id: str | None = None,
        window_index: int | None = None,
        project: str | None = None,
        domain: str | None = None,
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
        existing_document = read_record(self.ledger, "documents", document_id)
        if isinstance(existing_document, dict):
            for field in ("document_catalog", "project", "domain", "tags", "metadata"):
                if field in existing_document:
                    document_record[field] = existing_document[field]
        document_record = enrich_document_identity_metadata(
            document_record,
            project=project,
            domain=domain,
        )
        upsert_record(self.ledger, "sources", _record_id("source", source), source)
        upsert_record(self.ledger, "documents", document_id, document_record)
        chunks = self._store_chunks(
            document_id,
            text_content,
            page_range=document.get("page_range") if isinstance(document.get("page_range"), dict) else None,
            ingestion_id=ingestion_id,
            window_index=window_index,
            document=document_record,
            project=project,
            domain=domain,
        )
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

    def _store_chunks(
        self,
        document_id: str,
        text_content: str,
        *,
        page_range: dict[str, Any] | None = None,
        ingestion_id: str | None = None,
        window_index: int | None = None,
        document: dict[str, Any] | None = None,
        project: str | None = None,
        domain: str | None = None,
    ) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = []
        if not text_content.strip():
            return chunks
        normalized_page_range = dict(page_range or {})
        page_start = _safe_nonnegative_int(normalized_page_range.get("start"), default=0)
        chunk_base = page_start * 10000 if page_start > 0 else 0
        use_window_record_id = ingestion_id is not None or window_index is not None
        record_prefix_parts = [document_id]
        if use_window_record_id and ingestion_id is not None:
            record_prefix_parts.append(f"ingestion:{ingestion_id}")
        if use_window_record_id:
            record_prefix_parts.append(_window_label(window_index))
        record_prefix = ":".join(record_prefix_parts)
        for chunk in chunk_content_with_metadata(text_content):
            local_chunk_id = int(chunk["chunk_id"])
            chunk_id = chunk_base + local_chunk_id
            record = {
                "chunk_record_id": f"{record_prefix}:chunk:{chunk_id}",
                "document_id": document_id,
                "ingestion_id": ingestion_id,
                "window_index": window_index,
                "page_range": normalized_page_range,
                "local_chunk_id": local_chunk_id,
                "chunk_id": chunk_id,
                "text": str(chunk["text"]),
                "heading_path": list(chunk.get("heading_path") or []),
                "chunk_kind": str(chunk.get("chunk_kind") or "section"),
            }
            record = enrich_document_chunk_metadata(
                record,
                document or {"document_id": document_id},
                project=project,
                domain=domain,
            )
            if not use_window_record_id:
                existing = self._existing_window_chunk(
                    document_id=document_id,
                    chunk_id=chunk_id,
                    text=record["text"],
                )
                if existing is not None:
                    record = {
                        **record,
                        "chunk_record_id": existing["chunk_record_id"],
                        "ingestion_id": existing.get("ingestion_id"),
                        "window_index": existing.get("window_index"),
                        "page_range": existing.get("page_range") or record.get("page_range"),
                        "local_chunk_id": existing.get("local_chunk_id", record.get("local_chunk_id")),
                    }
            upsert_record(self.ledger, "chunks", record["chunk_record_id"], record)
            chunks.append(record)
        return chunks

    def _existing_window_chunk(
        self,
        *,
        document_id: str,
        chunk_id: int,
        text: str,
    ) -> dict[str, Any] | None:
        matches = [
            chunk
            for chunk in list_records(self.ledger, "chunks")
            if str(chunk.get("document_id") or "") == document_id
            and chunk.get("chunk_id") == chunk_id
            and str(chunk.get("text") or "") == text
            and str(chunk.get("ingestion_id") or "").strip()
            and str(chunk.get("chunk_record_id") or "").strip()
        ]
        if not matches:
            return None
        return sorted(matches, key=lambda chunk: str(chunk.get("chunk_record_id") or ""))[0]

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
        visual_needed_pages = sorted(int(page) for page in quality.get("visual_review_needed_pages") or [])
        ocr_needed_pages = sorted(
            {
                int(page)
                for page in [
                    *list(quality.get("low_text_pages") or []),
                    *list(quality.get("no_text_pages") or []),
                ]
            }
        )
        table_needed_pages = sorted(int(page) for page in quality.get("table_candidate_pages") or [])
        visual_covered_pages = _covered_pages(visual_needed_pages, visual_artifacts)
        ocr_covered_pages = _covered_pages(ocr_needed_pages, visual_artifacts, capability="ocr_text")
        table_covered_pages = _covered_pages(table_needed_pages, visual_artifacts, capability="table_structure")
        missing_visual_pages = _missing_pages(visual_needed_pages, visual_covered_pages)
        missing_ocr_pages = _missing_pages(ocr_needed_pages, ocr_covered_pages)
        missing_table_pages = _missing_pages(table_needed_pages, table_covered_pages)
        coverage = {
            "coverage_map_id": _record_id(
                "coverage",
                {
                    "document_id": document.get("document_id"),
                    "chunks": len(chunks),
                    "chunk_record_ids": [chunk.get("chunk_record_id") for chunk in chunks],
                    "page_ranges": [chunk.get("page_range") for chunk in chunks if chunk.get("page_range")],
                    "visuals": [artifact.get("artifact_id") for artifact in visual_artifacts],
                },
            ),
            "document_id": document.get("document_id"),
            "page_count": int(document.get("page_count") or len(pages)),
            "pages_reported": len(pages),
            "text_page_count": len(quality.get("text_pages") or []),
            "visual_needed_pages": visual_needed_pages,
            "visual_covered_pages": visual_covered_pages,
            "missing_visual_pages": missing_visual_pages,
            "ocr_needed_pages": ocr_needed_pages,
            "ocr_covered_pages": ocr_covered_pages,
            "missing_ocr_pages": missing_ocr_pages,
            "table_needed_pages": table_needed_pages,
            "table_covered_pages": table_covered_pages,
            "missing_table_pages": missing_table_pages,
            "coverage_complete": not (missing_visual_pages or missing_ocr_pages or missing_table_pages),
            "interpreted_visual_count": len(visual_artifacts),
            "table_count": sum(1 for artifact in visual_artifacts if artifact.get("artifact_type") == "table"),
            "figure_count": sum(1 for artifact in visual_artifacts if artifact.get("artifact_type") == "figure"),
            "chunk_count": len(chunks),
            "claim_count": len(understanding_packet.get("claim_candidates") or []),
            "concept_count": len(understanding_packet.get("concept_candidates") or []),
            "graph_proposal_count": len(graph_edges),
            "low_confidence_region_count": len(low_confidence_warnings) + len(low_confidence_visuals),
            "skipped_region_count": len(missing_visual_pages),
            "licensing": licensing,
            "active_memory_write_performed": False,
        }
        return coverage


def _covered_pages(
    page_numbers: list[int],
    visual_artifacts: list[dict[str, Any]],
    *,
    capability: str | None = None,
) -> list[int]:
    covered: set[int] = set()
    requested = set(page_numbers)
    for artifact in visual_artifacts:
        if capability is not None and not artifact_covers_capability(artifact, capability):
            continue
        provenance = artifact.get("provenance") if isinstance(artifact.get("provenance"), dict) else {}
        page_number = page_number_from_ref(provenance)
        if page_number in requested:
            covered.add(page_number)
    return sorted(covered)


def _missing_pages(required_pages: list[int], covered_pages: list[int]) -> list[int]:
    return sorted(set(required_pages) - set(covered_pages))


def _record_id(prefix: str, payload: Any) -> str:
    return f"{prefix}:{hash_payload(payload).removeprefix('sha256:')}"


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _safe_nonnegative_int(value: Any, *, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def _window_label(window_index: Any) -> str:
    if window_index is None:
        return "window:single"
    try:
        return f"window:{int(window_index):04d}"
    except (TypeError, ValueError):
        return f"window:{window_index}"
