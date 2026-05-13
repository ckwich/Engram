from core.memory_os._records import upsert_record
from core.memory_os.inspector import build_memory_os_inspector
from core.memory_os.ledger import MemoryOSLedger


class FakeRuntime:
    def __init__(self, ledger):
        self.ledger = ledger

    def status(self):
        return {
            "status": "ok",
            "components": {
                "ledger": {"path": str(self.ledger.path), "exists": True},
                "retrieval": {"backend": "LanceDBVectorIndex"},
                "graph": {"backend": "KuzuGraphStore"},
            },
        }


def test_memory_os_inspector_summarizes_read_only_runtime_state(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "engram.sqlite")
    upsert_record(
        ledger,
        "jobs",
        "job:one",
        {"job_id": "job:one", "job_kind": "document_materialization", "status": "queued"},
    )
    upsert_record(
        ledger,
        "transactions",
        "txn:one",
        {"transaction_id": "txn:one", "operation_kind": "import_document", "status": "dry_run"},
    )
    upsert_record(
        ledger,
        "retrieval_receipts",
        "coverage:one",
        {"coverage_map_id": "coverage:one", "document_id": "doc:one", "skipped_region_count": 0},
    )
    upsert_record(
        ledger,
        "entities",
        "entity:one",
        {"entity_id": "entity:one", "canonical_name": "Visual Hierarchy", "review_state": "reviewed"},
    )
    upsert_record(
        ledger,
        "concepts",
        "concept:one",
        {"concept_id": "concept:one", "label": "attention priority", "review_state": "draft"},
    )
    upsert_record(
        ledger,
        "firewall_events",
        "firewall:one",
        {"event_id": "firewall:one", "decision": "quarantine", "guidance_allowed": False},
    )
    upsert_record(
        ledger,
        "snapshots",
        "snapshot:one",
        {"snapshot_id": "snapshot:one", "ledger_revision": 1},
    )
    upsert_record(
        ledger,
        "skill_packs",
        "skill:one",
        {"compilation_id": "skill:one", "scope_id": "frontend-design"},
    )
    upsert_record(
        ledger,
        "graph_edges",
        "edge:one",
        {
            "edge_id": "edge:one",
            "from_ref": {"kind": "concept", "key": "visual_hierarchy"},
            "to_ref": {"kind": "concept", "key": "attention_priority"},
            "edge_type": "supports",
            "confidence": 0.9,
        },
    )

    payload = build_memory_os_inspector(FakeRuntime(ledger), limit=3)

    assert payload["schema_version"] == "2026-05-13.memory-os-inspector.v1"
    assert payload["write_performed"] is False
    assert payload["runtime"]["status"] == "ok"
    assert payload["jobs"]["items"][0]["job_id"] == "job:one"
    assert payload["transactions"]["items"][0]["transaction_id"] == "txn:one"
    assert payload["coverage_maps"]["items"][0]["coverage_map_id"] == "coverage:one"
    assert payload["entity_registry"]["entities"][0]["canonical_name"] == "Visual Hierarchy"
    assert payload["entity_registry"]["concepts"][0]["label"] == "attention priority"
    assert payload["firewall_queue"]["items"][0]["decision"] == "quarantine"
    assert payload["snapshots"]["items"][0]["snapshot_id"] == "snapshot:one"
    assert payload["skill_packs"]["items"][0]["compilation_id"] == "skill:one"
    assert payload["graph"]["edges"][0]["edge_id"] == "edge:one"
    assert payload["summary"]["coverage_map_count"] == 1
