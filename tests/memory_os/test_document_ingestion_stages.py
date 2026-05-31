from __future__ import annotations

from tests.memory_os.test_document_ingestion import (
    _pdf,
    _review_packet_for_window,
    _runtime,
    _understanding_analysis,
)


def _stages(payload):
    return {stage["stage"]: stage for stage in payload["stage_report"]["stages"]}


def test_inspect_document_ingestion_reports_retryable_stage_plan(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="graph_coverage",
        page_window_size=2,
    )

    inspected = runtime.inspect_document_ingestion(ingestion_id=plan["ingestion_id"])

    assert inspected["stage_report"]["schema_version"] == "2026-05-21.document-ingestion-stages.v1"
    assert inspected["stage_report"]["next_stage"]["stage"] == "disassembly_artifacts"
    assert inspected["retryable_stages"][0]["retry_action"]["tool"] == "run_document_ingestion"
    assert _stages(inspected)["retrieval_index"]["complete"] is False


def test_document_ingestion_stage_report_tracks_semantic_resume_boundary(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="graph_coverage",
        page_window_size=2,
        analysis_policy="connected_agent",
    )
    windows = [_review_packet_for_window(source, start=1, end=2, has_more=False)]

    structural = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=windows,
    )
    structural_stages = _stages(structural)

    assert structural_stages["disassembly_artifacts"]["complete"] is True
    assert structural_stages["retrieval_index"]["complete"] is True
    assert structural_stages["structural_graph"]["complete"] is True
    assert structural_stages["understanding"]["complete"] is False
    assert structural_stages["understanding"]["retry_action"]["tool"] == "resume_document_ingestion"
    assert structural_stages["semantic_promotion"]["complete"] is False

    semantic = runtime.resume_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=windows,
        understanding_analysis=_understanding_analysis(),
    )
    semantic_stages = _stages(semantic)

    assert semantic_stages["understanding"]["complete"] is True
    assert semantic_stages["semantic_promotion"]["complete"] is True
    assert semantic_stages["completion"]["complete"] is False
    assert semantic_stages["completion"]["retry_action"]["tool"] == "complete_document_ingestion"
