"""Compile reviewed design knowledge into citation-backed skill packs."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from core.memory_os._records import read_record, stable_id, upsert_record
from core.memory_os.ledger import MemoryOSLedger


def compile_design_knowledge(scope: dict[str, Any], *, ledger: MemoryOSLedger) -> dict[str, Any]:
    """Compile reviewed design concepts into source-backed agent skill material."""
    concepts = [
        concept
        for concept in scope.get("concepts", [])
        if isinstance(concept, dict) and concept.get("review_state") == "reviewed"
    ]
    compilation = {
        "schema_version": "2026-05-13.memory-os.design-compiler.v1",
        "compilation_id": stable_id("design_compilation", scope),
        "scope_id": scope.get("scope_id"),
        "principles": [_principle(concept) for concept in concepts],
        "critique_rubrics": _rubrics(concepts),
        "checklist": _checklist(concepts),
        "anti_patterns": _anti_patterns(concepts),
        "eval_pack_refs": _dedupe(
            [
                str(ref)
                for concept in concepts
                for ref in concept.get("eval_pack_refs", [])
            ]
        ),
        "quote_safety": {
            "direct_excerpt_policy": "short_quotes_only",
            "raw_source_exported": False,
        },
    }
    upsert_record(ledger, "skill_packs", compilation["compilation_id"], compilation)
    return compilation


def export_skill_pack(compilation_id: str, target: str | Path, *, ledger: MemoryOSLedger) -> dict[str, Any]:
    """Export a compiled design skill pack manifest without raw source dumps."""
    compilation = read_record(ledger, "skill_packs", compilation_id)
    if compilation is None:
        raise KeyError(f"design compilation not found: {compilation_id}")
    path = Path(target)
    if path.suffix.lower() != ".json":
        path = path / "skill_pack.json"
    _write_json(path, compilation)
    return {
        "schema_version": "2026-05-13.memory-os.skill-pack-export.v1",
        "compilation_id": compilation_id,
        "skill_pack_path": str(path),
        "principle_count": len(compilation.get("principles", [])),
        "raw_source_exported": False,
    }


def _principle(concept: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": concept.get("label"),
        "definition": concept.get("definition"),
        "citation_refs": list(concept.get("source_refs", [])),
    }


def _rubrics(concepts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "concept": concept.get("label"),
            "prompt": prompt,
            "citation_refs": list(concept.get("source_refs", [])),
        }
        for concept in concepts
        for prompt in concept.get("critique_prompts", [])
    ]


def _checklist(concepts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "concept": concept.get("label"),
            "text": item,
            "citation_refs": list(concept.get("source_refs", [])),
        }
        for concept in concepts
        for item in concept.get("checklist_items", [])
    ]


def _anti_patterns(concepts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "concept": concept.get("label"),
            "name": item,
            "citation_refs": list(concept.get("source_refs", [])),
        }
        for concept in concepts
        for item in concept.get("anti_patterns", [])
    ]


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    encoded = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
