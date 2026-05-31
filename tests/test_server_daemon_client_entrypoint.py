from __future__ import annotations

import asyncio
import builtins
import importlib
import sys


def test_thin_daemon_client_imports_without_storage_dependencies(monkeypatch):
    blocked = {"chromadb", "sentence_transformers", "torch", "lancedb", "kuzu"}
    real_import = builtins.__import__
    loaded_before = {name.split(".", 1)[0] for name in sys.modules}
    exact_before = set(sys.modules)

    def guarded_import(name, *args, **kwargs):
        if name.split(".", 1)[0] in blocked:
            raise ImportError(f"blocked storage dependency: {name}")
        return real_import(name, *args, **kwargs)

    for module_name in list(sys.modules):
        if (
            module_name == "server_daemon_client"
            or module_name.startswith("server_daemon_client.")
        ):
            del sys.modules[module_name]

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    module = importlib.import_module("server_daemon_client")

    assert module.PRODUCT_NAME == "Engram"
    assert module._daemon_url() == "http://127.0.0.1:8765"
    loaded_after = {name.split(".", 1)[0] for name in sys.modules}
    exact_after = set(sys.modules)
    assert (loaded_after - loaded_before).isdisjoint(blocked)
    assert "core.memory_manager" not in (exact_after - exact_before)
    assert "core.memory_os.runtime" not in (exact_after - exact_before)
    assert "core.memory_os.document_ingestion" not in (exact_after - exact_before)
    assert "core.document_extractors" not in (exact_after - exact_before)
    assert "core.document_coverage_workbench" not in (exact_after - exact_before)
    assert "server" not in (exact_after - exact_before)


def test_thin_daemon_client_timeout_is_long_enough_for_serialized_queue(monkeypatch):
    import server_daemon_client

    monkeypatch.delenv("ENGRAM_DAEMON_TIMEOUT", raising=False)
    assert server_daemon_client._daemon_timeout() == 120.0

    monkeypatch.setenv("ENGRAM_DAEMON_TIMEOUT", "240")
    assert server_daemon_client._daemon_timeout() == 240.0

    monkeypatch.setenv("ENGRAM_DAEMON_TIMEOUT", "bad")
    assert server_daemon_client._daemon_timeout() == 120.0

    monkeypatch.setenv("ENGRAM_DAEMON_TIMEOUT", "0.1")
    assert server_daemon_client._daemon_timeout() == 1.0


def test_thin_daemon_client_search_delegates_to_daemon(monkeypatch):
    import server_daemon_client

    class FakeClient:
        def __init__(self) -> None:
            self.calls = []

        def search_memories(self, payload):
            self.calls.append(("search_memories", payload))
            return {
                "query": payload["query"],
                "count": 1,
                "results": [{"key": "daemon_memory", "chunk_id": 0}],
                "error": None,
            }

    client = FakeClient()
    monkeypatch.setattr(server_daemon_client, "_daemon_client", lambda: client)

    payload = asyncio.run(
        server_daemon_client.search_memories(
            "daemon check",
            limit=3,
            tags="backend, daemon",
            retrieval_mode="hybrid",
        )
    )

    assert payload["results"][0]["key"] == "daemon_memory"
    assert client.calls == [
        (
            "search_memories",
            {
                "query": "daemon check",
                "limit": 3,
                "project": None,
                "exact_project_match": False,
                "domain": None,
                "tags": ["backend", "daemon"],
                "include_stale": True,
                "canonical_only": False,
                "pinned_keys": [],
                "pinned_first": False,
                "retrieval_mode": "hybrid",
            },
        )
    ]


def test_thin_daemon_client_discovers_capabilities(monkeypatch):
    import server_daemon_client

    class FakeClient:
        def __init__(self) -> None:
            self.calls = []

        def discover_memory_capabilities(self, payload):
            self.calls.append(("discover_memory_capabilities", payload))
            return {
                "schema_version": "2026-05-26.capability-discovery.v1",
                "write_performed": False,
                "capability_groups": {"memory": {"tools": ["search_memories"]}},
                "error": None,
            }

    client = FakeClient()
    monkeypatch.setattr(server_daemon_client, "_daemon_client", lambda: client)

    payload = asyncio.run(
        server_daemon_client.discover_memory_capabilities(
            query="document graph memory sync",
            budget_chars=1200,
        )
    )
    protocol = server_daemon_client.memory_protocol()

    assert payload["write_performed"] is False
    assert client.calls == [
        (
            "discover_memory_capabilities",
            {"query": "document graph memory sync", "budget_chars": 1200},
        )
    ]
    assert "discover_memory_capabilities" in protocol["canonical_tools"]


def test_thin_daemon_client_delegates_sync_identity_tools(monkeypatch):
    import server_daemon_client

    class FakeClient:
        def __init__(self) -> None:
            self.calls = []

        def ensure_sync_device_identity(self, payload):
            self.calls.append(("ensure_sync_device_identity", payload))
            return {"status": "ready", "local_device": {"device_name": payload["device_name"]}}

        def export_local_sync_identity(self, payload):
            self.calls.append(("export_local_sync_identity", payload))
            return {"record_type": "sync_public_identity", "device_id": "device:laptop"}

        def register_sync_peer(self, payload):
            self.calls.append(("register_sync_peer", payload))
            return {"write_performed": True, "peer": payload["peer_identity_packet"]}

        def inspect_sync_state(self, payload):
            self.calls.append(("inspect_sync_state", payload))
            return {"write_performed": False, "status": {"status": "ready"}}

        def prepare_sync_changeset(self, payload):
            self.calls.append(("prepare_sync_changeset", payload))
            return {"write_performed": False, "status": "ready", "peer_id": payload["peer_id"]}

        def export_sync_changeset(self, payload):
            self.calls.append(("export_sync_changeset", payload))
            return {"write_performed": True, "status": "exported", "plan": payload["plan"]}

        def prepare_sync_apply(self, payload):
            self.calls.append(("prepare_sync_apply", payload))
            return {"write_performed": False, "status": "ready", "bundle_b64": payload["bundle_b64"]}

        def apply_sync_changeset(self, payload):
            self.calls.append(("apply_sync_changeset", payload))
            return {"write_performed": True, "status": "applied", "plan": payload["plan"]}

        def inspect_sync_convergence(self, payload):
            self.calls.append(("inspect_sync_convergence", payload))
            return {"write_performed": False, "converged": True, "peer_id": payload["peer_id"]}

        def list_sync_conflicts(self, payload):
            self.calls.append(("list_sync_conflicts", payload))
            return {"write_performed": False, "conflicts": [], "unresolved_conflict_count": 0}

        def resolve_sync_conflict(self, payload):
            self.calls.append(("resolve_sync_conflict", payload))
            return {"write_performed": True, "status": "resolved", "conflict_id": payload["conflict_id"]}

        def configure_sync_peer_transport(self, payload):
            self.calls.append(("configure_sync_peer_transport", payload))
            return {"write_performed": True, "status": "configured", "peer": payload}

        def inspect_sync_peer(self, payload):
            self.calls.append(("inspect_sync_peer", payload))
            return {"write_performed": False, "status": "ok", "peer": {"device_id": payload["peer_id"]}}

        def push_sync_changeset(self, payload):
            self.calls.append(("push_sync_changeset", payload))
            return {"write_performed": True, "status": "pushed", "peer_id": payload["peer_id"]}

        def list_sync_inbox(self, payload):
            self.calls.append(("list_sync_inbox", payload))
            return {"write_performed": False, "inbox_count": 0, "inbox": []}

    client = FakeClient()
    peer_packet = {"device_id": "device:desktop"}
    plan = {"status": "ready", "peer_id": "device:desktop"}
    monkeypatch.setattr(server_daemon_client, "_daemon_client", lambda: client)

    ensured = asyncio.run(server_daemon_client.ensure_sync_device_identity("laptop"))
    exported = asyncio.run(server_daemon_client.export_local_sync_identity())
    registered = asyncio.run(
        server_daemon_client.register_sync_peer(
            peer_identity_packet=peer_packet,
            accept=True,
            approved_by="tester",
        )
    )
    state = asyncio.run(server_daemon_client.inspect_sync_state())
    prepared = asyncio.run(server_daemon_client.prepare_sync_changeset("device:desktop"))
    changeset_export = asyncio.run(
        server_daemon_client.export_sync_changeset(plan=plan, accept=True, approved_by="tester")
    )
    apply_plan = asyncio.run(server_daemon_client.prepare_sync_apply("bundle"))
    changeset_apply = asyncio.run(
        server_daemon_client.apply_sync_changeset(
            bundle_b64="bundle",
            plan=apply_plan,
            accept=True,
            approved_by="tester",
        )
    )
    convergence = asyncio.run(server_daemon_client.inspect_sync_convergence("device:desktop"))
    conflicts = asyncio.run(server_daemon_client.list_sync_conflicts())
    resolved = asyncio.run(
        server_daemon_client.resolve_sync_conflict(
            conflict_id="sync_conflict:1",
            resolution="keep_local",
            accept=True,
            approved_by="tester",
        )
    )
    configured_transport = asyncio.run(
        server_daemon_client.configure_sync_peer_transport(
            peer_id="device:desktop",
            url="http://100.64.0.10:8766",
            accept=True,
            approved_by="tester",
        )
    )
    inspected_peer = asyncio.run(server_daemon_client.inspect_sync_peer("device:desktop"))
    pushed = asyncio.run(
        server_daemon_client.push_sync_changeset(
            peer_id="device:desktop",
            accept=True,
            approved_by="tester",
        )
    )
    inbox = asyncio.run(server_daemon_client.list_sync_inbox())

    assert ensured["local_device"]["device_name"] == "laptop"
    assert exported["device_id"] == "device:laptop"
    assert registered["peer"] == peer_packet
    assert state["status"]["status"] == "ready"
    assert prepared["peer_id"] == "device:desktop"
    assert changeset_export["status"] == "exported"
    assert apply_plan["status"] == "ready"
    assert changeset_apply["status"] == "applied"
    assert convergence["converged"] is True
    assert conflicts["unresolved_conflict_count"] == 0
    assert resolved["status"] == "resolved"
    assert configured_transport["status"] == "configured"
    assert inspected_peer["peer"]["device_id"] == "device:desktop"
    assert pushed["status"] == "pushed"
    assert inbox["inbox_count"] == 0
    assert client.calls == [
        ("ensure_sync_device_identity", {"device_name": "laptop"}),
        ("export_local_sync_identity", {}),
        (
            "register_sync_peer",
            {
                "peer_identity_packet": peer_packet,
                "accept": True,
                "approved_by": "tester",
            },
        ),
        ("inspect_sync_state", {}),
        ("prepare_sync_changeset", {"peer_id": "device:desktop"}),
        (
            "export_sync_changeset",
            {
                "plan": plan,
                "accept": True,
                "approved_by": "tester",
            },
        ),
        ("prepare_sync_apply", {"bundle_b64": "bundle"}),
        (
            "apply_sync_changeset",
            {
                "bundle_b64": "bundle",
                "plan": apply_plan,
                "accept": True,
                "approved_by": "tester",
            },
        ),
        ("inspect_sync_convergence", {"peer_id": "device:desktop"}),
        ("list_sync_conflicts", {"status": None}),
        (
            "resolve_sync_conflict",
            {
                "conflict_id": "sync_conflict:1",
                "resolution": "keep_local",
                "accept": True,
                "approved_by": "tester",
            },
        ),
        (
            "configure_sync_peer_transport",
            {
                "peer_id": "device:desktop",
                "url": "http://100.64.0.10:8766",
                "mode": "manual",
                "allow_pull": False,
                "accept": True,
                "approved_by": "tester",
            },
        ),
        ("inspect_sync_peer", {"peer_id": "device:desktop"}),
        (
            "push_sync_changeset",
            {
                "peer_id": "device:desktop",
                "accept": True,
                "approved_by": "tester",
            },
        ),
        ("list_sync_inbox", {"peer_id": None}),
    ]


def test_thin_daemon_client_store_formats_daemon_response(monkeypatch):
    import server_daemon_client

    class FakeClient:
        def store_memory(self, payload):
            return {
                "stored": True,
                "result": {
                    "key": payload["key"],
                    "title": payload["title"],
                    "chunk_count": 2,
                    "chars": len(payload["content"]),
                },
                "error": None,
            }

    monkeypatch.setattr(server_daemon_client, "_daemon_client", lambda: FakeClient())

    message = asyncio.run(
        server_daemon_client.store_memory(
            key="daemon_memory",
            content="Daemon body.",
            title="Daemon Memory",
            tags=["daemon"],
            force=True,
        )
    )

    assert "Stored: 'Daemon Memory'" in message
    assert "2 chunks" in message


def test_thin_daemon_client_memory_os_status_delegates_to_daemon(monkeypatch):
    import server_daemon_client

    class FakeClient:
        def memory_os_status(self):
            return {
                "status": "ok",
                "components": {"retrieval": {"backend": "LanceDBVectorIndex"}},
            }

    monkeypatch.setattr(server_daemon_client, "_daemon_client", lambda: FakeClient())

    payload = asyncio.run(server_daemon_client.memory_os_status())

    assert payload["status"] == "ok"
    assert payload["components"]["retrieval"]["backend"] == "LanceDBVectorIndex"


def test_thin_daemon_client_query_knowledge_delegates_to_daemon(monkeypatch):
    import server_daemon_client

    class FakeClient:
        def query_knowledge(self, payload):
            return {
                "contract_version": "engram.knowledge.response.v0",
                "request_id": payload["request_id"],
                "status": "ok",
                "answer": {"project": payload["ask"]["project"]},
                "citations": [
                    {
                        "citation_id": "cit_001",
                        "level": "chunk",
                        "source": "memory_os",
                        "key": "engram_direction",
                        "chunk_id": 0,
                    }
                ],
                "freshness": {"state": "fresh"},
                "policy": {
                    "unreviewed_sources_used": False,
                    "unsupported_inferences_used": False,
                    "review_state_available": False,
                    "review_filter_enforced": False,
                    "review_state_basis": "not_available_in_current_memory_os_records",
                },
                "budget_used": {
                    "artifacts_built": 1,
                    "artifacts_read": 0,
                    "source_reads": 0,
                    "tokens_out_estimate": 0,
                },
                "planner": {
                    "strategy": "project_capsule",
                    "methods_used": ["artifact"],
                    "omissions": [],
                    "budget": {
                        "requested": {
                            "max_artifacts": 1,
                            "max_source_reads": 12,
                            "max_tokens_out": 2500,
                        },
                        "used": {
                            "artifacts_built": 1,
                            "artifacts_read": 0,
                            "source_reads": 0,
                            "tokens_out_estimate": 0,
                        },
                    },
                    "failure_receipts": [],
                    "response_status": "ok",
                },
                "errors": [],
            }

    monkeypatch.setattr(server_daemon_client, "_daemon_client", lambda: FakeClient())

    payload = asyncio.run(
        server_daemon_client.query_knowledge(
            {
                "request_id": "req-thin",
                "ask": {
                    "goal": "Get context.",
                    "task_type": "project_orientation",
                    "project": "Engram",
                },
            }
        )
    )

    assert payload["request_id"] == "req-thin"
    assert payload["answer"]["project"] == "Engram"
