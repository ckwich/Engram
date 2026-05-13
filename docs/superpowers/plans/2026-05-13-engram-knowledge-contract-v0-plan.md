# Engram Knowledge Contract v0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a narrow Engram Knowledge Contract v0 path that lets agents request typed, cited project orientation through a deterministic project capsule response.

**Architecture:** EKC v0 is an MCP-facing contract over the existing daemon-owned Memory OS. It reuses the SQLite ledger, Memory OS retrieval, project capsule concepts, and thin daemon-client entrypoint; it does not add Pinecone, KnowQL compatibility, autonomous compilers, or automatic memory writes.

**Tech Stack:** Python 3.10+, FastMCP, `engramd`, `core.memory_os`, SQLite ledger records, LanceDB-backed Memory OS search, pytest, existing reliability/eval harness patterns.

---

## File Map

- Create `core/memory_os/knowledge_contract.py`: EKC v0 constants, request normalization, validation, status helpers, and response builders.
- Create `core/memory_os/project_capsule_artifact.py`: deterministic read-only project capsule artifact builder over Memory OS search results.
- Create `core/memory_os/knowledge_eval.py`: small search-only versus EKC project-orientation comparison harness.
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

## Product Guardrails

- Keep the first slice to one tool, one artifact, one eval.
- Default unsupported inference to forbidden.
- Return typed failures instead of broad fallback search.
- Do not write durable memories from `query_knowledge`.
- Do not make graph traversal required for v0.
- Do not add remote provider calls.
- Do not expose policy-denied content in diagnostics.

## Task 1: EKC v0 Contract Module

**Files:**
- Create: `core/memory_os/knowledge_contract.py`
- Test: `tests/memory_os/test_knowledge_contract.py`

- [ ] **Step 1: Write failing contract tests**

Create `tests/memory_os/test_knowledge_contract.py`:

```python
from core.memory_os.knowledge_contract import (
    REQUEST_SCHEMA_VERSION,
    RESPONSE_SCHEMA_VERSION,
    normalize_knowledge_request,
    schema_failed_response,
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
```

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
        "policy": _merge(DEFAULT_POLICY, raw.get("policy")),
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
        "policy": {
            "unreviewed_sources_used": False,
            "unsupported_inferences_used": False,
        },
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
        "policy": {
            "unreviewed_sources_used": False,
            "unsupported_inferences_used": False,
        },
        "budget_used": {
            "artifacts_read": 0,
            "source_reads": 0,
            "tokens_out_estimate": 0,
        },
        "planner": {"strategy": "none", "methods_used": [], "omissions": []},
        "errors": errors,
    }


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

## Task 2: Deterministic Project Capsule Artifact

**Files:**
- Create: `core/memory_os/project_capsule_artifact.py`
- Test: `tests/memory_os/test_project_capsule_artifact.py`

- [ ] **Step 1: Write failing artifact tests**

Create `tests/memory_os/test_project_capsule_artifact.py`:

```python
from core.memory_os.project_capsule_artifact import build_project_capsule_artifact


def test_project_capsule_artifact_groups_orientation_chunks_by_heading():
    search_results = [
        {
            "key": "engram_direction",
            "chunk_id": 0,
            "title": "Engram Direction",
            "text": "# Summary\n\nEngram is a local-first Memory OS.",
            "score": 0.91,
            "citation": {"source": "memory_os", "key": "engram_direction", "chunk_id": 0},
            "metadata": {"tags": ["decision"], "project": "Engram"},
        },
        {
            "key": "engram_constraints",
            "chunk_id": 0,
            "title": "Engram Constraints",
            "text": "# Constraints\n\nWrites must remain explicit and reviewed.",
            "score": 0.84,
            "citation": {"source": "memory_os", "key": "engram_constraints", "chunk_id": 0},
            "metadata": {"tags": ["constraint"], "project": "Engram"},
        },
    ]

    artifact = build_project_capsule_artifact(
        project="Engram",
        goal="Get current project context.",
        focus=["Memory OS"],
        search_results=search_results,
        source_snapshot_id="memory_os:test",
    )

    assert artifact["artifact_type"] == "project_capsule"
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


def test_project_capsule_artifact_returns_partial_when_sources_are_empty():
    artifact = build_project_capsule_artifact(
        project="Engram",
        goal="Get current project context.",
        focus=[],
        search_results=[],
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

- [ ] **Step 3: Implement the artifact builder**

Create `core/memory_os/project_capsule_artifact.py` using deterministic heading-based grouping:

```python
"""Deterministic project capsule artifacts for EKC v0."""
from __future__ import annotations

from typing import Any

from core.memory_os._records import now_iso

PROJECT_CAPSULE_ARTIFACT_VERSION = "v0"


def build_project_capsule_artifact(
    *,
    project: str,
    goal: str,
    focus: list[str],
    search_results: list[dict[str, Any]],
    source_snapshot_id: str,
) -> dict[str, Any]:
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

    for index, result in enumerate(search_results, start=1):
        citation_id = f"cit_{index:03d}"
        key = str(result.get("key") or "")
        chunk_id = int(result.get("chunk_id", 0))
        text = str(result.get("text") or result.get("snippet") or "")
        citation = dict(result.get("citation") or {})
        citations.append(
            {
                "citation_id": citation_id,
                "level": "chunk",
                "key": key,
                "chunk_id": chunk_id,
                "source": citation.get("source", "memory_os"),
                "document_id": citation.get("document_id"),
                "review_state": "reviewed",
            }
        )
        source_refs.append(
            {
                "key": key,
                "chunk_id": chunk_id,
                "citation_id": citation_id,
                "score": float(result.get("score") or 0.0),
            }
        )
        _merge_text_into_fields(fields, text)

    return {
        "artifact_type": "project_capsule",
        "artifact_version": PROJECT_CAPSULE_ARTIFACT_VERSION,
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

- [ ] **Step 5: Commit the artifact builder**

Run:

```powershell
git add core/memory_os/project_capsule_artifact.py tests/memory_os/test_project_capsule_artifact.py
git commit -m "feat: build project capsule artifacts"
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
    assert response["budget_used"]["artifacts_read"] == 1
    assert response["policy"]["unsupported_inferences_used"] is False


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
                message=f"No reviewed project sources found for {ask['project']}.",
                planner=planner,
            )

        artifact = build_project_capsule_artifact(
            project=ask["project"],
            goal=ask["goal"],
            focus=ask["focus"],
            search_results=results,
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
                "artifacts_read": 1,
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
                "citations": [],
                "freshness": {"state": "fresh"},
                "policy": {
                    "unreviewed_sources_used": False,
                    "unsupported_inferences_used": False,
                },
                "budget_used": {
                    "artifacts_read": 1,
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
                "citations": [],
                "freshness": {"state": "fresh"},
                "policy": {
                    "unreviewed_sources_used": False,
                    "unsupported_inferences_used": False,
                },
                "budget_used": {
                    "artifacts_read": 1,
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
            "status": "no_answer",
            "answer": None,
            "citations": [],
            "freshness": {"state": "unknown"},
            "policy": {
                "unreviewed_sources_used": False,
                "unsupported_inferences_used": False,
            },
            "budget_used": {
                "artifacts_read": 0,
                "source_reads": 0,
                "tokens_out_estimate": 0,
            },
            "planner": {"strategy": "none", "methods_used": [], "omissions": []},
            "errors": [
                {
                    "code": "runtime_error",
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
            "citations": [],
            "freshness": {"state": "fresh"},
            "policy": {
                "unreviewed_sources_used": False,
                "unsupported_inferences_used": False,
            },
            "budget_used": {
                "artifacts_read": 1,
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
        "status": "no_answer",
        "answer": None,
        "citations": [],
        "freshness": {"state": "unknown"},
        "policy": {
            "unreviewed_sources_used": False,
            "unsupported_inferences_used": False,
        },
        "budget_used": {
            "artifacts_read": 0,
            "source_reads": 0,
            "tokens_out_estimate": 0,
        },
        "planner": {"strategy": "none", "methods_used": [], "omissions": []},
        "errors": [{"code": code, "message": message}],
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
from core.memory_os.knowledge_eval import run_project_orientation_eval


class FakeRuntime:
    def __init__(self):
        self.search_calls = 0
        self.knowledge_calls = 0

    def search_memories(self, query, **kwargs):
        self.search_calls += 1
        return {
            "count": 1,
            "results": [
                {
                    "key": "engram_direction",
                    "chunk_id": 0,
                    "snippet": "Engram is a local-first Memory OS.",
                }
            ],
            "error": None,
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

    report = run_project_orientation_eval(runtime, project="Engram")

    assert report["schema_version"] == "2026-05-13.ekc-v0.eval.v1"
    assert report["project"] == "Engram"
    assert report["question_count"] == 5
    assert report["search_only"]["tool_calls"] == 5
    assert report["ekc"]["tool_calls"] == 5
    assert report["ekc"]["citation_presence_rate"] == 1.0
    assert report["continuation_threshold"]["tool_call_reduction_target"] == 0.3
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

PROJECT_ORIENTATION_QUESTIONS = (
    "What is Engram's current architecture direction?",
    "What are the active constraints around reviewed writes?",
    "What should I know before modifying the MCP interface?",
    "What decisions already exist about local-first memory?",
    "What are the open questions for project capsule implementation?",
)


def run_project_orientation_eval(runtime: Any, *, project: str) -> dict[str, Any]:
    search_only = [_run_search_question(runtime, project, question) for question in PROJECT_ORIENTATION_QUESTIONS]
    ekc = [_run_ekc_question(runtime, project, question) for question in PROJECT_ORIENTATION_QUESTIONS]
    return {
        "schema_version": "2026-05-13.ekc-v0.eval.v1",
        "project": project,
        "question_count": len(PROJECT_ORIENTATION_QUESTIONS),
        "search_only": _summarize_search(search_only),
        "ekc": _summarize_ekc(ekc),
        "continuation_threshold": {
            "tool_call_reduction_target": 0.3,
            "requires_equal_or_better_traceability": True,
        },
    }


def _run_search_question(runtime: Any, project: str, question: str) -> dict[str, Any]:
    payload = runtime.search_memories(question, project=project, limit=5)
    return {
        "question": question,
        "tool_calls": 1,
        "result_count": int(payload.get("count") or 0),
        "has_citation": any(result.get("citation") for result in payload.get("results", [])),
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
        "schema_valid": payload.get("answer") is not None or payload.get("status") in {"no_answer", "partial", "schema_failed"},
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
