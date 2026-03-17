"""
core/chunker.py — Markdown-aware content chunker for Engram.

Splits memory content into retrievable chunks, preserving semantic boundaries.
Priority order: markdown headers → double newlines → hard size split.
"""
from __future__ import annotations
import re

MAX_CHUNK_SIZE = 800  # characters


def chunk_content(content: str, max_size: int = MAX_CHUNK_SIZE) -> list[dict]:
    """
    Split content into chunks suitable for embedding and retrieval.

    Returns a list of dicts: [{chunk_id: int, text: str}, ...]

    Strategy:
    1. Split on markdown headers (preserving the header in the chunk)
    2. If a section is still too large, split on double newlines
    3. If still too large, hard split by character count
    """
    if not content or not content.strip():
        return [{"chunk_id": 0, "text": content.strip()}]

    # Split on markdown headers, keeping the header attached to its section
    sections = re.split(r'(?=^#{1,3}\s)', content, flags=re.MULTILINE)
    sections = [s.strip() for s in sections if s.strip()]

    # If no headers found, treat whole content as one section
    if not sections:
        sections = [content.strip()]

    raw_chunks = []
    for section in sections:
        if len(section) <= max_size:
            raw_chunks.append(section)
        else:
            # Split on double newlines
            paragraphs = [p.strip() for p in section.split('\n\n') if p.strip()]
            current = ""
            for para in paragraphs:
                if not current:
                    current = para
                elif len(current) + 2 + len(para) <= max_size:
                    current += "\n\n" + para
                else:
                    raw_chunks.append(current)
                    current = para
            if current:
                raw_chunks.append(current)

    # Final pass: hard split anything still over max_size
    final_chunks = []
    for chunk in raw_chunks:
        if len(chunk) <= max_size:
            final_chunks.append(chunk)
        else:
            for i in range(0, len(chunk), max_size):
                final_chunks.append(chunk[i:i + max_size])

    return [{"chunk_id": i, "text": text} for i, text in enumerate(final_chunks)]
