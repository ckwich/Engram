from core.memory_os.knowledge_eval import (
    DEFAULT_QUESTIONS,
    DEFAULT_WORKFLOW_SCENARIOS,
    run_knowledge_contract_eval,
    run_project_orientation_eval,
    seed_knowledge_contract_eval_fixtures,
)
from core.memory_os.runtime import MemoryOSRuntime
from core.vector_index import InMemoryVectorIndex


EXPECTED_STABLE_EKC_TASK_TYPES = {
    "project_orientation",
    "source_orientation",
    "document_orientation",
    "review_preparation",
    "evidence_audit",
    "graph_evidence",
    "entity_profile",
    "decision_packet",
    "implementation_context",
    "evidence_bundle",
}


def _embed(text):
    text = str(text).lower()
    if "architecture" in text or "runtime" in text:
        return [1.0, 0.0]
    return [0.0, 1.0]


class FakeRuntime:
    def __init__(self):
        self.search_calls = 0
        self.retrieve_calls = 0
        self.context_calls = 0
        self.knowledge_calls = 0

    def search_memories(self, query, **kwargs):
        self.search_calls += 1
        return {
            "count": 3,
            "results": [
                {
                    "key": "engram_direction",
                    "chunk_id": 0,
                    "snippet": "Engram is a local-first Memory OS.",
                    "citation": {"key": "engram_direction", "chunk_id": 0},
                },
                {
                    "key": "engram_constraints",
                    "chunk_id": 0,
                    "snippet": "Writes are explicit and reviewed.",
                    "citation": {"key": "engram_constraints", "chunk_id": 0},
                },
                {
                    "key": "engram_runtime",
                    "chunk_id": 0,
                    "snippet": "The daemon owns Memory OS state.",
                    "citation": {"key": "engram_runtime", "chunk_id": 0},
                },
            ],
            "error": None,
        }

    def retrieve_chunk(self, key, chunk_id):
        self.retrieve_calls += 1
        return {
            "key": key,
            "chunk_id": chunk_id,
            "text": "Retrieved orientation evidence.",
            "citation": {"key": key, "chunk_id": chunk_id},
        }

    def context_pack(self, query, **kwargs):
        self.context_calls += 1
        return {
            "context": {
                "chunks": [{"key": "engram_direction", "chunk_id": 0}],
                "citations": [{"key": "engram_direction", "chunk_id": 0}],
            }
        }

    def query_knowledge(self, request):
        self.knowledge_calls += 1
        task_type = request["ask"]["task_type"]
        return {
            "contract_version": "engram.knowledge.response.v0",
            "request_id": request.get("request_id") or f"req-{task_type}",
            "status": "ok",
            "answer": {
                "project": request["ask"]["project"],
                "summary": f"Stable EKC fixture for {task_type}.",
                "task_type": task_type,
            },
            "citations": [
                {
                    "citation_id": "cit_001",
                    "level": "chunk",
                    "source": "memory_os",
                    "key": f"{task_type}_fixture",
                    "chunk_id": 0,
                }
            ],
            "freshness": {"state": "fresh", "basis": "eval_fixture"},
            "policy": {
                "unreviewed_sources_used": False,
                "unsupported_inferences_used": False,
                "review_state_available": False,
                "review_filter_enforced": False,
                "review_state_basis": "not_available_in_current_memory_os_records",
            },
            "budget_used": {
                "artifacts_built": 1 if task_type == "project_orientation" else 0,
                "artifacts_read": 0,
                "source_reads": 1,
                "tokens_out_estimate": 64,
            },
            "planner": {
                "strategy": task_type,
                "methods_used": ["ledger_records"],
                "omissions": [],
                "budget": {
                    "requested": {
                        "max_artifacts": 1,
                        "max_source_reads": 12,
                        "max_tokens_out": 2500,
                    },
                    "used": {
                        "artifacts_built": 1 if task_type == "project_orientation" else 0,
                        "artifacts_read": 0,
                        "source_reads": 1,
                        "tokens_out_estimate": 64,
                    },
                },
                "failure_receipts": [],
                "response_status": "ok",
            },
            "errors": [],
        }


def test_project_orientation_eval_compares_search_only_to_ekc():
    runtime = FakeRuntime()
    human_ratings = {
        question: {"search_only": 4.0, "ekc": 4.0}
        for question in DEFAULT_QUESTIONS
    }

    report = run_project_orientation_eval(
        runtime,
        project="Engram",
        human_ratings=human_ratings,
    )

    assert report["schema_version"] == "2026-05-13.ekc-v0.eval.v1"
    assert report["project"] == "Engram"
    assert report["question_count"] == 5
    assert report["search_only"]["tool_calls"] == 25
    assert report["ekc"]["tool_calls"] == 5
    assert report["ekc"]["citation_presence_rate"] == 1.0
    assert report["continuation_threshold"]["tool_call_reduction_target"] == 0.3
    assert report["tool_call_reduction_rate"] >= 0.3
    assert report["human_usefulness"]["status"] == "scored"
    assert report["human_usefulness"]["preserved"] is True
    assert report["passes"] is True


def test_knowledge_contract_eval_covers_stable_1_0_workflows():
    runtime = FakeRuntime()
    human_ratings = {
        question: {"search_only": 4.0, "ekc": 4.0}
        for question in DEFAULT_QUESTIONS
    }

    report = run_knowledge_contract_eval(
        runtime,
        project="Engram",
        human_ratings=human_ratings,
    )

    task_types = {row["task_type"] for row in report["workflow_coverage"]["scenarios"]}
    assert report["schema_version"] == "2026-05-14.ekc-1.0.eval.v1"
    assert report["contract_release"] == "1.0"
    assert report["compatibility_contract_versions"] == {
        "request": "engram.knowledge.request.v0",
        "response": "engram.knowledge.response.v0",
    }
    assert report["stability"] == "stable"
    assert task_types == EXPECTED_STABLE_EKC_TASK_TYPES
    assert {scenario["scenario_id"] for scenario in DEFAULT_WORKFLOW_SCENARIOS} == EXPECTED_STABLE_EKC_TASK_TYPES
    assert report["workflow_coverage"]["scenario_count"] == len(DEFAULT_WORKFLOW_SCENARIOS)
    assert report["workflow_coverage"]["schema_valid_rate"] == 1.0
    assert report["workflow_coverage"]["citation_presence_rate"] == 1.0
    assert report["workflow_coverage"]["planner_strategy_match_rate"] == 1.0
    assert report["workflow_coverage"]["active_memory_write_free_rate"] == 1.0
    for row in report["workflow_coverage"]["scenarios"]:
        assert row["schema_valid"] is True
        assert row["planner_strategy"] == row["task_type"]
        assert row["active_memory_write_performed"] is False
        if row["status"] in {"ok", "partial"}:
            assert row["has_citation"] is True
    assert report["project_orientation"]["passes"] is True
    assert report["passes"] is True


def test_knowledge_contract_eval_runs_against_seeded_memory_os_runtime(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path,
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
    )
    runtime.initialize()
    seed_knowledge_contract_eval_fixtures(runtime, project="Engram")
    human_ratings = {
        question: {"search_only": 4.0, "ekc": 4.0}
        for question in DEFAULT_QUESTIONS
    }

    report = run_knowledge_contract_eval(
        runtime,
        project="Engram",
        human_ratings=human_ratings,
    )

    assert report["stability"] == "stable"
    assert report["passes"] is True
    assert report["workflow_coverage"]["scenario_count"] == len(DEFAULT_WORKFLOW_SCENARIOS)
    assert report["workflow_coverage"]["schema_valid_rate"] == 1.0
    assert report["workflow_coverage"]["citation_presence_rate"] == 1.0
    assert report["workflow_coverage"]["planner_strategy_match_rate"] == 1.0
    assert report["workflow_coverage"]["active_memory_write_free_rate"] == 1.0
