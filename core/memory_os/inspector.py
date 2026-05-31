"""Read-only Memory OS inspector payloads."""
from __future__ import annotations

from typing import Any

from core.hub_client_config import read_hub_client_config, validate_hub_client_config
from core.memory_os._records import hash_payload, list_records
from core.memory_os.capability_discovery import build_capability_catalog
from core.memory_os.knowledge_pr_read_model import build_knowledge_pr_review_state
from core.memory_os.snapshots import snapshot_manifest_semantics

INSPECTOR_SCHEMA_VERSION = "2026-05-13.memory-os-inspector.v1"
REVIEW_RECORD_TYPES = {
    "document_draft",
    "document_intake_review",
    "document_understanding_packet",
    "source_draft",
}
REVIEW_STATUSES = {
    "candidate",
    "draft",
    "needs_review",
    "pending",
    "pending_review",
    "ready_for_review",
    "review_required",
}
SENSITIVE_SYNC_FIELD_FRAGMENTS = ("private", "secret", "token", "passphrase", "seed")
RELEASE_GATE_COMMANDS = (
    {
        "command": "python server.py --help",
        "purpose": "prove the MCP entrypoint imports and exposes CLI help",
    },
    {
        "command": 'python -c "from core.memory_manager import memory_manager; print(\'ok\')"',
        "purpose": "prove legacy JSON/Chroma compatibility imports",
    },
    {
        "command": "python engramd.py --doctor",
        "purpose": "check daemon process hygiene and store ownership",
    },
    {
        "command": "python engramd.py --smoke-test",
        "purpose": "prove daemon store/search/read/delete health",
    },
    {
        "command": "python server.py --self-test",
        "purpose": "prove direct MCP store/search/retrieve/delete behavior",
    },
    {
        "command": "python server.py --agent-eval",
        "purpose": "agent-facing retrieval/source/document workflow gates",
    },
    {
        "command": "python -m pytest tests/architecture tests/mcp tests/policy tests/backend_gates tests/release -q",
        "purpose": "pre-EKC architecture, policy, backend, and release gates",
    },
    {
        "command": "python -m pytest -q",
        "purpose": "full repository regression suite",
    },
    {
        "command": "git diff --check",
        "purpose": "whitespace and patch hygiene",
    },
)


def build_memory_os_inspector(runtime: Any, *, limit: int = 20) -> dict[str, Any]:
    """Build a compact read-only snapshot of daemon-owned Memory OS state."""
    bounded_limit = max(1, min(int(limit), 100))
    ledger = runtime.ledger
    status = runtime.status()

    jobs = _records_section(ledger, "jobs", bounded_limit)
    transactions = _records_section(ledger, "transactions", bounded_limit)
    coverage_maps = _records_section(ledger, "retrieval_receipts", bounded_limit)
    activation_receipts = _records_section(ledger, "activation_receipts", bounded_limit)
    memory_guardrail_receipts = _records_section(ledger, "memory_guardrail_receipts", bounded_limit)
    firewall = _records_section(ledger, "firewall_events", bounded_limit)
    snapshots = _snapshot_manifest_section(ledger, bounded_limit)
    skill_packs = _records_section(ledger, "skill_packs", bounded_limit)
    knowledge_artifacts = _records_section(ledger, "knowledge_artifacts", bounded_limit)
    transaction_records = list_records(ledger, "transactions")
    knowledge_branches = _records_section(ledger, "knowledge_branches", bounded_limit)
    memory_ci_runs = _records_section(ledger, "memory_ci_runs", bounded_limit)
    knowledge_pr_review_state = build_knowledge_pr_review_state(
        ledger,
        limit=bounded_limit,
    )
    graph_edge_records = list_records(ledger, "graph_edges")
    draft_records = list_records(ledger, "drafts")
    graph_edges = _latest(graph_edge_records, bounded_limit)
    entities = _latest(list_records(ledger, "entities"), bounded_limit)
    concepts = _latest(list_records(ledger, "concepts"), bounded_limit)
    aliases = _latest(list_records(ledger, "aliases"), bounded_limit)
    sources = _records_section(ledger, "sources", bounded_limit)
    documents = _records_section(ledger, "documents", bounded_limit)
    drafts = _section_from_records("drafts", draft_records, bounded_limit)
    review_queue = _section_from_records(
        "review_preparation_queue",
        _review_queue_records(draft_records),
        bounded_limit,
    )
    document_artifact_transactions = _section_from_records(
        "document_artifact_transactions",
        [record for record in transaction_records if _is_document_artifact_transaction(record)],
        bounded_limit,
    )
    promotion_transactions = _section_from_records(
        "promotion_transactions",
        [record for record in transaction_records if _is_document_promotion_transaction(record)],
        bounded_limit,
    )
    graph_evidence = _graph_evidence_section(graph_edge_records, bounded_limit)
    capability_discovery = build_capability_catalog(runtime, budget_chars=12000)
    sync_status = _runtime_sync_status(runtime)
    sync_devices = _sync_records_section(ledger, "sync_devices", bounded_limit)
    sync_cursors = _sync_records_section(ledger, "sync_cursors", bounded_limit)
    sync_changesets = _sync_records_section(ledger, "sync_changesets", bounded_limit)
    sync_conflicts = _sync_records_section(ledger, "sync_conflicts", bounded_limit)
    ekc_eval_summary = _ekc_eval_summary()
    release_gate_commands = _release_gate_commands_section()
    sync_panel = _sync_panel(
        status=status,
        sync_status=sync_status,
        sync_devices=sync_devices,
        sync_cursors=sync_cursors,
        sync_changesets=sync_changesets,
        sync_conflicts=sync_conflicts,
        snapshots=snapshots,
    )

    return {
        "schema_version": INSPECTOR_SCHEMA_VERSION,
        "write_performed": False,
        "limit": bounded_limit,
        "runtime": status,
        "daemon_status": {
            "status": status.get("status", "unknown") if isinstance(status, dict) else "unknown",
            "runtime": status,
            "write_performed": False,
        },
        "summary": {
            "job_count": jobs["count"],
            "transaction_count": transactions["count"],
            "coverage_map_count": coverage_maps["count"],
            "activation_receipt_count": activation_receipts["count"],
            "memory_guardrail_receipt_count": memory_guardrail_receipts["count"],
            "firewall_event_count": firewall["count"],
            "snapshot_count": snapshots["count"],
            "skill_pack_count": skill_packs["count"],
            "knowledge_artifact_count": knowledge_artifacts["count"],
            "knowledge_branch_count": knowledge_pr_review_state["branch_count"],
            "knowledge_pr_count": knowledge_pr_review_state["knowledge_pr_count"],
            "memory_ci_run_count": knowledge_pr_review_state["memory_ci_run_count"],
            "knowledge_pr_open_count": knowledge_pr_review_state["open_count"],
            "knowledge_pr_mergeable_count": knowledge_pr_review_state["mergeable_count"],
            "knowledge_pr_ci_blocked_count": knowledge_pr_review_state["ci_blocked_count"],
            "memory_ci_blocked_gate_count": knowledge_pr_review_state["blocked_ci_gate_count"],
            "graph_edge_count": len(graph_edges),
            "entity_count": len(entities),
            "concept_count": len(concepts),
            "source_count": sources["count"],
            "document_count": documents["count"],
            "draft_count": drafts["count"],
            "review_queue_count": review_queue["count"],
            "document_artifact_transaction_count": document_artifact_transactions["count"],
            "promotion_transaction_count": promotion_transactions["count"],
            "graph_evidence_count": graph_evidence["edge_count"],
            "graph_contradiction_count": graph_evidence["contradiction_count"],
            "capability_group_count": len(capability_discovery.get("capability_groups") or {}),
            "sync_device_count": sync_devices["count"],
            "sync_peer_count": sync_status.get("peer_count", 0),
            "sync_pending_conflict_count": sync_status.get("pending_conflict_count", 0),
            "sync_active_mode": sync_panel["active_mode"],
            "sync_rebuild_required": sync_panel["rebuild_required"],
            "ekc_eval_scenario_count": ekc_eval_summary["scenario_count"],
            "release_gate_command_count": release_gate_commands["count"],
        },
        "migration_import": {
            "sources": sources,
            "documents": documents,
            "drafts": drafts,
        },
        "jobs": jobs,
        "transactions": transactions,
        "graph": {
            "edge_count": len(graph_edges),
            "edges": graph_edges,
            "paths": [],
            "write_performed": False,
        },
        "entity_registry": {
            "entity_count": len(entities),
            "concept_count": len(concepts),
            "alias_count": len(aliases),
            "entities": entities,
            "concepts": concepts,
            "aliases": aliases,
            "write_performed": False,
        },
        "firewall_queue": firewall,
        "coverage_maps": coverage_maps,
        "activation_receipts": activation_receipts,
        "memory_guardrail_receipts": memory_guardrail_receipts,
        "knowledge_artifacts": knowledge_artifacts,
        "knowledge_branches": knowledge_branches,
        "knowledge_pr_review_state": {
            "branches": knowledge_branches,
            "pull_requests": _records_section(ledger, "knowledge_prs", bounded_limit),
            "memory_ci_runs": memory_ci_runs,
            **knowledge_pr_review_state,
        },
        "review_preparation_queue": review_queue,
        "document_artifact_transactions": document_artifact_transactions,
        "promotion_transactions": promotion_transactions,
        "graph_evidence": graph_evidence,
        "capability_discovery": capability_discovery,
        "sync": {
            "status": sync_status,
            "devices": sync_devices,
            "cursors": sync_cursors,
            "changesets": sync_changesets,
            "conflicts": sync_conflicts,
            "panel": sync_panel,
            "write_performed": False,
        },
        "ekc_eval_summary": ekc_eval_summary,
        "release_gate_commands": release_gate_commands,
        "snapshots": snapshots,
        "skill_packs": skill_packs,
    }


def _records_section(ledger: Any, table: str, limit: int) -> dict[str, Any]:
    records = list_records(ledger, table)
    return _section_from_records(table, records, limit)


def _sync_records_section(ledger: Any, table: str, limit: int) -> dict[str, Any]:
    records = [_redact_sensitive_sync_fields(record) for record in list_records(ledger, table)]
    return _section_from_records(table, records, limit)


def _runtime_sync_status(runtime: Any) -> dict[str, Any]:
    if not hasattr(runtime, "sync_status"):
        return {
            "status": "not_configured",
            "local_device": None,
            "peer_count": 0,
            "active_peer_count": 0,
            "revoked_peer_count": 0,
            "pending_conflict_count": 0,
            "last_exported_at": None,
            "last_applied_at": None,
        }
    result = runtime.sync_status()
    return result if isinstance(result, dict) else {}


def _sync_panel(
    *,
    status: dict[str, Any] | Any,
    sync_status: dict[str, Any],
    sync_devices: dict[str, Any],
    sync_cursors: dict[str, Any],
    sync_changesets: dict[str, Any],
    sync_conflicts: dict[str, Any],
    snapshots: dict[str, Any],
) -> dict[str, Any]:
    peers = _sync_peers(sync_devices.get("items") or [])
    pending_conflicts = int(sync_status.get("pending_conflict_count") or 0)
    if pending_conflicts == 0:
        pending_conflicts = len(_pending_sync_conflicts(sync_conflicts.get("items") or []))
    hub = _hub_panel_state()
    active_mode = _sync_active_mode(
        hub=hub,
        peer_count=len(peers),
        cursor_count=int(sync_cursors.get("count") or 0),
        changeset_count=int(sync_changesets.get("count") or 0),
        pending_conflicts=pending_conflicts,
    )
    warnings = _sync_panel_warnings(hub=hub, active_mode=active_mode)
    rebuild_required = _runtime_rebuild_required(status)
    panel = {
        "schema_version": "2026-05-26.sync-inspector-panel.v1",
        "active_mode": active_mode,
        "hub": hub,
        "warnings": warnings,
        "local_device_id": _local_device_id(sync_status),
        "peers": peers,
        "peer_direction_health": _peer_direction_health(
            peers=peers,
            changesets=sync_changesets.get("items") or [],
            cursors=sync_cursors.get("items") or [],
            conflicts=sync_conflicts.get("items") or [],
        ),
        "last_export": _latest_sync_event(sync_changesets.get("items") or [], "exported_at"),
        "last_apply": _latest_sync_event(sync_cursors.get("items") or [], "applied_at"),
        "pending_conflicts": pending_conflicts,
        "last_snapshot_id": _last_snapshot_id(snapshots),
        "rebuild_required": rebuild_required,
        "safe_next_command": _sync_safe_next_command(
            hub=hub,
            local_device_id=_local_device_id(sync_status),
            peer_count=len(peers),
            pending_conflicts=pending_conflicts,
            rebuild_required=rebuild_required,
        ),
        "write_performed": False,
    }
    return _redact_sensitive_sync_fields(panel)


def _hub_panel_state() -> dict[str, Any]:
    config = read_hub_client_config()
    validation = validate_hub_client_config(config)
    configured = bool(config.get("hub_configured"))
    hub_url = config.get("hub_url") if configured and not config.get("hub_url_error") else None
    status = str(validation.get("status") or "unknown")
    return {
        "configured": configured,
        "status": status,
        "auth_ready": status == "ready",
        "url_fingerprint": hash_payload(hub_url) if hub_url else None,
        "auth_fingerprint": validation.get("token_fingerprint") or config.get("token_fingerprint"),
        "reachability": {
            "status": "not_checked" if configured else "not_configured",
            "checked": False,
            "reason": "inspector_does_not_probe_network",
        },
        "error": _safe_error(validation.get("error") or config.get("hub_url_error")),
        "write_performed": False,
    }


def _safe_error(error: Any) -> dict[str, Any] | None:
    if not isinstance(error, dict):
        return None
    safe: dict[str, Any] = {}
    if error.get("code"):
        safe["code"] = str(error["code"])
    if error.get("message"):
        safe["message"] = str(error["message"])
    return safe or None


def _sync_active_mode(
    *,
    hub: dict[str, Any],
    peer_count: int,
    cursor_count: int,
    changeset_count: int,
    pending_conflicts: int,
) -> str:
    if hub.get("configured"):
        return "hub" if hub.get("auth_ready") is True else "standalone"
    if peer_count or cursor_count or changeset_count or pending_conflicts:
        return "reconciliation"
    return "loopback"


def _sync_panel_warnings(*, hub: dict[str, Any], active_mode: str) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    if hub.get("configured") and active_mode == "standalone":
        warnings.append(
            {
                "code": "hub_configured_but_not_ready",
                "severity": "warning",
                "message": "Hub configuration is present but not ready; client mode should fail closed.",
            }
        )
    return warnings


def _local_device_id(sync_status: dict[str, Any]) -> str | None:
    local = sync_status.get("local_device") if isinstance(sync_status.get("local_device"), dict) else {}
    device_id = str(local.get("device_id") or "").strip()
    return device_id or None


def _sync_peers(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    peers = []
    for record in records:
        if str(record.get("record_type") or "") != "sync_peer":
            continue
        peers.append(
            {
                "device_id": record.get("device_id"),
                "device_name": record.get("device_name"),
                "status": record.get("status"),
                "sync_allowed": bool(record.get("sync_allowed")),
                "transport": _sync_transport_summary(record.get("transport")),
            }
        )
    return peers


def _sync_transport_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"configured": False}
    url = str(value.get("url") or "").strip()
    trust = value.get("url_trust") if isinstance(value.get("url_trust"), dict) else {}
    return {
        "configured": bool(url),
        "url_fingerprint": hash_payload(url) if url else None,
        "mode": value.get("mode"),
        "allow_pull": bool(value.get("allow_pull")),
        "url_trust_status": trust.get("status"),
    }


def _peer_direction_health(
    *,
    peers: list[dict[str, Any]],
    changesets: list[dict[str, Any]],
    cursors: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    health = []
    pending_conflicts = _pending_sync_conflicts(conflicts)
    for peer in peers:
        peer_id = str(peer.get("device_id") or "")
        peer_changesets = [
            record for record in changesets
            if peer_id in {str(record.get("target_device_id") or ""), str(record.get("peer_id") or "")}
        ]
        peer_cursors = [
            record for record in cursors
            if peer_id in {str(record.get("source_device_id") or ""), str(record.get("peer_id") or "")}
        ]
        peer_conflicts = [
            record for record in pending_conflicts
            if peer_id in {str(record.get("source_device_id") or ""), str(record.get("peer_id") or "")}
        ]
        health.append(
            {
                "peer_id": peer_id,
                "outbound_lag": {
                    "exported_changeset_count": len(peer_changesets),
                    "last_exported_at": _latest_timestamp_value(peer_changesets, "exported_at"),
                },
                "inbound_lag": {
                    "cursor_count": len(peer_cursors),
                    "last_applied_at": _latest_timestamp_value(peer_cursors, "applied_at"),
                },
                "convergence_status": _peer_convergence_status(
                    changesets=peer_changesets,
                    cursors=peer_cursors,
                    conflicts=peer_conflicts,
                ),
            }
        )
    return health


def _peer_convergence_status(
    *,
    changesets: list[dict[str, Any]],
    cursors: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
) -> str:
    if conflicts:
        return "conflicts_pending"
    if changesets or cursors:
        return "converged"
    return "unknown"


def _pending_sync_conflicts(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        record for record in records
        if str(record.get("status") or "pending_review") not in {"resolved", "dismissed"}
    ]


def _latest_sync_event(records: list[dict[str, Any]], field: str) -> dict[str, Any] | None:
    latest = _latest_record_by_timestamp(records, field)
    if latest is None:
        return None
    return {
        key: value
        for key, value in latest.items()
        if key in {
            field,
            "changeset_id",
            "cursor_id",
            "source_device_id",
            "target_device_id",
            "peer_id",
            "row_count",
            "conflict_count",
        }
    }


def _latest_record_by_timestamp(records: list[dict[str, Any]], field: str) -> dict[str, Any] | None:
    candidates = [record for record in records if record.get(field)]
    if not candidates:
        return None
    return sorted(candidates, key=lambda record: str(record.get(field) or ""))[-1]


def _latest_timestamp_value(records: list[dict[str, Any]], field: str) -> str | None:
    record = _latest_record_by_timestamp(records, field)
    return str(record.get(field)) if record and record.get(field) else None


def _last_snapshot_id(snapshots: dict[str, Any]) -> str | None:
    items = snapshots.get("items") if isinstance(snapshots.get("items"), list) else []
    if not items:
        return None
    snapshot_id = str(items[0].get("snapshot_id") or "").strip()
    return snapshot_id or None


def _runtime_rebuild_required(status: dict[str, Any] | Any) -> bool:
    if not isinstance(status, dict):
        return False
    components = status.get("components") if isinstance(status.get("components"), dict) else {}
    for name in ("retrieval", "graph"):
        component = components.get(name) if isinstance(components.get(name), dict) else {}
        state = component.get("state") if isinstance(component.get("state"), dict) else {}
        status_value = str(component.get("status") or state.get("status") or "").strip().lower()
        if component.get("ready") is False:
            return True
        if status_value in {"repair_pending", "stale", "stale_manifest", "needs_rebuild", "missing"}:
            return True
    return False


def _sync_safe_next_command(
    *,
    hub: dict[str, Any],
    local_device_id: str | None,
    peer_count: int,
    pending_conflicts: int,
    rebuild_required: bool,
) -> str:
    if hub.get("configured") and hub.get("auth_ready") is not True:
        return "Set ENGRAM_HUB_ACCESS_TOKEN and run python engramd.py --doctor"
    if pending_conflicts:
        return 'list_sync_conflicts(status="pending_review")'
    if not local_device_id:
        return 'ensure_sync_device_identity(device_name="this-machine")'
    if peer_count == 0:
        return 'register_sync_peer(peer_identity_packet=packet, accept=True, approved_by="operator")'
    if rebuild_required:
        return "python engramd.py --doctor"
    return "inspect_sync_state()"


def _snapshot_manifest_section(ledger: Any, limit: int) -> dict[str, Any]:
    section = _records_section(ledger, "snapshots", limit)
    section["semantics"] = snapshot_manifest_semantics(record_type="snapshot_manifest_section")
    return section


def _section_from_records(section_id: str, records: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    return {
        "table": section_id,
        "count": len(records),
        "items": _latest(records, limit),
        "write_performed": False,
    }


def _latest(records: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return list(reversed(records))[:limit]


def _redact_sensitive_sync_fields(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive_sync_key(key):
                redacted[key] = {"redacted": True, "reason": "sync_secret_field"}
            else:
                redacted[key] = _redact_sensitive_sync_fields(item)
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive_sync_fields(item) for item in value]
    return value


def _is_sensitive_sync_key(key: Any) -> bool:
    text = str(key or "").lower()
    return any(fragment in text for fragment in SENSITIVE_SYNC_FIELD_FRAGMENTS)


def _review_queue_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if _is_review_queue_record(record)]


def _is_review_queue_record(record: dict[str, Any]) -> bool:
    record_type = str(record.get("record_type") or record.get("type") or "").strip()
    status_values = {
        str(record.get(name) or "").strip().lower()
        for name in ("status", "review_status", "review_state", "promotion_status")
        if record.get(name)
    }
    if record_type in REVIEW_RECORD_TYPES:
        return True
    if record_type.endswith("_draft"):
        return True
    if status_values & REVIEW_STATUSES:
        return True
    return bool(
        record.get("promotion_required")
        or record.get("proposed_memories")
        or record.get("candidate_graph_edges")
    )


def _is_document_artifact_transaction(record: dict[str, Any]) -> bool:
    operation_kind = str(record.get("operation_kind") or "").strip()
    artifact_family = str(record.get("artifact_family") or "").strip()
    record_type = str(record.get("record_type") or "").strip()
    return (
        operation_kind == "document_artifact_store"
        or artifact_family == "document_evidence"
        or record_type == "document_artifact_transaction"
    )


def _is_document_promotion_transaction(record: dict[str, Any]) -> bool:
    operation_kind = str(record.get("operation_kind") or "").strip()
    record_type = str(record.get("record_type") or "").strip()
    return (
        record_type == "document_promotion_transaction"
        or operation_kind in {"prepare_document_promotion_transaction", "apply_document_promotion_transaction"}
        or operation_kind == "apply_document_promotion"
    )


def _graph_evidence_section(records: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    edges = _latest(records, limit)
    support_count = sum(1 for record in records if record.get("edge_type") == "supports")
    contradiction_count = sum(1 for record in records if record.get("edge_type") == "contradicts")
    return {
        "edge_count": len(records),
        "support_count": support_count,
        "contradiction_count": contradiction_count,
        "items": edges,
        "write_performed": False,
    }


def _ekc_eval_summary() -> dict[str, Any]:
    try:
        from core.memory_os.knowledge_eval import DEFAULT_WORKFLOW_SCENARIOS
    except Exception as exc:  # pragma: no cover - defensive inspector fallback
        return {
            "scenario_count": 0,
            "workflow_ids": [],
            "task_types": [],
            "status": "unavailable",
            "error": {"code": "runtime_error", "message": str(exc)},
            "write_performed": False,
        }

    workflow_ids = [str(scenario.get("scenario_id") or "") for scenario in DEFAULT_WORKFLOW_SCENARIOS]
    task_types = [str(scenario.get("task_type") or "") for scenario in DEFAULT_WORKFLOW_SCENARIOS]
    return {
        "scenario_count": len(DEFAULT_WORKFLOW_SCENARIOS),
        "workflow_ids": workflow_ids,
        "task_types": task_types,
        "status": "available",
        "write_performed": False,
    }


def _release_gate_commands_section() -> dict[str, Any]:
    return {
        "count": len(RELEASE_GATE_COMMANDS),
        "items": list(RELEASE_GATE_COMMANDS),
        "write_performed": False,
    }
