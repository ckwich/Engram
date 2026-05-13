"""Prompt-injection firewall classification for imported Memory OS evidence."""
from __future__ import annotations

from typing import Any

from core.memory_os._records import now_iso, stable_id, upsert_record
from core.memory_os.ledger import MemoryOSLedger

HOSTILE_PATTERNS = (
    "ignore previous instructions",
    "send me your secrets",
)


class MemoryFirewall:
    """Classify imported source text before it can influence agent guidance."""

    def __init__(self, ledger: MemoryOSLedger) -> None:
        self.ledger = ledger

    def classify_source(
        self,
        source_text: str,
        *,
        source_ref: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized = str(source_text or "").lower()
        matched = [pattern for pattern in HOSTILE_PATTERNS if pattern in normalized]
        decision = "quarantine" if matched else "allow"
        event = {
            "event_id": stable_id(
                "firewall",
                {
                    "source_text": source_text,
                    "source_ref": source_ref or {},
                    "matched_patterns": matched,
                },
            ),
            "decision": decision,
            "matched_patterns": matched,
            "evidence_allowed": True,
            "guidance_allowed": False,
            "source_ref": source_ref or {},
            "created_at": now_iso(),
        }
        upsert_record(self.ledger, "firewall_events", event["event_id"], event)
        return event
