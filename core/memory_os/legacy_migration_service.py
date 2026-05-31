"""Focused legacy JSON and graph migration service for Memory OS."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from core.memory_os._records import hash_payload, list_records, now_iso, read_record, upsert_record
from core.memory_os.ledger import MemoryOSLedger
from core.memory_os_migration import LEGACY_STATUS_POLICY, MemoryOSMigrationKernel


class LegacyMigrationService:
    """Prepare and apply reviewed legacy corpus migration operations."""

    def __init__(
        self,
        *,
        root: str | Path,
        ledger: MemoryOSLedger,
        transactions: Any,
        content_store: Any,
        store_memory: Callable[..., dict[str, Any]],
        graph: Any,
    ) -> None:
        self.root = Path(root)
        self.ledger = ledger
        self.transactions = transactions
        self.content_store = content_store
        self.store_memory = store_memory
        self.graph = graph

    def prepare_legacy_memory_os_migration(
        self,
        *,
        legacy_dir: str | Path,
        include_details: bool = False,
    ) -> dict[str, Any]:
        """Prepare a no-write legacy JSON migration transaction."""
        legacy_path = Path(legacy_dir)
        if not legacy_path.is_dir():
            raise ValueError(f"legacy_dir must be an existing directory: {legacy_path}")
        report = MemoryOSMigrationKernel(self.root).import_legacy_json(legacy_path, dry_run=True)
        proposed_writes = _legacy_migration_proposed_writes(report)
        receipt = self.transactions.dry_run(
            operation_kind="legacy_memory_os_migration",
            proposed_writes=proposed_writes,
            idempotency_key=f"prepare:{_legacy_migration_idempotency_key(report)}",
            affected_refs=_legacy_migration_affected_refs(report),
        )
        upsert_record(self.ledger, "transactions", receipt["transaction_id"], receipt)
        return _legacy_migration_prepare_response(
            report,
            legacy_dir=legacy_path,
            receipt=receipt,
            include_details=include_details,
        )

    def apply_legacy_memory_os_migration(
        self,
        *,
        legacy_dir: str | Path,
        accept: bool = False,
        approved_by: str | None = None,
        include_details: bool = False,
    ) -> dict[str, Any]:
        """Apply reviewed legacy JSON migration writes after explicit acceptance."""
        legacy_path = Path(legacy_dir)
        if not accept:
            return _legacy_migration_policy_denied(legacy_path, "accept=True is required")
        reviewer = _optional_text(approved_by)
        if not reviewer:
            return _legacy_migration_policy_denied(legacy_path, "approved_by is required")
        if not legacy_path.is_dir():
            raise ValueError(f"legacy_dir must be an existing directory: {legacy_path}")

        kernel = MemoryOSMigrationKernel(self.root)
        records, invalid = kernel._scan_legacy_dir(legacy_path)
        duplicate_key_collisions = kernel._duplicate_key_collisions(records)
        dry_run = kernel.import_legacy_json(legacy_path, dry_run=True)
        if invalid or duplicate_key_collisions:
            return _legacy_migration_blocked(
                dry_run,
                legacy_dir=legacy_path,
                invalid=invalid,
                duplicate_key_collisions=duplicate_key_collisions,
            )

        changed: list[str] = []
        replayed: list[str] = []
        for record in records:
            raw_artifact_id = _legacy_raw_artifact_id(record)
            if self._legacy_memory_replayable(record, raw_artifact_id):
                replayed.append(record["key"])
                continue
            self.content_store.put_bytes(record["raw_bytes"], suffix=".legacy.json")
            stored = self.store_memory(
                key=record["key"],
                content=json_from_legacy_record(record, "content"),
                tags=record["tags"],
                title=record["title"],
                related_to=record["related_to"],
                force=True,
                project=record["project"],
                domain=record["domain"],
                status=record["status"],
                canonical=record["canonical"],
            )
            self._attach_legacy_import_metadata(
                record,
                raw_artifact_id=raw_artifact_id,
                approved_by=reviewer,
                store_transaction_id=str(stored.get("transaction_id") or ""),
            )
            changed.append(record["key"])

        proposed_writes = _legacy_migration_proposed_writes(dry_run)
        receipt = self.transactions.promote(
            operation_kind="legacy_memory_os_migration",
            proposed_writes=proposed_writes,
            idempotency_key=_legacy_migration_idempotency_key(dry_run),
            affected_refs=_legacy_migration_affected_refs(dry_run),
        )
        return _legacy_migration_apply_response(
            dry_run,
            legacy_dir=legacy_path,
            approved_by=reviewer,
            changed=changed,
            replayed=replayed,
            receipt=receipt,
            include_details=include_details,
        )

    def prepare_legacy_related_to_graph_migration(
        self,
        *,
        legacy_dir: str | Path,
        include_details: bool = False,
    ) -> dict[str, Any]:
        """Prepare a no-write legacy related_to graph migration transaction."""
        legacy_path = Path(legacy_dir)
        if not legacy_path.is_dir():
            raise ValueError(f"legacy_dir must be an existing directory: {legacy_path}")
        report, graphable_edges, skipped_edges = _build_legacy_related_to_graph_report(
            self.root,
            self.ledger,
            legacy_path,
            include_details=include_details,
        )
        receipt = self.transactions.dry_run(
            operation_kind="legacy_related_to_graph_migration",
            proposed_writes=_legacy_graph_proposed_writes(graphable_edges),
            idempotency_key=f"prepare:{_legacy_graph_idempotency_key(report, graphable_edges)}",
            affected_refs=_legacy_graph_affected_refs(graphable_edges),
        )
        upsert_record(self.ledger, "transactions", receipt["transaction_id"], receipt)
        response = _legacy_graph_common_response(report, legacy_dir=legacy_path)
        response.update(
            {
                "operation": "prepare_legacy_related_to_graph_migration",
                "status": "prepared" if not report["blocking_issues"] else "blocked",
                "prepared_transaction_id": receipt["transaction_id"],
                "transaction_receipt": receipt,
                "write_performed": False,
                "active_memory_write_performed": False,
                "graph_write_performed": False,
                "error": None if not report["blocking_issues"] else report["blocking_issues"][0],
            }
        )
        if include_details:
            response["graphable_edges"] = graphable_edges
            response["skipped_edges"] = skipped_edges
        return response

    def apply_legacy_related_to_graph_migration(
        self,
        *,
        legacy_dir: str | Path,
        accept: bool = False,
        approved_by: str | None = None,
        include_details: bool = False,
    ) -> dict[str, Any]:
        """Apply reviewed legacy related_to graph edges after explicit acceptance."""
        legacy_path = Path(legacy_dir)
        if not accept:
            return _legacy_graph_policy_denied(legacy_path, "accept=True is required")
        reviewer = _optional_text(approved_by)
        if not reviewer:
            return _legacy_graph_policy_denied(legacy_path, "approved_by is required")
        if not legacy_path.is_dir():
            raise ValueError(f"legacy_dir must be an existing directory: {legacy_path}")

        report, graphable_edges, skipped_edges = _build_legacy_related_to_graph_report(
            self.root,
            self.ledger,
            legacy_path,
            include_details=include_details,
        )
        if report["blocking_issues"]:
            return _legacy_graph_blocked(report, legacy_dir=legacy_path)

        idempotency_key = _legacy_graph_idempotency_key(report, graphable_edges)
        existing = _existing_legacy_graph_transaction(self.ledger, idempotency_key)
        if existing is not None:
            response = _legacy_graph_apply_response(
                report,
                legacy_dir=legacy_path,
                approved_by=reviewer,
                graphable_edges=graphable_edges,
                skipped_edges=skipped_edges,
                receipt=existing,
                changed_edges=[],
                include_details=include_details,
            )
            response["idempotent_replay"] = True
            return response

        changed_edges = [
            edge
            for edge in graphable_edges
            if read_record(self.ledger, "graph_edges", edge["edge_id"]) != edge
        ]
        if changed_edges:
            self.graph.import_edges(graphable_edges)
        receipt = self.transactions.promote(
            operation_kind="legacy_related_to_graph_migration",
            proposed_writes=_legacy_graph_proposed_writes(graphable_edges),
            idempotency_key=idempotency_key,
            affected_refs=_legacy_graph_affected_refs(graphable_edges),
        )
        response = _legacy_graph_apply_response(
            report,
            legacy_dir=legacy_path,
            approved_by=reviewer,
            graphable_edges=graphable_edges,
            skipped_edges=skipped_edges,
            receipt=receipt,
            changed_edges=changed_edges,
            include_details=include_details,
        )
        upsert_record(self.ledger, "transactions", receipt["transaction_id"], response)
        return response

    def _legacy_memory_replayable(self, record: dict[str, Any], raw_artifact_id: str) -> bool:
        memory = read_record(self.ledger, "memories", record["key"])
        source = read_record(self.ledger, "sources", _legacy_source_id(record["key"]))
        if memory is None or source is None:
            return False
        legacy_import = memory.get("legacy_import")
        if not isinstance(legacy_import, dict):
            return False
        if legacy_import.get("artifact_sha256") != record["artifact_sha256"]:
            return False
        if legacy_import.get("raw_artifact_id") != raw_artifact_id:
            return False
        if source.get("artifact_sha256") != record["artifact_sha256"]:
            return False
        if source.get("content_artifact_id") != raw_artifact_id:
            return False
        return self.content_store.path_for(raw_artifact_id).exists()

    def _attach_legacy_import_metadata(
        self,
        record: dict[str, Any],
        *,
        raw_artifact_id: str,
        approved_by: str,
        store_transaction_id: str,
    ) -> None:
        timestamp = now_iso()
        memory = read_record(self.ledger, "memories", record["key"]) or {}
        legacy_import = {
            "source_type": "legacy_memory_json",
            "legacy_filename": record["legacy_filename"],
            "source_path": record["source_path"],
            "artifact_sha256": record["artifact_sha256"],
            "raw_artifact_id": raw_artifact_id,
            "legacy_status": record["legacy_status"],
            "memory_os_status": record["status"],
            "legacy_created_at": record["created_at"],
            "legacy_updated_at": record["updated_at"],
            "imported_at": timestamp,
            "imported_by": approved_by,
            "store_transaction_id": store_transaction_id or None,
        }
        memory["legacy_import"] = legacy_import
        upsert_record(self.ledger, "memories", record["key"], memory)
        source = {
            "source_id": _legacy_source_id(record["key"]),
            "source_type": "legacy_memory_json",
            "memory_key": record["key"],
            "legacy_filename": record["legacy_filename"],
            "source_path": record["source_path"],
            "artifact_sha256": record["artifact_sha256"],
            "content_artifact_id": raw_artifact_id,
            "status": "imported",
            "imported_at": timestamp,
            "imported_by": approved_by,
            "write_performed": True,
        }
        upsert_record(self.ledger, "sources", source["source_id"], source)


def json_from_legacy_record(record: dict[str, Any], field: str) -> str:
    decoded = json.loads(record["raw_bytes"].decode("utf-8"))
    if not isinstance(decoded, dict) or not isinstance(decoded.get(field), str):
        raise ValueError(f"legacy record is missing text field: {field}")
    return str(decoded[field])


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _legacy_raw_artifact_id(record: dict[str, Any]) -> str:
    return f"sha256:{record['artifact_sha256']}.legacy.json"


def _legacy_source_id(key: str) -> str:
    return f"legacy_memory:{key}"


def _legacy_migration_idempotency_key(report: dict[str, Any]) -> str:
    return "legacy_memory_os_migration:" + hash_payload(
        {
            "schema_version": report.get("schema_version"),
            "artifact_hashes": report.get("artifact_hashes") or {},
            "status_policy": report.get("status_policy") or {},
        }
    )


def _legacy_migration_proposed_writes(report: dict[str, Any]) -> list[dict[str, Any]]:
    writes: list[dict[str, Any]] = []
    for key in report.get("key_set") or []:
        writes.append({"table": "memories", "id": str(key)})
        writes.append({"table": "sources", "id": _legacy_source_id(str(key))})
    return writes


def _legacy_migration_affected_refs(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"kind": "memory", "key": str(key)} for key in report.get("key_set") or []]


def _legacy_migration_prepare_response(
    report: dict[str, Any],
    *,
    legacy_dir: Path,
    receipt: dict[str, Any],
    include_details: bool,
) -> dict[str, Any]:
    response = _legacy_migration_common_response(report, legacy_dir=legacy_dir)
    response.update(
        {
            "operation": "prepare_legacy_memory_os_migration",
            "status": "prepared",
            "prepared_transaction_id": receipt["transaction_id"],
            "transaction_receipt": receipt,
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "error": None,
        }
    )
    if include_details:
        response["key_set"] = report.get("key_set") or []
        response["chunk_count_mismatches"] = report.get("chunk_count_mismatches") or []
        response["unsupported_fields"] = report.get("unsupported_fields") or {}
    return response


def _legacy_migration_apply_response(
    report: dict[str, Any],
    *,
    legacy_dir: Path,
    approved_by: str,
    changed: list[str],
    replayed: list[str],
    receipt: dict[str, Any],
    include_details: bool,
) -> dict[str, Any]:
    response = _legacy_migration_common_response(report, legacy_dir=legacy_dir)
    idempotent_replay = len(changed) == 0 and len(replayed) == len(report.get("key_set") or [])
    response.update(
        {
            "operation": "apply_legacy_memory_os_migration",
            "status": "ok",
            "approved_by": approved_by,
            "prepared_transaction_id": receipt["transaction_id"],
            "transaction_id": receipt["transaction_id"],
            "transaction_receipt": receipt,
            "write_performed": bool(changed),
            "active_memory_write_performed": bool(changed),
            "graph_write_performed": False,
            "imported_count": len(report.get("key_set") or []),
            "changed_count": len(changed),
            "replayed_count": len(replayed),
            "idempotent_replay": idempotent_replay,
            "error": None,
        }
    )
    if include_details:
        response["changed_keys"] = changed
        response["replayed_keys"] = replayed
        response["key_set"] = report.get("key_set") or []
    return response


def _legacy_migration_common_response(report: dict[str, Any], *, legacy_dir: Path) -> dict[str, Any]:
    return {
        "schema_version": report.get("schema_version"),
        "legacy_dir": str(legacy_dir),
        "source_count": int(report.get("source_count") or 0),
        "valid_count": int(report.get("valid_count") or 0),
        "invalid_count": int(report.get("invalid_count") or 0),
        "would_import_count": int(report.get("would_import_count") or 0),
        "chunk_count_total": int(report.get("chunk_count_total") or 0),
        "derived_chunk_count_total": int(report.get("derived_chunk_count_total") or 0),
        "related_to_count": int(report.get("related_to_count") or 0),
        "legacy_status_counts": dict(report.get("legacy_status_counts") or {}),
        "memory_os_status_counts": dict(report.get("memory_os_status_counts") or {}),
        "status_mapping_gaps": list(report.get("status_mapping_gaps") or []),
        "duplicate_key_collisions": list(report.get("duplicate_key_collisions") or []),
    }


def _legacy_migration_policy_denied(legacy_dir: Path, message: str) -> dict[str, Any]:
    return {
        "operation": "apply_legacy_memory_os_migration",
        "legacy_dir": str(legacy_dir),
        "status": "policy_denied",
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "idempotent_replay": False,
        "error": {"code": "explicit_acceptance_required", "message": message},
    }


def _legacy_migration_blocked(
    report: dict[str, Any],
    *,
    legacy_dir: Path,
    invalid: list[dict[str, Any]],
    duplicate_key_collisions: list[dict[str, Any]],
) -> dict[str, Any]:
    response = _legacy_migration_common_response(report, legacy_dir=legacy_dir)
    response.update(
        {
            "operation": "apply_legacy_memory_os_migration",
            "status": "blocked",
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "invalid": invalid,
            "duplicate_key_collisions": duplicate_key_collisions,
            "error": {
                "code": "migration_not_importable",
                "message": "Legacy migration has invalid records or duplicate key collisions.",
            },
        }
    )
    return response


def _build_legacy_related_to_graph_report(
    root: Path,
    ledger: MemoryOSLedger,
    legacy_path: Path,
    *,
    include_details: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    kernel = MemoryOSMigrationKernel(root)
    records, invalid = kernel._scan_legacy_dir(legacy_path)
    duplicate_key_collisions = kernel._duplicate_key_collisions(records)
    key_set = {record["key"] for record in records}
    graphable_edges: list[dict[str, Any]] = []
    skipped_edges: list[dict[str, Any]] = []
    missing_refs: list[dict[str, str]] = []
    skipped_by_status: dict[str, int] = {}

    for record in records:
        graphable = _legacy_record_graphable(record)
        for edge in record.get("graph_edges", []):
            normalized = _legacy_graph_edge_for_runtime(edge)
            to_key = str(normalized.get("to_ref", {}).get("key") or "")
            if to_key and to_key not in key_set:
                missing_refs.append({"from_key": record["key"], "to_key": to_key})
            if graphable:
                graphable_edges.append(normalized)
            else:
                skipped_edges.append(normalized)
                status = str(record.get("status") or "unknown")
                skipped_by_status[status] = skipped_by_status.get(status, 0) + 1

    blocking_issues = []
    if invalid:
        blocking_issues.append(
            {
                "code": "invalid_legacy_records",
                "message": "Legacy graph migration has invalid JSON records.",
                "count": len(invalid),
            }
        )
    if duplicate_key_collisions:
        blocking_issues.append(
            {
                "code": "duplicate_key_collisions",
                "message": "Legacy graph migration has duplicate key collisions.",
                "count": len(duplicate_key_collisions),
            }
        )

    report = {
        "schema_version": "2026-05-15.legacy-related-to-graph-migration.v1",
        "legacy_dir": str(legacy_path),
        "source_count": len(records) + len(invalid),
        "valid_count": len(records),
        "invalid_count": len(invalid),
        "candidate_edge_count": len(graphable_edges) + len(skipped_edges),
        "graphable_edge_count": len(graphable_edges),
        "skipped_edge_count": len(skipped_edges),
        "skipped_by_status": dict(sorted(skipped_by_status.items())),
        "missing_ref_count": len(missing_refs),
        "missing_refs": sorted(missing_refs, key=lambda item: (item["from_key"], item["to_key"])),
        "existing_graph_edge_count": len(list_records(ledger, "graph_edges")),
        "would_write_count": sum(
            1
            for edge in graphable_edges
            if read_record(ledger, "graph_edges", edge["edge_id"]) != edge
        ),
        "edge_ids": [edge["edge_id"] for edge in graphable_edges],
        "status_policy": LEGACY_STATUS_POLICY,
        "invalid": invalid,
        "duplicate_key_collisions": duplicate_key_collisions,
        "blocking_issues": blocking_issues,
    }
    if include_details:
        report["skipped_edge_ids"] = [edge["edge_id"] for edge in skipped_edges]
    return report, graphable_edges, skipped_edges


def _legacy_record_graphable(record: dict[str, Any]) -> bool:
    legacy_status = str(record.get("legacy_status") or "")
    policy = LEGACY_STATUS_POLICY.get(legacy_status)
    return bool(policy and policy.get("graphable"))


def _legacy_graph_edge_for_runtime(edge: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(edge)
    normalized["from_ref"] = dict(edge["from_ref"])
    normalized["to_ref"] = dict(edge["to_ref"])
    normalized["created_by"] = "legacy_related_to_migration"
    return normalized


def _legacy_graph_idempotency_key(
    report: dict[str, Any],
    graphable_edges: list[dict[str, Any]],
) -> str:
    return "legacy_related_to_graph_migration:" + hash_payload(
        {
            "schema_version": report.get("schema_version"),
            "edge_ids": [edge["edge_id"] for edge in graphable_edges],
            "status_policy": report.get("status_policy") or {},
        }
    )


def _legacy_graph_proposed_writes(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"table": "graph_edges", "id": edge["edge_id"]} for edge in edges]


def _legacy_graph_affected_refs(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"kind": "graph_edge", "edge_id": edge["edge_id"]} for edge in edges]


def _existing_legacy_graph_transaction(
    ledger: MemoryOSLedger,
    idempotency_key: str,
) -> dict[str, Any] | None:
    for record in list_records(ledger, "transactions"):
        if record.get("idempotency_key") == idempotency_key:
            return dict(record.get("transaction_receipt") or record)
    return None


def _legacy_graph_common_response(report: dict[str, Any], *, legacy_dir: Path) -> dict[str, Any]:
    return {
        "schema_version": report["schema_version"],
        "legacy_dir": str(legacy_dir),
        "source_count": report["source_count"],
        "valid_count": report["valid_count"],
        "invalid_count": report["invalid_count"],
        "candidate_edge_count": report["candidate_edge_count"],
        "graphable_edge_count": report["graphable_edge_count"],
        "skipped_edge_count": report["skipped_edge_count"],
        "skipped_by_status": dict(report["skipped_by_status"]),
        "missing_ref_count": report["missing_ref_count"],
        "missing_refs": list(report["missing_refs"]),
        "existing_graph_edge_count": report["existing_graph_edge_count"],
        "would_write_count": report["would_write_count"],
        "edge_ids": list(report["edge_ids"]),
        "duplicate_key_collisions": list(report["duplicate_key_collisions"]),
        "blocking_issues": list(report["blocking_issues"]),
    }


def _legacy_graph_apply_response(
    report: dict[str, Any],
    *,
    legacy_dir: Path,
    approved_by: str,
    graphable_edges: list[dict[str, Any]],
    skipped_edges: list[dict[str, Any]],
    receipt: dict[str, Any],
    changed_edges: list[dict[str, Any]],
    include_details: bool,
) -> dict[str, Any]:
    response = _legacy_graph_common_response(report, legacy_dir=legacy_dir)
    changed_ids = [edge["edge_id"] for edge in changed_edges]
    response.update(
        {
            "operation": "apply_legacy_related_to_graph_migration",
            "status": "ok",
            "approved_by": approved_by,
            "transaction_id": receipt["transaction_id"],
            "idempotency_key": receipt.get("idempotency_key"),
            "transaction_receipt": receipt,
            "graph_edges_written": changed_ids,
            "write_performed": bool(changed_edges),
            "active_memory_write_performed": False,
            "graph_write_performed": bool(changed_edges),
            "idempotent_replay": bool(receipt.get("idempotent_replay", False)),
            "error": None,
        }
    )
    if include_details:
        response["graphable_edges"] = graphable_edges
        response["skipped_edges"] = skipped_edges
    return response


def _legacy_graph_policy_denied(legacy_dir: Path, message: str) -> dict[str, Any]:
    return {
        "operation": "apply_legacy_related_to_graph_migration",
        "legacy_dir": str(legacy_dir),
        "status": "policy_denied",
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "idempotent_replay": False,
        "error": {"code": "explicit_acceptance_required", "message": message},
    }


def _legacy_graph_blocked(report: dict[str, Any], *, legacy_dir: Path) -> dict[str, Any]:
    response = _legacy_graph_common_response(report, legacy_dir=legacy_dir)
    response.update(
        {
            "operation": "apply_legacy_related_to_graph_migration",
            "status": "blocked",
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
            "idempotent_replay": False,
            "error": {
                "code": "legacy_graph_migration_not_importable",
                "message": "Legacy related_to graph migration has invalid records or duplicate key collisions.",
            },
        }
    )
    return response
