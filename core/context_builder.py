from __future__ import annotations


def build_context_receipt(
    query: str,
    filters: dict[str, object],
    semantic_candidate_count: int,
    graph_candidate_count: int,
    selected_chunk_count: int,
    omitted_count: int,
    budget_chars: int,
    used_chars: int,
    include_stale: bool,
    graph_enabled: bool,
    max_hops: int,
    retrieval_mode: str = "semantic",
    citation_count: int = 0,
) -> dict[str, object]:
    return {
        "query": query,
        "filters": filters,
        "retrieval_mode": retrieval_mode,
        "semantic_candidate_count": semantic_candidate_count,
        "graph_candidate_count": graph_candidate_count,
        "selected_chunk_count": selected_chunk_count,
        "citation_count": citation_count,
        "omitted_count": omitted_count,
        "budget_chars": budget_chars,
        "used_chars": used_chars,
        "stale_policy": "included" if include_stale else "excluded",
        "graph_enabled": graph_enabled,
        "max_hops": max_hops,
    }


def merge_graph_candidates(
    semantic_refs: list[dict],
    graph_edges: list[dict],
    max_graph_candidates: int,
) -> list[dict]:
    seen = {(item["key"], item.get("chunk_id")) for item in semantic_refs}
    candidates: list[dict] = []
    for edge in graph_edges:
        ref = edge.get("to_ref") or {}
        if ref.get("kind") != "memory" or not ref.get("key"):
            continue
        candidate_key = ref["key"]
        if (candidate_key, None) in seen or any(item["key"] == candidate_key for item in semantic_refs):
            continue
        candidates.append({"key": candidate_key, "reason": "graph_neighbor"})
        seen.add((candidate_key, None))
        if len(candidates) >= max_graph_candidates:
            break
    return candidates


def make_filters(
    project: str | None = None,
    domain: str | None = None,
    tags: list[str] | None = None,
    include_stale: bool = False,
    canonical_only: bool = False,
) -> dict[str, object]:
    return {
        "project": project,
        "domain": domain,
        "tags": tags or [],
        "include_stale": include_stale,
        "canonical_only": canonical_only,
    }
