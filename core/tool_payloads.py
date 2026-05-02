from __future__ import annotations

from typing import NotRequired, TypedDict


class SearchErrorPayload(TypedDict):
    code: str
    message: str


class ToolGroupPayload(TypedDict):
    purpose: str
    stability: str
    cost_class: str
    tools: list[str]


class ProgressiveDiscoveryPayload(TypedDict):
    start_here: str
    load_next: dict[str, str]


class MemoryProtocolPayload(TypedDict):
    name: str
    version: int
    schema_version: str
    stability: dict[str, str]
    retrieval_ladder: list[dict[str, object]]
    tool_groups: dict[str, ToolGroupPayload]
    progressive_discovery: ProgressiveDiscoveryPayload
    canonical_tools: dict[str, str]
    aliases: dict[str, str]
    examples: list[str]
    warnings: list[str]


class GraphRefPayload(TypedDict):
    kind: str
    key: str


class GraphEdgePayload(TypedDict):
    edge_id: str
    from_ref: dict[str, object]
    to_ref: dict[str, object]
    edge_type: str
    confidence: float
    evidence: str
    source: str
    status: str
    created_by: str
    created_at: str
    updated_at: str


class SourceDraftPayload(TypedDict):
    draft_id: str
    source_type: str
    status: str
    proposed_memories: list[dict[str, object]]
    proposed_edges: list[dict[str, object]]
    receipt: dict[str, object]


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
    project: NotRequired[str | None]
    domain: NotRequired[str | None]
    status: NotRequired[str]
    canonical: NotRequired[bool]


class MemoryListPayload(TypedDict):
    count: int
    memories: list[MemoryListItemPayload]
    error: SearchErrorPayload | None
    total: NotRequired[int]
    limit: NotRequired[int]
    offset: NotRequired[int]
    has_more: NotRequired[bool]


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


def build_list_payload(
    memories: list[MemoryListItemPayload],
    *,
    total: int | None = None,
    limit: int | None = None,
    offset: int | None = None,
    has_more: bool | None = None,
) -> MemoryListPayload:
    payload: MemoryListPayload = {
        "count": len(memories),
        "memories": memories,
        "error": None,
    }
    if total is not None:
        payload["total"] = total
    if limit is not None:
        payload["limit"] = limit
    if offset is not None:
        payload["offset"] = offset
    if has_more is not None:
        payload["has_more"] = has_more
    return payload


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

    total = payload.get("total")
    if total is not None and total != payload["count"]:
        heading_count = f"{payload['count']} of {total} memories"
    else:
        heading_count = f"{payload['count']} memories"

    lines = [f"📚 Engram Memory Directory — {heading_count}\n{'=' * 50}\n"]
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
