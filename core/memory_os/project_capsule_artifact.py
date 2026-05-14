"""EKC v0 adapter over existing no-write project capsule drafts."""
from __future__ import annotations

from typing import Any

from core.memory_os._records import now_iso
from core.memory_os.knowledge_citations import normalize_knowledge_citations
from core.project_capsule import build_project_capsule_draft


PROJECT_CAPSULE_ARTIFACT_VERSION = "v0"
ADAPTER_BASIS = "core.project_capsule.build_project_capsule_draft"


def build_project_capsule_artifact(
    *,
    project: str,
    goal: str,
    focus: list[str],
    context_packet: dict[str, Any],
    quality_payload: dict[str, Any],
    source_snapshot_id: str,
) -> dict[str, Any]:
    draft = build_project_capsule_draft(
        project=project,
        task=goal,
        summary=None,
        must_read_keys=None,
        context_packet=context_packet,
        quality_payload=quality_payload,
    )
    chunks = list((context_packet.get("context") or {}).get("chunks") or [])
    citations = []
    source_refs = []
    fields = {
        "summary": "",
        "current_goals": [],
        "active_decisions": [],
        "constraints": [],
        "open_questions": [],
        "important_entities": [],
        "recent_changes": [],
    }

    for index, chunk in enumerate(chunks, start=1):
        citation_id = f"cit_{index:03d}"
        key = str(chunk.get("key") or "")
        chunk_id = int(chunk.get("chunk_id", 0))
        text = str(chunk.get("text") or chunk.get("snippet") or "")
        citations.append(
            {
                "citation_id": citation_id,
                "level": "chunk",
                "key": key,
                "chunk_id": chunk_id,
                "source": "memory_os",
                "document_id": chunk.get("document_id"),
                "review_state": chunk.get("review_state"),
            }
        )
        source_refs.append(
            {
                "key": key,
                "chunk_id": chunk_id,
                "citation_id": citation_id,
                "score": float(chunk.get("score") or 0.0),
            }
        )
        _merge_text_into_fields(fields, text)

    return {
        "artifact_type": "project_capsule",
        "artifact_version": PROJECT_CAPSULE_ARTIFACT_VERSION,
        "adapter_basis": ADAPTER_BASIS,
        "project": project,
        "goal": goal,
        "focus": list(focus),
        "generated_at": now_iso(),
        "source_snapshot_id": source_snapshot_id,
        "source_refs": source_refs,
        "summary": fields["summary"],
        "current_goals": fields["current_goals"],
        "active_decisions": fields["active_decisions"],
        "constraints": fields["constraints"],
        "open_questions": fields["open_questions"],
        "important_entities": fields["important_entities"],
        "recent_changes": fields["recent_changes"],
        "citations": normalize_knowledge_citations(citations, default_source="memory_os"),
        "draft": draft,
        "staleness": {
            "state": "fresh" if source_refs else "partial",
            "invalidated_by": [],
        },
    }


def _merge_text_into_fields(fields: dict[str, Any], text: str) -> None:
    heading = ""
    body_lines = []
    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip().lower()
            continue
        if stripped:
            body_lines.append(stripped)
    body = " ".join(body_lines).strip()
    if not body:
        return
    if "constraint" in heading:
        _append_unique(fields["constraints"], body)
    elif "decision" in heading:
        _append_unique(fields["active_decisions"], body)
    elif "goal" in heading:
        _append_unique(fields["current_goals"], body)
    elif "question" in heading:
        _append_unique(fields["open_questions"], body)
    elif "entity" in heading or "concept" in heading:
        _append_unique(fields["important_entities"], body)
    elif "change" in heading:
        _append_unique(fields["recent_changes"], body)
    elif not fields["summary"]:
        fields["summary"] = body


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)
