"""Canonical Memory OS schema constants."""
from __future__ import annotations

SCHEMA_VERSION = "2026-05-13.memory-os.v1"

TABLES = (
    "sources",
    "documents",
    "sections",
    "chunks",
    "drafts",
    "memories",
    "entities",
    "concepts",
    "aliases",
    "graph_edges",
    "transactions",
    "retrieval_receipts",
    "jobs",
    "job_events",
    "snapshots",
    "firewall_events",
    "eval_packs",
    "skill_packs",
)

TRUTH_TYPES = (
    "observation",
    "user_preference",
    "decision",
    "claim",
    "summary",
    "inference",
    "procedure",
    "artifact",
)

GRAPH_EDGE_TYPES = (
    "related_to",
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
    "supersedes",
    "derived_from",
    "mentions",
)
