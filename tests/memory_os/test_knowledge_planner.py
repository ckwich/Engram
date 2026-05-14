from core.memory_os.knowledge_planner import (
    build_planner_receipt,
    validate_planner_receipt,
)


def test_build_planner_receipt_records_strategy_methods_and_budget():
    receipt = build_planner_receipt(
        strategy="project_capsule",
        methods_used=["artifact", "hybrid_search"],
        request_budget={
            "max_artifacts": 1,
            "max_source_reads": 12,
            "max_tokens_out": 2500,
        },
        budget_used={
            "artifacts_built": 1,
            "artifacts_read": 0,
            "source_reads": 3,
            "tokens_out_estimate": 128,
        },
    )

    assert receipt == {
        "strategy": "project_capsule",
        "methods_used": ["artifact", "hybrid_search"],
        "omissions": [],
        "budget": {
            "requested": {
                "max_artifacts": 1,
                "max_source_reads": 12,
                "max_tokens_out": 2500,
            },
            "used": {
                "artifacts_built": 1,
                "artifacts_read": 0,
                "source_reads": 3,
                "tokens_out_estimate": 128,
            },
        },
        "failure_receipts": [],
        "response_status": "ok",
    }
    assert validate_planner_receipt(receipt, response_status="ok") == []


def test_build_planner_receipt_records_omissions_and_failures():
    receipt = build_planner_receipt(
        strategy="project_capsule",
        methods_used=["artifact", "hybrid_search"],
        omissions=["focus:runtime edge cases"],
        failures=[
            {
                "code": "partial_capsule",
                "message": "Capsule is missing optional orientation fields.",
            }
        ],
        response_status="partial",
    )

    assert receipt["omissions"] == [
        {
            "code": "omitted",
            "message": "focus:runtime edge cases",
        }
    ]
    assert receipt["failure_receipts"] == [
        {
            "code": "partial_capsule",
            "category": "grounding",
            "message": "Capsule is missing optional orientation fields.",
            "recoverable": True,
        }
    ]
    assert validate_planner_receipt(receipt, response_status="partial") == []


def test_validate_planner_receipt_requires_failure_for_no_answer_and_unavailable():
    incomplete = build_planner_receipt(
        strategy="project_capsule",
        methods_used=["artifact"],
        response_status="no_answer",
    )

    assert validate_planner_receipt(incomplete, response_status="no_answer") == [
        "missing_failure_receipts"
    ]
