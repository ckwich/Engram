from __future__ import annotations

from core.retrieval_eval import run_retrieval_eval


def test_run_retrieval_eval_preserves_workflow_checks(isolated_storage):
    payload = run_retrieval_eval(isolated_storage["mm"].memory_manager)

    assert payload["schema_version"] == "2026-04-30.retrieval-eval.v1"
    assert payload["summary"]["workflow_check_count"] == 2
    assert payload["workflow_checks"][0]["id"] == "agent_workflow_packets"
    assert payload["workflow_checks"][0]["status"] == "pass"
    assert payload["workflow_checks"][1]["id"] == "book_dismantling_gate"
    assert payload["workflow_checks"][1]["status"] == "pass"
    assert payload["error"] is None
