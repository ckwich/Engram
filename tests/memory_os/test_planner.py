from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.planner import plan_retrieval, run_eval_pack


def test_retrieval_planner_selects_strategy_by_task_shape():
    semantic = plan_retrieval("What does visual hierarchy mean?", filters={}, budget_chars=4000)
    identifier = plan_retrieval("Find prepare_codebase_mapping usage", filters={}, budget_chars=4000)
    relationship = plan_retrieval("How does attention relate to visual hierarchy?", filters={}, budget_chars=4000)
    resume = plan_retrieval("Resume the Engram repo work", filters={"project": "Engram"}, budget_chars=4000)
    claim = plan_retrieval("Is this decision contradicted by newer evidence?", filters={}, budget_chars=4000)

    assert semantic["primary_strategy"] == "vector"
    assert identifier["primary_strategy"] == "hybrid"
    assert relationship["primary_strategy"] == "graph"
    assert resume["primary_strategy"] == "project_capsule"
    assert "contradiction_scan" in claim["supporting_strategies"]
    assert all(plan["budget_chars"] == 4000 for plan in [semantic, identifier, relationship, resume, claim])


def test_eval_pack_reports_missing_expected_design_book_evidence(tmp_path):
    pack = {
        "pack_id": "design-mini",
        "questions": [
            {
                "id": "visual-hierarchy",
                "question": "Which books discuss visual hierarchy?",
                "expected_refs": ["book_a:section_1", "book_b:figure_2"],
                "retrieved_refs": ["book_a:section_1"],
            }
        ],
    }

    report = run_eval_pack(pack, ledger=MemoryOSLedger(tmp_path / "engram.sqlite"))

    assert report["pack_id"] == "design-mini"
    assert report["status"] == "fail"
    assert report["questions"][0]["coverage_score"] == 0.5
    assert report["questions"][0]["missing_expected_refs"] == ["book_b:figure_2"]
