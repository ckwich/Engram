from __future__ import annotations

from core.graph_store import JsonGraphStore
from core.memory_os._records import list_records, read_record
from core.memory_os.runtime import MemoryOSRuntime
from core.vector_index import InMemoryVectorIndex


def _embed(text):
    return [1.0, 0.0] if "level" in str(text).lower() else [0.0, 1.0]


def _runtime(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path / "memory_os",
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
        graph_store=JsonGraphStore(tmp_path / "edges.json"),
    )
    runtime.initialize()
    return runtime


def test_store_memory_writes_metadata_graph_edges_without_agent_synthesis(tmp_path):
    runtime = _runtime(tmp_path)
    runtime.store_memory(
        key="design_skills_anchor",
        content="Design Skills anchor memory.",
        title="Design Skills Anchor",
        project="/Users/example/Projects/Design Skills",
        domain="game_design",
        status="active",
        canonical=True,
        force=True,
    )

    stored = runtime.store_memory(
        key="gmtk_level_transcript_summary",
        content=(
            "# GMTK Level Transcript Summary\n\n"
            "Level design transcripts discuss puzzle boxes, mission spaces, and world navigation."
        ),
        title="GMTK Level Transcript Summary",
        tags=["youtube-transcripts", "level-design"],
        related_to=["design_skills_anchor", "missing_memory_key"],
        project="/Users/example/Projects/Design Skills",
        domain="game_design",
        status="active",
        canonical=True,
        force=True,
    )

    treatment = stored["graph_treatment"]
    assert treatment["source"] == "memory_metadata_graph"
    assert treatment["graph_write_performed"] is True
    assert treatment["active_memory_write_performed"] is False
    assert treatment["missing_related_to"] == ["missing_memory_key"]

    edges = list_records(runtime.ledger, "graph_edges")
    assert "memory_metadata_graph" in {edge["source"] for edge in edges}
    target_refs = {(edge["edge_type"], edge["to_ref"].get("kind"), edge["to_ref"].get("id") or edge["to_ref"].get("key")) for edge in edges}
    assert ("contains", "chunk", "gmtk_level_transcript_summary:chunk:0") in target_refs
    assert (
        "applies_to",
        "entity",
        "entity:project:users-example-projects-design-skills",
    ) in target_refs
    assert ("mentions", "concept", "concept:domain:game-design") in target_refs
    assert ("mentions", "concept", "concept:tag:youtube-transcripts") in target_refs
    assert ("related_to", "memory", "design_skills_anchor") in target_refs

    concepts = {concept["concept_id"]: concept for concept in list_records(runtime.ledger, "concepts")}
    entities = {entity["entity_id"]: entity for entity in list_records(runtime.ledger, "entities")}
    assert concepts["concept:domain:game-design"]["source"] == "memory_metadata_graph"
    assert concepts["concept:tag:level-design"]["name"] == "level-design"
    assert entities["entity:project:users-example-projects-design-skills"]["entity_type"] == "project"


def test_store_memory_metadata_graphing_is_idempotent_for_same_memory(tmp_path):
    runtime = _runtime(tmp_path)
    kwargs = {
        "key": "repeat_memory",
        "content": "Repeat memory with stable metadata.",
        "title": "Repeat Memory",
        "tags": ["stable-tag"],
        "project": "Engram",
        "domain": "graph",
        "status": "active",
        "canonical": True,
        "force": True,
    }

    first = runtime.store_memory(**kwargs)
    edge_count = len(list_records(runtime.ledger, "graph_edges"))
    second = runtime.store_memory(**kwargs)

    assert edge_count > 0
    assert len(list_records(runtime.ledger, "graph_edges")) == edge_count
    assert set(second["graph_treatment"]["graph_edges_written"]) == set(first["graph_treatment"]["graph_edges_written"])


def test_store_memory_runs_semantic_graph_enrichment_job_with_cited_edges(tmp_path):
    runtime = _runtime(tmp_path)

    stored = runtime.store_memory(
        key="clockwork_mansion_notes",
        content=(
            "# Clockwork Mansion\n\n"
            "Mission space design uses systemic level design and affordance readability.\n\n"
            "## Puzzle Box Dungeons\n\n"
            "Puzzle box dungeons use lock and key structures for exploration pacing."
        ),
        title="Clockwork Mansion Notes",
        tags=["level-design"],
        project="Engram",
        domain="game_design",
        status="active",
        canonical=True,
        force=True,
    )

    treatment = stored["semantic_graph_treatment"]
    assert treatment["source"] == "memory_semantic_graph"
    assert treatment["job_kind"] == "memory_graph_enrichment"
    assert treatment["status"] == "succeeded"
    assert treatment["graph_write_performed"] is True
    assert treatment["active_memory_write_performed"] is False
    assert treatment["concepts_written"]
    assert treatment["graph_edges_written"]

    job = read_record(runtime.ledger, "jobs", treatment["job_id"])
    assert job is not None
    assert job["job_kind"] == "memory_graph_enrichment"
    assert job["status"] == "succeeded"
    assert job["payload"]["memory_key"] == "clockwork_mansion_notes"

    semantic_edges = [read_record(runtime.ledger, "graph_edges", edge_id) for edge_id in treatment["graph_edges_written"]]
    assert all(edge is not None for edge in semantic_edges)
    assert {edge["source"] for edge in semantic_edges} == {"memory_semantic_graph"}
    assert all(edge.get("evidence_refs") for edge in semantic_edges)
    assert any(edge["from_ref"].get("kind") == "memory" and edge["to_ref"].get("kind") == "concept" for edge in semantic_edges)
    assert any(edge["from_ref"].get("kind") == "chunk" and edge["to_ref"].get("kind") == "concept" for edge in semantic_edges)

    concept_refs = {
        edge["to_ref"].get("id")
        for edge in semantic_edges
        if edge["to_ref"].get("kind") == "concept"
    }
    assert "concept:semantic:mission-space-design" in concept_refs
    assert "concept:semantic:puzzle-box-dungeons" in concept_refs


def test_store_memory_semantic_graphing_is_idempotent_for_same_memory(tmp_path):
    runtime = _runtime(tmp_path)
    kwargs = {
        "key": "semantic_repeat_memory",
        "content": (
            "# Semantic Repeat Memory\n\n"
            "Signal charge cadence and combat draft telemetry explain reroll accounting."
        ),
        "title": "Semantic Repeat Memory",
        "tags": ["cadence"],
        "project": "Engram",
        "domain": "graph",
        "status": "active",
        "canonical": True,
        "force": True,
    }

    first = runtime.store_memory(**kwargs)
    semantic_edges = [
        edge
        for edge in list_records(runtime.ledger, "graph_edges")
        if edge.get("source") == "memory_semantic_graph"
    ]
    semantic_jobs = [
        job
        for job in list_records(runtime.ledger, "jobs")
        if job.get("job_kind") == "memory_graph_enrichment"
    ]
    second = runtime.store_memory(**kwargs)

    assert semantic_edges
    assert len(
        [
            edge
            for edge in list_records(runtime.ledger, "graph_edges")
            if edge.get("source") == "memory_semantic_graph"
        ]
    ) == len(semantic_edges)
    assert len(
        [
            job
            for job in list_records(runtime.ledger, "jobs")
            if job.get("job_kind") == "memory_graph_enrichment"
        ]
    ) == len(semantic_jobs) == 1
    assert second["semantic_graph_treatment"]["idempotent_replay"] is True
    assert set(second["semantic_graph_treatment"]["graph_edges_written"]) == set(
        first["semantic_graph_treatment"]["graph_edges_written"]
    )


def test_store_memory_semantic_graphing_supersedes_removed_edges_on_overwrite(tmp_path):
    runtime = _runtime(tmp_path)
    common = {
        "key": "semantic_overwrite_memory",
        "title": "Semantic Overwrite Memory",
        "project": "Engram",
        "domain": "graph",
        "status": "active",
        "canonical": True,
        "force": True,
    }

    first = runtime.store_memory(
        **common,
        content="# First Shape\n\nMission space design and affordance readability guide the original note.",
    )
    removed_edge_ids = [
        edge_id
        for edge_id in first["semantic_graph_treatment"]["graph_edges_written"]
        for edge in [read_record(runtime.ledger, "graph_edges", edge_id)]
        if edge and edge["to_ref"].get("id") == "concept:semantic:mission-space-design"
    ]

    second = runtime.store_memory(
        **common,
        content="# Second Shape\n\nEconomy sink tuning and reward pacing guide the revised note.",
    )

    assert removed_edge_ids
    assert set(removed_edge_ids).issubset(set(second["semantic_graph_treatment"]["graph_edges_deactivated"]))
    assert {
        read_record(runtime.ledger, "graph_edges", edge_id)["status"]
        for edge_id in removed_edge_ids
    } == {"superseded"}

    active_semantic_targets = {
        edge["to_ref"].get("id")
        for edge in list_records(runtime.ledger, "graph_edges")
        if edge.get("source") == "memory_semantic_graph"
        and edge.get("status") == "active"
        and (
            edge["from_ref"].get("key") == "semantic_overwrite_memory"
            or edge["from_ref"].get("memory_key") == "semantic_overwrite_memory"
        )
    }
    assert "concept:semantic:mission-space-design" not in active_semantic_targets
    assert "concept:semantic:economy-sink-tuning" in active_semantic_targets
