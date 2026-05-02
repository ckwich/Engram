from __future__ import annotations


def test_preview_memory_chunks_returns_reviewable_boundaries_without_writes():
    from core.chunk_preview import preview_memory_chunks

    payload = preview_memory_chunks(
        "# Design Notes\n\nIntro paragraph.\n\n## Combat Loop\n\nDecision: Keep loot tense.",
        title="Example Game Design",
    )

    assert payload["title"] == "Example Game Design"
    assert payload["chunk_count"] >= 2
    assert payload["chunks"][0]["chunk_id"] == 0
    assert payload["chunks"][0]["char_count"] > 0
    assert "text" in payload["chunks"][0]
    assert payload["receipt"]["write_performed"] is False


def test_preview_memory_chunks_caps_large_previews_without_writes():
    from core.chunk_preview import preview_memory_chunks

    payload = preview_memory_chunks(
        "\n\n".join(f"Paragraph {index}" for index in range(40)),
        max_size=100,
        max_chunks=2,
    )

    assert payload["chunk_count"] == 2
    assert payload["receipt"]["omitted_chunks"] > 0
    assert payload["receipt"]["write_performed"] is False


def test_ingestion_pipeline_catalog_exposes_agent_safe_presets():
    from core.ingestion_pipelines import list_ingestion_pipelines, resolve_ingestion_pipeline

    catalog = list_ingestion_pipelines()

    assert "transcript" in catalog["pipelines"]
    assert "code_scan" in catalog["pipelines"]
    transcript = resolve_ingestion_pipeline("transcript")
    assert transcript["memory_status"] == "draft"
    assert "decision" in transcript["extract_prefixes"]


def test_local_source_connector_preview_is_bounded_and_reviewable(tmp_path):
    from core.source_connectors import preview_source_connector

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "design.md").write_text("# Design\n\nDecision: Add weather hazards.", encoding="utf-8")
    (docs / "notes.txt").write_text("Action: Review combat map.", encoding="utf-8")

    payload = preview_source_connector(
        connector_type="local_path",
        target=str(docs),
        include_globs=["*.md", "*.txt"],
        max_files=5,
    )

    assert payload["connector_type"] == "local_path"
    assert payload["write_performed"] is False
    assert payload["count"] == 2
    assert payload["items"][0]["draft_arguments"]["source_type"] == "local_path"
    assert payload["items"][0]["draft_arguments"]["source_uri"].startswith("file:")


def test_local_source_connector_preview_truncates_large_draft_text(tmp_path):
    from core.source_connectors import preview_source_connector

    source = tmp_path / "long.md"
    source.write_text("A" * 2000, encoding="utf-8")

    payload = preview_source_connector(
        connector_type="local_path",
        target=str(source),
        max_source_text_chars=100,
    )

    item = payload["items"][0]
    assert item["chars"] == 2000
    assert item["truncated"] is True
    assert len(item["draft_arguments"]["source_text"]) == 100
    assert payload["receipt"]["max_source_text_chars"] == 100


def test_workflow_templates_are_agent_facing_and_actionable():
    from core.workflow_templates import list_workflow_templates

    payload = list_workflow_templates()
    template_ids = {template["id"] for template in payload["templates"]}

    assert "resume_repo" in template_ids
    assert "extract_decisions_from_source" in template_ids
    resume = next(template for template in payload["templates"] if template["id"] == "resume_repo")
    assert resume["recommended_tools"][0] == "memory_protocol"
    assert any("context_pack" in step for step in resume["steps"])
