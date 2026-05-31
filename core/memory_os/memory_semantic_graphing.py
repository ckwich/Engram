"""Automatic semantic graph enrichment for reviewed Memory OS memories."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from core.memory_os._records import hash_payload, now_iso, read_record, stable_id, upsert_record
from core.memory_os.ledger import MemoryOSLedger


MEMORY_SEMANTIC_GRAPH_SOURCE = "memory_semantic_graph"
MEMORY_GRAPH_ENRICHMENT_JOB_KIND = "memory_graph_enrichment"
GRAPHABLE_MEMORY_STATUSES = {"active", "accepted", "reviewed"}
MAX_CONCEPTS_PER_MEMORY = 12
MAX_CONCEPTS_PER_CHUNK = 5


_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
_LABEL_RE = re.compile(r"^\s*(?:[-*]\s+)?(?:\*\*)?([A-Z][A-Za-z0-9][A-Za-z0-9 /&+'-]{2,60}?)(?:\*\*)?:", re.MULTILINE)
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-'][A-Za-z0-9]+)?")
_NOISE_RE = re.compile(r"\s+")
_STOPWORDS = {
    "about",
    "above",
    "across",
    "after",
    "again",
    "against",
    "also",
    "amid",
    "among",
    "and",
    "another",
    "around",
    "because",
    "before",
    "between",
    "both",
    "but",
    "can",
    "could",
    "does",
    "done",
    "each",
    "for",
    "from",
    "had",
    "has",
    "have",
    "into",
    "its",
    "make",
    "more",
    "must",
    "need",
    "needs",
    "not",
    "only",
    "onto",
    "over",
    "same",
    "should",
    "than",
    "that",
    "the",
    "their",
    "then",
    "there",
    "these",
    "this",
    "those",
    "through",
    "under",
    "until",
    "use",
    "uses",
    "using",
    "was",
    "were",
    "when",
    "where",
    "which",
    "while",
    "with",
    "without",
    "would",
}


def graph_memory_semantics(
    *,
    ledger: MemoryOSLedger,
    graph: Any,
    memory: dict[str, Any],
    chunks: list[dict[str, Any]],
    created_by: str = MEMORY_GRAPH_ENRICHMENT_JOB_KIND,
) -> dict[str, Any]:
    """Run deterministic semantic graph enrichment for a stored memory."""
    key = str(memory.get("key") or "").strip()
    if not key:
        return _receipt(
            job_id="",
            fingerprint="",
            status="skipped",
            graph_edges=[],
            stale_edges=[],
            concept_ids=[],
            graph_write_performed=False,
            idempotent_replay=False,
            warning="memory key is required for semantic graph enrichment.",
        )

    fingerprint = _fingerprint(memory, chunks)
    job_id = stable_id(
        "job",
        {
            "job_kind": MEMORY_GRAPH_ENRICHMENT_JOB_KIND,
            "memory_key": key,
            "fingerprint": fingerprint,
        },
    )
    timestamp = now_iso()
    concepts = _extract_concepts(memory, chunks)
    if str(memory.get("status") or "").strip().lower() not in GRAPHABLE_MEMORY_STATUSES:
        concepts = []

    concept_records = [_concept_record(concept, timestamp=timestamp, created_by=created_by) for concept in concepts]
    semantic_edges = _semantic_edges(
        memory=memory,
        concepts=concepts,
        timestamp=timestamp,
        created_by=created_by,
    )
    existing_job = read_record(ledger, "jobs", job_id)
    semantic_edge_ids = {edge["edge_id"] for edge in semantic_edges}
    stale_edges = _stale_semantic_edges(
        ledger,
        memory_key=key,
        memory=memory,
        keep_edge_ids=semantic_edge_ids,
        timestamp=timestamp,
        job_id=job_id,
        created_by=created_by,
        existing_job=existing_job,
    )
    changed_edges = [edge for edge in semantic_edges if not _existing_edge_equivalent(ledger, edge)]
    idempotent_replay = (
        isinstance(existing_job, dict)
        and existing_job.get("status") == "succeeded"
        and not changed_edges
        and not stale_edges
    )
    if idempotent_replay:
        return _receipt(
            job_id=job_id,
            fingerprint=fingerprint,
            status="succeeded",
            graph_edges=semantic_edges,
            stale_edges=[],
            concept_ids=[concept["concept_id"] for concept in concepts],
            graph_write_performed=False,
            idempotent_replay=True,
        )

    edges_to_import = [*changed_edges, *stale_edges]
    if edges_to_import:
        graph.import_edges(edges_to_import)
    for record in concept_records:
        upsert_record(ledger, "concepts", record["concept_id"], record)

    status = "succeeded" if concepts else "skipped"
    receipt = _receipt(
        job_id=job_id,
        fingerprint=fingerprint,
        status=status,
        graph_edges=semantic_edges,
        stale_edges=stale_edges,
        concept_ids=[concept["concept_id"] for concept in concepts],
        graph_write_performed=bool(edges_to_import),
        idempotent_replay=False,
    )
    _upsert_job(
        ledger,
        job_id=job_id,
        memory=memory,
        chunks=chunks,
        fingerprint=fingerprint,
        status=status,
        result=receipt,
        timestamp=timestamp,
        existing_job=existing_job,
    )
    _upsert_job_event(
        ledger,
        job_id=job_id,
        event_type=status,
        payload={
            "memory_key": key,
            "fingerprint": fingerprint,
            "graph_edges_written": receipt["graph_edges_written"],
            "graph_edges_deactivated": receipt["graph_edges_deactivated"],
        },
        timestamp=timestamp,
    )
    return receipt


def _extract_concepts(memory: dict[str, Any], chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    first_ref = _first_chunk_ref(chunks)

    def add(phrase: Any, *, chunk: dict[str, Any] | None, source: str, boost: int = 0) -> None:
        normalized = _normalize_phrase(phrase)
        if not normalized:
            return
        slug = _slugify(normalized)
        concept_id = f"concept:semantic:{slug}"
        candidate = candidates.setdefault(
            concept_id,
            {
                "concept_id": concept_id,
                "name": _display_name(normalized),
                "slug": slug,
                "score": 0,
                "sources": set(),
                "evidence_refs": [],
                "chunk_refs": {},
                "heading": False,
            },
        )
        candidate["score"] += 1 + boost
        candidate["sources"].add(source)
        if source == "heading":
            candidate["heading"] = True
        ref = _chunk_evidence_ref(chunk) if chunk is not None else first_ref
        if ref:
            ref_key = _stable_ref_key(ref)
            candidate["chunk_refs"][ref_key] = ref
            if ref not in candidate["evidence_refs"]:
                candidate["evidence_refs"].append(ref)

    add(memory.get("title"), chunk=None, source="title", boost=2)
    for chunk in chunks:
        for heading in chunk.get("heading_path") or []:
            add(heading, chunk=chunk, source="heading", boost=4)
        add(chunk.get("section_title"), chunk=chunk, source="heading", boost=3)
        text = str(chunk.get("text") or "")
        for heading in _HEADING_RE.findall(text):
            add(heading, chunk=chunk, source="heading", boost=4)
        for label in _LABEL_RE.findall(text):
            add(label, chunk=chunk, source="label", boost=3)
        for phrase, count in _ranked_text_phrases(text):
            add(phrase, chunk=chunk, source="text", boost=count)

    ranked = sorted(
        candidates.values(),
        key=lambda item: (
            -int(item["score"]),
            0 if item["heading"] else 1,
            -len(str(item["name"])),
            str(item["name"]).lower(),
        ),
    )
    concepts: list[dict[str, Any]] = []
    for item in ranked[:MAX_CONCEPTS_PER_MEMORY]:
        chunk_refs = list(item["chunk_refs"].values())[:MAX_CONCEPTS_PER_CHUNK]
        concepts.append(
            {
                "concept_id": item["concept_id"],
                "name": item["name"],
                "score": int(item["score"]),
                "sources": sorted(item["sources"]),
                "evidence_refs": list(item["evidence_refs"])[:MAX_CONCEPTS_PER_CHUNK],
                "chunk_refs": chunk_refs,
                "heading": bool(item["heading"]),
            }
        )
    return concepts


def _ranked_text_phrases(text: str) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter()
    for span in re.split(r"[\n.!?;:]+", text):
        tokens = [_normalize_token(token) for token in _TOKEN_RE.findall(span)]
        tokens = [token for token in tokens if token]
        for length in (4, 3, 2):
            for index in range(0, max(len(tokens) - length + 1, 0)):
                window = tokens[index : index + length]
                if any(token in _STOPWORDS for token in window):
                    continue
                if all(len(token) < 4 for token in window):
                    continue
                phrase = " ".join(window)
                if not _normalize_phrase(phrase):
                    continue
                counts[phrase] += 1
    return sorted(counts.items(), key=lambda item: (-item[1], -len(item[0]), item[0]))[:MAX_CONCEPTS_PER_MEMORY]


def _semantic_edges(
    *,
    memory: dict[str, Any],
    concepts: list[dict[str, Any]],
    timestamp: str,
    created_by: str,
) -> list[dict[str, Any]]:
    key = str(memory.get("key") or "").strip()
    from_memory = {"kind": "memory", "key": key}
    project = _optional_text(memory.get("project"))
    domain = _optional_text(memory.get("domain"))
    edges: list[dict[str, Any]] = []
    for concept in concepts:
        to_ref = {"kind": "concept", "id": concept["concept_id"], "name": concept["name"]}
        evidence_refs = list(concept.get("evidence_refs") or [])
        edges.append(
            _edge(
                from_ref=from_memory,
                to_ref=to_ref,
                edge_type="mentions",
                confidence=_memory_edge_confidence(concept),
                evidence=f"Memory '{key}' discusses semantic concept '{concept['name']}'.",
                evidence_refs=evidence_refs,
                project=project,
                domain=domain,
                timestamp=timestamp,
                created_by=created_by,
            )
        )
        for ref in list(concept.get("chunk_refs") or [])[:MAX_CONCEPTS_PER_CHUNK]:
            chunk_record_id = str(ref.get("chunk_record_id") or "").strip()
            if not chunk_record_id:
                continue
            edge_type = "defines" if concept.get("heading") else "mentions"
            edges.append(
                _edge(
                    from_ref={
                        "kind": "chunk",
                        "key": chunk_record_id,
                        "memory_key": key,
                        "chunk_index": ref.get("chunk_index"),
                    },
                    to_ref=to_ref,
                    edge_type=edge_type,
                    confidence=0.86 if edge_type == "defines" else 0.72,
                    evidence=f"Chunk '{chunk_record_id}' {edge_type} semantic concept '{concept['name']}'.",
                    evidence_refs=[ref],
                    project=project,
                    domain=domain,
                    timestamp=timestamp,
                    created_by=created_by,
                )
            )
    return edges


def _edge(
    *,
    from_ref: dict[str, Any],
    to_ref: dict[str, Any],
    edge_type: str,
    confidence: float,
    evidence: str,
    evidence_refs: list[dict[str, Any]],
    project: str | None,
    domain: str | None,
    timestamp: str,
    created_by: str,
) -> dict[str, Any]:
    edge = {
        "from_ref": dict(from_ref),
        "to_ref": dict(to_ref),
        "edge_type": edge_type,
        "confidence": confidence,
        "evidence": evidence,
        "evidence_refs": [dict(ref) for ref in evidence_refs if isinstance(ref, dict)],
        "source": MEMORY_SEMANTIC_GRAPH_SOURCE,
        "status": "active",
        "created_by": created_by,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    if project:
        edge["project"] = project
    if domain:
        edge["domain"] = domain
    edge["edge_id"] = stable_id(
        "edge",
        {
            "source": MEMORY_SEMANTIC_GRAPH_SOURCE,
            "from_ref": edge["from_ref"],
            "to_ref": edge["to_ref"],
            "edge_type": edge["edge_type"],
        },
    )
    return edge


def _concept_record(concept: dict[str, Any], *, timestamp: str, created_by: str) -> dict[str, Any]:
    return {
        "concept_id": concept["concept_id"],
        "name": concept["name"],
        "concept_type": "semantic_concept",
        "source": MEMORY_SEMANTIC_GRAPH_SOURCE,
        "status": "active",
        "created_by": created_by,
        "created_at": timestamp,
        "updated_at": timestamp,
        "evidence_refs": list(concept.get("evidence_refs") or []),
        "sources": list(concept.get("sources") or []),
    }


def _stale_semantic_edges(
    ledger: MemoryOSLedger,
    *,
    memory_key: str,
    memory: dict[str, Any],
    keep_edge_ids: set[str],
    timestamp: str,
    job_id: str,
    created_by: str,
    existing_job: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    stale: list[dict[str, Any]] = []
    previous_edge_ids = _previous_semantic_edge_ids(existing_job, memory=memory)
    if not previous_edge_ids:
        return stale
    for edge_id in previous_edge_ids:
        edge = read_record(ledger, "graph_edges", edge_id)
        if not isinstance(edge, dict):
            continue
        if edge.get("source") != MEMORY_SEMANTIC_GRAPH_SOURCE:
            continue
        if edge.get("status") != "active":
            continue
        if str(edge.get("edge_id") or "") in keep_edge_ids:
            continue
        if not _edge_belongs_to_memory(edge, memory_key):
            continue
        updated = dict(edge)
        updated["status"] = "superseded"
        updated["updated_at"] = timestamp
        updated["updated_by"] = created_by
        updated["superseded_by_job_id"] = job_id
        updated["superseded_reason"] = "semantic concepts were refreshed for the current memory fingerprint."
        stale.append(updated)
    return stale


def _previous_semantic_edge_ids(
    existing_job: dict[str, Any] | None,
    *,
    memory: dict[str, Any],
) -> list[str]:
    edge_ids: list[str] = []
    for value in memory.get("semantic_graph_edge_ids") or []:
        if isinstance(value, str):
            edge_ids.append(value)
    if isinstance(existing_job, dict):
        result = existing_job.get("result")
        if isinstance(result, dict):
            for field in ("graph_edges_written", "graph_edges"):
                values = result.get(field)
                if not isinstance(values, list):
                    continue
                for value in values:
                    if isinstance(value, str):
                        edge_ids.append(value)
                    elif isinstance(value, dict) and isinstance(value.get("edge_id"), str):
                        edge_ids.append(value["edge_id"])
    return sorted(set(edge_ids))


def _edge_belongs_to_memory(edge: dict[str, Any], memory_key: str) -> bool:
    refs = [edge.get("from_ref"), edge.get("to_ref")]
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        if ref.get("kind") == "memory" and ref.get("key") == memory_key:
            return True
        if ref.get("kind") == "chunk":
            if ref.get("memory_key") == memory_key:
                return True
            chunk_key = str(ref.get("key") or ref.get("chunk_record_id") or "")
            if chunk_key.startswith(f"{memory_key}:chunk:"):
                return True
    return False


def _existing_edge_equivalent(ledger: MemoryOSLedger, edge: dict[str, Any]) -> bool:
    existing = read_record(ledger, "graph_edges", edge["edge_id"])
    if not isinstance(existing, dict):
        return False
    fields = (
        "from_ref",
        "to_ref",
        "edge_type",
        "confidence",
        "evidence",
        "evidence_refs",
        "source",
        "status",
        "project",
        "domain",
    )
    for field in fields:
        if existing.get(field) != edge.get(field):
            return False
    return True


def _upsert_job(
    ledger: MemoryOSLedger,
    *,
    job_id: str,
    memory: dict[str, Any],
    chunks: list[dict[str, Any]],
    fingerprint: str,
    status: str,
    result: dict[str, Any],
    timestamp: str,
    existing_job: dict[str, Any] | None,
) -> None:
    job = {
        "job_id": job_id,
        "job_kind": MEMORY_GRAPH_ENRICHMENT_JOB_KIND,
        "payload": {
            "memory_key": memory.get("key"),
            "content_hash": memory.get("content_hash"),
            "metadata_hash": _metadata_hash(memory),
            "fingerprint": fingerprint,
            "chunk_count": len(chunks),
        },
        "status": status,
        "result": result,
        "idempotency_key": f"{MEMORY_GRAPH_ENRICHMENT_JOB_KIND}:{memory.get('key')}:{fingerprint}",
        "created_at": existing_job.get("created_at") if isinstance(existing_job, dict) else timestamp,
        "updated_at": timestamp,
    }
    upsert_record(ledger, "jobs", job_id, job)


def _upsert_job_event(
    ledger: MemoryOSLedger,
    *,
    job_id: str,
    event_type: str,
    payload: dict[str, Any],
    timestamp: str,
) -> None:
    event_id = stable_id(
        "job_event",
        {
            "job_id": job_id,
            "event_type": event_type,
        },
    )
    upsert_record(
        ledger,
        "job_events",
        event_id,
        {
            "event_id": event_id,
            "job_id": job_id,
            "event_type": event_type,
            "payload": payload,
            "created_at": timestamp,
        },
    )


def _receipt(
    *,
    job_id: str,
    fingerprint: str,
    status: str,
    graph_edges: list[dict[str, Any]],
    stale_edges: list[dict[str, Any]],
    concept_ids: list[str],
    graph_write_performed: bool,
    idempotent_replay: bool,
    warning: str | None = None,
) -> dict[str, Any]:
    warnings = [warning] if warning else []
    return {
        "source": MEMORY_SEMANTIC_GRAPH_SOURCE,
        "job_kind": MEMORY_GRAPH_ENRICHMENT_JOB_KIND,
        "job_id": job_id,
        "fingerprint": fingerprint,
        "status": status,
        "graph_edges_written": [edge["edge_id"] for edge in graph_edges],
        "graph_edges_deactivated": [edge["edge_id"] for edge in stale_edges],
        "concepts_written": sorted(set(concept_ids)),
        "write_performed": graph_write_performed,
        "graph_write_performed": graph_write_performed,
        "active_memory_write_performed": False,
        "idempotent_replay": idempotent_replay,
        "warnings": warnings,
        "error": None,
    }


def _fingerprint(memory: dict[str, Any], chunks: list[dict[str, Any]]) -> str:
    return hash_payload(
        {
            "content_hash": memory.get("content_hash"),
            "metadata_hash": _metadata_hash(memory),
            "chunks": [
                {
                    "chunk_record_id": chunk.get("chunk_record_id"),
                    "text_hash": chunk.get("text_hash"),
                    "heading_path": chunk.get("heading_path"),
                    "section_title": chunk.get("section_title"),
                }
                for chunk in chunks
            ],
        }
    )


def _metadata_hash(memory: dict[str, Any]) -> str:
    return hash_payload(
        {
            "title": memory.get("title"),
            "tags": memory.get("tags") or [],
            "project": memory.get("project"),
            "domain": memory.get("domain"),
            "status": memory.get("status"),
            "canonical": memory.get("canonical"),
        }
    )


def _first_chunk_ref(chunks: list[dict[str, Any]]) -> dict[str, Any] | None:
    for chunk in chunks:
        ref = _chunk_evidence_ref(chunk)
        if ref:
            return ref
    return None


def _chunk_evidence_ref(chunk: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(chunk, dict):
        return None
    chunk_record_id = str(chunk.get("chunk_record_id") or "").strip()
    if not chunk_record_id:
        return None
    return {
        "kind": "chunk",
        "memory_key": chunk.get("memory_key"),
        "chunk_record_id": chunk_record_id,
        "chunk_index": chunk.get("chunk_index", chunk.get("chunk_id")),
        "text_hash": chunk.get("text_hash"),
    }


def _memory_edge_confidence(concept: dict[str, Any]) -> float:
    if concept.get("heading"):
        return 0.9
    return 0.78 if int(concept.get("score") or 0) > 1 else 0.68


def _stable_ref_key(ref: dict[str, Any]) -> str:
    return hash_payload(ref)


def _normalize_phrase(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = re.sub(r"[`*_>#]+", " ", text)
    text = text.replace("&", " and ")
    text = re.sub(r"[^A-Za-z0-9 +'/-]+", " ", text)
    text = _NOISE_RE.sub(" ", text).strip(" -/'")
    if not text:
        return None
    tokens = [_normalize_token(token) for token in _TOKEN_RE.findall(text)]
    tokens = [token for token in tokens if token and token not in _STOPWORDS]
    if not tokens:
        return None
    if len(tokens) == 1 and len(tokens[0]) < 5:
        return None
    if len(tokens) > 6:
        tokens = tokens[:6]
    phrase = " ".join(tokens)
    if len(phrase) < 5 or len(phrase) > 80:
        return None
    return phrase


def _normalize_token(value: Any) -> str:
    token = str(value or "").strip().lower()
    token = token.strip("-_'")
    return token


def _display_name(normalized: str) -> str:
    minor = {"ai", "api", "ui", "ux", "os", "mcp", "pdf", "ocr"}
    words = []
    for token in normalized.split():
        if token in minor:
            words.append(token.upper())
        else:
            words.append(token.capitalize())
    return " ".join(words)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _slugify(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "value"
