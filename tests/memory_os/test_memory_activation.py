from core.memory_os._records import list_records
from core.memory_os.ledger import MemoryOSLedger
from core.memory_os.memory_activation import score_activation, store_activation_receipt


def test_activation_prefers_canonical_source_backed_project_matches():
    score = score_activation(
        memory={
            "memory_type": "decision",
            "trust_state": "source_backed",
            "canonical": True,
            "project": "/repo/Engram",
            "updated_at": "2026-05-26T00:00:00+00:00",
        },
        query_context={"project": "/repo/Engram", "now": "2026-05-26T01:00:00+00:00"},
    )

    assert score["activation_score"] > 0.75
    assert "canonical" in score["signals"]
    assert "project_match" in score["signals"]


def test_activation_never_marks_memory_deleted():
    score = score_activation(
        memory={"trust_state": "superseded", "status": "active"},
        query_context={"now": "2026-05-26T01:00:00+00:00"},
    )

    assert score["action"] == "rank"
    assert score["activation_score"] >= 0.0


def test_activation_project_match_accepts_alias_filter_lists():
    score = score_activation(
        memory={"project": "/repo/Engram", "trust_state": "reviewed"},
        query_context={"project": ["/repo/Other", "/repo/Engram"]},
    )

    assert "project_match" in score["signals"]


def test_activation_receipt_stores_compact_refs_without_memory_bodies(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
    ledger.initialize()

    receipt = store_activation_receipt(
        ledger,
        query_context={
            "query": "runtime choice",
            "project": "/repo/Engram",
            "now": "2026-05-26T01:00:00+00:00",
        },
        selected_refs=[
            {
                "kind": "memory",
                "key": "engram_runtime_choice",
                "activation_score": 0.83,
                "content": "body must not be persisted",
            }
        ],
        omitted_refs=[{"kind": "memory", "key": "engram_legacy_note", "reason": "budget"}],
    )

    rows = list_records(ledger, "activation_receipts")
    assert receipt["receipt_id"].startswith("activation:")
    assert rows == [receipt]
    assert rows[0]["query_hash"].startswith("sha256:")
    assert rows[0]["selected_refs"] == [
        {"kind": "memory", "key": "engram_runtime_choice", "activation_score": 0.83}
    ]
    assert rows[0]["omitted_refs"] == [
        {"kind": "memory", "key": "engram_legacy_note", "reason": "budget"}
    ]
    assert "runtime choice" not in str(rows[0])
    assert "body must not be persisted" not in str(rows[0])


def test_activation_receipt_hashes_free_form_omission_reasons(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
    ledger.initialize()

    receipt = store_activation_receipt(
        ledger,
        query_context={"query": "activation audit", "project": "/repo/Engram"},
        selected_refs=[],
        omitted_refs=[
            {
                "kind": "memory",
                "key": "private_note",
                "reason": "raw user secret should not appear",
            }
        ],
    )

    omitted = receipt["omitted_refs"][0]
    assert omitted["reason"] == "free_form_reason_redacted"
    assert omitted["reason_hash"].startswith("sha256:")
    assert "raw user secret" not in str(receipt)


def test_activation_receipt_ids_do_not_collide_across_raw_queries(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
    ledger.initialize()
    common_refs = [{"kind": "memory", "key": "engram_runtime_choice"}]

    first = store_activation_receipt(
        ledger,
        query_context={"query": "first private query", "project": "/repo/Engram"},
        selected_refs=common_refs,
    )
    second = store_activation_receipt(
        ledger,
        query_context={"query": "second private query", "project": "/repo/Engram"},
        selected_refs=common_refs,
    )

    assert first["receipt_id"] != second["receipt_id"]
    assert len(list_records(ledger, "activation_receipts")) == 2
