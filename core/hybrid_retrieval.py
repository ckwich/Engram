from __future__ import annotations

import re
from typing import Iterable

VALID_RETRIEVAL_MODES = {"semantic", "hybrid"}
TOKEN_RE = re.compile(r"[A-Za-z0-9_./:-]+")


def normalize_retrieval_mode(mode: str | None) -> str:
    normalized = (mode or "semantic").strip().lower()
    if normalized not in VALID_RETRIEVAL_MODES:
        valid = ", ".join(sorted(VALID_RETRIEVAL_MODES))
        raise ValueError(f"retrieval_mode must be one of: {valid}")
    return normalized


def tokenize_for_lexical_score(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_RE.findall(text or "") if token.strip()}


def lexical_relevance_score(query: str, texts: Iterable[str]) -> float:
    query_tokens = tokenize_for_lexical_score(query)
    if not query_tokens:
        return 0.0

    haystack = "\n".join(text or "" for text in texts)
    haystack_lower = haystack.lower()
    haystack_tokens = tokenize_for_lexical_score(haystack)
    overlap = len(query_tokens & haystack_tokens) / len(query_tokens)

    phrase_boost = 0.0
    query_phrase = " ".join(query.lower().split())
    if query_phrase and query_phrase in " ".join(haystack_lower.split()):
        phrase_boost = 0.15

    identifier_boost = 0.0
    for token in query_tokens:
        if len(token) >= 8 and token in haystack_lower:
            identifier_boost = 0.1
            break

    return round(min(overlap + phrase_boost + identifier_boost, 1.0), 4)


def combine_retrieval_score(semantic_score: float, lexical_score: float) -> float:
    return round((semantic_score * 0.72) + (lexical_score * 0.28), 4)
