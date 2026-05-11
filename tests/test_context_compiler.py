from __future__ import annotations

from core.context_compiler import compile_context_packet, list_context_profiles


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
