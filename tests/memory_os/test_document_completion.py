from __future__ import annotations

import hashlib
import json

from core.document_intelligence import (
    prepare_document_promotion_transaction,
    prepare_document_record,
    prepare_document_understanding_packet,
    prepare_visual_extraction_request,
    preview_visual_extraction,
)
from core.graph_store import JsonGraphStore
from core.memory_os._records import list_records, read_record, upsert_record
from core.memory_os.document_completion_assessment import DocumentCompletionAssessmentService
from core.memory_os.knowledge_contract import validate_knowledge_response
from core.memory_os.runtime import MemoryOSRuntime
from core.vector_index import InMemoryVectorIndex


def _embed(text):
    return [1.0, 0.0] if "design" in str(text).lower() else [0.0, 1.0]


def _runtime(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path / "memory_os",
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
        graph_store=JsonGraphStore(tmp_path / "edges.json"),
    )
    runtime.initialize()
    return runtime


def _review_packet(tmp_path):
    source = tmp_path / "design-book.pdf"
    source_bytes = b"%PDF-1.4 synthetic design book"
    source.write_bytes(source_bytes)
    content_hash = "sha256:" + hashlib.sha256(source_bytes).hexdigest()
    source_uri = source.resolve().as_uri()
    return {
        "record_type": "document_intake_review",
        "status": "partial",
        "source": {
            "source_path": str(source),
            "source_uri": source_uri,
            "document_id": "doc_design_book",
            "sha256": content_hash,
        },
        "disassembly": {
            "record_type": "document_disassembly_preview",
            "write_performed": False,
            "active_memory_write_performed": False,
            "source": {
                "source_uri": source_uri,
                "path": str(source),
                "source_type": "pdf",
                "media_type": "application/pdf",
                "content_hash": content_hash,
            },
            "document": {
                "document_id": "doc_design_book",
                "title": "Design Book",
                "source_type": "pdf",
                "media_type": "application/pdf",
                "content_hash": content_hash,
                "page_count": 2,
                "page_limit": 2,
            },
            "pages": [
                {"page_number": 1, "text_status": "text", "visual_review_needed": False},
                {"page_number": 2, "text_status": "no_text", "visual_review_needed": True},
            ],
            "text": {
                "content": "# Design\n\nMotion, feedback, and structure shape player attention.",
                "char_count": 64,
            },
            "image_inventory": {"image_count": 1, "pages_with_images": [2]},
            "quality_seed": {
                "text_pages": [1],
                "no_text_pages": [2],
                "visual_review_needed_pages": [2],
            },
            "artifact_manifest": {
                "record_type": "document_artifact_manifest",
                "artifacts": {
                    "raw_source": {
                        "artifact_type": "raw_source",
                        "content_hash": content_hash,
                        "ref": "document_artifacts/sources/aa/design-book.pdf",
                    }
                },
                "pages": [],
            },
            "error": None,
        },
        "extraction_request": {
            "request_id": "vis_req_design_book",
            "document_id": "doc_design_book",
            "image_refs": [
                {
                    "source_uri": source_uri,
                    "page_number": 2,
                    "source_artifact_id": "page-image-2",
                }
            ],
            "requested_capabilities": ["figure_description", "ocr_text", "table_structure"],
        },
        "quality": {"warnings": []},
        "artifact_manifest": {
            "record_type": "document_artifact_manifest",
            "artifacts": {
                "raw_source": {
                    "artifact_type": "raw_source",
                    "content_hash": content_hash,
                    "ref": "document_artifacts/sources/aa/design-book.pdf",
                }
            },
            "pages": [],
        },
        "draft_candidates": [],
        "promotion_guidance": {"auto_promote": False},
        "policy": {
            "write_behavior": "read_only",
            "active_memory_promoted": False,
            "graph_edges_promoted": False,
        },
        "receipts": {
            "artifacts_built": 1,
            "artifacts_read": 0,
            "coverage_missing": ["ocr", "table", "visual"],
        },
        "error": None,
    }


def _review_packet_window_two(tmp_path):
    packet = _review_packet(tmp_path)
    packet["disassembly"]["document"]["page_count"] = 4
    packet["disassembly"]["document"]["page_limit"] = 4
    packet["disassembly"]["document"]["page_range"] = {"start": 3, "end": 4}
    packet["disassembly"]["pages"] = [
        {"page_number": 3, "text_status": "text", "visual_review_needed": False},
        {"page_number": 4, "text_status": "no_text", "visual_review_needed": True},
    ]
    packet["disassembly"]["text"] = {
        "content": "# Systems\n\nPlayer decisions and feedback systems shape play.",
        "char_count": 58,
    }
    packet["disassembly"]["image_inventory"] = {"image_count": 1, "pages_with_images": [4]}
    packet["disassembly"]["quality_seed"] = {
        "text_pages": [3],
        "no_text_pages": [4],
        "visual_review_needed_pages": [4],
    }
    packet["extraction_request"]["image_refs"] = [
        {
            "source_uri": packet["source"]["source_uri"],
            "page_number": 4,
            "source_artifact_id": "page-image-4",
        }
    ]
    return packet


def _review_packet_window_two_with_source_mismatch(tmp_path):
    packet = _review_packet_window_two(tmp_path)
    source = tmp_path / "other-design-book.pdf"
    source_bytes = b"%PDF-1.4 different synthetic design book"
    source.write_bytes(source_bytes)
    content_hash = "sha256:" + hashlib.sha256(source_bytes).hexdigest()
    source_uri = source.resolve().as_uri()
    packet["source"].update(
        {
            "source_path": str(source),
            "source_uri": source_uri,
            "sha256": content_hash,
        }
    )
    packet["disassembly"]["source"].update(
        {
            "source_uri": source_uri,
            "path": str(source),
            "content_hash": content_hash,
        }
    )
    packet["disassembly"]["document"]["content_hash"] = content_hash
    packet["extraction_request"]["image_refs"][0]["source_uri"] = source_uri
    return packet


def _review_packet_window_two_with_source_uri_mismatch_same_hash(tmp_path):
    packet = _review_packet_window_two(tmp_path)
    source = tmp_path / "same-bytes-design-book.pdf"
    source_bytes = b"%PDF-1.4 synthetic design book"
    source.write_bytes(source_bytes)
    content_hash = "sha256:" + hashlib.sha256(source_bytes).hexdigest()
    source_uri = source.resolve().as_uri()
    packet["source"].update(
        {
            "source_path": str(source),
            "source_uri": source_uri,
            "sha256": content_hash,
        }
    )
    packet["disassembly"]["source"].update(
        {
            "source_uri": source_uri,
            "path": str(source),
            "content_hash": content_hash,
        }
    )
    packet["disassembly"]["document"]["content_hash"] = content_hash
    packet["extraction_request"]["image_refs"][0]["source_uri"] = source_uri
    return packet


def _review_packet_window_two_with_table_candidate(tmp_path):
    packet = _review_packet_window_two(tmp_path)
    packet["disassembly"]["quality_seed"]["table_candidate_pages"] = [4]
    return packet


def _rewrite_staged_artifact_payload(runtime, artifact, mutate):
    payload = json.loads(runtime.content_store.read_bytes(artifact["content_ref"]).decode("utf-8"))
    mutate(payload)
    updated = dict(artifact)
    updated["content_ref"] = runtime.content_store.put_bytes(
        (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"),
        suffix=".json",
    )
    upsert_record(runtime.ledger, "knowledge_artifacts", updated["artifact_id"], updated)
    return updated


def _document_record(review_packet):
    disassembly = review_packet["disassembly"]
    document = disassembly["document"]
    source = disassembly["source"]
    return prepare_document_record(
        title=document["title"],
        source_uri=source["source_uri"],
        source_type=source["source_type"],
        content_hash=source["content_hash"],
        media_type=source["media_type"],
        metadata={"project": "Engram", "domain": "documents", "document_id": document["document_id"]},
    )


def _completion_inputs(review_packet):
    document_record = _document_record(review_packet)
    visual_request = prepare_visual_extraction_request(
        document_record=document_record,
        image_refs=review_packet["extraction_request"]["image_refs"],
        requested_capabilities=review_packet["extraction_request"]["requested_capabilities"],
        extractor_id="agent-native-vision",
        extractor_kind="agent_native",
    )
    source_ref = {
        "source_uri": document_record["source_uri"],
        "page_number": 2,
        "source_artifact_id": "page-image-2",
    }
    visual_preview = preview_visual_extraction(
        document_record=document_record,
        visual_request=visual_request,
        extractor_id="agent-native-vision",
        extractor_kind="agent_native",
        observations=[
            {
                "artifact_type": "ocr_block",
                "source_ref": source_ref,
                "page_number": 2,
                "text": "OCR confirms a page about feedback and structure.",
                "confidence": 0.93,
                "metadata": {"capabilities_covered": ["ocr_text"]},
            },
            {
                "artifact_type": "table",
                "source_ref": source_ref,
                "page_number": 2,
                "description": "No table is present on the reviewed page.",
                "confidence": 0.91,
                "metadata": {
                    "capabilities_covered": ["table_structure"],
                    "table_present": False,
                },
            },
            {
                "artifact_type": "figure",
                "source_ref": source_ref,
                "page_number": 2,
                "description": "A figure relates feedback loops to player attention.",
                "confidence": 0.9,
                "metadata": {"capabilities_covered": ["figure_description"]},
            },
        ],
    )
    visual_artifacts = visual_preview["visual_artifacts"]
    understanding_packet = prepare_document_understanding_packet(
        document_record=document_record,
        analysis={
            "summary": [
                {
                    "text": "The document connects design structure to player attention.",
                    "confidence": 0.87,
                    "evidence_refs": [{"document_id": document_record["document_id"], "chunk_id": 0}],
                }
            ],
            "claims": [
                {
                    "text": "Feedback and structure shape attention.",
                    "confidence": 0.88,
                    "evidence_refs": [
                        {"document_id": document_record["document_id"], "chunk_id": 0},
                        visual_artifacts[0]["artifact_id"],
                    ],
                }
            ],
            "concepts": [
                {
                    "name": "attention design",
                    "description": "How structure and feedback direct player focus.",
                    "confidence": 0.86,
                }
            ],
            "high_value_sections": [
                {
                    "title": "Design",
                    "reason": "Introduces the core attention pattern.",
                    "page_number": 1,
                    "confidence": 0.82,
                    "chunk_ref": {"document_id": document_record["document_id"], "chunk_id": 0},
                }
            ],
        },
        chunk_refs=[{"document_id": document_record["document_id"], "chunk_id": 0}],
        visual_artifacts=visual_artifacts,
        created_by="agent-review",
    )
    edge_indexes = list(range(len(understanding_packet["document_draft"]["proposed_edges"])))
    promotion_transaction = prepare_document_promotion_transaction(
        document_draft=understanding_packet["document_draft"],
        selected_memory_indexes=[],
        selected_edge_indexes=edge_indexes,
        approved_by="agent-review",
    )
    return {
        "document_record": document_record,
        "visual_request": visual_request,
        "visual_preview": visual_preview,
        "understanding_packet": understanding_packet,
        "document_promotion_transaction": promotion_transaction,
    }


def _multi_window_completion_inputs(review_packet):
    document_record = _document_record(review_packet)
    source_uri = document_record["source_uri"]
    image_refs = [
        {
            "source_uri": source_uri,
            "page_number": 2,
            "source_artifact_id": "page-image-2",
            "requested_capabilities": ["figure_description", "ocr_text"],
        },
        {
            "source_uri": source_uri,
            "page_number": 4,
            "source_artifact_id": "page-image-4",
            "requested_capabilities": ["figure_description", "ocr_text"],
        },
    ]
    visual_request = prepare_visual_extraction_request(
        document_record=document_record,
        image_refs=image_refs,
        requested_capabilities=["figure_description", "ocr_text"],
        extractor_id="agent-native-vision",
        extractor_kind="agent_native",
    )
    observations = []
    for page_number, source_artifact_id in ((2, "page-image-2"), (4, "page-image-4")):
        source_ref = {
            "source_uri": source_uri,
            "page_number": page_number,
            "source_artifact_id": source_artifact_id,
        }
        observations.extend(
            [
                {
                    "artifact_type": "ocr_block",
                    "source_ref": source_ref,
                    "page_number": page_number,
                    "text": f"OCR text for page {page_number}.",
                    "confidence": 0.93,
                    "metadata": {"capabilities_covered": ["ocr_text"]},
                },
                {
                    "artifact_type": "figure",
                    "source_ref": source_ref,
                    "page_number": page_number,
                    "description": f"Reviewed figure evidence for page {page_number}.",
                    "confidence": 0.9,
                    "metadata": {"capabilities_covered": ["figure_description"]},
                },
            ]
        )
    visual_preview = preview_visual_extraction(
        document_record=document_record,
        visual_request=visual_request,
        extractor_id="agent-native-vision",
        extractor_kind="agent_native",
        observations=observations,
    )
    understanding_packet = prepare_document_understanding_packet(
        document_record=document_record,
        analysis={
            "summary": [
                {
                    "text": "The combined document evidence covers attention and systems.",
                    "confidence": 0.87,
                    "evidence_refs": [{"document_id": document_record["document_id"], "chunk_id": 0}],
                }
            ],
            "claims": [
                {
                    "text": "Design structure and systems shape player experience.",
                    "confidence": 0.88,
                    "evidence_refs": [{"document_id": document_record["document_id"], "chunk_id": 0}],
                }
            ],
            "concepts": [
                {
                    "name": "player experience systems",
                    "description": "How feedback and systems shape player experience.",
                    "confidence": 0.86,
                }
            ],
            "high_value_sections": [
                {
                    "title": "Design",
                    "reason": "Introduces the core pattern.",
                    "page_number": 1,
                    "confidence": 0.82,
                    "chunk_ref": {"document_id": document_record["document_id"], "chunk_id": 0},
                }
            ],
        },
        chunk_refs=[{"document_id": document_record["document_id"], "chunk_id": 0}],
        visual_artifacts=visual_preview["visual_artifacts"],
        created_by="agent-review",
    )
    promotion_transaction = prepare_document_promotion_transaction(
        document_draft=understanding_packet["document_draft"],
        selected_memory_indexes=[],
        selected_edge_indexes=list(range(len(understanding_packet["document_draft"]["proposed_edges"]))),
        approved_by="agent-review",
    )
    return {
        "document_record": document_record,
        "visual_request": visual_request,
        "visual_preview": visual_preview,
        "understanding_packet": understanding_packet,
        "document_promotion_transaction": promotion_transaction,
    }


def _store_staged_artifact(runtime, review_packet):
    prepared = runtime.prepare_document_artifact_store(review_packet)
    return runtime.store_document_artifact(
        prepared["prepared_transaction_id"],
        accept=True,
        review_packet=review_packet,
    )


def _ledger_counts(runtime):
    return {
        table: len(list_records(runtime.ledger, table))
        for table in (
            "documents",
            "chunks",
            "knowledge_artifacts",
            "graph_edges",
            "jobs",
            "job_events",
            "transactions",
        )
    }


def test_prepare_document_ingestion_completion_blocks_staged_partial_document(tmp_path):
    runtime = _runtime(tmp_path)
    review_packet = _review_packet(tmp_path)
    staged = _store_staged_artifact(runtime, review_packet)

    completion = runtime.prepare_document_ingestion_completion(
        document_id="doc_design_book",
        artifact_id=staged["artifact"]["artifact_id"],
    )

    assert completion["status"] == "partial"
    assert completion["write_performed"] is False
    assert completion["usable"] is False
    assert {item["code"] for item in completion["blocking_issues"]} >= {
        "visual_coverage_required",
        "understanding_packet_required",
        "promotion_transaction_required",
    }
    assert read_record(runtime.ledger, "documents", "doc_design_book").get("usable") is not True


def test_prepare_document_ingestion_completion_requires_understanding_after_visual_coverage(tmp_path):
    runtime = _runtime(tmp_path)
    review_packet = _review_packet(tmp_path)
    staged = _store_staged_artifact(runtime, review_packet)
    inputs = _completion_inputs(review_packet)

    completion = runtime.prepare_document_ingestion_completion(
        document_id="doc_design_book",
        artifact_id=staged["artifact"]["artifact_id"],
        visual_request=inputs["visual_request"],
        visual_preview=inputs["visual_preview"],
    )

    assert completion["status"] == "partial"
    assert completion["usable"] is False
    assert {item["code"] for item in completion["blocking_issues"]} >= {
        "understanding_packet_required",
        "promotion_transaction_required",
    }
    assert completion["write_performed"] is False
    assert read_record(runtime.ledger, "documents", "doc_design_book").get("usable") is not True


def test_prepare_document_ingestion_completion_reports_execution_plan(tmp_path):
    runtime = _runtime(tmp_path)
    review_packet = _review_packet(tmp_path)
    staged = _store_staged_artifact(runtime, review_packet)
    inputs = _completion_inputs(review_packet)

    completion = runtime.prepare_document_ingestion_completion(
        document_id="doc_design_book",
        artifact_id=staged["artifact"]["artifact_id"],
        visual_request=inputs["visual_request"],
        visual_preview=inputs["visual_preview"],
        understanding_packet=inputs["understanding_packet"],
        document_promotion_transaction=inputs["document_promotion_transaction"],
    )

    assert completion["status"] == "ok"
    assert completion["execution_plan"]["progress_job_id"] == "document_completion:doc_design_book"
    assert completion["execution_plan"]["write_scale"]["visual_artifact_count"] == 3
    assert completion["execution_plan"]["write_scale"]["graph_operation_count"] >= 1
    assert [stage["stage"] for stage in completion["execution_plan"]["stages"]] == [
        "validate",
        "materialize_evidence",
        "promote_graph",
        "mark_usable",
    ]


def test_completion_assessment_service_is_read_only_and_matches_public_prepare(tmp_path):
    runtime = _runtime(tmp_path)
    review_packet = _review_packet(tmp_path)
    staged = _store_staged_artifact(runtime, review_packet)
    inputs = _completion_inputs(review_packet)
    assert isinstance(runtime.document_completion.assessment, DocumentCompletionAssessmentService)
    before = _ledger_counts(runtime)

    assessment = runtime.document_completion.assessment.assess(
        document_id="doc_design_book",
        artifact_id=staged["artifact"]["artifact_id"],
        visual_request=inputs["visual_request"],
        visual_preview=inputs["visual_preview"],
        understanding_packet=inputs["understanding_packet"],
        document_promotion_transaction=inputs["document_promotion_transaction"],
    )
    after = _ledger_counts(runtime)
    prepared = runtime.prepare_document_ingestion_completion(
        document_id="doc_design_book",
        artifact_id=staged["artifact"]["artifact_id"],
        visual_request=inputs["visual_request"],
        visual_preview=inputs["visual_preview"],
        understanding_packet=inputs["understanding_packet"],
        document_promotion_transaction=inputs["document_promotion_transaction"],
    )

    assert assessment["status"] == "ok"
    assert assessment["policy"]["write_behavior"] == "read_only"
    assert assessment["write_performed"] is False
    assert after == before
    assert prepared == assessment


def test_complete_document_ingestion_records_progress_events(tmp_path):
    runtime = _runtime(tmp_path)
    review_packet = _review_packet(tmp_path)
    staged = _store_staged_artifact(runtime, review_packet)
    inputs = _completion_inputs(review_packet)
    prepared = runtime.prepare_document_ingestion_completion(
        document_id="doc_design_book",
        artifact_id=staged["artifact"]["artifact_id"],
        visual_request=inputs["visual_request"],
        visual_preview=inputs["visual_preview"],
        understanding_packet=inputs["understanding_packet"],
        document_promotion_transaction=inputs["document_promotion_transaction"],
    )

    result = runtime.complete_document_ingestion(
        document_id="doc_design_book",
        artifact_id=staged["artifact"]["artifact_id"],
        visual_request=inputs["visual_request"],
        visual_preview=inputs["visual_preview"],
        understanding_packet=inputs["understanding_packet"],
        document_promotion_transaction=inputs["document_promotion_transaction"],
        accept=True,
        approved_by="agent-review",
    )

    assert result["status"] == "ok"
    assert result["progress_job_id"] == "document_completion:doc_design_book"
    assert result["execution_plan"]["write_scale"] == prepared["execution_plan"]["write_scale"]
    events = [
        event
        for event in list_records(runtime.ledger, "job_events")
        if event.get("job_id") == "document_completion:doc_design_book"
    ]
    event_types = [event["event_type"] for event in events]
    assert event_types == [
        "document_completion_started",
        "document_completion_materialized",
        "document_completion_graph_promotion_started",
        "document_completion_graph_promotion_completed",
        "document_completion_completed",
    ]
    assert events[0]["payload"]["write_scale"]["visual_artifact_count"] == 3
    assert events[2]["payload"]["write_scale"]["graph_operation_count"] >= 1
    assert events[-1]["payload"]["completion_artifact_id"] == result["completion_artifact"]["artifact_id"]


def test_complete_document_ingestion_requires_acceptance(tmp_path):
    runtime = _runtime(tmp_path)
    review_packet = _review_packet(tmp_path)
    staged = _store_staged_artifact(runtime, review_packet)
    inputs = _completion_inputs(review_packet)

    result = runtime.complete_document_ingestion(
        document_id="doc_design_book",
        artifact_id=staged["artifact"]["artifact_id"],
        visual_request=inputs["visual_request"],
        visual_preview=inputs["visual_preview"],
        understanding_packet=inputs["understanding_packet"],
        document_promotion_transaction=inputs["document_promotion_transaction"],
        accept=False,
        approved_by="agent-review",
    )

    assert result["status"] == "policy_denied"
    assert result["error"]["code"] == "accept_required"
    assert result["write_performed"] is False
    assert list_records(runtime.ledger, "graph_edges") == []


def test_complete_document_ingestion_marks_document_usable_and_graph_backed(tmp_path):
    runtime = _runtime(tmp_path)
    review_packet = _review_packet(tmp_path)
    staged = _store_staged_artifact(runtime, review_packet)
    document = read_record(runtime.ledger, "documents", "doc_design_book")
    document["document_catalog"] = {
        "primary_subject": "game_design",
        "secondary_subjects": ["systems_design"],
        "collections": ["game_design_books"],
        "reading_role": "core",
        "adjacent_to_game_design": False,
        "exclude_from_core_game_design_corpus": False,
        "corpus_tags": ["book", "game-design", "core-game-design"],
        "classification_basis": "agent_review",
        "classification_confidence": 1.0,
    }
    upsert_record(runtime.ledger, "documents", "doc_design_book", document)
    inputs = _completion_inputs(review_packet)

    result = runtime.complete_document_ingestion(
        document_id="doc_design_book",
        artifact_id=staged["artifact"]["artifact_id"],
        visual_request=inputs["visual_request"],
        visual_preview=inputs["visual_preview"],
        understanding_packet=inputs["understanding_packet"],
        document_promotion_transaction=inputs["document_promotion_transaction"],
        accept=True,
        approved_by="agent-review",
    )

    assert result["status"] == "ok"
    assert result["usable"] is True
    assert result["write_performed"] is True
    assert result["graph_write_performed"] is True
    assert result["active_memory_write_performed"] is False
    assert result["graph_edges_written"]
    assert result["completion_artifact"]["artifact_type"] == "document_completion"
    assert result["coverage_map"]["skipped_region_count"] == 0
    assert result["coverage_map"]["claim_count"] == 1
    assert result["coverage_map"]["graph_proposal_count"] >= 1
    document = read_record(runtime.ledger, "documents", "doc_design_book")
    assert document["usable"] is True
    assert document["ingestion_status"] == "usable"
    assert document["document_catalog"]["primary_subject"] == "game_design"
    assert document["document_catalog"]["collections"] == ["game_design_books"]
    assert document["document_catalog"]["classification_basis"] == "agent_review"
    assert document["completion_artifact_id"] == result["completion_artifact"]["artifact_id"]
    assert len(list_records(runtime.ledger, "graph_edges")) == len(result["graph_edges_written"])

    response = runtime.query_knowledge(
        {
            "request_id": "req-doc-usable",
            "ask": {
                "goal": "Orient to design book evidence.",
                "task_type": "document_orientation",
                "project": "Engram",
                "focus": ["Design"],
            },
        }
    )

    assert response["status"] == "ok"
    assert response["answer"]["documents"][0]["document_catalog"]["primary_subject"] == "game_design"
    assert response["answer"]["documents"][0]["usability"]["status"] == "usable"
    assert response["answer"]["documents"][0]["usability"]["completion_artifact_id"] == result["completion_artifact"]["artifact_id"]
    assert response["answer"]["documents"][0]["coverage"]["coverage_map_id"] == result["coverage_map"]["coverage_map_id"]
    assert (
        response["answer"]["documents"][0]["coverage"]["interpreted_visual_count"]
        == result["coverage_map"]["interpreted_visual_count"]
    )
    assert (
        response["answer"]["documents"][0]["coverage"]["skipped_region_count"]
        == result["coverage_map"]["skipped_region_count"]
    )
    assert response["answer"]["documents"][0]["coverage"]["claim_count"] == result["coverage_map"]["claim_count"]
    assert validate_knowledge_response(response)["valid"] is True

    graph_response = runtime.query_knowledge(
        {
            "request_id": "req-doc-usable-graph",
            "ask": {
                "goal": "Inspect completed document graph evidence.",
                "task_type": "graph_evidence",
                "project": "Engram",
                "focus": ["doc_design_book"],
            },
            "budget": {"max_source_reads": 1},
        }
    )

    assert graph_response["status"] == "ok"
    first_edge = graph_response["answer"]["evidence_paths"][0]["edges"][0]
    assert first_edge["source"] == "document_intelligence.auto_graph"


def test_complete_document_ingestion_merges_all_staged_artifact_windows(tmp_path):
    runtime = _runtime(tmp_path)
    first_packet = _review_packet(tmp_path)
    second_packet = _review_packet_window_two(tmp_path)
    first_staged = _store_staged_artifact(runtime, first_packet)
    second_staged = _store_staged_artifact(runtime, second_packet)
    inputs = _multi_window_completion_inputs(first_packet)

    result = runtime.complete_document_ingestion(
        document_id="doc_design_book",
        visual_request=inputs["visual_request"],
        visual_preview=inputs["visual_preview"],
        understanding_packet=inputs["understanding_packet"],
        document_promotion_transaction=inputs["document_promotion_transaction"],
        accept=True,
        approved_by="agent-review",
    )

    assert result["status"] == "ok"
    assert result["completion_artifact"]["source_artifact_ids"] == [
        first_staged["artifact"]["artifact_id"],
        second_staged["artifact"]["artifact_id"],
    ]
    assert result["coverage_map"]["pages_reported"] == 4
    assert result["coverage_map"]["visual_needed_pages"] == [2, 4]
    assert result["coverage_map"]["visual_covered_pages"] == [2, 4]
    assert result["coverage_map"]["missing_visual_pages"] == []
    assert result["coverage_map"]["ocr_needed_pages"] == [2, 4]
    assert result["coverage_map"]["ocr_covered_pages"] == [2, 4]
    assert result["coverage_map"]["missing_ocr_pages"] == []
    assert result["coverage_map"]["coverage_complete"] is True


def test_complete_document_ingestion_with_artifact_id_still_aggregates_all_document_artifacts(tmp_path):
    runtime = _runtime(tmp_path)
    first_packet = _review_packet(tmp_path)
    second_packet = _review_packet_window_two(tmp_path)
    first_staged = _store_staged_artifact(runtime, first_packet)
    second_staged = _store_staged_artifact(runtime, second_packet)
    inputs = _multi_window_completion_inputs(first_packet)

    result = runtime.complete_document_ingestion(
        document_id="doc_design_book",
        artifact_id=first_staged["artifact"]["artifact_id"],
        visual_request=inputs["visual_request"],
        visual_preview=inputs["visual_preview"],
        understanding_packet=inputs["understanding_packet"],
        document_promotion_transaction=inputs["document_promotion_transaction"],
        accept=True,
        approved_by="agent-review",
    )

    assert result["status"] == "ok"
    assert result["completion_artifact"]["source_artifact_ids"] == [
        first_staged["artifact"]["artifact_id"],
        second_staged["artifact"]["artifact_id"],
    ]
    assert result["coverage_map"]["pages_reported"] == 4


def test_prepare_document_ingestion_completion_blocks_missing_later_window_coverage(tmp_path):
    runtime = _runtime(tmp_path)
    first_packet = _review_packet(tmp_path)
    second_packet = _review_packet_window_two(tmp_path)
    _store_staged_artifact(runtime, first_packet)
    _store_staged_artifact(runtime, second_packet)
    inputs = _completion_inputs(first_packet)

    completion = runtime.prepare_document_ingestion_completion(
        document_id="doc_design_book",
        visual_request=inputs["visual_request"],
        visual_preview=inputs["visual_preview"],
        understanding_packet=inputs["understanding_packet"],
        document_promotion_transaction=inputs["document_promotion_transaction"],
    )

    assert completion["status"] == "partial"
    assert {
        (issue.get("code"), issue.get("page_number"), issue.get("capability"))
        for issue in completion["blocking_issues"]
    } >= {
        ("missing_visual_capability", 4, "figure_description"),
        ("missing_visual_capability", 4, "ocr_text"),
    }


def test_prepare_document_ingestion_completion_reports_missing_or_malformed_staged_payload(tmp_path):
    runtime = _runtime(tmp_path)
    review_packet = _review_packet(tmp_path)
    staged = _store_staged_artifact(runtime, review_packet)
    artifact = dict(staged["artifact"])
    artifact["content_ref"] = "sha256:" + "0" * 64
    upsert_record(runtime.ledger, "knowledge_artifacts", artifact["artifact_id"], artifact)

    completion = runtime.prepare_document_ingestion_completion(document_id="doc_design_book")

    assert completion["status"] == "partial"
    assert any(
        issue["code"] == "document_artifact_payload_unreadable"
        and issue["artifact_id"] == artifact["artifact_id"]
        for issue in completion["blocking_issues"]
    )


def test_completion_transaction_receipt_includes_all_mutated_staged_artifacts(tmp_path):
    runtime = _runtime(tmp_path)
    first_packet = _review_packet(tmp_path)
    second_packet = _review_packet_window_two(tmp_path)
    first_staged = _store_staged_artifact(runtime, first_packet)
    second_staged = _store_staged_artifact(runtime, second_packet)
    inputs = _multi_window_completion_inputs(first_packet)

    result = runtime.complete_document_ingestion(
        document_id="doc_design_book",
        visual_request=inputs["visual_request"],
        visual_preview=inputs["visual_preview"],
        understanding_packet=inputs["understanding_packet"],
        document_promotion_transaction=inputs["document_promotion_transaction"],
        accept=True,
        approved_by="agent-review",
    )

    expected_ids = {
        first_staged["artifact"]["artifact_id"],
        second_staged["artifact"]["artifact_id"],
    }
    proposed_writes = result["transaction_receipt"]["proposed_writes"]
    affected_refs = result["transaction_receipt"]["affected_refs"]
    assert expected_ids.issubset(
        {item.get("id") for item in proposed_writes if item.get("table") == "knowledge_artifacts"}
    )
    assert expected_ids.issubset(
        {
            item.get("artifact_id")
            for item in affected_refs
            if item.get("kind") == "knowledge_artifact"
        }
    )


def test_completion_visual_request_preserves_staged_extraction_refs(tmp_path):
    runtime = _runtime(tmp_path)
    first_packet = _review_packet(tmp_path)
    second_packet = _review_packet_window_two(tmp_path)
    _store_staged_artifact(runtime, first_packet)
    _store_staged_artifact(runtime, second_packet)
    inputs = _multi_window_completion_inputs(first_packet)

    completion = runtime.prepare_document_ingestion_completion(
        document_id="doc_design_book",
        visual_preview=inputs["visual_preview"],
        understanding_packet=inputs["understanding_packet"],
        document_promotion_transaction=inputs["document_promotion_transaction"],
    )

    refs = completion["requirements"]["visual_request"]["image_refs"]
    by_page = {ref["page_number"]: ref for ref in refs}
    assert by_page[2]["source_artifact_id"] == "page-image-2"
    assert by_page[4]["source_artifact_id"] == "page-image-4"


def test_complete_document_ingestion_blocks_source_hash_mismatch_across_artifacts(tmp_path):
    runtime = _runtime(tmp_path)
    first_packet = _review_packet(tmp_path)
    second_packet = _review_packet_window_two_with_source_mismatch(tmp_path)
    _store_staged_artifact(runtime, first_packet)
    _store_staged_artifact(runtime, second_packet)
    inputs = _multi_window_completion_inputs(first_packet)

    result = runtime.complete_document_ingestion(
        document_id="doc_design_book",
        visual_request=inputs["visual_request"],
        visual_preview=inputs["visual_preview"],
        understanding_packet=inputs["understanding_packet"],
        document_promotion_transaction=inputs["document_promotion_transaction"],
        accept=True,
        approved_by="agent-review",
    )

    assert result["status"] == "partial"
    assert any(issue["code"] == "document_source_mismatch" for issue in result["blocking_issues"])
    assert result["write_performed"] is False


def test_complete_document_ingestion_blocks_payload_document_id_mismatch(tmp_path):
    runtime = _runtime(tmp_path)
    first_packet = _review_packet(tmp_path)
    second_packet = _review_packet_window_two(tmp_path)
    _store_staged_artifact(runtime, first_packet)
    second_staged = _store_staged_artifact(runtime, second_packet)
    _rewrite_staged_artifact_payload(
        runtime,
        second_staged["artifact"],
        lambda payload: payload["disassembly"]["document"].update({"document_id": "doc_other_book"}),
    )
    inputs = _multi_window_completion_inputs(first_packet)

    result = runtime.complete_document_ingestion(
        document_id="doc_design_book",
        visual_request=inputs["visual_request"],
        visual_preview=inputs["visual_preview"],
        understanding_packet=inputs["understanding_packet"],
        document_promotion_transaction=inputs["document_promotion_transaction"],
        accept=True,
        approved_by="agent-review",
    )

    assert result["status"] == "partial"
    assert any(issue["code"] == "document_artifact_document_mismatch" for issue in result["blocking_issues"])
    assert result["write_performed"] is False


def test_complete_document_ingestion_blocks_source_uri_mismatch_even_with_same_hash(tmp_path):
    runtime = _runtime(tmp_path)
    first_packet = _review_packet(tmp_path)
    second_packet = _review_packet_window_two_with_source_uri_mismatch_same_hash(tmp_path)
    _store_staged_artifact(runtime, first_packet)
    _store_staged_artifact(runtime, second_packet)
    inputs = _multi_window_completion_inputs(first_packet)

    result = runtime.complete_document_ingestion(
        document_id="doc_design_book",
        visual_request=inputs["visual_request"],
        visual_preview=inputs["visual_preview"],
        understanding_packet=inputs["understanding_packet"],
        document_promotion_transaction=inputs["document_promotion_transaction"],
        accept=True,
        approved_by="agent-review",
    )

    assert result["status"] == "partial"
    assert any(issue["code"] == "document_source_mismatch" for issue in result["blocking_issues"])
    assert result["write_performed"] is False


def test_prepare_document_ingestion_completion_requires_later_window_table_coverage(tmp_path):
    runtime = _runtime(tmp_path)
    first_packet = _review_packet(tmp_path)
    second_packet = _review_packet_window_two_with_table_candidate(tmp_path)
    _store_staged_artifact(runtime, first_packet)
    _store_staged_artifact(runtime, second_packet)
    inputs = _multi_window_completion_inputs(first_packet)

    completion = runtime.prepare_document_ingestion_completion(
        document_id="doc_design_book",
        visual_request=inputs["visual_request"],
        visual_preview=inputs["visual_preview"],
        understanding_packet=inputs["understanding_packet"],
        document_promotion_transaction=inputs["document_promotion_transaction"],
    )

    assert completion["status"] == "partial"
    assert any(
        issue["code"] == "missing_visual_capability"
        and issue["page_number"] == 4
        and issue["capability"] == "table_structure"
        for issue in completion["blocking_issues"]
    )


def test_prepare_document_ingestion_completion_accepts_later_window_table_waiver(tmp_path):
    runtime = _runtime(tmp_path)
    first_packet = _review_packet(tmp_path)
    second_packet = _review_packet_window_two_with_table_candidate(tmp_path)
    _store_staged_artifact(runtime, first_packet)
    _store_staged_artifact(runtime, second_packet)
    inputs = _multi_window_completion_inputs(first_packet)

    completion = runtime.prepare_document_ingestion_completion(
        document_id="doc_design_book",
        visual_request=inputs["visual_request"],
        visual_preview=inputs["visual_preview"],
        understanding_packet=inputs["understanding_packet"],
        document_promotion_transaction=inputs["document_promotion_transaction"],
        coverage_waivers=[
            {
                "page_number": 4,
                "capability": "table_structure",
                "reason": "Reviewer confirmed the page has no parseable table.",
                "approved_by": "agent-review",
            }
        ],
    )

    assert completion["status"] == "ok"
    assert completion["usable"] is True


def test_prepare_document_ingestion_completion_succeeds_with_staged_visual_request_refs(tmp_path):
    runtime = _runtime(tmp_path)
    first_packet = _review_packet(tmp_path)
    second_packet = _review_packet_window_two(tmp_path)
    _store_staged_artifact(runtime, first_packet)
    _store_staged_artifact(runtime, second_packet)
    inputs = _multi_window_completion_inputs(first_packet)

    completion = runtime.prepare_document_ingestion_completion(
        document_id="doc_design_book",
        visual_preview=inputs["visual_preview"],
        understanding_packet=inputs["understanding_packet"],
        document_promotion_transaction=inputs["document_promotion_transaction"],
    )

    assert completion["status"] == "ok"
    refs = completion["requirements"]["visual_request"]["image_refs"]
    assert {ref["source_artifact_id"] for ref in refs} == {"page-image-2", "page-image-4"}


def test_complete_document_ingestion_progress_uses_synthesized_visual_request_refs(tmp_path):
    runtime = _runtime(tmp_path)
    first_packet = _review_packet(tmp_path)
    second_packet = _review_packet_window_two(tmp_path)
    _store_staged_artifact(runtime, first_packet)
    _store_staged_artifact(runtime, second_packet)
    inputs = _multi_window_completion_inputs(first_packet)

    result = runtime.complete_document_ingestion(
        document_id="doc_design_book",
        visual_preview=inputs["visual_preview"],
        understanding_packet=inputs["understanding_packet"],
        document_promotion_transaction=inputs["document_promotion_transaction"],
        accept=True,
        approved_by="agent-review",
    )

    assert result["status"] == "ok"
    assert result["execution_plan"]["write_scale"]["source_artifact_count"] == 2
    assert result["execution_plan"]["write_scale"]["required_visual_ref_count"] == 2
    events = [
        event
        for event in list_records(runtime.ledger, "job_events")
        if event.get("job_id") == "document_completion:doc_design_book"
    ]
    assert events[0]["payload"]["write_scale"]["source_artifact_count"] == 2
    assert events[0]["payload"]["write_scale"]["required_visual_ref_count"] == 2


def test_completion_updates_ingestion_inspection_usable_after_completion(tmp_path):
    runtime = _runtime(tmp_path)
    first_packet = _review_packet(tmp_path)
    second_packet = _review_packet_window_two(tmp_path)
    first_staged = _store_staged_artifact(runtime, first_packet)
    second_staged = _store_staged_artifact(runtime, second_packet)
    upsert_record(
        runtime.ledger,
        "jobs",
        "doc_ingest_design_book",
        {
            "record_type": "document_ingestion",
            "ingestion_id": "doc_ingest_design_book",
            "document_id": "doc_design_book",
            "status": "partial",
            "readiness": {
                "searchable": True,
                "structural_graph_covered": True,
                "semantic_graph_covered": False,
                "ocr_covered": False,
                "visual_covered": False,
                "table_covered": True,
                "usable": False,
            },
            "artifacts": [first_staged["artifact"], second_staged["artifact"]],
            "windows": [],
            "errors": [],
        },
    )
    inputs = _multi_window_completion_inputs(first_packet)

    runtime.complete_document_ingestion(
        document_id="doc_design_book",
        visual_request=inputs["visual_request"],
        visual_preview=inputs["visual_preview"],
        understanding_packet=inputs["understanding_packet"],
        document_promotion_transaction=inputs["document_promotion_transaction"],
        accept=True,
        approved_by="agent-review",
    )

    inspected = runtime.inspect_document_ingestion(ingestion_id="doc_ingest_design_book")
    assert inspected["readiness"]["ocr_covered"] is True
    assert inspected["readiness"]["visual_covered"] is True
    assert inspected["readiness"]["table_covered"] is True
    assert inspected["readiness"]["semantic_graph_covered"] is True
    assert inspected["readiness"]["usable"] is True
    assert inspected["completion_progress"]["job"]["job_id"] == "document_completion:doc_design_book"
    assert inspected["completion_progress"]["latest_event_type"] == "document_completion_completed"
    assert inspected["completion_progress"]["event_count"] == 5


def test_document_completion_honors_per_image_ref_capability_obligations(tmp_path):
    runtime = _runtime(tmp_path)
    review_packet = _review_packet(tmp_path)
    staged = _store_staged_artifact(runtime, review_packet)
    document_record = _document_record(review_packet)
    visual_request = prepare_visual_extraction_request(
        document_record=document_record,
        image_refs=[
            {
                "source_uri": document_record["source_uri"],
                "page_number": 2,
                "source_artifact_id": "page-image-2",
                "requested_capabilities": ["ocr_text"],
            },
            {
                "source_uri": document_record["source_uri"],
                "page_number": 3,
                "source_artifact_id": "page-image-3",
                "requested_capabilities": ["table_structure"],
            },
        ],
        requested_capabilities=["ocr_text", "table_structure"],
        extractor_id="agent-native-vision",
        extractor_kind="agent_native",
    )
    visual_preview = preview_visual_extraction(
        document_record=document_record,
        visual_request=visual_request,
        extractor_id="agent-native-vision",
        extractor_kind="agent_native",
        observations=[
            {
                "artifact_type": "ocr_block",
                "source_ref": visual_request["image_refs"][0],
                "page_number": 2,
                "text": "OCR text covers only page two.",
                "confidence": 0.91,
            },
            {
                "artifact_type": "table",
                "source_ref": visual_request["image_refs"][1],
                "page_number": 3,
                "description": "No table is present on page three.",
                "confidence": 0.92,
                "metadata": {"table_present": False},
            },
        ],
    )
    base_inputs = _completion_inputs(review_packet)

    completion = runtime.prepare_document_ingestion_completion(
        document_id="doc_design_book",
        artifact_id=staged["artifact"]["artifact_id"],
        visual_request=visual_request,
        visual_preview=visual_preview,
        understanding_packet=base_inputs["understanding_packet"],
        document_promotion_transaction=base_inputs["document_promotion_transaction"],
    )

    assert completion["status"] == "ok"
    assert completion["blocking_issues"] == []
