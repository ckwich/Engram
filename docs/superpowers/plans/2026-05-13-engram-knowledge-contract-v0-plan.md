# Engram Knowledge Contract v0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a narrow Engram Knowledge Contract v0 path that lets agents request typed, cited project orientation through a deterministic project capsule response.

**Architecture:** EKC v0 is an MCP-facing contract over the existing daemon-owned Memory OS. It reuses the SQLite ledger, Memory OS retrieval, project capsule concepts, and thin daemon-client entrypoint; it does not add Pinecone, KnowQL compatibility, autonomous compilers, or automatic memory writes.

**Tech Stack:** Python 3.10+, FastMCP, `engramd`, `core.memory_os`, SQLite ledger records, LanceDB-backed Memory OS search, pytest, existing reliability/eval harness patterns.

---

## File Map

- Create `core/memory_os/knowledge_contract.py`: EKC v0 constants, request normalization, unsafe-policy rejection, response-envelope validation, status helpers, and response builders.
- Create `core/memory_os/project_capsule_artifact.py`: deterministic read-only adapter that wraps and normalizes existing project capsule behavior; it must not become a second long-term project capsule semantics path.
- Create `core/memory_os/knowledge_eval.py`: search-only versus EKC project-orientation comparison harness that models realistic multi-call orientation workflows.
- Modify `core/memory_os/runtime.py`: add `query_knowledge()` and wire capsule artifact generation.
- Modify `core/engramd_api.py`: add `/v1/query_knowledge` daemon route.
- Modify `core/engramd_client.py`: add `query_knowledge()` client helper.
- Modify `server_daemon_client.py`: expose `query_knowledge` MCP tool through the thin daemon client and advertise it in `memory_protocol()`.
- Modify `server.py`: advertise EKC v0 in the full `memory_protocol()` manifest and expose a read-only daemon-first `query_knowledge` wrapper.
- Modify `plan.md`: add EKC v0 as a tracked local product enhancement without redefining the Memory OS 1.0 scope.
- Create `tests/memory_os/test_knowledge_contract.py`: contract validation and response helper tests.
- Create `tests/memory_os/test_project_capsule_artifact.py`: deterministic artifact builder tests.
- Modify `tests/memory_os/test_runtime.py`: runtime `query_knowledge()` behavior tests.
- Modify `tests/test_engramd_api.py`: daemon route tests.
- Modify `tests/test_engramd_client.py`: client route tests.
- Modify `tests/test_server_daemon_client_entrypoint.py`: thin MCP delegation tests.
- Modify `tests/test_server_daemon_client.py`: full `server.py` daemon-routing tests.
- Modify `tests/test_agent_protocol_tools.py`: memory protocol advertisement tests.
- Create `tests/memory_os/test_knowledge_eval.py`: minimal EKC eval harness tests.
- Create `tests/fixtures/knowledge_contract/*.json`: golden EKC response fixtures for every v0 status.

## Product Guardrails

- Keep the first slice to one tool, one artifact, one eval.
- Default unsupported inference to forbidden.
- Return typed failures instead of broad fallback search.
- Do not write durable memories from `query_knowledge`.
- Do not make graph traversal required for v0.
- Do not add remote provider calls.
- Do not expose policy-denied content in diagnostics.
- Enforce safe v0 policy. Requests that try `allow_unreviewed_sources=true`,
  `allow_unsupported_inferences=true`, or any `write_behavior` other than
  `read_only` must return `policy_denied` or be clamped with explicit policy
  metadata; this plan chooses `policy_denied` so unsafe overrides are visible.
- Do not claim reviewed-only context unless a real reviewed/accepted filter is
  enforced against current records. If Memory OS records do not expose a true
  review state, response policy metadata must say that review state is
  unavailable and that reviewed-only filtering was not enforced.
- Count ephemeral v0 capsule construction as `artifacts_built=1` and
  `artifacts_read=0`. Reserve `artifacts_read=1` for v0.2 persisted or ledgered
  capsules.
- Infrastructure failures are not `no_answer`. Daemon/runtime failures must
  return `status="unavailable"` with `error.category="infrastructure"` or the
  equivalent error object in `errors`.
- `validate_knowledge_response()` is mandatory. It must validate the required
  EKC envelope for both success and failure responses, backed by golden fixtures
  for `ok`, `partial`, `no_answer`, `policy_denied`, `budget_exceeded`,
  `schema_failed`, and `unavailable`/`runtime_error`.

## Task 1: EKC v0 Contract Module

**Files:**
- Create: `core/memory_os/knowledge_contract.py`
- Test: `tests/memory_os/test_knowledge_contract.py`
- Test fixtures: `tests/fixtures/knowledge_contract/{ok,partial,no_answer,policy_denied,budget_exceeded,schema_failed,unavailable_runtime_error}.json`

- [ ] **Step 1: Write failing contract tests**

Create `tests/memory_os/test_knowledge_contract.py`:

```python
from core.memory_os.knowledge_contract import (
    REQUEST_SCHEMA_VERSION,
    RESPONSE_SCHEMA_VERSION,
    normalize_knowledge_request,
    policy_denied_response,
    schema_failed_response,
    unavailable_response,
    validate_knowledge_response,
)


def test_normalize_knowledge_request_defaults_to_safe_project_capsule_contract():
    request = normalize_knowledge_request(
        {
            "ask": {
                "goal": "Get current project context.",
                "task_type": "project_orientation",
                "project": "Engram",
                "focus": ["Memory OS"],
            }
        }
    )

    assert request["contract_version"] == REQUEST_SCHEMA_VERSION
    assert request["ask"]["project"] == "Engram"
    assert request["shape"]["response_type"] == "project_capsule_summary"
    assert request["shape"]["format"] == "json"
    assert request["policy"]["allow_unreviewed_sources"] is False
    assert request["policy"]["write_behavior"] == "read_only"
    assert request["policy"]["inference_policy"] == {
        "allow_marked_inferences": False,
        "allow_unsupported_inferences": False,
        "on_required_inference": "return_partial",
    }
    assert request["grounding"]["citation_level"] == "artifact"
    assert request["budget"]["max_artifacts"] == 1


def test_normalize_knowledge_request_rejects_unsafe_policy_overrides():
    for unsafe_policy, expected_code in (
        ({"allow_unreviewed_sources": True}, "unreviewed_sources_not_allowed"),
        (
            {"inference_policy": {"allow_unsupported_inferences": True}},
            "unsupported_inferences_not_allowed",
        ),
        ({"write_behavior": "write_memory"}, "write_behavior_not_allowed"),
    ):
        response = normalize_knowledge_request(
            {
                "request_id": f"req-{expected_code}",
                "ask": {
                    "goal": "Get current project context.",
                    "task_type": "project_orientation",
                    "project": "Engram",
                },
                "policy": unsafe_policy,
            }
        )

        assert response["status"] == "policy_denied"
        assert response["errors"][0]["code"] == expected_code
        assert response["policy"]["unreviewed_sources_used"] is False
        assert response["policy"]["unsupported_inferences_used"] is False


def test_normalize_knowledge_request_rejects_missing_project():
    response = normalize_knowledge_request(
        {
            "ask": {
                "goal": "Get context.",
                "task_type": "project_orientation",
            }
        }
    )

    assert response["status"] == "schema_failed"
    assert response["contract_version"] == RESPONSE_SCHEMA_VERSION
    assert response["errors"][0]["code"] == "missing_project"


def test_schema_failed_response_has_stable_shape():
    response = schema_failed_response(
        request_id="req-1",
        code="unsupported_task_type",
        message="Unsupported task type: broad_research",
    )

    assert response["request_id"] == "req-1"
    assert response["status"] == "schema_failed"
    assert response["answer"] is None
    assert response["citations"] == []
    assert response["policy"]["unsupported_inferences_used"] is False


def test_validate_knowledge_response_accepts_required_success_and_failure_envelopes():
    ok = {
        "contract_version": RESPONSE_SCHEMA_VERSION,
        "request_id": "req-ok",
        "status": "ok",
        "answer": {"project": "Engram"},
        "citations": [{"citation_id": "cit_001"}],
        "freshness": {"state": "fresh"},
        "policy": {
            "unreviewed_sources_used": False,
            "unsupported_inferences_used": False,
            "review_state_available": False,
            "review_filter_enforced": False,
            "review_state_basis": "not_available_in_current_memory_os_records",
        },
        "budget_used": {
            "artifacts_built": 1,
            "artifacts_read": 0,
            "source_reads": 1,
            "tokens_out_estimate": 10,
        },
        "planner": {"strategy": "project_capsule", "methods_used": ["artifact"], "omissions": []},
        "errors": [],
    }
    unavailable = unavailable_response(
        request_id="req-down",
        code="runtime_error",
        message="daemon unavailable",
    )

    assert validate_knowledge_response(ok)["valid"] is True
    assert validate_knowledge_response(unavailable)["valid"] is True


def test_validate_knowledge_response_rejects_missing_envelope_fields():
    invalid = {"status": "ok", "answer": {"project": "Engram"}}

    result = validate_knowledge_response(invalid)

    assert result["valid"] is False
    assert "contract_version" in result["missing_fields"]
```

Also create golden fixtures under `tests/fixtures/knowledge_contract/` for:

- `ok.json`
- `partial.json`
- `no_answer.json`
- `policy_denied.json`
- `budget_exceeded.json`
- `schema_failed.json`
- `unavailable_runtime_error.json`

Each fixture must include the complete EKC envelope:
`contract_version`, `request_id`, `status`, `answer`, `citations`,
`freshness`, `policy`, `budget_used`, `planner`, and `errors`. The
`unavailable_runtime_error.json` fixture must include
`errors[0].category == "infrastructure"`.

- [ ] **Step 2: Run the focused test and verify red**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_knowledge_contract.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'core.memory_os.knowledge_contract'`.

- [ ] **Step 3: Implement the contract module**

Create `core/memory_os/knowledge_contract.py`:

```python
"""Engram Knowledge Contract v0 helpers."""
from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

REQUEST_SCHEMA_VERSION = "engram.knowledge.request.v0"
RESPONSE_SCHEMA_VERSION = "engram.knowledge.response.v0"
SUPPORTED_TASK_TYPES = {"project_orientation"}
SUPPORTED_RESPONSE_TYPES = {"project_capsule_summary"}
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

DEFAULT_SHAPE = {"response_type": "project_capsule_summary", "format": "json"}
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

    shape = _merge(DEFAULT_SHAPE, raw.get("shape"))
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
    return {
        "contract_version": RESPONSE_SCHEMA_VERSION,
        "request_id": request_id,
        "status": "partial" if partial else "ok",
        "answer": answer,
        "citations": citations,
        "freshness": freshness,
        "policy": _policy_metadata(),
        "budget_used": budget_used,
        "planner": planner,
        "errors": list(errors or []),
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
        response["planner"] = planner
    return response


def _empty_response(
    *,
    request_id: str,
    status: str,
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "contract_version": RESPONSE_SCHEMA_VERSION,
        "request_id": request_id,
        "status": status,
        "answer": None,
        "citations": [],
        "freshness": {"state": "unknown"},
        "policy": _policy_metadata(),
        "budget_used": {
            "artifacts_built": 0,
            "artifacts_read": 0,
            "source_reads": 0,
            "tokens_out_estimate": 0,
        },
        "planner": {"strategy": "none", "methods_used": [], "omissions": []},
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
    if response.get("status") == "unavailable":
        categories = {error.get("category") for error in response.get("errors", []) if isinstance(error, dict)}
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
```

- [ ] **Step 4: Run the focused test and verify green**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_knowledge_contract.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit the contract module**

Run:

```powershell
git add core/memory_os/knowledge_contract.py tests/memory_os/test_knowledge_contract.py
git commit -m "feat: add Engram knowledge contract schema"
```

## Task 2: Project Capsule Artifact Adapter

**Files:**
- Create: `core/memory_os/project_capsule_artifact.py`
- Test: `tests/memory_os/test_project_capsule_artifact.py`

- [ ] **Step 1: Write failing adapter tests**

Create `tests/memory_os/test_project_capsule_artifact.py`:

```python
from core.memory_os.project_capsule_artifact import build_project_capsule_artifact


def test_project_capsule_artifact_wraps_existing_project_capsule_draft():
    context_packet = {
        "profile": {"id": "project_capsule"},
        "context": {
            "chunks": [
                {
                    "key": "engram_direction",
                    "chunk_id": 0,
                    "text": "# Summary\n\nEngram is a local-first Memory OS.",
                    "score": 0.91,
                },
                {
                    "key": "engram_constraints",
                    "chunk_id": 0,
                    "text": "# Constraints\n\nWrites must remain explicit and reviewed.",
                    "score": 0.84,
                },
            ],
            "citations": [
                {"key": "engram_direction", "chunk_id": 0, "source": "memory_os"},
                {"key": "engram_constraints", "chunk_id": 0, "source": "memory_os"},
            ],
        },
        "warnings": [],
    }

    artifact = build_project_capsule_artifact(
        project="Engram",
        goal="Get current project context.",
        focus=["Memory OS"],
        context_packet=context_packet,
        quality_payload={"summary": {}, "issue_count": 0},
        source_snapshot_id="memory_os:test",
    )

    assert artifact["artifact_type"] == "project_capsule"
    assert artifact["adapter_basis"] == "core.project_capsule.build_project_capsule_draft"
    assert artifact["project"] == "Engram"
    assert artifact["summary"] == "Engram is a local-first Memory OS."
    assert artifact["constraints"] == ["Writes must remain explicit and reviewed."]
    assert artifact["source_refs"] == [
        {
            "key": "engram_direction",
            "chunk_id": 0,
            "citation_id": "cit_001",
            "score": 0.91,
        },
        {
            "key": "engram_constraints",
            "chunk_id": 0,
            "citation_id": "cit_002",
            "score": 0.84,
        },
    ]
    assert artifact["citations"][0]["level"] == "chunk"
    assert artifact["draft"]["record_type"] == "project_capsule_draft"


def test_project_capsule_artifact_returns_partial_when_sources_are_empty():
    artifact = build_project_capsule_artifact(
        project="Engram",
        goal="Get current project context.",
        focus=[],
        context_packet={"context": {"chunks": [], "citations": []}},
        quality_payload={"summary": {}, "issue_count": 0},
        source_snapshot_id="memory_os:test",
    )

    assert artifact["staleness"]["state"] == "partial"
    assert artifact["summary"] == ""
    assert artifact["source_refs"] == []
```

- [ ] **Step 2: Run the focused test and verify red**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_project_capsule_artifact.py -q
```

Expected: fail with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the adapter**

Create `core/memory_os/project_capsule_artifact.py` as an adapter over
`core.project_capsule.build_project_capsule_draft`. The adapter may normalize
context chunks into the EKC response fields, but it must keep the existing
project capsule draft attached in `artifact["draft"]` and must not introduce a
second durable project capsule semantic model:

```python
"""EKC v0 adapter over existing no-write project capsule drafts."""
from __future__ import annotations

from typing import Any

from core.project_capsule import build_project_capsule_draft
from core.memory_os._records import now_iso

PROJECT_CAPSULE_ARTIFACT_VERSION = "v0"
ADAPTER_BASIS = "core.project_capsule.build_project_capsule_draft"


def build_project_capsule_artifact(
    *,
    project: str,
    goal: str,
    focus: list[str],
    context_packet: dict[str, Any],
    quality_payload: dict[str, Any],
    source_snapshot_id: str,
) -> dict[str, Any]:
    draft = build_project_capsule_draft(
        project=project,
        task=goal,
        summary=None,
        must_read_keys=None,
        context_packet=context_packet,
        quality_payload=quality_payload,
    )
    chunks = list((context_packet.get("context") or {}).get("chunks") or [])
    citations = []
    source_refs = []
    fields = {
        "summary": "",
        "current_goals": [],
        "active_decisions": [],
        "constraints": [],
        "open_questions": [],
        "important_entities": [],
        "recent_changes": [],
    }

    for index, chunk in enumerate(chunks, start=1):
        citation_id = f"cit_{index:03d}"
        key = str(chunk.get("key") or "")
        chunk_id = int(chunk.get("chunk_id", 0))
        text = str(chunk.get("text") or chunk.get("snippet") or "")
        citations.append(
            {
                "citation_id": citation_id,
                "level": "chunk",
                "key": key,
                "chunk_id": chunk_id,
                "source": "memory_os",
                "document_id": chunk.get("document_id"),
                "review_state": chunk.get("review_state"),
            }
        )
        source_refs.append(
            {
                "key": key,
                "chunk_id": chunk_id,
                "citation_id": citation_id,
                "score": float(chunk.get("score") or 0.0),
            }
        )
        _merge_text_into_fields(fields, text)

    return {
        "artifact_type": "project_capsule",
        "artifact_version": PROJECT_CAPSULE_ARTIFACT_VERSION,
        "adapter_basis": ADAPTER_BASIS,
        "project": project,
        "goal": goal,
        "focus": list(focus),
        "generated_at": now_iso(),
        "source_snapshot_id": source_snapshot_id,
        "source_refs": source_refs,
        "summary": fields["summary"],
        "current_goals": fields["current_goals"],
        "active_decisions": fields["active_decisions"],
        "constraints": fields["constraints"],
        "open_questions": fields["open_questions"],
        "important_entities": fields["important_entities"],
        "recent_changes": fields["recent_changes"],
        "citations": citations,
        "draft": draft,
        "staleness": {
            "state": "fresh" if source_refs else "partial",
            "invalidated_by": [],
        },
    }


def _merge_text_into_fields(fields: dict[str, Any], text: str) -> None:
    heading = ""
    body_lines = []
    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip().lower()
            continue
        if stripped:
            body_lines.append(stripped)
    body = " ".join(body_lines).strip()
    if not body:
        return
    if "constraint" in heading:
        _append_unique(fields["constraints"], body)
    elif "decision" in heading:
        _append_unique(fields["active_decisions"], body)
    elif "goal" in heading:
        _append_unique(fields["current_goals"], body)
    elif "question" in heading:
        _append_unique(fields["open_questions"], body)
    elif "entity" in heading or "concept" in heading:
        _append_unique(fields["important_entities"], body)
    elif "change" in heading:
        _append_unique(fields["recent_changes"], body)
    elif not fields["summary"]:
        fields["summary"] = body


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)
```

- [ ] **Step 4: Run artifact tests and verify green**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_project_capsule_artifact.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit the artifact adapter**

Run:

```powershell
git add core/memory_os/project_capsule_artifact.py tests/memory_os/test_project_capsule_artifact.py
git commit -m "feat: adapt project capsule drafts for knowledge contract"
```

## Task 3: Memory OS Runtime Query Path

**Files:**
- Modify: `core/memory_os/runtime.py`
- Test: `tests/memory_os/test_runtime.py`

- [ ] **Step 1: Add failing runtime tests**

Append to `tests/memory_os/test_runtime.py`:

```python
def test_memory_os_runtime_query_knowledge_returns_project_capsule_response(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()
    runtime.store_memory(
        key="engram_runtime_direction",
        content="# Summary\n\nEngram uses a daemon-owned Memory OS runtime.",
        title="Runtime Direction",
        project="Engram",
        tags=["reviewed", "decision"],
    )

    response = runtime.query_knowledge(
        {
            "request_id": "req-runtime",
            "ask": {
                "goal": "Get current project context.",
                "task_type": "project_orientation",
                "project": "Engram",
                "focus": ["runtime"],
            },
        }
    )

    assert response["contract_version"] == "engram.knowledge.response.v0"
    assert response["request_id"] == "req-runtime"
    assert response["status"] == "ok"
    assert response["answer"]["project"] == "Engram"
    assert "daemon-owned Memory OS runtime" in response["answer"]["summary"]
    assert response["citations"]
    assert response["budget_used"]["artifacts_built"] == 1
    assert response["budget_used"]["artifacts_read"] == 0
    assert response["policy"]["unsupported_inferences_used"] is False
    assert response["policy"]["review_state_available"] is False
    assert response["policy"]["review_filter_enforced"] is False
    assert response["policy"]["review_state_basis"] == "not_available_in_current_memory_os_records"


def test_memory_os_runtime_query_knowledge_returns_schema_failure(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()

    response = runtime.query_knowledge(
        {
            "request_id": "req-bad",
            "ask": {"task_type": "project_orientation"},
        }
    )

    assert response["status"] == "schema_failed"
    assert response["errors"][0]["code"] == "missing_project"
```

- [ ] **Step 2: Run runtime tests and verify red**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_runtime.py::test_memory_os_runtime_query_knowledge_returns_project_capsule_response tests\memory_os\test_runtime.py::test_memory_os_runtime_query_knowledge_returns_schema_failure -q
```

Expected: fail because `MemoryOSRuntime.query_knowledge` does not exist.

- [ ] **Step 3: Add runtime query implementation**

Reviewed-source semantics for v0:

- `reviewed` or `accepted` means a first-class `review_state` field on a Memory
  OS source/chunk/document record with exactly one of those values. Tags,
  titles, `canonical`, and generic lifecycle `status` fields are not
  authoritative review approval in v0.
- If Memory OS result records expose that first-class `review_state`, filter to
  `reviewed` or `accepted` before building the artifact and set
  `policy.review_state_available=true` plus `policy.review_filter_enforced=true`.
- Current Memory OS memory/chunk records do not expose a reliable first-class
  review state. In that case, enforce the project filter and non-stale/source
  eligibility available to `search_memories`, but set
  `policy.review_state_available=false`,
  `policy.review_filter_enforced=false`, and
  `policy.review_state_basis="not_available_in_current_memory_os_records"`.
- Do not say "reviewed project sources" in user-visible errors unless the real
  review-state filter ran.

Modify `core/memory_os/runtime.py` imports:

```python
from core.memory_os.knowledge_contract import (
    RESPONSE_SCHEMA_VERSION,
    no_answer_response,
    normalize_knowledge_request,
    ok_response,
)
from core.memory_os.project_capsule_artifact import build_project_capsule_artifact
```

Add this method to `MemoryOSRuntime`:

```python
    def query_knowledge(self, request: dict[str, Any]) -> dict[str, Any]:
        """Return an EKC v0 typed project capsule response without writing memory."""
        normalized = normalize_knowledge_request(request)
        if normalized.get("contract_version") == RESPONSE_SCHEMA_VERSION:
            return normalized

        budget = normalized["budget"]
        ask = normalized["ask"]
        query = _knowledge_search_query(ask)
        search = self.search_memories(
            query,
            limit=max(int(budget.get("max_source_reads", 12)), 1),
            project=ask["project"],
            include_stale=False,
            retrieval_mode="hybrid",
        )
        results = list(search.get("results") or [])
        planner = {
            "strategy": "project_capsule",
            "methods_used": ["artifact", "hybrid_search"],
            "omissions": [],
        }
        if not results:
            return no_answer_response(
                request_id=normalized["request_id"],
                code="no_project_sources",
                message=f"No eligible project sources found for {ask['project']}.",
                planner=planner,
            )

        context_packet = {
            "profile": {"id": "project_capsule"},
            "context": {
                "chunks": results,
                "citations": [result.get("citation") for result in results if result.get("citation")],
            },
            "warnings": [],
        }
        artifact = build_project_capsule_artifact(
            project=ask["project"],
            goal=ask["goal"],
            focus=ask["focus"],
            context_packet=context_packet,
            quality_payload={"summary": {}, "issue_count": 0},
            source_snapshot_id="memory_os:latest",
        )
        answer = {
            "project": artifact["project"],
            "summary": artifact["summary"],
            "current_goals": artifact["current_goals"],
            "active_decisions": artifact["active_decisions"],
            "constraints": artifact["constraints"],
            "open_questions": artifact["open_questions"],
            "important_entities": artifact["important_entities"],
            "recent_changes": artifact["recent_changes"],
        }
        partial = artifact["staleness"]["state"] != "fresh" or not artifact["summary"]
        return ok_response(
            request_id=normalized["request_id"],
            answer=answer,
            citations=artifact["citations"],
            freshness={
                "state": artifact["staleness"]["state"],
                "artifact_generated_at": artifact["generated_at"],
                "source_snapshot_id": artifact["source_snapshot_id"],
            },
            budget_used={
                "artifacts_built": 1,
                "artifacts_read": 0,
                "source_reads": len(results),
                "tokens_out_estimate": len(str(answer)) // 4,
            },
            planner=planner,
            partial=partial,
            errors=[] if not partial else [{"code": "partial_capsule", "message": "Capsule is missing one or more optional orientation fields."}],
        )
```

Add helper near the bottom of `core/memory_os/runtime.py`:

```python
def _knowledge_search_query(ask: dict[str, Any]) -> str:
    parts = [ask.get("goal") or "project orientation", ask.get("project") or ""]
    parts.extend(ask.get("focus") or [])
    return " ".join(str(part).strip() for part in parts if str(part).strip())
```

- [ ] **Step 4: Run runtime tests and verify green**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_runtime.py tests\memory_os\test_knowledge_contract.py tests\memory_os\test_project_capsule_artifact.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit runtime query path**

Run:

```powershell
git add core/memory_os/runtime.py tests/memory_os/test_runtime.py
git commit -m "feat: add Memory OS knowledge query path"
```

## Task 4: Daemon Route and Client Helper

**Files:**
- Modify: `core/engramd_api.py`
- Modify: `core/engramd_client.py`
- Test: `tests/test_engramd_api.py`
- Test: `tests/test_engramd_client.py`

- [ ] **Step 1: Add failing daemon API test**

Append to `tests/test_engramd_api.py`:

```python
def test_query_knowledge_routes_to_memory_os_runtime():
    class FakeRuntime:
        def query_knowledge(self, request):
            return {
                "contract_version": "engram.knowledge.response.v0",
                "request_id": request["request_id"],
                "status": "ok",
                "answer": {"project": request["ask"]["project"]},
                "citations": [{"citation_id": "cit_001", "level": "chunk"}],
                "freshness": {"state": "fresh"},
                "policy": {
                    "unreviewed_sources_used": False,
                    "unsupported_inferences_used": False,
                    "review_state_available": False,
                    "review_filter_enforced": False,
                    "review_state_basis": "not_available_in_current_memory_os_records",
                },
                "budget_used": {
                    "artifacts_built": 1,
                    "artifacts_read": 0,
                    "source_reads": 0,
                    "tokens_out_estimate": 0,
                },
                "planner": {"strategy": "project_capsule", "methods_used": ["artifact"], "omissions": []},
                "errors": [],
            }

    api = EngramDaemonAPI(memory_manager=FakeMemoryManager(), memory_os_runtime=FakeRuntime())
    response = api.handle(
        "POST",
        "/v1/query_knowledge",
        {
            "request_id": "req-api",
            "ask": {
                "goal": "Get context.",
                "task_type": "project_orientation",
                "project": "Engram",
            },
        },
    )

    assert response["status"] == 200
    assert response["body"]["request_id"] == "req-api"
    assert response["body"]["answer"]["project"] == "Engram"
```

- [ ] **Step 2: Add failing client test**

Append to `tests/test_engramd_client.py`:

```python
def test_engramd_client_query_knowledge_posts_contract_request():
    calls = []

    class FakeTransport:
        def request_json(self, method, url, payload=None, timeout=10.0):
            calls.append((method, url, payload, timeout))
            return {"status": "ok", "request_id": payload["request_id"]}

    client = EngramDaemonClient(
        "http://127.0.0.1:8765",
        transport=FakeTransport(),
    )

    response = client.query_knowledge(
        {
            "request_id": "req-client",
            "ask": {"project": "Engram", "task_type": "project_orientation"},
        }
    )

    assert response["request_id"] == "req-client"
    assert calls == [
        (
            "POST",
            "http://127.0.0.1:8765/v1/query_knowledge",
            {
                "request_id": "req-client",
                "ask": {"project": "Engram", "task_type": "project_orientation"},
            },
            10.0,
        )
    ]
```

- [ ] **Step 3: Run daemon/client tests and verify red**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\test_engramd_api.py::test_query_knowledge_routes_to_memory_os_runtime tests\test_engramd_client.py::test_engramd_client_query_knowledge_posts_contract_request -q
```

Expected: route/client method missing failures.

- [ ] **Step 4: Implement daemon route**

In `core/engramd_api.py`, add this route before the existing `/v1/search_memories` route:

```python
            if route == "/v1/query_knowledge":
                return await self._query_knowledge(request)
```

Add this method:

```python
    async def _query_knowledge(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.memory_os_runtime is None:
            return self._error(
                503,
                "memory_os_unavailable",
                "query_knowledge requires daemon-owned Memory OS runtime.",
            )
        return self._ok(self.memory_os_runtime.query_knowledge(request))
```

- [ ] **Step 5: Implement client helper**

In `core/engramd_client.py`, add:

```python
    def query_knowledge(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/query_knowledge", payload)
```

- [ ] **Step 6: Run daemon/client tests and verify green**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\test_engramd_api.py tests\test_engramd_client.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit daemon/client route**

Run:

```powershell
git add core/engramd_api.py core/engramd_client.py tests/test_engramd_api.py tests/test_engramd_client.py
git commit -m "feat: route knowledge queries through engramd"
```

## Task 5: Thin MCP Tool

**Files:**
- Modify: `server_daemon_client.py`
- Test: `tests/test_server_daemon_client_entrypoint.py`

- [ ] **Step 1: Add failing thin-client delegation test**

Append to `tests/test_server_daemon_client_entrypoint.py`:

```python
def test_thin_daemon_client_query_knowledge_delegates_to_daemon(monkeypatch):
    import asyncio
    import server_daemon_client

    class FakeClient:
        def query_knowledge(self, payload):
            return {
                "contract_version": "engram.knowledge.response.v0",
                "request_id": payload["request_id"],
                "status": "ok",
                "answer": {"project": payload["ask"]["project"]},
                "citations": [{"citation_id": "cit_001", "level": "chunk"}],
                "freshness": {"state": "fresh"},
                "policy": {
                    "unreviewed_sources_used": False,
                    "unsupported_inferences_used": False,
                    "review_state_available": False,
                    "review_filter_enforced": False,
                    "review_state_basis": "not_available_in_current_memory_os_records",
                },
                "budget_used": {
                    "artifacts_built": 1,
                    "artifacts_read": 0,
                    "source_reads": 0,
                    "tokens_out_estimate": 0,
                },
                "planner": {"strategy": "project_capsule", "methods_used": ["artifact"], "omissions": []},
                "errors": [],
            }

    monkeypatch.setattr(server_daemon_client, "_daemon_client", lambda: FakeClient())

    payload = asyncio.run(
        server_daemon_client.query_knowledge(
            {
                "request_id": "req-thin",
                "ask": {
                    "goal": "Get context.",
                    "task_type": "project_orientation",
                    "project": "Engram",
                },
            }
        )
    )

    assert payload["request_id"] == "req-thin"
    assert payload["answer"]["project"] == "Engram"
```

- [ ] **Step 2: Run thin-client test and verify red**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\test_server_daemon_client_entrypoint.py::test_thin_daemon_client_query_knowledge_delegates_to_daemon -q
```

Expected: fail because `query_knowledge` is not exposed.

- [ ] **Step 3: Add MCP tool and protocol advertisement**

In `server_daemon_client.py`, add this MCP tool after `memory_os_status()`:

```python
@mcp.tool()
async def query_knowledge(request: dict[str, Any]) -> dict[str, Any]:
    """
    Return an Engram Knowledge Contract v0 response for task-shaped project context.

    EKC v0 supports project_orientation requests and returns a typed project
    capsule summary with citations, freshness, policy, budget, planner, and
    explicit errors. This tool is read-only.
    """
    try:
        return await _call_daemon("query_knowledge", request)
    except EngramDaemonClientError as exc:
        return {
            "contract_version": "engram.knowledge.response.v0",
            "request_id": str((request or {}).get("request_id") or ""),
            "status": "unavailable",
            "answer": None,
            "citations": [],
            "freshness": {"state": "unknown"},
            "policy": {
                "unreviewed_sources_used": False,
                "unsupported_inferences_used": False,
                "review_state_available": False,
                "review_filter_enforced": False,
                "review_state_basis": "not_available_in_current_memory_os_records",
            },
            "budget_used": {
                "artifacts_built": 0,
                "artifacts_read": 0,
                "source_reads": 0,
                "tokens_out_estimate": 0,
            },
            "planner": {"strategy": "none", "methods_used": [], "omissions": []},
            "errors": [
                {
                    "code": "runtime_error",
                    "category": "infrastructure",
                    "message": f"Engram daemon error: {exc}",
                }
            ],
        }
```

In `memory_protocol()`, add `query_knowledge` to the stable helper description:

```python
        "knowledge_contract": {
            "tool": "query_knowledge",
            "contract_version": "engram.knowledge.request.v0",
            "response_version": "engram.knowledge.response.v0",
            "scope": "project_orientation via project_capsule_summary",
        },
```

- [ ] **Step 4: Run thin-client tests and verify green**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\test_server_daemon_client_entrypoint.py -q
```

Expected: all thin daemon-client tests pass.

- [ ] **Step 5: Commit thin MCP tool**

Run:

```powershell
git add server_daemon_client.py tests/test_server_daemon_client_entrypoint.py
git commit -m "feat: expose knowledge query MCP tool"
```

## Task 6: Full Server Protocol Manifest

**Files:**
- Modify: `server.py`
- Test: `tests/test_agent_protocol_tools.py`
- Test: `tests/test_server_daemon_client.py`

- [ ] **Step 1: Add failing protocol test**

Append to `tests/test_agent_protocol_tools.py`:

```python
def test_memory_protocol_advertises_knowledge_contract_v0():
    payload = asyncio.run(server.memory_protocol())

    assert payload["tool_groups"]["knowledge_contract"] == {
        "stability": "beta",
        "cost_class": "low-to-medium",
        "tools": ["query_knowledge"],
    }
    assert payload["progressive_discovery"]["load_next"]["knowledge contract"] == "query_knowledge"
    assert "query_knowledge" in payload["canonical_tools"]
    assert "project capsule" in payload["canonical_tools"]["query_knowledge"]
```

- [ ] **Step 2: Run protocol test and verify red**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\test_agent_protocol_tools.py::test_memory_protocol_advertises_knowledge_contract_v0 -q
```

Expected: fail because `memory_protocol()` does not advertise EKC v0.

- [ ] **Step 3: Add failing full-server daemon-routing test**

Modify `tests/test_server_daemon_client.py` so `FakeDaemonClient` includes:

```python
    def query_knowledge(self, payload):
        self.calls.append(("query_knowledge", payload))
        return {
            "contract_version": "engram.knowledge.response.v0",
            "request_id": payload["request_id"],
            "status": "ok",
            "answer": {"project": payload["ask"]["project"]},
            "citations": [{"citation_id": "cit_001", "level": "chunk"}],
            "freshness": {"state": "fresh"},
            "policy": {
                "unreviewed_sources_used": False,
                "unsupported_inferences_used": False,
                "review_state_available": False,
                "review_filter_enforced": False,
                "review_state_basis": "not_available_in_current_memory_os_records",
            },
            "budget_used": {
                "artifacts_built": 1,
                "artifacts_read": 0,
                "source_reads": 0,
                "tokens_out_estimate": 0,
            },
            "planner": {"strategy": "project_capsule", "methods_used": ["artifact"], "omissions": []},
            "errors": [],
        }
```

Append this test to `tests/test_server_daemon_client.py`:

```python
def test_query_knowledge_uses_daemon_when_configured(monkeypatch):
    client = FakeDaemonClient()
    monkeypatch.setenv("ENGRAM_DAEMON_URL", "http://127.0.0.1:8765")
    monkeypatch.setattr(server, "_daemon_client", lambda: client)

    payload = asyncio.run(
        server.query_knowledge(
            {
                "request_id": "req-server",
                "ask": {
                    "goal": "Get context.",
                    "task_type": "project_orientation",
                    "project": "Engram",
                },
            }
        )
    )

    assert payload["request_id"] == "req-server"
    assert payload["answer"]["project"] == "Engram"
    assert client.calls[-1][0] == "query_knowledge"
```

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\test_server_daemon_client.py::test_query_knowledge_uses_daemon_when_configured -q
```

Expected: fail because `server.query_knowledge` does not exist.

- [ ] **Step 4: Update `memory_protocol()` manifest**

In `server.py`, add a `knowledge_contract` tool group next to `agent_workflows`:

```python
            "knowledge_contract": {
                "stability": "beta",
                "cost_class": "low-to-medium",
                "tools": ["query_knowledge"],
            },
```

Add this progressive discovery entry:

```python
                "knowledge contract": "query_knowledge",
```

Add this canonical tool entry:

```python
            "query_knowledge": "Return an EKC v0 project capsule response with citations, freshness, policy, budget, planner, and typed errors.",
```

Add this daemon-first MCP tool to `server.py`:

```python
@mcp.tool()
async def query_knowledge(request: dict[str, Any]) -> dict[str, Any]:
    """
    Return an Engram Knowledge Contract v0 project capsule response.

    This tool is read-only. It requires the daemon-owned Memory OS path because
    EKC v0 is a serving contract over compiled local context, not a legacy
    direct-mode memory write path.
    """
    if _daemon_enabled():
        try:
            return await asyncio.to_thread(_daemon_client().query_knowledge, request)
        except EngramDaemonClientError as exc:
            return _query_knowledge_runtime_error(request, str(exc))
    return _query_knowledge_runtime_error(
        request,
        "query_knowledge requires the daemon-owned Memory OS path.",
        code="daemon_required",
    )


def _query_knowledge_runtime_error(
    request: dict[str, Any] | None,
    message: str,
    *,
    code: str = "runtime_error",
) -> dict[str, Any]:
    return {
        "contract_version": "engram.knowledge.response.v0",
        "request_id": str((request or {}).get("request_id") or ""),
        "status": "unavailable",
        "answer": None,
        "citations": [],
        "freshness": {"state": "unknown"},
        "policy": {
            "unreviewed_sources_used": False,
            "unsupported_inferences_used": False,
            "review_state_available": False,
            "review_filter_enforced": False,
            "review_state_basis": "not_available_in_current_memory_os_records",
        },
        "budget_used": {
            "artifacts_built": 0,
            "artifacts_read": 0,
            "source_reads": 0,
            "tokens_out_estimate": 0,
        },
        "planner": {"strategy": "none", "methods_used": [], "omissions": []},
        "errors": [{"code": code, "category": "infrastructure", "message": message}],
    }
```

- [ ] **Step 5: Run protocol and full-server daemon tests and verify green**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\test_agent_protocol_tools.py tests\test_server_structured_tools.py tests\test_server_daemon_client.py -q
```

Expected: all protocol and structured-tool tests pass.

- [ ] **Step 6: Commit protocol manifest and wrapper**

Run:

```powershell
git add server.py tests/test_agent_protocol_tools.py tests/test_server_daemon_client.py
git commit -m "docs: advertise knowledge contract tool"
```

## Task 7: EKC v0 Eval Harness

**Files:**
- Create: `core/memory_os/knowledge_eval.py`
- Test: `tests/memory_os/test_knowledge_eval.py`

- [ ] **Step 1: Write failing eval test**

Create `tests/memory_os/test_knowledge_eval.py`:

```python
from core.memory_os.knowledge_eval import DEFAULT_QUESTIONS, run_project_orientation_eval


class FakeRuntime:
    def __init__(self):
        self.search_calls = 0
        self.retrieve_calls = 0
        self.context_calls = 0
        self.knowledge_calls = 0

    def search_memories(self, query, **kwargs):
        self.search_calls += 1
        return {
            "count": 3,
            "results": [
                {
                    "key": "engram_direction",
                    "chunk_id": 0,
                    "snippet": "Engram is a local-first Memory OS.",
                    "citation": {"key": "engram_direction", "chunk_id": 0},
                },
                {
                    "key": "engram_constraints",
                    "chunk_id": 0,
                    "snippet": "Writes are explicit and reviewed.",
                    "citation": {"key": "engram_constraints", "chunk_id": 0},
                },
                {
                    "key": "engram_runtime",
                    "chunk_id": 0,
                    "snippet": "The daemon owns Memory OS state.",
                    "citation": {"key": "engram_runtime", "chunk_id": 0},
                }
            ],
            "error": None,
        }

    def retrieve_chunk(self, key, chunk_id):
        self.retrieve_calls += 1
        return {
            "key": key,
            "chunk_id": chunk_id,
            "text": "Retrieved orientation evidence.",
            "citation": {"key": key, "chunk_id": chunk_id},
        }

    def context_pack(self, query, **kwargs):
        self.context_calls += 1
        return {
            "context": {
                "chunks": [{"key": "engram_direction", "chunk_id": 0}],
                "citations": [{"key": "engram_direction", "chunk_id": 0}],
            }
        }

    def query_knowledge(self, request):
        self.knowledge_calls += 1
        return {
            "status": "ok",
            "answer": {"summary": "Engram is a local-first Memory OS."},
            "citations": [{"citation_id": "cit_001"}],
            "errors": [],
        }


def test_project_orientation_eval_compares_search_only_to_ekc():
    runtime = FakeRuntime()
    human_ratings = {
        question: {"search_only": 4.0, "ekc": 4.0}
        for question in DEFAULT_QUESTIONS
    }

    report = run_project_orientation_eval(
        runtime,
        project="Engram",
        human_ratings=human_ratings,
    )

    assert report["schema_version"] == "2026-05-13.ekc-v0.eval.v1"
    assert report["project"] == "Engram"
    assert report["question_count"] == 5
    assert report["search_only"]["tool_calls"] == 25
    assert report["ekc"]["tool_calls"] == 5
    assert report["ekc"]["citation_presence_rate"] == 1.0
    assert report["continuation_threshold"]["tool_call_reduction_target"] == 0.3
    assert report["tool_call_reduction_rate"] >= 0.3
    assert report["human_usefulness"]["status"] == "scored"
    assert report["human_usefulness"]["preserved"] is True
    assert report["passes"] is True
```

- [ ] **Step 2: Run eval test and verify red**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_knowledge_eval.py -q
```

Expected: fail with `ModuleNotFoundError`.

- [ ] **Step 3: Implement eval harness**

Create `core/memory_os/knowledge_eval.py`:

```python
"""EKC v0 project-orientation eval helpers."""
from __future__ import annotations

from typing import Any

DEFAULT_QUESTIONS = (
    "What is Engram's current architecture direction?",
    "What are the active constraints around reviewed writes?",
    "What should I know before modifying the MCP interface?",
    "What decisions already exist about local-first memory?",
    "What are the open questions for project capsule implementation?",
)


def run_project_orientation_eval(
    runtime: Any,
    *,
    project: str,
    human_ratings: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    search_only = [_run_search_orientation_workflow(runtime, project, question) for question in DEFAULT_QUESTIONS]
    ekc = [_run_ekc_question(runtime, project, question) for question in DEFAULT_QUESTIONS]
    search_summary = _summarize_search(search_only)
    ekc_summary = _summarize_ekc(ekc)
    reduction = _tool_call_reduction(search_summary["tool_calls"], ekc_summary["tool_calls"])
    human_usefulness = _summarize_human_usefulness(DEFAULT_QUESTIONS, human_ratings)
    citation_preserved = ekc_summary["citation_presence_rate"] >= search_summary["citation_presence_rate"]
    return {
        "schema_version": "2026-05-13.ekc-v0.eval.v1",
        "project": project,
        "question_count": len(DEFAULT_QUESTIONS),
        "search_only": search_summary,
        "ekc": ekc_summary,
        "tool_call_reduction_rate": reduction,
        "citation_presence_preserved": citation_preserved,
        "human_usefulness": human_usefulness,
        "continuation_threshold": {
            "tool_call_reduction_target": 0.3,
            "requires_citation_presence_preserved": True,
            "requires_human_usefulness_preserved": True,
        },
        "passes": reduction >= 0.3 and citation_preserved and human_usefulness["preserved"] is True,
    }


def _run_search_orientation_workflow(runtime: Any, project: str, question: str) -> dict[str, Any]:
    tool_calls = 0
    initial = runtime.search_memories(question, project=project, limit=3)
    tool_calls += 1
    results = list(initial.get("results") or [])[:3]
    chunks = []
    for result in results:
        chunks.append(runtime.retrieve_chunk(result.get("key"), result.get("chunk_id")))
        tool_calls += 1
    if results:
        # Project orientation normally needs a second pass for constraints,
        # decisions, or related context after the first result set is read.
        if hasattr(runtime, "context_pack"):
            runtime.context_pack(f"{question} constraints decisions citations", project=project, max_chunks=3)
        else:
            runtime.search_memories(f"{question} constraints decisions citations", project=project, limit=3)
        tool_calls += 1
    return {
        "question": question,
        "tool_calls": tool_calls,
        "result_count": int(initial.get("count") or 0),
        "has_citation": any(result.get("citation") for result in results)
        or any(chunk.get("citation") for chunk in chunks if isinstance(chunk, dict)),
    }


def _run_ekc_question(runtime: Any, project: str, question: str) -> dict[str, Any]:
    payload = runtime.query_knowledge(
        {
            "ask": {
                "goal": question,
                "task_type": "project_orientation",
                "project": project,
            }
        }
    )
    return {
        "question": question,
        "tool_calls": 1,
        "status": payload.get("status"),
        "has_citation": bool(payload.get("citations")),
        "schema_valid": payload.get("answer") is not None
        or payload.get("status") in {
            "no_answer",
            "partial",
            "schema_failed",
            "policy_denied",
            "budget_exceeded",
            "unavailable",
        },
    }


def _summarize_search(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "tool_calls": sum(int(row["tool_calls"]) for row in rows),
        "questions_with_results": sum(1 for row in rows if row["result_count"] > 0),
        "citation_presence_rate": _rate(rows, "has_citation"),
    }


def _summarize_ekc(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "tool_calls": sum(int(row["tool_calls"]) for row in rows),
        "ok_or_partial_count": sum(1 for row in rows if row["status"] in {"ok", "partial"}),
        "schema_valid_rate": _rate(rows, "schema_valid"),
        "citation_presence_rate": _rate(rows, "has_citation"),
    }


def _rate(rows: list[dict[str, Any]], field: str) -> float:
    if not rows:
        return 0.0
    return sum(1 for row in rows if row.get(field)) / len(rows)


def _tool_call_reduction(search_calls: int, ekc_calls: int) -> float:
    if search_calls <= 0:
        return 0.0
    return max((search_calls - ekc_calls) / search_calls, 0.0)


def _summarize_human_usefulness(
    questions: tuple[str, ...],
    ratings: dict[str, dict[str, float]] | None,
) -> dict[str, Any]:
    if not ratings:
        return {
            "status": "not_scored",
            "preserved": False,
            "reason": "Human ratings are required for the EKC v0 continuation gate.",
        }
    rows = [ratings.get(question, {}) for question in questions]
    search_avg = sum(float(row.get("search_only", 0.0)) for row in rows) / len(questions)
    ekc_avg = sum(float(row.get("ekc", 0.0)) for row in rows) / len(questions)
    return {
        "status": "scored",
        "search_only_average": search_avg,
        "ekc_average": ekc_avg,
        "preserved": ekc_avg >= search_avg,
    }
```

- [ ] **Step 4: Run eval test and verify green**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_knowledge_eval.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit eval harness**

Run:

```powershell
git add core/memory_os/knowledge_eval.py tests/memory_os/test_knowledge_eval.py
git commit -m "test: add knowledge contract orientation eval"
```

## Task 8: Documentation and Operator Guidance

**Files:**
- Modify: `plan.md`
- Modify: `docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md`
- Modify: `README.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: Update `plan.md` tracked docs and decisions**

Add an EKC v0 product enhancement section:

```markdown
## Engram Knowledge Contract v0 - Local Agent Contract Hardening

EKC v0 is a planned local product enhancement, not a hosted feature and not a
Pinecone/Nexus dependency. It adds one MCP-facing `query_knowledge` contract,
one deterministic `project_capsule` artifact, and one project-orientation eval.

Tracked docs:

- `docs/superpowers/specs/2026-05-13-engram-knowledge-contract-v0-design.md`
- `docs/superpowers/plans/2026-05-13-engram-knowledge-contract-v0-plan.md`

Key constraints:

- no local KnowQL clone
- no Pinecone dependency
- no autonomous compiler in v0
- no automatic durable memory writes
- unsupported inference defaults to forbidden
```

- [ ] **Step 2: Update Memory OS spec agent workflow section**

In `docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md`, add `query_knowledge` near the
context compiler/project capsule tool list:

```markdown
- `query_knowledge` accepts EKC v0 project-orientation requests and returns a
  typed project capsule response with citations, freshness, policy, budget,
  planner, and explicit errors. It is read-only and does not replace
  `prepare_project_capsule`, which remains a draft/review helper.
```

- [ ] **Step 3: Update README agent quickstart**

Add a short note:

```markdown
For repeated project orientation, start with `query_knowledge` when available.
It returns a typed EKC v0 project capsule response. Use `search_memories` and
`retrieve_chunk` when you need lower-level evidence beyond the capsule.
```

- [ ] **Step 4: Update AGENTS.md tool guidance**

Add an agent-facing note:

```markdown
Use `query_knowledge` for project-orientation context when the thin daemon
client advertises EKC v0. It is a read-only serving contract. It must not be
treated as permission to write or promote memory.
```

- [ ] **Step 5: Run doc sanity checks**

Run:

```powershell
rg -n "query_knowledge|Knowledge Contract|KnowQL|Pinecone" plan.md docs README.md AGENTS.md
git diff --check
```

Expected: EKC docs are discoverable, Pinecone/KnowQL are mentioned only as
non-goal/inspiration language, and `git diff --check` reports no whitespace
errors.

- [ ] **Step 6: Commit documentation**

Run:

```powershell
git add plan.md docs/ENGRAM_MEMORY_OS_REBUILD_SPEC.md README.md AGENTS.md
git commit -m "docs: document knowledge contract v0"
```

## Task 9: Full Validation Gate

**Files:**
- No new files

- [ ] **Step 1: Run focused EKC tests**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_knowledge_contract.py tests\memory_os\test_project_capsule_artifact.py tests\memory_os\test_knowledge_eval.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run daemon and protocol tests**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest tests\memory_os\test_runtime.py tests\test_engramd_api.py tests\test_engramd_client.py tests\test_server_daemon_client_entrypoint.py tests\test_agent_protocol_tools.py -q
```

Expected: all tests pass.

- [ ] **Step 3: Run repository completion gates**

Run:

```powershell
.\venv\Scripts\python.exe server.py --help
.\venv\Scripts\python.exe -c "from core.memory_manager import memory_manager; print('ok')"
.\venv\Scripts\python.exe engramd.py --doctor
.\venv\Scripts\python.exe engramd.py --smoke-test
$env:ENGRAM_DATA_DIR = Join-Path $env:TEMP ("engram-ekc-self-test-" + [guid]::NewGuid())
.\venv\Scripts\python.exe server.py --self-test
$env:ENGRAM_DATA_DIR = Join-Path $env:TEMP ("engram-ekc-agent-eval-" + [guid]::NewGuid())
.\venv\Scripts\python.exe server.py --agent-eval
git diff --check
```

Expected: all commands pass. `server.py --agent-eval` still reports the Book
Dismantling Gate as passing.

- [ ] **Step 4: Run full pytest if focused gates pass**

Run:

```powershell
.\venv\Scripts\python.exe -m pytest -q
```

Expected: full suite passes with only known skips.

- [ ] **Step 5: Commit validation notes if docs changed during validation**

Run this only if validation required doc updates:

```powershell
git add docs plan.md README.md AGENTS.md
git commit -m "docs: record knowledge contract validation"
```

## Task 10: Closeout and Memory

**Files:**
- No required code files

- [ ] **Step 1: Inspect final worktree**

Run:

```powershell
git status --short --branch
git log --oneline -8
```

Expected: branch contains logically scoped EKC commits and no unrelated dirty
files.

- [ ] **Step 2: Write Engram closeout memory if MCP tools are available**

Use `write_memory` with a key like:

```text
engram_knowledge_contract_v0_closeout_2026_05_13
```

Content should include:

- repo path
- branch and final commit
- files changed
- validation commands
- whether EKC v0 is production-ready or still planned
- next recommended step

- [ ] **Step 3: Fallback memory if Engram write is unavailable**

If the write fails with a transport/runtime error, append an import-ready entry
to a repo doc named `docs/ENGRAM_MEMORY_FALLBACK_2026_05_13.md` with:

```markdown
## engram_knowledge_contract_v0_closeout_2026_05_13

Repo: C:\Dev\Engram
Summary: EKC v0 added a typed project capsule query contract for project orientation.
Validation: Record exact commands run and pass/fail outcomes in this line.
Next step: Record the next recommended action in this line.
```

- [ ] **Step 4: Final response**

Report:

- spec path
- plan path
- final commit id
- validation commands run
- any residual risk

## Plan Self-Review

- Spec coverage: The plan covers request/response contract, deterministic
  capsule artifact, runtime path, daemon route, thin MCP tool, protocol
  discovery, eval, docs, validation, and Engram closeout memory.
- Placeholder scan: The plan contains no unfinished placeholder tokens or undefined future work items.
- Type consistency: The plan consistently uses `query_knowledge`,
  `engram.knowledge.request.v0`, `engram.knowledge.response.v0`,
  `project_orientation`, and `project_capsule_summary`.
- Scope check: The implementation plan intentionally excludes local KnowQL,
  Pinecone integration, autonomous compilers, graph-path packets, entity
  profiles, and locator-level citations from the v0 implementation slice. The
  product roadmap adds source/document orientation, review-preparation, evidence
  audit, and bounded graph/contradiction work before any generic artifact
  families.
- Hardening check: The revised plan enforces safe policy overrides, defines
  current reviewed-source semantics honestly, keeps capsule behavior anchored to
  `core.project_capsule`, separates ephemeral `artifacts_built` from persisted
  `artifacts_read`, treats daemon/runtime failure as `unavailable`, and gates
  continuation on a >=30% orientation workflow call reduction with citations and
  human-rated usefulness preserved.

## EKC Roadmap After v0

Keep v0 through v0.4 as the foundation:

- v0: shape - one typed `query_knowledge` response over project capsules
- v0.1: contract - stable schema, status, error, and inference-policy behavior
- v0.2: persisted artifact - ledgered, versioned project capsules with source refs
- v0.3: citations - artifact/chunk citations first, locator citations later
- v0.4: accountable planner - explicit strategy, omissions, budget, and failure receipt

Revise v0.5 onward as an evidence-first ladder:

- v0.5: source/document orientation before generic artifact families
- v0.6: review-preparation packets for candidate promotions and quality warnings
- v0.7: evidence audit responses for grounding gaps, stale refs, and weak claims
- v0.8: bounded graph evidence and contradiction surfacing with cited paths
- v0.9: higher-level artifact families such as `entity_profile`,
  `decision_packet`, `implementation_context`, and richer `evidence_bundle`
- v1.0: stable agent knowledge contract proven by evals across project,
  source/document, review-prep, evidence audit, and bounded graph workflows

Do not add entity profiles, decision packets, or implementation-context
artifacts before the source/document, review-prep, evidence-audit, and bounded
graph stages have passed focused evals.

## Execution Options

Plan complete and saved to `docs/superpowers/plans/2026-05-13-engram-knowledge-contract-v0-plan.md`. Two execution options:

1. Subagent-Driven (recommended) - dispatch a fresh subagent per task, review between tasks, fast iteration.
2. Inline Execution - execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.
