"""Inspectable retrieval planning and eval packs for Memory OS agents."""
from __future__ import annotations

from typing import Any

from core.memory_os.ledger import MemoryOSLedger


def plan_retrieval(task: str, *, filters: dict[str, Any], budget_chars: int) -> dict[str, Any]:
    """Choose an inspectable retrieval strategy for an agent task."""
    text = str(task or "").lower()
    strategies: list[str] = []
    if _looks_like_repo_resume(text):
        primary = "project_capsule"
        strategies.extend(["context_pack", "stale_check"])
    elif _looks_like_relationship(text):
        primary = "graph"
        strategies.extend(["vector", "evidence_chunks"])
    elif _looks_like_identifier_query(task):
        primary = "hybrid"
        strategies.extend(["full_text", "vector"])
    else:
        primary = "vector"
        strategies.extend(["context_pack"])

    if _looks_like_claim_or_decision(text):
        strategies.append("contradiction_scan")
    if budget_chars < 1500:
        strategies.append("snippet_first")

    supporting = _dedupe([strategy for strategy in strategies if strategy != primary])
    return {
        "schema_version": "2026-05-13.memory-os.retrieval-plan.v1",
        "task": task,
        "filters": dict(filters or {}),
        "budget_chars": int(budget_chars),
        "primary_strategy": primary,
        "supporting_strategies": supporting,
        "receipt": {
            "relationship_question": _looks_like_relationship(text),
            "identifier_query": _looks_like_identifier_query(task),
            "repo_resume": _looks_like_repo_resume(text),
            "claim_or_decision": _looks_like_claim_or_decision(text),
        },
    }


def run_eval_pack(pack: dict[str, Any], *, ledger: MemoryOSLedger) -> dict[str, Any]:
    """Run a deterministic expected-evidence coverage check for an eval pack."""
    ledger.initialize()
    questions = []
    failed = 0
    for question in pack.get("questions", []):
        expected = [str(ref) for ref in question.get("expected_refs", [])]
        retrieved = [str(ref) for ref in question.get("retrieved_refs", [])]
        missing = [ref for ref in expected if ref not in retrieved]
        coverage_score = 1.0 if not expected else (len(expected) - len(missing)) / len(expected)
        status = "pass" if not missing else "fail"
        if status == "fail":
            failed += 1
        questions.append(
            {
                "id": question.get("id"),
                "question": question.get("question"),
                "expected_ref_count": len(expected),
                "retrieved_ref_count": len(retrieved),
                "missing_expected_refs": missing,
                "coverage_score": coverage_score,
                "status": status,
            }
        )
    return {
        "schema_version": "2026-05-13.memory-os.eval-pack.v1",
        "pack_id": pack.get("pack_id"),
        "status": "pass" if failed == 0 else "fail",
        "question_count": len(questions),
        "failed": failed,
        "questions": questions,
    }


def _looks_like_repo_resume(text: str) -> bool:
    return "resume" in text and ("repo" in text or "project" in text or "work" in text)


def _looks_like_relationship(text: str) -> bool:
    return any(phrase in text for phrase in ("relate to", "relationship", "graph path", "connect"))


def _looks_like_claim_or_decision(text: str) -> bool:
    return any(word in text for word in ("claim", "decision", "contradict", "supersede", "conflict"))


def _looks_like_identifier_query(task: str) -> bool:
    tokens = str(task or "").split()
    return any("_" in token or "." in token or "::" in token for token in tokens)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
