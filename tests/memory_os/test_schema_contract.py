from core.memory_os import schema


def test_schema_declares_required_core_tables():
    assert {
        "sources",
        "documents",
        "sections",
        "chunks",
        "drafts",
        "memories",
        "entities",
        "concepts",
        "graph_edges",
        "transactions",
        "retrieval_receipts",
        "jobs",
        "snapshots",
        "firewall_events",
    }.issubset(set(schema.TABLES))


def test_truth_types_match_rebuild_spec():
    assert schema.TRUTH_TYPES == (
        "observation",
        "user_preference",
        "decision",
        "claim",
        "summary",
        "inference",
        "procedure",
        "artifact",
    )


def test_cross_document_edge_types_are_available():
    assert {
        "same_as",
        "similar_to",
        "extends",
        "refines",
        "supports",
        "contradicts",
        "applies_to",
        "example_of",
        "anti_pattern_of",
        "synthesizes",
        "cites",
        "illustrates",
    }.issubset(set(schema.GRAPH_EDGE_TYPES))
