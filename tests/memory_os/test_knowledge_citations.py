from core.memory_os.knowledge_citations import (
    normalize_knowledge_citations,
    validate_knowledge_citation,
)


def test_normalize_chunk_citation_adds_required_envelope_fields():
    citations = normalize_knowledge_citations(
        [{"key": "engram_direction", "chunk_id": 0}],
        default_source="memory_os",
    )

    assert citations == [
        {
            "citation_id": "cit_001",
            "level": "chunk",
            "source": "memory_os",
            "key": "engram_direction",
            "chunk_id": 0,
        }
    ]


def test_validate_artifact_citation_requires_artifact_id_and_source():
    valid = {
        "citation_id": "artifact_001",
        "level": "artifact",
        "source": "memory_os",
        "artifact_id": "knowledge_artifact:abc",
    }
    invalid = {
        "citation_id": "artifact_001",
        "level": "artifact",
        "source": "memory_os",
    }

    assert validate_knowledge_citation(valid) == []
    assert validate_knowledge_citation(invalid) == ["missing_artifact_id"]


def test_validate_knowledge_pr_and_memory_ci_citations():
    citations = normalize_knowledge_citations(
        [
            {"knowledge_pr_id": "kpr:design"},
            {"ci_run_id": "mci:design", "knowledge_pr_id": "kpr:design"},
        ],
        default_source="memory_os",
    )

    assert citations == [
        {
            "citation_id": "cit_001",
            "level": "knowledge_pr",
            "source": "memory_os",
            "knowledge_pr_id": "kpr:design",
        },
        {
            "citation_id": "cit_002",
            "level": "memory_ci",
            "source": "memory_os",
            "ci_run_id": "mci:design",
            "knowledge_pr_id": "kpr:design",
        },
    ]
    assert validate_knowledge_citation(citations[0]) == []
    assert validate_knowledge_citation(citations[1]) == []
    assert validate_knowledge_citation(
        {"citation_id": "cit_bad", "level": "knowledge_pr", "source": "memory_os"}
    ) == ["missing_knowledge_pr_id"]
    assert validate_knowledge_citation(
        {"citation_id": "cit_bad", "level": "memory_ci", "source": "memory_os"}
    ) == ["missing_ci_run_id"]
