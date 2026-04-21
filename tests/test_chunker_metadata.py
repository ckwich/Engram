from __future__ import annotations

from core.chunker import chunk_content, chunk_content_with_metadata


def test_chunk_content_with_metadata_tracks_headings_and_chunk_kinds():
    content = (
        "# Alpha\n"
        "Alpha paragraph one stays together.\n\n"
        "## Beta\n"
        "Beta paragraph one is long enough to stand alone.\n\n"
        "Beta paragraph two is also long enough to stand alone.\n\n"
        "### Gamma\n"
        "Gamma closing note."
    )

    chunks = chunk_content_with_metadata(content, max_size=70)

    assert [chunk["chunk_id"] for chunk in chunks] == list(range(len(chunks)))
    assert chunks[0]["text"].startswith("# Alpha")
    assert chunks[0]["section_title"] == "Alpha"
    assert chunks[0]["heading_path"] == ["Alpha"]
    assert chunks[0]["chunk_kind"] == "section"

    beta_chunks = [chunk for chunk in chunks if chunk["section_title"] == "Beta"]
    assert len(beta_chunks) == 2
    assert all(chunk["heading_path"] == ["Alpha", "Beta"] for chunk in beta_chunks)
    assert all(chunk["chunk_kind"] == "paragraph" for chunk in beta_chunks)

    gamma_chunk = chunks[-1]
    assert gamma_chunk["section_title"] == "Gamma"
    assert gamma_chunk["heading_path"] == ["Alpha", "Beta", "Gamma"]
    assert gamma_chunk["chunk_kind"] == "section"


def test_chunk_content_preserves_legacy_shape_and_order():
    content = (
        "# Alpha\n"
        "Alpha paragraph one stays together. Alpha paragraph two stays together.\n\n"
        "## Beta\n"
        "Beta paragraph one is long enough to stand alone.\n\n"
        "Beta paragraph two is also long enough to stand alone.\n\n"
        "### Gamma\n"
        "Gamma closing note."
    )

    metadata_chunks = chunk_content_with_metadata(content, max_size=70)
    legacy_chunks = chunk_content(content, max_size=70)

    assert legacy_chunks == [
        {"chunk_id": chunk["chunk_id"], "text": chunk["text"]}
        for chunk in metadata_chunks
    ]
    assert all(set(chunk) == {"chunk_id", "text"} for chunk in legacy_chunks)
