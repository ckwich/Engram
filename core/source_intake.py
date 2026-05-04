from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from core.ingestion_pipelines import resolve_ingestion_pipeline

PROJECT_ROOT = Path(__file__).parent.parent
SOURCE_DRAFTS_DIR = PROJECT_ROOT / "data" / "source_drafts"
SOURCE_DRAFT_SCHEMA_VERSION = "2026-04-30.source-draft.v2"

SECTION_TITLES = {
    "actions": "Actions",
    "architecture": "Architecture",
    "constraints": "Constraints",
    "decisions": "Decisions",
    "insights": "Insights",
    "invariants": "Invariants",
    "next_steps": "Next Steps",
    "notes": "Notes",
    "open_questions": "Open Questions",
    "questions": "Questions",
    "risks": "Risks",
    "validations": "Validation",
}


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _source_hash(source_text: str) -> str:
    return "sha256:" + hashlib.sha256(source_text.encode("utf-8")).hexdigest()


def _draft_path(draft_id: str) -> Path:
    safe_id = draft_id.replace(":", "_")
    return SOURCE_DRAFTS_DIR / f"{safe_id}.json"


def _stable_key(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _append_section(lines: list[str], title: str, items: list[str]) -> None:
    if not items:
        return
    lines.append(f"## {title}")
    lines.extend(f"- {item}" for item in items)
    lines.append("")


def _normalize_source_text(source_text: str) -> str:
    return "\n".join(line.strip() for line in source_text.splitlines() if line.strip())


def _require_non_blank_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value


def _normalize_optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value


def _normalize_budget_chars(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("budget_chars must be an integer")
    try:
        return max(100, min(int(value), 15000))
    except (TypeError, ValueError):
        raise ValueError("budget_chars must be an integer") from None


def _section_key(prefix: str) -> str:
    normalized = prefix.strip().lower().replace("-", "_")
    if normalized == "note":
        return "notes"
    if normalized == "next":
        return "next_steps"
    if normalized == "validation":
        return "validations"
    if normalized.endswith("y"):
        return normalized[:-1] + "ies"
    if normalized.endswith("s"):
        return normalized
    return normalized + "s"


class SourceIntakeManager:
    def __init__(self) -> None:
        self._draft_cache: dict[str, dict[str, Any]] | None = None

    def _extract_sections(self, source_text: str, extract_prefixes: list[str] | None = None) -> dict[str, list[str]]:
        prefixes = extract_prefixes or ["decision", "action", "risk", "note"]
        prefix_map = {
            prefix.strip().lower().replace("-", "_"): _section_key(prefix)
            for prefix in prefixes
            if prefix and prefix.strip()
        }
        sections = {section_key: [] for section_key in prefix_map.values() if section_key != "notes"}
        sections["notes"] = []
        for raw_line in source_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            lowered = line.lower()
            matched = False
            for prefix, section_key in prefix_map.items():
                if prefix == "note":
                    continue
                if lowered.startswith(f"{prefix}:"):
                    sections.setdefault(section_key, []).append(line.split(":", 1)[1].strip())
                    matched = True
                    break
            if not matched:
                sections["notes"].append(line)
        return sections

    def _draft_content(self, sections: dict[str, list[str]], budget_chars: int) -> str:
        lines = ["# Source Intake Draft", ""]
        for section_key, items in sections.items():
            _append_section(lines, SECTION_TITLES.get(section_key, section_key.replace("_", " ").title()), items)
        content = "\n".join(lines).strip() + "\n"
        return content[:budget_chars]

    def _write_draft(self, draft: dict[str, Any]) -> None:
        SOURCE_DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
        path = _draft_path(draft["draft_id"])
        fd, temp_name = tempfile.mkstemp(prefix="source-draft.", suffix=".tmp", dir=SOURCE_DRAFTS_DIR)
        temp_path = Path(temp_name)
        try:
            with open(fd, "w", encoding="utf-8") as handle:
                json.dump(draft, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            temp_path.replace(path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
        if self._draft_cache is not None:
            self._draft_cache[draft["draft_id"]] = draft

    def _load_drafts(self) -> dict[str, dict[str, Any]]:
        if self._draft_cache is not None:
            return self._draft_cache
        drafts: dict[str, dict[str, Any]] = {}
        if SOURCE_DRAFTS_DIR.exists():
            for path in SOURCE_DRAFTS_DIR.glob("*.json"):
                draft = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(draft, dict) and draft.get("draft_id"):
                    drafts[draft["draft_id"]] = draft
        self._draft_cache = drafts
        return drafts

    def prepare_source_memory(
        self,
        *,
        source_text: str,
        source_type: str,
        source_uri: str | None = None,
        project: str | None = None,
        domain: str | None = None,
        budget_chars: int = 6000,
        pipeline: str = "generic",
    ) -> dict[str, Any]:
        source_text = _require_non_blank_string(source_text, "source_text")
        source_type = _require_non_blank_string(source_type, "source_type")
        source_uri = _normalize_optional_string(source_uri, "source_uri")
        project = _normalize_optional_string(project, "project")
        domain = _normalize_optional_string(domain, "domain")
        pipeline = _normalize_optional_string(pipeline, "pipeline")

        pipeline_config = resolve_ingestion_pipeline(pipeline)
        normalized_budget = _normalize_budget_chars(budget_chars)
        normalized_source_text = _normalize_source_text(source_text)
        source_digest = _source_hash(source_text)
        draft_id = source_digest
        sections = self._extract_sections(
            source_text,
            extract_prefixes=pipeline_config.get("extract_prefixes", []),
        )
        content = self._draft_content(sections, normalized_budget)
        timestamp = _now()
        tags = []
        for tag in [source_type.strip(), *pipeline_config.get("tags", [])]:
            if tag and tag not in tags:
                tags.append(tag)
        proposed_memory = {
            "key": _stable_key("source_intake", f"{source_type}:{source_digest}"),
            "title": "Source Intake Draft",
            "content": content,
            "tags": tags,
            "project": project,
            "domain": domain,
            "status": pipeline_config.get("memory_status", "draft"),
            "canonical": False,
        }
        draft = {
            "schema_version": SOURCE_DRAFT_SCHEMA_VERSION,
            "draft_id": draft_id,
            "source_type": source_type.strip(),
            "source_uri": source_uri,
            "source_hash": source_digest,
            "normalized_source_text": normalized_source_text,
            "pipeline": pipeline_config["id"],
            "pipeline_config": {
                "id": pipeline_config["id"],
                "label": pipeline_config.get("label"),
                "extract_prefixes": pipeline_config.get("extract_prefixes", []),
                "stages": pipeline_config.get("stages", []),
            },
            "project": project,
            "domain": domain,
            "status": "draft",
            "proposed_memories": [proposed_memory],
            "proposed_edges": [],
            "receipt": {
                "input_chars": len(source_text),
                "cleaned_chars": sum(len(item) for values in sections.values() for item in values),
                "proposed_memory_count": 1,
                "proposed_edge_count": 0,
                "budget_chars": normalized_budget,
                "used_chars": len(content),
                "pipeline": pipeline_config["id"],
                "pipeline_stages": pipeline_config.get("stages", []),
            },
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        self._write_draft(draft)
        return draft

    def list_source_drafts(
        self,
        *,
        project: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        drafts = list(self._load_drafts().values())
        if project is not None:
            drafts = [draft for draft in drafts if draft.get("project") == project]
        if status is not None:
            drafts = [draft for draft in drafts if draft.get("status") == status]
        drafts.sort(key=lambda draft: draft.get("updated_at", ""), reverse=True)
        total = len(drafts)
        normalized_offset = max(int(offset), 0)
        normalized_limit = min(max(int(limit), 1), 500)
        page = drafts[normalized_offset:normalized_offset + normalized_limit]
        return {
            "count": len(page),
            "total": total,
            "limit": normalized_limit,
            "offset": normalized_offset,
            "has_more": normalized_offset + normalized_limit < total,
            "drafts": page,
            "error": None,
        }

    def get_source_draft(self, draft_id: str) -> dict[str, Any] | None:
        return self._load_drafts().get(draft_id)

    def discard_source_draft(self, draft_id: str) -> dict[str, Any]:
        draft = self.get_source_draft(draft_id)
        if draft is None:
            return {"discarded": False, "draft_id": draft_id, "error": "draft_not_found"}
        draft["status"] = "rejected"
        draft["updated_at"] = _now()
        self._write_draft(draft)
        return {"discarded": True, "draft_id": draft_id, "error": None}


source_intake_manager = SourceIntakeManager()
