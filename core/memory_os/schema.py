"""Canonical Memory OS schema constants."""
from __future__ import annotations

SCHEMA_VERSION = "2026-05-14.memory-os.v1"

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
    "knowledge_artifacts",
    "knowledge_branches",
    "knowledge_prs",
    "memory_ci_runs",
    "jobs",
    "job_events",
    "snapshots",
    "firewall_events",
    "eval_packs",
    "skill_packs",
    "memory_type_receipts",
    "activation_receipts",
    "capability_catalogs",
    "memory_guardrail_receipts",
    "benchmark_runs",
    "sync_devices",
    "sync_cursors",
    "sync_changesets",
    "sync_conflicts",
    "sync_inbox",
    "sync_transport_receipts",
)

MEMORY_TYPES = (
    "fact",
    "decision",
    "procedure",
    "source_evidence",
    "project_state",
    "preference",
    "open_loop",
    "handoff",
    "document_claim",
    "benchmark_result",
)

MEMORY_SCOPES = (
    "global",
    "user",
    "device",
    "project",
    "source",
    "document",
    "workspace",
)

TRUST_STATES = (
    "unreviewed",
    "reviewed",
    "source_backed",
    "conflicted",
    "superseded",
    "quarantined",
)

RETENTION_POLICIES = (
    "standard",
    "pinned",
    "ephemeral",
    "local_only",
)

SYNC_POLICIES = (
    "sync",
    "local_only",
    "quarantined",
)

SYNC_ELIGIBLE_TABLES = (
    "sources",
    "documents",
    "sections",
    "chunks",
    "memories",
    "entities",
    "concepts",
    "aliases",
    "graph_edges",
    "retrieval_receipts",
    "knowledge_artifacts",
    "memory_ci_runs",
    "eval_packs",
    "skill_packs",
)

SYNC_CONDITIONAL_TABLES = (
    "drafts",
)

SYNC_LOCAL_ONLY_TABLES = (
    "jobs",
    "job_events",
    "snapshots",
    "firewall_events",
    "knowledge_branches",
    "knowledge_prs",
    "sync_devices",
    "sync_cursors",
    "sync_changesets",
    "sync_conflicts",
    "sync_inbox",
    "sync_transport_receipts",
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
    "contains",
    "defines",
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
