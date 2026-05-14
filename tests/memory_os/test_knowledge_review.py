from core.memory_os._records import list_records, upsert_record
from core.memory_os.knowledge_review import build_review_preparation
from core.memory_os.ledger import MemoryOSLedger


def _seed_review_records(ledger):
    upsert_record(
        ledger,
        "documents",
        "doc_design",
        {
            "document_id": "doc_design",
            "title": "Design Book",
            "project": "Engram",
            "source_ref": {"source_uri": "file:///books/design.pdf"},
        },
    )
    upsert_record(
        ledger,
        "drafts",
        "draft:doc_design",
        {
            "draft_id": "draft:doc_design",
            "record_type": "document_draft",
            "document_id": "doc_design",
            "project": "Engram",
            "review_status": "candidate",
            "promotion_required": True,
            "proposed_memories": [{"key": "design_attention"}],
            "candidate_graph_edges": [{"edge_type": "supports"}],
        },
    )
    upsert_record(
        ledger,
        "retrieval_receipts",
        "coverage:doc_design",
        {
            "coverage_map_id": "coverage:doc_design",
            "document_id": "doc_design",
            "chunk_count": 2,
            "claim_count": 1,
            "low_confidence_region_count": 1,
            "skipped_region_count": 0,
            "visual_needed_pages": [2],
            "interpreted_visual_count": 1,
        },
    )


def test_build_review_preparation_reads_drafts_and_quality_warnings(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
    _seed_review_records(ledger)

    packet = build_review_preparation(
        ledger,
        project="Engram",
        focus=["design"],
        max_records=10,
    )

    assert packet["status"] == "partial"
    assert packet["answer"]["packet_type"] == "review_preparation"
    assert packet["answer"]["draft_count"] == 1
    assert packet["answer"]["quality_warning_count"] == 1
    assert packet["answer"]["review_items"][0] == {
        "draft_id": "draft:doc_design",
        "record_type": "document_draft",
        "document_id": "doc_design",
        "document_title": "Design Book",
        "review_status": "candidate",
        "promotion_required": True,
        "proposed_memory_count": 1,
        "candidate_graph_edge_count": 1,
        "quality_warning_count": 1,
    }
    assert packet["answer"]["quality_warnings"] == [
        {
            "code": "low_confidence_regions",
            "severity": "medium",
            "document_id": "doc_design",
            "message": "doc_design has low-confidence extracted regions.",
        }
    ]
    assert packet["citations"] == [
        {
            "citation_id": "cit_001",
            "level": "document",
            "source": "memory_os",
            "document_id": "doc_design",
            "source_ref": "file:///books/design.pdf",
        }
    ]
    assert packet["source_reads"] == 3


def test_build_review_preparation_returns_no_answer_without_review_records(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")

    packet = build_review_preparation(
        ledger,
        project="Engram",
        focus=["missing"],
        max_records=10,
    )

    assert packet["status"] == "no_answer"
    assert packet["answer"] is None
    assert packet["citations"] == []


def test_build_review_preparation_does_not_write_records(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
    _seed_review_records(ledger)
    before = {table: len(list_records(ledger, table)) for table in ("drafts", "memories", "transactions")}

    packet = build_review_preparation(
        ledger,
        project="Engram",
        focus=[],
        max_records=10,
    )

    after = {table: len(list_records(ledger, table)) for table in ("drafts", "memories", "transactions")}
    assert packet["write_performed"] is False
    assert packet["active_memory_write_performed"] is False
    assert after == before
