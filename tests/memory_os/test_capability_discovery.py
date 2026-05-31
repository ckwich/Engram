import json

from core.graph_store import JsonGraphStore
from core.memory_os.capability_discovery import (
    MIN_CAPABILITY_DISCOVERY_BUDGET_CHARS,
    build_capability_catalog,
)
from core.memory_os.runtime import MemoryOSRuntime
from core.vector_index import InMemoryVectorIndex


def _runtime(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path / "memory_os",
        embed_text=lambda text: [0.1, 0.2],
        vector_index=InMemoryVectorIndex(),
        graph_store=JsonGraphStore(tmp_path / "edges.json"),
    )
    runtime.initialize(rebuild_retrieval=False)
    return runtime


def test_capability_catalog_is_read_only_and_budgeted(tmp_path):
    runtime = _runtime(tmp_path)

    catalog = build_capability_catalog(
        runtime,
        query="document graph memory sync",
        budget_chars=2000,
    )

    assert catalog["schema_version"] == "2026-05-26.capability-discovery.v1"
    assert catalog["write_performed"] is False
    assert catalog["budget"]["budget_chars"] == 2000
    assert catalog["budget"]["used_chars"] <= 2000
    assert "memory" in catalog["capability_groups"]
    assert "document_intelligence" in catalog["capability_groups"]
    assert "graph" in catalog["capability_groups"]
    assert "knowledge_prs" in catalog["capability_groups"]
    assert "sync" in catalog["capability_groups"]
    assert "benchmarks" in catalog["capability_groups"]


def test_capability_catalog_truncates_without_private_payloads(tmp_path):
    runtime = _runtime(tmp_path)

    for budget in (500, 300, 250, 200, 100, 1):
        catalog = build_capability_catalog(
            runtime,
            query="PRIVATE_SOURCE_TEXT should be hashed away",
            budget_chars=budget,
        )
        effective_budget = max(budget, MIN_CAPABILITY_DISCOVERY_BUDGET_CHARS)

        assert catalog["write_performed"] is False
        assert catalog["budget"]["truncated"] is True
        assert catalog["budget"]["budget_chars"] == effective_budget
        assert catalog["budget"]["used_chars"] <= effective_budget
        assert len(json.dumps(catalog, ensure_ascii=False, sort_keys=True)) <= effective_budget
        rendered = str(catalog)
        assert "PRIVATE_SOURCE_TEXT" not in rendered
        assert "private_sync_key" not in rendered
        assert "raw_benchmark_payload" not in rendered


def test_runtime_and_inspector_expose_capability_discovery(tmp_path):
    runtime = _runtime(tmp_path)

    catalog = runtime.discover_memory_capabilities(query="sync", budget_chars=2000)
    inspector = runtime.inspector(limit=5)

    assert catalog["write_performed"] is False
    assert catalog["capability_groups"]["sync"]["tools"]
    assert inspector["capability_discovery"]["write_performed"] is False
    assert inspector["capability_discovery"]["runtime"]["retrieval"]["state"]["ready"] is False
    assert any(
        warning["code"] == "sync_not_configured"
        for warning in inspector["capability_discovery"]["warnings"]
    )
