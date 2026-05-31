from __future__ import annotations

from core.memory_os.document_catalog import (
    build_document_catalog,
    enrich_document_identity_metadata,
    enrich_document_record,
    merge_catalog_into_chunk_metadata,
)


def test_document_catalog_classifies_core_game_design_books() -> None:
    catalog = build_document_catalog(
        {
            "document_id": "doc_advanced_game_design",
            "title": "Advanced Game Design",
            "source_ref": {"path": "/books/Advanced Game Design.pdf", "source_type": "pdf"},
        }
    )

    assert catalog["primary_subject"] == "game_design"
    assert catalog["reading_role"] == "core"
    assert catalog["collections"] == ["game_design_books"]
    assert catalog["exclude_from_core_game_design_corpus"] is False
    assert "core-game-design" in catalog["corpus_tags"]


def test_document_catalog_classifies_youtube_game_design_transcripts() -> None:
    catalog = build_document_catalog(
        {
            "document_id": "doc_001_making_hitman_3_s_best_level_lfj_vgxx9ag",
            "title": "001 - Making Hitman 3's Best Level [lfJ-vGXX9ag]",
            "project": "Design Skills",
            "domain": "game_design",
            "source_ref": {
                "path": "/Design Skills/sources/youtube/PLc38fcMFcV_t6cVUpPXYnooVe1r_C0_4f/normalized/001 - Making Hitman 3's Best Level [lfJ-vGXX9ag].md",
                "source_type": "markdown",
                "media_type": "text/markdown",
            },
        }
    )

    assert catalog["content_form"] == "transcript"
    assert catalog["primary_subject"] == "game_design"
    assert catalog["reading_role"] == "core"
    assert catalog["collections"] == [
        "game_design_transcripts",
        "youtube_transcripts",
        "gmtk_level_design_playlist",
    ]
    assert catalog["exclude_from_core_game_design_corpus"] is False
    assert "youtube-transcript" in catalog["corpus_tags"]
    assert "level-design" in catalog["corpus_tags"]


def test_document_catalog_classifies_adjacent_ux_books_without_core_game_tag() -> None:
    catalog = build_document_catalog(
        {
            "document_id": "doc_evil_by_design",
            "title": "Evil by Design",
            "source_ref": {"path": "/books/Evil By Design.pdf", "source_type": "pdf"},
        }
    )

    assert catalog["primary_subject"] == "ux_design"
    assert catalog["reading_role"] == "adjacent"
    assert catalog["adjacent_to_game_design"] is True
    assert catalog["exclude_from_core_game_design_corpus"] is True
    assert "game-design-adjacent" in catalog["corpus_tags"]
    assert "core-game-design" not in catalog["corpus_tags"]


def test_document_catalog_classifies_interaction_design_books_as_ux_reference() -> None:
    catalog = build_document_catalog(
        {
            "document_id": "doc_designing_interfaces",
            "title": "Designing Interfaces Patterns for Effective Interaction Design",
            "source_ref": {"path": "/books/Designing Interfaces.pdf", "source_type": "pdf"},
        }
    )

    assert catalog["primary_subject"] == "ux_design"
    assert catalog["reading_role"] == "reference"
    assert catalog["collections"] == ["ux_design_books"]
    assert catalog["exclude_from_core_game_design_corpus"] is True
    assert "ux-design" in catalog["corpus_tags"]
    assert "product-design" not in catalog["corpus_tags"]


def test_document_catalog_classifies_ux_for_beginners_as_ux_reference() -> None:
    catalog = build_document_catalog(
        {
            "document_id": "doc_ux_for_beginners",
            "title": "UX for Beginners",
            "source_ref": {"path": "/books/ux-for-beginners.pdf", "source_type": "pdf"},
        }
    )

    assert catalog["primary_subject"] == "ux_design"
    assert catalog["reading_role"] == "reference"
    assert catalog["collections"] == ["ux_design_books"]
    assert catalog["exclude_from_core_game_design_corpus"] is True
    assert "ux-design" in catalog["corpus_tags"]
    assert "uncatalogued-book" not in catalog["corpus_tags"]


def test_document_catalog_classifies_product_interaction_design_books() -> None:
    catalog = build_document_catalog(
        {
            "document_id": "doc_the_design_of_everyday_things",
            "title": "The Design of Everyday Things",
            "source_ref": {"path": "/books/Everyday things.pdf", "source_type": "pdf"},
        }
    )

    assert catalog["primary_subject"] == "product_design"
    assert catalog["reading_role"] == "reference"
    assert catalog["collections"] == [
        "product_design_books",
        "ux_design_books",
        "design_theory_books",
    ]
    assert catalog["exclude_from_core_game_design_corpus"] is True
    assert "product-design" in catalog["corpus_tags"]
    assert "interaction-design" in catalog["corpus_tags"]
    assert "core-game-design" not in catalog["corpus_tags"]


def test_enrich_document_record_and_chunk_metadata_surface_catalog_facets() -> None:
    document = enrich_document_record(
        {
            "document_id": "doc_the_art_of_game_design_schell_jesse",
            "title": "The Art of Game Design",
            "source_ref": {"path": "/books/The Art of Game Design Schell Jesse.pdf", "source_type": "pdf"},
        }
    )
    metadata: dict[str, object] = {"tags": ["document-ingestion"]}

    merge_catalog_into_chunk_metadata(metadata, document)

    assert document["document_catalog"]["primary_subject"] == "game_design"
    assert metadata["document_primary_subject"] == "game_design"
    assert metadata["document_reading_role"] == "core"
    assert metadata["document_collections"] == ["game_design_books"]
    assert metadata["document_catalog"]["primary_subject"] == "game_design"
    assert metadata["tags"] == ["document-ingestion", "book", "game-design", "core-game-design"]


def test_agent_review_catalog_overrides_title_path_inference() -> None:
    document = enrich_document_record(
        {
            "document_id": "doc_design_book",
            "title": "Design Book",
            "source_ref": {"path": "/books/design-book.pdf", "source_type": "pdf"},
            "document_catalog": {
                "primary_subject": "game_design",
                "secondary_subjects": ["systems_design"],
                "collections": ["game_design_books"],
                "reading_role": "core",
                "adjacent_to_game_design": False,
                "exclude_from_core_game_design_corpus": False,
                "corpus_tags": ["book", "game-design", "core-game-design"],
                "classification_basis": "agent_review",
                "classification_confidence": 1.0,
            },
        }
    )

    assert document["document_catalog"]["primary_subject"] == "game_design"
    assert document["document_catalog"]["collections"] == ["game_design_books"]
    assert document["document_catalog"]["classification_basis"] == "agent_review"


def test_stronger_title_path_inference_replaces_uncatalogued_catalog() -> None:
    document = enrich_document_record(
        {
            "document_id": "doc_ux_for_beginners",
            "title": "UX for Beginners",
            "source_ref": {"path": "/books/ux-for-beginners.pdf", "source_type": "pdf"},
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
        }
    )

    assert document["document_catalog"]["primary_subject"] == "ux_design"
    assert document["document_catalog"]["collections"] == ["ux_design_books"]
    assert document["document_catalog"]["corpus_tags"] == ["book", "ux-design"]


def test_enrich_identity_metadata_drops_stale_uncatalogued_tags() -> None:
    document = enrich_document_identity_metadata(
        {
            "document_id": "doc_level_transcript",
            "title": "GMTK Level Design Transcript",
            "project": "Design Skills",
            "domain": "game_design",
            "source_ref": {
                "path": "/Design Skills/sources/youtube/video.md",
                "source_type": "markdown",
                "media_type": "text/markdown",
            },
            "tags": ["document-ingestion", "uncatalogued-document"],
            "metadata": {"tags": ["uncatalogued-document"]},
            "document_catalog": {
                "primary_subject": "uncatalogued",
                "secondary_subjects": [],
                "collections": [],
                "reading_role": "reference",
                "adjacent_to_game_design": False,
                "exclude_from_core_game_design_corpus": True,
                "corpus_tags": ["uncatalogued-document"],
                "classification_basis": "title_path_rules",
                "classification_confidence": 0.0,
            },
        }
    )

    assert document["document_catalog"]["primary_subject"] == "game_design"
    assert "youtube-transcript" in document["tags"]
    assert "uncatalogued-document" not in document["tags"]
    assert "uncatalogued-document" not in document["metadata"]["tags"]
