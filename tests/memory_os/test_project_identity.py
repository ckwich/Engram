from __future__ import annotations

from core.memory_os._records import list_records, upsert_record
from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.project_identity import (
    PROJECT_ALIAS_SCOPE,
    resolve_project_filter_values,
    upsert_project_aliases,
)


def test_project_alias_registry_preserves_source_labels_and_resolves_variants(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")

    entity = upsert_project_aliases(
        ledger,
        canonical_project_id="project:engram",
        canonical_label="Engram",
        aliases=["C:\\Dev\\Engram", "C:/Dev/Engram", "c:/dev/engram"],
        created_by="migration-test",
    )

    assert entity["entity_type"] == "project"
    assert entity["canonical_project_id"] == "project:engram"
    assert entity["canonical_label"] == "Engram"
    assert entity["aliases"] == ["C:\\Dev\\Engram", "C:/Dev/Engram", "c:/dev/engram", "Engram"]
    assert resolve_project_filter_values(ledger, "Engram") == [
        "C:/Dev/Engram",
        "C:\\Dev\\Engram",
        "Engram",
        "c:/dev/engram",
    ]
    assert resolve_project_filter_values(ledger, "C:\\Dev\\Engram") == [
        "C:/Dev/Engram",
        "C:\\Dev\\Engram",
        "Engram",
        "c:/dev/engram",
    ]
    assert resolve_project_filter_values(ledger, "Engram", exact=True) == ["Engram"]

    aliases = list_records(ledger, "aliases")
    assert {alias["alias_scope"] for alias in aliases} == {PROJECT_ALIAS_SCOPE}
    assert {alias["label"] for alias in aliases} == set(entity["aliases"])


def test_project_filter_values_infer_path_aliases_from_existing_records(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
    upsert_record(ledger, "memories", "alpha", {"key": "alpha", "project": "Engram"})
    upsert_record(ledger, "memories", "beta", {"key": "beta", "project": "C:\\Dev\\Engram"})
    upsert_record(ledger, "documents", "doc:one", {"document_id": "doc:one", "project": "C:/Dev/Engram"})
    upsert_record(ledger, "memories", "other", {"key": "other", "project": "Other"})

    assert resolve_project_filter_values(ledger, "Engram") == [
        "C:/Dev/Engram",
        "C:\\Dev\\Engram",
        "Engram",
    ]
    assert resolve_project_filter_values(ledger, "C:/Dev/Engram") == [
        "C:/Dev/Engram",
        "C:\\Dev\\Engram",
        "Engram",
    ]
    assert resolve_project_filter_values(ledger, "Other") == ["Other"]
