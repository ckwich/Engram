from __future__ import annotations

from typing import Any

from core.reliability_harness import run_agent_reliability_harness

RETRIEVAL_EVAL_SCHEMA_VERSION = "2026-04-30.retrieval-eval.v1"


def run_retrieval_eval(memory_manager: Any) -> dict[str, Any]:
    """Run the deterministic retrieval harness behind an agent/WebUI friendly shape."""
    report = run_agent_reliability_harness(memory_manager)
    return {
        "schema_version": RETRIEVAL_EVAL_SCHEMA_VERSION,
        "summary": report.get("summary", {}),
        "scenarios": report.get("scenarios", []),
        "warnings": report.get("warnings", []),
        "source_schema_version": report.get("schema_version"),
        "generated_at": report.get("generated_at"),
        "error": None,
    }
