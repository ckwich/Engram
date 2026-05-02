"""
core/chunker.py — Markdown-aware content chunker for Engram.

Splits memory content into retrievable chunks, preserving semantic boundaries.
Priority order: markdown headers → double newlines → hard size split.
"""
from __future__ import annotations

import re

MAX_CHUNK_SIZE = 800  # characters
_HEADING_SPLIT_RE = re.compile(r"(?=^#{1,3}\s)", re.MULTILINE)
_HEADING_LINE_RE = re.compile(r"^(#{1,3})\s+(.*?)\s*#*\s*$")


def _split_sections(content: str) -> list[str]:
    sections = [section.strip() for section in _HEADING_SPLIT_RE.split(content) if section.strip()]
    return sections or [content.strip()]


def _heading_metadata(section: str) -> tuple[int, str]:
    first_line = section.splitlines()[0].strip() if section else ""
    match = _HEADING_LINE_RE.match(first_line)
    if not match:
        return 0, ""

    level = len(match.group(1))
    title = match.group(2).strip()
    return level, title


def _chunk_payload(
    *,
    text: str,
    section_title: str,
    heading_path: list[str],
    chunk_kind: str,
) -> dict:
    return {
        "text": text,
        "section_title": section_title,
        "heading_path": heading_path,
        "chunk_kind": chunk_kind,
    }


def chunk_content_with_metadata(content: str, max_size: int = MAX_CHUNK_SIZE) -> list[dict]:
    """
    Split content into chunks suitable for embedding and retrieval.

    Returns a list of dicts with metadata:
    [{chunk_id: int, text: str, section_title: str, heading_path: list[str], chunk_kind: str}, ...]

    Strategy:
    1. Split on markdown headers (preserving the header in the chunk)
    2. If a section is still too large, split on double newlines
    3. If still too large, hard split by character count
    """
    if not content or not content.strip():
        return [
            {
                "chunk_id": 0,
                **_chunk_payload(
                    text=content.strip(),
                    section_title="",
                    heading_path=[],
                    chunk_kind="section",
                ),
            }
        ]

    sections = _split_sections(content)

    raw_chunks: list[dict] = []
    current_heading_path: list[str] = []

    for section in sections:
        section_heading_level, section_title = _heading_metadata(section)
        if section_heading_level:
            current_heading_path = current_heading_path[: section_heading_level - 1] + [section_title]

        heading_path = list(current_heading_path)

        if len(section) <= max_size:
            raw_chunks.append(
                _chunk_payload(
                    text=section,
                    section_title=section_title,
                    heading_path=heading_path,
                    chunk_kind="section",
                )
            )
            continue

        paragraphs = [paragraph.strip() for paragraph in section.split("\n\n") if paragraph.strip()]
        current = ""
        for paragraph in paragraphs:
            if not current:
                current = paragraph
            elif len(current) + 2 + len(paragraph) <= max_size:
                current += "\n\n" + paragraph
            else:
                raw_chunks.append(
                    _chunk_payload(
                        text=current,
                        section_title=section_title,
                        heading_path=heading_path,
                        chunk_kind="paragraph",
                    )
                )
                current = paragraph
        if current:
            raw_chunks.append(
                _chunk_payload(
                    text=current,
                    section_title=section_title,
                    heading_path=heading_path,
                    chunk_kind="paragraph",
                )
            )

    final_chunks: list[dict] = []
    for chunk in raw_chunks:
        text = chunk["text"]
        if len(text) <= max_size:
            final_chunks.append(chunk)
            continue

        for i in range(0, len(text), max_size):
            final_chunks.append(
                _chunk_payload(
                    text=text[i : i + max_size],
                    section_title=chunk["section_title"],
                    heading_path=list(chunk["heading_path"]),
                    chunk_kind="hard",
                )
            )

    return [
        {
            "chunk_id": i,
            **chunk,
        }
        for i, chunk in enumerate(final_chunks)
    ]


def chunk_content(content: str, max_size: int = MAX_CHUNK_SIZE) -> list[dict]:
    """
    Split content into chunks suitable for embedding and retrieval.

    Returns a list of dicts: [{chunk_id: int, text: str}, ...]

    Strategy:
    1. Split on markdown headers (preserving the header in the chunk)
    2. If a section is still too large, split on double newlines
    3. If still too large, hard split by character count
    """
    return [
        {
            "chunk_id": chunk["chunk_id"],
            "text": chunk["text"],
        }
        for chunk in chunk_content_with_metadata(content, max_size=max_size)
    ]
