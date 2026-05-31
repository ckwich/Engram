"""Focused metadata repair services for daemon-owned Memory OS records."""
from __future__ import annotations

from typing import Any

from core.memory_os._records import list_records, now_iso, read_record, upsert_record
from core.memory_os.document_catalog import (
    enrich_document_chunk_metadata,
    enrich_document_identity_metadata,
)


class MetadataRepairService:
    """Review and apply Memory OS metadata repair operations."""

    def __init__(self, *, ledger: Any, retrieval: Any) -> None:
        self.ledger = ledger
        self.retrieval = retrieval

    def repair_memory_metadata(self, keys: list[str], *, dry_run: bool = True) -> dict[str, Any]:
        """Return simple Memory OS metadata repair receipts."""
        repairs = []
        repaired_count = 0
        for key in _string_list(keys):
            exists = read_record(self.ledger, "memories", key) is not None
            repaired = bool(exists and not dry_run)
            repaired_count += 1 if repaired else 0
            repairs.append({"key": key, "exists": exists, "repaired": repaired, "issues": []})
        return {
            "requested_count": len(repairs),
            "repaired_count": repaired_count,
            "dry_run": dry_run,
            "repairs": repairs,
            "error": None,
        }

    def repair_document_metadata(
        self,
        *,
        project: str | None = None,
        document_ids: list[str] | None = None,
        accept: bool = False,
        approved_by: str | None = None,
    ) -> dict[str, Any]:
        """Review or apply project/domain/catalog metadata repairs for documents."""
        selected_ids = set(_string_list(document_ids or []))
        documents = [
            document
            for document in list_records(self.ledger, "documents")
            if _document_metadata_repair_candidate(document, selected_ids)
        ]
        repairs = [
            self._document_metadata_repair_plan(document, project=project)
            for document in documents
        ]
        repairs = [repair for repair in repairs if repair["changed"]]
        if not accept:
            return {
                "status": "prepared",
                "requested_count": len(selected_ids) if selected_ids else len(documents),
                "repair_count": len(repairs),
                "repaired_document_count": 0,
                "repairs": [_repair_summary(repair) for repair in repairs],
                "write_performed": False,
                "active_memory_write_performed": False,
                "error": None,
            }
        reviewer = str(approved_by or "").strip()
        if not reviewer:
            return {
                "status": "schema_failed",
                "requested_count": len(selected_ids) if selected_ids else len(documents),
                "repair_count": len(repairs),
                "repaired_document_count": 0,
                "repairs": [_repair_summary(repair) for repair in repairs],
                "write_performed": False,
                "active_memory_write_performed": False,
                "error": {
                    "code": "approved_by_required",
                    "message": "approved_by is required when accept=True.",
                },
            }
        repaired_count = 0
        retrieval_receipts = []
        now = now_iso()
        for repair in repairs:
            document_id = str(repair["document_id"])
            document = repair["document"]
            document["metadata_repaired_at"] = now
            document["metadata_repaired_by"] = reviewer
            upsert_record(self.ledger, "documents", document_id, document)
            for chunk_record_id in repair.get("duplicate_chunk_record_ids") or []:
                self._delete_record("chunks", str(chunk_record_id))
            for chunk in repair["chunks"]:
                upsert_record(self.ledger, "chunks", str(chunk["chunk_record_id"]), chunk)
            for job in repair["jobs"]:
                job["updated_at"] = now
                job["metadata_repaired_at"] = now
                job["metadata_repaired_by"] = reviewer
                upsert_record(self.ledger, "jobs", str(job.get("ingestion_id") or job.get("job_id")), job)
            if repair["chunks"] or repair.get("duplicate_chunk_record_ids"):
                retrieval_receipts.append(
                    self.retrieval.upsert_chunk_records(document_id, repair["chunks"])
                )
            repaired_count += 1
        return {
            "status": "ok",
            "requested_count": len(selected_ids) if selected_ids else len(documents),
            "repair_count": len(repairs),
            "repaired_document_count": repaired_count,
            "repairs": [_repair_summary(repair) for repair in repairs],
            "retrieval_receipts": retrieval_receipts,
            "write_performed": bool(repairs),
            "active_memory_write_performed": False,
            "error": None,
        }

    def _document_metadata_repair_plan(
        self,
        document: dict[str, Any],
        *,
        project: str | None,
    ) -> dict[str, Any]:
        document_id = str(document.get("document_id") or "")
        desired_document = enrich_document_identity_metadata(
            document,
            project=project,
            prefer_catalog_domain=True,
        )
        desired_project = desired_document.get("project")
        desired_domain = desired_document.get("domain")
        current_chunks = [
            chunk
            for chunk in list_records(self.ledger, "chunks")
            if str(chunk.get("document_id") or "") == document_id
        ]
        chunks = [
            enrich_document_chunk_metadata(
                chunk,
                desired_document,
                project=str(desired_project or "") or None,
                domain=str(desired_domain or "") or None,
                prefer_catalog_domain=True,
            )
            for chunk in current_chunks
        ]
        chunks, duplicate_chunk_record_ids = _dedupe_document_chunks(chunks)
        jobs = []
        for job in list_records(self.ledger, "jobs"):
            if job.get("record_type") != "document_ingestion":
                continue
            if str(job.get("document_id") or "") != document_id:
                continue
            updated = dict(job)
            if desired_project is not None:
                updated["project"] = desired_project
            if desired_domain is not None:
                updated["domain"] = desired_domain
            jobs.append(updated)
        current_jobs = [
            job
            for job in list_records(self.ledger, "jobs")
            if job.get("record_type") == "document_ingestion"
            and str(job.get("document_id") or "") == document_id
        ]
        changed = (
            desired_document != document
            or chunks != current_chunks
            or bool(duplicate_chunk_record_ids)
            or jobs != current_jobs
        )
        return {
            "document_id": document_id,
            "title": desired_document.get("title"),
            "project": desired_project,
            "domain": desired_domain,
            "tags": desired_document.get("tags") or [],
            "chunk_count": len(chunks),
            "duplicate_chunk_count": len(duplicate_chunk_record_ids),
            "duplicate_chunk_record_ids": duplicate_chunk_record_ids,
            "job_count": len(jobs),
            "changed": changed,
            "document": desired_document,
            "chunks": chunks,
            "jobs": jobs,
        }

    def _delete_record(self, table: str, record_id: str) -> None:
        self.ledger.initialize()
        with self.ledger.connect() as conn:
            conn.execute(f"DELETE FROM {table} WHERE id = ?", (record_id,))  # nosec B608
            conn.commit()


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    raw_items = value.split(",") if isinstance(value, str) else list(value)
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _document_metadata_repair_candidate(document: dict[str, Any], selected_ids: set[str]) -> bool:
    document_id = str(document.get("document_id") or "").strip()
    if not document_id:
        return False
    if selected_ids and document_id not in selected_ids:
        return False
    if selected_ids:
        return True
    catalog = document.get("document_catalog") if isinstance(document.get("document_catalog"), dict) else {}
    return catalog.get("content_form") in {"book", "transcript"} and (
        document.get("usable") is True or document.get("ingestion_status") == "usable"
    )


def _repair_summary(repair: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_id": repair.get("document_id"),
        "title": repair.get("title"),
        "project": repair.get("project"),
        "domain": repair.get("domain"),
        "tags": repair.get("tags") or [],
        "chunk_count": repair.get("chunk_count", 0),
        "duplicate_chunk_count": repair.get("duplicate_chunk_count", 0),
        "job_count": repair.get("job_count", 0),
        "changed": bool(repair.get("changed")),
    }


def _dedupe_document_chunks(chunks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    by_signature: dict[tuple[str, int, str], list[dict[str, Any]]] = {}
    for chunk in chunks:
        try:
            chunk_id = int(chunk.get("chunk_id"))
        except (TypeError, ValueError):
            chunk_id = -1
        signature = (
            str(chunk.get("document_id") or ""),
            chunk_id,
            str(chunk.get("text") or ""),
        )
        by_signature.setdefault(signature, []).append(chunk)
    kept: list[dict[str, Any]] = []
    duplicate_ids: list[str] = []
    for matches in by_signature.values():
        ordered = sorted(matches, key=_document_chunk_dedupe_sort_key)
        kept.append(ordered[0])
        duplicate_ids.extend(
            str(chunk.get("chunk_record_id") or "")
            for chunk in ordered[1:]
            if str(chunk.get("chunk_record_id") or "").strip()
        )
    kept.sort(key=lambda chunk: str(chunk.get("chunk_record_id") or ""))
    return kept, duplicate_ids


def _document_chunk_dedupe_sort_key(chunk: dict[str, Any]) -> tuple[int, str]:
    has_ingestion = bool(str(chunk.get("ingestion_id") or "").strip())
    return (0 if has_ingestion else 1, str(chunk.get("chunk_record_id") or ""))
