"""Engram Knowledge Contract v0 helpers."""
from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

from core.memory_os.knowledge_citations import validate_knowledge_citation
from core.memory_os.knowledge_planner import (
    normalize_planner_receipt,
    validate_planner_receipt,
)


REQUEST_SCHEMA_VERSION = "engram.knowledge.request.v0"
RESPONSE_SCHEMA_VERSION = "engram.knowledge.response.v0"
SUPPORTED_TASK_TYPES = {
    "project_orientation",
    "source_orientation",
    "document_orientation",
    "review_preparation",
}
SUPPORTED_RESPONSE_TYPES = {
    "project_capsule_summary",
    "source_orientation_summary",
    "document_orientation_summary",
    "review_preparation_packet",
}
STATUSES = (
    "ok",
    "partial",
    "no_answer",
    "stale_artifact",
    "policy_denied",
    "budget_exceeded",
    "schema_failed",
    "unavailable",
)

DEFAULT_SHAPES = {
    "project_orientation": {"response_type": "project_capsule_summary", "format": "json"},
    "source_orientation": {"response_type": "source_orientation_summary", "format": "json"},
    "document_orientation": {"response_type": "document_orientation_summary", "format": "json"},
    "review_preparation": {"response_type": "review_preparation_packet", "format": "json"},
}
DEFAULT_SCOPE = {
    "review_state": ["reviewed", "accepted"],
    "source_kinds": ["note", "document", "decision", "conversation", "code"],
    "time_range": {"from": None, "to": None},
}
DEFAULT_POLICY = {
    "allow_unreviewed_sources": False,
    "inference_policy": {
        "allow_marked_inferences": False,
        "allow_unsupported_inferences": False,
        "on_required_inference": "return_partial",
    },
    "write_behavior": "read_only",
}
DEFAULT_POLICY_METADATA = {
    "unreviewed_sources_used": False,
    "unsupported_inferences_used": False,
    "review_state_available": False,
    "review_filter_enforced": False,
    "review_state_basis": "not_available_in_current_memory_os_records",
    "review_filter_requested": ["reviewed", "accepted"],
}
DEFAULT_GROUNDING = {
    "required": True,
    "citation_level": "artifact",
    "on_missing_grounding": "return_partial",
}
DEFAULT_FRESHNESS = {
    "max_artifact_age": "P14D",
    "on_stale": "return_stale_warning",
}
DEFAULT_BUDGET = {
    "depth": "standard",
    "max_artifacts": 1,
    "max_source_reads": 12,
    "max_tokens_out": 2500,
}


def normalize_knowledge_request(raw: dict[str, Any]) -> dict[str, Any]:
    request_id = str(raw.get("request_id") or uuid4())
    if raw.get("contract_version") not in (None, REQUEST_SCHEMA_VERSION):
        return schema_failed_response(
            request_id=request_id,
            code="unsupported_contract_version",
            message=f"Unsupported EKC contract version: {raw.get('contract_version')}",
        )

    ask = dict(raw.get("ask") or {})
    project = str(ask.get("project") or "").strip()
    if not project:
        return schema_failed_response(
            request_id=request_id,
            code="missing_project",
            message="ask.project is required",
        )

    task_type = str(ask.get("task_type") or "project_orientation").strip()
    if task_type not in SUPPORTED_TASK_TYPES:
        return schema_failed_response(
            request_id=request_id,
            code="unsupported_task_type",
            message=f"Unsupported task type: {task_type}",
        )

    shape = _merge(DEFAULT_SHAPES[task_type], raw.get("shape"))
    if shape["response_type"] not in SUPPORTED_RESPONSE_TYPES:
        return schema_failed_response(
            request_id=request_id,
            code="unsupported_response_type",
            message=f"Unsupported response type: {shape['response_type']}",
        )

    policy = _merge(DEFAULT_POLICY, raw.get("policy"))
    unsafe_policy = _unsafe_policy_error(policy)
    if unsafe_policy is not None:
        return policy_denied_response(
            request_id=request_id,
            code=unsafe_policy["code"],
            message=unsafe_policy["message"],
        )

    budget = _merge(DEFAULT_BUDGET, raw.get("budget"))
    if int(budget.get("max_artifacts", 0)) < 1:
        return _empty_response(
            request_id=request_id,
            status="budget_exceeded",
            errors=[
                {
                    "code": "max_artifacts_too_low",
                    "message": "budget.max_artifacts must be at least 1 for EKC v0.",
                }
            ],
        )

    return {
        "contract_version": REQUEST_SCHEMA_VERSION,
        "request_id": request_id,
        "ask": {
            "goal": str(ask.get("goal") or "").strip(),
            "task_type": task_type,
            "project": project,
            "focus": _string_list(ask.get("focus")),
        },
        "shape": shape,
        "scope": _merge(DEFAULT_SCOPE, raw.get("scope")),
        "policy": policy,
        "grounding": _merge(DEFAULT_GROUNDING, raw.get("grounding")),
        "freshness": _merge(DEFAULT_FRESHNESS, raw.get("freshness")),
        "budget": budget,
    }


def schema_failed_response(*, request_id: str, code: str, message: str) -> dict[str, Any]:
    return _empty_response(
        request_id=request_id,
        status="schema_failed",
        errors=[{"code": code, "message": message}],
    )


def policy_denied_response(*, request_id: str, code: str, message: str) -> dict[str, Any]:
    return _empty_response(
        request_id=request_id,
        status="policy_denied",
        errors=[{"code": code, "category": "policy", "message": message}],
    )


def unavailable_response(*, request_id: str, code: str, message: str) -> dict[str, Any]:
    return _empty_response(
        request_id=request_id,
        status="unavailable",
        errors=[{"code": code, "category": "infrastructure", "message": message}],
    )


def ok_response(
    *,
    request_id: str,
    answer: dict[str, Any],
    citations: list[dict[str, Any]],
    freshness: dict[str, Any],
    budget_used: dict[str, Any],
    planner: dict[str, Any],
    partial: bool = False,
    errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    status = "partial" if partial else "ok"
    response_errors = list(errors or [])
    return {
        "contract_version": RESPONSE_SCHEMA_VERSION,
        "request_id": request_id,
        "status": status,
        "answer": answer,
        "citations": citations,
        "freshness": freshness,
        "policy": _policy_metadata(),
        "budget_used": budget_used,
        "planner": normalize_planner_receipt(
            planner,
            budget_used=budget_used,
            failures=response_errors,
            response_status=status,
        ),
        "errors": response_errors,
    }


def no_answer_response(
    *,
    request_id: str,
    code: str,
    message: str,
    planner: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = _empty_response(
        request_id=request_id,
        status="no_answer",
        errors=[{"code": code, "message": message}],
    )
    if planner is not None:
        response["planner"] = normalize_planner_receipt(
            planner,
            budget_used=response["budget_used"],
            failures=response["errors"],
            response_status="no_answer",
        )
    return response


def _empty_response(
    *,
    request_id: str,
    status: str,
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    budget_used = {
        "artifacts_built": 0,
        "artifacts_read": 0,
        "source_reads": 0,
        "tokens_out_estimate": 0,
    }
    return {
        "contract_version": RESPONSE_SCHEMA_VERSION,
        "request_id": request_id,
        "status": status,
        "answer": None,
        "citations": [],
        "freshness": {"state": "unknown"},
        "policy": _policy_metadata(),
        "budget_used": budget_used,
        "planner": normalize_planner_receipt(
            {"strategy": "none", "methods_used": [], "omissions": []},
            budget_used=budget_used,
            failures=errors,
            response_status=status,
        ),
        "errors": errors,
    }


def validate_knowledge_response(response: dict[str, Any]) -> dict[str, Any]:
    required = {
        "contract_version",
        "request_id",
        "status",
        "answer",
        "citations",
        "freshness",
        "policy",
        "budget_used",
        "planner",
        "errors",
    }
    missing = sorted(field for field in required if field not in response)
    errors: list[str] = []
    if response.get("contract_version") != RESPONSE_SCHEMA_VERSION:
        errors.append("unsupported_response_version")
    if response.get("status") not in STATUSES:
        errors.append("unsupported_status")
    if response.get("status") in {"ok", "partial"} and not response.get("citations"):
        errors.append("missing_success_citations")
    for index, citation in enumerate(response.get("citations") or []):
        for citation_error in validate_knowledge_citation(citation):
            errors.append(f"invalid_citation_{index}_{citation_error}")
    for field in ("artifacts_built", "artifacts_read", "source_reads", "tokens_out_estimate"):
        if field not in (response.get("budget_used") or {}):
            errors.append(f"missing_budget_{field}")
    for field in (
        "unreviewed_sources_used",
        "unsupported_inferences_used",
        "review_state_available",
        "review_filter_enforced",
        "review_state_basis",
    ):
        if field not in (response.get("policy") or {}):
            errors.append(f"missing_policy_{field}")
    for planner_error in validate_planner_receipt(
        response.get("planner") or {},
        response_status=response.get("status"),
    ):
        errors.append(f"invalid_planner_{planner_error}")
    if response.get("status") == "unavailable":
        categories = {
            error.get("category")
            for error in response.get("errors", [])
            if isinstance(error, dict)
        }
        if "infrastructure" not in categories:
            errors.append("missing_infrastructure_error_category")
    return {"valid": not missing and not errors, "missing_fields": missing, "errors": errors}


def _policy_metadata() -> dict[str, Any]:
    return deepcopy(DEFAULT_POLICY_METADATA)


def _unsafe_policy_error(policy: dict[str, Any]) -> dict[str, str] | None:
    if policy.get("allow_unreviewed_sources") is True:
        return {
            "code": "unreviewed_sources_not_allowed",
            "message": "EKC v0 does not allow unreviewed sources.",
        }
    inference = policy.get("inference_policy") or {}
    if inference.get("allow_unsupported_inferences") is True:
        return {
            "code": "unsupported_inferences_not_allowed",
            "message": "EKC v0 does not allow unsupported inferences.",
        }
    if policy.get("write_behavior") != "read_only":
        return {
            "code": "write_behavior_not_allowed",
            "message": "EKC v0 query_knowledge is read-only.",
        }
    return None


def _merge(defaults: dict[str, Any], override: Any) -> dict[str, Any]:
    result = deepcopy(defaults)
    if not isinstance(override, dict):
        return result
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


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
