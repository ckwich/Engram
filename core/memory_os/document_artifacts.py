"""Explicit ledgered document evidence artifact materialization."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

from core.document_artifacts import artifact_path_from_ref
from core.memory_os._records import list_records, now_iso, read_record, upsert_record
from core.memory_os.content_store import ContentAddressedStore
from core.memory_os.document_pipeline import DocumentPipeline
from core.memory_os.ledger import MemoryOSLedger


DOCUMENT_ARTIFACT_STORE_SCHEMA_VERSION = "2026-05-14.document-artifact-store.v1"
READ_ONLY_POLICY = {
    "write_behavior": "read_only",
    "active_memory_promoted": False,
    "graph_edges_promoted": False,
}


class DocumentArtifactValidationError(ValueError):
    """Validation failure with a stable machine-readable error code."""

    def __init__(self, code: str, message: str, *, category: str = "validation") -> None:
        super().__init__(message)
        self.code = code
        self.category = category


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
                code=_error_code(exc),
                message=str(exc),
                category=_error_category(exc),
            )

        review_packet_sha256 = _review_packet_sha256(review_packet)
        review_context = _review_context(review_packet, artifact_preview=artifact_preview)
        prepared_transaction_id = _readable_record_id(
            "doc_artifact_txn",
            artifact_preview["document_id"],
            {
                "artifact_family": artifact_family,
                "document_id": artifact_preview["document_id"],
                "source_sha256": artifact_preview["source_sha256"],
                "coverage_receipt": artifact_preview["coverage_receipt"],
                "review_packet_sha256": review_packet_sha256,
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
            "review_packet_sha256": review_packet_sha256,
            "review_context": review_context,
            "proposed_writes": [
                {"table": "knowledge_artifacts", "id": artifact_preview["artifact_id"]},
                {"table": "documents", "id": artifact_preview["document_id"]},
                {"table": "retrieval_receipts", "id": "coverage map"},
            ],
            "artifact_preview": artifact_preview,
            "acceptance_requirements": {
                "requires_review_packet": True,
                "review_packet_sha256": review_packet_sha256,
                "source_hash_verification": "required_when_source_path_is_available",
            },
            "created_at": now_iso(),
        }
        upsert_record(self.ledger, "transactions", prepared_transaction_id, transaction)
        return {
            "schema_version": DOCUMENT_ARTIFACT_STORE_SCHEMA_VERSION,
            "status": "prepared",
            "prepared_transaction_id": prepared_transaction_id,
            "artifact_preview": artifact_preview,
            "review_context": review_context,
            "review_packet_sha256": review_packet_sha256,
            "acceptance_requirements": transaction["acceptance_requirements"],
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
        review_packet: dict[str, Any] | None = None,
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
        if prepared.get("status") == "stored":
            return _stored_artifact_replay_payload(self.ledger, prepared)
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

        review_packet = review_packet if review_packet is not None else prepared.get("review_packet")
        try:
            if review_packet is None:
                raise DocumentArtifactValidationError(
                    "review_packet_required",
                    "store_document_artifact requires the reviewed packet used to prepare this compact transaction",
                )
            _validate_review_packet_matches_prepared(review_packet, prepared)
            disassembly = _review_disassembly(review_packet)
            _validate_review_policy(review_packet)
            _validate_manifest_refs(review_packet, data_root=self.store.root.parent)
            _validate_source_bytes_if_available(disassembly)
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
                code=_error_code(exc),
                message=str(exc),
                category=_error_category(exc),
            )

        upsert_record(self.ledger, "knowledge_artifacts", artifact["artifact_id"], artifact)
        stored_transaction = {
            **prepared,
            "status": "stored",
            "write_performed": True,
            "stored_at": now_iso(),
            "stored_artifact_ids": [artifact["artifact_id"]],
            "stored_document_id": artifact["document_id"],
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


def _stored_artifact_replay_payload(
    ledger: MemoryOSLedger,
    prepared: dict[str, Any],
) -> dict[str, Any]:
    artifact_ids = list(prepared.get("stored_artifact_ids") or [])
    artifact = read_record(ledger, "knowledge_artifacts", str(artifact_ids[0])) if artifact_ids else None
    document_id = (
        artifact.get("document_id")
        if isinstance(artifact, dict)
        else prepared.get("stored_document_id")
    )
    document = read_record(ledger, "documents", str(document_id)) if document_id else None
    coverage_map = None
    for receipt in list_records(ledger, "retrieval_receipts"):
        if str(receipt.get("document_id") or "") == str(document_id or ""):
            coverage_map = receipt
            break
    return {
        "schema_version": DOCUMENT_ARTIFACT_STORE_SCHEMA_VERSION,
        "status": "ok",
        "prepared_transaction_id": prepared.get("transaction_id"),
        "stored": True,
        "idempotent_replay": True,
        "artifact": artifact,
        "document": document,
        "coverage_map": coverage_map,
        "transaction_id": prepared.get("transaction_id"),
        "policy": dict(READ_ONLY_POLICY),
        "receipts": {
            "artifacts_built": 0,
            "artifacts_read": 1 if artifact else 0,
            "stored_artifact_count": len(artifact_ids),
            "coverage_missing": (artifact or {}).get("coverage_receipt", {}).get("coverage_missing", [])
            if isinstance(artifact, dict)
            else [],
        },
        "write_performed": False,
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
        raise DocumentArtifactValidationError("policy_required", "review_packet.policy is required")
    if policy.get("write_behavior") != "read_only":
        raise DocumentArtifactValidationError(
            "policy_write_behavior_not_read_only",
            "review_packet.policy.write_behavior must be read_only",
        )
    if policy.get("active_memory_promoted") is True:
        raise DocumentArtifactValidationError(
            "policy_active_memory_already_promoted",
            "review_packet cannot already promote active memory",
        )
    if policy.get("graph_edges_promoted") is True:
        raise DocumentArtifactValidationError(
            "policy_graph_edges_already_promoted",
            "review_packet cannot already promote graph edges",
        )


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
            raise DocumentArtifactValidationError(
                "invalid_artifact_ref",
                f"artifact manifest ref is unsafe: {ref}",
            ) from exc


def _validate_review_packet_matches_prepared(
    review_packet: dict[str, Any],
    prepared: dict[str, Any],
) -> None:
    expected_hash = str(prepared.get("review_packet_sha256") or "").strip()
    actual_hash = _review_packet_sha256(review_packet)
    if expected_hash and actual_hash != expected_hash:
        raise DocumentArtifactValidationError(
            "review_packet_mismatch",
            "review_packet does not match the prepared document artifact transaction",
        )
    artifact_preview = prepared.get("artifact_preview") if isinstance(prepared.get("artifact_preview"), dict) else {}
    current_preview = _artifact_record(
        review_packet,
        content_ref=None,
        artifact_type=str(prepared.get("artifact_family") or "document_evidence"),
        review_state="prepared",
    )
    if artifact_preview.get("artifact_id") and current_preview.get("artifact_id") != artifact_preview.get("artifact_id"):
        raise DocumentArtifactValidationError(
            "artifact_preview_mismatch",
            "review_packet no longer produces the prepared artifact preview",
        )


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
    source_uri = str(source.get("source_uri") or review_packet.get("source", {}).get("source_uri") or "")
    artifact_id = _readable_record_id(
        "doc_artifact",
        document.get("document_id"),
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
        "citations": [
            {
                "level": "document",
                "source": "memory_os",
                "document_id": document.get("document_id"),
                "source_ref": source_uri,
            }
        ],
        "created_by_tool": "store_document_artifact",
        "created_at": now_iso(),
        "review_state": review_state,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
    }


def _review_packet_sha256(review_packet: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_json_bytes(review_packet)).hexdigest()


def _readable_record_id(prefix: str, readable_label: Any, payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    label = _slugify(str(readable_label or "document"), max_length=96)
    return f"{prefix}:{label}:{digest}" if label else f"{prefix}:{digest}"


def _slugify(value: str, *, max_length: int = 80) -> str:
    slug = "".join(char.lower() if char.isalnum() else "_" for char in str(value).strip())
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_")[:max_length].strip("_")


def _review_context(review_packet: dict[str, Any], *, artifact_preview: dict[str, Any]) -> dict[str, Any]:
    disassembly = _review_disassembly(review_packet)
    document = dict(disassembly.get("document") or {})
    source = dict(disassembly.get("source") or {})
    text = disassembly.get("text") if isinstance(disassembly.get("text"), dict) else {}
    pages = [page for page in disassembly.get("pages") or [] if isinstance(page, dict)]
    image_inventory = disassembly.get("image_inventory") if isinstance(disassembly.get("image_inventory"), dict) else {}
    quality = review_packet.get("quality") if isinstance(review_packet.get("quality"), dict) else {}
    extraction_request = (
        review_packet.get("extraction_request")
        if isinstance(review_packet.get("extraction_request"), dict)
        else {}
    )
    return {
        "document": {
            "document_id": document.get("document_id"),
            "title": document.get("title"),
            "page_count": document.get("page_count"),
            "page_limit": document.get("page_limit"),
            "content_hash": document.get("content_hash"),
        },
        "source": {
            "source_uri": source.get("source_uri") or (review_packet.get("source") or {}).get("source_uri"),
            "source_path": source.get("path") or (review_packet.get("source") or {}).get("source_path"),
            "content_hash": source.get("content_hash") or artifact_preview.get("source_sha256"),
            "media_type": source.get("media_type"),
        },
        "text": {
            "char_count": text.get("char_count"),
            "page_count": text.get("page_count"),
            "content_persisted": False,
        },
        "pages": {
            "count": len(pages),
            "text_pages": [page.get("page_number") for page in pages if page.get("text_status") == "text"],
            "low_text_pages": [page.get("page_number") for page in pages if page.get("text_status") == "low_text"],
            "no_text_pages": [page.get("page_number") for page in pages if page.get("text_status") == "no_text"],
            "visual_review_needed_pages": [
                page.get("page_number") for page in pages if page.get("visual_review_needed")
            ],
        },
        "images": {
            "image_count": image_inventory.get("image_count"),
            "pages_with_images": list(image_inventory.get("pages_with_images") or []),
        },
        "quality": {
            "warning_count": len(quality.get("warnings") or []),
            "warning_codes": [
                warning.get("code")
                for warning in quality.get("warnings") or []
                if isinstance(warning, dict)
            ],
        },
        "coverage_missing": list((review_packet.get("receipts") or {}).get("coverage_missing") or []),
        "extraction_request": {
            "request_id": extraction_request.get("request_id"),
            "requested_capabilities": list(extraction_request.get("requested_capabilities") or []),
        },
        "artifact_preview": {
            "artifact_id": artifact_preview.get("artifact_id"),
            "artifact_type": artifact_preview.get("artifact_type"),
        },
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


def _validate_source_bytes_if_available(disassembly: dict[str, Any]) -> None:
    source = disassembly.get("source") if isinstance(disassembly.get("source"), dict) else {}
    path_text = str(source.get("path") or "").strip()
    expected_hash = str(source.get("content_hash") or "").strip()
    if not path_text or not expected_hash:
        return
    path = Path(path_text)
    if not path.exists() or not path.is_file():
        return
    actual_hash = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_hash != expected_hash:
        raise DocumentArtifactValidationError(
            "source_hash_mismatch",
            "source bytes no longer match the reviewed document source hash",
        )


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _error_payload(*, status: str, code: str, message: str, category: str = "validation") -> dict[str, Any]:
    return {
        "schema_version": DOCUMENT_ARTIFACT_STORE_SCHEMA_VERSION,
        "status": status,
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "policy": dict(READ_ONLY_POLICY),
        "receipts": {"artifacts_built": 0, "artifacts_read": 0},
        "error": {"code": code, "category": category, "message": message},
    }


def _error_code(exc: ValueError) -> str:
    if isinstance(exc, DocumentArtifactValidationError):
        return exc.code
    return "invalid_request"


def _error_category(exc: ValueError) -> str:
    if isinstance(exc, DocumentArtifactValidationError):
        return exc.category
    return "validation"
