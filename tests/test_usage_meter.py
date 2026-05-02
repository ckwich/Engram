from __future__ import annotations

import json
from pathlib import Path


def test_usage_paths_are_project_relative():
    import core.usage_meter as usage_meter_module

    project_root = Path(usage_meter_module.__file__).resolve().parents[1]

    assert usage_meter_module.USAGE_DIR == project_root / "data" / "usage"
    assert usage_meter_module.TOOL_CALLS_PATH == usage_meter_module.USAGE_DIR / "tool_calls.jsonl"


def test_estimate_tokens_uses_chars_div_4(isolated_usage_meter):
    meter_module = isolated_usage_meter

    assert meter_module.estimate_tokens("") == 0
    assert meter_module.estimate_tokens("abcdefgh") == 2
    assert meter_module.estimate_tokens({"query": "agent memory"}) >= 4


def test_record_tool_call_redacts_content_but_tracks_cost(isolated_usage_meter):
    meter = isolated_usage_meter.usage_meter

    event = meter.record_tool_call(
        tool="context_pack",
        input_payload={"query": "agent memory", "content": "secret raw body"},
        output_payload={
            "chunks": [{"key": "engram_plan", "chunk_id": 0, "text": "retrieved context body"}],
            "receipt": {"budget_chars": 6000, "used_chars": 24},
        },
        status="ok",
        duration_ms=12,
    )

    serialized = json.dumps(event)
    assert event["tool"] == "context_pack"
    assert event["estimate_method"] == "chars_div_4"
    assert event["retrieved_text_tokens"] > 0
    assert event["memory_refs"] == [{"key": "engram_plan", "chunk_id": 0}]
    assert "secret raw body" not in serialized
    assert "retrieved context body" not in serialized


def test_record_tool_call_treats_non_dict_receipt_as_empty(isolated_usage_meter):
    meter = isolated_usage_meter.usage_meter

    event = meter.record_tool_call(
        tool="context_pack",
        input_payload={"query": "agent memory"},
        output_payload={"chunks": [], "receipt": None},
        status="ok",
        duration_ms=3,
    )

    assert event["budget_chars"] is None
    assert event["used_chars"] is None


def test_usage_summary_reports_averages_and_outliers(isolated_usage_meter):
    meter = isolated_usage_meter.usage_meter

    meter.record_tool_call(
        tool="retrieve_memory",
        input_payload={"key": "large_memory"},
        output_payload={"key": "large_memory", "content": "x" * 9000},
        status="ok",
        duration_ms=20,
    )
    meter.record_tool_call(
        tool="search_memories",
        input_payload={"query": "small"},
        output_payload=[{"key": "small", "snippet": "tiny"}],
        status="ok",
        duration_ms=5,
    )

    summary = meter.get_summary(days=7)

    assert summary["total_calls"] == 2
    assert summary["total_response_tokens"] > summary["total_input_tokens"]
    assert summary["by_tool"]["retrieve_memory"]["call_count"] == 1
    assert summary["warnings"][0]["kind"] == "high_response_tokens"
