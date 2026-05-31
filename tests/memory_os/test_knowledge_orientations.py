from core.memory_os._records import upsert_record
from core.memory_os.knowledge_orientations import (
    build_document_orientation,
    build_source_orientation,
)
from core.memory_os.ledger import MemoryOSLedger


def _seed_document_records(ledger):
    upsert_record(
        ledger,
        "sources",
        "source-design",
        {
            "source_uri": "file:///books/design.pdf",
            "source_type": "pdf",
            "project": "Engram",
        },
    )
    upsert_record(
        ledger,
        "documents",
        "doc_design",
        {
            "document_id": "doc_design",
            "title": "Design Book",
            "project": "Engram",
            "source_ref": {
                "source_uri": "file:///books/design.pdf",
                "source_type": "pdf",
            },
            "document": {"page_count": 3},
        },
    )
    upsert_record(
        ledger,
        "chunks",
        "doc_design:chunk:0",
        {
            "document_id": "doc_design",
            "chunk_id": 0,
            "text": "# Attention\n\nPeople notice motion before static details.",
        },
    )
    upsert_record(
        ledger,
        "retrieval_receipts",
        "coverage:doc_design",
        {
            "coverage_map_id": "coverage:doc_design",
            "document_id": "doc_design",
            "page_count": 3,
            "chunk_count": 1,
            "claim_count": 1,
            "visual_needed_pages": [2],
            "interpreted_visual_count": 1,
            "low_confidence_region_count": 0,
            "skipped_region_count": 0,
        },
    )


def test_build_source_orientation_reads_source_document_and_coverage_records(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
    _seed_document_records(ledger)

    orientation = build_source_orientation(
        ledger,
        project="Engram",
        focus=["design"],
        max_records=10,
    )

    assert orientation["status"] == "ok"
    assert orientation["answer"]["orientation_type"] == "source_orientation"
    assert orientation["answer"]["source_count"] == 1
    assert orientation["answer"]["document_count"] == 1
    assert orientation["answer"]["documents"][0]["document_id"] == "doc_design"
    assert orientation["answer"]["documents"][0]["coverage"]["claim_count"] == 1
    assert orientation["citations"] == [
        {
            "citation_id": "cit_001",
            "level": "document",
            "source": "memory_os",
            "document_id": "doc_design",
            "source_ref": "file:///books/design.pdf",
        }
    ]
    assert orientation["source_reads"] == 4


def test_build_document_orientation_attaches_related_knowledge_pr_state(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
    _seed_document_records(ledger)
    upsert_record(
        ledger,
        "knowledge_prs",
        "kpr:design",
        {
            "knowledge_pr_id": "kpr:design",
            "record_type": "knowledge_pr",
            "title": "Design document Knowledge PR",
            "project": "Engram",
            "status": "mergeable",
            "document_refs": [{"document_id": "doc_design"}],
            "source_refs": [{"source_uri": "file:///books/design.pdf"}],
            "proposed_operations": [
                {
                    "operation_id": "op:design",
                    "operation_kind": "memory",
                    "evidence_refs": [{"document_id": "doc_design"}],
                }
            ],
            "ci_summary": {"status": "passed", "blocking_gate_ids": []},
        },
    )
    upsert_record(
        ledger,
        "memory_ci_runs",
        "mci:design",
        {
            "ci_run_id": "mci:design",
            "record_type": "memory_ci_run",
            "knowledge_pr_id": "kpr:design",
            "status": "passed",
            "blocking_gate_ids": [],
            "gate_results": [],
        },
    )

    orientation = build_document_orientation(
        ledger,
        project="Engram",
        focus=["design"],
        max_records=10,
    )

    assert orientation["answer"]["knowledge_pr_state"]["knowledge_pr_count"] == 1
    assert orientation["answer"]["knowledge_pr_state"]["mergeable_count"] == 1
    assert orientation["answer"]["knowledge_pr_state"]["items"][0]["knowledge_pr_id"] == "kpr:design"
    assert [citation["level"] for citation in orientation["citations"]] == [
        "document",
        "knowledge_pr",
        "memory_ci",
    ]


def test_build_document_orientation_returns_partial_for_missing_chunk_evidence(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
    upsert_record(
        ledger,
        "documents",
        "doc_sparse",
        {
            "document_id": "doc_sparse",
            "title": "Sparse Doc",
            "project": "Engram",
            "source_ref": {"source_uri": "file:///books/sparse.pdf"},
            "document": {"page_count": 2},
        },
    )

    orientation = build_document_orientation(
        ledger,
        project="Engram",
        focus=["sparse"],
        max_records=10,
    )

    assert orientation["status"] == "partial"
    assert orientation["answer"]["documents"][0]["chunk_count"] == 0
    assert orientation["errors"] == [
        {
            "code": "orientation_incomplete",
            "message": "Document orientation is missing required evidence or usable ingestion state.",
        }
    ]
    assert orientation["omissions"] == [
        {
            "code": "missing_chunks",
            "message": "doc_sparse has no chunk evidence.",
        },
        {
            "code": "missing_coverage",
            "message": "doc_sparse has no coverage map.",
        },
    ]


def test_build_document_orientation_returns_no_answer_without_matching_records(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")

    orientation = build_document_orientation(
        ledger,
        project="Engram",
        focus=["missing"],
        max_records=10,
    )

    assert orientation["status"] == "no_answer"
    assert orientation["answer"] is None
    assert orientation["citations"] == []
