from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent
USAGE_DIR = PROJECT_ROOT / "data" / "usage"
TOOL_CALLS_PATH = USAGE_DIR / "tool_calls.jsonl"
# Reserved for later compaction; v0.6 summaries read TOOL_CALLS_PATH directly.
DAILY_ROLLUPS_PATH = USAGE_DIR / "daily_rollups.json"

ESTIMATE_METHOD = "chars_div_4"
SENSITIVE_KEYS = {"body", "content", "raw", "source_text", "text"}
HIGH_RESPONSE_TOKEN_WARNING = 2000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def estimate_tokens(value: Any) -> int:
    rendered = value if isinstance(value, str) else _stable_json(value)
    if not rendered:
        return 0
    return math.ceil(len(rendered) / 4)


def _sha256(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _strip_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                cleaned[key] = {"redacted": True, "tokens": estimate_tokens(item)}
            else:
                cleaned[key] = _strip_sensitive(item)
        return cleaned
    if isinstance(value, list):
        return [_strip_sensitive(item) for item in value]
    return value


def _memory_refs(output_payload: Any) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    chunks = output_payload.get("chunks", []) if isinstance(output_payload, dict) else []
    if not isinstance(chunks, list):
        return refs
    for chunk in chunks:
        if isinstance(chunk, dict) and chunk.get("key") is not None:
            refs.append({"key": chunk["key"], "chunk_id": chunk.get("chunk_id")})
    return refs


class UsageMeter:
    def record_tool_call(
        self,
        *,
        tool: str,
        input_payload: Any,
        output_payload: Any,
        status: str,
        duration_ms: int,
        error: str | None = None,
    ) -> dict[str, Any]:
        input_token_estimate = estimate_tokens(input_payload)
        response_token_estimate = estimate_tokens(output_payload)
        retrieved_text_tokens = self._retrieved_text_tokens(output_payload)
        receipt = output_payload.get("receipt", {}) if isinstance(output_payload, dict) else {}
        if not isinstance(receipt, dict):
            receipt = {}
        chunks = output_payload.get("chunks", []) if isinstance(output_payload, dict) else []
        event = {
            "call_id": _sha256(f"{tool}:{time.time_ns()}"),
            "timestamp": _now(),
            "tool": tool,
            "status": status,
            "duration_ms": int(duration_ms),
            "input_token_estimate": input_token_estimate,
            "response_token_estimate": response_token_estimate,
            "retrieved_text_tokens": retrieved_text_tokens,
            "budget_chars": receipt.get("budget_chars"),
            "used_chars": receipt.get("used_chars"),
            "chunk_count": len(chunks) if isinstance(chunks, list) else 0,
            "memory_refs": _memory_refs(output_payload),
            "estimate_method": ESTIMATE_METHOD,
            "warnings": self._warnings(response_token_estimate, retrieved_text_tokens, status),
            "error": error,
            "input_summary": _strip_sensitive(input_payload),
        }
        self._append_event(event)
        return event

    def list_calls(self, *, tool: str | None = None, limit: int = 100) -> dict[str, Any]:
        events = self._read_events()
        if tool:
            events = [event for event in events if event.get("tool") == tool]
        events = events[-limit:]
        return {"count": len(events), "calls": list(reversed(events))}

    def get_summary(self, *, days: int = 7) -> dict[str, Any]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        events = [
            event
            for event in self._read_events()
            if datetime.fromisoformat(event["timestamp"]) >= cutoff
        ]
        by_tool: dict[str, dict[str, Any]] = {}
        warnings: list[dict[str, Any]] = []
        for event in events:
            tool = event["tool"]
            bucket = by_tool.setdefault(
                tool,
                {"call_count": 0, "response_tokens": 0, "input_tokens": 0},
            )
            bucket["call_count"] += 1
            bucket["response_tokens"] += event["response_token_estimate"]
            bucket["input_tokens"] += event["input_token_estimate"]
            for warning in event.get("warnings", []):
                warnings.append({"tool": tool, **warning})
        total_calls = len(events)
        total_input = sum(event["input_token_estimate"] for event in events)
        total_response = sum(event["response_token_estimate"] for event in events)
        return {
            "days": days,
            "total_calls": total_calls,
            "total_input_tokens": total_input,
            "total_response_tokens": total_response,
            "avg_response_tokens": round(total_response / total_calls, 2) if total_calls else 0,
            "by_tool": by_tool,
            "warnings": warnings[:25],
            "estimate_method": ESTIMATE_METHOD,
            "caveat": "Engram estimates tokens it contributes; actual model billing requires client-reported usage.",
        }

    def _retrieved_text_tokens(self, output_payload: Any) -> int:
        if not isinstance(output_payload, dict):
            return 0
        chunks = output_payload.get("chunks", [])
        if not isinstance(chunks, list):
            return 0
        return sum(
            estimate_tokens(chunk.get("text", ""))
            for chunk in chunks
            if isinstance(chunk, dict)
        )

    def _warnings(self, response_tokens: int, retrieved_tokens: int, status: str) -> list[dict[str, Any]]:
        warnings: list[dict[str, Any]] = []
        if response_tokens >= HIGH_RESPONSE_TOKEN_WARNING:
            warnings.append({"kind": "high_response_tokens", "tokens": response_tokens})
        if status != "ok":
            warnings.append({"kind": "failed_call"})
        if response_tokens >= HIGH_RESPONSE_TOKEN_WARNING and retrieved_tokens == 0:
            warnings.append({"kind": "large_non_retrieval_response", "tokens": response_tokens})
        return warnings

    def _append_event(self, event: dict[str, Any]) -> None:
        USAGE_DIR.mkdir(parents=True, exist_ok=True)
        with TOOL_CALLS_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _read_events(self) -> list[dict[str, Any]]:
        if not TOOL_CALLS_PATH.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in TOOL_CALLS_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
        return events


usage_meter = UsageMeter()
