from __future__ import annotations

from enum import Enum
from typing import Any


class WritePolicy(str, Enum):
    READ_ONLY = "read_only"
    PREVIEW_ONLY = "preview_only"
    DRAFT_ONLY = "draft_only"
    PROMOTION_REQUIRED = "promotion_required"
    ALLOW_DURABLE_WRITE = "allow_durable_write"
    DESTRUCTIVE = "destructive"


NO_ACTIVE_WRITE_POLICIES = {
    WritePolicy.READ_ONLY,
    WritePolicy.PREVIEW_ONLY,
    WritePolicy.DRAFT_ONLY,
    WritePolicy.PROMOTION_REQUIRED,
}


def write_policy_metadata(
    policy: WritePolicy | str,
    *,
    write_performed: bool = False,
    active_memory_write_performed: bool = False,
    promotion_required: bool | None = None,
) -> dict[str, Any]:
    normalized = normalize_write_policy(policy)
    metadata = {
        "write_policy": normalized.value,
        "write_performed": bool(write_performed),
        "active_memory_write_performed": bool(active_memory_write_performed),
    }
    if promotion_required is not None:
        metadata["promotion_required"] = bool(promotion_required)
    return metadata


def validate_write_policy_metadata(payload: dict[str, Any], *, operation: str = "payload") -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    policy = _optional_policy(payload.get("write_policy"))
    if policy is None:
        policy = _infer_policy(payload)
    if "write_performed" not in payload:
        errors.append(_error("missing_write_performed", operation, "write_performed is required."))
    if "active_memory_write_performed" not in payload:
        errors.append(
            _error(
                "missing_active_memory_write_performed",
                operation,
                "active_memory_write_performed is required.",
            )
        )
    write_performed = bool(payload.get("write_performed"))
    active_write = bool(payload.get("active_memory_write_performed"))
    if policy in NO_ACTIVE_WRITE_POLICIES and write_performed:
        errors.append(_error("unexpected_write", operation, f"{policy.value} must not perform writes."))
    if policy in NO_ACTIVE_WRITE_POLICIES and active_write:
        errors.append(
            _error("unexpected_active_memory_write", operation, f"{policy.value} must not write active memory.")
        )
    if policy is WritePolicy.ALLOW_DURABLE_WRITE and not write_performed:
        errors.append(_error("missing_durable_write", operation, "allow_durable_write must report write_performed."))
    if policy is WritePolicy.ALLOW_DURABLE_WRITE and not active_write:
        errors.append(
            _error(
                "missing_active_memory_write",
                operation,
                "allow_durable_write must report active_memory_write_performed.",
            )
        )
    if policy is WritePolicy.DESTRUCTIVE and not write_performed:
        errors.append(_error("missing_destructive_write", operation, "destructive operations must report a write."))
    return {
        "valid": not errors,
        "operation": operation,
        "write_policy": policy.value,
        "errors": errors,
    }


def assert_write_policy_metadata(payload: dict[str, Any], *, operation: str = "payload") -> None:
    result = validate_write_policy_metadata(payload, operation=operation)
    if result["valid"]:
        return
    details = "; ".join(f"{error['code']}: {error['message']}" for error in result["errors"])
    raise AssertionError(f"{operation} write policy contract failed: {details}")


def normalize_write_policy(policy: WritePolicy | str) -> WritePolicy:
    if isinstance(policy, WritePolicy):
        return policy
    normalized = str(policy or "").strip()
    for candidate in WritePolicy:
        if candidate.value == normalized:
            return candidate
    raise ValueError(f"unknown write policy: {policy}")


def _optional_policy(value: Any) -> WritePolicy | None:
    if value is None:
        return None
    return normalize_write_policy(str(value))


def _infer_policy(payload: dict[str, Any]) -> WritePolicy:
    if payload.get("promotion_required") is True:
        return WritePolicy.PROMOTION_REQUIRED
    if payload.get("write_performed") is True and payload.get("active_memory_write_performed") is True:
        return WritePolicy.ALLOW_DURABLE_WRITE
    return WritePolicy.PREVIEW_ONLY


def _error(code: str, operation: str, message: str) -> dict[str, str]:
    return {"code": code, "operation": operation, "message": message}
