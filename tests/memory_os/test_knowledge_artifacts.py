import json

from core.memory_os.content_store import ContentAddressedStore
from core.memory_os.knowledge_artifacts import KnowledgeArtifactStore
from core.memory_os.ledger import MemoryOSLedger


def _artifact(summary: str = "Engram is a local-first Memory OS.") -> dict:
    return {
        "artifact_type": "project_capsule",
        "artifact_version": "v0",
        "project": "Engram",
        "generated_at": "2026-05-14T00:00:00+00:00",
        "source_snapshot_id": "memory_os:test",
        "source_refs": [{"key": "engram_direction", "chunk_id": 0, "citation_id": "cit_001"}],
        "summary": summary,
        "current_goals": [],
        "active_decisions": [],
        "constraints": [],
        "open_questions": [],
        "important_entities": [],
        "recent_changes": [],
        "citations": [
            {
                "citation_id": "cit_001",
                "level": "chunk",
                "source": "memory_os",
                "key": "engram_direction",
                "chunk_id": 0,
            }
        ],
        "staleness": {"state": "fresh", "invalidated_by": []},
    }


def test_knowledge_artifact_store_persists_json_payload_and_latest_record(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
    content_store = ContentAddressedStore(tmp_path / "objects")
    artifacts = KnowledgeArtifactStore(ledger, content_store)

    record = artifacts.store_artifact(_artifact(), request_id="req-artifact")
    loaded = artifacts.read_artifact(record["artifact_id"])
    latest = artifacts.read_latest_artifact(
        project="Engram",
        artifact_type="project_capsule",
        artifact_version="v0",
    )

    assert record["record_type"] == "knowledge_artifact"
    assert record["artifact_id"].startswith("knowledge_artifact:")
    assert record["content_artifact_id"].startswith("sha256:")
    assert content_store.path_for(record["content_artifact_id"]).exists()
    assert json.loads(content_store.read_bytes(record["content_artifact_id"]).decode("utf-8"))["summary"] == "Engram is a local-first Memory OS."
    assert loaded["artifact"]["summary"] == "Engram is a local-first Memory OS."
    assert latest["artifact_id"] == record["artifact_id"]
    assert latest["artifact"]["source_refs"][0]["key"] == "engram_direction"


def test_knowledge_artifact_latest_skips_stale_records_when_fresh_required(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
    content_store = ContentAddressedStore(tmp_path / "objects")
    artifacts = KnowledgeArtifactStore(ledger, content_store)
    stale = _artifact("Stale summary")
    stale["staleness"] = {"state": "stale", "invalidated_by": ["newer_source"]}

    artifacts.store_artifact(stale, request_id="req-stale")

    assert artifacts.read_latest_artifact(
        project="Engram",
        artifact_type="project_capsule",
        artifact_version="v0",
        require_fresh=True,
    ) is None

    fresh = artifacts.store_artifact(_artifact("Fresh summary"), request_id="req-fresh")

    latest = artifacts.read_latest_artifact(
        project="Engram",
        artifact_type="project_capsule",
        artifact_version="v0",
        require_fresh=True,
    )

    assert latest["artifact_id"] == fresh["artifact_id"]
    assert latest["artifact"]["summary"] == "Fresh summary"
