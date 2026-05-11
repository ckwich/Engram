from __future__ import annotations

from core.project_capsule import build_project_capsule_draft


def test_build_project_capsule_draft_uses_context_refs_and_quality_summary():
    context_packet = {
        "record_type": "context_packet",
        "task": "prepare project capsule",
        "project": "C:/Dev/Engram",
        "profile": {"id": "repo_resume"},
        "context": {
            "chunks": [
                {
                    "key": "engram_rebuild_plan",
                    "chunk_id": 0,
                    "title": "Engram rebuild plan",
                }
            ],
            "citations": [{"citation_id": "engram:engram_rebuild_plan#0"}],
            "omitted": [],
        },
        "warnings": [{"code": "stale_excluded", "message": "Stale excluded."}],
    }
    quality_payload = {
        "summary": {"low_risk_count": 4, "medium_risk_count": 1, "high_risk_count": 0},
        "issue_count": 2,
    }

    capsule = build_project_capsule_draft(
        project="C:/Dev/Engram",
        task="prepare project capsule",
        summary="Engram rebuild is focused on agent-facing Memory OS primitives.",
        must_read_keys=["engram_rebuild_plan"],
        context_packet=context_packet,
        quality_payload=quality_payload,
    )

    assert capsule["schema_version"] == "2026-05-11.project-capsule.v1"
    assert capsule["record_type"] == "project_capsule_draft"
    assert capsule["write_performed"] is False
    assert capsule["must_read"] == [
        {"key": "engram_rebuild_plan", "chunk_id": 0, "source": "context"},
        {"key": "engram_rebuild_plan", "source": "explicit"},
    ]
    assert capsule["quality_summary"]["medium_risk_count"] == 1
    assert capsule["warnings"][0]["code"] == "stale_excluded"
