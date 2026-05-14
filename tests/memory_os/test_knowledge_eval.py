from core.memory_os.knowledge_eval import DEFAULT_QUESTIONS, run_project_orientation_eval


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
        return {
            "status": "ok",
            "answer": {"summary": "Engram is a local-first Memory OS."},
            "citations": [{"citation_id": "cit_001"}],
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
