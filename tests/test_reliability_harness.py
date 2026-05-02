from __future__ import annotations


def test_agent_reliability_harness_reports_pass_for_expected_retrieval(isolated_storage):
    from core.reliability_harness import (
        SCHEMA_VERSION,
        AgentReliabilityScenario,
        run_agent_reliability_harness,
    )

    manager = isolated_storage["mm"].memory_manager
    scenario = AgentReliabilityScenario(
        scenario_id="context_budget_smoke",
        description="Expected memory should appear in search and fit within the context budget.",
        key="_engram_eval_context_budget_smoke",
        content=(
            "## Agent Reliability Harness\n\n"
            "This calibration memory checks agent reliability harness context budget "
            "retrieval behavior with a compact chunk."
        ),
        query="agent reliability harness context budget retrieval behavior",
        expected_key="_engram_eval_context_budget_smoke",
        title="Agent Reliability Harness Smoke",
        tags=["agent-eval", "reliability"],
        project="C:/Dev/Engram",
        domain="agent-reliability",
        max_chunks=2,
        budget_chars=600,
    )

    report = run_agent_reliability_harness(manager, scenarios=[scenario])

    assert report["schema_version"] == SCHEMA_VERSION
    assert report["summary"] == {
        "status": "pass",
        "scenario_count": 1,
        "passed": 1,
        "failed": 0,
    }

    scenario_report = report["scenarios"][0]
    assert scenario_report["id"] == "context_budget_smoke"
    assert scenario_report["status"] == "pass"
    assert scenario_report["expected_key_found"] is True
    assert scenario_report["expected_key_rank"] == 1
    assert scenario_report["context_pack"]["selected_chunk_count"] >= 1
    assert scenario_report["context_pack"]["used_chars"] <= 600
    assert scenario_report["token_estimates"]["search_response_tokens"] > 0
    assert scenario_report["token_estimates"]["estimate_method"] == "chars_div_4"
    assert manager.retrieve_memory("_engram_eval_context_budget_smoke") is None


def test_agent_reliability_harness_reports_findings_for_missing_expected_key(isolated_storage):
    from core.reliability_harness import AgentReliabilityScenario, run_agent_reliability_harness

    manager = isolated_storage["mm"].memory_manager
    scenario = AgentReliabilityScenario(
        scenario_id="missing_expected",
        description="Missing expected key should produce a compact actionable finding.",
        key="_engram_eval_missing_expected_seed",
        content="## Seed\n\nThis memory is intentionally not the expected result.",
        query="nonexistent expected key reliability check",
        expected_key="_engram_eval_key_that_does_not_exist",
        title="Missing Expected Seed",
        tags=["agent-eval", "reliability"],
        project="C:/Dev/Engram",
        domain="agent-reliability",
        max_chunks=2,
        budget_chars=600,
    )

    report = run_agent_reliability_harness(manager, scenarios=[scenario])

    assert report["summary"]["status"] == "fail"
    assert report["summary"]["failed"] == 1
    scenario_report = report["scenarios"][0]
    assert scenario_report["expected_key_found"] is False
    assert scenario_report["expected_key_rank"] is None
    assert scenario_report["findings"] == [
        {
            "code": "expected_key_not_found",
            "message": "Expected memory _engram_eval_key_that_does_not_exist was not returned by search.",
        }
    ]


def test_default_agent_reliability_scenarios_are_seeded_and_bounded():
    from core.reliability_harness import (
        EVAL_KEY_PREFIX,
        default_agent_reliability_scenarios,
    )

    scenarios = default_agent_reliability_scenarios()

    assert len(scenarios) >= 1
    for scenario in scenarios:
        assert scenario.key.startswith(EVAL_KEY_PREFIX)
        assert scenario.expected_key == scenario.key
        assert scenario.budget_chars <= 1500
        assert scenario.max_chunks <= 3
