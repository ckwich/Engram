from core.memory_os._records import upsert_record
from core.memory_os.knowledge_artifact_families import build_artifact_family_packet
from core.memory_os.ledger import MemoryOSLedger


def test_entity_profile_requires_cited_entity_evidence(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
    upsert_record(
        ledger,
        "entities",
        "entity:attention",
        {
            "entity_id": "entity:attention",
            "canonical_name": "Attention Priority",
            "entity_type": "concept",
            "project": "Engram",
            "source_refs": [{"document_id": "doc_design", "source_ref": "file:///books/design.pdf"}],
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
            "source_ref": {"source_uri": "file:///books/design.pdf"},
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
        },
    )

    packet = build_artifact_family_packet(
        ledger,
        artifact_family="entity_profile",
        project="Engram",
        focus=["attention"],
        max_records=10,
    )

    assert packet["status"] == "ok"
    assert packet["answer"]["artifact_family"] == "entity_profile"
    assert packet["answer"]["items"][0]["entity_id"] == "entity:attention"
    assert packet["answer"]["evidence_audit"]["status"] == "ok"
    assert packet["citations"] == [
        {
            "citation_id": "cit_001",
            "level": "document",
            "source": "memory_os",
            "document_id": "doc_design",
            "source_ref": "file:///books/design.pdf",
        }
    ]


def test_entity_profile_returns_no_answer_when_entities_lack_evidence(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
    upsert_record(
        ledger,
        "entities",
        "entity:attention",
        {
            "entity_id": "entity:attention",
            "canonical_name": "Attention Priority",
            "entity_type": "concept",
            "project": "Engram",
        },
    )

    packet = build_artifact_family_packet(
        ledger,
        artifact_family="entity_profile",
        project="Engram",
        focus=["attention"],
        max_records=10,
    )

    assert packet["status"] == "no_answer"
    assert packet["answer"] is None
    assert packet["errors"][0]["code"] == "missing_cited_evidence"


def test_implementation_context_treats_missing_audit_as_optional_metadata(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
    upsert_record(
        ledger,
        "chunks",
        "impl:chunk:0",
        {
            "chunk_record_id": "impl:chunk:0",
            "memory_key": "impl_context",
            "document_id": "impl_context:chunk:0",
            "chunk_id": 0,
            "project": "Engram",
            "domain": "code",
            "text": "Use query_knowledge before loading implementation context.",
        },
    )

    packet = build_artifact_family_packet(
        ledger,
        artifact_family="implementation_context",
        project="Engram",
        focus=["query_knowledge"],
        max_records=10,
    )

    assert packet["status"] == "ok"
    assert packet["answer"]["artifact_family"] == "implementation_context"
    assert packet["answer"]["evidence_audit"]["status"] == "no_answer"
    assert packet["answer"]["evidence_audit"]["required"] is False
    assert packet["omissions"] == [
        {
            "code": "evidence_audit_unavailable",
            "message": "No artifact, coverage, or draft audit records matched this implementation_context request.",
        }
    ]
    assert packet["errors"] == []
    assert packet["citations"] == [
        {
            "citation_id": "cit_001",
            "level": "chunk",
            "source": "memory_os",
            "key": "impl_context",
            "chunk_id": 0,
        }
    ]


def test_implementation_context_extracts_next_polish_target_from_brief_text(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
    upsert_record(
        ledger,
        "chunks",
        "old_impl_polish:chunk:0",
        {
            "chunk_record_id": "old_impl_polish:chunk:0",
            "memory_key": "old_impl_polish",
            "document_id": "old_impl_polish:chunk:0",
            "chunk_id": 0,
            "project": "Engram",
            "domain": "implementation",
            "updated_at": "2026-05-13T00:00:00+00:00",
            "text": (
                "Earlier query_knowledge implementation_context planning note. "
                "Next recommended slice: build an older stabilization pack that has already been completed."
            ),
        },
    )
    upsert_record(
        ledger,
        "chunks",
        "impl_polish:chunk:0",
        {
            "chunk_record_id": "impl_polish:chunk:0",
            "memory_key": "impl_polish",
            "document_id": "impl_polish:chunk:0",
            "chunk_id": 0,
            "project": "Engram",
            "domain": "implementation",
            "updated_at": "2026-05-14T00:00:00+00:00",
            "text": (
                "Validated behavior: query_knowledge implementation_context returns a cited brief. "
                "Opinion from agent-use test: the payload is useful, but continuation cues are thin. "
                "Main next polish target is improve implementation_context next_action extraction "
                "so recent slice next steps surface reliably."
            ),
        },
    )

    packet = build_artifact_family_packet(
        ledger,
        artifact_family="implementation_context",
        project="Engram",
        focus=["query_knowledge", "implementation_context"],
        max_records=10,
    )

    assert packet["status"] == "ok"
    assert packet["answer"]["brief"]["next_actions"] == [
        "improve implementation_context next_action extraction so recent slice next steps surface reliably."
    ]
