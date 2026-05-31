"""Operator CLI helpers for the full Engram MCP server entrypoint."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Awaitable, Callable


@dataclass(frozen=True)
class ServerCliDependencies:
    """Runtime objects supplied by server.py without importing server.py here."""

    product_name: str
    product_version: str
    default_sse_host: str
    script_path: Path
    normalize_daemon_url: Callable[[str | None], str | None]
    mcp_env: Callable[[str | None], dict[str, str]]
    embedder: Any
    memory_manager: Any
    duplicate_memory_error: type[BaseException]
    build_health_payload: Callable[[], dict[str, Any]]
    run_agent_reliability_harness: Callable[[Any], dict[str, Any]]
    context_pack: Callable[..., Awaitable[dict[str, Any]]]
    graph_manager: Any
    list_graph_edges: Callable[..., Awaitable[dict[str, Any]]]
    impact_scan: Callable[..., Awaitable[dict[str, Any]]]
    audit_graph: Callable[..., Awaitable[dict[str, Any]]]
    prepare_source_memory: Callable[..., Awaitable[dict[str, Any]]]
    list_source_drafts: Callable[..., Awaitable[dict[str, Any]]]
    discard_source_draft: Callable[..., Awaitable[dict[str, Any]]]
    usage_summary: Callable[..., Awaitable[dict[str, Any]]]
    list_usage_calls: Callable[..., Awaitable[dict[str, Any]]]
    list_operation_jobs: Callable[..., Awaitable[dict[str, Any]]]
    list_operation_events: Callable[..., Awaitable[dict[str, Any]]]
    memory_protocol: Callable[..., Awaitable[dict[str, Any]]]
    validate_raw_service_bind: Callable[..., None]
    public_bind_denied: type[BaseException]
    prepare_mcp_runtime_before_start: Callable[[], dict[str, Any]]
    mcp: Any


def build_server_arg_parser(deps: ServerCliDependencies) -> argparse.ArgumentParser:
    """Build the full-server operator parser."""
    parser = argparse.ArgumentParser(
        description=f"{deps.product_name} {deps.product_version} — Semantic Memory MCP Server"
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument(
        "--host",
        default=deps.default_sse_host,
        help=f"SSE host (default: {deps.default_sse_host})",
    )
    parser.add_argument("--port", type=int, default=5100, help="SSE port (default: 5100)")
    parser.add_argument(
        "--rebuild-index",
        action="store_true",
        help="Rebuild ChromaDB index from JSON files and exit",
    )
    parser.add_argument(
        "--generate-config",
        action="store_true",
        help="Print MCP client config JSON and exit",
    )
    parser.add_argument(
        "--daemon-url",
        dest="daemon_url",
        help="Include ENGRAM_DAEMON_URL in generated config or use it for this server process",
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="Export all memories to engram_export_YYYY-MM-DD.json and exit",
    )
    parser.add_argument(
        "--import-file",
        dest="import_file",
        metavar="FILE",
        help="Import memories from a JSON bundle file and exit",
    )
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Re-chunk memories missing chunk_count and exit",
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help="Print server health status and exit",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run memory and v0.6 agent operating layer integration checks and exit",
    )
    parser.add_argument(
        "--agent-eval",
        action="store_true",
        help="Run deterministic agent reliability harness and exit",
    )
    return parser


def run_server_cli(deps: ServerCliDependencies, argv: list[str] | None = None) -> int:
    """Run the full server CLI or start the MCP transport."""
    parser = build_server_arg_parser(deps)
    args = parser.parse_args(argv)
    normalized_daemon_url = deps.normalize_daemon_url(args.daemon_url)
    if args.daemon_url is not None and normalized_daemon_url is None:
        parser.error("--daemon-url cannot be blank")
    if normalized_daemon_url is not None:
        os.environ["ENGRAM_DAEMON_URL"] = normalized_daemon_url

    if args.rebuild_index:
        deps.embedder._load()
        count = deps.memory_manager.rebuild_index()
        print(f"Rebuilt index for {count} memories.", file=sys.stderr)
        return 0

    if args.export:
        export_list = deps.memory_manager.export_memory_bundle()
        filename = f"engram_export_{date.today().isoformat()}.json"
        with open(filename, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(export_list, indent=2, ensure_ascii=False))
        print(f"Exported {len(export_list)} memories to {filename}", file=sys.stderr)
        return 0

    if args.import_file:
        deps.embedder._load()
        with open(args.import_file, "r", encoding="utf-8") as handle:
            bundle = json.load(handle)
        result = deps.memory_manager.import_memory_bundle(bundle, overwrite=True)
        print(f"Imported {result['imported_count']} memories from {args.import_file}", file=sys.stderr)
        if result["skipped_count"]:
            print(f"Skipped {result['skipped_count']} invalid memories during import.", file=sys.stderr)
        return 0

    if args.migrate:
        return _migrate_legacy_chunk_counts(deps.script_path)

    if args.health:
        payload = deps.build_health_payload()
        _print_health_payload(payload)
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        return 0 if payload["status"] == "ok" else 2

    if args.agent_eval:
        deps.embedder._load()
        deps.memory_manager._ensure_initialized()
        report = deps.run_agent_reliability_harness(deps.memory_manager)
        sys.stdout.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        return 0 if report["summary"]["status"] == "pass" else 1

    if args.self_test:
        deps.embedder._load()
        deps.memory_manager._ensure_initialized()
        print("Engram Self-Test: memory + v0.6 agent operating layer", file=sys.stderr)
        passed = asyncio.run(_run_self_test(deps))
        return 0 if passed else 1

    if args.generate_config:
        server_config: dict[str, Any] = {
            "command": sys.executable,
            "args": [os.path.abspath(deps.script_path)],
            "env": deps.mcp_env(normalized_daemon_url),
        }
        config = {
            "mcpServers": {
                "engram": server_config,
            }
        }
        sys.stdout.write(json.dumps(config, indent=2) + "\n")
        return 0

    if args.transport == "sse":
        try:
            deps.validate_raw_service_bind(args.host, surface="Engram MCP SSE transport")
        except deps.public_bind_denied as exc:
            print(f"[Engram] {exc}", file=sys.stderr)
            return 2

    runtime_payload = deps.prepare_mcp_runtime_before_start()
    if runtime_payload["mode"] == "daemon_client":
        if runtime_payload["reachable"]:
            print(
                f"[Engram] Daemon ready at {runtime_payload['configured_url']}. "
                "MCP server is running as a thin client.",
                file=sys.stderr,
            )
        else:
            error = runtime_payload.get("error") or {}
            print(
                f"[Engram] Daemon unavailable at {runtime_payload['configured_url']}: "
                f"{error.get('message', 'unknown error')}",
                file=sys.stderr,
            )

    if args.transport == "sse":
        print(f"[Engram] Starting — SSE on {args.host}:{args.port}", file=sys.stderr)
        deps.mcp.run(transport="sse", host=args.host, port=args.port)
    else:
        deps.mcp.run(transport="stdio")
    return 0


def _migrate_legacy_chunk_counts(script_path: Path) -> int:
    from core.chunker import chunk_content
    from core.memory_os.runtime_paths import resolve_data_root

    json_dir = resolve_data_root() / "memories"
    count = 0
    for path in json_dir.glob("*.json"):
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if "chunk_count" not in data or data["chunk_count"] == "?":
            chunks = chunk_content(data.get("content", ""))
            data["chunk_count"] = len(chunks)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)
            count += 1
    print(f"Migrated {count} memories (added chunk_count)", file=sys.stderr)
    return 0


def _print_health_payload(payload: dict[str, Any]) -> None:
    stats = payload["stats"]
    print("Engram Health Check", file=sys.stderr)
    print(f"  Model:      {payload['model']}", file=sys.stderr)
    print(f"  Mode:       {payload['mode']}", file=sys.stderr)
    print(f"  Memories:   {stats['total_memories']}", file=sys.stderr)
    print(f"  Chunks:     {stats['total_chunks']}", file=sys.stderr)
    print(
        f"  Brain size: {stats['storage_size']} "
        f"(JSON {stats['json_size']}, Chroma {stats['chroma_size']})",
        file=sys.stderr,
    )
    print(f"  JSON path:  {stats['json_path']}", file=sys.stderr)
    print(f"  Chroma path:{stats['chroma_path']}", file=sys.stderr)
    if payload["error"]:
        print(f"  Error:      {payload['error']['message']}", file=sys.stderr)
    print(f"Status: {payload['status'].upper()}", file=sys.stderr)


async def _run_self_test(deps: ServerCliDependencies) -> bool:
    test_key = "_engram_self_test"

    t0 = time.time()
    result = await deps.memory_manager.store_memory_async(
        test_key,
        "## Self Test\n\nThis is an integration test memory for Engram.",
        ["selftest"],
        "Self Test",
    )
    print(f"  store:          {result['chunk_count']} chunks in {time.time()-t0:.1f}s", file=sys.stderr)

    t0 = time.time()
    results = await deps.memory_manager.search_memories_async("integration test memory", limit=3)
    found = any(result["key"] == test_key for result in results)
    print(f"  search:         {'found' if found else 'NOT FOUND'} in {time.time()-t0:.1f}s", file=sys.stderr)

    t0 = time.time()
    chunk = await deps.memory_manager.retrieve_chunk_async(test_key, 0)
    print(f"  retrieve_chunk: {'ok' if chunk else 'FAILED'} in {time.time()-t0:.1f}s", file=sys.stderr)

    t0 = time.time()
    context_payload = await deps.context_pack(
        "integration test memory",
        max_chunks=1,
        budget_chars=1000,
    )
    context_receipt = context_payload.get("receipt", {})
    context_ok = (
        context_payload.get("count", 0) >= 1
        and context_receipt.get("selected_chunk_count", 0) >= 1
        and context_receipt.get("budget_chars") == 1000
    )
    print(f"  context_pack:   {'ok' if context_ok else 'FAILED'} in {time.time()-t0:.1f}s", file=sys.stderr)

    t0 = time.time()
    deleted = await deps.memory_manager.delete_memory_async(test_key)
    print(f"  delete:         {'ok' if deleted else 'FAILED'} in {time.time()-t0:.1f}s", file=sys.stderr)

    verify = await deps.memory_manager.retrieve_memory_async(test_key)
    print(f"  verify deleted: {'ok' if verify is None else 'STILL EXISTS'}", file=sys.stderr)

    await deps.memory_manager.store_memory_async(
        "_test_tracking",
        "## Tracking test\n\nThis tests last_accessed updates.",
        ["selftest"],
        "Tracking Test",
    )
    await deps.memory_manager.retrieve_memory_async("_test_tracking")
    await asyncio.sleep(0.1)
    data_after = deps.memory_manager._load_json("_test_tracking")
    tracking_ok = data_after is not None and data_after.get("last_accessed") is not None
    print(f"  last_accessed:  {'set' if tracking_ok else 'NOT SET'}", file=sys.stderr)

    await deps.memory_manager.store_memory_async(
        "_test_dedup_original",
        "## Dedup original\n\nThis is a test memory for duplicate detection purposes. "
        "It contains enough substantive content to get a reliable and stable embedding from the sentence-transformers model.",
        ["selftest"],
        "Dedup Original",
    )
    dedup_blocked = False
    try:
        await deps.memory_manager.store_memory_async(
            "_test_dedup_copy",
            "## Dedup original\n\nThis is a test memory for duplicate detection purposes. "
            "It contains enough substantive content to get a reliable and stable embedding from the sentence-transformers model.",
            ["selftest"],
            "Dedup Copy",
        )
    except deps.duplicate_memory_error:
        dedup_blocked = True
    print(f"  dedup block:    {'blocked' if dedup_blocked else 'NOT BLOCKED'}", file=sys.stderr)

    force_ok = False
    try:
        await deps.memory_manager.store_memory_async(
            "_test_dedup_forced",
            "## Dedup original\n\nThis is a test memory for duplicate detection purposes. "
            "It contains enough substantive content to get a reliable and stable embedding from the sentence-transformers model.",
            ["selftest"],
            "Dedup Forced",
            force=True,
        )
        force_ok = True
    except deps.duplicate_memory_error:
        force_ok = False
    print(f"  force override: {'ok' if force_ok else 'FAILED'}", file=sys.stderr)

    self_update_ok = False
    try:
        await deps.memory_manager.store_memory_async(
            "_test_dedup_original",
            "## Dedup original\n\nThis is a test memory for duplicate detection purposes. "
            "It contains enough substantive content to get a reliable and stable embedding from the sentence-transformers model. Updated.",
            ["selftest"],
            "Dedup Original Updated",
        )
        self_update_ok = True
    except deps.duplicate_memory_error:
        self_update_ok = False
    print(f"  self-update:    {'ok' if self_update_ok else 'BLOCKED (BUG)'}", file=sys.stderr)

    await deps.memory_manager.store_memory_async(
        "_test_relm_a",
        "## Related A\n\nThis memory links to B.",
        ["selftest"],
        "Related A",
        related_to=["_test_relm_b"],
    )
    await deps.memory_manager.store_memory_async(
        "_test_relm_b",
        "## Related B\n\nStandalone memory.",
        ["selftest"],
        "Related B",
    )
    relm_json = deps.memory_manager._load_json("_test_relm_a")
    relm_stored = relm_json is not None and relm_json.get("related_to") == ["_test_relm_b"]
    print(f"  related_to JSON:{'ok' if relm_stored else 'FAILED'}", file=sys.stderr)

    rel_result = await deps.memory_manager.get_related_memories_async("_test_relm_b")
    relm_bidir = any(result["key"] == "_test_relm_a" for result in rel_result.get("reverse", []))
    print(f"  bidirectional:  {'ok' if relm_bidir else 'FAILED'}", file=sys.stderr)

    graph_edge = deps.graph_manager.add_edge(
        from_ref={"kind": "memory", "key": "_test_relm_a"},
        to_ref={"kind": "memory", "key": "_test_relm_b"},
        edge_type="related_to",
        evidence="Self-test verifies graph edge storage.",
        source="self_test",
        created_by="self_test",
    )
    graph_list = await deps.list_graph_edges(ref={"kind": "memory", "key": "_test_relm_a"})
    graph_scan = await deps.impact_scan({"kind": "memory", "key": "_test_relm_a"})
    graph_audit_payload = await deps.audit_graph()
    graph_ok = (
        graph_edge.get("edge_id", "").startswith("sha256:")
        and graph_list.get("count", 0) >= 1
        and graph_scan.get("count", 0) >= 1
        and graph_audit_payload.get("error") is None
    )
    print(f"  graph tools:    {'ok' if graph_ok else 'FAILED'}", file=sys.stderr)

    source_payload = await deps.prepare_source_memory(
        source_text="Decision: Self-test source intake remains draft-only.",
        source_type="self_test",
        project="Engram Self Test",
        domain="operations",
        budget_chars=1000,
    )
    source_draft = source_payload.get("draft") or {}
    source_draft_id = source_draft.get("draft_id")
    source_list = await deps.list_source_drafts(
        project="Engram Self Test",
        status="draft",
        limit=5,
    )
    source_discard = (
        await deps.discard_source_draft(source_draft_id)
        if source_draft_id
        else {"discarded": False}
    )
    source_ok = (
        bool(source_draft_id)
        and source_list.get("count", 0) >= 1
        and source_discard.get("discarded") is True
    )
    print(f"  source drafts:  {'ok' if source_ok else 'FAILED'}", file=sys.stderr)

    usage_payload = await deps.usage_summary(days=1)
    usage_calls_payload = await deps.list_usage_calls(limit=10)
    usage_ok = usage_payload.get("total_calls", 0) >= 1 and usage_calls_payload.get("count", 0) >= 1
    print(f"  usage meter:    {'ok' if usage_ok else 'FAILED'}", file=sys.stderr)

    operation_jobs = await deps.list_operation_jobs(limit=20)
    operation_events = await deps.list_operation_events(limit=20)
    operations_ok = operation_jobs.get("count", 0) >= 1 and operation_events.get("count", 0) >= 1
    print(f"  operation log:  {'ok' if operations_ok else 'FAILED'}", file=sys.stderr)

    protocol_payload = await deps.memory_protocol()
    protocol_ok = (
        protocol_payload.get("version") == 2
        and protocol_payload.get("tool_groups", {}).get("graph", {}).get("stability") == "beta"
        and protocol_payload.get("tool_groups", {}).get("usage", {}).get("stability") == "beta"
        and protocol_payload.get("tool_groups", {}).get("operations", {}).get("stability") == "beta"
    )
    print(f"  protocol v0.6:  {'ok' if protocol_ok else 'FAILED'}", file=sys.stderr)

    for key in [
        "_test_tracking",
        "_test_dedup_original",
        "_test_dedup_copy",
        "_test_dedup_forced",
        "_test_relm_a",
        "_test_relm_b",
    ]:
        try:
            await deps.memory_manager.delete_memory_async(key)
        except Exception as exc:
            print(f"  cleanup skip {key}: {exc}", file=sys.stderr)
    try:
        deps.graph_manager.add_edge(
            from_ref={"kind": "memory", "key": "_test_relm_a"},
            to_ref={"kind": "memory", "key": "_test_relm_b"},
            edge_type="related_to",
            evidence="Self-test verifies graph edge storage.",
            source="self_test",
            created_by="self_test",
            status="archived",
        )
    except Exception as exc:
        print(f"  graph cleanup skip: {exc}", file=sys.stderr)

    all_ok = (
        found
        and chunk
        and deleted
        and verify is None
        and context_ok
        and tracking_ok
        and dedup_blocked
        and force_ok
        and self_update_ok
        and relm_stored
        and relm_bidir
        and graph_ok
        and source_ok
        and usage_ok
        and operations_ok
        and protocol_ok
    )
    print(f"Self-test {'PASSED' if all_ok else 'FAILED'}", file=sys.stderr)
    return bool(all_ok)
