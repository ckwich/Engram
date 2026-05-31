"""Document catalog metadata helpers for Memory OS book corpora."""
from __future__ import annotations

from typing import Any


DOCUMENT_CATALOG_SCHEMA_VERSION = "2026-05-17.document-catalog.v1"

_CORE_GAME_DESIGN_MARKERS = (
    "advanced game design",
    "art of game design",
    "designing games",
    "game design",
    "game_design",
)
_YOUTUBE_TRANSCRIPT_MARKERS = ("youtube", "youtu be", "transcript")
_GMTK_LEVEL_DESIGN_MARKERS = (
    "game maker s toolkit",
    "gmtk",
    "level design",
    "boss keys",
    "plc38fcmfcv",
)
_EVIL_BY_DESIGN_MARKERS = ("evil by design", "evil_by_design")
_UX_MARKERS = (
    "ux for beginners",
    "joel marsh",
    "user experience",
    "ux design",
    "ui design",
    "interface design",
    "interaction design",
    "usability",
    "persuasive design",
    "behavioral design",
    "behavioural design",
    "dark pattern",
    "dark_pattern",
)
_PRODUCT_INTERACTION_DESIGN_MARKERS = (
    "design of everyday things",
    "everyday things",
    "don norman",
    "human centered design",
    "human centred design",
    "product design",
    "designing products",
    "designing products people love",
)
_STALE_UNCATALOGUED_TAGS = {"uncatalogued-book", "uncatalogued-document"}


def build_document_catalog(record: dict[str, Any]) -> dict[str, Any]:
    """Infer deterministic catalog facets for a document record."""
    signal = _classification_signal(record)
    content_form = _content_form(record, signal)
    if any(marker in signal for marker in _EVIL_BY_DESIGN_MARKERS):
        return _catalog(
            content_form=content_form,
            primary_subject="ux_design",
            secondary_subjects=[
                "behavioral_design",
                "persuasive_design",
                "dark_patterns",
                "gamification",
            ],
            collections=["ux_design_books", "behavioral_design_books", "game_design_adjacent_books"],
            reading_role="adjacent",
            adjacent_to_game_design=True,
            exclude_from_core_game_design_corpus=True,
            corpus_tags=[
                "book",
                "ux-design",
                "behavioral-design",
                "persuasive-design",
                "game-design-adjacent",
            ],
            confidence=0.96,
        )
    if _is_youtube_game_design_transcript(signal, content_form):
        return _catalog(
            content_form=content_form,
            primary_subject="game_design",
            secondary_subjects=["level_design", "game_development"],
            collections=[
                "game_design_transcripts",
                "youtube_transcripts",
                "gmtk_level_design_playlist",
            ],
            reading_role="core",
            adjacent_to_game_design=False,
            exclude_from_core_game_design_corpus=False,
            corpus_tags=[
                "transcript",
                "youtube-transcript",
                "game-design",
                "level-design",
                "gmtk",
                "core-game-design",
            ],
            confidence=0.9,
        )
    if any(marker in signal for marker in _CORE_GAME_DESIGN_MARKERS):
        return _catalog(
            content_form=content_form,
            primary_subject="game_design",
            secondary_subjects=["game_development", "game_mechanics"],
            collections=["game_design_books"],
            reading_role="core",
            adjacent_to_game_design=False,
            exclude_from_core_game_design_corpus=False,
            corpus_tags=["book", "game-design", "core-game-design"],
            confidence=0.9,
        )
    if any(marker in signal for marker in _UX_MARKERS):
        return _catalog(
            content_form=content_form,
            primary_subject="ux_design",
            secondary_subjects=["interface_design"],
            collections=["ux_design_books"],
            reading_role="reference",
            adjacent_to_game_design=False,
            exclude_from_core_game_design_corpus=True,
            corpus_tags=["book", "ux-design"],
            confidence=0.72,
        )
    if any(marker in signal for marker in _PRODUCT_INTERACTION_DESIGN_MARKERS):
        return _catalog(
            content_form=content_form,
            primary_subject="product_design",
            secondary_subjects=["interaction_design", "human_centered_design", "ux_design"],
            collections=[
                "product_design_books",
                "ux_design_books",
                "design_theory_books",
            ],
            reading_role="reference",
            adjacent_to_game_design=False,
            exclude_from_core_game_design_corpus=True,
            corpus_tags=["book", "product-design", "interaction-design", "ux-design"],
            confidence=0.82,
        )
    if content_form == "book":
        return _catalog(
            content_form=content_form,
            primary_subject="uncatalogued",
            secondary_subjects=[],
            collections=["uncatalogued_books"],
            reading_role="reference",
            adjacent_to_game_design=False,
            exclude_from_core_game_design_corpus=True,
            corpus_tags=["book", "uncatalogued-book"],
            confidence=0.2,
        )
    return _catalog(
        content_form=content_form,
        primary_subject="uncatalogued",
        secondary_subjects=[],
        collections=[],
        reading_role="reference",
        adjacent_to_game_design=False,
        exclude_from_core_game_design_corpus=True,
        corpus_tags=["uncatalogued-document"],
        confidence=0.0,
    )


def enrich_document_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return a document record with normalized catalog metadata."""
    enriched = dict(record)
    existing = enriched.get("document_catalog") if isinstance(enriched.get("document_catalog"), dict) else {}
    inferred = build_document_catalog(enriched)
    catalog = _merge_existing_catalog(inferred, existing)
    enriched["document_catalog"] = catalog
    enriched["document_content_form"] = catalog["content_form"]
    enriched["document_primary_subject"] = catalog["primary_subject"]
    enriched["document_secondary_subjects"] = list(catalog["secondary_subjects"])
    enriched["document_collections"] = list(catalog["collections"])
    enriched["document_reading_role"] = catalog["reading_role"]
    enriched["document_corpus_tags"] = list(catalog["corpus_tags"])
    enriched["adjacent_to_game_design"] = bool(catalog["adjacent_to_game_design"])
    enriched["exclude_from_core_game_design_corpus"] = bool(
        catalog["exclude_from_core_game_design_corpus"]
    )
    return enriched


def merge_catalog_into_chunk_metadata(metadata: dict[str, Any], document: dict[str, Any]) -> None:
    """Add document catalog facets to retrieval chunk metadata in-place."""
    enriched = enrich_document_record(document) if document else {}
    catalog = enriched.get("document_catalog") if isinstance(enriched.get("document_catalog"), dict) else {}
    if not catalog:
        return
    metadata["document_catalog"] = dict(catalog)
    metadata["document_content_form"] = catalog["content_form"]
    metadata["document_primary_subject"] = catalog["primary_subject"]
    metadata["document_secondary_subjects"] = list(catalog["secondary_subjects"])
    metadata["document_collections"] = list(catalog["collections"])
    metadata["document_reading_role"] = catalog["reading_role"]
    metadata["document_corpus_tags"] = list(catalog["corpus_tags"])
    metadata["adjacent_to_game_design"] = bool(catalog["adjacent_to_game_design"])
    metadata["exclude_from_core_game_design_corpus"] = bool(
        catalog["exclude_from_core_game_design_corpus"]
    )
    metadata["tags"] = _merge_lists(metadata.get("tags") or [], catalog["corpus_tags"])


def enrich_document_identity_metadata(
    record: dict[str, Any],
    *,
    project: str | None = None,
    domain: str | None = None,
    prefer_catalog_domain: bool = False,
) -> dict[str, Any]:
    """Return a document record with project/domain/tags aligned to catalog facets."""
    enriched = enrich_document_record(record)
    metadata = dict(enriched.get("metadata") or {})
    catalog = enriched.get("document_catalog") if isinstance(enriched.get("document_catalog"), dict) else {}
    project_value = (
        _optional_text(project)
        or _optional_text(enriched.get("project"))
        or _optional_text(metadata.get("project"))
    )
    catalog_domain = _catalog_domain(catalog)
    domain_value = (
        catalog_domain
        if prefer_catalog_domain and catalog_domain
        else (
            _optional_text(domain)
            or _optional_text(enriched.get("domain"))
            or _optional_text(metadata.get("domain"))
            or catalog_domain
        )
    )
    tags = _merge_lists(
        ["document-ingestion"],
        catalog.get("corpus_tags") or [],
        _drop_stale_uncatalogued_tags(enriched.get("tags") or [], catalog),
        _drop_stale_uncatalogued_tags(metadata.get("tags") or [], catalog),
    )
    if project_value is not None:
        enriched["project"] = project_value
        metadata["project"] = project_value
    if domain_value is not None:
        enriched["domain"] = domain_value
        metadata["domain"] = domain_value
    enriched["tags"] = tags
    metadata["tags"] = list(tags)
    metadata["document_id"] = enriched.get("document_id") or metadata.get("document_id")
    if catalog:
        metadata["document_catalog"] = dict(catalog)
    enriched["metadata"] = metadata
    return enriched


def enrich_document_chunk_metadata(
    chunk: dict[str, Any],
    document: dict[str, Any],
    *,
    project: str | None = None,
    domain: str | None = None,
    prefer_catalog_domain: bool = False,
) -> dict[str, Any]:
    """Return a chunk record with top-level project/domain/catalog metadata."""
    enriched_document = enrich_document_identity_metadata(
        document,
        project=project,
        domain=domain,
        prefer_catalog_domain=prefer_catalog_domain,
    )
    enriched = dict(chunk)
    title = enriched_document.get("title")
    if title:
        enriched.setdefault("title", title)
    if enriched_document.get("project") is not None:
        enriched["project"] = enriched_document["project"]
    if enriched_document.get("domain") is not None:
        enriched["domain"] = enriched_document["domain"]
    enriched["status"] = str(enriched.get("status") or "active")
    enriched["source"] = str(enriched.get("source") or "document_ingestion")
    enriched["tags"] = ["document-ingestion"]
    merge_catalog_into_chunk_metadata(enriched, enriched_document)
    return enriched


def _catalog(
    *,
    content_form: str,
    primary_subject: str,
    secondary_subjects: list[str],
    collections: list[str],
    reading_role: str,
    adjacent_to_game_design: bool,
    exclude_from_core_game_design_corpus: bool,
    corpus_tags: list[str],
    confidence: float,
) -> dict[str, Any]:
    return {
        "schema_version": DOCUMENT_CATALOG_SCHEMA_VERSION,
        "content_form": content_form,
        "primary_subject": primary_subject,
        "secondary_subjects": list(secondary_subjects),
        "collections": list(collections),
        "reading_role": reading_role,
        "adjacent_to_game_design": bool(adjacent_to_game_design),
        "exclude_from_core_game_design_corpus": bool(exclude_from_core_game_design_corpus),
        "corpus_tags": list(corpus_tags),
        "classification_basis": "title_path_rules",
        "classification_confidence": confidence,
    }


def _merge_existing_catalog(inferred: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    if not existing:
        return inferred
    if str(existing.get("classification_basis") or "") in {"agent_review", "manual_review"}:
        merged = {**inferred, **existing}
        for field in ("secondary_subjects", "collections", "corpus_tags"):
            merged[field] = _string_list(existing.get(field)) or _string_list(inferred.get(field))
        return merged
    if existing.get("primary_subject") == "uncatalogued" and inferred.get("primary_subject") != "uncatalogued":
        return inferred
    else:
        merged = {**existing, **inferred}
    merged["secondary_subjects"] = _merge_lists(
        inferred.get("secondary_subjects") or [],
        existing.get("secondary_subjects") or [],
    )
    merged["collections"] = _merge_lists(
        inferred.get("collections") or [],
        existing.get("collections") or [],
    )
    merged["corpus_tags"] = _merge_lists(
        inferred.get("corpus_tags") or [],
        existing.get("corpus_tags") or [],
    )
    return merged


def _classification_signal(record: dict[str, Any]) -> str:
    document = record.get("document") if isinstance(record.get("document"), dict) else {}
    source_ref = record.get("source_ref") if isinstance(record.get("source_ref"), dict) else {}
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    parts = [
        record.get("document_id"),
        record.get("title"),
        record.get("project"),
        record.get("domain"),
        document.get("title"),
        document.get("source_type"),
        source_ref.get("path"),
        source_ref.get("source_path"),
        source_ref.get("source_uri"),
        source_ref.get("media_type"),
        metadata.get("project"),
        metadata.get("domain"),
        metadata.get("source_path"),
        metadata.get("source_uri"),
        " ".join(_string_list(record.get("tags"))),
        " ".join(_string_list(metadata.get("tags"))),
    ]
    signal = " ".join(str(part) for part in parts if part)
    return _normalize_signal(signal)


def _content_form(record: dict[str, Any], signal: str) -> str:
    document = record.get("document") if isinstance(record.get("document"), dict) else {}
    source_ref = record.get("source_ref") if isinstance(record.get("source_ref"), dict) else {}
    source_type = str(document.get("source_type") or source_ref.get("source_type") or "").lower()
    media_type = str(document.get("media_type") or source_ref.get("media_type") or "").lower()
    if (
        "transcript" in signal
        or (
            ("youtube" in signal or "youtu be" in signal)
            and (
                source_type in {"md", "markdown", "txt", "text"}
                or media_type in {"text/markdown", "text/plain"}
            )
        )
    ):
        return "transcript"
    if "book" in signal or "pdf" in source_type or "application/pdf" in media_type or signal.endswith(" pdf"):
        return "book"
    return "document"


def _is_youtube_game_design_transcript(signal: str, content_form: str) -> bool:
    if content_form != "transcript":
        return False
    if not any(marker in signal for marker in _YOUTUBE_TRANSCRIPT_MARKERS):
        return False
    return any(marker in signal for marker in (*_CORE_GAME_DESIGN_MARKERS, *_GMTK_LEVEL_DESIGN_MARKERS))


def _normalize_signal(value: str) -> str:
    normalized = str(value).lower().replace("%20", " ")
    for char in "\\/_-.:":
        normalized = normalized.replace(char, " ")
    while "  " in normalized:
        normalized = normalized.replace("  ", " ")
    return normalized.strip()


def _merge_lists(*values: Any) -> list[str]:
    merged: list[str] = []
    for value in [item for value in values for item in _string_list(value)]:
        text = str(value or "").strip()
        if text and text not in merged:
            merged.append(text)
    return merged


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _catalog_domain(catalog: dict[str, Any]) -> str | None:
    if not catalog:
        return None
    primary = str(catalog.get("primary_subject") or "").strip()
    if primary and primary != "uncatalogued":
        return primary
    return None


def _drop_stale_uncatalogued_tags(value: Any, catalog: dict[str, Any]) -> list[str]:
    tags = _string_list(value)
    if str(catalog.get("primary_subject") or "") == "uncatalogued":
        return tags
    return [tag for tag in tags if tag not in _STALE_UNCATALOGUED_TAGS]


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
