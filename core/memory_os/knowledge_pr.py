"""Knowledge Branch, Knowledge PR, and Memory CI records."""
from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from typing import Any

from core.memory_os._records import (
    hash_payload,
    list_records,
    now_iso,
    read_record,
    stable_id,
    upsert_record,
)
from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.schema import GRAPH_EDGE_TYPES, TABLES


KNOWLEDGE_PR_SCHEMA_VERSION = "2026-05-19.knowledge-pr.v1"
PR_STATUSES = {"open", "ci_blocked", "mergeable", "merged", "closed"}
CI_STATUSES = {"passed", "blocked", "warning", "not_applicable", "error"}
DEFAULT_CI_GATES = (
    "gate_provenance",
    "gate_document_coverage",
    "gate_graph_validity",
    "gate_retrieval_regression",
    "gate_policy",
    "gate_idempotency",
)


class KnowledgePRService:
    """Prepare and inspect reviewable Memory OS change packets."""

    def __init__(self, ledger: MemoryOSLedger, runtime: Any) -> None:
        self.ledger = ledger
        self.runtime = runtime

    def prepare_knowledge_branch(
        self,
        *,
        name: str,
        source_refs: list[dict[str, Any]] | None = None,
        base_snapshot_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_name = _required_text(name, "name")
        normalized_source_refs = _dict_list(source_refs)
        branch_id = stable_id(
            "kbranch",
            {
                "name": normalized_name,
                "base_snapshot_ref": base_snapshot_ref,
                "source_refs": normalized_source_refs,
            },
        )
        existing = read_record(self.ledger, "knowledge_branches", branch_id)
        if isinstance(existing, dict):
            return _with_no_active_writes(existing, write_performed=False)

        now = now_iso()
        record = {
            "schema_version": KNOWLEDGE_PR_SCHEMA_VERSION,
            "record_type": "knowledge_branch",
            "branch_id": branch_id,
            "name": normalized_name,
            "base_snapshot_ref": base_snapshot_ref,
            "source_refs": normalized_source_refs,
            "staged_refs": [],
            "metadata": dict(metadata or {}),
            "status": "open",
            "created_at": now,
            "updated_at": now,
        }
        upsert_record(self.ledger, "knowledge_branches", branch_id, record)
        return _with_no_active_writes(record, write_performed=True)

    def prepare_knowledge_pr(
        self,
        *,
        branch_id: str,
        title: str,
        proposed_operations: list[dict[str, Any]] | None = None,
        source_refs: list[dict[str, Any]] | None = None,
        document_refs: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_branch_id = _required_text(branch_id, "branch_id")
        branch = read_record(self.ledger, "knowledge_branches", normalized_branch_id)
        if not isinstance(branch, dict):
            return _error(
                "not_found",
                "knowledge branch was not found",
                branch_id=normalized_branch_id,
            )

        normalized_title = _required_text(title, "title")
        operations_result = _proposed_operations(proposed_operations)
        if operations_result.get("error"):
            return _error(
                "invalid_proposed_operations",
                "proposed_operations must be a list of objects.",
                branch_id=normalized_branch_id,
            )
        operations = operations_result["operations"]
        pr_id = stable_id(
            "kpr",
            {
                "branch_id": normalized_branch_id,
                "title": normalized_title,
                "operations_hash": hash_payload(operations),
            },
        )
        existing = read_record(self.ledger, "knowledge_prs", pr_id)
        if isinstance(existing, dict):
            return _with_no_active_writes(existing, write_performed=False)

        now = now_iso()
        record = {
            "schema_version": KNOWLEDGE_PR_SCHEMA_VERSION,
            "record_type": "knowledge_pr",
            "knowledge_pr_id": pr_id,
            "branch_id": normalized_branch_id,
            "title": normalized_title,
            "base_snapshot_ref": branch.get("base_snapshot_ref"),
            "source_refs": _dict_list(source_refs) or _dict_list(branch.get("source_refs")),
            "document_refs": _dict_list(document_refs),
            "proposed_operations": operations,
            "ci_run_ids": [],
            "ci_summary": {"status": "not_run", "blocking_gate_ids": []},
            "blocking_issues": [],
            "metadata": dict(metadata or {}),
            "status": "open",
            "created_at": now,
            "updated_at": now,
        }
        upsert_record(self.ledger, "knowledge_prs", pr_id, record)
        return _with_no_active_writes(record, write_performed=True)

    def inspect_knowledge_pr(self, *, knowledge_pr_id: str) -> dict[str, Any]:
        pr_id = _required_text(knowledge_pr_id, "knowledge_pr_id")
        record = read_record(self.ledger, "knowledge_prs", pr_id)
        if not isinstance(record, dict):
            return _error("not_found", "knowledge PR was not found", knowledge_pr_id=pr_id)
        ci_runs = [
            run
            for run in list_records(self.ledger, "memory_ci_runs")
            if run.get("knowledge_pr_id") == pr_id
        ]
        return _with_no_active_writes(
            {
                **record,
                "ci_runs": ci_runs,
                "mergeable": record.get("status") == "mergeable",
            },
            write_performed=False,
        )

    def run_memory_ci(
        self,
        *,
        knowledge_pr_id: str,
        gates: list[str] | None = None,
        ci_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        pr_id = _required_text(knowledge_pr_id, "knowledge_pr_id")
        record = read_record(self.ledger, "knowledge_prs", pr_id)
        if not isinstance(record, dict):
            return _error("not_found", "knowledge PR was not found", knowledge_pr_id=pr_id)

        selected_gates = _gate_list(gates)
        context = dict(ci_context or {})
        gate_results = [
            _run_gate(gate_id, record, context, self.runtime)
            for gate_id in selected_gates
        ]
        blocking_gate_ids = [
            result["gate_id"]
            for result in gate_results
            if result.get("required") is True and result.get("status") in {"blocked", "error"}
        ]
        status = "passed" if not blocking_gate_ids else "blocked"
        now = now_iso()
        ci_run_id = stable_id(
            "mci",
            {
                "knowledge_pr_id": pr_id,
                "gates": selected_gates,
                "operations_hash": hash_payload(record.get("proposed_operations") or []),
                "context_hash": hash_payload(context),
            },
        )
        ci_record = {
            "schema_version": KNOWLEDGE_PR_SCHEMA_VERSION,
            "record_type": "memory_ci_run",
            "ci_run_id": ci_run_id,
            "knowledge_pr_id": pr_id,
            "gate_results": gate_results,
            "blocking_gate_ids": blocking_gate_ids,
            "status": status,
            "created_at": now,
            "updated_at": now,
        }
        upsert_record(self.ledger, "memory_ci_runs", ci_run_id, ci_record)

        updated_pr = {
            **record,
            "ci_run_ids": _merge_ids([*list(record.get("ci_run_ids") or []), ci_run_id]),
            "ci_summary": {"status": status, "blocking_gate_ids": blocking_gate_ids},
            "blocking_issues": _blocking_issues(gate_results),
            "status": "mergeable" if status == "passed" else "ci_blocked",
            "updated_at": now,
        }
        upsert_record(self.ledger, "knowledge_prs", pr_id, updated_pr)
        return _with_no_active_writes(ci_record, write_performed=True)

    def merge_knowledge_pr(
        self,
        *,
        knowledge_pr_id: str,
        accept: bool = False,
        approved_by: str | None = None,
        selected_operation_ids: list[str] | None = None,
        selected_operation_indexes: list[int] | None = None,
        ci_waivers: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        pr_id = _required_text(knowledge_pr_id, "knowledge_pr_id")
        record = read_record(self.ledger, "knowledge_prs", pr_id)
        if not isinstance(record, dict):
            return _error("not_found", "knowledge PR was not found", knowledge_pr_id=pr_id)
        if not accept:
            return _merge_error(pr_id, "policy_denied", "accept_required", "merge_knowledge_pr requires accept=True.")
        reviewer = str(approved_by or "").strip()
        if not reviewer:
            return _merge_error(pr_id, "schema_failed", "approved_by_required", "approved_by is required.")
        if self.runtime is None:
            return _merge_error(pr_id, "schema_failed", "runtime_required", "merge requires a MemoryOSRuntime.")
        if record.get("status") == "merged":
            return _merged_pr_replay(self.ledger, record, write_performed=False)

        ci_result = _ci_allows_merge(record, _dict_list(ci_waivers))
        if ci_result.get("error"):
            return _merge_error(
                pr_id,
                "policy_denied",
                str(ci_result["error"]["code"]),
                str(ci_result["error"]["message"]),
                details=ci_result,
            )

        operations = _selected_operations(
            _operations(record),
            selected_operation_ids=selected_operation_ids,
            selected_operation_indexes=selected_operation_indexes,
        )
        validation_error = _validate_merge_operations(operations)
        if validation_error is not None:
            return _merge_error(
                pr_id,
                "schema_failed",
                str(validation_error["code"]),
                str(validation_error["message"]),
                details=validation_error,
            )

        idempotency_key = _merge_idempotency_key(record, operations)
        existing_transaction = _transaction_by_idempotency_key(self.ledger, idempotency_key)
        if isinstance(existing_transaction, dict):
            replay = dict(existing_transaction)
            replay["idempotent_replay"] = True
            now = now_iso()
            upsert_record(
                self.ledger,
                "knowledge_prs",
                pr_id,
                {
                    **record,
                    "status": "merged",
                    "merged_by": reviewer,
                    "merged_at": record.get("merged_at") or now,
                    "merge_transaction_id": replay["transaction_id"],
                    "merge_transaction": replay,
                    "merge_operation_results": list(record.get("merge_operation_results") or []),
                    "ci_waivers": _dict_list(ci_waivers),
                    "updated_at": now,
                },
            )
            return {
                "schema_version": KNOWLEDGE_PR_SCHEMA_VERSION,
                "status": "merged",
                "knowledge_pr_id": pr_id,
                "transaction": replay,
                "operation_results": list(record.get("merge_operation_results") or []),
                "write_performed": True,
                "active_memory_write_performed": False,
                "graph_write_performed": False,
                "idempotent_replay": True,
                "error": None,
            }

        guardrail_preflight = _preflight_merge_memory_guardrails(
            self.runtime,
            operations,
            approved_by=reviewer,
            knowledge_pr_id=pr_id,
        )
        if guardrail_preflight is not None:
            guardrail = guardrail_preflight.get("guardrail") or {}
            decision = str(guardrail.get("decision") or "").strip()
            return _merge_error(
                pr_id,
                "policy_denied" if decision == "block" else "review_required",
                "memory_guardrail_blocked"
                if decision == "block"
                else "memory_guardrail_review_required",
                "Memory guardrails blocked a selected Knowledge PR memory write."
                if decision == "block"
                else "Memory guardrails require reviewed promotion for a selected document claim.",
                details=guardrail_preflight,
                write_performed=bool(
                    guardrail_preflight.get("receipt") or guardrail_preflight.get("firewall_event")
                ),
            )

        now = now_iso()
        with _runtime_write_lock(self.runtime):
            rollback_snapshot = _merge_rollback_snapshot(self.runtime, self.ledger)
            try:
                operation_results = [
                    _apply_merge_operation(
                        self.runtime,
                        operation,
                        approved_by=reviewer,
                        now=now,
                        knowledge_pr_id=pr_id,
                        operation_index=operation_index,
                    )
                    for operation_index, operation in enumerate(operations)
                ]
                failed = [result for result in operation_results if result.get("status") != "ok"]
                if failed:
                    rollback_report = _restore_merge_rollback_snapshot(self.runtime, self.ledger, rollback_snapshot)
                    return _merge_error(
                        pr_id,
                        "schema_failed",
                        "merge_operation_failed",
                        "one or more selected operations failed.",
                        details={
                            "operation_results": operation_results,
                            "rollback": rollback_report,
                        },
                    )

                proposed_writes = [
                    write
                    for result in operation_results
                    for write in result.get("proposed_writes") or []
                    if isinstance(write, dict)
                ]
                affected_refs = [
                    ref
                    for result in operation_results
                    for ref in result.get("affected_refs") or []
                    if isinstance(ref, dict)
                ]
                transaction = self.runtime.transactions.promote(
                    operation_kind="merge_knowledge_pr",
                    proposed_writes=[
                        *proposed_writes,
                        {"table": "knowledge_prs", "id": pr_id},
                    ],
                    idempotency_key=idempotency_key,
                    affected_refs=[{"kind": "knowledge_pr", "knowledge_pr_id": pr_id}, *affected_refs],
                )
                idempotent_replay = bool(transaction.get("idempotent_replay"))
                active_memory_write_performed = any(
                    bool(result.get("active_memory_write_performed"))
                    for result in operation_results
                )
                graph_write_performed = any(bool(result.get("graph_write_performed")) for result in operation_results)
                updated_pr = {
                    **record,
                    "status": "merged",
                    "merged_by": reviewer,
                    "merged_at": now,
                    "merge_transaction_id": transaction["transaction_id"],
                    "merge_transaction": transaction,
                    "merge_operation_results": operation_results,
                    "ci_waivers": _dict_list(ci_waivers),
                    "updated_at": now,
                }
                upsert_record(self.ledger, "knowledge_prs", pr_id, updated_pr)
            except Exception as error:  # pragma: no cover - defensive rollback around write phase
                rollback_report = _restore_merge_rollback_snapshot(self.runtime, self.ledger, rollback_snapshot)
                return _merge_error(
                    pr_id,
                    "schema_failed",
                    "merge_operation_exception",
                    "one or more selected operations raised during merge.",
                    details={
                        "exception": type(error).__name__,
                        "message": str(error),
                        "rollback": rollback_report,
                    },
                )
        return {
            "schema_version": KNOWLEDGE_PR_SCHEMA_VERSION,
            "status": "merged",
            "knowledge_pr_id": pr_id,
            "transaction": transaction,
            "operation_results": operation_results,
            "write_performed": not idempotent_replay,
            "active_memory_write_performed": active_memory_write_performed and not idempotent_replay,
            "graph_write_performed": graph_write_performed and not idempotent_replay,
            "idempotent_replay": idempotent_replay,
            "error": None,
        }


def _dict_list(values: list[dict[str, Any]] | Any | None) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    return [dict(value) for value in values if isinstance(value, dict)]


def _preflight_merge_memory_guardrails(
    runtime: Any,
    operations: list[dict[str, Any]],
    *,
    approved_by: str,
    knowledge_pr_id: str,
) -> dict[str, Any] | None:
    enforce = getattr(runtime, "_enforce_memory_guardrails", None)
    if not callable(enforce):
        return None
    for operation_index, operation in enumerate(operations):
        kind = str(operation.get("operation_kind") or "").strip()
        if kind == "memory_write":
            treatment = enforce(
                memory=_merge_guardrail_memory_payload(operation),
                approved_by=approved_by,
                context=_merge_guardrail_context(
                    knowledge_pr_id=knowledge_pr_id,
                    operation_index=operation_index,
                    operation_kind="merge_knowledge_pr",
                ),
            )
            if treatment.get("allowed") is not True:
                return treatment
        if kind in {"document_promotion", "document_promotion_transaction"}:
            nested = operation.get("promotion_transaction")
            if not isinstance(nested, dict):
                continue
            nested_operations = nested.get("operations")
            if not isinstance(nested_operations, list):
                continue
            selected = operation.get("selected_operation_indexes")
            selected_indexes = (
                selected
                if isinstance(selected, list)
                else list(range(len(nested_operations)))
            )
            for nested_index in selected_indexes:
                if not isinstance(nested_index, int) or nested_index < 0 or nested_index >= len(nested_operations):
                    continue
                nested_operation = nested_operations[nested_index]
                if not isinstance(nested_operation, dict) or nested_operation.get("kind") != "memory":
                    continue
                payload = nested_operation.get("payload")
                if not isinstance(payload, dict):
                    continue
                treatment = enforce(
                    memory=_merge_guardrail_memory_payload(payload),
                    approved_by=approved_by,
                    context=_merge_guardrail_context(
                        knowledge_pr_id=knowledge_pr_id,
                        operation_index=operation_index,
                        operation_kind="merge_knowledge_pr_document_promotion",
                        transaction_id=str(nested.get("transaction_id") or nested.get("id") or ""),
                    ),
                )
                if treatment.get("allowed") is not True:
                    return treatment
    return None


def _merge_guardrail_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": str(payload.get("key") or ""),
        "content": str(payload.get("content") or ""),
        "memory_type": str(payload.get("memory_type") or "fact").strip() or "fact",
        "scope": payload.get("scope"),
        "trust_state": payload.get("trust_state"),
        "status": payload.get("status"),
        "project": payload.get("project"),
        "domain": payload.get("domain"),
        "citations": _dict_list(payload.get("citations")),
    }


def _merge_guardrail_context(
    *,
    knowledge_pr_id: str,
    operation_index: int,
    operation_kind: str,
    transaction_id: str | None = None,
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "operation_kind": operation_kind,
        "knowledge_pr_id": knowledge_pr_id,
        "operation_index": operation_index,
    }
    if transaction_id:
        context["transaction_id"] = transaction_id
    return context


def _proposed_operations(values: list[dict[str, Any]] | Any | None) -> dict[str, Any]:
    if values is None:
        return {"operations": [], "error": None}
    if not isinstance(values, list) or any(not isinstance(value, dict) for value in values):
        return {
            "operations": [],
            "error": {"code": "invalid_proposed_operations"},
        }
    return {"operations": [dict(value) for value in values], "error": None}


def _gate_list(gates: list[str] | None) -> list[str]:
    if not isinstance(gates, list) or not gates:
        return list(DEFAULT_CI_GATES)
    return [str(gate).strip() for gate in gates if str(gate or "").strip()]


def _run_gate(
    gate_id: str,
    pr: dict[str, Any],
    context: dict[str, Any],
    runtime: Any,
) -> dict[str, Any]:
    if gate_id == "gate_provenance":
        return _gate_provenance(pr)
    if gate_id == "gate_document_coverage":
        return _gate_document_coverage(pr, context, runtime)
    if gate_id == "gate_graph_validity":
        return _gate_graph_validity(pr)
    if gate_id == "gate_retrieval_regression":
        return _gate_retrieval_regression(context)
    if gate_id == "gate_policy":
        return _gate_policy(pr, context)
    if gate_id == "gate_idempotency":
        return _gate_idempotency(pr)
    return _gate_result(
        gate_id,
        "error",
        "Unknown Memory CI gate.",
        findings=[{"code": "unknown_gate", "gate_id": gate_id}],
    )


def _gate_provenance(pr: dict[str, Any]) -> dict[str, Any]:
    operations = _operations(pr)
    if not operations:
        return _gate_result("gate_provenance", "not_applicable", "No proposed operations.")
    findings = [
        _operation_finding(operation, "missing_evidence_refs", "operation is missing evidence_refs")
        for operation in operations
        if not _operation_has_evidence(operation)
    ]
    if findings:
        return _gate_result(
            "gate_provenance",
            "blocked",
            "Every proposed operation must include evidence_refs.",
            findings=findings,
        )
    return _gate_result("gate_provenance", "passed", "Every operation has evidence refs.")


def _gate_document_coverage(
    pr: dict[str, Any],
    context: dict[str, Any],
    runtime: Any,
) -> dict[str, Any]:
    document_refs = _dict_list(pr.get("document_refs"))
    if not document_refs:
        return _gate_result("gate_document_coverage", "not_applicable", "No document refs.")

    previews = _document_completion_previews(context)
    if not previews and runtime is not None and hasattr(runtime, "prepare_document_ingestion_completion"):
        previews = _runtime_document_completion_previews(runtime, document_refs, context)
    if not previews:
        return _gate_result(
            "gate_document_coverage",
            "blocked",
            "Document refs require completion preview evidence.",
            findings=[
                {
                    "code": "document_completion_preview_required",
                    "document_refs": document_refs,
                }
            ],
        )

    findings: list[dict[str, Any]] = []
    for preview in previews:
        if preview.get("status") != "ok" or preview.get("usable") is not True:
            findings.append(
                {
                    "code": "document_completion_unmet",
                    "document_id": preview.get("document_id"),
                    "status": preview.get("status"),
                    "blocking_issues": list(preview.get("blocking_issues") or []),
                }
            )
    if findings:
        return _gate_result(
            "gate_document_coverage",
            "blocked",
            "One or more document completion previews are not usable.",
            findings=findings,
        )
    return _gate_result("gate_document_coverage", "passed", "Document coverage previews are usable.")


def _gate_graph_validity(pr: dict[str, Any]) -> dict[str, Any]:
    graph_operations = [
        operation for operation in _operations(pr)
        if str(operation.get("operation_kind") or "") in {"graph_edge", "graph_edges"}
    ]
    if not graph_operations:
        return _gate_result("gate_graph_validity", "not_applicable", "No graph operations.")

    findings: list[dict[str, Any]] = []
    for operation in graph_operations:
        edges = _graph_edge_candidates(operation)
        if not edges:
            findings.append(_operation_finding(operation, "graph_edge_required", "graph operation requires edges"))
            continue
        for edge_index, edge in enumerate(edges):
            edge_type = str(edge.get("edge_type") or "").strip()
            if not edge_type or edge_type not in GRAPH_EDGE_TYPES:
                findings.append(_operation_finding(operation, "invalid_edge_type", "edge_type is invalid", edge_index=edge_index))
            if not isinstance(edge.get("from_ref"), dict):
                findings.append(_operation_finding(operation, "from_ref_required", "from_ref is required", edge_index=edge_index))
            if not isinstance(edge.get("to_ref"), dict):
                findings.append(_operation_finding(operation, "to_ref_required", "to_ref is required", edge_index=edge_index))
    if findings:
        return _gate_result(
            "gate_graph_validity",
            "blocked",
            "Graph operations must include valid typed refs.",
            findings=findings,
        )
    return _gate_result("gate_graph_validity", "passed", "Graph operations are structurally valid.")


def _gate_retrieval_regression(context: dict[str, Any]) -> dict[str, Any]:
    receipts = context.get("retrieval_receipts") or context.get("retrieval_eval")
    if receipts is None:
        return _gate_result("gate_retrieval_regression", "not_applicable", "No retrieval receipts.")
    normalized = receipts if isinstance(receipts, list) else [receipts]
    findings = [
        {
            "code": "retrieval_regression",
            "receipt": receipt,
        }
        for receipt in normalized
        if isinstance(receipt, dict) and str(receipt.get("status") or "").lower() in {"failed", "fail", "error"}
    ]
    if findings:
        return _gate_result(
            "gate_retrieval_regression",
            "blocked",
            "Retrieval regression receipts failed.",
            findings=findings,
        )
    return _gate_result("gate_retrieval_regression", "passed", "Retrieval receipts passed.")


def _gate_policy(pr: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    policy_issues = [
        issue
        for issue in [
            *list(pr.get("policy_issues") or []),
            *list(pr.get("firewall_issues") or []),
            *list(context.get("policy_issues") or []),
            *list(context.get("firewall_issues") or []),
        ]
        if isinstance(issue, dict)
    ]
    if policy_issues:
        return _gate_result(
            "gate_policy",
            "blocked",
            "Policy or firewall issues block the PR.",
            findings=policy_issues,
        )
    return _gate_result("gate_policy", "passed", "No policy blockers were supplied.")


def _gate_idempotency(pr: dict[str, Any]) -> dict[str, Any]:
    operations = _operations(pr)
    if not operations:
        return _gate_result("gate_idempotency", "not_applicable", "No proposed operations.")
    findings = [
        _operation_finding(
            operation,
            "operation_id_required",
            "operation requires operation_id or idempotency_key",
        )
        for operation in operations
        if not str(operation.get("operation_id") or operation.get("idempotency_key") or "").strip()
    ]
    if findings:
        return _gate_result(
            "gate_idempotency",
            "blocked",
            "Every proposed operation requires a deterministic idempotency key.",
            findings=findings,
        )
    return _gate_result("gate_idempotency", "passed", "Every operation is idempotency-addressable.")


def _document_completion_previews(context: dict[str, Any]) -> list[dict[str, Any]]:
    previews = context.get("document_completion_previews") or context.get("document_completion_preview")
    if isinstance(previews, dict):
        return [previews]
    if isinstance(previews, list):
        return [dict(preview) for preview in previews if isinstance(preview, dict)]
    return []


def _runtime_document_completion_previews(
    runtime: Any,
    document_refs: list[dict[str, Any]],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    inputs_by_document_id = context.get("completion_inputs_by_document_id")
    if not isinstance(inputs_by_document_id, dict):
        return []
    previews: list[dict[str, Any]] = []
    for ref in document_refs:
        document_id = str(ref.get("document_id") or ref.get("id") or "").strip()
        if not document_id:
            continue
        inputs = inputs_by_document_id.get(document_id)
        if not isinstance(inputs, dict):
            continue
        previews.append(runtime.prepare_document_ingestion_completion(document_id=document_id, **inputs))
    return previews


def _operations(pr: dict[str, Any]) -> list[dict[str, Any]]:
    return _dict_list(pr.get("proposed_operations"))


def _operation_has_evidence(operation: dict[str, Any]) -> bool:
    if _non_empty_list(operation.get("evidence_refs")) or _non_empty_list(operation.get("evidence")):
        return True
    if str(operation.get("operation_kind") or "") != "graph_edges":
        return False
    edges = operation.get("edges")
    if not isinstance(edges, list) or not edges:
        return False
    return all(
        isinstance(edge, dict)
        and (_non_empty_list(edge.get("evidence_refs")) or _non_empty_list(edge.get("evidence")))
        for edge in edges
    )


def _graph_edge_candidates(operation: dict[str, Any]) -> list[dict[str, Any]]:
    if str(operation.get("operation_kind") or "") == "graph_edges":
        return [dict(edge) for edge in operation.get("edges") or [] if isinstance(edge, dict)]
    return [operation]


def _selected_operations(
    operations: list[dict[str, Any]],
    *,
    selected_operation_ids: list[str] | None,
    selected_operation_indexes: list[int] | None,
) -> list[dict[str, Any]]:
    if selected_operation_ids:
        selected = {str(value or "").strip() for value in selected_operation_ids if str(value or "").strip()}
        return [
            operation
            for operation in operations
            if _operation_identity(operation) in selected
        ]
    if selected_operation_indexes:
        indexes = {int(index) for index in selected_operation_indexes}
        return [
            operation
            for index, operation in enumerate(operations)
            if index in indexes
        ]
    return operations


def _ci_allows_merge(pr: dict[str, Any], ci_waivers: list[dict[str, Any]]) -> dict[str, Any]:
    summary = pr.get("ci_summary") if isinstance(pr.get("ci_summary"), dict) else {}
    blocking_gate_ids = [
        str(gate_id)
        for gate_id in summary.get("blocking_gate_ids") or []
        if str(gate_id or "").strip()
    ]
    if summary.get("status") == "passed" and not blocking_gate_ids:
        return {"status": "ok", "blocking_gate_ids": []}
    waiver_gate_ids = {
        str(waiver.get("gate_id") or "").strip()
        for waiver in ci_waivers
        if str(waiver.get("gate_id") or "").strip()
        and str(waiver.get("approved_by") or "").strip()
        and str(waiver.get("reason") or "").strip()
    }
    if blocking_gate_ids and set(blocking_gate_ids).issubset(waiver_gate_ids):
        return {"status": "waived", "blocking_gate_ids": blocking_gate_ids}
    code = "memory_ci_blocked" if blocking_gate_ids else "memory_ci_required"
    message = (
        "Knowledge PR has blocked Memory CI gates."
        if blocking_gate_ids
        else "Knowledge PR requires a passing Memory CI run before merge."
    )
    return {
        "status": "blocked",
        "blocking_gate_ids": blocking_gate_ids,
        "error": {"code": code, "message": message},
    }


def _validate_merge_operations(operations: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not operations:
        return {"code": "no_selected_operations", "message": "merge requires at least one selected operation."}
    for index, operation in enumerate(operations):
        if not _operation_identity(operation):
            return {
                "code": "operation_id_required",
                "message": "merge operation requires operation_id or idempotency_key.",
                "operation_index": index,
            }
        kind = str(operation.get("operation_kind") or "").strip()
        if kind == "memory_write":
            if not str(operation.get("key") or "").strip():
                return {"code": "memory_key_required", "message": "memory_write requires key.", "operation_index": index}
            if not str(operation.get("content") or "").strip():
                return {"code": "memory_content_required", "message": "memory_write requires content.", "operation_index": index}
            continue
        if kind in {"graph_edge", "graph_edges"}:
            edges = _graph_edge_candidates(operation)
            if not edges:
                return {"code": "graph_edge_required", "message": "graph operation requires at least one edge.", "operation_index": index}
            for edge_index, edge in enumerate(edges):
                edge_type = str(edge.get("edge_type") or "").strip()
                if edge_type not in GRAPH_EDGE_TYPES:
                    return {
                        "code": "invalid_edge_type",
                        "message": "graph operation requires a valid edge_type.",
                        "operation_index": index,
                        "edge_index": edge_index,
                    }
                if not isinstance(edge.get("from_ref"), dict) or not isinstance(edge.get("to_ref"), dict):
                    return {
                        "code": "graph_refs_required",
                        "message": "graph operation requires from_ref and to_ref.",
                        "operation_index": index,
                        "edge_index": edge_index,
                    }
            continue
        if kind in {"document_completion", "complete_document_ingestion"}:
            if not str(operation.get("document_id") or "").strip():
                return {"code": "document_id_required", "message": "document completion requires document_id.", "operation_index": index}
            completion_validation = _validate_document_completion_operation(operation)
            if completion_validation is not None:
                completion_validation["operation_index"] = index
                return completion_validation
            continue
        if kind in {"document_promotion", "document_promotion_transaction"}:
            promotion_validation = _validate_document_promotion_operation(operation)
            if promotion_validation is not None:
                promotion_validation["operation_index"] = index
                return promotion_validation
            continue
        return {"code": "unsupported_operation_kind", "message": f"unsupported operation_kind: {kind}", "operation_index": index}
    return None


def _validate_document_completion_operation(operation: dict[str, Any]) -> dict[str, Any] | None:
    completion_args = operation.get("completion_args")
    if not isinstance(completion_args, dict):
        return {
            "code": "completion_args_required",
            "message": "document completion requires completion_args.",
        }
    document_id = str(operation.get("document_id") or completion_args.get("document_id") or "").strip()
    promotion_transaction = completion_args.get("document_promotion_transaction")
    validation = _validate_document_promotion_transaction(
        promotion_transaction,
        expected_document_id=document_id,
        selected_operation_indexes=completion_args.get("selected_operation_indexes"),
        require_graph_edge=True,
    )
    if validation is not None:
        return validation
    return None


def _validate_document_promotion_operation(operation: dict[str, Any]) -> dict[str, Any] | None:
    promotion_transaction = operation.get("promotion_transaction")
    return _validate_document_promotion_transaction(
        promotion_transaction,
        expected_document_id=None,
        selected_operation_indexes=operation.get("selected_operation_indexes"),
        require_graph_edge=False,
    )


def _validate_document_promotion_transaction(
    transaction: Any,
    *,
    expected_document_id: str | None,
    selected_operation_indexes: Any,
    require_graph_edge: bool,
) -> dict[str, Any] | None:
    if not isinstance(transaction, dict):
        return {
            "code": "promotion_transaction_required",
            "message": "document promotion requires promotion_transaction.",
        }
    if transaction.get("record_type") != "document_promotion_transaction":
        return {
            "code": "invalid_promotion_transaction",
            "message": "record_type must be document_promotion_transaction.",
        }
    if expected_document_id is not None and str(transaction.get("document_id") or "") != expected_document_id:
        return {
            "code": "promotion_document_mismatch",
            "message": "promotion transaction document_id does not match document completion.",
        }

    operations = transaction.get("operations")
    if not isinstance(operations, list) or not operations:
        return {
            "code": "promotion_operations_required",
            "message": "document promotion transaction requires operations.",
        }
    selected = _validate_selected_document_promotion_indexes(selected_operation_indexes, len(operations))
    if isinstance(selected, dict):
        return selected

    saw_graph_edge = False
    for selected_index in selected:
        operation = operations[selected_index]
        if not isinstance(operation, dict):
            return {
                "code": "promotion_operation_required",
                "message": f"document promotion operation {selected_index} must be an object.",
                "promotion_operation_index": selected_index,
            }
        operation_kind = operation.get("kind")
        if operation_kind not in {"memory", "graph_edge"}:
            return {
                "code": "unsupported_promotion_operation_kind",
                "message": f"document promotion operation {selected_index} kind must be memory or graph_edge.",
                "promotion_operation_index": selected_index,
            }
        payload = operation.get("payload")
        if not isinstance(payload, dict):
            return {
                "code": "promotion_operation_payload_required",
                "message": f"document promotion operation {selected_index} payload is required.",
                "promotion_operation_index": selected_index,
            }
        if operation_kind == "memory":
            missing = _missing_document_promotion_text(payload, ("key", "content"))
            if missing is not None:
                return {
                    "code": f"memory_payload_{missing}_required",
                    "message": f"document promotion operation {selected_index} memory payload requires {missing}.",
                    "promotion_operation_index": selected_index,
                }
            continue

        saw_graph_edge = True
        for ref_field in ("from_ref", "to_ref"):
            if not isinstance(payload.get(ref_field), dict) or not payload.get(ref_field):
                return {
                    "code": f"graph_edge_payload_{ref_field}_required",
                    "message": f"document promotion operation {selected_index} graph edge payload requires {ref_field}.",
                    "promotion_operation_index": selected_index,
                }
        missing = _missing_document_promotion_text(payload, ("edge_type", "evidence"))
        if missing is not None:
            return {
                "code": f"graph_edge_payload_{missing}_required",
                "message": f"document promotion operation {selected_index} graph edge payload requires {missing}.",
                "promotion_operation_index": selected_index,
            }

    if require_graph_edge and not saw_graph_edge:
        return {
            "code": "graph_edges_required",
            "message": "document completion requires at least one selected graph edge.",
        }
    return None


def _validate_selected_document_promotion_indexes(value: Any, total: int) -> list[int] | dict[str, Any]:
    if value is None:
        return list(range(total))
    if not isinstance(value, list):
        return {
            "code": "selected_operation_indexes_invalid",
            "message": "selected_operation_indexes must be a list.",
        }
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
        return {
            "code": "selected_operations_required",
            "message": "at least one operation must be selected.",
        }
    return indexes


def _missing_document_promotion_text(payload: dict[str, Any], field_names: tuple[str, ...]) -> str | None:
    for field_name in field_names:
        if not str(payload.get(field_name) or "").strip():
            return field_name
    return None


def _apply_merge_operation(
    runtime: Any,
    operation: dict[str, Any],
    *,
    approved_by: str,
    now: str,
    knowledge_pr_id: str,
    operation_index: int,
) -> dict[str, Any]:
    kind = str(operation.get("operation_kind") or "").strip()
    operation_id = _operation_identity(operation)
    if kind == "memory_write":
        stored = runtime.store_memory(
            key=str(operation.get("key") or ""),
            content=str(operation.get("content") or ""),
            tags=_operation_string_list(operation.get("tags")),
            title=operation.get("title"),
            related_to=_operation_string_list(operation.get("related_to")),
            force=bool(operation.get("force", True)),
            project=operation.get("project"),
            domain=operation.get("domain"),
            status=operation.get("status"),
            canonical=operation.get("canonical"),
            memory_type=operation.get("memory_type"),
            scope=operation.get("scope"),
            trust_state=operation.get("trust_state"),
            retention_policy=operation.get("retention_policy"),
            sync_policy=operation.get("sync_policy"),
            document_id=operation.get("document_id"),
            source_id=operation.get("source_id"),
            source_document=operation.get("source_document") if isinstance(operation.get("source_document"), dict) else None,
            citations=_dict_list(operation.get("citations")),
            approved_by=approved_by,
            guardrail_context=_merge_guardrail_context(
                knowledge_pr_id=knowledge_pr_id,
                operation_index=operation_index,
                operation_kind="merge_knowledge_pr",
            ),
        )
        if stored.get("status") in {"policy_denied", "review_required"}:
            return {
                "status": stored.get("status"),
                "operation_id": operation_id,
                "operation_kind": kind,
                "error": stored.get("error") or {"code": "memory_guardrail_failed"},
                "guardrail": stored.get("guardrail"),
                "receipt": stored.get("guardrail_receipt"),
                "firewall_event": stored.get("firewall_event"),
                "active_memory_write_performed": False,
                "graph_write_performed": False,
            }
        return {
            "status": "ok",
            "operation_id": operation_id,
            "operation_kind": kind,
            "result_ref": {"kind": "memory", "key": stored["key"]},
            "proposed_writes": [{"table": "memories", "id": stored["key"]}],
            "affected_refs": [{"kind": "memory", "key": stored["key"]}],
            "active_memory_write_performed": True,
            "graph_write_performed": bool(
                stored.get("graph_treatment", {}).get("edge_ids")
                or stored.get("semantic_graph_treatment", {}).get("edge_ids")
            ),
        }
    if kind in {"graph_edge", "graph_edges"}:
        edges = _graph_edges_from_operation(operation, approved_by=approved_by, now=now)
        imported = runtime.graph.import_edges(edges)
        edge_ids = list(imported.get("edge_ids") or [edge["edge_id"] for edge in edges])
        return {
            "status": "ok",
            "operation_id": operation_id,
            "operation_kind": kind,
            "result_ref": {"kind": "graph_edges", "edge_ids": edge_ids},
            "proposed_writes": [{"table": "graph_edges", "id": edge_id} for edge_id in edge_ids],
            "affected_refs": [{"kind": "graph_edge", "edge_id": edge_id} for edge_id in edge_ids],
            "active_memory_write_performed": False,
            "graph_write_performed": bool(edge_ids),
        }
    if kind in {"document_completion", "complete_document_ingestion"}:
        kwargs = dict(operation.get("completion_args") or {})
        kwargs.setdefault("document_id", operation.get("document_id"))
        kwargs.pop("accept", None)
        kwargs.pop("approved_by", None)
        result = runtime.complete_document_ingestion(**kwargs, accept=True, approved_by=approved_by)
        if result.get("status") != "ok":
            return {
                "status": "failed",
                "operation_id": operation_id,
                "operation_kind": kind,
                "error": result.get("error") or {"code": "document_completion_failed"},
            }
        return {
            "status": "ok",
            "operation_id": operation_id,
            "operation_kind": kind,
            "result_ref": {"kind": "document", "document_id": result.get("document_id") or operation.get("document_id")},
            "proposed_writes": [{"table": "documents", "id": result.get("document_id") or operation.get("document_id")}],
            "affected_refs": [{"kind": "document", "document_id": result.get("document_id") or operation.get("document_id")}],
            "active_memory_write_performed": False,
            "graph_write_performed": bool(result.get("graph_write_performed")),
        }
    if kind in {"document_promotion", "document_promotion_transaction"}:
        result = runtime.apply_document_promotion_transaction(
            operation["promotion_transaction"],
            accept=True,
            approved_by=approved_by,
            selected_operation_indexes=operation.get("selected_operation_indexes"),
        )
        if result.get("status") != "ok":
            return {
                "status": "failed",
                "operation_id": operation_id,
                "operation_kind": kind,
                "error": result.get("error") or {"code": "document_promotion_failed"},
            }
        edge_ids = list(result.get("graph_edges_written") or [])
        memory_keys = list(result.get("memories_written") or [])
        return {
            "status": "ok",
            "operation_id": operation_id,
            "operation_kind": kind,
            "result_ref": {"kind": "document_promotion", "graph_edge_ids": edge_ids, "memory_keys": memory_keys},
            "proposed_writes": [
                *[{"table": "graph_edges", "id": edge_id} for edge_id in edge_ids],
                *[{"table": "memories", "id": key} for key in memory_keys],
            ],
            "affected_refs": [
                *[{"kind": "graph_edge", "edge_id": edge_id} for edge_id in edge_ids],
                *[{"kind": "memory", "key": key} for key in memory_keys],
            ],
            "active_memory_write_performed": bool(memory_keys),
            "graph_write_performed": bool(edge_ids),
        }
    return {
        "status": "failed",
        "operation_id": operation_id,
        "operation_kind": kind,
        "error": {"code": "unsupported_operation_kind"},
    }


def _graph_edges_from_operation(operation: dict[str, Any], *, approved_by: str, now: str) -> list[dict[str, Any]]:
    raw_edges = _graph_edge_candidates(operation)
    edges: list[dict[str, Any]] = []
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, dict):
            continue
        from_ref = raw_edge.get("from_ref") if isinstance(raw_edge.get("from_ref"), dict) else None
        to_ref = raw_edge.get("to_ref") if isinstance(raw_edge.get("to_ref"), dict) else None
        edge_type = str(raw_edge.get("edge_type") or "").strip()
        if not from_ref or not to_ref or not edge_type:
            continue
        edge = {
            "edge_id": str(raw_edge.get("edge_id") or stable_id(
                "edge",
                {
                    "operation_id": _operation_identity(operation),
                    "from_ref": from_ref,
                    "edge_type": edge_type,
                    "to_ref": to_ref,
                },
            )),
            "from_ref": dict(from_ref),
            "to_ref": dict(to_ref),
            "edge_type": edge_type,
            "confidence": float(raw_edge.get("confidence", operation.get("confidence", 0.75))),
            "evidence": list(
                raw_edge.get("evidence")
                or raw_edge.get("evidence_refs")
                or operation.get("evidence_refs")
                or []
            ),
            "source": str(raw_edge.get("source") or operation.get("source") or "knowledge_pr.merge"),
            "status": str(raw_edge.get("status") or "active"),
            "created_by": str(raw_edge.get("created_by") or approved_by),
            "created_at": str(raw_edge.get("created_at") or now),
            "updated_at": now,
        }
        edges.append(edge)
    return edges


def _operation_identity(operation: dict[str, Any]) -> str:
    return str(operation.get("operation_id") or operation.get("idempotency_key") or "").strip()


def _operation_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    return []


def _merge_idempotency_key(pr: dict[str, Any], operations: list[dict[str, Any]]) -> str:
    operation_ids = [_operation_identity(operation) for operation in operations]
    return f"merge_knowledge_pr:{pr['knowledge_pr_id']}:{hash_payload(operation_ids or operations)}"


def _runtime_write_lock(runtime: Any):
    lock = getattr(runtime, "write_lock", None)
    if hasattr(lock, "__enter__") and hasattr(lock, "__exit__"):
        return lock
    return nullcontext()


def _merge_rollback_snapshot(runtime: Any, ledger: MemoryOSLedger) -> dict[str, Any]:
    snapshot: dict[str, Any] = {"tables": {}, "graph": None}
    ledger.initialize()
    with ledger.connect() as conn:
        for table in TABLES:
            select_query = f"SELECT id, payload_json, created_at, updated_at FROM {table} ORDER BY id"  # nosec B608
            rows = conn.execute(select_query).fetchall()
            snapshot["tables"][table] = [
                {
                    "id": row["id"],
                    "payload_json": row["payload_json"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
                for row in rows
            ]

    graph_service = getattr(runtime, "graph", None)
    graph_store = getattr(graph_service, "graph_store", None)
    if graph_store is not None and hasattr(graph_store, "load_graph") and hasattr(graph_store, "save_graph"):
        snapshot["graph"] = deepcopy(graph_store.load_graph())
    return snapshot


def _restore_merge_rollback_snapshot(
    runtime: Any,
    ledger: MemoryOSLedger,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    report = {
        "ledger_restored": False,
        "graph_restored": False,
        "retrieval_rebuilt": False,
        "errors": [],
    }

    try:
        graph_snapshot = snapshot.get("graph")
        graph_service = getattr(runtime, "graph", None)
        graph_store = getattr(graph_service, "graph_store", None)
        if graph_snapshot is not None and graph_store is not None and hasattr(graph_store, "save_graph"):
            graph_store.save_graph(graph_snapshot)
            report["graph_restored"] = True
    except Exception as error:  # pragma: no cover - defensive rollback reporting
        report["errors"].append(
            {
                "stage": "graph_restore",
                "exception": type(error).__name__,
                "message": str(error),
            }
        )

    try:
        table_rows = snapshot.get("tables") if isinstance(snapshot.get("tables"), dict) else {}
        ledger.initialize()
        with ledger.connect() as conn:
            for table in TABLES:
                conn.execute(f"DELETE FROM {table}")  # nosec B608
                rows = table_rows.get(table) or []
                insert_query = f"""
                    INSERT INTO {table} (id, payload_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    """  # nosec B608
                conn.executemany(
                    insert_query,
                    [
                        (
                            row["id"],
                            row["payload_json"],
                            row["created_at"],
                            row["updated_at"],
                        )
                        for row in rows
                        if isinstance(row, dict)
                    ],
                )
            conn.commit()
        report["ledger_restored"] = True
    except Exception as error:  # pragma: no cover - defensive rollback reporting
        report["errors"].append(
            {
                "stage": "ledger_restore",
                "exception": type(error).__name__,
                "message": str(error),
            }
        )

    try:
        retrieval = getattr(runtime, "retrieval", None)
        rebuild = getattr(retrieval, "rebuild_from_ledger", None)
        if callable(rebuild):
            rebuild(force=True)
            report["retrieval_rebuilt"] = True
    except Exception as error:  # pragma: no cover - defensive rollback reporting
        report["errors"].append(
            {
                "stage": "retrieval_rebuild",
                "exception": type(error).__name__,
                "message": str(error),
            }
        )

    return report


def _transaction_by_idempotency_key(ledger: MemoryOSLedger, idempotency_key: str) -> dict[str, Any] | None:
    for transaction in list_records(ledger, "transactions"):
        if transaction.get("idempotency_key") == idempotency_key:
            return transaction
    return None


def _merged_pr_replay(ledger: MemoryOSLedger, record: dict[str, Any], *, write_performed: bool) -> dict[str, Any]:
    transaction = record.get("merge_transaction") if isinstance(record.get("merge_transaction"), dict) else None
    if transaction is None:
        transaction_id = str(record.get("merge_transaction_id") or "").strip()
        if transaction_id:
            for candidate in list_records(ledger, "transactions"):
                if candidate.get("transaction_id") == transaction_id:
                    transaction = candidate
                    break
    pr_id = str(record.get("knowledge_pr_id") or "")
    if transaction is None:
        return _merge_error(
            pr_id,
            "policy_denied",
            "already_merged",
            "Knowledge PR is already merged but no merge transaction was found.",
        )
    replay = dict(transaction)
    replay["idempotent_replay"] = True
    return {
        "schema_version": KNOWLEDGE_PR_SCHEMA_VERSION,
        "status": "merged",
        "knowledge_pr_id": pr_id,
        "transaction": replay,
        "operation_results": list(record.get("merge_operation_results") or []),
        "write_performed": write_performed,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "idempotent_replay": True,
        "error": None,
    }


def _blocking_issues(gate_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for result in gate_results:
        if result.get("required") is not True or result.get("status") not in {"blocked", "error"}:
            continue
        issues.append(
            {
                "code": "memory_ci_gate_blocked",
                "gate_id": result.get("gate_id"),
                "message": result.get("message"),
                "findings": list(result.get("findings") or []),
            }
        )
    return issues


def _gate_result(
    gate_id: str,
    status: str,
    message: str,
    *,
    findings: list[dict[str, Any]] | None = None,
    required: bool = True,
) -> dict[str, Any]:
    return {
        "gate_id": gate_id,
        "status": status if status in CI_STATUSES else "error",
        "required": required,
        "message": message,
        "findings": list(findings or []),
    }


def _operation_finding(
    operation: dict[str, Any],
    code: str,
    message: str,
    *,
    edge_index: int | None = None,
) -> dict[str, Any]:
    finding = {
        "code": code,
        "message": message,
        "operation_id": operation.get("operation_id"),
        "operation_kind": operation.get("operation_kind"),
    }
    if edge_index is not None:
        finding["edge_index"] = edge_index
    return finding


def _merge_ids(values: list[Any]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        merged.append(text)
    return merged


def _non_empty_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value)


def _required_text(value: str | None, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _with_no_active_writes(payload: dict[str, Any], *, write_performed: bool) -> dict[str, Any]:
    return {
        **payload,
        "write_performed": write_performed,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "error": None,
    }


def _error(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {
        "schema_version": KNOWLEDGE_PR_SCHEMA_VERSION,
        "status": "not_found" if code == "not_found" else "schema_failed",
        **extra,
        "write_performed": False,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "error": {"code": code, "category": "knowledge_pr", "message": message},
    }


def _merge_error(
    knowledge_pr_id: str,
    status: str,
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    write_performed: bool = False,
) -> dict[str, Any]:
    error = {"code": code, "category": "knowledge_pr_merge", "message": message}
    if details is not None:
        error["details"] = details
    return {
        "schema_version": KNOWLEDGE_PR_SCHEMA_VERSION,
        "status": status,
        "knowledge_pr_id": knowledge_pr_id,
        "write_performed": write_performed,
        "active_memory_write_performed": False,
        "graph_write_performed": False,
        "idempotent_replay": False,
        "error": error,
    }
