from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from core.context_builder import build_context_receipt, make_filters
from core.context_compiler import (
    build_context_query,
    build_handoff_packet,
    compile_context_packet,
    get_context_profile,
)
from core.document_intelligence import (
    prepare_document_draft,
    prepare_visual_artifact_record,
    preview_document_extraction,
)
from core.memory_quality import audit_memory_quality
from core.project_capsule import build_project_capsule_draft
from core.usage_meter import ESTIMATE_METHOD, estimate_tokens
from core.workflow_templates import list_workflow_templates


SCHEMA_VERSION = "2026-04-28.agent-reliability.v1"
BOOK_DISMANTLING_GATE_SCHEMA_VERSION = "2026-05-12.book-dismantling-gate.v1"
DEFAULT_PROJECT = "C:/Dev/Engram"
DEFAULT_DOMAIN = "agent-reliability"
EVAL_KEY_PREFIX = "_engram_eval_"
LOGGER = logging.getLogger(__name__)
REQUIRED_BOOK_DISMANTLING_FIXTURE_IDS = [
    "clean_text_pdf",
    "book_style_pdf",
    "image_only_pdf",
    "table_heavy_page",
    "figure_caption_page",
    "rotated_page",
    "ocr_noise_page",
]


@dataclass(frozen=True)
class AgentReliabilityScenario:
    scenario_id: str
    description: str
    key: str
    content: str
    query: str
    expected_key: str
    title: str
    tags: list[str]
    project: str = DEFAULT_PROJECT
    domain: str = DEFAULT_DOMAIN
    max_chunks: int = 3
    budget_chars: int = 1200
    include_stale: bool = False
    canonical_only: bool = False
    distractors: list[dict[str, Any]] = field(default_factory=list)


def default_agent_reliability_scenarios() -> list[AgentReliabilityScenario]:
    return [
        AgentReliabilityScenario(
            scenario_id="retrieval_ladder_context_budget",
            description=(
                "Seed one calibration memory and verify search, chunk retrieval, "
                "budget accounting, and token estimates stay aligned."
            ),
            key=f"{EVAL_KEY_PREFIX}retrieval_ladder_context_budget",
            expected_key=f"{EVAL_KEY_PREFIX}retrieval_ladder_context_budget",
            title="Agent Reliability Retrieval Ladder",
            content=(
                "## Retrieval Ladder Calibration\n\n"
                "Engram should let agents search first, retrieve only bounded "
                "chunks, and see budget accounting before escalating to full "
                "memory reads."
            ),
            query="Engram retrieval ladder bounded context budget accounting",
            tags=["agent-eval", "reliability", "context-pack"],
            max_chunks=2,
            budget_chars=1000,
        ),
        AgentReliabilityScenario(
            scenario_id="current_memory_excludes_stale_distractor",
            description=(
                "Seed a stale distractor with matching text and verify the current "
                "memory is selected when stale memories are excluded."
            ),
            key=f"{EVAL_KEY_PREFIX}current_memory_excludes_stale_distractor",
            expected_key=f"{EVAL_KEY_PREFIX}current_memory_excludes_stale_distractor",
            title="Agent Reliability Current Memory",
            content=(
                "## Current Memory Preference\n\n"
                "Current reviewed source-backed memory should be preferred over a "
                "stale matching claim during agent reliability checks."
            ),
            query="current reviewed source-backed memory preferred stale matching claim",
            tags=["agent-eval", "reliability", "freshness"],
            max_chunks=2,
            budget_chars=1000,
            distractors=[
                {
                    "key": f"{EVAL_KEY_PREFIX}stale_memory_preference_distractor",
                    "title": "Agent Reliability Stale Distractor",
                    "content": (
                        "## Stale Memory Preference\n\n"
                        "Current reviewed source-backed memory should be preferred over a "
                        "stale matching claim during agent reliability checks."
                    ),
                    "tags": ["agent-eval", "reliability", "freshness"],
                    "canonical": True,
                    "potentially_stale": True,
                    "stale_reason": "seeded stale distractor for agent reliability eval",
                }
            ],
        ),
        AgentReliabilityScenario(
            scenario_id="reviewed_source_backed_metadata_preference",
            description=(
                "Verify reviewed source-backed memories can be targeted through "
                "required metadata tags before agent context assembly."
            ),
            key=f"{EVAL_KEY_PREFIX}reviewed_source_backed_metadata_preference",
            expected_key=f"{EVAL_KEY_PREFIX}reviewed_source_backed_metadata_preference",
            title="Agent Reliability Reviewed Source Backing",
            content=(
                "## Reviewed Source Backing\n\n"
                "Reviewed source-backed memories should be retrievable when an agent "
                "requires evidence-backed context."
            ),
            query="reviewed source-backed evidence-backed context",
            tags=["agent-eval", "reliability", "source-backed", "reviewed"],
            max_chunks=2,
            budget_chars=1000,
            distractors=[
                {
                    "key": f"{EVAL_KEY_PREFIX}unreviewed_source_backed_distractor",
                    "title": "Agent Reliability Unreviewed Source Distractor",
                    "content": (
                        "## Unreviewed Source Backing\n\n"
                        "Reviewed source-backed memories should be retrievable when an agent "
                        "requires evidence-backed context."
                    ),
                    "tags": ["agent-eval", "reliability", "source-backed"],
                    "canonical": True,
                    "status": "draft",
                }
            ],
        ),
    ]


def run_agent_reliability_harness(
    memory_manager: Any,
    *,
    scenarios: Iterable[AgentReliabilityScenario] | None = None,
    cleanup: bool = True,
) -> dict[str, Any]:
    scenario_list = list(scenarios or default_agent_reliability_scenarios())
    reports: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []

    for scenario in scenario_list:
        reports.append(_run_scenario(memory_manager, scenario, cleanup=cleanup))

    passed = sum(1 for report in reports if report["status"] == "pass")
    failed = len(reports) - passed
    workflow_checks = [_run_workflow_primitive_check(), _run_book_dismantling_gate_check()]
    workflow_failed = sum(1 for check in workflow_checks if check["status"] != "pass")
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "status": "pass" if failed == 0 and workflow_failed == 0 else "fail",
            "scenario_count": len(reports),
            "passed": passed,
            "failed": failed,
            "workflow_check_count": len(workflow_checks),
            "workflow_failed": workflow_failed,
        },
        "scenarios": reports,
        "workflow_checks": workflow_checks,
        "warnings": warnings,
    }


def _run_scenario(
    memory_manager: Any,
    scenario: AgentReliabilityScenario,
    *,
    cleanup: bool,
) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    search_payload: dict[str, Any] = {"query": scenario.query, "count": 0, "results": []}
    chunks: list[dict[str, Any]] = []
    seeded_keys: list[str] = []

    try:
        for distractor in scenario.distractors:
            distractor_key = str(distractor["key"])
            memory_manager.store_memory(
                distractor_key,
                str(distractor["content"]),
                list(distractor.get("tags") or scenario.tags),
                str(distractor.get("title") or distractor_key),
                force=True,
                project=str(distractor.get("project") or scenario.project),
                domain=str(distractor.get("domain") or scenario.domain),
                status=distractor.get("status"),
                canonical=bool(distractor.get("canonical", False)),
            )
            seeded_keys.append(distractor_key)
            if distractor.get("potentially_stale"):
                memory_manager.mark_memory_potentially_stale(
                    distractor_key,
                    reason=str(distractor.get("stale_reason") or "agent reliability distractor"),
                )

        memory_manager.store_memory(
            scenario.key,
            scenario.content,
            scenario.tags,
            scenario.title,
            force=True,
            project=scenario.project,
            domain=scenario.domain,
            canonical=True,
        )
        seeded_keys.append(scenario.key)
        search_payload = memory_manager.search_memories_structured(
            scenario.query,
            limit=max(scenario.max_chunks, 1),
            project=scenario.project,
            domain=scenario.domain,
            tags=scenario.tags,
            include_stale=scenario.include_stale,
            canonical_only=scenario.canonical_only,
        )
        expected_rank = _expected_key_rank(search_payload.get("results", []), scenario.expected_key)
        chunk_requests = _chunk_requests(search_payload.get("results", []), scenario.max_chunks)
        retrieved_chunks = memory_manager.retrieve_chunks(chunk_requests)
        chunks = _select_budgeted_chunks(retrieved_chunks, scenario.budget_chars)

        if expected_rank is None:
            findings.append(
                {
                    "code": "expected_key_not_found",
                    "message": f"Expected memory {scenario.expected_key} was not returned by search.",
                }
            )
        if not chunks:
            findings.append(
                {
                    "code": "no_chunks_selected",
                    "message": "Search returned no retrievable chunks within the scenario budget.",
                }
            )

        used_chars = sum(len(chunk.get("text") or "") for chunk in chunks)
        omitted_count = max(len(retrieved_chunks) - len(chunks), 0)
        status = "pass" if not findings else "fail"
        return {
            "id": scenario.scenario_id,
            "description": scenario.description,
            "status": status,
            "expected_key": scenario.expected_key,
            "expected_key_found": expected_rank is not None,
            "expected_key_rank": expected_rank,
            "search": {
                "count": search_payload.get("count", 0),
                "top_keys": [result.get("key") for result in search_payload.get("results", [])],
            },
            "context_pack": {
                "selected_chunk_count": len(chunks),
                "used_chars": used_chars,
                "budget_chars": scenario.budget_chars,
                "omitted_count": omitted_count,
                "receipt": build_context_receipt(
                    query=scenario.query,
                    filters=make_filters(
                        project=scenario.project,
                        domain=scenario.domain,
                        tags=scenario.tags,
                        include_stale=scenario.include_stale,
                        canonical_only=scenario.canonical_only,
                    ),
                    semantic_candidate_count=search_payload.get("count", 0),
                    graph_candidate_count=0,
                    selected_chunk_count=len(chunks),
                    omitted_count=omitted_count,
                    budget_chars=scenario.budget_chars,
                    used_chars=used_chars,
                    include_stale=scenario.include_stale,
                    graph_enabled=False,
                    max_hops=0,
                ),
            },
            "token_estimates": {
                "search_response_tokens": estimate_tokens(search_payload),
                "context_response_tokens": estimate_tokens(chunks),
                "estimate_method": ESTIMATE_METHOD,
            },
            "findings": findings,
        }
    except Exception as exc:
        return {
            "id": scenario.scenario_id,
            "description": scenario.description,
            "status": "fail",
            "expected_key": scenario.expected_key,
            "expected_key_found": False,
            "expected_key_rank": None,
            "search": {
                "count": search_payload.get("count", 0),
                "top_keys": [result.get("key") for result in search_payload.get("results", [])],
            },
            "context_pack": {
                "selected_chunk_count": len(chunks),
                "used_chars": sum(len(chunk.get("text") or "") for chunk in chunks),
                "budget_chars": scenario.budget_chars,
                "omitted_count": 0,
                "receipt": {},
            },
            "token_estimates": {
                "search_response_tokens": estimate_tokens(search_payload),
                "context_response_tokens": estimate_tokens(chunks),
                "estimate_method": ESTIMATE_METHOD,
            },
            "findings": [
                {
                    "code": "scenario_runtime_error",
                    "message": str(exc),
                }
            ],
        }
    finally:
        if cleanup:
            for key in dict.fromkeys([*seeded_keys, scenario.key]):
                try:
                    memory_manager.delete_memory(key)
                except Exception as cleanup_exc:
                    LOGGER.warning(
                        "Failed to clean up agent reliability eval memory %s: %s",
                        key,
                        cleanup_exc,
                    )


def _expected_key_rank(results: list[dict[str, Any]], expected_key: str) -> int | None:
    for index, result in enumerate(results, start=1):
        if result.get("key") == expected_key:
            return index
    return None


def _chunk_requests(results: list[dict[str, Any]], max_chunks: int) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for result in results:
        key = result.get("key")
        chunk_id = result.get("chunk_id")
        if key is None or chunk_id is None:
            continue
        ref = (str(key), int(chunk_id))
        if ref in seen:
            continue
        seen.add(ref)
        requests.append({"key": ref[0], "chunk_id": ref[1]})
        if len(requests) >= max(max_chunks, 1):
            break
    return requests


def _select_budgeted_chunks(chunks: list[dict[str, Any]], budget_chars: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    used_chars = 0
    budget = max(int(budget_chars), 1)
    for chunk in chunks:
        if not chunk.get("found"):
            continue
        text = chunk.get("text") or ""
        if used_chars + len(text) > budget:
            continue
        selected.append(chunk)
        used_chars += len(text)
    return selected


def default_book_dismantling_fixture_manifests() -> list[dict[str, Any]]:
    """Return synthetic no-copyright manifests for the Book Dismantling Gate."""
    return [
        _book_fixture(
            "clean_text_pdf",
            title="Clean Text PDF",
            page_statuses=["text", "text", "text"],
            image_pages=[],
            expected_warnings=[],
            content="# Clean Text\n\nPlain text pages with stable section chunks.",
        ),
        _book_fixture(
            "book_style_pdf",
            title="Book Style PDF",
            page_statuses=["text", "text", "low_text", "text"],
            image_pages=[3],
            expected_warnings=["low_text_pages", "image_heavy_pages", "visual_review_needed"],
            content="# Chapter\n\nA chapter with heading structure.\n\n## Example\n\nA figure needs review.",
        ),
        _book_fixture(
            "image_only_pdf",
            title="Image Only PDF",
            page_statuses=["no_text", "no_text"],
            image_pages=[1, 2],
            expected_warnings=["no_text_pages", "visual_review_needed"],
            content="# Image Only\n\nOCR required before claims can be trusted.",
        ),
        _book_fixture(
            "table_heavy_page",
            title="Table Heavy Page",
            page_statuses=["text", "low_text"],
            image_pages=[2],
            expected_warnings=["low_text_pages", "image_heavy_pages", "visual_review_needed"],
            content="# Tables\n\nA dense comparison table needs structure extraction.",
        ),
        _book_fixture(
            "figure_caption_page",
            title="Figure Caption Page",
            page_statuses=["text", "low_text"],
            image_pages=[2],
            expected_warnings=["low_text_pages", "image_heavy_pages", "visual_review_needed"],
            content="# Figures\n\nA figure and caption need linked visual evidence.",
        ),
        _book_fixture(
            "rotated_page",
            title="Rotated Page",
            page_statuses=["text", "low_text"],
            image_pages=[2],
            expected_warnings=["low_text_pages", "visual_review_needed"],
            content="# Rotated Page\n\nRotation should be represented as review-needed evidence.",
        ),
        _book_fixture(
            "ocr_noise_page",
            title="OCR Noise Page",
            page_statuses=["text", "low_text", "text"],
            image_pages=[2],
            expected_warnings=["low_text_pages", "visual_review_needed"],
            content="# OCR Noise\n\nNoisy OCR text requires lower-confidence review.",
        ),
    ]


def run_book_dismantling_gate(fixtures: Iterable[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Validate synthetic or local-only book disassembly manifests without writes."""
    fixture_list = list(fixtures or default_book_dismantling_fixture_manifests())
    fixture_reports = [_evaluate_book_fixture(fixture) for fixture in fixture_list]
    present_ids = {report["fixture_id"] for report in fixture_reports}
    missing_required = [
        fixture_id for fixture_id in REQUIRED_BOOK_DISMANTLING_FIXTURE_IDS if fixture_id not in present_ids
    ]
    passed = sum(1 for report in fixture_reports if report["status"] == "pass")
    failed = len(fixture_reports) - passed
    status = "pass" if failed == 0 and not missing_required else "fail"
    return {
        "schema_version": BOOK_DISMANTLING_GATE_SCHEMA_VERSION,
        "summary": {
            "status": status,
            "fixture_count": len(fixture_reports),
            "passed": passed,
            "failed": failed,
            "required_fixture_count": len(REQUIRED_BOOK_DISMANTLING_FIXTURE_IDS),
            "missing_required_count": len(missing_required),
        },
        "required_fixture_ids": list(REQUIRED_BOOK_DISMANTLING_FIXTURE_IDS),
        "missing_required_fixture_ids": missing_required,
        "fixtures": fixture_reports,
        "write_performed": False,
        "active_memory_write_performed": False,
    }


def _run_book_dismantling_gate_check() -> dict[str, Any]:
    try:
        report = run_book_dismantling_gate()
        return {
            "id": "book_dismantling_gate",
            "description": "Verify synthetic book-scale document disassembly manifests satisfy the 1.0 gate.",
            "status": report["summary"]["status"],
            "summary": report["summary"],
            "required_fixture_ids": report["required_fixture_ids"],
            "findings": _book_gate_findings(report),
        }
    except Exception as exc:
        return {
            "id": "book_dismantling_gate",
            "description": "Verify synthetic book-scale document disassembly manifests satisfy the 1.0 gate.",
            "status": "fail",
            "summary": {},
            "required_fixture_ids": list(REQUIRED_BOOK_DISMANTLING_FIXTURE_IDS),
            "findings": [{"code": "book_gate_runtime_error", "message": str(exc)}],
        }


def _book_gate_findings(report: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for fixture_id in report.get("missing_required_fixture_ids", []):
        findings.append(
            {
                "code": "missing_required_fixture",
                "message": f"Required book dismantling fixture is missing: {fixture_id}",
            }
        )
    for fixture in report.get("fixtures", []):
        for finding in fixture.get("findings", []):
            findings.append(
                {
                    "code": finding["code"],
                    "message": f"{fixture['fixture_id']}: {finding['message']}",
                }
            )
    return findings


def _evaluate_book_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    fixture_id = str(fixture.get("fixture_id") or "")
    disassembly = dict(fixture.get("disassembly") or {})
    expected = dict(fixture.get("expected") or {})
    chunks = list(fixture.get("chunks") or [])
    draft = dict(fixture.get("document_draft") or {})
    findings: list[dict[str, str]] = []

    pages = list(disassembly.get("pages") or [])
    if not pages:
        findings.append({"code": "missing_page_inventory", "message": "Page inventory is empty."})
    coverage = dict((disassembly.get("quality_report") or {}).get("coverage") or {})
    min_text_ratio = float(expected.get("min_text_page_ratio", 0))
    if float(coverage.get("text_page_ratio", 0)) < min_text_ratio:
        findings.append(
            {
                "code": "text_coverage_below_gate",
                "message": f"Text page ratio is below {min_text_ratio}.",
            }
        )
    quality_seed = dict(disassembly.get("quality_seed") or {})
    visual_pages = list(quality_seed.get("visual_review_needed_pages") or [])
    expected_visual_pages = list(expected.get("visual_review_needed_pages") or [])
    if visual_pages != expected_visual_pages:
        findings.append(
            {
                "code": "visual_page_mismatch",
                "message": f"Expected visual pages {expected_visual_pages}, got {visual_pages}.",
            }
        )
    warning_codes = [
        warning.get("code")
        for warning in (disassembly.get("quality_report") or {}).get("warnings", [])
        if warning.get("code")
    ]
    missing_warnings = sorted(set(expected.get("warning_codes") or []) - set(warning_codes))
    if missing_warnings:
        findings.append(
            {
                "code": "quality_warning_missing",
                "message": f"Missing quality warnings: {', '.join(missing_warnings)}.",
            }
        )
    if not all(isinstance(chunk.get("provenance"), dict) and "document_id" in chunk["provenance"] for chunk in chunks):
        findings.append({"code": "chunk_provenance_missing", "message": "Chunk provenance is incomplete."})
    if expected_visual_pages:
        request = disassembly.get("visual_extraction_request") or {}
        if request.get("record_type") != "visual_extraction_request":
            findings.append({"code": "visual_request_missing", "message": "Visual extraction request is missing."})
    if draft.get("record_type") != "document_draft" or draft.get("active_memory_write_performed") is not False:
        findings.append({"code": "promotion_draft_missing", "message": "Reviewable document draft is missing."})

    return {
        "fixture_id": fixture_id,
        "status": "pass" if not findings else "fail",
        "checks": {
            "page_count": len(pages),
            "text_page_ratio": coverage.get("text_page_ratio"),
            "visual_review_needed_pages": visual_pages,
            "warning_codes": warning_codes,
            "chunk_count": len(chunks),
            "visual_request_capabilities": (
                disassembly.get("visual_extraction_request") or {}
            ).get("requested_capabilities", []),
        },
        "findings": findings,
    }


def _book_fixture(
    fixture_id: str,
    *,
    title: str,
    page_statuses: list[str],
    image_pages: list[int],
    expected_warnings: list[str],
    content: str,
) -> dict[str, Any]:
    preview = preview_document_extraction(
        title=title,
        source_uri=f"fixture://document_books/{fixture_id}.pdf",
        source_type="pdf",
        content=content,
        media_type="text/markdown",
        metadata={"project": DEFAULT_PROJECT, "domain": "document-intelligence", "fixture_id": fixture_id},
    )
    pages = [
        {
            "page_number": index + 1,
            "text_chars": 120 if status == "text" else (20 if status == "low_text" else 0),
            "non_whitespace_chars": 100 if status == "text" else (15 if status == "low_text" else 0),
            "text_status": status,
            "image_count": 1 if index + 1 in image_pages else 0,
            "visual_review_needed": status != "text" or index + 1 in image_pages,
        }
        for index, status in enumerate(page_statuses)
    ]
    visual_pages = [page["page_number"] for page in pages if page["visual_review_needed"]]
    text_pages = [page["page_number"] for page in pages if page["text_status"] == "text"]
    visual_artifacts = [
        prepare_visual_artifact_record(
            document_id=preview["document_record"]["document_id"],
            artifact_type="page_crop",
            source_ref={
                "source_uri": f"fixture://document_books/{fixture_id}.pdf",
                "source_artifact_id": f"document_artifacts/sources/{fixture_id}.pdf",
            },
            extractor_id="fixture",
            extractor_kind="agent_native",
            page_number=page,
            confidence=0.8,
            description=f"Synthetic page crop for {fixture_id} page {page}.",
        )
        for page in visual_pages
    ]
    draft = prepare_document_draft(
        document_record=preview["document_record"],
        analysis={
            "summary": f"Synthetic {title} fixture.",
            "claims": [f"{title} has deterministic document disassembly evidence."],
        },
        chunk_refs=[chunk["provenance"] for chunk in preview["chunks"]],
        visual_artifacts=visual_artifacts,
    )
    warnings = [{"code": code, "message": f"Synthetic fixture warning: {code}."} for code in expected_warnings]
    disassembly = {
        "record_type": "document_disassembly_preview",
        "write_performed": False,
        "active_memory_write_performed": False,
        "document": {
            "document_id": preview["document_record"]["document_id"],
            "title": title,
            "page_count": len(pages),
        },
        "pages": pages,
        "quality_seed": {
            "page_count": len(pages),
            "pages_reported": len(pages),
            "text_pages": text_pages,
            "low_text_pages": [page["page_number"] for page in pages if page["text_status"] == "low_text"],
            "no_text_pages": [page["page_number"] for page in pages if page["text_status"] == "no_text"],
            "image_pages": list(image_pages),
            "visual_review_needed_pages": visual_pages,
        },
        "quality_report": {
            "record_type": "document_quality_report",
            "status": "pass" if not expected_warnings else "warn",
            "coverage": {
                "text_page_ratio": round(len(text_pages) / len(pages), 3),
                "no_text_page_count": sum(1 for page in pages if page["text_status"] == "no_text"),
            },
            "warnings": warnings,
        },
        "artifact_manifest": {
            "record_type": "document_artifact_manifest",
            "resume": {
                "page_count": len(pages),
                "pages_recorded": len(pages),
                "states": {
                    str(page["page_number"]): (
                        "visual_needed" if page["visual_review_needed"] else "text_extracted"
                    )
                    for page in pages
                },
            },
        },
        "visual_extraction_request": (
            {
                "record_type": "visual_extraction_request",
                "image_refs": [{"page_number": page} for page in visual_pages],
                "requested_capabilities": [
                    "caption_alt_text",
                    "diagram_description",
                    "figure_description",
                    "ocr_text",
                    "table_structure",
                ],
            }
            if visual_pages
            else None
        ),
    }
    return {
        "fixture_id": fixture_id,
        "disassembly": disassembly,
        "chunks": preview["chunks"],
        "document_draft": draft,
        "expected": {
            "visual_review_needed_pages": visual_pages,
            "warning_codes": expected_warnings,
            "min_text_page_ratio": 0 if fixture_id == "image_only_pdf" else 0.25,
        },
    }


def _run_workflow_primitive_check() -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    try:
        profile = get_context_profile("repo_resume")
        query = build_context_query("resume Engram workflow reliability", profile, project=DEFAULT_PROJECT)
        context_payload = {
            "query": query,
            "count": 1,
            "chunks": [
                {
                    "key": "_engram_eval_workflow_context",
                    "chunk_id": 0,
                    "title": "Workflow Context",
                    "text": "Agents should compile context packets, handoffs, quality signals, and project capsules without writing memory.",
                    "citation": {"citation_id": "engram:_engram_eval_workflow_context#0"},
                }
            ],
            "citations": [{"citation_id": "engram:_engram_eval_workflow_context#0"}],
            "omitted": [],
            "budget_chars": 1000,
            "used_chars": 105,
            "receipt": build_context_receipt(
                query=query,
                filters=make_filters(project=DEFAULT_PROJECT, domain=DEFAULT_DOMAIN, tags=["agent-eval"]),
                semantic_candidate_count=1,
                graph_candidate_count=0,
                selected_chunk_count=1,
                omitted_count=0,
                budget_chars=1000,
                used_chars=105,
                include_stale=False,
                graph_enabled=False,
                max_hops=0,
            ),
            "error": None,
        }
        context_packet = compile_context_packet(
            task="resume Engram workflow reliability",
            profile_id=profile["id"],
            profile=profile,
            context_payload=context_payload,
            project=DEFAULT_PROJECT,
            domain=DEFAULT_DOMAIN,
            tags=["agent-eval"],
            query=query,
        )
        handoff = build_handoff_packet(
            task="resume Engram workflow reliability",
            project=DEFAULT_PROJECT,
            branch="agent-eval",
            status="workflow primitives under test",
            next_steps=["verify workflow packet schemas"],
            validation=["python server.py --agent-eval"],
            blockers=[],
            context_packet=context_packet,
        )
        quality = audit_memory_quality(
            [
                {
                    "key": "_engram_eval_workflow_context",
                    "title": "Workflow Context",
                    "project": DEFAULT_PROJECT,
                    "domain": DEFAULT_DOMAIN,
                    "tags": ["agent-eval"],
                    "status": "active",
                    "canonical": True,
                    "chars": 512,
                    "chunk_count": 1,
                }
            ],
            limit=0,
        )
        capsule = build_project_capsule_draft(
            project=DEFAULT_PROJECT,
            task="resume Engram workflow reliability",
            summary="Synthetic agent workflow reliability packet.",
            must_read_keys=["_engram_eval_workflow_context"],
            context_packet=context_packet,
            quality_payload=quality,
        )

        workflow_templates = list_workflow_templates()
        templates_by_id = {template["id"]: template for template in workflow_templates["templates"]}
        required_workflow_tools = {
            "compile_task_context": {"list_context_profiles", "prepare_context"},
            "prepare_session_handoff": {"prepare_context", "make_handoff"},
            "prepare_project_capsule_review": {"audit_memory_quality", "prepare_project_capsule"},
            "review_memory_health": {"audit_memory_quality", "conflict_scan", "retrieval_eval"},
        }
        for template_id, required_tools in required_workflow_tools.items():
            template = templates_by_id.get(template_id)
            if template is None:
                findings.append(
                    {
                        "code": "workflow_template_missing",
                        "message": f"Workflow template {template_id} is missing.",
                    }
                )
                continue
            missing_tools = sorted(required_tools - set(template.get("recommended_tools", [])))
            if missing_tools:
                findings.append(
                    {
                        "code": "workflow_template_tool_missing",
                        "message": f"Workflow template {template_id} is missing tools: {', '.join(missing_tools)}.",
                    }
                )
            template_text = " ".join([template.get("purpose", ""), *template.get("steps", [])]).lower()
            if "no-write" not in template_text and "explicit" not in template_text:
                findings.append(
                    {
                        "code": "workflow_template_review_boundary_missing",
                        "message": f"Workflow template {template_id} does not state a no-write or explicit-review boundary.",
                    }
                )

        artifacts = {
            "context_packet": context_packet["schema_version"],
            "handoff_packet": handoff["schema_version"],
            "project_capsule": capsule["schema_version"],
            "memory_quality": quality["schema_version"],
            "workflow_templates": {
                "schema_version": workflow_templates["schema_version"],
                "template_ids": list(required_workflow_tools),
            },
        }
        for name, artifact in [
            ("context_packet", context_packet),
            ("handoff_packet", handoff),
            ("project_capsule", capsule),
            ("memory_quality", quality),
        ]:
            if artifact.get("write_performed") is not False:
                findings.append(
                    {
                        "code": "workflow_write_boundary_failed",
                        "message": f"{name} did not report write_performed=false.",
                    }
                )

        return {
            "id": "agent_workflow_packets",
            "description": "Verify no-write workflow packet builders produce stable schema identities.",
            "status": "pass" if not findings else "fail",
            "artifacts": artifacts,
            "findings": findings,
        }
    except Exception as exc:
        return {
            "id": "agent_workflow_packets",
            "description": "Verify no-write workflow packet builders produce stable schema identities.",
            "status": "fail",
            "artifacts": {},
            "findings": [{"code": "workflow_runtime_error", "message": str(exc)}],
        }
