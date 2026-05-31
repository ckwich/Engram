"""Shared constants for provider-neutral document intelligence primitives."""
from __future__ import annotations

DOCUMENT_INTELLIGENCE_SCHEMA_VERSION = "2026-05-11.document-intelligence.v1"
DOCUMENT_EXTRACTOR_CATALOG_SCHEMA_VERSION = "2026-05-11.document-intelligence.extractors.v1"
DOCUMENT_PREVIEW_SCHEMA_VERSION = "2026-05-11.document-intelligence.preview.v1"
VISUAL_PREVIEW_SCHEMA_VERSION = "2026-05-11.document-intelligence.visual-preview.v1"
VISUAL_REQUEST_SCHEMA_VERSION = "2026-05-11.document-intelligence.visual-request.v1"
DOCUMENT_EXTRACTION_REQUEST_SCHEMA_VERSION = "2026-05-11.document-intelligence.extraction-request.v1"
DOCUMENT_EXTRACTION_RESULT_SCHEMA_VERSION = "2026-05-11.document-intelligence.extraction-result.v1"
DOCUMENT_DRAFT_SCHEMA_VERSION = "2026-05-11.document-intelligence.draft.v1"
DOCUMENT_UNDERSTANDING_SCHEMA_VERSION = "2026-05-12.document-intelligence.understanding.v1"
DOCUMENT_PROMOTION_SCHEMA_VERSION = "2026-05-11.document-intelligence.promotion.v1"
LOW_CONFIDENCE_THRESHOLD = 0.5
AUTO_GRAPH_SOURCE = "document_intelligence.auto_graph"
VALID_EXTRACTOR_KINDS = {"agent_native", "ocr", "vision", "ocr_vision"}
VALID_DOCUMENT_EXTRACTOR_KINDS = {
    "agent_native",
    "docx",
    "external_document",
    "html",
    "ocr",
    "ocr_document",
    "ocr_vision",
    "pdf",
    "vision",
}
VALID_DOCUMENT_OUTPUTS = {
    "figures",
    "html",
    "markdown",
    "metadata",
    "page_images",
    "plain_text",
    "tables",
    "visual_artifacts",
}
VISUAL_DOCUMENT_OUTPUTS = {"figures", "page_images", "tables", "visual_artifacts"}
VISUAL_SOURCE_TYPES = {"image", "image_folder", "pdf", "scan", "screenshot"}
DOCUMENT_ANALYSIS_SECTIONS = {
    "summary": "Summary",
    "decisions": "Decisions",
    "claims": "Claims",
    "entities": "Entities",
    "constraints": "Constraints",
    "tasks": "Tasks",
    "risks": "Risks",
    "dates": "Dates",
    "open_questions": "Open Questions",
    "external_pointers": "External Pointers",
}
DOCUMENT_UNDERSTANDING_ANALYSIS_FIELDS = {
    "summary",
    "claims",
    "concepts",
    "entities",
    "high_value_sections",
    "warnings",
}
VALID_VISUAL_CAPABILITIES = {
    "caption_alt_text",
    "chart_summary",
    "diagram_description",
    "figure_description",
    "ocr_text",
    "screenshot_state",
    "table_structure",
}
PROMOTION_GUIDANCE = {
    "default_action": "review_before_promotion",
    "auto_promote": False,
    "allowed_destinations": ["memory", "graph_edge", "document_store", "external_pointer"],
}
EXPECTED_VISUAL_OBSERVATION_FIELDS = [
    "artifact_type",
    "source_ref",
    "source_artifact_id",
    "text",
    "description",
    "page_number",
    "bounding_box",
    "coordinates",
    "confidence",
    "metadata",
]
EXPECTED_DOCUMENT_EXTRACTION_FIELDS = [
    "title",
    "source_uri",
    "source_type",
    "content",
    "media_type",
    "content_hash",
    "metadata",
    "image_refs",
]
