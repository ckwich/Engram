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
    assert coverage["visual_covered_pages"] == [2, 3]
    assert coverage["missing_visual_pages"] == []
    assert coverage["ocr_needed_pages"] == [2, 3]
    assert coverage["ocr_covered_pages"] == []
    assert coverage["missing_ocr_pages"] == [2, 3]
    assert coverage["table_needed_pages"] == []
    assert coverage["table_covered_pages"] == []
    assert coverage["missing_table_pages"] == []
    assert coverage["coverage_complete"] is False
    assert coverage["interpreted_visual_count"] == 2
    assert coverage["table_count"] == 1
    assert coverage["figure_count"] == 1
    assert coverage["chunk_count"] == 1
    assert coverage["claim_count"] == 1
    assert coverage["concept_count"] == 1
    assert coverage["graph_proposal_count"] >= 1
    assert coverage["low_confidence_region_count"] >= 1
    assert coverage["skipped_region_count"] == 0


def test_document_pipeline_reports_ocr_and_table_coverage_from_visual_artifacts(tmp_path):
    ledger = MemoryOSLedger(tmp_path / "engram.sqlite")
    store = ContentAddressedStore(tmp_path / "objects")
    pipeline = DocumentPipeline(ledger, store)
    disassembly = _disassembly()
    disassembly["pages"][1]["table_candidate"] = True
    disassembly["quality_seed"]["table_candidate_pages"] = [2]
    ocr = prepare_visual_artifact_record(
        document_id="doc_design",
        artifact_type="ocr_block",
        source_ref={"source_uri": "file:///books/design.pdf", "page_number": 2},
        extractor_id="agent-native-vision",
        extractor_kind="agent_native",
        page_number=2,
        text="OCR text for page two.",
        confidence=0.91,
    )
    table = prepare_visual_artifact_record(
        document_id="doc_design",
        artifact_type="table",
        source_ref={"source_uri": "file:///books/design.pdf", "page_number": 2},
        extractor_id="agent-native-vision",
        extractor_kind="agent_native",
        page_number=2,
        description="No table is present after review.",
        confidence=0.9,
        metadata={"table_present": False},
    )
    figure = prepare_visual_artifact_record(
        document_id="doc_design",
        artifact_type="figure",
        source_ref={"source_uri": "file:///books/design.pdf", "page_number": 3},
        extractor_id="agent-native-vision",
        extractor_kind="agent_native",
        page_number=3,
        description="A reviewed figure about visual hierarchy.",
        confidence=0.84,
    )

    result = pipeline.materialize_document_job(
        disassembly,
        visual_artifacts=[ocr, table, figure],
    )

    coverage = result["coverage_map"]
    assert coverage["visual_covered_pages"] == [2, 3]
    assert coverage["missing_visual_pages"] == []
    assert coverage["ocr_covered_pages"] == [2]
    assert coverage["missing_ocr_pages"] == [3]
    assert coverage["table_covered_pages"] == [2]
    assert coverage["missing_table_pages"] == []
    assert coverage["coverage_complete"] is False


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


def test_document_pipeline_preserves_chunks_from_multiple_page_windows(tmp_path):
    from core.memory_os._records import list_records
    from core.memory_os.content_store import ContentAddressedStore
    from core.memory_os.document_pipeline import DocumentPipeline
    from core.memory_os.ledger import MemoryOSLedger

    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
    ledger.initialize()
    store = ContentAddressedStore(tmp_path / "objects")
    pipeline = DocumentPipeline(ledger, store)

    first = {
        "document": {
            "document_id": "doc_windowed_book",
            "title": "Windowed Book",
            "page_count": 4,
            "page_range": {"start": 1, "end": 2},
        },
        "source": {"source_uri": "file:///book.pdf", "content_hash": "sha256:book"},
        "pages": [
            {"page_number": 1, "text_status": "text", "visual_review_needed": False},
            {"page_number": 2, "text_status": "text", "visual_review_needed": False},
        ],
        "text": {"content": "# Window One\n\nAlpha page text."},
        "quality_seed": {"text_pages": [1, 2], "visual_review_needed_pages": []},
    }
    second = {
        "document": {
            "document_id": "doc_windowed_book",
            "title": "Windowed Book",
            "page_count": 4,
            "page_range": {"start": 3, "end": 4},
        },
        "source": {"source_uri": "file:///book.pdf", "content_hash": "sha256:book"},
        "pages": [
            {"page_number": 3, "text_status": "text", "visual_review_needed": False},
            {"page_number": 4, "text_status": "text", "visual_review_needed": False},
        ],
        "text": {"content": "# Window Two\n\nBeta page text."},
        "quality_seed": {"text_pages": [3, 4], "visual_review_needed_pages": []},
    }

    pipeline.materialize_document_job(first, ingestion_id="ingest-book", window_index=0)
    pipeline.materialize_document_job(second, ingestion_id="ingest-book", window_index=1)

    chunks = sorted(list_records(ledger, "chunks"), key=lambda item: item["chunk_record_id"])
    assert len(chunks) == 2
    assert chunks[0]["chunk_record_id"] == "doc_windowed_book:ingestion:ingest-book:window:0000:chunk:10000"
    assert chunks[0]["local_chunk_id"] == 0
    assert chunks[0]["chunk_id"] == 10000
    assert chunks[0]["ingestion_id"] == "ingest-book"
    assert chunks[0]["window_index"] == 0
    assert chunks[0]["page_range"] == {"start": 1, "end": 2}
    assert chunks[0]["text"] == "# Window One\n\nAlpha page text."
    assert chunks[1]["chunk_record_id"] == "doc_windowed_book:ingestion:ingest-book:window:0001:chunk:30000"
    assert chunks[1]["local_chunk_id"] == 0
    assert chunks[1]["chunk_id"] == 30000
    assert chunks[1]["ingestion_id"] == "ingest-book"
    assert chunks[1]["window_index"] == 1
    assert chunks[1]["page_range"] == {"start": 3, "end": 4}
    assert chunks[1]["text"] == "# Window Two\n\nBeta page text."

    receipts = list_records(ledger, "retrieval_receipts")
    assert len(receipts) == 2
    assert len({receipt["coverage_map_id"] for receipt in receipts}) == 2


def test_document_pipeline_reuses_window_chunks_during_completion_materialization(tmp_path):
    from core.memory_os._records import list_records

    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
    store = ContentAddressedStore(tmp_path / "objects")
    pipeline = DocumentPipeline(ledger, store)
    disassembly = _disassembly()
    disassembly["document"]["page_range"] = {"start": 1, "end": 1}

    pipeline.materialize_document_job(
        disassembly,
        ingestion_id="ingest-design",
        window_index=0,
    )
    pipeline.materialize_document_job(disassembly)

    chunks = list_records(ledger, "chunks")
    assert len(chunks) == 1
    assert chunks[0]["chunk_record_id"] == "doc_design:ingestion:ingest-design:window:0000:chunk:10000"
    assert chunks[0]["ingestion_id"] == "ingest-design"
    assert chunks[0]["window_index"] == 0


def test_document_pipeline_keeps_default_chunk_record_ids_legacy_compatible(tmp_path):
    from core.memory_os._records import list_records

    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
    store = ContentAddressedStore(tmp_path / "objects")
    pipeline = DocumentPipeline(ledger, store)

    pipeline.materialize_document_job(_disassembly())

    chunks = list_records(ledger, "chunks")
    assert len(chunks) == 1
    assert chunks[0]["chunk_record_id"] == "doc_design:chunk:0"
    assert chunks[0]["chunk_id"] == 0
    assert chunks[0]["ingestion_id"] is None
    assert chunks[0]["window_index"] is None


def test_document_pipeline_ignores_invalid_optional_page_window_metadata(tmp_path):
    from core.memory_os._records import list_records

    ledger = MemoryOSLedger(tmp_path / "ledger.sqlite3")
    store = ContentAddressedStore(tmp_path / "objects")
    pipeline = DocumentPipeline(ledger, store)
    disassembly = _disassembly()
    disassembly["document"]["page_range"] = {"start": "not-a-number", "end": "also-not-a-number"}

    pipeline.materialize_document_job(
        disassembly,
        ingestion_id="ingest-invalid",
        window_index="first-window",
    )

    chunks = list_records(ledger, "chunks")
    assert len(chunks) == 1
    assert chunks[0]["chunk_record_id"] == "doc_design:ingestion:ingest-invalid:window:first-window:chunk:0"
    assert chunks[0]["chunk_id"] == 0
    assert chunks[0]["page_range"] == {"start": "not-a-number", "end": "also-not-a-number"}
    assert chunks[0]["window_index"] == "first-window"
