from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from core.document_artifacts import artifact_path_from_ref, build_document_artifact_manifest


def _disassembly() -> dict:
    source_hash = "sha256:" + "a" * 64
    return {
        "source": {
            "source_uri": "file:///sample.pdf",
            "path": "C:/docs/sample.pdf",
            "source_type": "pdf",
            "media_type": "application/pdf",
            "content_hash": source_hash,
            "size_bytes": 1234,
        },
        "document": {
            "document_id": "doc_alpha",
            "title": "Sample",
            "page_count": 3,
            "content_hash": source_hash,
        },
        "pages": [
            {"page_number": 1, "text_status": "text", "image_count": 0, "visual_review_needed": False},
            {"page_number": 2, "text_status": "no_text", "image_count": 1, "visual_review_needed": True},
            {"page_number": 3, "text_status": "low_text", "image_count": 1, "visual_review_needed": True},
        ],
        "text": {"content": "Page one text\f\fCaption only", "page_count": 3},
        "image_inventory": {"pages_with_images": [2, 3], "image_count": 2},
        "quality_seed": {"failed_pages": [3]},
        "error": None,
    }


def test_build_document_artifact_manifest_uses_content_addresses_and_resume_states(tmp_path):
    manifest = build_document_artifact_manifest(_disassembly(), data_root=tmp_path / "data")

    assert manifest["schema_version"] == "2026-05-12.document-artifacts.v1"
    assert manifest["record_type"] == "document_artifact_manifest"
    assert manifest["write_performed"] is False
    assert manifest["active_memory_write_performed"] is False
    assert manifest["document_id"] == "doc_alpha"
    assert manifest["manifest_id"].startswith("doc_manifest_doc_alpha_")
    assert manifest["artifacts"]["raw_source"]["ref"].startswith("document_artifacts/sources/aa/")
    assert manifest["artifacts"]["raw_source"]["content_hash"] == "sha256:" + "a" * 64
    page_text_refs = [page["text_artifact"]["ref"] for page in manifest["pages"] if page.get("text_artifact")]
    assert len(page_text_refs) == 2
    assert all(not Path(ref).is_absolute() for ref in page_text_refs)
    assert manifest["resume"]["states"] == {
        "1": "text_extracted",
        "2": "visual_needed",
        "3": "failed",
    }
    first_text_hash = "sha256:" + hashlib.sha256("Page one text".encode("utf-8")).hexdigest()
    assert manifest["pages"][0]["text_artifact"]["content_hash"] == first_text_hash


def test_artifact_path_from_ref_stays_under_data_root(tmp_path):
    resolved = artifact_path_from_ref("document_artifacts/sources/aa/example.pdf", data_root=tmp_path / "data")

    assert resolved == (tmp_path / "data" / "document_artifacts" / "sources" / "aa" / "example.pdf").resolve()

    with pytest.raises(ValueError, match="artifact ref must be relative"):
        artifact_path_from_ref("C:/outside/file.pdf", data_root=tmp_path / "data")

    with pytest.raises(ValueError, match="artifact ref cannot contain parent traversal"):
        artifact_path_from_ref("../outside/file.pdf", data_root=tmp_path / "data")
