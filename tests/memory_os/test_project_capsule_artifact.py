from core.memory_os.project_capsule_artifact import build_project_capsule_artifact


def test_project_capsule_artifact_wraps_existing_project_capsule_draft():
    context_packet = {
        "profile": {"id": "project_capsule"},
        "context": {
            "chunks": [
                {
                    "key": "engram_direction",
                    "chunk_id": 0,
                    "text": "# Summary\n\nEngram is a local-first Memory OS.",
                    "score": 0.91,
                },
                {
                    "key": "engram_constraints",
                    "chunk_id": 0,
                    "text": "# Constraints\n\nWrites must remain explicit and reviewed.",
                    "score": 0.84,
                },
            ],
            "citations": [
                {"key": "engram_direction", "chunk_id": 0, "source": "memory_os"},
                {"key": "engram_constraints", "chunk_id": 0, "source": "memory_os"},
            ],
        },
        "warnings": [],
    }

    artifact = build_project_capsule_artifact(
        project="Engram",
        goal="Get current project context.",
        focus=["Memory OS"],
        context_packet=context_packet,
        quality_payload={"summary": {}, "issue_count": 0},
        source_snapshot_id="memory_os:test",
    )

    assert artifact["artifact_type"] == "project_capsule"
    assert artifact["adapter_basis"] == "core.project_capsule.build_project_capsule_draft"
    assert artifact["project"] == "Engram"
    assert artifact["summary"] == "Engram is a local-first Memory OS."
    assert artifact["constraints"] == ["Writes must remain explicit and reviewed."]
    assert artifact["source_refs"] == [
        {
            "key": "engram_direction",
            "chunk_id": 0,
            "citation_id": "cit_001",
            "score": 0.91,
        },
        {
            "key": "engram_constraints",
            "chunk_id": 0,
            "citation_id": "cit_002",
            "score": 0.84,
        },
    ]
    assert artifact["citations"][0]["level"] == "chunk"
    assert artifact["draft"]["record_type"] == "project_capsule_draft"


def test_project_capsule_artifact_returns_partial_when_sources_are_empty():
    artifact = build_project_capsule_artifact(
        project="Engram",
        goal="Get current project context.",
        focus=[],
        context_packet={"context": {"chunks": [], "citations": []}},
        quality_payload={"summary": {}, "issue_count": 0},
        source_snapshot_id="memory_os:test",
    )

    assert artifact["staleness"]["state"] == "partial"
    assert artifact["summary"] == ""
    assert artifact["source_refs"] == []
