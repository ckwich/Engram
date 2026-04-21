from __future__ import annotations

from typing import NotRequired, TypedDict


class SearchErrorPayload(TypedDict):
    code: str
    message: str


class SearchResultPayload(TypedDict):
    key: str
    chunk_id: int
    title: str
    score: float
    snippet: str
    tags: list[str]
    pinned: NotRequired[bool]
    explanation: NotRequired[str]
    project: NotRequired[str | None]
    domain: NotRequired[str | None]
    status: NotRequired[str]
    canonical: NotRequired[bool]
    stale_type: NotRequired[str | None]


class SearchPayload(TypedDict):
    query: str
    count: int
    results: list[SearchResultPayload]
    error: SearchErrorPayload | None


class MemoryListItemPayload(TypedDict):
    key: str
    title: str
    tags: list[str]
    updated_at: str
    created_at: str
    chars: int
    chunk_count: int | str


class MemoryListPayload(TypedDict):
    count: int
    memories: list[MemoryListItemPayload]
    error: SearchErrorPayload | None


def build_search_payload(query: str, results: list[SearchResultPayload]) -> SearchPayload:
    return {
        "query": query,
        "count": len(results),
        "results": results,
        "error": None,
    }


def build_search_error_payload(query: str, code: str, message: str) -> SearchPayload:
    return {
        "query": query,
        "count": 0,
        "results": [],
        "error": {
            "code": code,
            "message": message,
        },
    }


def render_search_payload(payload: SearchPayload) -> str:
    if payload["error"] is not None:
        return payload["error"]["message"]

    query = payload["query"]
    results = payload["results"]

    if not results:
        return f"🔍 No memories found for '{query}'"

    lines = [f"🔍 {payload['count']} results for '{query}':\n"]
    for result in results:
        tags = ", ".join(result["tags"]) if result["tags"] else "none"
        lines.append(
            f"[score: {result['score']}] {result['title']}\n"
            f"  key={result['key']}  chunk_id={result['chunk_id']}  tags={tags}\n"
            f"  snippet: {result['snippet']}\n"
        )
    return "\n".join(lines)


def build_list_payload(memories: list[MemoryListItemPayload]) -> MemoryListPayload:
    return {
        "count": len(memories),
        "memories": memories,
        "error": None,
    }


def build_list_error_payload(code: str, message: str) -> MemoryListPayload:
    return {
        "count": 0,
        "memories": [],
        "error": {
            "code": code,
            "message": message,
        },
    }


def render_list_payload(payload: MemoryListPayload) -> str:
    if payload["error"] is not None:
        return payload["error"]["message"]

    memories = payload["memories"]

    if not memories:
        return "📭 No memories stored yet."

    lines = [f"📚 Engram Memory Directory — {payload['count']} memories\n{'=' * 50}\n"]
    for memory in memories:
        tags = ", ".join(memory["tags"]) if memory["tags"] else "none"
        lines.append(
            f"🔑 {memory['key']}\n"
            f"   Title:   {memory['title']}\n"
            f"   Tags:    {tags}\n"
            f"   Chunks:  {memory['chunk_count']}\n"
            f"   Updated: {memory['updated_at'][:16]}\n"
        )
    return "\n".join(lines)
