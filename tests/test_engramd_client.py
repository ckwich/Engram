from __future__ import annotations

import ast
import json
import inspect
from pathlib import Path
import re
import subprocess
import sys

import pytest

from core.engramd_client import DEFAULT_DAEMON_TIMEOUT, EngramDaemonClient, EngramDaemonClientError
from core.mcp.tool_registry import (
    DAEMON_ROUTES,
    THIN_CLIENT_CANONICAL_TOOLS,
    TOOL_ALIASES,
    concurrent_daemon_route_paths,
    expected_thin_mcp_tools,
    full_server_daemon_routed_tools,
    validate_daemon_route_registry,
    validate_mcp_tool_surface,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _decorated_mcp_tools(path: str) -> set[str]:
    tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
    tools: set[str] = set()
    for node in tree.body:
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "tool"
            ):
                tools.add(node.name)
    return tools


class FakeTransport:
    def __init__(self):
        self.calls = []

    def request_json(self, method, url, payload=None, timeout=DEFAULT_DAEMON_TIMEOUT, headers=None):
        self.calls.append((method, url, payload, timeout, headers or {}))
        return {"ok": True, "url": url, "payload": payload}


def test_client_posts_search_to_v1_endpoint():
    transport = FakeTransport()
    client = EngramDaemonClient("http://127.0.0.1:8765/", transport=transport)

    result = client.search_memories({"query": "agent memory"})

    assert result["ok"] is True
    assert transport.calls == [
        (
            "POST",
            "http://127.0.0.1:8765/v1/search_memories",
            {"query": "agent memory"},
            DEFAULT_DAEMON_TIMEOUT,
            {},
        )
    ]


def test_daemon_route_registry_covers_client_api_and_thin_tools():
    client_methods = {
        name
        for name, member in inspect.getmembers(EngramDaemonClient, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    thin_tools = set(THIN_CLIENT_CANONICAL_TOOLS)

    assert validate_daemon_route_registry(
        client_methods=client_methods,
        thin_client_tools=thin_tools,
    ) == []


def test_daemon_route_registry_covers_daemon_api_dispatch():
    api_source = (REPO_ROOT / "core" / "engramd_api.py").read_text(encoding="utf-8")
    api_paths = set(re.findall(r'route == "([^"]+)"', api_source))
    api_paths.add("/health")

    assert validate_daemon_route_registry(api_paths=api_paths) == []


def test_daemon_concurrent_routes_are_registry_backed():
    from core.engramd_api import _CONCURRENT_READ_ROUTES

    assert _CONCURRENT_READ_ROUTES == frozenset(concurrent_daemon_route_paths())
    assert "/v1/store_memory" not in _CONCURRENT_READ_ROUTES


def test_full_server_daemon_routed_tools_are_route_backed():
    routed = full_server_daemon_routed_tools()
    aliases = set(TOOL_ALIASES)

    assert len(routed) == len(set(routed))
    assert "health" not in routed
    assert "memory_os_inspector" not in routed
    assert "search_memories" in routed
    assert "write_memory" in routed

    for name in routed:
        if name in aliases:
            assert TOOL_ALIASES[name] in routed
        else:
            assert name in DAEMON_ROUTES


def test_thin_mcp_decorated_tool_surface_matches_registry():
    actual_tools = _decorated_mcp_tools("server_daemon_client.py")

    assert validate_mcp_tool_surface(actual_tools, thin_client=True) == []
    assert {"find_memories", "read_chunk", "read_memory", "write_memory"}.issubset(actual_tools)
    assert expected_thin_mcp_tools().issubset(actual_tools)


def test_full_mcp_decorated_tool_surface_matches_registry():
    actual_tools = _decorated_mcp_tools("server.py")

    assert validate_mcp_tool_surface(actual_tools, thin_client=False) == []


def test_thin_memory_protocol_advertises_all_route_backed_tools():
    import server_daemon_client

    protocol = server_daemon_client.memory_protocol()
    advertised = set(protocol["canonical_tools"])
    advertised.update(protocol["aliases"])
    for group in protocol["tool_groups"].values():
        advertised.update(group.get("tools") or [])

    missing = sorted(_decorated_mcp_tools("server_daemon_client.py") - advertised)

    assert missing == []


def test_client_gets_health_endpoint():
    transport = FakeTransport()
    client = EngramDaemonClient("http://127.0.0.1:8765", timeout=3.5, transport=transport)

    client.health()

    assert transport.calls == [
        ("GET", "http://127.0.0.1:8765/health", None, 3.5, {})
    ]


def test_client_attaches_configured_headers_to_requests():
    transport = FakeTransport()
    client = EngramDaemonClient(
        "http://engram-hub.tailnet-name.ts.net:8767",
        headers={"Authorization": "Bearer " + "x" * 40},
        transport=transport,
    )

    client.health()

    assert transport.calls == [
        (
            "GET",
            "http://engram-hub.tailnet-name.ts.net:8767/health",
            None,
            DEFAULT_DAEMON_TIMEOUT,
            {"Authorization": "Bearer " + "x" * 40},
        )
    ]


def test_client_rejects_remote_raw_daemon_url_without_auth_or_opt_in(monkeypatch):
    monkeypatch.delenv("ENGRAM_DAEMON_REMOTE_URL_ACK", raising=False)

    with pytest.raises(EngramDaemonClientError, match="daemon_url_remote_requires_auth_or_opt_in"):
        EngramDaemonClient("http://192.168.1.20:8765")


def test_client_methods_map_to_daemon_routes():
    transport = FakeTransport()
    client = EngramDaemonClient("http://127.0.0.1:8765", transport=transport)

    client.retrieve_chunk({"key": "k", "chunk_id": 0})
    client.retrieve_chunks({"requests": [{"key": "k", "chunk_id": 0}]})
    client.retrieve_memory({"key": "k"})
    client.store_memory({"key": "k", "content": "body"})
    client.check_duplicate({"key": "k", "content": "body"})
    client.update_memory_metadata({"key": "k", "title": "Updated"})
    client.repair_memory_metadata({"keys": ["k"], "dry_run": False})
    client.prepare_source_memory({"source_text": "body", "source_type": "note"})
    client.prepare_document_disassembly({"source_path": "C:/docs/book.pdf", "source_type": "pdf", "max_pages": 5})
    client.memory_os_status()
    client.memory_os_inspector()
    client.memory_os_source_import_job({"source_ref": {"source_uri": "file:///book.pdf"}})
    client.list_source_drafts(
        {"project": "Engram", "status": "draft", "limit": 10, "offset": 0}
    )
    client.discard_source_draft({"draft_id": "draft-a"})
    client.store_prepared_memory({"draft_id": "draft-a", "selected_items": [0], "force": True})
    client.delete_memory({"key": "k"})

    assert [call[1].rsplit("/", 1)[-1] for call in transport.calls] == [
        "retrieve_chunk",
        "retrieve_chunks",
        "retrieve_memory",
        "store_memory",
        "check_duplicate",
        "update_memory_metadata",
        "repair_memory_metadata",
        "prepare_source_memory",
        "prepare_document_disassembly",
        "status",
        "inspector",
        "source_import_job",
        "list_source_drafts",
        "discard_source_draft",
        "store_prepared_memory",
        "delete_memory",
    ]


def test_client_document_methods_map_to_stable_daemon_routes():
    transport = FakeTransport()
    client = EngramDaemonClient("http://127.0.0.1:8765", transport=transport)

    client.list_document_extractors({})
    client.preview_document_source_connector({"connector_type": "local_path", "target": "docs"})
    client.prepare_document_disassembly({"source_path": "C:/docs/book.pdf"})
    client.prepare_document_coverage_workbench({"source_path": "C:/docs/book.pdf"})
    client.prepare_document_coverage_pass({"ingestion_record": {"ingestion_id": "doc_ingest_book"}})
    client.prepare_document_intake_review({"source_path": "C:/docs/book.pdf"})
    client.prepare_document_extraction_request({"source_ref": {"source_uri": "file:///book.pdf"}})
    client.prepare_document_extraction_result({"title": "Book", "content": "body"})
    client.preview_document_extraction({"title": "Book", "content": "body"})
    client.prepare_visual_extraction_request({"document_record": {}, "image_refs": []})
    client.preview_visual_extraction({"document_record": {}, "observations": []})
    client.prepare_document_understanding_packet({"document_record": {}, "analysis": {}})
    client.prepare_document_draft({"document_record": {}, "analysis": {}})
    client.prepare_document_promotion_transaction({"document_draft": {}, "approved_by": "reviewer"})
    client.apply_document_promotion_transaction({"document_promotion_transaction": {}, "accept": True})
    client.prepare_document_artifact_store({"review_packet": {}})
    client.store_document_artifact({"prepared_transaction_id": "txn", "accept": True})
    client.prepare_document_ingestion_plan({"source_path": "C:/docs/book.pdf"})
    client.run_document_ingestion({"ingestion_id": "doc_ingest_book", "accept": True})
    client.resume_document_ingestion({"ingestion_id": "doc_ingest_book", "accept": True})
    client.inspect_document_ingestion({"ingestion_id": "doc_ingest_book"})
    client.prepare_document_ingestion_completion({"document_id": "doc_book"})
    client.complete_document_ingestion({"document_id": "doc_book", "accept": True})
    client.prepare_knowledge_branch({"name": "Review"})
    client.prepare_knowledge_pr({"branch_id": "kbranch_review", "title": "Review PR"})
    client.run_memory_ci({"knowledge_pr_id": "kpr_review"})
    client.inspect_knowledge_pr({"knowledge_pr_id": "kpr_review"})
    client.merge_knowledge_pr({"knowledge_pr_id": "kpr_review", "accept": True})
    client.list_memory_benchmark_suites({})
    client.run_memory_benchmark({"suite_id": "smoke", "seed": 42})
    client.inspect_benchmark_run({"run_id": "benchmark_run:smoke"})
    client.prepare_graph_readiness_report({"scope": "memory_os"})
    client.prepare_graph_proposal_batch({"scope": "memory_os", "source_refs": []})
    client.apply_graph_proposal_batch({"scope": "memory_os", "accept": True})
    client.repair_graph_edge_refs({"source": "document_ingestion.structural"})
    client.repair_graph_store_reconciliation({"repair_mode": "upsert_missing"})

    assert [call[1].rsplit("/", 1)[-1] for call in transport.calls] == [
        "list_document_extractors",
        "preview_document_source_connector",
        "prepare_document_disassembly",
        "prepare_document_coverage_workbench",
        "prepare_document_coverage_pass",
        "prepare_document_intake_review",
        "prepare_document_extraction_request",
        "prepare_document_extraction_result",
        "preview_document_extraction",
        "prepare_visual_extraction_request",
        "preview_visual_extraction",
        "prepare_document_understanding_packet",
        "prepare_document_draft",
        "prepare_document_promotion_transaction",
        "apply_document_promotion_transaction",
        "prepare_document_artifact_store",
        "store_document_artifact",
        "prepare_document_ingestion_plan",
        "run_document_ingestion",
        "resume_document_ingestion",
        "inspect_document_ingestion",
        "prepare_document_ingestion_completion",
        "complete_document_ingestion",
        "prepare_knowledge_branch",
        "prepare_knowledge_pr",
        "run_memory_ci",
        "inspect_knowledge_pr",
        "merge_knowledge_pr",
        "list_memory_benchmark_suites",
        "run_memory_benchmark",
        "inspect_benchmark_run",
        "prepare_graph_readiness_report",
        "prepare_graph_proposal_batch",
        "apply_graph_proposal_batch",
        "repair_graph_edge_refs",
        "repair_graph_store_reconciliation",
    ]


def test_engramd_help_exposes_daemon_options():
    result = subprocess.run(
        [sys.executable, "engramd.py", "--help"],
        cwd=".",
        capture_output=True,
        text=True,
        check=True,
    )

    assert "--host" in result.stdout
    assert "--port" in result.stdout
    assert "--health" in result.stdout
    assert "--smoke-test" in result.stdout
    assert "--doctor" in result.stdout
    assert "--hub-listen" in result.stdout
    assert "--hub-host" in result.stdout
    assert "--hub-port" in result.stdout
    assert "--sync-listen" in result.stdout
    assert "--sync-host" in result.stdout
    assert "--sync-port" in result.stdout
    assert "--stop-server-pid" in result.stdout


def test_engramd_client_query_knowledge_posts_contract_request():
    calls = []

    class FakeTransport:
        def request_json(self, method, url, payload=None, timeout=DEFAULT_DAEMON_TIMEOUT, headers=None):
            calls.append((method, url, payload, timeout, headers or {}))
            return {"status": "ok", "request_id": payload["request_id"]}

    client = EngramDaemonClient(
        "http://127.0.0.1:8765",
        transport=FakeTransport(),
    )

    response = client.query_knowledge(
        {
            "request_id": "req-client",
            "ask": {"project": "Engram", "task_type": "project_orientation"},
        }
    )

    assert response["request_id"] == "req-client"
    assert calls == [
        (
            "POST",
            "http://127.0.0.1:8765/v1/query_knowledge",
            {
                "request_id": "req-client",
                "ask": {"project": "Engram", "task_type": "project_orientation"},
            },
            DEFAULT_DAEMON_TIMEOUT,
            {},
        )
    ]
