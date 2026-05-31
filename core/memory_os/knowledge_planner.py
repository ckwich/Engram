"""Accountable planner receipts for Engram Knowledge Contract responses."""
from __future__ import annotations

from typing import Any


RECOVERABLE_STATUSES = {"partial", "no_answer", "stale_artifact", "budget_exceeded", "unavailable"}


def build_planner_receipt(
    *,
    strategy: str,
    methods_used: list[str] | None = None,
    request_budget: dict[str, Any] | None = None,
    budget_used: dict[str, Any] | None = None,
    omissions: list[Any] | None = None,
    failures: list[Any] | None = None,
    response_status: str = "ok",
) -> dict[str, Any]:
    """Build the stable EKC planner receipt envelope."""
    return {
        "strategy": str(strategy or "none").strip() or "none",
        "methods_used": _string_list(methods_used),
        "omissions": _omission_receipts(omissions),
        "budget": {
            "requested": _budget_request_receipt(request_budget),
            "used": _budget_used_receipt(budget_used),
        },
        "failure_receipts": _failure_receipts(failures, response_status=response_status),
        "response_status": str(response_status or "ok").strip() or "ok",
    }


def normalize_planner_receipt(
    planner: dict[str, Any] | None,
    *,
    request_budget: dict[str, Any] | None = None,
    budget_used: dict[str, Any] | None = None,
    failures: list[Any] | None = None,
    response_status: str | None = None,
) -> dict[str, Any]:
    """Normalize older planner payloads into the accountable receipt shape."""
    raw = planner if isinstance(planner, dict) else {}
    budget = raw.get("budget") if isinstance(raw.get("budget"), dict) else {}
    requested = (
        request_budget
        if request_budget is not None
        else raw.get("budget_requested")
        or budget.get("requested")
    )
    used = (
        budget_used
        if budget_used is not None
        else raw.get("budget_used")
        or budget.get("used")
    )
    failure_source = failures if failures is not None else raw.get("failure_receipts")
    return build_planner_receipt(
        strategy=str(raw.get("strategy") or "none"),
        methods_used=_string_list(raw.get("methods_used")),
        request_budget=requested if isinstance(requested, dict) else None,
        budget_used=used if isinstance(used, dict) else None,
        omissions=list(raw.get("omissions") or []) if isinstance(raw.get("omissions"), list) else [],
        failures=list(failure_source or []) if isinstance(failure_source, list) else [],
        response_status=str(response_status or raw.get("response_status") or "ok"),
    )


def validate_planner_receipt(
    planner: dict[str, Any],
    *,
    response_status: str | None = None,
) -> list[str]:
    """Return stable validation error codes for one EKC planner receipt."""
    if not isinstance(planner, dict):
        return ["not_object"]
    errors: list[str] = []
    for field in ("strategy", "methods_used", "omissions", "budget", "failure_receipts", "response_status"):
        if field not in planner:
            errors.append(f"missing_{field}")
    if "strategy" in planner and not str(planner.get("strategy") or "").strip():
        errors.append("missing_strategy")
    if "methods_used" in planner and not isinstance(planner.get("methods_used"), list):
        errors.append("invalid_methods_used")
    if "omissions" in planner and not isinstance(planner.get("omissions"), list):
        errors.append("invalid_omissions")
    budget = planner.get("budget")
    if isinstance(budget, dict):
        if "requested" not in budget:
            errors.append("missing_budget_requested")
        if "used" not in budget:
            errors.append("missing_budget_used")
    elif "budget" in planner:
        errors.append("invalid_budget")
    failures = planner.get("failure_receipts")
    if "failure_receipts" in planner and not isinstance(failures, list):
        errors.append("invalid_failure_receipts")
        failures = []
    status = str(response_status or planner.get("response_status") or "ok")
    if status != "ok" and not failures:
        errors.append("missing_failure_receipts")
    for index, failure in enumerate(failures or []):
        if not isinstance(failure, dict):
            errors.append(f"invalid_failure_{index}_not_object")
            continue
        for field in ("code", "category", "message", "recoverable"):
            if field not in failure:
                errors.append(f"invalid_failure_{index}_missing_{field}")
    return errors


def _omission_receipts(omissions: list[Any] | None) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for omission in omissions or []:
        if isinstance(omission, dict):
            receipts.append(
                {
                    "code": str(omission.get("code") or "omitted").strip() or "omitted",
                    "message": str(omission.get("message") or omission.get("ref") or "").strip(),
                }
            )
        else:
            receipts.append({"code": "omitted", "message": str(omission).strip()})
    return [receipt for receipt in receipts if receipt["message"]]


def _failure_receipts(
    failures: list[Any] | None,
    *,
    response_status: str,
) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for failure in failures or []:
        if isinstance(failure, dict):
            code = str(failure.get("code") or "failure").strip() or "failure"
            message = str(failure.get("message") or code).strip()
            category = str(failure.get("category") or _failure_category(response_status)).strip()
            recoverable = failure.get("recoverable")
        else:
            code = "failure"
            message = str(failure).strip()
            category = _failure_category(response_status)
            recoverable = None
        receipts.append(
            {
                "code": code,
                "category": category,
                "message": message,
                "recoverable": bool(recoverable)
                if recoverable is not None
                else response_status in RECOVERABLE_STATUSES,
            }
        )
    return [receipt for receipt in receipts if receipt["message"]]


def _failure_category(response_status: str) -> str:
    if response_status == "unavailable":
        return "infrastructure"
    if response_status == "policy_denied":
        return "policy"
    if response_status == "budget_exceeded":
        return "budget"
    if response_status == "schema_failed":
        return "schema"
    return "grounding"


def _budget_request_receipt(budget: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(budget, dict):
        return {}
    return {
        key: budget[key]
        for key in ("depth", "max_artifacts", "max_source_reads", "max_tokens_out")
        if key in budget
    }


def _budget_used_receipt(budget: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(budget, dict):
        return {}
    return {
        key: budget[key]
        for key in ("artifacts_built", "artifacts_read", "source_reads", "tokens_out_estimate")
        if key in budget
    }


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    raw_items = value if isinstance(value, list) else [value]
    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            normalized.append(text)
    return normalized
