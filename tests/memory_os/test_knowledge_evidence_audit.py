from __future__ import annotations

from core.memory_os.knowledge_audit import build_evidence_audit
from core.memory_os.knowledge_contract import validate_knowledge_response
from core.memory_os.runtime import MemoryOSRuntime
from tests.memory_os.test_knowledge_document_orientation import _review_packet


def test_evidence_audit_reports_missing_document_coverage_from_ledgered_artifact(tmp_path):
    runtime = MemoryOSRuntime(tmp_path / "memory_os")
    runtime.initialize()
    prepared = runtime.prepare_document_artifact_store(_review_packet(tmp_path))
    runtime.store_document_artifact(prepared["prepared_transaction_id"], accept=True)

    audit = build_evidence_audit(
        runtime.ledger,
        project="Engram",
        focus=["Design"],
        max_records=10,
    )

    codes = {finding["code"] for finding in audit["answer"]["findings"]}
    assert audit["status"] == "partial"
    assert "missing_ocr_coverage" in codes
    assert "missing_table_coverage" in codes
    assert "unresolved_visual_evidence" in codes
    assert audit["citations"][0]["level"] == "artifact"


def test_query_knowledge_evidence_audit_response_validates(tmp_path):
    runtime = MemoryOSRuntime(tmp_path / "memory_os")
    runtime.initialize()
    prepared = runtime.prepare_document_artifact_store(_review_packet(tmp_path))
    runtime.store_document_artifact(prepared["prepared_transaction_id"], accept=True)

    response = runtime.query_knowledge(
        {
            "request_id": "req-audit",
            "ask": {
                "goal": "Audit document evidence.",
                "task_type": "evidence_audit",
                "project": "Engram",
                "focus": ["Design"],
            },
        }
    )

    assert response["status"] == "partial"
    assert validate_knowledge_response(response)["valid"] is True
