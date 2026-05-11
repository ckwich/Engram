from __future__ import annotations

from core.context_compiler import build_handoff_packet, compile_context_packet, list_context_profiles


def test_list_context_profiles_exposes_agent_workflow_defaults():
    catalog = list_context_profiles()

    assert catalog["schema_version"] == "2026-05-11.context-profiles.v1"
    assert catalog["count"] >= 3
    assert catalog["profiles"]["repo_resume"]["max_chunks"] == 8
    assert catalog["profiles"]["repo_resume"]["use_graph"] is True
    assert "handoff" in catalog["profiles"]["repo_resume"]["query_terms"]


def test_compile_context_packet_preserves_receipts_and_review_warnings():
    context_payload = {
        "query": "resume Engram rebuild handoff next step",
        "count": 1,
        "chunks": [
            {
                "key": "engram_rebuild_checkpoint",
                "chunk_id": 0,
                "title": "Engram rebuild checkpoint",
                "text": "Continue with agent workflow context compiler.",
                "citation": {"citation_id": "engram:engram_rebuild_checkpoint#0"},
            }
        ],
        "citations": [{"citation_id": "engram:engram_rebuild_checkpoint#0"}],
        "omitted": [],
        "budget_chars": 4000,
        "used_chars": 46,
        "receipt": {
            "semantic_candidate_count": 3,
            "graph_candidate_count": 1,
            "selected_chunk_count": 1,
            "omitted_count": 0,
            "stale_policy": "excluded",
        },
        "error": None,
    }

    packet = compile_context_packet(
        task="resume Engram rebuild",
        profile_id="repo_resume",
        profile=list_context_profiles()["profiles"]["repo_resume"],
        context_payload=context_payload,
        project="C:/Dev/Engram",
        query="resume Engram rebuild handoff next step",
    )

    assert packet["schema_version"] == "2026-05-11.context-packet.v1"
    assert packet["record_type"] == "context_packet"
    assert packet["write_performed"] is False
    assert packet["profile"]["id"] == "repo_resume"
    assert packet["context"]["chunks"][0]["key"] == "engram_rebuild_checkpoint"
    assert packet["receipt"]["context_pack"]["semantic_candidate_count"] == 3
    assert packet["warnings"] == [
        {
            "code": "stale_excluded",
            "message": "Stale or superseded memories were excluded by default.",
        }
    ]
    assert packet["next_actions"][0]["tool"] == "retrieve_chunk"


def test_build_handoff_packet_turns_context_into_resume_artifact():
    context_packet = {
        "record_type": "context_packet",
        "task": "continue Engram rebuild",
        "project": "C:/Dev/Engram",
        "profile": {"id": "repo_resume"},
        "context": {
            "chunks": [
                {
                    "key": "engram_context_compiler",
                    "chunk_id": 0,
                    "title": "Context compiler",
                }
            ],
            "citations": [{"citation_id": "engram:engram_context_compiler#0"}],
            "omitted": [],
        },
        "warnings": [{"code": "stale_excluded", "message": "Stale memories excluded."}],
    }

    handoff = build_handoff_packet(
        task="continue Engram rebuild",
        project="C:/Dev/Engram",
        branch="codex/memory-os-migration-kernel",
        status="context compiler committed",
        next_steps=["add handoff generator", "run full validation"],
        validation=["pytest -q"],
        blockers=[],
        context_packet=context_packet,
    )

    assert handoff["schema_version"] == "2026-05-11.handoff-packet.v1"
    assert handoff["record_type"] == "handoff_packet"
    assert handoff["write_performed"] is False
    assert handoff["context_refs"] == [{"key": "engram_context_compiler", "chunk_id": 0}]
    assert handoff["citations"] == [{"citation_id": "engram:engram_context_compiler#0"}]
    assert "continue Engram rebuild" in handoff["resume_prompt"]
    assert handoff["next_steps"][0] == "add handoff generator"
