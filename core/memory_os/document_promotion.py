"""Apply reviewed document promotion transactions through Memory OS services."""
from __future__ import annotations

from typing import Any

from core.memory_os._records import list_records, now_iso, stable_id, upsert_record
from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.transactions import MemoryTransactionService


DOCUMENT_PROMOTION_APPLY_SCHEMA_VERSION = "2026-05-14.document-promotion-apply.v1"
ALLOWED_OPERATION_KINDS = {"memory", "graph_edge"}


def apply_document_promotion_transaction(
    ledger: MemoryOSLedger,
    runtime: Any,
    document_promotion_transaction: dict[str, Any],
    *,
    accept: bool = False,
    approved_by: str | None = None,
    selected_operation_indexes: list[int] | None = None,
) -> dict[str, Any]:
    """Apply selected reviewed document promotion writes after explicit acceptance."""
    transaction_id = _transaction_id(document_promotion_transaction)
    if not accept:
        return _error_response(
            "policy_denied",
            "accept_required",
            "apply_document_promotion_transaction requires accept=True.",
            category="policy",
            transaction_id=transaction_id,
        )

    reviewer = str(approved_by or "").strip()
    if not reviewer:
        return _error_response(
            "schema_failed",
            "approved_by_required",
            "approved_by is required when accept=True.",
            transaction_id=transaction_id,
        )

    validation = _validate_transaction(document_promotion_transaction)
    if validation is not None:
        return _error_response(
            "schema_failed",
            validation["code"],
            validation["message"],
            transaction_id=transaction_id,
        )

    operations = list(document_promotion_transaction["operations"])
    selected = _normalize_selected_operation_indexes(selected_operation_indexes, len(operations))
    if isinstance(selected, dict):
        return _error_response(
            "schema_failed",
            selected["code"],
            selected["message"],
            transaction_id=transaction_id,
        )

    idempotency_key = stable_id(
        "apply_document_promotion",
        {
            "approved_by": reviewer,
            "selected_operation_indexes": selected,
            "transaction_id": transaction_id,
        },
    )
    existing = _find_apply_receipt(ledger, idempotency_key)
    if existing is not None:
        replay = dict(existing)
        replay["idempotent_replay"] = True
        return replay

    memories_written: list[str] = []
    graph_edges_written: list[str] = []
    proposed_writes: list[dict[str, Any]] = []
    affected_refs: list[dict[str, Any]] = []

    for operation_index in selected:
        operation = operations[operation_index]
        payload = operation["payload"]
        if operation["kind"] == "memory":
            key = _required_text(payload.get("key"), "memory payload key")
            runtime.store_memory(
                key=key,
                content=_required_text(payload.get("content"), "memory payload content"),
                tags=_string_list(payload.get("tags")),
                title=_optional_text(payload.get("title")),
                related_to=_string_list(payload.get("related_to")),
                force=True,
                project=_optional_text(payload.get("project")),
                domain=_optional_text(payload.get("domain")),
                status=_optional_text(payload.get("status")) or "active",
                canonical=bool(payload.get("canonical", False)),
            )
            memories_written.append(key)
            proposed_writes.append({"table": "memories", "id": key, "operation_index": operation_index})
            affected_refs.append({"kind": "memory", "key": key})
            continue

        edge = _graph_edge_from_operation(
            payload,
            transaction_id=transaction_id,
            operation_index=operation_index,
            approved_by=reviewer,
        )
        runtime.graph.import_edges([edge])
        graph_edges_written.append(edge["edge_id"])
        proposed_writes.append(
            {"table": "graph_edges", "id": edge["edge_id"], "operation_index": operation_index}
        )
        affected_refs.append({"kind": "graph_edge", "edge_id": edge["edge_id"]})

    write_performed = bool(memories_written or graph_edges_written)
    transaction_service = getattr(runtime, "transactions", None) or MemoryTransactionService(ledger)
    receipt = transaction_service.promote(
        operation_kind="apply_document_promotion_transaction",
        proposed_writes=proposed_writes,
        idempotency_key=idempotency_key,
        affected_refs=affected_refs,
    )
    result = {
        "schema_version": DOCUMENT_PROMOTION_APPLY_SCHEMA_VERSION,
        "status": "ok",
        "source_transaction_id": transaction_id,
        "apply_transaction_id": receipt["transaction_id"],
        "transaction_receipt": receipt,
        "selected_operation_indexes": selected,
        "memories_written": memories_written,
        "graph_edges_written": graph_edges_written,
        "write_performed": write_performed,
        "active_memory_write_performed": bool(memories_written),
        "graph_write_performed": bool(graph_edges_written),
        "idempotent_replay": bool(receipt.get("idempotent_replay", False)),
        "approved_by": reviewer,
        "error": None,
        "errors": [],
    }
    upsert_record(ledger, "transactions", receipt["transaction_id"], result)
    return result


def _validate_transaction(transaction: dict[str, Any]) -> dict[str, str] | None:
    if not isinstance(transaction, dict):
        return {"code": "transaction_required", "message": "document_promotion_transaction must be an object."}
    if transaction.get("record_type") != "document_promotion_transaction":
        return {"code": "invalid_record_type", "message": "record_type must be document_promotion_transaction."}
    operations = transaction.get("operations")
    if not isinstance(operations, list) or not operations:
        return {"code": "operations_required", "message": "document promotion transaction requires operations."}
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            return {"code": "operation_required", "message": f"operation {index} must be an object."}
        if operation.get("kind") not in ALLOWED_OPERATION_KINDS:
            return {
                "code": "unsupported_operation_kind",
                "message": f"operation {index} kind must be memory or graph_edge.",
            }
        payload = operation.get("payload")
        if not isinstance(payload, dict):
            return {"code": "operation_payload_required", "message": f"operation {index} payload is required."}
        if operation["kind"] == "memory":
            missing = _missing_text_field(payload, ("key", "content"))
            if missing is not None:
                return {
                    "code": f"memory_payload_{missing}_required",
                    "message": f"operation {index} memory payload requires {missing}.",
                }
        if operation["kind"] == "graph_edge":
            for ref_field in ("from_ref", "to_ref"):
                if not isinstance(payload.get(ref_field), dict) or not payload.get(ref_field):
                    return {
                        "code": f"graph_edge_payload_{ref_field}_required",
                        "message": f"operation {index} graph edge payload requires {ref_field}.",
                    }
            missing = _missing_text_field(payload, ("edge_type", "evidence"))
            if missing is not None:
                return {
                    "code": f"graph_edge_payload_{missing}_required",
                    "message": f"operation {index} graph edge payload requires {missing}.",
                }
    return None


def _normalize_selected_operation_indexes(value: Any, total: int) -> list[int] | dict[str, str]:
    if value is None:
        return list(range(total))
    if not isinstance(value, list):
        return {"code": "selected_operation_indexes_invalid", "message": "selected_operation_indexes must be a list."}
    indexes: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            return {
                "code": "selected_operation_index_invalid",
                "message": "selected operation indexes must be integers.",
            }
        if item < 0 or item >= total:
            return {
                "code": "selected_operation_index_out_of_range",
                "message": "selected operation index out of range.",
            }
        if item not in indexes:
            indexes.append(item)
    if not indexes:
        return {"code": "selected_operations_required", "message": "at least one operation must be selected."}
    return indexes


def _graph_edge_from_operation(
    payload: dict[str, Any],
    *,
    transaction_id: str,
    operation_index: int,
    approved_by: str,
) -> dict[str, Any]:
    timestamp = now_iso()
    edge = {
        "from_ref": dict(payload.get("from_ref") or {}),
        "to_ref": dict(payload.get("to_ref") or {}),
        "edge_type": _required_text(payload.get("edge_type"), "graph edge type"),
        "confidence": float(payload.get("confidence", 0.5)),
        "evidence": _required_text(payload.get("evidence"), "graph edge evidence"),
        "source": _optional_text(payload.get("source")) or "document_intelligence",
        "status": _optional_text(payload.get("status")) or "active",
        "created_by": approved_by,
        "created_at": _optional_text(payload.get("created_at")) or timestamp,
        "updated_at": timestamp,
    }
    edge["edge_id"] = _optional_text(payload.get("edge_id")) or stable_id(
        "edge",
        {
            "operation_index": operation_index,
            "payload": edge,
            "transaction_id": transaction_id,
        },
    )
    return edge


def _find_apply_receipt(ledger: MemoryOSLedger, idempotency_key: str) -> dict[str, Any] | None:
    for record in list_records(ledger, "transactions"):
        receipt = record.get("transaction_receipt") if isinstance(record.get("transaction_receipt"), dict) else record
        if receipt.get("idempotency_key") == idempotency_key:
            return record
    return None


def _transaction_id(transaction: Any) -> str | None:
    if isinstance(transaction, dict) and transaction.get("transaction_id"):
        return str(transaction["transaction_id"])
    return None


def _missing_text_field(payload: dict[str, Any], field_names: tuple[str, ...]) -> str | None:
    for field_name in field_names:
        if not str(payload.get(field_name) or "").strip():
            return field_name
    return None


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _error_response(
    status: str,
    code: str,
    message: str,
    *,
    transaction_id: str | None = None,
    category: str = "schema",
) -> dict[str, Any]:
    error = {"code": code, "category": category, "message": message}
    return {
        "schema_version": DOCUMENT_PROMOTION_APPLY_SCHEMA_VERSION,
        "status": status,
        "source_transaction_id": transaction_id,
        "selected_operation_indexes": [],
        "memories_written": [],
        "graph_edges_written": [],
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "idempotent_replay": False,
        "error": error,
        "errors": [error],
    }
