from __future__ import annotations

from pathlib import Path


def test_inspector_tab_is_wired_in_static_assets():
    html = Path("templates/index.html").read_text(encoding="utf-8")
    js = Path("static/app.js").read_text(encoding="utf-8")

    assert 'id="btn-inspector-tab"' in html
    assert 'id="inspector-panel"' in html
    assert 'data-action="toggle-inspector"' in html
    assert "toggleInspectorTab" in js
    assert "loadInspectorTab" in js
    assert "/api/inspector/memory-quality" in js
    assert "/api/inspector/graph/audit" in js
    assert "/api/inspector/source-drafts" in js
    assert "/api/inspector/operations/jobs" in js
    assert "/api/inspector/operations/events" in js
    assert "/api/inspector/memory-os" in js
    assert "/api/inspector/review-queue" in js
    assert "/api/inspector/release-gates" in js
    assert 'id="inspector-memory-os-list"' in html
    assert 'id="inspector-draft-list"' in html
    assert 'id="inspector-review-list"' in html
    assert 'id="inspector-promotion-list"' in html
    assert 'id="inspector-release-gates-list"' in html


def test_memory_quality_inspector_api_returns_metadata_only_report(monkeypatch):
    import webui

    class FakeMemoryManager:
        def list_memories(self):
            return [
                {
                    "key": "quality-note",
                    "title": "Quality Note",
                    "tags": [],
                    "project": "C:/Dev/Engram",
                    "domain": None,
                    "status": "active",
                    "canonical": False,
                    "chars": 500,
                    "chunk_count": 1,
                },
                {
                    "key": "other-project",
                    "title": "Other",
                    "tags": ["ok"],
                    "project": "Other",
                    "domain": "notes",
                    "status": "active",
                    "canonical": False,
                    "chars": 100,
                    "chunk_count": 1,
                },
            ]

    monkeypatch.setattr(webui, "memory_manager", FakeMemoryManager())

    response = webui.app.test_client().get(
        "/api/inspector/memory-quality?project=C%3A%2FDev%2FEngram&limit=10"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["schema_version"] == "2026-05-11.memory-quality.v1"
    assert payload["count"] == 1
    assert payload["write_performed"] is False
    assert payload["memories"][0]["key"] == "quality-note"
    assert "content" not in payload["memories"][0]
    assert payload["memories"][0]["issues"][0]["code"] == "missing_domain"


def test_graph_edges_inspector_api_uses_graph_manager_boundary(monkeypatch):
    import webui

    observed = {}

    class FakeGraphManager:
        def list_edges(self, *, ref=None, edge_type=None, status="active"):
            observed.update({"ref": ref, "edge_type": edge_type, "status": status})
            return {"count": 1, "edges": [{"edge_type": edge_type, "status": status}], "error": None}

    monkeypatch.setattr(webui, "graph_manager", FakeGraphManager())

    response = webui.app.test_client().get(
        "/api/inspector/graph/edges?ref_kind=memory&ref_key=decision&edge_type=supports"
    )

    assert response.status_code == 200
    assert observed == {
        "ref": {"kind": "memory", "key": "decision"},
        "edge_type": "supports",
        "status": "active",
    }
    assert response.get_json()["count"] == 1


def test_operation_receipts_inspector_api_lists_jobs_and_events(monkeypatch):
    import webui

    class FakeOperationLog:
        def list_jobs(self, *, operation_type=None, status=None, limit=50):
            return {
                "count": 1,
                "jobs": [{"operation_type": operation_type, "status": status, "limit": limit}],
                "error": None,
            }

        def list_events(self, *, event_type=None, limit=50):
            return {
                "count": 1,
                "events": [{"event_type": event_type, "limit": limit}],
                "error": None,
            }

    monkeypatch.setattr(webui, "operation_log", FakeOperationLog())
    client = webui.app.test_client()

    jobs = client.get("/api/inspector/operations/jobs?operation_type=source_intake&status=completed&limit=5")
    events = client.get("/api/inspector/operations/events?event_type=source_draft_ready&limit=7")

    assert jobs.status_code == 200
    assert jobs.get_json()["jobs"] == [
        {"operation_type": "source_intake", "status": "completed", "limit": 5}
    ]
    assert events.status_code == 200
    assert events.get_json()["events"] == [{"event_type": "source_draft_ready", "limit": 7}]


def test_source_drafts_inspector_api_lists_review_queue(monkeypatch):
    import webui

    observed = {}

    class FakeSourceIntakeManager:
        def list_source_drafts(self, *, project=None, status=None, limit=50, offset=0):
            observed.update({"project": project, "status": status, "limit": limit, "offset": offset})
            return {
                "count": 1,
                "total": 1,
                "limit": limit,
                "offset": offset,
                "has_more": False,
                "drafts": [{"draft_id": "sha256:abc", "status": status, "pipeline": "handoff"}],
                "error": None,
            }

    monkeypatch.setattr(webui, "source_intake_manager", FakeSourceIntakeManager())

    response = webui.app.test_client().get(
        "/api/inspector/source-drafts?project=C%3A%2FDev%2FEngram&status=draft&limit=5&offset=2"
    )

    assert response.status_code == 200
    assert observed == {"project": "C:/Dev/Engram", "status": "draft", "limit": 5, "offset": 2}
    assert response.get_json()["drafts"] == [
        {"draft_id": "sha256:abc", "status": "draft", "pipeline": "handoff"}
    ]


def test_memory_os_inspector_api_returns_read_only_report(monkeypatch):
    import webui

    def fake_memory_os_inspector_payload(*, limit=20):
        return {
            "schema_version": "2026-05-13.memory-os-inspector.v1",
            "limit": limit,
            "write_performed": False,
            "runtime": {"status": "ok"},
            "jobs": {"count": 1, "items": [{"job_id": "job:document", "status": "queued"}]},
            "transactions": {"count": 1, "items": [{"transaction_id": "txn:dry", "status": "dry_run"}]},
            "graph": {"edge_count": 1, "edges": [{"edge_id": "edge:one", "edge_type": "supports"}]},
            "entity_registry": {
                "entity_count": 1,
                "concept_count": 1,
                "entities": [{"canonical_name": "Visual Hierarchy"}],
                "concepts": [{"label": "attention priority"}],
            },
            "firewall_queue": {"count": 1, "items": [{"event_id": "firewall:one", "decision": "quarantine"}]},
            "coverage_maps": {"count": 1, "items": [{"coverage_map_id": "coverage:book"}]},
            "snapshots": {"count": 1, "items": [{"snapshot_id": "snapshot:one"}]},
            "skill_packs": {"count": 1, "items": [{"compilation_id": "design_compilation:one"}]},
        }

    monkeypatch.setattr(webui, "get_memory_os_inspector_payload", fake_memory_os_inspector_payload)

    response = webui.app.test_client().get("/api/inspector/memory-os?limit=9")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["write_performed"] is False
    assert payload["limit"] == 9
    assert payload["coverage_maps"]["items"][0]["coverage_map_id"] == "coverage:book"
    assert payload["firewall_queue"]["items"][0]["decision"] == "quarantine"


def test_review_queue_inspector_api_returns_read_only_memory_os_state(monkeypatch):
    import webui

    def fake_memory_os_inspector_payload(*, limit=20):
        return {
            "schema_version": "2026-05-13.memory-os-inspector.v1",
            "limit": limit,
            "write_performed": False,
            "review_preparation_queue": {
                "count": 1,
                "items": [{"record_type": "document_draft", "draft_id": "draft:book"}],
            },
            "document_artifact_transactions": {
                "count": 1,
                "items": [{"transaction_id": "txn:artifact", "operation_kind": "document_artifact_store"}],
            },
            "promotion_transactions": {
                "count": 1,
                "items": [
                    {
                        "transaction_id": "txn:promote",
                        "record_type": "document_promotion_transaction",
                    }
                ],
            },
        }

    monkeypatch.setattr(webui, "get_memory_os_inspector_payload", fake_memory_os_inspector_payload)

    response = webui.app.test_client().get("/api/inspector/review-queue?limit=4")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["write_performed"] is False
    assert payload["limit"] == 4
    assert payload["review_preparation_queue"]["items"][0]["draft_id"] == "draft:book"
    assert payload["document_artifact_transactions"]["items"][0]["transaction_id"] == "txn:artifact"
    assert payload["promotion_transactions"]["items"][0]["transaction_id"] == "txn:promote"


def test_release_gates_inspector_api_exposes_command_list(monkeypatch):
    import webui

    def fake_memory_os_inspector_payload(*, limit=20):
        return {
            "schema_version": "2026-05-13.memory-os-inspector.v1",
            "limit": limit,
            "write_performed": False,
            "release_gate_commands": {
                "count": 1,
                "items": [
                    {
                        "command": "python server.py --agent-eval",
                        "purpose": "agent-facing retrieval/source/document workflow gates",
                    }
                ],
            },
        }

    monkeypatch.setattr(webui, "get_memory_os_inspector_payload", fake_memory_os_inspector_payload)

    response = webui.app.test_client().get("/api/inspector/release-gates")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["write_performed"] is False
    assert payload["release_gate_commands"]["items"][0]["command"] == "python server.py --agent-eval"


def test_document_promotion_apply_route_requires_acceptance_and_reviewer(monkeypatch):
    import webui

    calls = []

    def fake_apply_document_promotion_from_webui(payload):
        calls.append(payload)
        return {
            "status": "ok",
            "write_performed": True,
            "source_transaction_id": payload["document_promotion_transaction"]["transaction_id"],
        }

    monkeypatch.setenv("ENGRAM_WEBUI_HOST", "127.0.0.1")
    monkeypatch.setattr(
        webui,
        "apply_document_promotion_from_webui",
        fake_apply_document_promotion_from_webui,
    )

    client = webui.app.test_client()
    transaction = {
        "transaction_id": "txn:promote",
        "record_type": "document_promotion_transaction",
        "operations": [],
    }

    missing_accept = client.post(
        "/api/inspector/document-promotions/apply",
        json={"document_promotion_transaction": transaction, "approved_by": "Reviewer"},
    )
    missing_reviewer = client.post(
        "/api/inspector/document-promotions/apply",
        json={"document_promotion_transaction": transaction, "accept": True},
    )
    ok = client.post(
        "/api/inspector/document-promotions/apply",
        json={
            "document_promotion_transaction": transaction,
            "accept": True,
            "approved_by": "Reviewer",
            "selected_operation_indexes": [0],
        },
    )

    assert missing_accept.status_code == 400
    assert missing_accept.get_json()["error"]["code"] == "accept_required"
    assert missing_reviewer.status_code == 400
    assert missing_reviewer.get_json()["error"]["code"] == "approved_by_required"
    assert ok.status_code == 200
    assert ok.get_json()["source_transaction_id"] == "txn:promote"
    assert calls == [
        {
            "document_promotion_transaction": transaction,
            "accept": True,
            "approved_by": "Reviewer",
            "selected_operation_indexes": [0],
        }
    ]
