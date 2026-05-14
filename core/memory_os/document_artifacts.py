"""Explicit ledgered document evidence artifact materialization."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.document_artifacts import artifact_path_from_ref
from core.memory_os._records import list_records, now_iso, read_record, stable_id, upsert_record
from core.memory_os.content_store import ContentAddressedStore
from core.memory_os.document_pipeline import DocumentPipeline
from core.memory_os.ledger import MemoryOSLedger


DOCUMENT_ARTIFACT_STORE_SCHEMA_VERSION = "2026-05-14.document-artifact-store.v1"
READ_ONLY_POLICY = {
    "write_behavior": "read_only",
    "active_memory_promoted": False,
    "graph_edges_promoted": False,
}


class DocumentArtifactMaterializer:
    """Prepare and store reviewed document evidence without active memory promotion."""

    def __init__(self, ledger: MemoryOSLedger, store: ContentAddressedStore) -> None:
        self.ledger = ledger
        self.store = store
        self.pipeline = DocumentPipeline(ledger, store)

    def prepare_document_artifact_store(
        self,
        review_packet: dict[str, Any],
        *,
        artifact_family: str = "document_evidence",
    ) -> dict[str, Any]:
        """Record a reviewable artifact-store transaction without storing artifacts."""
        try:
            disassembly = _review_disassembly(review_packet)
            _validate_review_policy(review_packet)
            _validate_manifest_refs(review_packet, data_root=self.store.root.parent)
            artifact_preview = _artifact_record(
                review_packet,
                content_ref=None,
                artifact_type=artifact_family,
                review_state="prepared",
            )
        except ValueError as exc:
            return _error_payload(
                status="schema_failed",
                code=getattr(exc, "args", ["invalid_request"])[0] if _is_error_code(exc) else "invalid_request",
                message=str(exc),
            )

        prepared_transaction_id = stable_id(
            "doc_artifact_txn",
            {
                "artifact_family": artifact_family,
                "document_id": artifact_preview["document_id"],
                "source_sha256": artifact_preview["source_sha256"],
                "coverage_receipt": artifact_preview["coverage_receipt"],
            },
        )
        transaction = {
            "schema_version": DOCUMENT_ARTIFACT_STORE_SCHEMA_VERSION,
            "transaction_id": prepared_transaction_id,
            "operation_kind": "document_artifact_store",
            "status": "prepared",
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "artifact_family": artifact_family,
            "review_packet": review_packet,
            "proposed_writes": [
                {"table": "knowledge_artifacts", "id": artifact_preview["artifact_id"]},
                {"table": "documents", "id": artifact_preview["document_id"]},
                {"table": "retrieval_receipts", "id": "coverage map"},
            ],
            "artifact_preview": artifact_preview,
            "created_at": now_iso(),
        }
        upsert_record(self.ledger, "transactions", prepared_transaction_id, transaction)
        return {
            "schema_version": DOCUMENT_ARTIFACT_STORE_SCHEMA_VERSION,
            "status": "prepared",
            "prepared_transaction_id": prepared_transaction_id,
            "artifact_preview": artifact_preview,
            "policy": dict(READ_ONLY_POLICY),
            "receipts": {
                "artifacts_built": 1,
                "artifacts_read": 0,
                "documents_consulted": 1 if disassembly.get("document") else 0,
                "coverage_missing": artifact_preview["coverage_receipt"].get("coverage_missing", []),
            },
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None,
        }

    def store_document_artifact(
        self,
        prepared_transaction_id: str,
        *,
        accept: bool = False,
    ) -> dict[str, Any]:
        """Store ledgered document evidence only after explicit acceptance."""
        transaction_id = str(prepared_transaction_id or "").strip()
        if not transaction_id:
            return _error_payload(
                status="schema_failed",
                code="invalid_request",
                message="prepared_transaction_id is required",
            )
        prepared = read_record(self.ledger, "transactions", transaction_id)
        if prepared is None or prepared.get("operation_kind") != "document_artifact_store":
            return _error_payload(
                status="not_found",
                code="not_found",
                message=f"prepared document artifact transaction not found: {transaction_id}",
            )
        if not accept:
            return {
                "schema_version": DOCUMENT_ARTIFACT_STORE_SCHEMA_VERSION,
                "status": "policy_denied",
                "prepared_transaction_id": transaction_id,
                "stored": False,
                "write_performed": False,
                "active_memory_write_performed": False,
                "graph_write_performed": False,
                "policy": dict(READ_ONLY_POLICY),
                "receipts": {"artifacts_built": 0, "artifacts_read": 0},
                "error": {
                    "code": "accept_required",
                    "category": "policy",
                    "message": "store_document_artifact requires accept=True",
                },
            }

        review_packet = prepared.get("review_packet")
        try:
            disassembly = _review_disassembly(review_packet)
            _validate_review_policy(review_packet)
            _validate_manifest_refs(review_packet, data_root=self.store.root.parent)
            evidence_ref = self.store.put_bytes(
                _json_bytes(
                    {
                        "review_packet": review_packet,
                        "disassembly": disassembly,
                        "artifact_preview": prepared.get("artifact_preview"),
                    }
                ),
                suffix=".json",
            )
            artifact = _artifact_record(
                review_packet,
                content_ref=evidence_ref,
                artifact_type=str(prepared.get("artifact_family") or "document_evidence"),
                review_state="ledgered_evidence",
            )
            source_ref = _store_source_bytes_if_available(self.store, disassembly)
            if source_ref is not None:
                artifact["source_content_ref"] = source_ref
            pipeline_result = self.pipeline.materialize_document_job(disassembly)
        except ValueError as exc:
            return _error_payload(
                status="schema_failed",
                code=getattr(exc, "args", ["invalid_request"])[0] if _is_error_code(exc) else "invalid_request",
                message=str(exc),
            )

        upsert_record(self.ledger, "knowledge_artifacts", artifact["artifact_id"], artifact)
        stored_transaction = {
            **prepared,
            "status": "stored",
            "write_performed": True,
            "stored_at": now_iso(),
            "stored_artifact_ids": [artifact["artifact_id"]],
            "pipeline_job_id": pipeline_result.get("job_id"),
        }
        upsert_record(self.ledger, "transactions", transaction_id, stored_transaction)
        return {
            "schema_version": DOCUMENT_ARTIFACT_STORE_SCHEMA_VERSION,
            "status": "ok",
            "prepared_transaction_id": transaction_id,
            "stored": True,
            "artifact": artifact,
            "document": pipeline_result.get("document"),
            "coverage_map": pipeline_result.get("coverage_map"),
            "transaction_id": transaction_id,
            "policy": dict(READ_ONLY_POLICY),
            "receipts": {
                "artifacts_built": 0,
                "artifacts_read": 1,
                "stored_artifact_count": 1,
                "coverage_missing": artifact["coverage_receipt"].get("coverage_missing", []),
            },
            "write_performed": True,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None,
        }


def _review_disassembly(review_packet: Any) -> dict[str, Any]:
    if not isinstance(review_packet, dict):
        raise ValueError("review_packet must be an object")
    disassembly = review_packet.get("disassembly")
    if not isinstance(disassembly, dict):
        raise ValueError("review_packet.disassembly is required")
    if disassembly.get("active_memory_write_performed") is True:
        raise ValueError("review_packet disassembly cannot include active memory writes")
    document = disassembly.get("document")
    if not isinstance(document, dict) or not str(document.get("document_id") or "").strip():
        raise ValueError("review_packet.disassembly.document.document_id is required")
    return disassembly


def _validate_review_policy(review_packet: dict[str, Any]) -> None:
    policy = review_packet.get("policy")
    if not isinstance(policy, dict):
        raise ValueError("review_packet.policy is required")
    if policy.get("write_behavior") != "read_only":
        raise ValueError("review_packet.policy.write_behavior must be read_only")
    if policy.get("active_memory_promoted") is True:
        raise ValueError("review_packet cannot already promote active memory")
    if policy.get("graph_edges_promoted") is True:
        raise ValueError("review_packet cannot already promote graph edges")


def _validate_manifest_refs(review_packet: dict[str, Any], *, data_root: Path) -> None:
    manifest = review_packet.get("artifact_manifest") or (_review_disassembly(review_packet).get("artifact_manifest"))
    if not isinstance(manifest, dict):
        return
    refs: list[str] = []
    raw_source = ((manifest.get("artifacts") or {}).get("raw_source") or {})
    if isinstance(raw_source, dict) and raw_source.get("ref"):
        refs.append(str(raw_source["ref"]))
    for page in manifest.get("pages") or []:
        if not isinstance(page, dict):
            continue
        text_artifact = page.get("text_artifact")
        if isinstance(text_artifact, dict) and text_artifact.get("ref"):
            refs.append(str(text_artifact["ref"]))
    for ref in refs:
        try:
            artifact_path_from_ref(ref, data_root=data_root)
        except ValueError as exc:
            error = ValueError(f"artifact manifest ref is unsafe: {ref}")
            error.args = ("invalid_artifact_ref", str(error))
            raise error from exc


def _artifact_record(
    review_packet: dict[str, Any],
    *,
    content_ref: str | None,
    artifact_type: str,
    review_state: str,
) -> dict[str, Any]:
    disassembly = _review_disassembly(review_packet)
    document = dict(disassembly.get("document") or {})
    source = dict(disassembly.get("source") or {})
    coverage_receipt = {
        "coverage_missing": list((review_packet.get("receipts") or {}).get("coverage_missing") or []),
        "quality_warnings": list((review_packet.get("quality") or {}).get("warnings") or []),
        "visual_request_id": (review_packet.get("extraction_request") or {}).get("request_id")
        if isinstance(review_packet.get("extraction_request"), dict)
        else None,
    }
    source_sha256 = str(source.get("content_hash") or review_packet.get("source", {}).get("sha256") or "")
    artifact_id = stable_id(
        "doc_artifact",
        {
            "document_id": document.get("document_id"),
            "artifact_type": artifact_type,
            "source_sha256": source_sha256,
            "coverage_receipt": coverage_receipt,
        },
    )
    return {
        "schema_version": DOCUMENT_ARTIFACT_STORE_SCHEMA_VERSION,
        "artifact_id": artifact_id,
        "document_id": document.get("document_id"),
        "source_sha256": source_sha256,
        "artifact_type": artifact_type,
        "content_ref": content_ref,
        "page_refs": [
            {"page_number": page.get("page_number"), "text_status": page.get("text_status")}
            for page in disassembly.get("pages") or []
            if isinstance(page, dict)
        ],
        "coverage_receipt": coverage_receipt,
        "created_by_tool": "store_document_artifact",
        "created_at": now_iso(),
        "review_state": review_state,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
    }


def _store_source_bytes_if_available(store: ContentAddressedStore, disassembly: dict[str, Any]) -> str | None:
    source = disassembly.get("source") if isinstance(disassembly.get("source"), dict) else {}
    path_text = str(source.get("path") or "").strip()
    if not path_text:
        return None
    path = Path(path_text)
    if not path.exists() or not path.is_file():
        return None
    suffix = ".pdf" if source.get("media_type") == "application/pdf" or source.get("source_type") == "pdf" else ".bin"
    return store.put_bytes(path.read_bytes(), suffix=suffix)


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _error_payload(*, status: str, code: str, message: str) -> dict[str, Any]:
    return {
        "schema_version": DOCUMENT_ARTIFACT_STORE_SCHEMA_VERSION,
        "status": status,
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "policy": dict(READ_ONLY_POLICY),
        "receipts": {"artifacts_built": 0, "artifacts_read": 0},
        "error": {"code": code, "category": "validation", "message": message},
    }


def _is_error_code(exc: ValueError) -> bool:
    return bool(exc.args and isinstance(exc.args[0], str) and "_" in exc.args[0])
