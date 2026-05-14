from __future__ import annotations

import json
from pathlib import Path

from core.memory_os.knowledge_contract import (
    REQUEST_SCHEMA_VERSION,
    RESPONSE_SCHEMA_VERSION,
    normalize_knowledge_request,
    policy_denied_response,
    schema_failed_response,
    unavailable_response,
    validate_knowledge_response,
)
from core.memory_os.knowledge_planner import build_planner_receipt


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "knowledge_contract"


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


def test_normalize_knowledge_request_supports_source_and_document_orientation_defaults():
    source_request = normalize_knowledge_request(
        {
            "ask": {
                "goal": "Orient me to this source.",
                "task_type": "source_orientation",
                "project": "Engram",
            }
        }
    )
    document_request = normalize_knowledge_request(
        {
            "ask": {
                "goal": "Orient me to this document.",
                "task_type": "document_orientation",
                "project": "Engram",
            }
        }
    )

    assert source_request["shape"]["response_type"] == "source_orientation_summary"
    assert document_request["shape"]["response_type"] == "document_orientation_summary"
    assert source_request["policy"]["write_behavior"] == "read_only"
    assert document_request["policy"]["allow_unreviewed_sources"] is False


def test_normalize_knowledge_request_supports_review_preparation_defaults():
    request = normalize_knowledge_request(
        {
            "ask": {
                "goal": "Prepare review packet.",
                "task_type": "review_preparation",
                "project": "Engram",
            }
        }
    )

    assert request["shape"]["response_type"] == "review_preparation_packet"
    assert request["policy"]["write_behavior"] == "read_only"
    assert request["policy"]["allow_unreviewed_sources"] is False


def test_normalize_knowledge_request_supports_evidence_audit_defaults():
    request = normalize_knowledge_request(
        {
            "ask": {
                "goal": "Audit evidence.",
                "task_type": "evidence_audit",
                "project": "Engram",
            }
        }
    )

    assert request["shape"]["response_type"] == "evidence_audit_report"
    assert request["policy"]["write_behavior"] == "read_only"


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
        "citations": [
            {
                "citation_id": "cit_001",
                "level": "chunk",
                "source": "memory_os",
                "key": "engram_direction",
                "chunk_id": 0,
            }
        ],
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
        "planner": build_planner_receipt(
            strategy="project_capsule",
            methods_used=["artifact"],
            request_budget={"max_artifacts": 1, "max_source_reads": 12, "max_tokens_out": 2500},
            budget_used={
                "artifacts_built": 1,
                "artifacts_read": 0,
                "source_reads": 1,
                "tokens_out_estimate": 10,
            },
        ),
        "errors": [],
    }
    unavailable = unavailable_response(
        request_id="req-down",
        code="runtime_error",
        message="daemon unavailable",
    )

    assert validate_knowledge_response(ok)["valid"] is True
    assert validate_knowledge_response(unavailable)["valid"] is True
    assert unavailable["planner"]["failure_receipts"][0]["category"] == "infrastructure"


def test_validate_knowledge_response_rejects_malformed_success_citations():
    invalid = {
        "contract_version": RESPONSE_SCHEMA_VERSION,
        "request_id": "req-bad-citation",
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
        "planner": build_planner_receipt(
            strategy="project_capsule",
            methods_used=["artifact"],
            request_budget={"max_artifacts": 1, "max_source_reads": 12, "max_tokens_out": 2500},
            budget_used={
                "artifacts_built": 1,
                "artifacts_read": 0,
                "source_reads": 1,
                "tokens_out_estimate": 10,
            },
        ),
        "errors": [],
    }

    result = validate_knowledge_response(invalid)

    assert result["valid"] is False
    assert "invalid_citation_0_missing_level" in result["errors"]
    assert "invalid_citation_0_missing_source" in result["errors"]


def test_validate_knowledge_response_rejects_malformed_planner_receipt():
    invalid = {
        "contract_version": RESPONSE_SCHEMA_VERSION,
        "request_id": "req-bad-planner",
        "status": "ok",
        "answer": {"project": "Engram"},
        "citations": [
            {
                "citation_id": "cit_001",
                "level": "chunk",
                "source": "memory_os",
                "key": "engram_direction",
                "chunk_id": 0,
            }
        ],
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

    result = validate_knowledge_response(invalid)

    assert result["valid"] is False
    assert "invalid_planner_missing_budget" in result["errors"]
    assert "invalid_planner_missing_failure_receipts" in result["errors"]


def test_validate_knowledge_response_rejects_missing_envelope_fields():
    invalid = {"status": "ok", "answer": {"project": "Engram"}}

    result = validate_knowledge_response(invalid)

    assert result["valid"] is False
    assert "contract_version" in result["missing_fields"]


def test_policy_denied_response_uses_policy_error_category():
    response = policy_denied_response(
        request_id="req-policy",
        code="write_behavior_not_allowed",
        message="EKC v0 query_knowledge is read-only.",
    )

    assert response["status"] == "policy_denied"
    assert response["errors"][0]["category"] == "policy"
    assert validate_knowledge_response(response)["valid"] is True


def test_golden_knowledge_response_fixtures_are_valid():
    fixture_names = {
        "ok.json",
        "partial.json",
        "no_answer.json",
        "policy_denied.json",
        "budget_exceeded.json",
        "schema_failed.json",
        "unavailable_runtime_error.json",
    }

    for fixture_name in fixture_names:
        payload = json.loads((FIXTURE_DIR / fixture_name).read_text(encoding="utf-8"))
        result = validate_knowledge_response(payload)
        assert result["valid"] is True, (fixture_name, result)

    unavailable = json.loads(
        (FIXTURE_DIR / "unavailable_runtime_error.json").read_text(encoding="utf-8")
    )
    assert unavailable["status"] == "unavailable"
    assert unavailable["errors"][0]["category"] == "infrastructure"
