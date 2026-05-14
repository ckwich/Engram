from __future__ import annotations

from typing import Any


BACKEND_GATE_SCHEMA_VERSION = "2026-05-13.backend-gate.v1"
BLOCKING_STATUSES = {"blocked", "fail", "failed", "error", "skipped"}
READY_STATUSES = {"pass", "ready", "ready_for_default"}


def build_backend_gate_report(
    *,
    backend: str,
    source_status: dict[str, Any],
    source_operation: str,
    live_changed_field: str,
    parity_probe_field: str,
) -> dict[str, Any]:
    readiness_gates = dict(source_status.get("readiness_gates") or {})
    blocking_failures = _blocking_failures(readiness_gates)
    windows_status = _windows_status(readiness_gates)
    if windows_status["status"] != "pass":
        blocking_failures.append(
            {
                "gate": "windows_reliability",
                "status": windows_status["status"],
                "evidence": windows_status["evidence"],
            }
        )
    live_changed = bool(source_status.get(live_changed_field))
    if live_changed:
        blocking_failures.append(
            {
                "gate": live_changed_field,
                "status": "failed",
                "evidence": "Backend readiness gates must not switch live backends.",
            }
        )

    decision = _decision(readiness_gates, blocking_failures)
    return {
        "schema_version": BACKEND_GATE_SCHEMA_VERSION,
        "operation": f"{backend}_backend_gate",
        "backend": backend,
        "decision": decision,
        "source_operation": source_operation,
        "source_schema_version": source_status.get("schema_version"),
        "write_policy": "read_only",
        "write_performed": False,
        "active_memory_write_performed": False,
        "live_backend_changed": live_changed,
        "runtime_mode": source_status.get("runtime_mode"),
        "daemon_owned": bool(source_status.get("daemon_owned")),
        "direct_mode_legacy": bool(source_status.get("direct_mode_legacy")),
        "candidate_dependency_available": bool(source_status.get("candidate_dependency_available")),
        "corpus_parity_status": source_status.get("corpus_parity_status") or {},
        "recovery_gate_status": source_status.get("recovery_gate_status") or {},
        "operator_docs_status": source_status.get("operator_docs_status") or {},
        "live_switch_decision": source_status.get("live_switch_decision") or {},
        "blocking_failures": blocking_failures,
        "parity": source_status.get(parity_probe_field) or {},
        "windows_status": windows_status,
        "rebuild_status": source_status.get("rebuild_probe") or {},
        "filtering_status": _filtering_status(readiness_gates),
        "readiness_gates": readiness_gates,
        "recommendation": source_status.get("recommendation") or "",
        "source_status": source_status,
        "error": source_status.get("error"),
    }


def _blocking_failures(readiness_gates: dict[str, Any]) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    for gate, payload in sorted(readiness_gates.items()):
        if not isinstance(payload, dict):
            continue
        status = str(payload.get("status") or "unknown")
        if status.lower() in BLOCKING_STATUSES:
            failures.append(
                {
                    "gate": gate,
                    "status": status,
                    "evidence": str(payload.get("evidence") or ""),
                }
            )
    return failures


def _windows_status(readiness_gates: dict[str, Any]) -> dict[str, str]:
    for gate, payload in readiness_gates.items():
        if "windows" not in gate.lower() or not isinstance(payload, dict):
            continue
        return {
            "gate": gate,
            "status": str(payload.get("status") or "unknown"),
            "evidence": str(payload.get("evidence") or ""),
        }
    return {
        "gate": "windows_reliability",
        "status": "blocked",
        "evidence": "No explicit Windows path/restart reliability gate was reported.",
    }


def _filtering_status(readiness_gates: dict[str, Any]) -> dict[str, str]:
    for gate, payload in readiness_gates.items():
        if "filter" not in gate.lower() or not isinstance(payload, dict):
            continue
        return {
            "gate": gate,
            "status": str(payload.get("status") or "unknown"),
            "evidence": str(payload.get("evidence") or ""),
        }
    return {
        "gate": "metadata_filtering",
        "status": "unknown",
        "evidence": "No explicit metadata-filtering gate was reported.",
    }


def _decision(readiness_gates: dict[str, Any], blocking_failures: list[dict[str, str]]) -> str:
    if blocking_failures:
        return "not_ready"
    live_switch = readiness_gates.get("live_backend_switch")
    if isinstance(live_switch, dict) and str(live_switch.get("status") or "").lower() in READY_STATUSES:
        return "ready_for_default"
    if readiness_gates:
        return "ready_for_shadow"
    return "not_ready"
