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
        "workflow_check_count": 4,
        "workflow_failed": 0,
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
    assert report["workflow_checks"][0]["id"] == "agent_workflow_packets"
    assert report["workflow_checks"][0]["status"] == "pass"
    assert report["workflow_checks"][0]["artifacts"] == {
        "context_packet": "2026-05-11.context-packet.v1",
        "handoff_packet": "2026-05-11.handoff-packet.v1",
        "project_capsule": "2026-05-11.project-capsule.v1",
        "memory_quality": "2026-05-11.memory-quality.v1",
        "workflow_templates": {
            "schema_version": "2026-04-30.workflow-templates.v1",
            "template_ids": [
                "compile_task_context",
                "prepare_session_handoff",
                "prepare_project_capsule_review",
                "review_memory_health",
            ],
        },
    }
    document_ingestion_check = next(
        check for check in report["workflow_checks"] if check["id"] == "document_intelligence_ingestion"
    )
    assert document_ingestion_check["status"] == "pass"
    assert document_ingestion_check["required_methods"] == [
        "prepare_document_ingestion_plan",
        "run_document_ingestion",
        "inspect_document_ingestion",
    ]
    assert document_ingestion_check["readiness"]["after_run"]["searchable"] is True
    assert document_ingestion_check["readiness"]["after_run"]["structural_graph_covered"] is True
    assert document_ingestion_check["readiness"]["after_run"]["usable"] is False
    assert document_ingestion_check["active_memory_write_performed"] is False
    knowledge_pr_check = next(check for check in report["workflow_checks"] if check["id"] == "knowledge_pr_memory_ci_gate")
    assert knowledge_pr_check["status"] == "pass"
    assert knowledge_pr_check["required_methods"] == [
        "prepare_knowledge_branch",
        "prepare_knowledge_pr",
        "run_memory_ci",
        "merge_knowledge_pr",
        "prepare_document_coverage_pass",
    ]
    assert knowledge_pr_check["status_values"]["blocked_ci"] == "blocked"
    assert knowledge_pr_check["status_values"]["clean_ci"] == "passed"
    assert knowledge_pr_check["status_values"]["acceptance_check"] == "policy_denied"
    assert knowledge_pr_check["status_values"]["merge"] == "merged"
    assert knowledge_pr_check["coverage_pass"]["status"] == "partial"
    assert "coverage_adapter_unavailable" in knowledge_pr_check["coverage_pass"]["blocking_issue_codes"]
    assert knowledge_pr_check["coverage_pass"]["next_action"]["tool"] == "prepare_document_coverage_pass"
    assert knowledge_pr_check["merge_transaction_id"]
    book_gate_check = next(check for check in report["workflow_checks"] if check["id"] == "book_dismantling_gate")
    assert book_gate_check["status"] == "pass"
    assert book_gate_check["summary"]["fixture_count"] == 7
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
    assert report["summary"]["workflow_failed"] == 0
    scenario_report = report["scenarios"][0]
    assert scenario_report["expected_key_found"] is False
    assert scenario_report["expected_key_rank"] is None
    assert scenario_report["findings"] == [
        {
            "code": "expected_key_not_found",
            "message": "Expected memory _engram_eval_key_that_does_not_exist was not returned by search.",
        }
    ]


def test_agent_reliability_harness_seeds_and_cleans_distractor_memories(isolated_storage):
    from core.reliability_harness import AgentReliabilityScenario, run_agent_reliability_harness

    manager = isolated_storage["mm"].memory_manager
    scenario = AgentReliabilityScenario(
        scenario_id="freshness_preference",
        description="Expected fresh memory should be selected while a stale distractor is excluded.",
        key="_engram_eval_current_preference",
        content="## Current\n\nCurrent reviewed source-backed architecture decision.",
        query="current reviewed source-backed architecture decision",
        expected_key="_engram_eval_current_preference",
        title="Current Preference",
        tags=["agent-eval", "freshness"],
        project="C:/Dev/Engram",
        domain="agent-reliability",
        max_chunks=2,
        budget_chars=600,
        distractors=[
            {
                "key": "_engram_eval_stale_preference_distractor",
                "content": "## Stale\n\nCurrent reviewed source-backed architecture decision.",
                "title": "Stale Preference Distractor",
                "tags": ["agent-eval", "freshness"],
                "canonical": True,
                "potentially_stale": True,
                "stale_reason": "superseded during reliability eval",
            }
        ],
    )

    report = run_agent_reliability_harness(manager, scenarios=[scenario])

    assert report["summary"]["status"] == "pass"
    assert report["scenarios"][0]["search"]["top_keys"] == ["_engram_eval_current_preference"]
    assert manager.retrieve_memory("_engram_eval_current_preference") is None
    assert manager.retrieve_memory("_engram_eval_stale_preference_distractor") is None


def test_default_agent_reliability_scenarios_are_seeded_and_bounded():
    from core.reliability_harness import (
        EVAL_KEY_PREFIX,
        default_agent_reliability_scenarios,
    )

    scenarios = default_agent_reliability_scenarios()
    scenario_ids = {scenario.scenario_id for scenario in scenarios}

    assert {
        "retrieval_ladder_context_budget",
        "current_memory_excludes_stale_distractor",
        "reviewed_source_backed_metadata_preference",
    } <= scenario_ids
    for scenario in scenarios:
        assert scenario.key.startswith(EVAL_KEY_PREFIX)
        assert scenario.expected_key == scenario.key
        assert scenario.budget_chars <= 1500
        assert scenario.max_chunks <= 3
    freshness = next(
        scenario for scenario in scenarios if scenario.scenario_id == "current_memory_excludes_stale_distractor"
    )
    assert freshness.distractors[0]["potentially_stale"] is True
    source_backed = next(
        scenario for scenario in scenarios if scenario.scenario_id == "reviewed_source_backed_metadata_preference"
    )
    assert {"source-backed", "reviewed"} <= set(source_backed.tags)


def test_book_dismantling_gate_reports_missing_required_fixture():
    from core.reliability_harness import (
        default_book_dismantling_fixture_manifests,
        run_book_dismantling_gate,
    )

    fixtures = [
        fixture
        for fixture in default_book_dismantling_fixture_manifests()
        if fixture["fixture_id"] != "ocr_noise_page"
    ]

    report = run_book_dismantling_gate(fixtures)

    assert report["summary"]["status"] == "fail"
    assert report["summary"]["missing_required_count"] == 1
    assert report["missing_required_fixture_ids"] == ["ocr_noise_page"]


def test_document_intelligence_ingestion_check_exercises_runtime_methods():
    from core.reliability_harness import run_document_intelligence_ingestion_check

    report = run_document_intelligence_ingestion_check()

    assert report["id"] == "document_intelligence_ingestion"
    assert report["status"] == "pass"
    assert report["required_methods"] == [
        "prepare_document_ingestion_plan",
        "run_document_ingestion",
        "inspect_document_ingestion",
    ]
    assert report["methods_called"] == report["required_methods"]
    assert report["status_values"]["run"] in {"ok", "partial"}
    assert report["status_values"]["inspect"] in {"ok", "partial"}
    assert report["readiness"]["after_run"]["searchable"] is True
    assert report["readiness"]["after_run"]["structural_graph_covered"] is True
    assert report["readiness"]["after_run"]["usable"] is False
    assert report["write_flags"]["run"]["write_performed"] is True
    assert report["write_flags"]["run"]["active_memory_write_performed"] is False


def test_knowledge_pr_memory_ci_gate_exercises_review_and_merge_boundaries():
    from core.reliability_harness import run_knowledge_pr_memory_ci_gate

    report = run_knowledge_pr_memory_ci_gate()

    assert report["id"] == "knowledge_pr_memory_ci_gate"
    assert report["status"] == "pass"
    assert report["status_values"]["blocked_ci"] == "blocked"
    assert report["status_values"]["blocked_merge"] == "policy_denied"
    assert report["status_values"]["clean_ci"] == "passed"
    assert report["status_values"]["acceptance_check"] == "policy_denied"
    assert report["status_values"]["merge"] == "merged"
    assert report["status_values"]["inspect"] == "merged"
    assert report["write_flags"]["blocked_ci"]["active_memory_write_performed"] is False
    assert report["write_flags"]["clean_ci"]["active_memory_write_performed"] is False
    assert report["write_flags"]["acceptance_check"]["write_performed"] is False
    assert report["write_flags"]["merge"]["active_memory_write_performed"] is True
    assert report["write_flags"]["coverage_pass"]["active_memory_write_performed"] is False
    assert report["coverage_pass"]["status"] == "partial"
    assert "coverage_adapter_unavailable" in report["coverage_pass"]["blocking_issue_codes"]
