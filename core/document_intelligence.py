"""Compatibility facade for no-write document intelligence primitives.

Implementation is split by concept so callers can keep importing from
``core.document_intelligence`` while reviewers work in focused modules.
"""
from __future__ import annotations

from core.document_extraction_intelligence import (
    list_document_extractors,
    prepare_document_extraction_request,
    prepare_document_extraction_result,
    prepare_document_record,
    preview_document_extraction,
)
from core.document_intelligence_contracts import (
    AUTO_GRAPH_SOURCE,
    DOCUMENT_ANALYSIS_SECTIONS,
    DOCUMENT_DRAFT_SCHEMA_VERSION,
    DOCUMENT_EXTRACTION_REQUEST_SCHEMA_VERSION,
    DOCUMENT_EXTRACTION_RESULT_SCHEMA_VERSION,
    DOCUMENT_EXTRACTOR_CATALOG_SCHEMA_VERSION,
    DOCUMENT_INTELLIGENCE_SCHEMA_VERSION,
    DOCUMENT_PREVIEW_SCHEMA_VERSION,
    DOCUMENT_PROMOTION_SCHEMA_VERSION,
    DOCUMENT_UNDERSTANDING_ANALYSIS_FIELDS,
    DOCUMENT_UNDERSTANDING_SCHEMA_VERSION,
    EXPECTED_DOCUMENT_EXTRACTION_FIELDS,
    EXPECTED_VISUAL_OBSERVATION_FIELDS,
    LOW_CONFIDENCE_THRESHOLD,
    PROMOTION_GUIDANCE,
    VALID_DOCUMENT_EXTRACTOR_KINDS,
    VALID_DOCUMENT_OUTPUTS,
    VALID_EXTRACTOR_KINDS,
    VALID_VISUAL_CAPABILITIES,
    VISUAL_DOCUMENT_OUTPUTS,
    VISUAL_PREVIEW_SCHEMA_VERSION,
    VISUAL_REQUEST_SCHEMA_VERSION,
    VISUAL_SOURCE_TYPES,
)
from core.document_promotion_intelligence import prepare_document_promotion_transaction
from core.document_understanding_intelligence import (
    prepare_document_draft,
    prepare_document_understanding_packet,
)
from core.document_visual_intelligence import (
    prepare_extractor_receipt,
    prepare_visual_artifact_record,
    prepare_visual_extraction_request,
    preview_visual_extraction,
)
