from __future__ import annotations

import pytest

from core.ingestion_pipelines import list_ingestion_pipelines


def test_ingestion_pipeline_catalog_exposes_no_write_lifecycle_policy():
    catalog = list_ingestion_pipelines()

    assert catalog["write_performed"] is False
    assert catalog["lifecycle_policy"] == {
        "prepared_memory_status": "draft",
        "auto_promote": False,
        "promotion_tool": "store_prepared_memory",
        "stale_retrieval_default": "exclude_stale_when_building_context",
    }


def test_prepare_source_memory_creates_reviewable_draft(isolated_source_drafts):
    manager = isolated_source_drafts.source_intake_manager
    source_text = """
    Title: Architecture meeting

    Decision: Keep JSON as source of truth.
    Action: Add graph edges as rebuildable control plane.
    Risk: Do not store raw transcripts as active memories.
    """

    draft = manager.prepare_source_memory(
        source_text=source_text,
        source_type="transcript",
        source_uri="C:/tmp/transcript.txt",
        project="C:/Dev/Engram",
        domain="project-notes",
        budget_chars=6000,
    )

    assert draft["status"] == "draft"
    assert draft["source_hash"].startswith("sha256:")
    assert draft["receipt"]["input_chars"] == len(source_text)
    assert draft["receipt"]["proposed_memory_count"] >= 1
    assert draft["proposed_memories"][0]["status"] == "draft"
    assert "Decision" in draft["proposed_memories"][0]["content"]


def test_prepare_source_memory_includes_review_and_promotion_contract(isolated_source_drafts):
    manager = isolated_source_drafts.source_intake_manager

    draft = manager.prepare_source_memory(
        source_text="Decision: Keep noisy collaboration comments app-owned until reviewed.",
        source_type="handoff",
        source_uri="file:///tmp/handoff.md",
        project="Engram",
        domain="source-intake",
        pipeline="handoff",
    )
    proposed = draft["proposed_memories"][0]
    destinations = {
        destination["kind"]: destination
        for destination in draft["promotion_guidance"]["allowed_destinations"]
    }

    assert draft["active_memory_write_performed"] is False
    assert draft["review_required"] is True
    assert draft["promotion_guidance"]["auto_promote"] is False
    assert destinations["memory"]["tool"] == "store_prepared_memory"
    assert destinations["graph_edge"]["tool"] == "add_graph_edge"
    assert destinations["app_record"]["owner"] == "collaboration_app"
    assert destinations["external_pointer"]["field"] == "source_uri"
    assert proposed["source_intake"] == {
        "draft_id": draft["draft_id"],
        "source_hash": draft["source_hash"],
        "source_type": "handoff",
        "source_uri": "file:///tmp/handoff.md",
        "pipeline": "handoff",
        "review_status": "draft",
        "promotion_required": True,
    }


def test_prepare_source_memory_uses_named_pipeline_sections(isolated_source_drafts):
    manager = isolated_source_drafts.source_intake_manager

    draft = manager.prepare_source_memory(
        source_text="""
        Question: Will graph traversal increase token use?
        Insight: Keep graph expansion opt-in and receipt-visible.
        Decision: Add token accounting before graph expansion defaults.
        """,
        source_type="transcript",
        pipeline="transcript",
    )

    content = draft["proposed_memories"][0]["content"]
    assert draft["pipeline"] == "transcript"
    assert draft["receipt"]["pipeline_stages"] == [
        "normalize_source_text",
        "extract_prefixed_lines",
        "preserve_open_questions",
        "compose_reviewable_draft",
    ]
    assert "## Questions" in content
    assert "Will graph traversal increase token use?" in content
    assert "## Insights" in content
    assert "Keep graph expansion opt-in" in content
    assert "transcript" in draft["proposed_memories"][0]["tags"]


def test_prepare_source_memory_rejects_invalid_agent_argument_shapes(isolated_source_drafts):
    manager = isolated_source_drafts.source_intake_manager

    invalid_cases = [
        {"source_text": {"bad": "shape"}, "source_type": "note"},
        {"source_text": "Decision: Capture note.", "source_type": {"bad": "shape"}},
        {"source_text": "Decision: Capture note.", "source_type": "note", "budget_chars": None},
        {"source_text": "Decision: Capture note.", "source_type": "note", "pipeline": {"bad": "shape"}},
    ]

    for kwargs in invalid_cases:
        with pytest.raises(ValueError):
            manager.prepare_source_memory(**kwargs)


def test_source_drafts_are_not_active_memories(isolated_source_drafts):
    manager = isolated_source_drafts.source_intake_manager
    draft = manager.prepare_source_memory(
        source_text="Decision: Keep drafts separate from active memory.",
        source_type="note",
    )

    drafts = manager.list_source_drafts(status="draft")

    assert drafts["count"] == 1
    assert drafts["drafts"][0]["draft_id"] == draft["draft_id"]


def test_discard_source_draft_marks_rejected(isolated_source_drafts):
    manager = isolated_source_drafts.source_intake_manager
    draft = manager.prepare_source_memory(
        source_text="Action: discard this draft",
        source_type="note",
    )

    result = manager.discard_source_draft(draft["draft_id"])

    assert result["discarded"] is True
    assert manager.get_source_draft(draft["draft_id"])["status"] == "rejected"
