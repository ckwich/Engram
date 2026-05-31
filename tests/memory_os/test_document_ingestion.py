from __future__ import annotations

import hashlib
from pathlib import Path

from core.graph_store import JsonGraphStore
from core.memory_os._records import list_records, read_record, upsert_record
from core.memory_os.document_coverage_pass import DocumentCoveragePassService
from core.memory_os.runtime import MemoryOSRuntime
from core.vector_index import InMemoryVectorIndex


def _embed(text):
    return [1.0, 0.0] if str(text).strip() else [0.0, 1.0]


def _runtime(tmp_path):
    runtime = MemoryOSRuntime(
        tmp_path / "memory_os",
        embed_text=_embed,
        vector_index=InMemoryVectorIndex(),
        graph_store=JsonGraphStore(tmp_path / "edges.json"),
    )
    runtime.initialize()
    return runtime


def _pdf(tmp_path: Path) -> Path:
    path = tmp_path / "book.pdf"
    path.write_bytes(b"%PDF-1.4 synthetic book bytes")
    return path


def _review_packet_for_window(source_path, *, start, end, has_more):
    source = Path(source_path).resolve()
    content_hash = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    document_id = "doc_synthetic_ingestion_book"
    text = f"# Pages {start}-{end}\n\nDesign notes for pages {start} through {end}."
    return {
        "record_type": "document_intake_review",
        "status": "partial" if has_more else "ok",
        "source": {
            "source_path": str(source),
            "source_uri": source.as_uri(),
            "document_id": document_id,
            "sha256": content_hash,
        },
        "disassembly": {
            "record_type": "document_disassembly_preview",
            "write_performed": False,
            "active_memory_write_performed": False,
            "source": {
                "source_uri": source.as_uri(),
                "path": str(source),
                "source_type": "pdf",
                "media_type": "application/pdf",
                "content_hash": content_hash,
            },
            "document": {
                "document_id": document_id,
                "title": "Synthetic Ingestion Book",
                "source_type": "pdf",
                "media_type": "application/pdf",
                "content_hash": content_hash,
                "page_count": 4,
                "page_limit": end,
                "page_range": {"start": start, "end": end},
            },
            "pages": [
                {"page_number": page, "text_status": "text", "visual_review_needed": False}
                for page in range(start, end + 1)
            ],
            "text": {"content": text, "char_count": len(text), "page_start": start, "page_end": end},
            "image_inventory": {"image_count": 0, "pages_with_images": []},
            "quality_seed": {
                "text_pages": list(range(start, end + 1)),
                "no_text_pages": [],
                "visual_review_needed_pages": [],
            },
            "artifact_manifest": {
                "record_type": "document_artifact_manifest",
                "artifacts": {},
                "pages": [],
            },
            "resume": {
                "has_more": has_more,
                "next_page": end + 1 if has_more else None,
                "resume_token": f"resume-{end + 1}" if has_more else None,
            },
            "error": None,
        },
        "extraction_request": None,
        "quality": {"warnings": []},
        "artifact_manifest": {
            "record_type": "document_artifact_manifest",
            "artifacts": {},
            "pages": [],
        },
        "policy": {
            "write_behavior": "read_only",
            "active_memory_promoted": False,
            "graph_edges_promoted": False,
        },
        "receipts": {"coverage_missing": []},
        "error": None,
    }


def _empty_text_review_packet(source_path):
    packet = _review_packet_for_window(source_path, start=1, end=1, has_more=False)
    packet["disassembly"]["text"] = {"content": "", "char_count": 0, "page_start": 1, "page_end": 1}
    packet["disassembly"]["pages"] = [
        {"page_number": 1, "text_status": "no_text", "visual_review_needed": False}
    ]
    packet["disassembly"]["quality_seed"] = {
        "text_pages": [],
        "no_text_pages": [1],
        "visual_review_needed_pages": [],
    }
    return packet


def _coverage_review_packet(source_path):
    packet = _review_packet_for_window(source_path, start=1, end=2, has_more=False)
    source_uri = packet["source"]["source_uri"]
    packet["disassembly"]["pages"] = [
        {"page_number": 1, "text_status": "text", "visual_review_needed": False},
        {"page_number": 2, "text_status": "no_text", "visual_review_needed": True},
    ]
    packet["disassembly"]["image_inventory"] = {"image_count": 1, "pages_with_images": [2]}
    packet["disassembly"]["quality_seed"] = {
        "text_pages": [1],
        "no_text_pages": [2],
        "visual_review_needed_pages": [2],
        "table_candidate_pages": [2],
    }
    packet["extraction_request"] = {
        "request_id": "vis_req_synthetic_ingestion_book",
        "document_id": "doc_synthetic_ingestion_book",
        "requested_capabilities": ["figure_description", "ocr_text", "table_structure"],
        "image_refs": [
            {
                "source_uri": source_uri,
                "page_number": 2,
                "source_artifact_id": "page-image-2",
                "requested_capabilities": ["figure_description", "ocr_text", "table_structure"],
            }
        ],
    }
    packet["receipts"]["coverage_missing"] = ["ocr", "table", "visual"]
    return packet


def _install_fake_coverage_pass(runtime, *, unavailable=False, no_observations=False):
    def workbench(**kwargs):
        visual_request = kwargs["visual_request"]
        document_record = kwargs["document_record"]
        if unavailable:
            return {
                "schema_version": "test.coverage-workbench",
                "record_type": "document_coverage_workbench",
                "workbench_id": "workbench-unavailable",
                "status": "partial",
                "visual_request": visual_request,
                "document_record": document_record,
                "observations": [],
                "preview_visual_extraction_arguments": {
                    "document_record": document_record,
                    "observations": [],
                    "extractor_id": "fake-coverage",
                    "extractor_kind": "agent_native",
                    "visual_request": visual_request,
                },
                "unavailable_receipts": [
                    {"code": "ocr_adapter_unavailable", "page_number": 2},
                    {"code": "table_adapter_unavailable", "page_number": 2},
                ],
                "receipts": {"observation_count": 0, "unavailable_count": 2},
                "write_performed": False,
                "active_memory_write_performed": False,
                "graph_write_performed": False,
            }
        if no_observations:
            return {
                "schema_version": "test.coverage-workbench",
                "record_type": "document_coverage_workbench",
                "workbench_id": "workbench-needs-agent-vision",
                "status": "ok",
                "visual_request": visual_request,
                "document_record": document_record,
                "page_tasks": [
                    {
                        "page_number": 2,
                        "visual_review": {
                            "status": "required",
                            "required_capabilities": ["figure_description"],
                            "return_tool": "preview_visual_extraction",
                        },
                    }
                ],
                "observations": [],
                "preview_visual_extraction_arguments": {
                    "document_record": document_record,
                    "observations": [],
                    "extractor_id": "fake-coverage",
                    "extractor_kind": "agent_native",
                    "visual_request": visual_request,
                },
                "unavailable_receipts": [],
                "skipped_receipts": [],
                "receipts": {"observation_count": 0, "unavailable_count": 0},
                "write_performed": False,
                "active_memory_write_performed": False,
                "graph_write_performed": False,
            }
        source_ref = dict(visual_request["image_refs"][0])
        observations = [
            {
                "artifact_type": "figure",
                "source_ref": source_ref,
                "page_number": 2,
                "description": "A figure illustrates document coverage.",
                "confidence": 0.91,
                "metadata": {"capabilities_covered": ["figure_description"]},
            },
            {
                "artifact_type": "ocr_block",
                "source_ref": source_ref,
                "page_number": 2,
                "text": "Readable OCR text from page two.",
                "confidence": 0.9,
                "metadata": {"capabilities_covered": ["ocr_text"]},
            },
            {
                "artifact_type": "table",
                "source_ref": source_ref,
                "page_number": 2,
                "description": "No table is present after review.",
                "confidence": 0.88,
                "metadata": {"capabilities_covered": ["table_structure"], "table_present": False},
            },
        ]
        return {
            "schema_version": "test.coverage-workbench",
            "record_type": "document_coverage_workbench",
            "workbench_id": "workbench-ok",
            "status": "ok",
            "visual_request": visual_request,
            "document_record": document_record,
            "observations": observations,
            "preview_visual_extraction_arguments": {
                "document_record": document_record,
                "observations": observations,
                "extractor_id": "fake-coverage",
                "extractor_kind": "agent_native",
                "visual_request": visual_request,
            },
            "unavailable_receipts": [],
            "receipts": {"observation_count": len(observations), "unavailable_count": 0},
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
        }

    runtime.document_coverage_pass = DocumentCoveragePassService(runtime, workbench=workbench)


def _understanding_analysis():
    return {
        "summary": [
            {
                "text": "The document explains design notes from the synthetic book.",
                "confidence": 0.9,
                "evidence_refs": [{"document_id": "doc_synthetic_ingestion_book", "chunk_id": 10000}],
            }
        ],
        "claims": [
            {
                "text": "Design notes are useful retrieval evidence.",
                "confidence": 0.88,
                "evidence_refs": [{"document_id": "doc_synthetic_ingestion_book", "chunk_id": 10000}],
            }
        ],
        "concepts": [
            {
                "name": "document intelligence ingestion",
                "description": (
                    "A workflow that turns document evidence into searchable and graph-covered "
                    "Memory OS records."
                ),
                "confidence": 0.86,
            }
        ],
    }


def test_prepare_document_ingestion_plan_persists_resumable_job(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)

    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="graph_coverage",
        page_window_size=2,
        analysis_policy="defer",
        approval_mode="agent_authorized",
    )

    assert plan["status"] == "planned"
    assert plan["write_performed"] is False
    assert plan["ingestion_id"].startswith("doc_ingest_")
    assert plan["source"]["path"] == str(source.resolve())
    assert plan["profile"] == "graph_coverage"
    assert plan["readiness"]["searchable"] is False
    assert plan["readiness"]["usable"] is False

    jobs = list_records(runtime.ledger, "jobs")
    assert any(job["job_id"] == plan["ingestion_id"] for job in jobs)

    inspected = runtime.inspect_document_ingestion(ingestion_id=plan["ingestion_id"])
    assert inspected["status"] == "planned"
    assert inspected["ingestion_id"] == plan["ingestion_id"]
    assert inspected["readiness"]["searchable"] is False
    assert inspected["next_action"]["tool"] == "run_document_ingestion"


def test_run_document_ingestion_makes_text_windows_searchable_before_usable(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="searchable",
        page_window_size=2,
        analysis_policy="defer",
        approval_mode="agent_authorized",
    )

    windows = [
        _review_packet_for_window(source, start=1, end=2, has_more=True),
        _review_packet_for_window(source, start=3, end=4, has_more=False),
    ]

    result = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=windows,
    )

    assert result["status"] == "partial"
    assert result["readiness"]["searchable"] is True
    assert result["readiness"]["ocr_covered"] is True
    assert result["readiness"]["visual_covered"] is True
    assert result["readiness"]["table_covered"] is True
    assert result["readiness"]["usable"] is False
    assert result["document_id"] == "doc_synthetic_ingestion_book"
    assert result["chunk_count"] == 2
    assert result["indexed_count"] == 2
    assert result["write_performed"] is True
    assert result["active_memory_write_performed"] is False
    assert result["understanding_packet"] is None
    assert result["document_promotion_transaction"] is None
    assert result["semantic_graph_edges_written"] == []

    inspected = runtime.inspect_document_ingestion(ingestion_id=plan["ingestion_id"])
    assert inspected["readiness"]["ocr_covered"] is True
    assert inspected["readiness"]["visual_covered"] is True
    assert inspected["readiness"]["table_covered"] is True
    assert inspected["understanding_packet"] is None
    assert inspected["document_promotion_transaction"] is None
    assert inspected["semantic_graph_edges_written"] == []

    search = runtime.search_memories("Design notes pages 3", limit=3)
    assert any(item["key"] == "doc_synthetic_ingestion_book" for item in search["results"])


def test_queued_document_ingestion_returns_progress_and_worker_completes(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="searchable",
        page_window_size=2,
        analysis_policy="defer",
        approval_mode="agent_authorized",
    )
    windows = [
        _review_packet_for_window(source, start=1, end=2, has_more=True),
        _review_packet_for_window(source, start=3, end=4, has_more=False),
    ]

    queued = runtime.enqueue_document_ingestion_run(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=windows,
    )
    queued_inspection = runtime.inspect_document_ingestion(ingestion_id=plan["ingestion_id"])
    worked = runtime.run_queued_document_ingestion(worker_id="worker-a")
    inspected = runtime.inspect_document_ingestion(ingestion_id=plan["ingestion_id"])
    replay = runtime.enqueue_document_ingestion_run(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=windows,
    )

    assert queued["status"] == "queued"
    assert queued["background_job"]["status"] == "queued"
    assert queued["next_action"]["tool"] == "inspect_document_ingestion"
    assert queued_inspection["status"] == "queued"
    assert queued_inspection["background_job"]["status"] == "queued"
    assert worked["processed"] is True
    assert worked["background_job"]["status"] == "completed"
    assert inspected["status"] == "partial"
    assert inspected["readiness"]["searchable"] is True
    assert inspected["background_job"]["status"] == "completed"
    assert inspected["progress"]["stored_window_count"] == 2
    assert inspected["last_successful_checkpoint"]["window_index"] == 1
    assert inspected["retry"]["attempt"] == 1
    assert inspected["dead_letter"]["dead_lettered"] is False
    assert replay["queued"] is False
    assert replay["status"] == "partial"
    assert replay["background_job"]["status"] == "completed"


def test_queued_document_ingestion_reuses_active_execution_job(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="searchable",
        page_window_size=2,
        analysis_policy="defer",
        approval_mode="agent_authorized",
    )
    first = runtime.enqueue_document_ingestion_run(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=[_review_packet_for_window(source, start=1, end=2, has_more=False)],
    )
    second = runtime.enqueue_document_ingestion_run(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=[_review_packet_for_window(source, start=3, end=4, has_more=False)],
    )
    jobs = [
        job
        for job in list_records(runtime.ledger, "jobs")
        if job.get("job_kind") == "document_ingestion_execution"
    ]

    assert first["background_job"]["job_id"] == second["background_job"]["job_id"]
    assert second["queued"] is True
    assert second["status"] == "queued"
    assert len(jobs) == 1


def test_queued_document_ingestion_reuse_preserves_fresh_progress(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="searchable",
        page_window_size=2,
        analysis_policy="defer",
        approval_mode="agent_authorized",
    )
    runtime.enqueue_document_ingestion_run(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=[_review_packet_for_window(source, start=1, end=2, has_more=False)],
    )
    stale_record = read_record(runtime.ledger, "jobs", plan["ingestion_id"])
    refreshed = {
        **stale_record,
        "windows": [
            {
                "window_id": "window:0000",
                "window_digest": "digest:latest",
                "window_index": 0,
                "status": "stored",
                "document_id": "doc_synthetic_ingestion_book",
                "artifact_id": "artifact:latest",
                "updated_at": "2026-05-21T12:00:00+00:00",
            }
        ],
    }
    upsert_record(runtime.ledger, "jobs", plan["ingestion_id"], refreshed)
    active_job_id = runtime.inspect_document_ingestion(
        ingestion_id=plan["ingestion_id"]
    )["background_job"]["job_id"]

    response = runtime.document_ingestion._queued_response(
        stale_record,
        job=runtime.job_runner.queue._read_job(active_job_id),
        queued=True,
    )
    inspected = runtime.inspect_document_ingestion(ingestion_id=plan["ingestion_id"])

    assert response["progress"]["stored_window_count"] == 1
    assert inspected["progress"]["stored_window_count"] == 1
    assert inspected["windows"][0]["artifact_id"] == "artifact:latest"


def test_queued_document_ingestion_dead_letters_after_worker_failures(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="searchable",
        page_window_size=2,
        analysis_policy="defer",
        approval_mode="agent_authorized",
    )
    queued = runtime.enqueue_document_ingestion_run(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=[_review_packet_for_window(source, start=1, end=2, has_more=False)],
    )

    def fail_run(**kwargs):
        raise RuntimeError("forced background failure")

    monkeypatch.setattr(runtime.document_ingestion, "run_document_ingestion", fail_run)
    first = runtime.run_queued_document_ingestion(worker_id="worker-a")
    second = runtime.run_queued_document_ingestion(worker_id="worker-b")
    third = runtime.run_queued_document_ingestion(worker_id="worker-c")
    inspected = runtime.inspect_document_ingestion(ingestion_id=plan["ingestion_id"])

    assert queued["background_job"]["max_attempts"] == 3
    assert first["status"] == "queued"
    assert second["status"] == "queued"
    assert third["status"] == "dead_lettered"
    assert third["background_job"]["dead_lettered_at"] is not None
    assert inspected["status"] == "failed"
    assert inspected["retry"]["attempt"] == 3
    assert inspected["retry"]["remaining_attempts"] == 0
    assert inspected["dead_letter"]["dead_lettered"] is True
    assert inspected["dead_letter"]["last_error"] == "forced background failure"


def test_queued_document_ingestion_failure_result_resets_status_to_queued(tmp_path, monkeypatch):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="searchable",
        page_window_size=2,
        analysis_policy="defer",
        approval_mode="agent_authorized",
    )
    runtime.enqueue_document_ingestion_run(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=[_review_packet_for_window(source, start=1, end=2, has_more=False)],
    )

    def fail_result(**kwargs):
        return {
            "status": "schema_failed",
            "ingestion_id": kwargs["ingestion_id"],
            "error": {"code": "forced", "message": "forced failure"},
        }

    monkeypatch.setattr(runtime.document_ingestion, "run_document_ingestion", fail_result)
    failed = runtime.run_queued_document_ingestion(worker_id="worker-a")
    inspected = runtime.inspect_document_ingestion(ingestion_id=plan["ingestion_id"])

    assert failed["status"] == "queued"
    assert failed["background_job"]["status"] == "queued"
    assert inspected["status"] == "queued"
    assert inspected["background_job"]["status"] == "queued"
    assert inspected["retry"]["attempt"] == 1
    assert inspected["error"]["code"] == "forced"


def test_run_document_ingestion_auto_runs_coverage_pass(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    _install_fake_coverage_pass(runtime)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="graph_coverage",
        page_window_size=2,
    )

    result = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=[_coverage_review_packet(source)],
    )

    assert result["status"] == "partial"
    assert result["readiness"]["searchable"] is True
    assert result["readiness"]["visual_covered"] is True
    assert result["readiness"]["ocr_covered"] is True
    assert result["readiness"]["table_covered"] is True
    assert result["readiness"]["usable"] is False
    assert result["coverage_pass"]["status"] == "ok"
    assert result["coverage_pass"]["write_performed"] is False
    assert result["coverage_pass"]["active_memory_write_performed"] is False
    assert result["coverage_pass"]["graph_write_performed"] is False
    assert result["visual_preview"]["visual_coverage"]["coverage_complete"] is True
    assert result["visual_preview"]["receipt"]["visual_artifact_count"] == 3

    inspected = runtime.inspect_document_ingestion(ingestion_id=plan["ingestion_id"])
    assert inspected["coverage_pass"]["status"] == "ok"
    assert inspected["coverage_pass"]["receipts"]["observation_count"] == 3
    assert inspected["visual_preview"]["visual_coverage"]["coverage_complete"] is True
    events = [
        event
        for event in list_records(runtime.ledger, "job_events")
        if event.get("event_type") == "document_coverage_pass"
    ]
    assert len(events) == 1
    assert events[0]["status"] == "ok"
    assert events[0]["receipts"]["observation_count"] == 3
    assert "workbench" not in events[0]
    assert "visual_preview" not in events[0]
    assert "observations" not in events[0]


def test_run_document_ingestion_records_partial_coverage_when_adapter_unavailable(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    _install_fake_coverage_pass(runtime, unavailable=True)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="graph_coverage",
        page_window_size=2,
    )

    result = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=[_coverage_review_packet(source)],
    )

    assert result["status"] == "partial"
    assert result["coverage_pass"]["status"] == "partial"
    assert result["coverage_pass"]["next_action"]["tool"] == "prepare_document_coverage_pass"
    assert {issue["code"] for issue in result["coverage_pass"]["blocking_issues"]} >= {
        "ocr_adapter_unavailable",
        "table_adapter_unavailable",
    }
    assert result["readiness"]["visual_covered"] is False
    assert result["readiness"]["ocr_covered"] is False
    assert result["readiness"]["table_covered"] is False
    assert result["active_memory_write_performed"] is False

    inspected = runtime.inspect_document_ingestion(ingestion_id=plan["ingestion_id"])
    assert inspected["next_action"]["tool"] == "prepare_document_coverage_pass"
    assert inspected["coverage_pass"]["status"] == "partial"
    events = [
        event
        for event in list_records(runtime.ledger, "job_events")
        if event.get("event_type") == "document_coverage_pass"
    ]
    assert events[0]["status"] == "partial"
    assert events[0]["blocking_issue_codes"][:2] == [
        "ocr_adapter_unavailable",
        "table_adapter_unavailable",
    ]
    assert "missing_visual_capability" in events[0]["blocking_issue_codes"]


def test_run_document_ingestion_keeps_required_visual_review_partial_without_observations(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    _install_fake_coverage_pass(runtime, no_observations=True)
    packet = _coverage_review_packet(source)
    packet["extraction_request"]["requested_capabilities"] = ["figure_description"]
    packet["extraction_request"]["image_refs"][0]["requested_capabilities"] = ["figure_description"]
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="graph_coverage",
        page_window_size=2,
        coverage_policy="required",
    )

    result = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=[packet],
    )

    assert result["coverage_pass"]["status"] == "partial"
    assert result["coverage_pass"]["next_action"]["tool"] == "prepare_document_coverage_pass"
    assert result["coverage_pass"]["visual_preview"] is None
    assert result["readiness"]["visual_covered"] is False
    assert result["readiness"]["usable"] is False
    assert [
        issue["details"]["capability"]
        for issue in result["coverage_pass"]["blocking_issues"]
        if issue["code"] == "missing_visual_capability"
    ] == ["figure_description"]


def test_run_document_ingestion_manual_and_external_bundle_skip_auto_coverage_pass(tmp_path):
    for policy in ("manual", "external_bundle"):
        case_path = tmp_path / policy
        case_path.mkdir()
        runtime = _runtime(case_path)
        source = _pdf(case_path)
        plan = runtime.prepare_document_ingestion_plan(
            source_path=str(source),
            project="Engram",
            domain="documents",
            profile="graph_coverage",
            page_window_size=2,
            coverage_policy=policy,
        )

        def fail_if_called(**kwargs):
            raise AssertionError(f"coverage pass should not run for {policy}")

        runtime.prepare_document_coverage_pass = fail_if_called
        result = runtime.run_document_ingestion(
            ingestion_id=plan["ingestion_id"],
            accept=True,
            approved_by="agent-review",
            review_packets=[_coverage_review_packet(source)],
        )

        assert result["status"] == "partial"
        assert result["coverage_policy"] == policy
        assert result["coverage_pass"] is None
        assert result["visual_preview"] is None
        assert result["active_memory_write_performed"] is False


def test_run_document_ingestion_coverage_pass_failure_is_checkpointed(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="graph_coverage",
        page_window_size=2,
    )

    def fail_coverage(**kwargs):
        raise RuntimeError("synthetic coverage failure")

    runtime.prepare_document_coverage_pass = fail_coverage
    result = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=[_coverage_review_packet(source)],
    )

    assert result["status"] == "partial"
    assert result["resumable"] is True
    assert result["chunk_count"] == 1
    assert result["readiness"]["searchable"] is True
    assert result["error"]["code"] == "document_coverage_pass_failed"
    assert result["error"]["details"]["exception_type"] == "RuntimeError"
    assert result["active_memory_write_performed"] is False

    inspected = runtime.inspect_document_ingestion(ingestion_id=plan["ingestion_id"])
    assert inspected["status"] == "partial"
    assert inspected["resumable"] is True
    assert inspected["error"]["code"] == "document_coverage_pass_failed"
    assert inspected["next_action"]["tool"] == "run_document_ingestion"


def test_run_document_ingestion_applies_book_catalog_metadata_to_future_books(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="searchable",
        page_window_size=2,
        analysis_policy="defer",
        approval_mode="agent_authorized",
    )
    packet = _review_packet_for_window(source, start=1, end=2, has_more=False)
    packet["source"]["document_id"] = "doc_advanced_game_design"
    packet["disassembly"]["document"]["document_id"] = "doc_advanced_game_design"
    packet["disassembly"]["document"]["title"] = "Advanced Game Design"

    result = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=[packet],
    )

    assert result["readiness"]["searchable"] is True
    document = read_record(runtime.ledger, "documents", "doc_advanced_game_design")
    assert document["document_catalog"]["primary_subject"] == "game_design"
    assert document["document_catalog"]["reading_role"] == "core"

    search = runtime.search_memories("Design notes pages 1", limit=3, tags=["core-game-design"])
    assert [item["key"] for item in search["results"]] == ["doc_advanced_game_design"]
    assert search["results"][0]["tags"] == [
        "document-ingestion",
        "book",
        "game-design",
        "core-game-design",
    ]


def test_run_document_ingestion_refreshes_stale_uncatalogued_metadata(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    upsert_record(
        runtime.ledger,
        "documents",
        "doc_ux_for_beginners",
        {
            "document_id": "doc_ux_for_beginners",
            "title": "UX for Beginners",
            "source_ref": {"path": str(source), "source_type": "pdf"},
            "document_catalog": {
                "primary_subject": "uncatalogued",
                "secondary_subjects": [],
                "collections": ["uncatalogued_books"],
                "reading_role": "reference",
                "adjacent_to_game_design": False,
                "exclude_from_core_game_design_corpus": True,
                "corpus_tags": ["book", "uncatalogued-book"],
                "classification_basis": "title_path_rules",
                "classification_confidence": 0.2,
            },
        },
    )
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="searchable",
        page_window_size=2,
    )
    packet = _review_packet_for_window(source, start=1, end=2, has_more=False)
    packet["source"]["document_id"] = "doc_ux_for_beginners"
    packet["disassembly"]["document"]["document_id"] = "doc_ux_for_beginners"
    packet["disassembly"]["document"]["title"] = "UX for Beginners"

    result = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=[packet],
    )

    assert result["readiness"]["searchable"] is True
    document = read_record(runtime.ledger, "documents", "doc_ux_for_beginners")
    assert document["document_catalog"]["primary_subject"] == "ux_design"
    assert document["document_catalog"]["corpus_tags"] == ["book", "ux-design"]

    search = runtime.search_memories("Design notes pages 1", limit=3, tags=["ux-design"])
    assert [item["key"] for item in search["results"]] == ["doc_ux_for_beginners"]


def test_ingestion_readiness_keeps_coverage_false_until_all_pages_are_observed(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="searchable",
        page_window_size=2,
    )
    first_window = _review_packet_for_window(source, start=1, end=2, has_more=True)

    result = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=[first_window],
    )

    assert result["readiness"]["searchable"] is True
    assert result["readiness"]["ocr_covered"] is False
    assert result["readiness"]["visual_covered"] is False
    assert result["readiness"]["table_covered"] is False


def test_run_document_ingestion_stores_distinct_artifacts_for_each_window(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="searchable",
        page_window_size=2,
    )
    windows = [
        _review_packet_for_window(source, start=1, end=2, has_more=True),
        _review_packet_for_window(source, start=3, end=4, has_more=False),
    ]

    result = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=windows,
    )

    assert result["status"] == "partial"
    artifacts = list_records(runtime.ledger, "knowledge_artifacts")
    artifact_ids = {artifact["artifact_id"] for artifact in artifacts}
    assert len(artifacts) == 2
    assert len(artifact_ids) == 2
    page_refs = {
        page["page_number"]
        for artifact in artifacts
        for page in artifact["page_refs"]
    }
    assert page_refs == {1, 2, 3, 4}


def test_resume_document_ingestion_replays_without_duplicate_chunks_or_artifacts(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="searchable",
        page_window_size=2,
    )
    windows = [
        _review_packet_for_window(source, start=1, end=2, has_more=True),
        _review_packet_for_window(source, start=3, end=4, has_more=False),
    ]

    first = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=windows,
    )
    replay = runtime.resume_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=windows,
    )

    assert replay["status"] == "partial"
    assert replay["readiness"]["searchable"] is True
    assert replay["idempotent_replay"] is True
    assert replay["chunk_count"] == first["chunk_count"]
    assert len(list_records(runtime.ledger, "chunks")) == first["chunk_count"]
    assert len({artifact["artifact_id"] for artifact in replay["artifacts"]}) == len(replay["artifacts"])


def test_resume_document_ingestion_mixed_replay_reports_new_writes(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="searchable",
        page_window_size=2,
    )
    first_window = _review_packet_for_window(source, start=1, end=2, has_more=True)
    second_window = _review_packet_for_window(source, start=3, end=4, has_more=False)

    initial = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=[first_window],
    )
    resumed = runtime.resume_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=[first_window, second_window],
    )

    assert initial["chunk_count"] == 1
    assert resumed["write_performed"] is True
    assert resumed["idempotent_replay"] is False
    assert resumed["chunk_count"] == 2
    artifacts = list_records(runtime.ledger, "knowledge_artifacts")
    assert len(artifacts) == 2
    assert len({artifact["artifact_id"] for artifact in artifacts}) == 2
    assert len({artifact["artifact_id"] for artifact in resumed["artifacts"]}) == len(resumed["artifacts"])


def test_resume_document_ingestion_reuses_complete_staged_packets_without_reviewer(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="graph_coverage",
        page_window_size=2,
        analysis_policy="connected_agent",
    )
    windows = [
        _review_packet_for_window(source, start=1, end=2, has_more=True),
        _review_packet_for_window(source, start=3, end=4, has_more=False),
    ]
    structural = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=windows,
    )

    def fail_if_called(**kwargs):
        raise AssertionError("resume should reuse staged document artifacts")

    runtime.document_ingestion.document_intake_reviewer = fail_if_called
    semantic = runtime.resume_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        understanding_analysis=_understanding_analysis(),
    )

    assert structural["readiness"]["structural_graph_covered"] is True
    assert semantic["readiness"]["semantic_graph_covered"] is True
    assert semantic["semantic_graph_edges_written"]
    assert semantic["chunk_count"] == structural["chunk_count"]
    assert semantic["stage_report"]["stages"][0]["complete"] is True


def test_resume_document_ingestion_falls_back_when_staged_packets_are_incomplete(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="searchable",
        page_window_size=2,
    )
    first_window = _review_packet_for_window(source, start=1, end=2, has_more=True)
    second_window = _review_packet_for_window(source, start=3, end=4, has_more=False)
    initial = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=[first_window],
    )
    calls = []

    def reviewer(**kwargs):
        calls.append(kwargs.get("resume_token"))
        return second_window if kwargs.get("resume_token") else first_window

    runtime.document_ingestion.document_intake_reviewer = reviewer
    resumed = runtime.resume_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
    )

    assert initial["chunk_count"] == 1
    assert calls == [None, "resume-3"]
    assert resumed["chunk_count"] == 2
    assert resumed["write_performed"] is True
    assert len(list_records(runtime.ledger, "knowledge_artifacts")) == 2


def test_run_document_ingestion_promotes_structural_graph_edges_idempotently(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="graph_coverage",
        page_window_size=2,
    )
    windows = [
        _review_packet_for_window(source, start=1, end=2, has_more=True),
        _review_packet_for_window(source, start=3, end=4, has_more=False),
    ]

    first = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=windows,
    )
    first_edges = {
        edge_id: read_record(runtime.ledger, "graph_edges", edge_id)
        for edge_id in first["graph_edges_written"]
    }
    second = runtime.resume_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="different-reviewer",
        review_packets=windows,
    )
    second_edges = {
        edge_id: read_record(runtime.ledger, "graph_edges", edge_id)
        for edge_id in second["graph_edges_written"]
    }

    assert first["readiness"]["structural_graph_covered"] is True
    assert first["graph_write_performed"] is True
    assert first["graph_edges_written"]
    assert second["graph_edges_written"] == first["graph_edges_written"]
    assert second["graph_write_performed"] is False
    assert second["idempotent_replay"] is True
    assert first_edges == second_edges
    assert {edge["created_by"] for edge in second_edges.values()} == {"agent-review"}
    edges = list_records(runtime.ledger, "graph_edges")
    assert len(edges) == 3
    source_edges = [edge for edge in edges if edge["edge_type"] == "cites"]
    chunk_edges = [edge for edge in edges if edge["edge_type"] == "contains"]
    assert len(source_edges) == 1
    assert len(chunk_edges) == 2
    assert source_edges[0]["from_ref"] == {
        "kind": "document",
        "key": "doc_synthetic_ingestion_book",
        "document_id": "doc_synthetic_ingestion_book",
    }
    assert source_edges[0]["to_ref"] == {
        "kind": "source",
        "key": source.resolve().as_uri(),
        "source_uri": source.resolve().as_uri(),
        "sha256": "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    chunk_records = {
        chunk["chunk_record_id"]: chunk
        for chunk in list_records(runtime.ledger, "chunks")
    }
    for edge in chunk_edges:
        assert edge["from_ref"] == {
            "kind": "document",
            "key": "doc_synthetic_ingestion_book",
            "document_id": "doc_synthetic_ingestion_book",
        }
        chunk_ref = edge["to_ref"]
        assert chunk_ref["kind"] == "chunk"
        assert chunk_ref["key"] == chunk_ref["chunk_record_id"]
        assert chunk_ref["document_id"] == "doc_synthetic_ingestion_book"
        chunk = chunk_records[chunk_ref["chunk_record_id"]]
        assert chunk_ref["chunk_id"] == chunk["chunk_id"]
        assert chunk_ref["chunk_record_id"] == chunk["chunk_record_id"]


def test_run_document_ingestion_promotes_semantic_graph_from_supplied_analysis(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="graph_coverage",
        page_window_size=2,
        analysis_policy="connected_agent",
    )
    windows = [_review_packet_for_window(source, start=1, end=2, has_more=False)]
    result = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=windows,
        understanding_analysis=_understanding_analysis(),
    )

    assert result["readiness"]["semantic_graph_covered"] is True
    assert result["semantic_graph_edges_written"]
    assert result["understanding_packet"]["receipt"]["claim_candidate_count"] == 1
    assert result["understanding_packet"]["receipt"]["chunk_ref_count"] == 1
    assert result["document_promotion_transaction"]["receipt"]["selected_edge_count"] >= 1


def test_run_document_ingestion_records_semantic_promotion_failure(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="graph_coverage",
        page_window_size=2,
        analysis_policy="connected_agent",
    )
    windows = [_review_packet_for_window(source, start=1, end=2, has_more=False)]
    original_apply = runtime.apply_document_promotion_transaction

    def fail_promotion(*args, **kwargs):
        return {
            "status": "schema_failed",
            "error": {"code": "synthetic_failure", "message": "promotion failed"},
            "graph_edges_written": [],
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
        }

    runtime.apply_document_promotion_transaction = fail_promotion

    result = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=windows,
        understanding_analysis=_understanding_analysis(),
    )

    runtime.apply_document_promotion_transaction = original_apply

    assert result["status"] == "partial"
    assert result["error"]["code"] == "semantic_promotion_failed"
    assert result["error"]["details"]["status"] == "schema_failed"
    assert result["write_performed"] is True
    assert result["active_memory_write_performed"] is False
    assert result["graph_write_performed"] is True
    assert result["document_id"] == "doc_synthetic_ingestion_book"
    assert result["chunk_count"] == 1
    assert result["indexed_count"] == 1
    assert result["readiness"]["searchable"] is True
    assert result["readiness"]["structural_graph_covered"] is True
    assert result["readiness"]["semantic_graph_covered"] is False
    assert result["semantic_graph_edges_written"] == []

    inspected = runtime.inspect_document_ingestion(ingestion_id=plan["ingestion_id"])
    assert inspected["status"] == "partial"
    assert inspected["error"]["code"] == "semantic_promotion_failed"
    assert inspected["error"]["details"]["error"]["code"] == "synthetic_failure"
    assert inspected["document_id"] == "doc_synthetic_ingestion_book"
    assert inspected["chunk_count"] == 1


def test_resume_semantic_ingestion_dedupes_existing_edges_across_reviewers(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="graph_coverage",
        page_window_size=2,
        analysis_policy="connected_agent",
    )
    windows = [_review_packet_for_window(source, start=1, end=2, has_more=False)]

    first = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=windows,
        understanding_analysis=_understanding_analysis(),
    )
    graph_edge_count = len(list_records(runtime.ledger, "graph_edges"))
    semantic_edges_written = list(first["semantic_graph_edges_written"])
    replay = runtime.resume_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="different-reviewer",
        review_packets=windows,
        understanding_analysis=_understanding_analysis(),
    )

    assert first["readiness"]["semantic_graph_covered"] is True
    assert semantic_edges_written
    assert replay["readiness"]["semantic_graph_covered"] is True
    assert replay["semantic_graph_edges_written"] == semantic_edges_written
    assert replay["graph_write_performed"] is False
    assert replay["idempotent_replay"] is True
    assert len(list_records(runtime.ledger, "graph_edges")) == graph_edge_count
    assert {
        read_record(runtime.ledger, "graph_edges", edge_id)["created_by"]
        for edge_id in replay["semantic_graph_edges_written"]
    } == {"agent-review"}


def test_resume_semantic_ingestion_does_not_count_inactive_same_reviewer_replay_edges(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="graph_coverage",
        page_window_size=2,
        analysis_policy="connected_agent",
    )
    windows = [_review_packet_for_window(source, start=1, end=2, has_more=False)]

    first = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=windows,
        understanding_analysis=_understanding_analysis(),
    )
    inactive_edge_ids = list(first["semantic_graph_edges_written"])
    assert inactive_edge_ids
    for index, edge_id in enumerate(inactive_edge_ids):
        edge = read_record(runtime.ledger, "graph_edges", edge_id)
        upsert_record(
            runtime.ledger,
            "graph_edges",
            edge_id,
            {
                **edge,
                "status": "inactive" if index % 2 == 0 else "rejected",
            },
        )

    replay = runtime.resume_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=windows,
        understanding_analysis=_understanding_analysis(),
    )

    assert replay["readiness"]["semantic_graph_covered"] is False
    assert replay["graph_write_performed"] is False
    assert replay["idempotent_replay"] is True
    assert replay["semantic_graph_edges_written"] == []


def test_resume_document_ingestion_without_analysis_preserves_semantic_graph_state(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="graph_coverage",
        page_window_size=2,
        analysis_policy="connected_agent",
    )
    windows = [_review_packet_for_window(source, start=1, end=2, has_more=False)]

    first = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=windows,
        understanding_analysis=_understanding_analysis(),
    )
    replay = runtime.resume_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=windows,
    )

    assert first["readiness"]["semantic_graph_covered"] is True
    assert replay["readiness"]["semantic_graph_covered"] is True
    assert replay["semantic_graph_edges_written"] == first["semantic_graph_edges_written"]
    assert replay["understanding_packet"] == first["understanding_packet"]
    assert replay["document_promotion_transaction"] == first["document_promotion_transaction"]


def test_semantic_run_after_structural_replay_reports_graph_write(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="graph_coverage",
        page_window_size=2,
        analysis_policy="connected_agent",
    )
    windows = [
        _review_packet_for_window(source, start=1, end=2, has_more=True),
        _review_packet_for_window(source, start=3, end=4, has_more=False),
    ]

    structural = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=windows,
    )
    semantic = runtime.resume_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=windows,
        understanding_analysis=_understanding_analysis(),
    )

    assert structural["readiness"]["structural_graph_covered"] is True
    assert structural["semantic_graph_edges_written"] == []
    assert semantic["readiness"]["semantic_graph_covered"] is True
    assert semantic["semantic_graph_edges_written"]
    assert semantic["graph_write_performed"] is True
    assert semantic["idempotent_replay"] is False


def test_semantic_failure_after_structural_progress_stays_resumable(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="graph_coverage",
        page_window_size=2,
        analysis_policy="connected_agent",
    )
    windows = [
        _review_packet_for_window(source, start=1, end=2, has_more=True),
        _review_packet_for_window(source, start=3, end=4, has_more=False),
    ]
    structural = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=windows,
    )
    original_apply = runtime.apply_document_promotion_transaction

    def fail_promotion(*args, **kwargs):
        return {
            "status": "schema_failed",
            "error": {"code": "synthetic_failure", "message": "promotion failed"},
            "graph_edges_written": [],
            "write_performed": False,
            "active_memory_write_performed": False,
            "graph_write_performed": False,
        }

    runtime.apply_document_promotion_transaction = fail_promotion

    result = runtime.resume_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=windows,
        understanding_analysis=_understanding_analysis(),
    )

    runtime.apply_document_promotion_transaction = original_apply

    assert structural["readiness"]["searchable"] is True
    assert structural["readiness"]["structural_graph_covered"] is True
    assert structural["semantic_graph_edges_written"] == []
    assert result["status"] == "partial"
    assert result["write_performed"] is False
    assert result["error"]["code"] == "semantic_promotion_failed"
    assert result["readiness"]["searchable"] is True
    assert result["readiness"]["structural_graph_covered"] is True
    assert result["readiness"]["semantic_graph_covered"] is False

    inspected = runtime.inspect_document_ingestion(ingestion_id=plan["ingestion_id"])
    assert inspected["status"] == "partial"
    assert inspected["resumable"] is True
    assert inspected["error"]["code"] == "semantic_promotion_failed"
    assert inspected["error"]["details"]["error"]["code"] == "synthetic_failure"


def test_run_document_ingestion_does_not_mark_structural_graph_covered_without_chunks(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="graph_coverage",
        page_window_size=2,
    )

    result = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=[_empty_text_review_packet(source)],
    )

    assert result["status"] == "partial"
    assert result["chunk_count"] == 0
    assert result["readiness"]["searchable"] is False
    assert result["readiness"]["structural_graph_covered"] is False


def test_run_document_ingestion_preserves_project_domain_retrieval_filters(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="searchable",
        page_window_size=2,
    )

    result = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=[_review_packet_for_window(source, start=1, end=2, has_more=False)],
    )

    assert result["status"] == "partial"
    project_search = runtime.search_memories("Design notes", project="Engram", limit=3)
    domain_search = runtime.search_memories("Design notes", domain="documents", limit=3)
    assert any(item["key"] == "doc_synthetic_ingestion_book" for item in project_search["results"])
    assert any(item["key"] == "doc_synthetic_ingestion_book" for item in domain_search["results"])


def test_run_document_ingestion_preserves_project_domain_on_document_and_chunks(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Design Skills",
        domain="ux_design",
        profile="searchable",
        page_window_size=2,
    )

    result = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=[_review_packet_for_window(source, start=1, end=2, has_more=False)],
    )

    assert result["status"] == "partial"
    document = read_record(runtime.ledger, "documents", "doc_synthetic_ingestion_book")
    assert document["project"] == "Design Skills"
    assert document["domain"] == "ux_design"
    assert document["document_primary_subject"] == "ux_design"
    assert document["document_catalog"]["content_form"] == "book"
    assert document["tags"] == ["document-ingestion", "book", "ux-design"]

    chunks = [
        record
        for record in list_records(runtime.ledger, "chunks")
        if record.get("document_id") == "doc_synthetic_ingestion_book"
    ]
    assert chunks
    assert {chunk.get("project") for chunk in chunks} == {"Design Skills"}
    assert {chunk.get("domain") for chunk in chunks} == {"ux_design"}
    assert all(chunk.get("document_catalog", {}).get("content_form") == "book" for chunk in chunks)
    assert all(chunk.get("document_primary_subject") == "ux_design" for chunk in chunks)
    assert all(chunk.get("tags") == ["document-ingestion", "book", "ux-design"] for chunk in chunks)


def test_rerun_document_ingestion_refreshes_existing_chunk_catalog_metadata(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    packet = _review_packet_for_window(source, start=1, end=2, has_more=False)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="searchable",
        page_window_size=2,
    )
    first = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=[packet],
    )
    assert first["status"] == "partial"
    document = read_record(runtime.ledger, "documents", "doc_synthetic_ingestion_book")
    document["title"] = "Advanced Game Design"
    document["document"]["title"] = "Advanced Game Design"
    upsert_record(runtime.ledger, "documents", "doc_synthetic_ingestion_book", document)

    second = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=[packet],
    )

    assert second["status"] == "partial"
    chunks = [
        record
        for record in list_records(runtime.ledger, "chunks")
        if record.get("document_id") == "doc_synthetic_ingestion_book"
    ]
    assert chunks
    assert all(chunk["document_primary_subject"] == "game_design" for chunk in chunks)
    assert all(chunk["tags"] == ["document-ingestion", "book", "game-design", "core-game-design"] for chunk in chunks)


def test_repair_document_metadata_removes_duplicate_completion_chunks(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    packet = _review_packet_for_window(source, start=1, end=2, has_more=False)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="searchable",
        page_window_size=2,
    )
    runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=[packet],
    )
    original_chunks = [
        record
        for record in list_records(runtime.ledger, "chunks")
        if record.get("document_id") == "doc_synthetic_ingestion_book"
    ]
    duplicate = {
        **original_chunks[0],
        "chunk_record_id": "doc_synthetic_ingestion_book:chunk:10000",
        "ingestion_id": None,
        "window_index": None,
    }
    upsert_record(runtime.ledger, "chunks", duplicate["chunk_record_id"], duplicate)

    result = runtime.repair_document_metadata(
        document_ids=["doc_synthetic_ingestion_book"],
        accept=True,
        approved_by="agent-review",
    )

    assert result["status"] == "ok"
    assert result["repairs"][0]["duplicate_chunk_count"] == 1
    chunks = [
        record
        for record in list_records(runtime.ledger, "chunks")
        if record.get("document_id") == "doc_synthetic_ingestion_book"
    ]
    assert len(chunks) == len(original_chunks)
    assert all(chunk["chunk_record_id"] != "doc_synthetic_ingestion_book:chunk:10000" for chunk in chunks)


def test_run_document_ingestion_failure_after_first_window_records_partial_writes(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="searchable",
        page_window_size=2,
    )
    windows = [
        _review_packet_for_window(source, start=1, end=2, has_more=True),
        _review_packet_for_window(source, start=3, end=4, has_more=False),
    ]
    original_prepare = runtime.prepare_document_artifact_store
    calls = {"count": 0}

    def fail_second_prepare(packet):
        calls["count"] += 1
        if calls["count"] == 2:
            return {"status": "schema_failed", "error": {"code": "boom"}}
        return original_prepare(packet)

    runtime.prepare_document_artifact_store = fail_second_prepare

    result = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=windows,
    )

    assert result["status"] == "partial"
    assert result["write_performed"] is True
    assert result["active_memory_write_performed"] is False
    assert result["document_id"] == "doc_synthetic_ingestion_book"
    assert result["chunk_count"] > 0
    assert result["indexed_count"] > 0
    assert result["error"]["code"] == "artifact_prepare_failed"
    assert len(result["artifacts"]) == 1

    inspected = runtime.inspect_document_ingestion(ingestion_id=plan["ingestion_id"])
    assert inspected["status"] == "partial"
    assert inspected["document_id"] == "doc_synthetic_ingestion_book"
    assert inspected["chunk_count"] > 0
    assert inspected["error"]["code"] == "artifact_prepare_failed"
    assert inspected["artifacts"] == result["artifacts"]


def test_run_document_ingestion_error_checkpoint_retrieval_failure_keeps_original_error(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="searchable",
        page_window_size=2,
    )
    windows = [
        _review_packet_for_window(source, start=1, end=2, has_more=True),
        _review_packet_for_window(source, start=3, end=4, has_more=False),
    ]
    original_prepare = runtime.prepare_document_artifact_store
    original_upsert = runtime.retrieval.upsert_chunk_records
    calls = {"count": 0}

    def fail_retrieval_index(*args, **kwargs):
        raise RuntimeError("synthetic checkpoint retrieval failure")

    def fail_second_prepare(packet):
        calls["count"] += 1
        if calls["count"] == 2:
            runtime.retrieval.upsert_chunk_records = fail_retrieval_index
            return {"status": "schema_failed", "error": {"code": "boom"}}
        return original_prepare(packet)

    runtime.prepare_document_artifact_store = fail_second_prepare

    try:
        result = runtime.run_document_ingestion(
            ingestion_id=plan["ingestion_id"],
            accept=True,
            approved_by="agent-review",
            review_packets=windows,
        )
    finally:
        runtime.prepare_document_artifact_store = original_prepare
        runtime.retrieval.upsert_chunk_records = original_upsert

    assert result["status"] == "partial"
    assert result["resumable"] is True
    assert result["write_performed"] is True
    assert result["active_memory_write_performed"] is False
    assert result["document_id"] == "doc_synthetic_ingestion_book"
    assert result["chunk_count"] == 1
    assert result["error"]["code"] == "artifact_prepare_failed"
    assert result["error"]["details"]["status"] == "schema_failed"
    checkpoint_error = result["error"]["details"]["checkpoint_retrieval_index_error"]
    assert checkpoint_error["code"] == "checkpoint_retrieval_index_failed"
    assert checkpoint_error["details"]["exception_type"] == "RuntimeError"
    assert len(result["artifacts"]) == 1

    inspected = runtime.inspect_document_ingestion(ingestion_id=plan["ingestion_id"])
    assert inspected["status"] == "partial"
    assert inspected["resumable"] is True
    assert inspected["document_id"] == "doc_synthetic_ingestion_book"
    assert inspected["chunk_count"] == 1
    assert inspected["active_memory_write_performed"] is False
    assert inspected["error"]["code"] == "artifact_prepare_failed"
    assert inspected["error"]["details"]["checkpoint_retrieval_index_error"] == checkpoint_error


def test_run_document_ingestion_retrieval_index_failure_keeps_progress_resumable(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="searchable",
        page_window_size=2,
    )

    def fail_retrieval_index(*args, **kwargs):
        raise RuntimeError("synthetic retrieval index failure")

    runtime.retrieval.upsert_chunk_records = fail_retrieval_index

    result = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=[_review_packet_for_window(source, start=1, end=2, has_more=False)],
    )

    assert result["status"] == "partial"
    assert result["resumable"] is True
    assert result["error"]["code"] == "retrieval_index_checkpoint_failed"
    assert result["error"]["details"]["exception_type"] == "RuntimeError"
    assert result["active_memory_write_performed"] is False
    assert result["document_id"] == "doc_synthetic_ingestion_book"
    assert result["chunk_count"] == 1
    assert result["indexed_count"] == 0
    assert result["readiness"]["searchable"] is False
    assert len(result["artifacts"]) == 1

    inspected = runtime.inspect_document_ingestion(ingestion_id=plan["ingestion_id"])
    assert inspected["status"] == "partial"
    assert inspected["resumable"] is True
    assert inspected["document_id"] == "doc_synthetic_ingestion_book"
    assert inspected["chunk_count"] == 1
    assert inspected["indexed_count"] == 0
    assert inspected["readiness"]["searchable"] is False
    assert len(inspected["artifacts"]) == 1
    assert inspected["error"]["code"] == "retrieval_index_checkpoint_failed"
    assert inspected["active_memory_write_performed"] is False


def test_run_document_ingestion_failure_before_progress_remains_schema_failed(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="searchable",
        page_window_size=2,
    )

    def fail_prepare(packet):
        return {"status": "schema_failed", "error": {"code": "boom"}}

    runtime.prepare_document_artifact_store = fail_prepare

    result = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=[_review_packet_for_window(source, start=1, end=2, has_more=False)],
    )

    assert result["status"] == "schema_failed"
    assert result["write_performed"] is False
    assert result["error"]["code"] == "artifact_prepare_failed"

    inspected = runtime.inspect_document_ingestion(ingestion_id=plan["ingestion_id"])
    assert inspected["status"] == "schema_failed"
    assert inspected["resumable"] is False
    assert inspected["chunk_count"] == 0


def test_run_document_ingestion_merges_existing_artifacts(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="searchable",
        page_window_size=2,
    )
    existing_artifact = {"artifact_id": "doc_artifact:existing", "review_state": "ledgered_evidence"}
    upsert_record(runtime.ledger, "jobs", plan["ingestion_id"], {**plan, "artifacts": [existing_artifact]})

    result = runtime.run_document_ingestion(
        ingestion_id=plan["ingestion_id"],
        accept=True,
        approved_by="agent-review",
        review_packets=[_review_packet_for_window(source, start=1, end=2, has_more=False)],
    )

    artifact_ids = [artifact["artifact_id"] for artifact in result["artifacts"]]
    assert "doc_artifact:existing" in artifact_ids
    assert len(artifact_ids) == 2


def test_prepare_document_ingestion_plan_preserves_existing_progress(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="graph_coverage",
        page_window_size=2,
    )
    progressed = {
        **plan,
        "status": "partial",
        "document_id": "doc_book",
        "windows": [{"window_id": "window_1", "status": "complete"}],
        "artifacts": [{"artifact_id": "artifact_1"}],
        "coverage_maps": [{"coverage_id": "coverage_1"}],
        "errors": [{"code": "needs_review", "message": "review required"}],
        "readiness": {**plan["readiness"], "searchable": True},
    }
    upsert_record(runtime.ledger, "jobs", plan["ingestion_id"], progressed)

    prepared_again = runtime.prepare_document_ingestion_plan(
        source_path=str(source),
        project="Engram",
        domain="documents",
        profile="graph_coverage",
        page_window_size=9,
    )

    assert prepared_again["write_performed"] is False
    assert prepared_again["status"] == "partial"
    assert prepared_again["document_id"] == "doc_book"
    assert prepared_again["windows"] == [{"window_id": "window_1", "status": "complete"}]
    assert prepared_again["artifacts"] == [{"artifact_id": "artifact_1"}]
    assert prepared_again["coverage_maps"] == [{"coverage_id": "coverage_1"}]
    assert prepared_again["errors"] == [{"code": "needs_review", "message": "review required"}]
    assert prepared_again["readiness"]["searchable"] is True
    assert prepared_again["page_window_size"] == 2
    assert prepared_again["next_action"]["tool"] == "run_document_ingestion"


def test_inspect_document_ingestion_by_document_id(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)
    plan = runtime.prepare_document_ingestion_plan(source_path=str(source))
    progressed = {**plan, "document_id": "doc_book", "status": "partial"}
    upsert_record(runtime.ledger, "jobs", plan["ingestion_id"], progressed)

    inspected = runtime.inspect_document_ingestion(document_id="doc_book")

    assert inspected["status"] == "partial"
    assert inspected["document_id"] == "doc_book"
    assert inspected["ingestion_id"] == plan["ingestion_id"]
    assert inspected["write_performed"] is False


def test_inspect_document_ingestion_not_found_payload(tmp_path):
    runtime = _runtime(tmp_path)

    inspected = runtime.inspect_document_ingestion(ingestion_id="doc_ingest_missing")

    assert inspected["status"] == "not_found"
    assert inspected["ingestion_id"] == "doc_ingest_missing"
    assert inspected["write_performed"] is False
    assert inspected["error"]["code"] == "not_found"


def test_prepare_document_ingestion_plan_rejects_non_numeric_page_window_size(tmp_path):
    runtime = _runtime(tmp_path)
    source = _pdf(tmp_path)

    try:
        runtime.prepare_document_ingestion_plan(source_path=str(source), page_window_size="many")
    except ValueError as exc:
        assert "page_window_size must be an integer" in str(exc)
    else:
        raise AssertionError("expected ValueError")
