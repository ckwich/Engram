from core.memory_os.entities import EntityRegistry
from core.memory_os.ledger import MemoryOSLedger


def test_aliases_resolve_to_canonical_entities_and_flag_low_confidence(tmp_path):
    registry = EntityRegistry(MemoryOSLedger(tmp_path / "engram.sqlite"))
    entity = registry.upsert_entity(
        canonical_name="Visual Hierarchy",
        entity_type="design_principle",
        aliases=[
            {"label": "VH", "confidence": 0.95},
            {"label": "visual order", "confidence": 0.55},
        ],
    )

    strong = registry.resolve("VH")
    weak = registry.resolve("visual order")

    assert strong["entity_id"] == entity["entity_id"]
    assert strong["canonical_name"] == "Visual Hierarchy"
    assert strong["low_confidence"] is False
    assert weak["entity_id"] == entity["entity_id"]
    assert weak["low_confidence"] is True


def test_entity_merge_and_split_preserve_history_and_labels(tmp_path):
    registry = EntityRegistry(MemoryOSLedger(tmp_path / "engram.sqlite"))
    primary = registry.upsert_entity("Visual Hierarchy", "design_principle", aliases=["hierarchy"])
    duplicate = registry.upsert_entity("Visual Order", "concept", aliases=["visual order"])

    merged = registry.merge_entities(primary["entity_id"], duplicate["entity_id"], created_by="agent")
    split = registry.split_entity(
        primary["entity_id"],
        alias_label="visual order",
        new_canonical_name="Visual Order",
        created_by="agent",
    )

    assert "Visual Order" in merged["source_labels"]
    assert merged["merge_history"][0]["merged_entity_id"] == duplicate["entity_id"]
    assert split["entity"]["canonical_name"] == "Visual Order"
    assert registry.resolve("visual order")["entity_id"] == split["entity"]["entity_id"]
    assert registry.get_entity(primary["entity_id"])["split_history"][0]["alias_label"] == "visual order"
