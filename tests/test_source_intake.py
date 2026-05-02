from __future__ import annotations


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
        domain="product-roadmap",
        budget_chars=6000,
    )

    assert draft["status"] == "draft"
    assert draft["source_hash"].startswith("sha256:")
    assert draft["receipt"]["input_chars"] == len(source_text)
    assert draft["receipt"]["proposed_memory_count"] >= 1
    assert draft["proposed_memories"][0]["status"] == "draft"
    assert "Decision" in draft["proposed_memories"][0]["content"]


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
