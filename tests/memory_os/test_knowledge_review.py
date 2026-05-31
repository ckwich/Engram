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


def test_build_review_preparation_surfaces_knowledge_pr_and_memory_ci(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
    upsert_record(
        ledger,
        "knowledge_branches",
        "kbranch:design",
        {
            "branch_id": "kbranch:design",
            "record_type": "knowledge_branch",
            "name": "Design knowledge branch",
            "metadata": {"project": "Engram"},
            "status": "open",
        },
    )
    upsert_record(
        ledger,
        "knowledge_prs",
        "kpr:design",
        {
            "knowledge_pr_id": "kpr:design",
            "record_type": "knowledge_pr",
            "branch_id": "kbranch:design",
            "title": "Design Knowledge PR",
            "project": "Engram",
            "status": "ci_blocked",
            "source_refs": [{"source_uri": "file:///books/design.pdf"}],
            "document_refs": [{"document_id": "doc_design"}],
            "proposed_operations": [{"operation_id": "op:design", "operation_kind": "memory"}],
            "ci_summary": {"status": "blocked", "blocking_gate_ids": ["gate_provenance"]},
            "blocking_issues": [{"gate_id": "gate_provenance"}],
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
            "status": "blocked",
            "blocking_gate_ids": ["gate_provenance"],
            "gate_results": [
                {
                    "gate_id": "gate_provenance",
                    "status": "blocked",
                    "required": True,
                    "findings": [{"code": "missing_evidence_refs"}],
                }
            ],
        },
    )

    packet = build_review_preparation(
        ledger,
        project="Engram",
        focus=["Knowledge PR"],
        max_records=10,
    )

    assert packet["status"] == "partial"
    assert packet["answer"]["knowledge_pr_count"] == 1
    assert packet["answer"]["memory_ci_run_count"] == 1
    assert packet["answer"]["knowledge_pr_review_items"][0]["knowledge_pr_id"] == "kpr:design"
    assert packet["answer"]["knowledge_pr_review_items"][0]["latest_ci_run_id"] == "mci:design"
    assert [citation["level"] for citation in packet["citations"]] == ["knowledge_pr", "memory_ci"]
    assert packet["write_performed"] is False
    assert packet["active_memory_write_performed"] is False
