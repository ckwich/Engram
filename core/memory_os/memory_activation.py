"""Deterministic activation scoring for Memory OS retrieval results."""
from __future__ import annotations

from typing import Any

from core.memory_os._records import hash_payload, now_iso, stable_id, upsert_record
from core.memory_os.ledger import MemoryOSLedger

ACTIVATION_SCHEMA_VERSION = "2026-05-26.memory-activation.v1"

_HIGH_VALUE_MEMORY_TYPES = {"decision", "procedure", "project_state"}
_POSITIVE_TRUST_STATES = {"reviewed", "source_backed"}
_NEGATIVE_TRUST_STATES = {"conflicted", "quarantined"}
_SAFE_REASON_CODES = {
    "budget",
    "duplicate",
    "lifecycle_filter",
    "low_activation_score",
    "policy",
    "project_filter",
}


def score_activation(
    memory: dict[str, Any],
    query_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return an auditable rank-only activation score for one candidate memory."""
    context = dict(query_context or {})
    signals: list[str] = ["base"]
    score = 0.35

    if bool(memory.get("canonical")):
        score += 0.15
        signals.append("canonical")

    trust_state = _normalize_token(memory.get("trust_state"))
    if trust_state in _POSITIVE_TRUST_STATES:
        score += 0.15
        signals.append(f"trust_state:{trust_state}")
    if trust_state in _NEGATIVE_TRUST_STATES:
        score -= 0.30
        signals.append(f"{trust_state}_trust_penalty")

    if _project_matches(memory.get("project"), context.get("project")):
        score += 0.15
        signals.append("project_match")

    memory_type = _normalize_token(memory.get("memory_type"))
    if memory_type in _HIGH_VALUE_MEMORY_TYPES:
        score += 0.10
        signals.append(f"memory_type:{memory_type}")

    if trust_state == "superseded" or _normalize_token(memory.get("status")) == "superseded":
        score -= 0.20
        signals.append("superseded_penalty")

    return {
        "schema_version": ACTIVATION_SCHEMA_VERSION,
        "activation_score": round(_clamp(score), 4),
        "action": "rank",
        "signals": signals,
    }


def store_activation_receipt(
    ledger: MemoryOSLedger,
    *,
    query_context: dict[str, Any],
    selected_refs: list[dict[str, Any]],
    omitted_refs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Persist a compact activation receipt without raw query text or memory bodies."""
    sanitized_context = _sanitize_query_context(query_context)
    query_hash = hash_payload(str((query_context or {}).get("query") or ""))
    selected = [_sanitize_ref(ref) for ref in selected_refs]
    omitted = [_sanitize_ref(ref) for ref in omitted_refs or []]
    receipt = {
        "receipt_id": stable_id(
            "activation",
            {
                "schema_version": ACTIVATION_SCHEMA_VERSION,
                "query_hash": query_hash,
                "query_context": sanitized_context,
                "selected_refs": selected,
                "omitted_refs": omitted,
            },
        ),
        "schema_version": ACTIVATION_SCHEMA_VERSION,
        "query_hash": query_hash,
        "query_context_hash": hash_payload(sanitized_context),
        "selected_refs": selected,
        "omitted_refs": omitted,
        "created_at": now_iso(),
        "write_performed": True,
    }
    upsert_record(ledger, "activation_receipts", receipt["receipt_id"], receipt)
    return receipt


def _sanitize_query_context(query_context: dict[str, Any]) -> dict[str, Any]:
    context = dict(query_context or {})
    sanitized: dict[str, Any] = {}
    for field in ("project", "domain", "retrieval_mode", "surface", "task_type"):
        value = context.get(field)
        if value is not None:
            sanitized[field] = value
    return sanitized


def _sanitize_ref(ref: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for field in (
        "kind",
        "key",
        "chunk_id",
        "document_id",
        "source_id",
        "activation_score",
        "action",
    ):
        value = ref.get(field)
        if value is not None:
            sanitized[field] = value
    reason = _safe_reason(ref.get("reason"))
    if reason:
        sanitized.update(reason)
    activation = ref.get("activation")
    if isinstance(activation, dict):
        if activation.get("activation_score") is not None:
            sanitized["activation_score"] = activation.get("activation_score")
        if activation.get("action") is not None:
            sanitized["action"] = activation.get("action")
    return sanitized


def _safe_reason(value: Any) -> dict[str, str]:
    text = str(value or "").strip()
    if not text:
        return {}
    normalized = _normalize_token(text)
    if normalized in _SAFE_REASON_CODES:
        return {"reason": normalized}
    return {
        "reason": "free_form_reason_redacted",
        "reason_hash": hash_payload(text),
    }


def _project_matches(memory_project: Any, query_project: Any) -> bool:
    memory_value = _normalize_project(memory_project)
    query_values = _normalize_projects(query_project)
    return bool(memory_value and memory_value in query_values)


def _normalize_projects(value: Any) -> set[str]:
    if isinstance(value, (list, tuple, set)):
        return {
            normalized
            for item in value
            if (normalized := _normalize_project(item))
        }
    normalized = _normalize_project(value)
    return {normalized} if normalized else set()


def _normalize_project(value: Any) -> str:
    return str(value or "").strip().replace("\\", "/").rstrip("/").lower()


def _normalize_token(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
