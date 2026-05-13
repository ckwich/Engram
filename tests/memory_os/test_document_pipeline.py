from core.document_intelligence import (
    prepare_document_understanding_packet,
    prepare_visual_artifact_record,
)
from core.memory_os.content_store import ContentAddressedStore
from core.memory_os.document_pipeline import DocumentPipeline
from core.memory_os.ledger import MemoryOSLedger


def _disassembly():
    return {
        "record_type": "document_disassembly_preview",
        "write_performed": False,
        "active_memory_write_performed": False,
        "source": {
            "source_uri": "file:///books/design.pdf",
            "source_type": "pdf",
            "media_type": "application/pdf",
            "content_hash": "sha256:" + "a" * 64,
        },
        "document": {
            "document_id": "doc_design",
            "title": "Design Book",
            "source_type": "pdf",
            "media_type": "application/pdf",
            "content_hash": "sha256:" + "a" * 64,
            "page_count": 3,
            "page_limit": 3,
        },
        "pages": [
            {"page_number": 1, "text_status": "text", "visual_review_needed": False},
            {"page_number": 2, "text_status": "low_text", "visual_review_needed": True},
            {"page_number": 3, "text_status": "no_text", "visual_review_needed": True},
        ],
        "text": {
            "content": "# Attention\n\nPeople notice motion before static details.",
            "char_count": 55,
        },
        "image_inventory": {"image_count": 2, "pages_with_images": [2, 3]},
        "quality_seed": {
            "text_pages": [1],
            "low_text_pages": [2],
            "no_text_pages": [3],
            "image_pages": [2, 3],
            "visual_review_needed_pages": [2, 3],
        },
        "visual_artifact_candidates": [
            {"candidate_id": "candidate-2", "page_number": 2},
            {"candidate_id": "candidate-3", "page_number": 3},
        ],
        "error": None,
    }


def test_document_pipeline_materializes_coverage_map_without_promoting_memory(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "engram.sqlite")
    store = ContentAddressedStore(tmp_path / "objects")
    pipeline = DocumentPipeline(ledger, store)
    artifact = prepare_visual_artifact_record(
        document_id="doc_design",
        artifact_type="table",
        source_ref={"source_uri": "file:///books/design.pdf", "page_number": 2},
        extractor_id="agent-native-vision",
        extractor_kind="agent_native",
        page_number=2,
        description="A table comparing attention principles.",
        confidence=0.88,
    )
    low_confidence_figure = prepare_visual_artifact_record(
        document_id="doc_design",
        artifact_type="figure",
        source_ref={"source_uri": "file:///books/design.pdf", "page_number": 3},
        extractor_id="agent-native-vision",
        extractor_kind="agent_native",
        page_number=3,
        description="A figure about visual hierarchy.",
        confidence=0.42,
    )
    packet = prepare_document_understanding_packet(
        document_record={
            "document_id": "doc_design",
            "title": "Design Book",
            "source_uri": "file:///books/design.pdf",
            "source_type": "pdf",
            "content_hash": "sha256:" + "a" * 64,
            "media_type": "application/pdf",
        },
        analysis={
            "claims": ["People notice motion before static details."],
            "concepts": [{"name": "attention priority", "confidence": 0.8}],
        },
        visual_artifacts=[artifact, low_confidence_figure],
    )

    result = pipeline.materialize_document_job(
        _disassembly(),
        visual_artifacts=[artifact, low_confidence_figure],
        understanding_packet=packet,
    )

    coverage = result["coverage_map"]
    assert result["status"] == "succeeded"
    assert result["active_memory_write_performed"] is False
    assert coverage["page_count"] == 3
    assert coverage["text_page_count"] == 1
    assert coverage["visual_needed_pages"] == [2, 3]
    assert coverage["interpreted_visual_count"] == 2
    assert coverage["table_count"] == 1
    assert coverage["figure_count"] == 1
    assert coverage["chunk_count"] == 1
    assert coverage["claim_count"] == 1
    assert coverage["concept_count"] == 1
    assert coverage["graph_proposal_count"] >= 1
    assert coverage["low_confidence_region_count"] >= 1
    assert coverage["skipped_region_count"] == 0


def test_document_pipeline_preserves_licensing_and_quote_policy(tmp_path):
    pipeline = DocumentPipeline(
        MemoryOSLedger(tmp_path / "engram.sqlite"),
        ContentAddressedStore(tmp_path / "objects"),
    )

    result = pipeline.materialize_document_job(
        _disassembly(),
        licensing={
            "quote_policy": "short_quotes_only",
            "citation_format": "page",
            "skill_export_direct_excerpts": False,
        },
    )

    assert result["coverage_map"]["licensing"] == {
        "quote_policy": "short_quotes_only",
        "citation_format": "page",
        "skill_export_direct_excerpts": False,
    }
    assert result["document"]["licensing"]["quote_policy"] == "short_quotes_only"
