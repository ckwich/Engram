from core.memory_os._records import upsert_record
from core.memory_os.knowledge_audit import build_evidence_audit
from core.memory_os.ledger import MemoryOSLedger


def test_build_evidence_audit_reports_stale_citation_and_coverage_risks(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
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
        "knowledge_artifacts",
        "artifact:stale",
        {
            "artifact_id": "artifact:stale",
            "artifact_type": "project_capsule",
            "artifact_version": "v0",
            "project": "Engram",
            "citations": [{"citation_id": "cit_bad"}],
            "staleness": {"state": "stale", "invalidated_by": ["doc_design"]},
        },
    )
    upsert_record(
        ledger,
        "retrieval_receipts",
        "coverage:doc_design",
        {
            "coverage_map_id": "coverage:doc_design",
            "document_id": "doc_design",
            "chunk_count": 0,
            "claim_count": 2,
            "skipped_region_count": 1,
            "low_confidence_region_count": 1,
        },
    )
    upsert_record(
        ledger,
        "drafts",
        "draft:doc_design",
        {
            "draft_id": "draft:doc_design",
            "project": "Engram",
            "document_id": "doc_design",
            "candidate_graph_edges": [{"edge_type": "supports"}],
        },
    )

    audit = build_evidence_audit(
        ledger,
        project="Engram",
        focus=["design"],
        max_records=10,
    )

    assert audit["status"] == "partial"
    assert audit["answer"]["audit_type"] == "evidence_audit"
    assert audit["answer"]["finding_count"] == 5
    assert [finding["code"] for finding in audit["answer"]["findings"]] == [
        "stale_artifact",
        "invalid_citation",
        "coverage_risk",
        "weak_claim_support",
        "graph_proposal_needs_evidence",
    ]
    assert audit["citations"] == [
        {
            "citation_id": "cit_001",
            "level": "artifact",
            "source": "memory_os",
            "artifact_id": "artifact:stale",
        },
        {
            "citation_id": "cit_002",
            "level": "document",
            "source": "memory_os",
            "document_id": "doc_design",
            "source_ref": "file:///books/design.pdf",
        },
    ]
    assert audit["source_reads"] == 4


def test_build_evidence_audit_returns_ok_for_clean_records(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
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
        "knowledge_artifacts",
        "artifact:fresh",
        {
            "artifact_id": "artifact:fresh",
            "artifact_type": "project_capsule",
            "artifact_version": "v0",
            "project": "Engram",
            "citations": [
                {
                    "citation_id": "cit_001",
                    "level": "document",
                    "source": "memory_os",
                    "document_id": "doc_design",
                }
            ],
            "staleness": {"state": "fresh", "invalidated_by": []},
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
            "skipped_region_count": 0,
            "low_confidence_region_count": 0,
        },
    )

    audit = build_evidence_audit(
        ledger,
        project="Engram",
        focus=["design"],
        max_records=10,
    )

    assert audit["status"] == "ok"
    assert audit["answer"]["finding_count"] == 0
    assert audit["errors"] == []


def test_build_evidence_audit_returns_no_answer_without_records(tmp_path):
    audit = build_evidence_audit(
        MemoryOSLedger(tmp_path / "ledger.sqlite3"),
        project="Engram",
        focus=[],
        max_records=10,
    )

    assert audit["status"] == "no_answer"
    assert audit["answer"] is None
    assert audit["citations"] == []


def test_build_evidence_audit_reports_knowledge_pr_memory_ci_findings(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
    upsert_record(
        ledger,
        "knowledge_prs",
        "kpr:blocked",
        {
            "knowledge_pr_id": "kpr:blocked",
            "record_type": "knowledge_pr",
            "title": "Knowledge PR coverage audit",
            "project": "Engram",
            "status": "ci_blocked",
            "document_refs": [{"document_id": "doc_design"}],
            "proposed_operations": [{"operation_id": "op:missing-evidence", "operation_kind": "memory"}],
            "ci_summary": {
                "status": "blocked",
                "blocking_gate_ids": ["gate_document_coverage"],
            },
        },
    )
    upsert_record(
        ledger,
        "memory_ci_runs",
        "mci:blocked",
        {
            "ci_run_id": "mci:blocked",
            "record_type": "memory_ci_run",
            "knowledge_pr_id": "kpr:blocked",
            "status": "blocked",
            "blocking_gate_ids": ["gate_document_coverage"],
            "gate_results": [
                {
                    "gate_id": "gate_document_coverage",
                    "status": "blocked",
                    "required": True,
                    "findings": [{"document_id": "doc_design"}],
                }
            ],
        },
    )

    audit = build_evidence_audit(
        ledger,
        project="Engram",
        focus=["coverage audit"],
        max_records=10,
    )

    assert audit["status"] == "partial"
    assert audit["answer"]["knowledge_pr_count"] == 1
    assert audit["answer"]["memory_ci_run_count"] == 1
    assert audit["answer"]["ci_blocked_count"] == 1
    assert [finding["code"] for finding in audit["answer"]["findings"]] == [
        "memory_ci_blocked",
        "knowledge_pr_missing_provenance",
        "knowledge_pr_missing_document_completion",
    ]
    assert [citation["level"] for citation in audit["citations"]] == ["knowledge_pr", "memory_ci"]
    assert audit["write_performed"] is False
